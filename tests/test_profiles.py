"""Tests for the leaf module and the profiles it declares."""

import ast
import dataclasses
import inspect
import itertools
import re

import pytest

from converter import profiles
from converter.profiles import (
    AVIF,
    BMP,
    FLAC,
    GIF,
    JPG,
    LOSSY_CODECS,
    M4A,
    MKV,
    MOV,
    MP3,
    MP4,
    OGG,
    OPUS,
    PNG,
    PROFILES,
    SOURCE_SUFFIXES,
    TIFF,
    WAV,
    WEBM,
    WEBP,
    Attempt,
    Profile,
    StreamRule,
    flags,
    resolve_target,
)

#: ffmpeg's stream-specifier letters, as `docs/design/degradation-ladder.md` uses them.
#: Extend this when a profile introduces a selector form it does not list yet
#: (e.g. the capital-`V` "video minus attached pictures" specifier) -- an
#: unlisted letter is exactly what `mapped_types`'s own assertion below is for.
MAP_LETTERS = {"v": "video", "a": "audio", "s": "subtitle", "t": "attachment", "d": "data"}

#: Disposition qualifiers a "0:disp:<qualifier>?" selector can carry, mapped to
#: the rule key they resolve to -- the third selector kind
#: `docs/design/degradation-ladder.md` names: it carries a colon-separated
#: qualifier the way an index-named selector does, but behaves like a blind
#: one (measured, one such map carries *every* matching stream, not one).
#: Extend this the same way `MAP_LETTERS` is extended, when a profile
#: introduces another disposition selector. Only `attached_pic` exists today
#: (docs/specs/archive/spec-stream-disposition.md).
DISPOSITION_QUALIFIERS = {"attached_pic": "attached_pic"}

#: Every profile the registry ships. A new one joins the invariant checks here.
SHIPPED = [
    MP4,
    WAV,
    MKV,
    MOV,
    MP3,
    FLAC,
    WEBM,
    M4A,
    OGG,
    OPUS,
    PNG,
    JPG,
    TIFF,
    BMP,
    GIF,
    WEBP,
    AVIF,
]

#: Stream types each profile maps only to *force* the cheap attempt to fail when
#: the source carries one -- never to carry it on the success side. The narrowed
#: invariant (`docs/design/degradation-ladder.md`) exempts these from needing a
#: rule: a type mapped to force a failure never reaches the success-side check.
#: `mov` is THE motivating case for this exemption (issue #39): it maps
#: `attachment` via `-map 0:t?` -- MOV's muxer rejects any mapped attachment
#: outright -- but declares no `attachment` rule, since an attachment-bearing
#: source fails the cheap attempt and is routed into the ladder instead of
#: reaching the success-side check. Previously proven by a stand-in fixture,
#: `MOV_SHAPED`; retired now that the real profile proves it directly, the same
#: way `MP3_SHAPED` was retired by PR #53.
FORCED_FAILURE_TYPES: dict[str, frozenset[str]] = {
    MP4.name: frozenset(),
    WAV.name: frozenset(),
    MKV.name: frozenset(),
    MOV.name: frozenset({"attachment"}),
    MP3.name: frozenset(),
    FLAC.name: frozenset(),
    # WebM maps no attachment at all -- unlike MOV, it does not need the "map
    # to force a failure" trick, since it silently discards a mapped one
    # instead of rejecting it (measured, spec-video-formats.md). The type is
    # simply absent from mapped_types, so no exemption is needed here either.
    WEBM.name: frozenset(),
    M4A.name: frozenset(),
    OGG.name: frozenset(),
    OPUS.name: frozenset(),
    PNG.name: frozenset(),
    JPG.name: frozenset(),
    TIFF.name: frozenset(),
    BMP.name: frozenset(),
    GIF.name: frozenset(),
    WEBP.name: frozenset(),
    AVIF.name: frozenset(),
}

#: Stream types whose `stream_limit` is enforced by the container's own muxer
#: rather than by the cheap attempt's own selectors -- the mirror of
#: `FORCED_FAILURE_TYPES` for `stream_limit` instead of rule existence. A type
#: listed here is mapped *blindly* and still carries a limit, because a source
#: that would exceed it makes the cheap attempt itself fail. `mp3` and `flac`
#: are the profiles issue #40's narrowing was written for -- both map audio
#: blindly (`-map 0:a?`) yet declare `stream_limit=1`, because their own
#: muxers reject a second audio stream outright (measured against ffmpeg 9.0,
#: `docs/specs/archive/spec-audio-formats.md`): a source that would trip the limit
#: never reaches the success side at all; it fails the cheap attempt and lands
#: on the failure side, where the declared limit drives the selective rung's
#: own note instead.
MUXER_ENFORCED_LIMIT_TYPES: dict[str, frozenset[str]] = {
    MP4.name: frozenset(),
    WAV.name: frozenset(),
    MKV.name: frozenset(),
    MOV.name: frozenset(),
    MP3.name: frozenset({"audio"}),
    FLAC.name: frozenset({"audio"}),
    WEBM.name: frozenset(),
    # No entry: m4a, ogg and opus declare no stream_limit at all -- their
    # muxers hold several audio streams, so there is nothing for a muxer to
    # enforce here.
    M4A.name: frozenset(),
    OGG.name: frozenset(),
    OPUS.name: frozenset(),
    # image2's muxer refuses to write more than one frame -- or more than one
    # video stream -- to one output file, so a source that would trip the
    # limit never reaches the success side: it fails the cheap attempt outright
    # (spec-image-formats.md's muxer-facts table).
    PNG.name: frozenset({"video"}),
    JPG.name: frozenset({"video"}),
    TIFF.name: frozenset({"video"}),
    BMP.name: frozenset({"video"}),
    # gif, webp and avif self-police the same way: none of these muxers holds
    # more than one video *stream* (a second one -- cover art beside an
    # animation -- fails the cheap attempt outright), so a source that would
    # trip the limit never reaches the success side either. Orthogonal to how
    # many *frames* the one stream they do hold may carry -- gif and webp
    # write every frame, and neither carries a frame limit anywhere
    # (spec-image-formats.md).
    GIF.name: frozenset({"video"}),
    WEBP.name: frozenset({"video"}),
    AVIF.name: frozenset({"video"}),
}


def mapped_types(profile: Profile) -> dict[str, bool]:
    """Stream types the cheap attempt maps -> whether it maps them *blindly*.

    Reading the option list is the point here and forbidden in the engine: this
    check exists precisely to catch a profile whose declared mapping and declared
    rules disagree, which needs both readings side by side.
    """
    options = profile.cheap_attempt.options
    mapped: dict[str, bool] = {}
    for flag, value in itertools.pairwise(options):
        if flag != "-map":
            continue
        # A "-map" value this function cannot read (a bare index like "0:0", or
        # a negative exclusion like "-0:s") must fail loudly, not be skipped
        # silently -- a skip would let the invariant checks below pass over a
        # stream type they never actually looked at.
        assert value.startswith("0:"), f"{profile.label}: -map selector not recognised: {value!r}"
        selector = value[2:].removesuffix("?")
        letter = selector.split(":")[0]
        if letter == "disp":
            # "0:disp:attached_pic?" reads like an index-named selector -- it
            # carries a colon-separated qualifier -- but behaves like a blind
            # one (degradation-ladder.md's third selector kind), so it is
            # resolved by the qualifier rather than by MAP_LETTERS and always
            # recorded as blind.
            qualifier = selector.split(":", 1)[1] if ":" in selector else ""
            assert qualifier in DISPOSITION_QUALIFIERS, (
                f"{profile.label}: -map disposition selector not recognised: {value!r}"
            )
            mapped[DISPOSITION_QUALIFIERS[qualifier]] = True
            continue
        assert letter in MAP_LETTERS, f"{profile.label}: -map selector not recognised: {value!r}"
        # "0:a?" selects every audio stream; "0:a:0" names exactly one.
        mapped[MAP_LETTERS[letter]] = ":" not in selector
    return mapped


def named_index_counts(profile: Profile) -> dict[str, int]:
    """How many stream indices the cheap attempt names, per type.

    Counts occurrences, not distinct indices -- no shipped profile repeats one,
    and a repeat is itself a shape worth this helper noticing rather than
    silently collapsing. ``mapped_types`` collapses a type down to one
    blind/explicit bit; a ``stream_limit`` check needs the actual count, so a
    profile that names two indices of a type but declares a limit of one -- or
    the reverse -- is caught rather than passing because *some* index of that
    type was named. Left lenient about a selector it cannot read (unlike
    ``mapped_types``): every profile in ``INVARIANT_CASES`` is parametrized
    through both helpers in the same test class, so an unreadable ``-map``
    already fails loudly in ``mapped_types`` before this one is ever asked
    to make sense of it.
    """
    options = profile.cheap_attempt.options
    counts: dict[str, int] = {}
    for flag, value in itertools.pairwise(options):
        if flag != "-map" or not value.startswith("0:"):
            continue
        selector = value[2:].removesuffix("?")
        parts = selector.split(":")
        letter = parts[0]
        if letter == "disp":
            # A disposition selector carries a colon-separated qualifier but
            # is blind, not index-named (see mapped_types) -- skipped here so
            # it is never mistaken for a named index.
            continue
        if letter in MAP_LETTERS and len(parts) > 1:
            kind = MAP_LETTERS[letter]
            counts[kind] = counts.get(kind, 0) + 1
    return counts


#: Exactly `SHIPPED`: both exemptions are now proven by shipped profiles rather
#: than a stand-in -- `MP3` and `FLAC` prove the muxer-enforced `stream_limit`
#: exemption (`docs/specs/archive/spec-audio-formats.md`, which retired `MP3_SHAPED`),
#: and `MOV` now proves the force-failure exemption the same way, retiring
#: `MOV_SHAPED`.
INVARIANT_CASES = SHIPPED


@pytest.mark.parametrize("profile", INVARIANT_CASES, ids=lambda profile: profile.label)
class TestPartialMappingInvariant:
    """What `degradation-ladder.md` says a `partial_mapping` profile owes.

    The success-side verification reads the declared rules instead of the option
    list, which is sound only while the two agree. Checked per profile rather
    than left to review, because the profile that breaks it is by definition one
    nobody has written yet.
    """

    def test_every_successfully_carryable_type_the_cheap_attempt_maps_has_a_rule(self, profile):
        """Otherwise a stream the attempt faithfully copied is announced as lost.

        Narrowed form (issue #39): a type mapped only to *force* the cheap
        attempt to fail -- `mov`'s `attachment`, per `FORCED_FAILURE_TYPES` --
        never reaches the success side this check protects, so it is exempt.
        """
        forced_failure = FORCED_FAILURE_TYPES[profile.name]

        assert set(mapped_types(profile)) - forced_failure <= set(profile.rules)

    def test_no_rule_for_a_type_the_cheap_attempt_does_not_map(self, profile):
        """The mirrored direction (issue #40): a rule for a type the cheap
        attempt never maps is never exercised by ffmpeg, so `_structural_drop`
        (`converter/jobs.py`) finds the rule, sees no stream-limit trip, and
        treats the stream as accepted -- a stream that really was dropped then
        produces no note. Together with the test above, this pins the full
        equality `set(profile.rules) == set(mapped_types(profile))` (modulo the
        force-failure exemption, which only ever removes from the `mapped_types`
        side -- `test_forced_failure_types_carry_no_rule` below confirms it is
        never present on the `rules` side to begin with).
        """
        assert set(profile.rules) <= set(mapped_types(profile))

    def test_forced_failure_types_carry_no_rule(self, profile):
        """The exemption is for a type genuinely absent from `rules`, not a
        second way to satisfy the requirement -- otherwise `mov`-shaped would
        stop proving the distinction the moment someone added a belt-and-braces
        rule alongside it."""
        forced_failure = FORCED_FAILURE_TYPES[profile.name]

        assert forced_failure.isdisjoint(profile.rules)

    def test_no_blindly_mapped_type_carries_a_stream_limit(self, profile):
        """A blind selector maps every stream of its type, so a limit it does not
        enforce would have the verification report drops the output disproves.

        Only checked for a type that actually has a rule: a force-failure type
        by definition has none, and a limit on a rule that does not exist is not
        a thing that can be checked. `MUXER_ENFORCED_LIMIT_TYPES` is exempt for
        the opposite reason a force-failure type is exempt from the check above:
        the container's own muxer -- not the mapping -- is what turns a surplus
        stream into a failure, so the limit never needs the mapping to enforce it
        (`mp3`-shaped's `audio`, per `docs/design/degradation-ladder.md`).
        """
        muxer_enforced = MUXER_ENFORCED_LIMIT_TYPES[profile.name]
        blind = [
            kind
            for kind, is_blind in mapped_types(profile).items()
            if is_blind and kind in profile.rules and kind not in muxer_enforced
        ]

        assert all(profile.rules[kind].stream_limit is None for kind in blind)

    def test_muxer_enforced_limit_types_are_blindly_mapped_with_a_limit(self, profile):
        """The exemption above is for a type whose blind mapping is deliberately
        paired with a limit the container's own muxer enforces -- not a second
        way to skip the blind-type check -- so it only ever applies to a type
        that actually is blind and actually does carry a limit, the same
        discipline `test_forced_failure_types_carry_no_rule` holds the other
        exemption to.
        """
        muxer_enforced = MUXER_ENFORCED_LIMIT_TYPES[profile.name]
        mapped = mapped_types(profile)

        for kind in muxer_enforced:
            assert mapped.get(kind) is True
            assert profile.rules[kind].stream_limit is not None

    def test_stream_limit_matches_the_cheap_attempt_s_named_index_count(self, profile):
        """A limit belongs to a type the cheap attempt names by index, and
        must equal how many indices of that type are actually named -- WAV
        names one audio index and limits audio to 1. Pinning the count, not
        just that a limit exists, catches a profile that names two indices of
        a type but limits it to one, a limit with no named index behind it at
        all, or -- the mirror hole -- a named-index type with *no* limit, which
        would silently accept an unbounded number of that type's streams.
        `MUXER_ENFORCED_LIMIT_TYPES` is excluded: its limit is not backed by a
        named index at all, by construction.
        """
        muxer_enforced = MUXER_ENFORCED_LIMIT_TYPES[profile.name]
        counts = named_index_counts(profile)
        limited = {kind for kind, rule in profile.rules.items() if rule.stream_limit is not None}
        checked = (set(counts) | limited) - muxer_enforced

        for kind in checked:
            rule = profile.rules.get(kind)
            limit = rule.stream_limit if rule is not None else None
            assert limit == counts.get(kind, 0)


class TestLeafModule:
    def test_imports_nothing_from_converter(self):
        """The leaf property is checked, not trusted: parse the actual import
        statements (not the prose that happens to mention them) and assert none
        names ``converter``."""
        tree = ast.parse(inspect.getsource(profiles))
        imported_modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules.append(node.module)

        assert not any(
            name == "converter" or name.startswith("converter.") for name in imported_modules
        )


class TestFlags:
    def test_splits_a_command_line_shaped_string(self):
        assert flags("-c:v copy -c:a aac") == ("-c:v", "copy", "-c:a", "aac")

    def test_empty_spec_is_the_empty_tuple(self):
        assert flags("") == ()


class TestMp4Profile:
    def test_label_and_suffix(self):
        assert MP4.label == "MP4"
        assert MP4.target_suffix == ".mp4"

    def test_name_and_description(self):
        assert MP4.name == "mp4"
        assert MP4.description

    def test_container_options_carry_faststart_once(self):
        assert MP4.container_options == ("-movflags", "+faststart")

    def test_cheap_attempt_excludes_container_options(self):
        """The engine appends container options once; the declared attempt must
        not repeat them (Prior decisions, spec-profile-registry)."""
        assert MP4.cheap_attempt.label == "remux"
        assert "-movflags" not in MP4.cheap_attempt.options
        assert "+faststart" not in MP4.cheap_attempt.options

    def test_cheap_attempt_selects_streams_blindly(self):
        assert MP4.explicit_streams is False

    def test_cheap_attempt_is_declared_partial(self):
        """`-map 0:v? -map 0:a? -map 0:s?` selects no attachment and no data
        stream, so a source carrying one loses it without ffmpeg complaining."""
        assert MP4.partial_mapping is True

    def test_last_resort_excludes_container_options_too(self):
        assert MP4.last_resort is not None
        assert MP4.last_resort.label == "re-encode"
        assert "-movflags" not in MP4.last_resort.options

    def test_has_exactly_the_three_stream_rules(self):
        assert set(MP4.rules) == {"video", "audio", "subtitle"}

    def test_video_and_audio_rules_carry_the_position_placeholder(self):
        for stream_type in ("video", "audio"):
            rule = MP4.rules[stream_type]
            assert "{n}" in " ".join(rule.accept_options)
            assert rule.fallback_options is not None
            assert "{n}" in " ".join(rule.fallback_options)

    def test_subtitle_rule_transcodes_to_mov_text_and_has_no_fallback(self):
        rule = MP4.rules["subtitle"]

        assert rule.accept_options == ("-c:s:{n}", "mov_text")
        assert rule.fallback_options is None
        assert rule.drop_reason == "bitmap subtitles cannot be stored in MP4"

    def test_profile_is_byte_for_byte_unchanged_since_before_this_phase(self):
        """Guard rail for issue #30: `mkv`, `mov` and `webm` land in the same
        registry this phase, and `mp4` is the one profile every one of them
        could plausibly bump into (it is the source every other cheap-attempt
        docstring in `converter/profiles.py` contrasts itself against). The
        field-by-field tests above already pin most of `mp4`'s shape; this
        compares the *whole* frozen `Profile` at once, the same way
        `TestWavProfile.test_profile_is_byte_for_byte_unchanged_since_phase_2`
        guards `wav` against phase 3's siblings, so a change to any field --
        including one nobody wrote a dedicated assertion for -- fails here
        rather than shipping silently. The three copy masks are spelled out
        literally rather than imported (`WAV`'s snapshot precedent), because
        importing `MP4_VIDEO_CODECS` et al. and comparing them against
        themselves would make this assertion `X == X` for those three
        fields -- passing even if a codec were added to or removed from the
        real constant.
        """
        expected = Profile(
            label="MP4",
            name="mp4",
            description="Video: copies compatible streams, re-encodes the rest to h264/aac",
            target_suffix=".mp4",
            container_options=("-movflags", "+faststart"),
            cheap_attempt=Attempt(
                label="remux",
                options=(
                    "-map",
                    "0:v?",
                    "-map",
                    "0:a?",
                    "-map",
                    "0:s?",
                    "-c",
                    "copy",
                    "-c:s",
                    "mov_text",
                ),
            ),
            explicit_streams=False,
            partial_mapping=True,
            rules={
                "video": StreamRule(
                    copy_mask=frozenset(
                        {"h264", "hevc", "av1", "vp9", "mpeg4", "mpeg2video", "mjpeg"}
                    ),
                    accept_options=("-c:v:{n}", "copy"),
                    fallback_options=("-c:v:{n}", "libx264", "-crf:v:{n}", "18"),
                    fallback_name="h264",
                    stream_limit=None,
                    drop_reason=None,
                ),
                "audio": StreamRule(
                    copy_mask=frozenset({"aac", "mp3", "ac3", "eac3", "alac", "opus", "flac"}),
                    accept_options=("-c:a:{n}", "copy"),
                    fallback_options=("-c:a:{n}", "aac", "-b:a:{n}", "192k"),
                    fallback_name="aac",
                    stream_limit=None,
                    drop_reason=None,
                ),
                "subtitle": StreamRule(
                    copy_mask=frozenset(
                        {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}
                    ),
                    accept_options=("-c:s:{n}", "mov_text"),
                    fallback_options=None,
                    fallback_name=None,
                    stream_limit=None,
                    drop_reason="bitmap subtitles cannot be stored in MP4",
                ),
            },
            last_resort=Attempt(
                label="re-encode",
                options=(
                    "-map",
                    "0:v:0?",
                    "-map",
                    "0:a?",
                    "-c:v",
                    "libx264",
                    "-crf",
                    "18",
                    "-preset",
                    "medium",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                ),
                notes=(
                    "re-encoded to h264/aac (lossy); subtitles and extra video streams dropped",
                    "10-bit or HDR sources are reduced to 8-bit yuv420p for player compatibility",
                ),
            ),
        )
        assert expected == MP4


class TestWavProfile:
    def test_label_and_suffix(self):
        assert WAV.label == "WAV"
        assert WAV.target_suffix == ".wav"

    def test_name_and_description(self):
        assert WAV.name == "wav"
        assert WAV.description

    def test_no_container_options(self):
        assert WAV.container_options == ()

    def test_cheap_attempt_selects_streams_explicitly(self):
        assert WAV.explicit_streams is True
        assert WAV.cheap_attempt.options == ("-map", "0:a:0", "-c:a", "pcm_s16le")

    def test_cheap_attempt_is_declared_partial(self):
        """One index is named and nothing else is, so a second audio stream or
        an embedded cover image is left behind."""
        assert WAV.partial_mapping is True

    def test_declares_no_last_resort(self):
        assert WAV.last_resort is None

    def test_declares_only_an_audio_rule(self):
        assert set(WAV.rules) == {"audio"}

    def test_audio_rule_has_an_empty_copy_mask(self):
        assert WAV.rules["audio"].copy_mask == frozenset()

    def test_audio_rule_fallback_is_placeholder_free(self):
        rule = WAV.rules["audio"]

        assert rule.fallback_options == ("-c:a", "pcm_s16le")
        assert "{n}" not in " ".join(rule.fallback_options)
        assert "{n}" not in " ".join(rule.accept_options)

    def test_audio_rule_fallback_carries_no_re_encode_note(self):
        """Decoding to PCM is the point of WAV, not a loss."""
        assert WAV.rules["audio"].fallback_name is None

    def test_audio_rule_stream_limit_is_one(self):
        assert WAV.rules["audio"].stream_limit == 1

    def test_profile_is_byte_for_byte_unchanged_since_phase_2(self):
        """Guard rail for issue #23: the audio-formats phase's Outcome promises
        `wav` "behaves exactly as it does after phase 2" while five sibling
        profiles land around it in the same registry. The field-by-field tests
        above already pin most of this; this test compares the *whole* frozen
        `Profile` at once, so a change to any field -- including one nobody
        wrote a dedicated assertion for -- fails here. Notably: the gate
        (`docs/specs/archive/spec-audio-formats.md`) deliberately did NOT extend the
        five siblings' standing non-audio note to `wav`, to keep this exact
        promise; a well-intentioned "consistency" edit adding one would trip
        this test immediately.
        """
        expected = Profile(
            label="WAV",
            name="wav",
            description="Audio: single stream, uncompressed 16-bit PCM",
            target_suffix=".wav",
            container_options=(),
            cheap_attempt=Attempt(
                label="pcm_s16le", options=("-map", "0:a:0", "-c:a", "pcm_s16le")
            ),
            explicit_streams=True,
            partial_mapping=True,
            rules={
                "audio": StreamRule(
                    copy_mask=frozenset(),
                    accept_options=(),
                    fallback_options=("-c:a", "pcm_s16le"),
                    fallback_name=None,
                    stream_limit=1,
                    drop_reason=None,
                ),
            },
            last_resort=None,
        )
        assert expected == WAV


class TestMkvProfile:
    def test_label_and_suffix(self):
        assert MKV.label == "MKV"
        assert MKV.target_suffix == ".mkv"

    def test_name_and_description(self):
        assert MKV.name == "mkv"
        assert MKV.description

    def test_no_container_options(self):
        """Measured: +faststart is MP4/MOV furniture MKV's muxer ignores, so
        declaring it here would be noise (Prior decisions, spec-video-formats)."""
        assert MKV.container_options == ()

    def test_cheap_attempt_selects_streams_blindly(self):
        assert MKV.explicit_streams is False

    def test_cheap_attempt_maps_every_stream_type_including_attachments(self):
        assert MKV.cheap_attempt.options == (
            "-map",
            "0:v?",
            "-map",
            "0:a?",
            "-map",
            "0:s?",
            "-map",
            "0:t?",
            "-c",
            "copy",
        )

    def test_cheap_attempt_is_declared_partial(self):
        """No "v/a/s/t" map carries a data or timecode stream (measured), so a
        source with either loses it without ffmpeg ever complaining."""
        assert MKV.partial_mapping is True

    def test_cheap_attempt_carries_no_standing_note(self):
        """Issue #67: the standing note is retired -- `jobs.verify_success`
        already names a real data or timecode drop per stream, and MKV's
        muxer never regenerates one from source metadata (measured), unlike
        MOV/MP4's `tmcd`. See `tests/test_argv.py::TestConfirmDrops` for the
        per-stream proof."""
        assert MKV.cheap_attempt.notes == ()

    def test_last_resort_excludes_container_options(self):
        assert MKV.last_resort is not None
        assert MKV.last_resort.label == "re-encode"
        assert "-movflags" not in MKV.last_resort.options

    def test_has_exactly_the_four_stream_rules(self):
        assert set(MKV.rules) == {"video", "audio", "subtitle", "attachment"}

    def test_video_and_audio_rules_carry_the_position_placeholder(self):
        for stream_type in ("video", "audio"):
            rule = MKV.rules[stream_type]
            assert "{n}" in " ".join(rule.accept_options)
            assert rule.fallback_options is not None
            assert "{n}" in " ".join(rule.fallback_options)

    def test_subtitle_rule_copies_in_kind_and_falls_back_to_srt(self):
        """Matroska rejects a literal mov_text copy (measured), so mov_text is
        absent from the copy mask and falls to the srt re-encode instead."""
        rule = MKV.rules["subtitle"]

        assert "mov_text" not in rule.copy_mask
        assert rule.accept_options == ("-c:s:{n}", "copy")
        assert rule.fallback_options == ("-c:s:{n}", "srt")
        assert rule.fallback_name == "subrip"

    def test_subtitle_mask_holds_bitmap_subtitles_too(self):
        """Unlike MP4's text-only mask -- Matroska is the only container in
        this phase that holds bitmap subtitles as a literal copy."""
        rule = MKV.rules["subtitle"]

        assert {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle"} <= rule.copy_mask

    def test_attachment_rule_accepts_every_codec_name(self):
        """ffprobe reports a font/ttf or font/otf attachment's codec_name as
        "unknown", so a mask enumerating font codec names would drop exactly
        the fonts it meant to keep (measured, spec-video-formats.md)."""
        rule = MKV.rules["attachment"]

        assert "unknown" in rule.copy_mask
        assert "ttf" in rule.copy_mask
        assert len(rule.copy_mask) == 0

    def test_attachment_rule_copies_unconditionally_with_no_fallback(self):
        rule = MKV.rules["attachment"]

        assert rule.accept_options == ("-c:t:{n}", "copy")
        assert rule.fallback_options is None
        assert rule.stream_limit is None


class TestMovProfile:
    """Pins the shape Acceptance fixes for `mov` (issue #28,
    `docs/specs/archive/spec-video-formats.md`)."""

    def test_label_and_suffix(self):
        assert MOV.label == "MOV"
        assert MOV.target_suffix == ".mov"

    def test_name_and_description(self):
        assert MOV.name == "mov"
        assert MOV.description

    def test_container_options_carry_faststart_once(self):
        assert MOV.container_options == ("-movflags", "+faststart")

    def test_cheap_attempt_selects_streams_blindly(self):
        assert MOV.explicit_streams is False

    def test_cheap_attempt_maps_every_stream_type_including_attachments(self):
        """`0:t?` is mapped deliberately: MOV rejects a mapped attachment, so
        an attachment-bearing source fails into the ladder instead of being
        carried (Acceptance, spec-video-formats.md)."""
        assert MOV.cheap_attempt.options == (
            "-map",
            "0:v?",
            "-map",
            "0:a?",
            "-map",
            "0:s?",
            "-map",
            "0:t?",
            "-c",
            "copy",
            "-c:s",
            "mov_text",
        )

    def test_cheap_attempt_is_declared_partial(self):
        assert MOV.partial_mapping is True

    def test_cheap_attempt_carries_no_standing_note(self):
        """MOV's muxer regenerates a `tmcd` timecode track from source metadata
        even though no selector maps it, so a standing note here would have
        been measurably false (issue #66) -- unlike MKV's and WebM's own
        retired notes (issue #67), which needed no such exemption since
        neither muxer regenerates one. The per-file success-side verification
        reads the written output and names a real data drop itself, so
        nothing is lost by dropping the blanket claim."""
        assert MOV.cheap_attempt.notes == ()

    def test_last_resort_excludes_container_options(self):
        assert MOV.last_resort is not None
        assert MOV.last_resort.label == "re-encode"
        assert "-movflags" not in MOV.last_resort.options

    def test_has_exactly_the_three_stream_rules(self):
        """No `attachment` rule: mapping `0:t?` only ever forces a failure,
        never carries one on the success side (FORCED_FAILURE_TYPES above)."""
        assert set(MOV.rules) == {"video", "audio", "subtitle"}

    def test_video_and_audio_rules_carry_the_position_placeholder(self):
        for stream_type in ("video", "audio"):
            rule = MOV.rules[stream_type]
            assert "{n}" in " ".join(rule.accept_options)
            assert rule.fallback_options is not None
            assert "{n}" in " ".join(rule.fallback_options)

    def test_video_mask_excludes_vp9_and_av1_unlike_mp4(self):
        """The likeliest copy-paste mistake in the phase (Acceptance,
        spec-video-formats.md): MOV rejects vp9, av1 *and* vp8, while MP4
        accepts vp9 and av1."""
        assert "vp9" not in MOV.rules["video"].copy_mask
        assert "av1" not in MOV.rules["video"].copy_mask
        assert "vp8" not in MOV.rules["video"].copy_mask
        assert "vp9" in MP4.rules["video"].copy_mask
        assert "av1" in MP4.rules["video"].copy_mask

    def test_video_mask_includes_ffv1_and_theora(self):
        assert {"ffv1", "theora"} <= MOV.rules["video"].copy_mask

    def test_audio_mask_includes_dts_and_pcm_s16le(self):
        assert {"dts", "pcm_s16le"} <= MOV.rules["audio"].copy_mask

    def test_subtitle_rule_transcodes_to_mov_text_and_has_no_fallback(self):
        rule = MOV.rules["subtitle"]

        assert rule.accept_options == ("-c:s:{n}", "mov_text")
        assert rule.fallback_options is None
        assert rule.drop_reason == "bitmap subtitles cannot be stored in MOV"


class TestWebmProfile:
    """Pins the shape Acceptance fixes for `webm` (issue #29,
    `docs/specs/archive/spec-video-formats.md`)."""

    def test_label_and_suffix(self):
        assert WEBM.label == "WebM"
        assert WEBM.target_suffix == ".webm"

    def test_name_and_description(self):
        assert WEBM.name == "webm"
        assert WEBM.description

    def test_no_container_options(self):
        assert WEBM.container_options == ()

    def test_cheap_attempt_selects_streams_blindly(self):
        assert WEBM.explicit_streams is False

    def test_cheap_attempt_maps_no_attachment(self):
        """Unlike `mkv` and `mov`, `webm` never maps `0:t?`: WebM does not
        reject a mapped attachment, it silently discards it at exit 0
        (measured), so mapping it would buy nothing (Acceptance,
        spec-video-formats.md)."""
        assert WEBM.cheap_attempt.options == (
            "-map",
            "0:v?",
            "-map",
            "0:a?",
            "-map",
            "0:s?",
            "-c",
            "copy",
            "-c:s",
            "webvtt",
        )

    def test_cheap_attempt_is_declared_partial(self):
        assert WEBM.partial_mapping is True

    def test_cheap_attempt_carries_no_standing_note(self):
        """Issue #67: the standing note is retired -- `jobs.verify_success`
        already names a real attachment, data or timecode drop per stream
        (WebM declares neither rule), and WebM's muxer regenerates nothing
        from source metadata (measured). See
        `tests/test_argv.py::TestWebmDegradationNotes` for the per-stream
        proof."""
        assert WEBM.cheap_attempt.notes == ()

    def test_last_resort_excludes_container_options(self):
        assert WEBM.last_resort is not None
        assert WEBM.last_resort.label == "re-encode"
        assert "-movflags" not in WEBM.last_resort.options

    def test_has_exactly_the_three_stream_rules(self):
        """No `attachment` rule: the cheap attempt never maps one at all, so
        the type is simply absent from both sides of the equality."""
        assert set(WEBM.rules) == {"video", "audio", "subtitle"}

    def test_video_and_audio_rules_carry_the_position_placeholder(self):
        for stream_type in ("video", "audio"):
            rule = WEBM.rules[stream_type]
            assert "{n}" in " ".join(rule.accept_options)
            assert rule.fallback_options is not None
            assert "{n}" in " ".join(rule.fallback_options)

    def test_video_mask_is_vp8_vp9_av1_only(self):
        assert WEBM.rules["video"].copy_mask == {"vp8", "vp9", "av1"}

    def test_audio_mask_is_opus_vorbis_only(self):
        assert WEBM.rules["audio"].copy_mask == {"opus", "vorbis"}

    def test_video_fallback_is_vp9_quality_targeted(self):
        """VP9 needs both `-crf` and `-b:v 0` to mean quality-targeted mode;
        `-crf` alone leaves it constrained-quality (measured, the spec's "one
        open decision")."""
        rule = WEBM.rules["video"]

        assert rule.accept_options == ("-c:v:{n}", "copy")
        assert rule.fallback_options == (
            "-c:v:{n}",
            "libvpx-vp9",
            "-crf:v:{n}",
            "32",
            "-b:v:{n}",
            "0",
            "-row-mt",
            "1",
            "-cpu-used",
            "4",
        )
        assert rule.fallback_name == "vp9"

    def test_audio_fallback_is_opus(self):
        rule = WEBM.rules["audio"]

        assert rule.fallback_options == ("-c:a:{n}", "libopus", "-b:a:{n}", "128k")
        assert rule.fallback_name == "opus"

    def test_subtitle_rule_transcodes_to_webvtt_and_has_no_fallback(self):
        rule = WEBM.rules["subtitle"]

        assert rule.accept_options == ("-c:s:{n}", "webvtt")
        assert rule.fallback_options is None
        assert rule.drop_reason == "bitmap subtitles cannot be stored in WebM"

    def test_declares_the_pinned_last_resort(self):
        assert WEBM.last_resort is not None
        assert WEBM.last_resort.options == (
            "-map",
            "0:v:0?",
            "-map",
            "0:a?",
            "-c:v",
            "libvpx-vp9",
            "-crf",
            "32",
            "-b:v",
            "0",
            "-row-mt",
            "1",
            "-cpu-used",
            "4",
            "-c:a",
            "libopus",
            "-b:a",
            "128k",
        )
        assert WEBM.last_resort.notes == (
            "re-encoded to vp9/opus (lossy); subtitles and extra video streams dropped",
        )


class TestMp3Profile:
    """Pins the shape Acceptance fixes for `mp3` (issue #21,
    `docs/specs/archive/spec-audio-formats.md`)."""

    def test_label_and_suffix(self):
        assert MP3.label == "MP3"
        assert MP3.target_suffix == ".mp3"

    def test_name_and_description(self):
        assert MP3.name == "mp3"
        assert MP3.description

    def test_no_container_options(self):
        assert MP3.container_options == ()

    def test_cheap_attempt_maps_audio_and_attached_pictures_blindly(self):
        """Issue #77, `docs/specs/archive/spec-stream-disposition.md`:
        `-map 0:disp:attached_pic?` maps an embedded cover picture and nothing
        else -- measured, it never matches a real video stream. `-c copy`
        replaces `-c:a copy` deliberately: with no codec option covering the
        picture, ffmpeg would re-encode it to the muxer's default instead of
        copying it, an undeclared loss the mask would hide."""
        assert MP3.explicit_streams is False
        assert MP3.cheap_attempt.options == (
            "-map",
            "0:a?",
            "-map",
            "0:disp:attached_pic?",
            "-c",
            "copy",
        )

    def test_cheap_attempt_carries_no_standing_note(self):
        """Issue #78: the standing note is retired -- `jobs.verify_success`
        already names every dropped stream per stream, and the blanket line
        had gone false for cover art specifically once #77 started carrying
        it. See `tests/test_argv.py::TestMp3Job` for the per-stream proof."""
        assert MP3.cheap_attempt.notes == ()

    def test_cheap_attempt_is_declared_partial(self):
        assert MP3.partial_mapping is True

    def test_declares_an_audio_rule_and_an_attached_pic_rule(self):
        assert set(MP3.rules) == {"audio", "attached_pic"}

    def test_audio_rule_mask_and_fallback(self):
        rule = MP3.rules["audio"]

        assert rule.copy_mask == frozenset({"mp3"})
        assert rule.accept_options == ("-c:a", "copy")
        assert rule.fallback_options == ("-c:a", "libmp3lame", "-q:a", "2")
        assert rule.fallback_name == "mp3"

    def test_audio_rule_stream_limit_is_one(self):
        """The mp3 muxer, not this mapping, enforces it -- the muxer-enforced
        `stream_limit` exemption `docs/design/degradation-ladder.md` names."""
        assert MP3.rules["audio"].stream_limit == 1

    def test_attached_pic_rule_accepts_any_codec_with_no_stream_limit(self):
        """Accept-anything mask, the same mechanism MKV's attachment rule
        uses: the decision resting on this rule is the disposition, not the
        codec. No `stream_limit`: one `-map 0:disp:attached_pic?` carries
        *every* picture a source holds (measured), so a limit of 1 would
        report a carried picture as dropped (Prior decisions,
        spec-stream-disposition.md)."""
        rule = MP3.rules["attached_pic"]

        assert "png" in rule.copy_mask
        assert "mjpeg" in rule.copy_mask
        assert len(rule.copy_mask) == 0
        assert rule.accept_options == ("-c:v:{n}", "copy")
        assert rule.fallback_options is None
        assert rule.stream_limit is None

    def test_declares_the_pinned_last_resort(self):
        assert MP3.last_resort is not None
        assert MP3.last_resort.options == ("-map", "0:a:0", "-c:a", "libmp3lame", "-q:a", "2")


class TestFlacProfile:
    """Pins the shape Acceptance fixes for `flac` (issue #21,
    `docs/specs/archive/spec-audio-formats.md`)."""

    def test_label_and_suffix(self):
        assert FLAC.label == "FLAC"
        assert FLAC.target_suffix == ".flac"

    def test_name_and_description(self):
        assert FLAC.name == "flac"
        assert FLAC.description

    def test_no_container_options(self):
        assert FLAC.container_options == ()

    def test_cheap_attempt_maps_audio_and_attached_pictures_blindly(self):
        """Same disposition addition as MP3's -- see its comment."""
        assert FLAC.explicit_streams is False
        assert FLAC.cheap_attempt.options == (
            "-map",
            "0:a?",
            "-map",
            "0:disp:attached_pic?",
            "-c",
            "copy",
        )

    def test_cheap_attempt_carries_no_standing_note(self):
        """Issue #78 -- see `TestMp3Profile`'s equivalent for why."""
        assert FLAC.cheap_attempt.notes == ()

    def test_cheap_attempt_is_declared_partial(self):
        assert FLAC.partial_mapping is True

    def test_declares_an_audio_rule_and_an_attached_pic_rule(self):
        assert set(FLAC.rules) == {"audio", "attached_pic"}

    def test_audio_rule_mask_and_fallback(self):
        rule = FLAC.rules["audio"]

        assert rule.copy_mask == frozenset({"flac"})
        assert rule.accept_options == ("-c:a", "copy")
        assert rule.fallback_options == ("-c:a", "flac")

    def test_audio_rule_fallback_carries_no_re_encode_note(self):
        """Encoding into a container's own lossless codec gives up nothing,
        the same rule WAV's PCM fallback carries."""
        assert FLAC.rules["audio"].fallback_name is None

    def test_audio_rule_stream_limit_is_one(self):
        """The flac muxer, not this mapping, enforces it, same as mp3's."""
        assert FLAC.rules["audio"].stream_limit == 1

    def test_attached_pic_rule_accepts_any_codec_with_no_stream_limit(self):
        """Same accept-anything shape as MP3's -- see its comment."""
        rule = FLAC.rules["attached_pic"]

        assert "png" in rule.copy_mask
        assert "mjpeg" in rule.copy_mask
        assert len(rule.copy_mask) == 0
        assert rule.accept_options == ("-c:v:{n}", "copy")
        assert rule.fallback_options is None
        assert rule.stream_limit is None

    def test_declares_the_pinned_last_resort(self):
        assert FLAC.last_resort is not None
        assert FLAC.last_resort.options == ("-map", "0:a:0", "-c:a", "flac")


class TestM4aProfile:
    """Pins the shape Acceptance fixes for `m4a` (issue #22,
    `docs/specs/archive/spec-audio-formats.md`)."""

    def test_label_and_suffix(self):
        assert M4A.label == "M4A"
        assert M4A.target_suffix == ".m4a"

    def test_name_and_description(self):
        assert M4A.name == "m4a"
        assert M4A.description

    def test_no_container_options(self):
        assert M4A.container_options == ()

    def test_cheap_attempt_maps_audio_and_attached_pictures_blindly(self):
        """Same disposition addition as MP3's, and the same reason
        "-c:a copy" becomes "-c copy" -- trap 1 in
        `docs/specs/archive/spec-stream-disposition.md`. Measured, this one matters
        most: the ipod muxer's *default* video encoder is h264, which ipod
        then rejects, so leaving "-c:a copy" in place would fail every
        artwork-bearing `--to m4a` at rung 1 rather than silently
        mis-encoding as mp3/flac would."""
        assert M4A.explicit_streams is False
        assert M4A.cheap_attempt.options == (
            "-map",
            "0:a?",
            "-map",
            "0:disp:attached_pic?",
            "-c",
            "copy",
        )

    def test_cheap_attempt_carries_no_standing_note(self):
        """Issue #78 -- see `TestMp3Profile`'s equivalent for why."""
        assert M4A.cheap_attempt.notes == ()

    def test_cheap_attempt_is_declared_partial(self):
        assert M4A.partial_mapping is True

    def test_declares_an_audio_rule_and_an_attached_pic_rule(self):
        assert set(M4A.rules) == {"audio", "attached_pic"}

    def test_attached_pic_rule_accepts_any_codec_with_no_stream_limit(self):
        """Same accept-anything shape as MP3's -- see its comment."""
        rule = M4A.rules["attached_pic"]

        assert "png" in rule.copy_mask
        assert "mjpeg" in rule.copy_mask
        assert len(rule.copy_mask) == 0
        assert rule.accept_options == ("-c:v:{n}", "copy")
        assert rule.fallback_options is None
        assert rule.stream_limit is None

    def test_audio_rule_mask_and_fallback(self):
        """The mask is `{aac, alac}`, not `MP4_AUDIO_CODECS`: `.m4a` selects
        the narrower `ipod` muxer, which rejects mp3, opus and flac stream
        copies (docs/specs/archive/spec-audio-formats.md)."""
        rule = M4A.rules["audio"]

        assert rule.copy_mask == frozenset({"aac", "alac"})
        assert rule.accept_options == ("-c:a:{n}", "copy")
        assert rule.fallback_options == ("-c:a:{n}", "aac", "-b:a:{n}", "192k")
        assert rule.fallback_name == "aac"

    def test_audio_rule_declares_no_stream_limit(self):
        """The ipod muxer holds several audio streams, so every one the
        source has is carried rather than one kept and the rest dropped."""
        assert M4A.rules["audio"].stream_limit is None

    def test_audio_rule_carries_the_position_placeholder(self):
        """No stream_limit means more than one output audio stream is
        possible, and ffmpeg's unindexed "-c:a" is not positional -- the last
        one given wins for every audio stream, not one per stream in map
        order (measured against ffmpeg 9.0). The placeholder is required for
        the same reason MP4's video/audio rules carry one."""
        rule = M4A.rules["audio"]

        assert "{n}" in " ".join(rule.accept_options)
        assert "{n}" in " ".join(rule.fallback_options)

    def test_declares_the_pinned_last_resort(self):
        assert M4A.last_resort is not None
        assert M4A.last_resort.options == ("-map", "0:a:0", "-c:a", "aac", "-b:a", "192k")


class TestOggProfile:
    """Pins the shape Acceptance fixes for `ogg` (issue #22,
    `docs/specs/archive/spec-audio-formats.md`)."""

    def test_label_and_suffix(self):
        assert OGG.label == "OGG"
        assert OGG.target_suffix == ".ogg"

    def test_name_and_description(self):
        assert OGG.name == "ogg"
        assert OGG.description

    def test_no_container_options(self):
        assert OGG.container_options == ()

    def test_cheap_attempt_maps_audio_blindly(self):
        """ "-c copy", not "-c:a copy": the spec pins this exact spelling
        (docs/specs/archive/spec-audio-formats.md's fixed-profiles table)."""
        assert OGG.explicit_streams is False
        assert OGG.cheap_attempt.options == ("-map", "0:a?", "-c", "copy")

    def test_cheap_attempt_carries_no_standing_note(self):
        """Issue #78: ogg gains no artwork rule, so this note's claim was
        never about a false statement -- it was pure duplication of the
        per-stream drop `jobs.verify_success` already names for any non-audio
        stream, cover art included. See `tests/test_argv.py::TestOggJob`."""
        assert OGG.cheap_attempt.notes == ()

    def test_cheap_attempt_is_declared_partial(self):
        assert OGG.partial_mapping is True

    def test_declares_only_an_audio_rule(self):
        assert set(OGG.rules) == {"audio"}

    def test_audio_rule_mask_and_fallback(self):
        rule = OGG.rules["audio"]

        assert rule.copy_mask == frozenset({"vorbis", "opus", "flac"})
        assert rule.accept_options == ("-c:a:{n}", "copy")
        assert rule.fallback_options == ("-c:a:{n}", "libvorbis", "-q:a:{n}", "5")
        assert rule.fallback_name == "vorbis"

    def test_audio_rule_declares_no_stream_limit(self):
        assert OGG.rules["audio"].stream_limit is None

    def test_audio_rule_carries_the_position_placeholder(self):
        """See `TestM4aProfile`'s equivalent test for why."""
        rule = OGG.rules["audio"]

        assert "{n}" in " ".join(rule.accept_options)
        assert "{n}" in " ".join(rule.fallback_options)

    def test_declares_the_pinned_last_resort(self):
        assert OGG.last_resort is not None
        assert OGG.last_resort.options == ("-map", "0:a:0", "-c:a", "libvorbis", "-q:a", "5")


class TestOpusProfile:
    """Pins the shape Acceptance fixes for `opus` (issue #22,
    `docs/specs/archive/spec-audio-formats.md`)."""

    def test_label_and_suffix(self):
        assert OPUS.label == "OPUS"
        assert OPUS.target_suffix == ".opus"

    def test_name_and_description(self):
        assert OPUS.name == "opus"
        assert OPUS.description

    def test_no_container_options(self):
        assert OPUS.container_options == ()

    def test_cheap_attempt_maps_audio_blindly(self):
        """ "-c copy", like ogg's: the muxer, not the mask, decides the happy
        path (Prior decisions, spec-audio-formats.md)."""
        assert OPUS.explicit_streams is False
        assert OPUS.cheap_attempt.options == ("-map", "0:a?", "-c", "copy")

    def test_cheap_attempt_carries_no_standing_note(self):
        """Issue #78 -- see `TestOggProfile`'s equivalent for why."""
        assert OPUS.cheap_attempt.notes == ()

    def test_cheap_attempt_is_declared_partial(self):
        assert OPUS.partial_mapping is True

    def test_declares_only_an_audio_rule(self):
        assert set(OPUS.rules) == {"audio"}

    def test_audio_rule_mask_and_fallback(self):
        rule = OPUS.rules["audio"]

        assert rule.copy_mask == frozenset({"opus"})
        assert rule.accept_options == ("-c:a:{n}", "copy")
        assert rule.fallback_options == ("-c:a:{n}", "libopus", "-b:a:{n}", "128k")
        assert rule.fallback_name == "opus"

    def test_audio_rule_declares_no_stream_limit(self):
        """The opus muxer holds several audio streams, by copy and by
        encode (docs/specs/archive/spec-audio-formats.md)."""
        assert OPUS.rules["audio"].stream_limit is None

    def test_audio_rule_carries_the_position_placeholder(self):
        """See `TestM4aProfile`'s equivalent test for why."""
        rule = OPUS.rules["audio"]

        assert "{n}" in " ".join(rule.accept_options)
        assert "{n}" in " ".join(rule.fallback_options)

    def test_declares_the_pinned_last_resort(self):
        assert OPUS.last_resort is not None
        assert OPUS.last_resort.options == ("-map", "0:a:0", "-c:a", "libopus", "-b:a", "128k")


#: The five audio profiles a cheap-attempt standing note used to sit on
#: (Acceptance, issue #78, docs/specs/archive/spec-stream-disposition.md). `wav` is
#: deliberately absent: it carries none, so there is nothing for it to retire.
AUDIO_PROFILES_WITH_A_RETIRED_NOTE = [MP3, FLAC, M4A, OGG, OPUS]

#: Each profile's `last_resort.notes`, exactly as declared before this issue --
#: unchanged, since that rung maps `-map 0:a:0` explicitly and is never
#: verified (Out of scope, docs/specs/archive/spec-stream-disposition.md: "`last_resort`
#: notes ... the only place that information exists").
_LAST_RESORT_NOTES = {
    MP3.name: (
        "non-audio streams, and any audio stream beyond the first, are not carried into MP3",
    ),
    FLAC.name: (
        "non-audio streams, and any audio stream beyond the first, are not carried into FLAC",
    ),
    M4A.name: (
        "non-audio streams, and any audio stream beyond the first, are not carried into M4A",
    ),
    OGG.name: (
        "non-audio streams, and any audio stream beyond the first, are not carried into OGG",
    ),
    OPUS.name: (
        "non-audio streams, and any audio stream beyond the first, are not carried into OPUS",
    ),
}


class TestStandingNoteRetirement:
    """Issue #78: the cheap-attempt standing note is gone from every audio
    profile that used to carry one, and `last_resort` -- never verified, so
    its note is the only place that information exists -- is untouched."""

    @pytest.mark.parametrize(
        "profile", AUDIO_PROFILES_WITH_A_RETIRED_NOTE, ids=lambda profile: profile.label
    )
    def test_no_audio_profile_carries_a_cheap_attempt_standing_note(self, profile):
        assert profile.cheap_attempt.notes == ()

    def test_wav_never_carried_one_either(self):
        """The sixth audio profile, named explicitly since it is absent from
        `AUDIO_PROFILES_WITH_A_RETIRED_NOTE` above -- nothing to retire."""
        assert WAV.cheap_attempt.notes == ()

    @pytest.mark.parametrize(
        "profile", AUDIO_PROFILES_WITH_A_RETIRED_NOTE, ids=lambda profile: profile.label
    )
    def test_last_resort_notes_are_unchanged(self, profile):
        assert profile.last_resort is not None
        assert profile.last_resort.notes == _LAST_RESORT_NOTES[profile.name]


#: The video containers whose cheap-attempt standing note is retired by issue
#: #67 -- `mkv` and `webm`. `mov` is deliberately absent: it lost its own
#: standing note earlier, to issue #66's finding that its muxer's `tmcd`
#: regeneration made the blanket claim measurably false, so it has nothing
#: left for this issue to retire.
VIDEO_PROFILES_WITH_A_RETIRED_STANDING_NOTE = [MKV, WEBM]

#: Each video container's `last_resort.notes`, exactly as declared before this
#: issue -- unchanged, since that rung is never verified (the same "only place
#: that information exists" reasoning `_LAST_RESORT_NOTES` above records for
#: the audio profiles).
_VIDEO_LAST_RESORT_NOTES = {
    MKV.name: (
        "re-encoded to h264/aac (lossy); subtitles and extra video streams dropped",
        "10-bit or HDR sources are reduced to 8-bit yuv420p for player compatibility",
    ),
    MOV.name: (
        "re-encoded to h264/aac (lossy); subtitles and extra video streams dropped",
        "10-bit or HDR sources are reduced to 8-bit yuv420p for player compatibility",
    ),
    WEBM.name: ("re-encoded to vp9/opus (lossy); subtitles and extra video streams dropped",),
}


class TestVideoStandingNoteRetirement:
    """Issue #67: the cheap-attempt standing note is gone from every video
    container profile that used to carry one, `mov` never carried one for this
    issue to retire, and `last_resort` -- never verified, so its note is the
    only place that information exists -- is untouched on all three. A guard
    against a future profile quietly re-introducing one, the same shape #78's
    `TestStandingNoteRetirement` above already established for the audio
    profiles."""

    @pytest.mark.parametrize(
        "profile", VIDEO_PROFILES_WITH_A_RETIRED_STANDING_NOTE, ids=lambda profile: profile.label
    )
    def test_no_video_profile_carries_a_cheap_attempt_standing_note(self, profile):
        assert profile.cheap_attempt.notes == ()

    def test_mov_never_carried_one_either(self):
        """The third video container, named explicitly since it is absent from
        `VIDEO_PROFILES_WITH_A_RETIRED_STANDING_NOTE` above -- nothing for
        this issue to retire (issue #66 already removed it)."""
        assert MOV.cheap_attempt.notes == ()

    @pytest.mark.parametrize("profile", [MKV, MOV, WEBM], ids=lambda profile: profile.label)
    def test_last_resort_notes_are_unchanged(self, profile):
        assert profile.last_resort is not None
        assert profile.last_resort.notes == _VIDEO_LAST_RESORT_NOTES[profile.name]


#: One tuple per image2 profile this phase adds: the profile itself, the codec
#: name its own encoder produces (so a copy-mask hit can be constructed), and
#: whether its lossless re-encode carries a note (Verification,
#: spec-image-formats.md: only `jpg`'s does).
IMAGE2_CASES = [
    (PNG, "png", False),
    (JPG, "mjpeg", True),
    (TIFF, "tiff", False),
    (BMP, "bmp", False),
]


@pytest.mark.parametrize(
    "profile,own_codec,has_reencode_name", IMAGE2_CASES, ids=lambda v: getattr(v, "label", v)
)
class TestImage2Profiles:
    """Shared shape of the four image2 targets: png, jpg, tiff, bmp all force
    their encoder in the cheap attempt, so a stream copy never ships a
    mislabelled file (spec-image-formats.md's muxer-facts table)."""

    def test_cheap_attempt_forces_the_encoder_and_maps_video_blindly(
        self, profile, own_codec, has_reencode_name
    ):
        assert profile.cheap_attempt.options[:2] == ("-map", "0:v?")
        assert "-c:v" in profile.cheap_attempt.options
        assert "copy" not in profile.cheap_attempt.options

    def test_cheap_attempt_selects_streams_blindly(self, profile, own_codec, has_reencode_name):
        assert profile.explicit_streams is False

    def test_cheap_attempt_is_declared_partial(self, profile, own_codec, has_reencode_name):
        assert profile.partial_mapping is True

    def test_has_exactly_one_video_rule(self, profile, own_codec, has_reencode_name):
        assert set(profile.rules) == {"video"}

    def test_video_rule_copy_mask_is_its_own_codec(self, profile, own_codec, has_reencode_name):
        assert profile.rules["video"].copy_mask == frozenset({own_codec})

    def test_video_rule_accept_options_force_a_real_copy(
        self, profile, own_codec, has_reencode_name
    ):
        """`accept_options=flags("-c:v copy")`, not WAV's `()`: every mask here
        is non-empty, so an empty accept branch would silently re-encode on the
        one path the copy mask exists to protect (Prior decisions)."""
        assert profile.rules["video"].accept_options == ("-c:v", "copy")

    def test_video_rule_is_placeholder_free(self, profile, own_codec, has_reencode_name):
        rule = profile.rules["video"]

        assert "{n}" not in " ".join(rule.accept_options)
        assert rule.fallback_options is not None
        assert "{n}" not in " ".join(rule.fallback_options)

    def test_video_rule_stream_limit_is_one(self, profile, own_codec, has_reencode_name):
        assert profile.rules["video"].stream_limit == 1

    def test_fallback_name_matches_whether_the_encode_is_lossless(
        self, profile, own_codec, has_reencode_name
    ):
        if has_reencode_name:
            assert profile.rules["video"].fallback_name is not None
        else:
            assert profile.rules["video"].fallback_name is None

    def test_no_container_options(self, profile, own_codec, has_reencode_name):
        assert profile.container_options == ()

    def test_last_resort_extracts_a_single_frame_with_a_note(
        self, profile, own_codec, has_reencode_name
    ):
        assert profile.last_resort is not None
        assert profile.last_resort.options[:4] == ("-map", "0:v:0", "-frames:v", "1")
        assert "{n}" not in " ".join(profile.last_resort.options)
        assert any("first frame" in note for note in profile.last_resort.notes)

    def test_last_resort_also_names_what_the_explicit_index_cannot_reach(
        self, profile, own_codec, has_reencode_name
    ):
        """`-map 0:v:0` is explicit-index, so unlike the selective rung it
        cannot name a per-stream drop itself -- the same reason MP3's and
        FLAC's index-named last resort carries a standing note for whatever it
        structurally drops (`docs/design/degradation-ladder.md`: "Every rung
        carries its own notes"). Without this, an audio-bearing video into
        `--to png`/`--to jpg`/`--to tiff`/`--to bmp` would lose its audio track
        with nothing saying so."""
        assert any("non-video streams" in note for note in profile.last_resort.notes)


class TestPngProfile:
    def test_label_and_suffix(self):
        assert PNG.label == "PNG"
        assert PNG.target_suffix == ".png"

    def test_name_and_description(self):
        assert PNG.name == "png"
        assert PNG.description

    def test_cheap_attempt_carries_no_standing_note(self):
        """PNG is lossless, so forcing its own encoder gives up nothing worth
        naming (Verification: png/tiff/bmp emit no note for the encode itself)."""
        assert PNG.cheap_attempt.notes == ()

    def test_cheap_attempt_argv(self):
        assert PNG.cheap_attempt.options == ("-map", "0:v?", "-c:v", "png")


class TestJpgProfile:
    def test_label_and_suffix(self):
        assert JPG.label == "JPG"
        assert JPG.target_suffix == ".jpg"

    def test_name_and_description(self):
        assert JPG.name == "jpg"
        assert JPG.description

    def test_cheap_attempt_argv(self):
        assert JPG.cheap_attempt.options == ("-map", "0:v?", "-c:v", "mjpeg", "-q:v", "2")

    def test_cheap_attempt_carries_the_transparency_standing_note(self):
        """Always wins for an ordinary image (the encoder is forced
        unconditionally), so this is the note that actually prints
        (Verification / spec-image-formats.md's gate decision)."""
        assert JPG.cheap_attempt.notes == (
            "transparency is not carried by JPEG; the image was re-encoded",
        )

    def test_fallback_name_is_declared(self):
        """Forcing mjpeg re-encodes an already-JPEG source too (measured:
        +15.5% size, PSNR 53.5 dB) -- a real loss on the selective rung."""
        assert JPG.rules["video"].fallback_name == "mjpeg"

    def test_last_resort_repeats_the_transparency_note(self):
        """The cheap attempt's standing note only actually prints for a source
        that never reaches the last resort -- a video with alpha into `--to
        jpg` lands here instead, so the loss has to be named again on the rung
        that actually wins for it (review finding on issue #34: a video's
        transparency was otherwise dropped in complete silence)."""
        assert JPG.last_resort is not None
        assert "transparency is not carried by JPEG; the image was re-encoded" in (
            JPG.last_resort.notes
        )


class TestTiffProfile:
    def test_label_and_suffix(self):
        assert TIFF.label == "TIFF"
        assert TIFF.target_suffix == ".tiff"

    def test_name_and_description(self):
        assert TIFF.name == "tiff"
        assert TIFF.description

    def test_cheap_attempt_carries_no_standing_note(self):
        assert TIFF.cheap_attempt.notes == ()

    def test_cheap_attempt_argv(self):
        assert TIFF.cheap_attempt.options == ("-map", "0:v?", "-c:v", "tiff")


class TestBmpProfile:
    def test_label_and_suffix(self):
        assert BMP.label == "BMP"
        assert BMP.target_suffix == ".bmp"

    def test_name_and_description(self):
        assert BMP.name == "bmp"
        assert BMP.description

    def test_cheap_attempt_carries_no_standing_note(self):
        assert BMP.cheap_attempt.notes == ()

    def test_cheap_attempt_argv(self):
        assert BMP.cheap_attempt.options == ("-map", "0:v?", "-c:v", "bmp")


#: The animated-capable trio: unlike the image2 four, none of these carries a
#: frame limit anywhere -- `gif` and `webp` write every frame of a multi-frame
#: source, and `avif`'s reduction to one frame is the muxer's own doing, not
#: something a `-frames:v` flag chooses.
ANIMATED_CASES = [GIF, WEBP, AVIF]


@pytest.mark.parametrize("profile", ANIMATED_CASES, ids=lambda profile: profile.label)
class TestAnimatedTrioShape:
    """Shared shape across gif, webp and avif (spec-image-formats.md)."""

    def test_cheap_attempt_maps_video_blindly(self, profile):
        assert profile.cheap_attempt.options[:2] == ("-map", "0:v?")

    def test_cheap_attempt_selects_streams_blindly(self, profile):
        assert profile.explicit_streams is False

    def test_cheap_attempt_is_declared_partial(self, profile):
        assert profile.partial_mapping is True

    def test_has_exactly_one_video_rule(self, profile):
        assert set(profile.rules) == {"video"}

    def test_video_rule_accept_options_force_a_real_copy(self, profile):
        assert profile.rules["video"].accept_options == ("-c:v", "copy")

    def test_video_rule_is_placeholder_free(self, profile):
        rule = profile.rules["video"]

        assert "{n}" not in " ".join(rule.accept_options)
        assert rule.fallback_options is not None
        assert "{n}" not in " ".join(rule.fallback_options)

    def test_video_rule_stream_limit_is_one(self, profile):
        """Muxer-enforced, not mapping-enforced: none of these three holds more
        than one video *stream* -- orthogonal to how many frames that one
        stream may carry (MUXER_ENFORCED_LIMIT_TYPES above)."""
        assert profile.rules["video"].stream_limit == 1

    def test_no_container_options(self, profile):
        assert profile.container_options == ()

    def test_last_resort_carries_no_frame_limit(self, profile):
        """Verification: neither gif nor webp carries a frame limit anywhere,
        and avif's reduction to one frame is the muxer's own doing -- none of
        the three last resorts adds a `-frames:v` flag."""
        assert profile.last_resort is not None
        assert "-frames:v" not in profile.last_resort.options

    def test_last_resort_names_what_the_explicit_index_cannot_reach(self, profile):
        assert any("non-video streams" in note for note in profile.last_resort.notes)


class TestGifProfile:
    def test_label_and_suffix(self):
        assert GIF.label == "GIF"
        assert GIF.target_suffix == ".gif"

    def test_name_and_description(self):
        assert GIF.name == "gif"
        assert GIF.description

    def test_cheap_attempt_argv(self):
        assert GIF.cheap_attempt.options == ("-map", "0:v?", "-c:v", "gif")

    def test_cheap_attempt_always_wins_so_its_standing_notes_always_print(self):
        """Forces the encoder unconditionally, so this is the rung whose notes
        actually print for the overwhelming majority of inputs. Both notes are
        worded as format facts (issue #67 review) -- "GIF holds at most a
        256-colour palette", not "colours are reduced", since an already-GIF,
        already-<=256-colour source re-encodes pixel-identically and a
        "reduced" claim would be false for it."""
        assert GIF.cheap_attempt.notes == (
            "transparency is not carried by GIF",
            "GIF holds at most a 256-colour palette",
        )

    def test_video_rule_copy_mask_is_its_own_codec(self):
        assert GIF.rules["video"].copy_mask == frozenset({"gif"})

    def test_fallback_name_is_declared(self):
        """GIF is a 256-colour palette format, not a lossless one, unlike
        png/tiff/bmp -- the quantisation must be named."""
        assert GIF.rules["video"].fallback_name == "gif"

    def test_last_resort_argv(self):
        assert GIF.last_resort is not None
        assert GIF.last_resort.options == ("-map", "0:v:0", "-c:v", "gif")

    def test_last_resort_repeats_the_standing_notes(self):
        """Only reached when the cheap attempt failed, so its standing notes
        never printed -- the same reasoning JPG's last_resort repeats its
        transparency note for."""
        assert GIF.last_resort is not None
        assert "transparency is not carried by GIF" in GIF.last_resort.notes
        assert "GIF holds at most a 256-colour palette" in GIF.last_resort.notes


class TestWebpProfile:
    def test_label_and_suffix(self):
        assert WEBP.label == "WEBP"
        assert WEBP.target_suffix == ".webp"

    def test_name_and_description(self):
        assert WEBP.name == "webp"
        assert WEBP.description

    def test_cheap_attempt_keeps_a_real_copy(self):
        """The one target in this trio whose muxer self-polices cleanly enough
        (a non-matching codec copy exits 127) to keep a bare copy, unlike gif
        and avif which force their encoder instead."""
        assert WEBP.cheap_attempt.options == ("-map", "0:v?", "-c", "copy")

    def test_cheap_attempt_carries_no_standing_note(self):
        """Loses neither alpha nor frames, so no note's reachability depends
        on which rung wins."""
        assert WEBP.cheap_attempt.notes == ()

    def test_video_rule_copy_mask_is_its_own_codec(self):
        assert WEBP.rules["video"].copy_mask == frozenset({"webp"})

    def test_fallback_name_is_declared(self):
        """The fallback is a real, lossy re-encode (quality 80), unlike
        png/tiff/bmp's lossless one."""
        assert WEBP.rules["video"].fallback_name == "webp"

    def test_last_resort_argv(self):
        assert WEBP.last_resort is not None
        assert WEBP.last_resort.options == (
            "-map",
            "0:v:0",
            "-c:v",
            "libwebp",
            "-quality:v",
            "80",
        )


class TestAvifProfile:
    def test_label_and_suffix(self):
        assert AVIF.label == "AVIF"
        assert AVIF.target_suffix == ".avif"

    def test_name_and_description(self):
        assert AVIF.name == "avif"
        assert AVIF.description

    def test_cheap_attempt_argv(self):
        assert AVIF.cheap_attempt.options == (
            "-map",
            "0:v?",
            "-c:v",
            "libaom-av1",
            "-crf:v",
            "30",
            "-still-picture",
            "1",
        )

    def test_cheap_attempt_always_wins_so_its_standing_notes_always_print(self):
        """The one loss in this phase no failure path can hang a per-stream
        note on: the muxer keeps one frame no matter what is asked of it, even
        on the cheap attempt for an AV1-in-MP4 source."""
        assert AVIF.cheap_attempt.notes == (
            "transparency is not carried by AVIF",
            "a multi-frame source is reduced to a single frame",
        )

    def test_video_rule_copy_mask_is_its_own_codec(self):
        assert AVIF.rules["video"].copy_mask == frozenset({"av1"})

    def test_fallback_name_is_declared(self):
        assert AVIF.rules["video"].fallback_name == "av1"

    def test_last_resort_argv(self):
        assert AVIF.last_resort is not None
        assert AVIF.last_resort.options == (
            "-map",
            "0:v:0",
            "-c:v",
            "libaom-av1",
            "-crf",
            "30",
            "-still-picture",
            "1",
        )

    def test_last_resort_repeats_the_standing_notes(self):
        assert AVIF.last_resort is not None
        assert "transparency is not carried by AVIF" in AVIF.last_resort.notes
        assert "a multi-frame source is reduced to a single frame" in AVIF.last_resort.notes


@pytest.mark.parametrize("profile", PROFILES.values(), ids=lambda profile: profile.label)
class TestNoExifOrIccPromiseInDescription:
    """Guard rail for issue #36, registry-wide rather than image-only:
    `docs/vision.md`'s Non-goals list "EXIF/ICC preservation" -- ffmpeg
    strips metadata by default, and PNG cannot carry EXIF at all by
    construction, so no profile's user-facing `description` (the text
    `--list-formats` prints and `README.md` mirrors byte-for-byte,
    `TestListFormats.test_readme_format_list_matches_the_command_byte_for_byte`
    in `tests/test_cli.py`) may claim otherwise.

    Deliberately scoped to `description` alone, not a rung's notes: a note
    exists to name a *loss* (`Attempt.notes`'s own docstring), so a future
    "EXIF metadata is not carried" note would be the honest disclosure
    `docs/vision.md`'s loss-accounting goal asks for, not the promise this
    non-goal forbids. Scanning notes too would fail exactly the text this
    project wants to see. Nothing in the registry mentions either word
    today, image or otherwise.
    """

    def test_description_does_not_mention_exif_or_icc(self, profile):
        assert not re.search(r"\bexif\b", profile.description, re.IGNORECASE)
        assert not re.search(r"\bicc\b", profile.description, re.IGNORECASE)


class TestRegistry:
    def test_keys_are_each_profile_s_own_name(self):
        assert PROFILES == {
            "mp4": MP4,
            "wav": WAV,
            "mkv": MKV,
            "mp3": MP3,
            "flac": FLAC,
            "mov": MOV,
            "webm": WEBM,
            "m4a": M4A,
            "ogg": OGG,
            "opus": OPUS,
            "png": PNG,
            "jpg": JPG,
            "tiff": TIFF,
            "bmp": BMP,
            "gif": GIF,
            "webp": WEBP,
            "avif": AVIF,
        }


@pytest.mark.parametrize("profile", PROFILES.values(), ids=lambda profile: profile.label)
class TestRegistryStructuralInvariants:
    """Registry-wide guard rails for issue #23.

    Parametrized over ``PROFILES.values()`` itself, not over the hand-maintained
    ``SHIPPED`` list above -- so a profile that lands after this PR (phases 4
    and 5 are landing in parallel) is covered the moment it is added to
    ``PROFILES``, with no further edit to this file needed. This is the
    "structural test over the whole registry" the issue asks for: it catches a
    half-written profile -- a blank name or description, a target suffix
    nobody added to ``SOURCE_SUFFIXES``, or a profile with no stream rule at
    all (which would make every conversion into it structurally unsupported).
    """

    def test_has_a_non_empty_name(self, profile):
        assert isinstance(profile.name, str) and profile.name

    def test_has_a_non_empty_description(self, profile):
        assert isinstance(profile.description, str) and profile.description

    def test_target_suffix_is_a_curated_source_suffix(self, profile):
        """Otherwise a source already carrying the target's own suffix could
        never take part in selection at all (the self-write and
        existing-output-skip cases, `docs/design/source-selection.md`)."""
        assert profile.target_suffix in SOURCE_SUFFIXES

    def test_declares_at_least_one_stream_rule(self, profile):
        """A profile with no rule at all could never carry a single stream:
        every source would be `Outcome.UNSUPPORTED` (`converter/jobs.py`'s
        `describe_unsupported`), which is not a target format, it is a no-op
        that pretends to be one."""
        assert len(profile.rules) >= 1

    def test_a_rule_with_no_stream_limit_carries_the_position_placeholder(self, profile):
        """Issue #22's real bug, generalised registry-wide: ffmpeg's unindexed
        codec options (`-c:a copy`) are not positional -- when several are
        given for the same stream type, the *last* one wins for every output
        stream of that type, not one per stream in map order (measured against
        ffmpeg 9.0, `M4A`'s and `OPUS`'s audio-rule comments in
        `converter/profiles.py`). That silently re-encodes an already-accepted
        stream with no note, so a rule not capped at one output stream of its
        type -- `stream_limit == 1`, e.g. `WAV`'s or the image profiles', where
        only one index is ever substituted and the bare form cannot collide --
        must carry the `{n}` placeholder `jobs._substitute_position`
        substitutes per stream position.

        `accept_options` is asserted non-empty rather than skipped when falsy:
        an empty `accept_options` on an uncapped rule would emit a map with no
        codec option at all, producing an undeclared re-encode -- exactly what
        `OPUS`'s own audio-rule comment (`converter/profiles.py`) says was
        measured and is why `opus`'s cheap attempt does not use `WAV`'s empty
        form. `fallback_options` stays conditional: it is genuinely optional
        (`StreamRule.fallback_options: tuple[str, ...] | None`), unlike
        `accept_options`.
        """
        for rule in profile.rules.values():
            if rule.stream_limit == 1:
                continue
            assert rule.accept_options, (
                f"{profile.label}: accept_options is empty on a rule with no "
                "stream_limit==1 cap -- this would emit a map with no codec option, "
                "producing an undeclared re-encode"
            )
            assert "{n}" in " ".join(rule.accept_options), (
                f"{profile.label}: accept_options {rule.accept_options!r} has no "
                "stream_limit==1 cap but no {n} placeholder"
            )
            if rule.fallback_options:
                assert "{n}" in " ".join(rule.fallback_options), (
                    f"{profile.label}: fallback_options {rule.fallback_options!r} has no "
                    "stream_limit==1 cap but no {n} placeholder"
                )

    def test_a_declared_last_resort_always_carries_a_note(self, profile):
        """Issue #34's bug class, generalised registry-wide: the image
        `last_resort` used to drop a stream type it did not explicitly map
        (audio, alongside `-map 0:v:0`) with no note at all -- a direct
        violation of the constitution's "Never report success for a
        conversion that silently dropped something." A `last_resort` exists
        specifically because the ladder's earlier rungs failed, so by
        construction it is always more constrained than the cheap attempt; an
        empty `notes` tuple on one would mean a future profile shipped that
        same silent drop again. Every shipped `last_resort` names either what
        it re-encoded or what it structurally could not reach, so this is not
        a hypothetical -- it is the shape every one of them already has.
        """
        if profile.last_resort is None:
            return
        assert profile.last_resort.notes, (
            f"{profile.label}: last_resort declares no note for what it degrades or drops"
        )


class TestRegistryTargetCoherence:
    """Target-suffix coherence across the whole registry (issue #30).

    `TestRegistryStructuralInvariants` above already pins that every target
    suffix is a curated source suffix; this class pins the direction that
    check cannot: that no two profiles claim the *same* suffix. A duplicate
    registry *name* is not this class's concern -- `PROFILES` is built as
    ``{profile.name: profile for profile in (...)}``, so a name collision
    would silently drop one profile from the dict entirely rather than leave
    both reachable for a test parametrized over ``PROFILES.values()`` to
    compare; `TestRegistry.test_keys_are_each_profile_s_own_name`'s full
    dict-literal equality is what would actually notice a missing profile.
    """

    def test_no_two_profiles_share_a_target_suffix(self):
        suffixes = [profile.target_suffix for profile in PROFILES.values()]
        duplicates = {suffix for suffix in suffixes if suffixes.count(suffix) > 1}

        assert not duplicates, f"target_suffix collision(s) in the registry: {sorted(duplicates)}"


class TestLossyCodecs:
    """`LOSSY_CODECS` (issue #87, `docs/specs/archive/spec-lossy-source-notes.md`): the
    curated set the source-codec advisory checks against, hand-maintained
    because ffmpeg's own `-codecs` classification cannot be read wholesale --
    see the constant's own docstring in `converter/profiles.py` for the full
    argument and the ffmpeg 9.0 flags it was measured against.
    """

    def test_excludes_the_named_lossless_family(self):
        """The four awkward codecs the issue names -- `alac`, `flac`,
        `wmalossless`, `truehd` -- and the *linear* `pcm_*` decoders all
        report ffmpeg's own lossless flag (`S`) with no `L`, and none of
        them may ever read as a lossy source. Scoped to a representative
        sample of linear PCM (`pcm_s16le`, `pcm_s24le`, `pcm_s32le`,
        `pcm_f32le`, `pcm_u8` -- different bit depths, signedness and a
        float variant) rather than a blanket `pcm_` prefix ban: three
        *other* `pcm_*` decoders -- `pcm_alaw`, `pcm_mulaw`, `pcm_vidc` --
        are genuinely lossy and are members (the next test)."""
        assert LOSSY_CODECS.isdisjoint(
            {
                "alac",
                "flac",
                "wmalossless",
                "truehd",
                "pcm_s16le",
                "pcm_s24le",
                "pcm_s32le",
                "pcm_f32le",
                "pcm_u8",
            }
        )

    def test_includes_the_lossy_pcm_companding_variants(self):
        """`pcm_alaw`/`pcm_mulaw` (G.711 companding) and `pcm_vidc` report
        `L` only, no `S` -- unambiguously lossy, unlike every codec this
        set deliberately leaves out. A companded source is an ordinary
        `SOURCE_SUFFIXES` member (a G.711 `.wav`), so omitting them would
        have been a silent gap rather than a judgement call."""
        assert {"pcm_alaw", "pcm_mulaw", "pcm_vidc"} <= LOSSY_CODECS

    def test_includes_the_common_lossy_audio_codecs_reachable_as_a_source(self):
        """Membership cannot be scoped to "whatever this registry's own copy
        masks and fallback names already use": `LOSSY_CODECS` matches a
        *source* codec, reachable via `SOURCE_SUFFIXES` regardless of what
        any target profile does with it -- the same correction that added
        the companded PCM trio applies to every codec below. `wmav1`/
        `wmav2`/`wmapro` are the sharpest case: this set already guards
        against misreading `wmalossless`, so staying silent on the far
        commoner lossy WMA family would have been backwards. All ten
        report ffmpeg's `L` flag only, no `S` -- no ambiguity to trade
        against, unlike `dts`."""
        assert {
            "wmav1",
            "wmav2",
            "wmapro",
            "mp2",
            "amr_nb",
            "amr_wb",
            "nellymoser",
            "speex",
            "gsm",
            "ilbc",
        } <= LOSSY_CODECS

    def test_includes_the_motivating_and_flag_contradicting_cases(self):
        """A set could satisfy the exclusion test above by being empty, which
        would not be a lossy-codec set at all. `mp3` is the motivating case
        (Verification, spec-lossy-source-notes.md: "an MP3 library into
        FLAC"); `gif` is the case ffmpeg's own flag gets wrong (reports
        lossless, measured lossy in `docs/specs/archive/spec-image-formats.md`).
        Both must actually be members for this set to be doing its job.
        """
        assert {"mp3", "gif"} <= LOSSY_CODECS


def lossless_target_names(registry: dict[str, Profile]) -> set[str]:
    """Names of every profile with at least one rule matching the lossless
    criterion the spec pins: `fallback_options is not None and fallback_name
    is None` -- it re-encodes, and the profile declared that re-encode not
    worth naming. The bare `fallback_name is None` test is overloaded (Prior
    decisions, spec-lossy-source-notes.md): it also matches a rule with no
    fallback at all, which is a *drop*, not a lossless re-encode -- exactly
    the shape phase 6's fallback-less `attached_pic` rules have, which must
    not be misread as lossless targets the moment they land.
    """
    return {
        profile.name
        for profile in registry.values()
        if any(
            rule.fallback_options is not None and rule.fallback_name is None
            for rule in profile.rules.values()
        )
    }


class TestLosslessTargetCriterion:
    """The second, load-bearing guard rail from issue #87: pins that exactly
    the five profiles the spec's Prior decisions table names satisfy the
    lossless criterion, checked against the *whole* registry so a profile
    added later -- lossless or not -- is covered without editing this test.
    """

    def test_exactly_five_profiles_satisfy_the_lossless_criterion(self):
        assert lossless_target_names(PROFILES) == {"flac", "wav", "png", "tiff", "bmp"}


class TestResolveTarget:
    @pytest.mark.parametrize("target", ["mp4", "MP4", ".mp4", ".MP4", "Mp4"])
    def test_accepts_name_case_and_dot_variants(self, target):
        assert resolve_target(target) is MP4

    def test_resolves_wav_too(self):
        assert resolve_target("wav") is WAV

    @pytest.mark.parametrize("target", ["mkv", "MKV", ".mkv", ".MKV", "Mkv"])
    def test_accepts_mkv_name_case_and_dot_variants(self, target):
        assert resolve_target(target) is MKV

    def test_resolves_mp3_and_flac_too(self):
        assert resolve_target("mp3") is MP3
        assert resolve_target("flac") is FLAC

    def test_resolves_m4a_ogg_and_opus_too(self):
        assert resolve_target("m4a") is M4A
        assert resolve_target("ogg") is OGG
        assert resolve_target("opus") is OPUS

    @pytest.mark.parametrize("target", ["mov", "MOV", ".mov", ".MOV", "Mov"])
    def test_accepts_mov_name_case_and_dot_variants(self, target):
        assert resolve_target(target) is MOV

    @pytest.mark.parametrize("target", ["webm", "WEBM", ".webm", ".WEBM", "Webm"])
    def test_accepts_webm_name_case_and_dot_variants(self, target):
        assert resolve_target(target) is WEBM

    @pytest.mark.parametrize(
        ("target", "profile"),
        [
            ("png", PNG),
            ("jpg", JPG),
            ("tiff", TIFF),
            ("bmp", BMP),
            ("gif", GIF),
            ("webp", WEBP),
            ("avif", AVIF),
        ],
    )
    def test_resolves_the_image_targets(self, target, profile):
        assert resolve_target(target) is profile

    def test_unknown_target_raises_value_error_listing_available_targets(self):
        """`avi` is a curated source suffix, never a registered target, so this
        stays stable regardless of which other in-flight profile lands next."""
        with pytest.raises(
            ValueError,
            match=(
                r"avi.*available targets: avif, bmp, flac, gif, jpg, m4a, mkv, mov, "
                r"mp3, mp4, ogg, opus, png, tiff, wav, webm, webp"
            ),
        ):
            resolve_target("avi")


class TestSourceSuffixes:
    def test_holds_the_phase_2_through_phase_5_suffixes(self):
        """`.mkv`/`.opus` are what the old sub-commands read; `.mp4`/`.wav` are
        what let a source already carrying the target suffix take part in
        selection (the self-write and existing-output cases,
        `docs/design/source-selection.md`). Issue #20 (`spec-audio-formats.md`)
        widens the set with the audio containers people actually have, the video
        containers a "rip the audio" run needs, and the remaining audio target
        suffixes ahead of the profiles that will claim them. Issue #26
        (`spec-video-formats.md`) widens it once more with the video containers
        no earlier phase added. Issue #33 (`spec-image-formats.md`) widens it
        once more with the image containers ahead of the seven image profiles
        that milestone still adds."""
        assert {
            ".mkv",
            ".mp4",
            ".opus",
            ".wav",
            ".aac",
            ".m4b",
            ".wma",
            ".aiff",
            ".aif",
            ".ape",
            ".wv",
            ".caf",
            ".mov",
            ".avi",
            ".webm",
            ".m4v",
            ".wmv",
            ".flv",
            ".mp3",
            ".m4a",
            ".flac",
            ".ogg",
            ".mpg",
            ".mpeg",
            ".ts",
            ".m2ts",
            ".mts",
            ".vob",
            ".ogv",
            ".3gp",
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".avif",
            ".gif",
            ".tif",
            ".tiff",
            ".bmp",
            ".ppm",
            ".pgm",
            ".tga",
        } == SOURCE_SUFFIXES

    def test_every_shipped_profile_s_target_suffix_is_a_source_suffix(self):
        assert all(profile.target_suffix in SOURCE_SUFFIXES for profile in SHIPPED)

    def test_every_audio_target_suffix_is_a_source_suffix(self):
        """The six audio targets this milestone covers -- `mp3`, `m4a`, `flac`,
        `opus`, `ogg`, `wav` -- all have their own suffix readable as a source,
        even for the five whose profile has not landed yet, so #20 does not block
        on issue order within the milestone."""
        audio_target_suffixes = {".mp3", ".m4a", ".flac", ".opus", ".ogg", ".wav"}
        assert audio_target_suffixes <= SOURCE_SUFFIXES

    def test_holds_the_phase_4_video_container_suffixes(self):
        """Issue #26 (`spec-video-formats.md`): the video containers no earlier
        phase added, ahead of the `mkv`/`webm`/`mov` profiles that milestone still
        adds. `.mkv` (phase 2) and `.mp4`/`.mov`/`.avi`/`.webm`/`.m4v`/`.wmv`/
        `.flv` (phase 3) are deliberately not repeated here -- they are already
        covered by the phase-2/phase-3 suffixes above."""
        phase_4_suffixes = {".mpg", ".mpeg", ".ts", ".m2ts", ".mts", ".vob", ".ogv", ".3gp"}
        assert phase_4_suffixes <= SOURCE_SUFFIXES

    def test_holds_the_phase_5_image_container_suffixes(self):
        """Issue #33 (`spec-image-formats.md`): the twelve image container
        suffixes ahead of the seven image profiles (`png`, `jpg`, `webp`, `avif`,
        `gif`, `tiff`, `bmp`) that milestone still adds. None of the twelve was
        already present in the set seeded by phases 2 through 4."""
        phase_5_suffixes = {
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".avif",
            ".gif",
            ".tif",
            ".tiff",
            ".bmp",
            ".ppm",
            ".pgm",
            ".tga",
        }
        assert phase_5_suffixes <= SOURCE_SUFFIXES


class TestValueTypesAreFrozen:
    def test_attempt_is_frozen(self):
        attempt = Attempt(label="x", options=())

        with pytest.raises(AttributeError):
            attempt.label = "y"

    def test_stream_rule_is_frozen(self):
        rule = StreamRule(copy_mask=frozenset(), accept_options=())

        with pytest.raises(AttributeError):
            rule.copy_mask = frozenset({"x"})

    def test_profile_is_frozen(self):
        with pytest.raises(AttributeError):
            MP4.label = "changed"

    def test_profile_dataclass_shape(self):
        """Sanity check the type itself, not just the two instances."""
        fields = {f.name for f in dataclasses.fields(Profile)}

        assert fields == {
            "label",
            "name",
            "description",
            "target_suffix",
            "container_options",
            "cheap_attempt",
            "explicit_streams",
            "partial_mapping",
            "rules",
            "last_resort",
        }

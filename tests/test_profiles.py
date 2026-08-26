"""Tests for the leaf module and the two profiles it declares."""

import ast
import dataclasses
import inspect
import itertools

import pytest

from converter import profiles
from converter.profiles import (
    MP4,
    PROFILES,
    SOURCE_SUFFIXES,
    WAV,
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

#: Every profile the registry ships. A new one joins the invariant checks here.
SHIPPED = [MP4, WAV]

#: A stand-in for the not-yet-shipped `mov` profile (`docs/specs/spec-video-formats.md`),
#: shaped only enough to prove the degradation-ladder invariant's narrowed form:
#: it maps `attachment` via `-map 0:t?` -- exactly `mov`'s pinned cheap attempt --
#: but declares no `attachment` rule, because MOV's muxer rejects any mapped
#: attachment outright. An attachment-bearing source fails the cheap attempt and
#: is routed into the ladder instead of reaching the success-side check, so the
#: type never needs a rule to keep that check honest (issue #39).
MOV_SHAPED = Profile(
    label="MOV (shaped)",
    name="mov-shaped",
    description="Stand-in for the invariant test, not a shipped profile",
    target_suffix=".mov",
    container_options=(),
    cheap_attempt=Attempt(
        label="remux",
        options=flags("-map 0:v? -map 0:a? -map 0:s? -map 0:t? -c copy -c:s mov_text"),
    ),
    explicit_streams=False,
    partial_mapping=True,
    rules={
        "video": StreamRule(copy_mask=frozenset({"h264"}), accept_options=flags("-c:v:{n} copy")),
        "audio": StreamRule(copy_mask=frozenset({"aac"}), accept_options=flags("-c:a:{n} copy")),
        "subtitle": StreamRule(
            copy_mask=frozenset(), accept_options=(), drop_reason="not modelled here"
        ),
    },
)

#: A stand-in for a not-yet-shipped phase-3 profile shaped like `mp3`/`flac`
#: (`docs/specs/spec-audio-formats.md`): its cheap attempt maps audio *blindly*
#: (`-map 0:a?`), yet the rule still carries `stream_limit=1`, because the mp3
#: and flac muxers themselves reject a second audio stream outright (measured
#: against ffmpeg 9.0 during that spec's planning) -- a source that would trip
#: the limit never reaches the success side at all; it fails the cheap attempt
#: and lands on the failure side, where the declared limit drives the
#: selective rung's own note instead. Proves the muxer-enforced `stream_limit`
#: exemption (issue #40) the way `MOV_SHAPED` proves the force-failure one.
MP3_SHAPED = Profile(
    label="MP3 (shaped)",
    name="mp3-shaped",
    description="Stand-in for the invariant test, not a shipped profile",
    target_suffix=".mp3",
    container_options=(),
    cheap_attempt=Attempt(label="remux", options=flags("-map 0:a? -c:a copy")),
    explicit_streams=False,
    partial_mapping=True,
    rules={
        "audio": StreamRule(
            copy_mask=frozenset({"mp3"}),
            accept_options=flags("-c:a copy"),
            fallback_options=flags("-c:a libmp3lame -q:a 2"),
            fallback_name="mp3",
            stream_limit=1,
        ),
    },
)

#: Stream types each profile maps only to *force* the cheap attempt to fail when
#: the source carries one -- never to carry it on the success side. The narrowed
#: invariant (`docs/design/degradation-ladder.md`) exempts these from needing a
#: rule: a type mapped to force a failure never reaches the success-side check.
FORCED_FAILURE_TYPES: dict[str, frozenset[str]] = {
    MP4.name: frozenset(),
    WAV.name: frozenset(),
    MOV_SHAPED.name: frozenset({"attachment"}),
    MP3_SHAPED.name: frozenset(),
}

#: Stream types whose `stream_limit` is enforced by the container's own muxer
#: rather than by the cheap attempt's own selectors -- the mirror of
#: `FORCED_FAILURE_TYPES` for `stream_limit` instead of rule existence. A type
#: listed here is mapped *blindly* and still carries a limit, because a source
#: that would exceed it makes the cheap attempt itself fail (issue #40).
MUXER_ENFORCED_LIMIT_TYPES: dict[str, frozenset[str]] = {
    MP4.name: frozenset(),
    WAV.name: frozenset(),
    MOV_SHAPED.name: frozenset(),
    MP3_SHAPED.name: frozenset({"audio"}),
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
        if letter in MAP_LETTERS and len(parts) > 1:
            kind = MAP_LETTERS[letter]
            counts[kind] = counts.get(kind, 0) + 1
    return counts


#: `SHIPPED` plus the two stand-ins, so the invariant is checked against
#: profiles that actually exercise both exemptions -- otherwise the narrowed
#: reading and a stricter one would agree on every case tested.
INVARIANT_CASES = [*SHIPPED, MOV_SHAPED, MP3_SHAPED]


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


class TestRegistry:
    def test_keys_are_each_profile_s_own_name(self):
        assert PROFILES == {"mp4": MP4, "wav": WAV}


class TestResolveTarget:
    @pytest.mark.parametrize("target", ["mp4", "MP4", ".mp4", ".MP4", "Mp4"])
    def test_accepts_name_case_and_dot_variants(self, target):
        assert resolve_target(target) is MP4

    def test_resolves_wav_too(self):
        assert resolve_target("wav") is WAV

    def test_unknown_target_raises_value_error_listing_available_targets(self):
        with pytest.raises(ValueError, match=r"mkv.*available targets: mp4, wav"):
            resolve_target("mkv")


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
        """Issue #33 (`spec-image-formats.md`): the image containers ahead of the
        seven image profiles that milestone still adds -- `png`, `jpg`, `webp`,
        `avif`, `gif`, `tiff`, `bmp`. None of these twelve suffixes was already
        present in the set seeded by phases 2 through 4."""
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

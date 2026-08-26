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

#: Stream types each profile maps only to *force* the cheap attempt to fail when
#: the source carries one -- never to carry it on the success side. The narrowed
#: invariant (`docs/design/degradation-ladder.md`) exempts these from needing a
#: rule: a type mapped to force a failure never reaches the success-side check.
FORCED_FAILURE_TYPES: dict[str, frozenset[str]] = {
    MP4.name: frozenset(),
    WAV.name: frozenset(),
    MOV_SHAPED.name: frozenset({"attachment"}),
}


def mapped_types(profile: Profile) -> dict[str, bool]:
    """Stream types the cheap attempt maps -> whether it maps them *blindly*.

    Reading the option list is the point here and forbidden in the engine: this
    check exists precisely to catch a profile whose declared mapping and declared
    rules disagree, which needs both readings side by side.
    """
    options = profile.cheap_attempt.options
    mapped: dict[str, bool] = {}
    map_values = [value for flag, value in itertools.pairwise(options) if flag == "-map"]
    for value in map_values:
        if not value.startswith("0:"):
            continue
        selector = value[2:].removesuffix("?")
        letter = selector.split(":")[0]
        if letter in MAP_LETTERS:
            # "0:a?" selects every audio stream; "0:a:0" names exactly one.
            mapped[MAP_LETTERS[letter]] = ":" not in selector
    # A "-map" flag this function cannot read (a bare index like "0:0", or a
    # negative exclusion like "-0:s") must fail loudly, not return {} and let
    # the invariant checks pass over a profile they never actually looked at.
    assert not map_values or mapped, (
        f"{profile.label}: no -map selector recognised among {map_values!r}"
    )
    return mapped


def named_index_counts(profile: Profile) -> dict[str, int]:
    """How many distinct stream indices the cheap attempt names, per type.

    ``mapped_types`` collapses a type down to one blind/explicit bit; a
    ``stream_limit`` check needs the actual count, so a profile that names two
    indices of a type but declares a limit of one -- or the reverse -- is
    caught rather than passing because *some* index of that type was named.
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


#: `SHIPPED` plus the mov-shaped stand-in, so the invariant is checked against a
#: profile that actually exercises the force-failure exemption -- otherwise the
#: narrowed reading and the old, broader one would agree on every case tested.
INVARIANT_CASES = [*SHIPPED, MOV_SHAPED]


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
        force-failure exemption, which only ever removes from the left).
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
        a thing that can be checked.
        """
        blind = [
            kind
            for kind, is_blind in mapped_types(profile).items()
            if is_blind and kind in profile.rules
        ]

        assert all(profile.rules[kind].stream_limit is None for kind in blind)

    def test_stream_limit_matches_the_cheap_attempt_s_named_index_count(self, profile):
        """A limit belongs to a type the cheap attempt names by index, and
        must equal how many indices of that type are actually named -- WAV
        names one audio index and limits audio to 1. Pinning the count, not
        just that a limit exists, catches a profile that names two indices of
        a type but limits it to one, or declares a limit with no named index
        behind it at all.
        """
        counts = named_index_counts(profile)

        for kind, rule in profile.rules.items():
            if rule.stream_limit is not None:
                assert rule.stream_limit == counts.get(kind, 0)


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
    def test_holds_the_old_job_suffixes_and_each_shipped_profile_s_own_suffix(self):
        """`.mkv`/`.opus` are what the old sub-commands read; `.mp4`/`.wav` are
        what let a source already carrying the target suffix take part in
        selection (the self-write and existing-output cases,
        `docs/design/source-selection.md`)."""
        assert {".mkv", ".mp4", ".opus", ".wav"} == SOURCE_SUFFIXES

    def test_every_shipped_profile_s_target_suffix_is_a_source_suffix(self):
        assert all(profile.target_suffix in SOURCE_SUFFIXES for profile in SHIPPED)


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

"""The generic conversion engine: profile plus probed streams -> attempt ladder.

The engine holds no format-specific fact -- no codec name, no container option,
no degradation-note wording. Every such fact lives in the ``Profile`` it is
handed (``converter/profiles.py``) and is read out of that data, never written
here. ``batch.py`` calls this module's entry points directly and never reads a
profile's rules itself -- the boundary ``docs/architecture.md`` draws between
"carries a profile" and "decides with one".

See ``docs/design/degradation-ladder.md`` for the order of attempts this module
builds, ``docs/design/stream-decision.md`` for how one stream's fate is decided
inside the engine-built rung, and
``docs/specs/spec-target-driven-cli.md`` for the ``unsupported`` discriminator
:func:`describe_unsupported` implements.
"""

from collections.abc import Sequence
from dataclasses import replace

from converter.ffmpegtool import Stream
from converter.profiles import Attempt, Profile


def _with_container_options(attempt: Attempt, profile: Profile) -> Attempt:
    """Append the profile's container-wide options once, at the end of *attempt*.

    Declared attempts exclude them by convention (Prior decisions,
    spec-profile-registry) so a profile states ``+faststart`` once rather than
    repeating it in every attempt it declares.
    """
    return replace(attempt, options=(*attempt.options, *profile.container_options))


def _substitute_position(template: tuple[str, ...], position: int) -> tuple[str, ...]:
    """Replace the optional literal ``{n}`` placeholder with an output position."""
    return tuple(item.replace("{n}", str(position)) for item in template)


def _drop_note(stream: Stream, reason: str) -> str:
    """D1/D2/D3 of stream-decision.md: a drop always names index, codec, reason."""
    kind = stream.codec_type or "unknown"
    codec = stream.codec_name or "unknown"
    return f"{kind} stream {stream.index} ({codec}) dropped: {reason}"


def _reencode_note(stream: Stream, target_codec: str) -> str:
    """The note a re-encode carries when the rule declares one worth naming."""
    kind = stream.codec_type or "unknown"
    codec = stream.codec_name or "unknown"
    return f"{kind} stream {stream.index} ({codec}) re-encoded to {target_codec}"


def _room_reason(profile: Profile, stream_type: str, limit: int) -> str:
    """D2's reason: the noun agrees in number with the rule's stream limit."""
    noun = "stream" if limit == 1 else "streams"
    return f"{profile.label} holds {limit} {stream_type} {noun}"


def _structural_drop(profile: Profile, stream: Stream, counts: dict[str, int]) -> str | None:
    """D1 and D2 of stream-decision.md: the drops the profile's *shape* forces.

    Split out because both verdicts are reached from the declared rules alone,
    without ever looking at the stream's codec. That is what lets the
    success-side verification in :func:`_unmapped_notes` reuse them without
    asserting anything about what an already-successful attempt encoded.
    """
    rule = profile.rules.get(stream.codec_type)
    if rule is None:
        return _drop_note(stream, f"not supported by {profile.label}")

    position = counts.get(stream.codec_type, 0)
    if rule.stream_limit is not None and position >= rule.stream_limit:
        return _drop_note(stream, _room_reason(profile, stream.codec_type, rule.stream_limit))
    return None


def _unmapped_notes(profile: Profile, streams: Sequence[Stream]) -> tuple[str, ...]:
    """Name what a structurally partial cheap attempt cannot have carried over.

    Only the structural verdicts above are consulted. Codec-level ones are
    deliberately left out: the cheap attempt has already exited 0, so whatever
    it did with a stream's codec worked, and announcing a re-encode it never
    performed would just swap one dishonest report for another.
    """
    notes: list[str] = []
    counts: dict[str, int] = {}
    for stream in streams:
        note = _structural_drop(profile, stream, counts)
        if note is None:
            counts[stream.codec_type] = counts.get(stream.codec_type, 0) + 1
        else:
            notes.append(note)
    return tuple(notes)


def _decide_stream(
    profile: Profile, stream: Stream, counts: dict[str, int]
) -> tuple[list[str], list[str], str | None]:
    """One pass through stream-decision.md's flowchart for a single stream.

    Returns the maps and codec options *stream* contributes and the note it
    produces (or ``None``). ``counts`` is mutated so later streams see how many
    output streams of their type already exist.
    """
    structural = _structural_drop(profile, stream, counts)
    if structural is not None:
        return [], [], structural

    rule = profile.rules[stream.codec_type]
    position = counts.get(stream.codec_type, 0)
    maps = ["-map", f"0:{stream.index}"]
    if stream.codec_name in rule.copy_mask:
        codecs = list(_substitute_position(rule.accept_options, position))
        note = None
    elif rule.fallback_options is not None:
        codecs = list(_substitute_position(rule.fallback_options, position))
        note = _reencode_note(stream, rule.fallback_name) if rule.fallback_name else None
    else:
        reason = rule.drop_reason or f"not supported by {profile.label}"
        return [], [], _drop_note(stream, reason)

    counts[stream.codec_type] = position + 1
    return maps, codecs, note


def _build_selective(profile: Profile, streams: Sequence[Stream]) -> Attempt | None:
    """The engine-built rung: the PLAN and SEL nodes of degradation-ladder.md.

    Returns ``None`` when the rung would add nothing over the cheap attempt --
    either no stream survives at all, or the cheap attempt already selects
    streams explicitly and this plan gives up nothing worth naming.
    """
    maps: list[str] = []
    codecs: list[str] = []
    notes: list[str] = []
    counts: dict[str, int] = {}

    for stream in streams:
        stream_maps, stream_codecs, note = _decide_stream(profile, stream, counts)
        maps += stream_maps
        codecs += stream_codecs
        if note is not None:
            notes.append(note)

    if not maps:
        return None
    if profile.explicit_streams and not notes:
        return None
    return Attempt("selective", (*maps, *codecs), tuple(notes))


def first_attempt(profile: Profile) -> Attempt:
    """Rung 1 of degradation-ladder.md: *profile*'s own cheap attempt."""
    return _with_container_options(profile.cheap_attempt, profile)


def retries(profile: Profile, streams: Sequence[Stream]) -> list[Attempt]:
    """The rest of the ladder, built from the source's probed *streams*."""
    attempts: list[Attempt] = []
    selective = _build_selective(profile, streams)
    if selective is not None:
        attempts.append(_with_container_options(selective, profile))
    if profile.last_resort is not None:
        attempts.append(_with_container_options(profile.last_resort, profile))
    return attempts


def needs_verification(profile: Profile) -> bool:
    """Whether a successful cheap attempt is worth an ffprobe round-trip.

    True only for a profile whose cheap attempt is declared partial by
    construction (``docs/design/degradation-ladder.md``) -- the narrowed happy
    path in ``docs/constitution.md`` keeps every other profile's success
    probe-free.
    """
    return profile.partial_mapping


def verify_success(profile: Profile, streams: Sequence[Stream]) -> tuple[str, ...]:
    """The success-side verifier of degradation-ladder.md: what a partial cheap
    attempt's mapping could not have carried over, named per stream."""
    return _unmapped_notes(profile, streams)


def describe_unsupported(profile: Profile, streams: Sequence[Stream]) -> tuple[str, ...] | None:
    """The ``unsupported`` discriminator: "no rule matches any present stream".

    ``None`` means the source carries at least one stream type *profile* has a
    rule for -- that stream may still be dropped for shape or codec reasons, but
    that is a genuine ``failed``, not this (``docs/specs/spec-target-driven-cli.md``).
    Otherwise returns one drop note per stream, reusing D1 of
    ``docs/design/stream-decision.md`` so the reporting stays identical to an
    ordinary unsupported-type drop. Derived entirely from the probe, never from
    ffmpeg's stderr (``docs/constitution.md``).
    """
    if any(stream.codec_type in profile.rules for stream in streams):
        return None
    return tuple(_drop_note(stream, f"not supported by {profile.label}") for stream in streams)

"""The generic conversion engine: profile plus probed streams -> attempt ladder.

The engine holds no format-specific fact -- no codec name, no container option,
no degradation-note wording. Every such fact lives in the ``Profile`` it is
handed (``converter/profiles.py``) and is read out of that data, never written
here. The two exceptions are ``Job`` -- the public shape ``cli.py`` and
``batch.py`` already depend on -- and ``JOB_BINDINGS`` below it, which is CLI
wiring (source suffixes, sub-command name, progress-bar label) rather than
target-format knowledge, and is marked as phase-2 scaffolding: it disappears
once ``--to`` replaces the ``video``/``audio`` sub-commands
(``docs/specs/spec-profile-registry.md``).

See ``docs/design/degradation-ladder.md`` for the order of attempts this module
builds, and ``docs/design/stream-decision.md`` for how one stream's fate is
decided inside the engine-built rung.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace

from converter.ffmpegtool import Stream
from converter.profiles import MP4, WAV, Attempt, Profile


@dataclass(frozen=True)
class Job:
    """A source suffix, a target suffix, and how to get from one to the other.

    ``verify_success`` turns the source's stream list into the notes the *cheap*
    attempt owes once it has already succeeded, and is ``None`` for a cheap
    attempt whose mapping is exhaustive -- which is how ``batch.py`` knows
    whether that success is worth an ffprobe round-trip at all
    (``docs/design/degradation-ladder.md``).
    """

    name: str
    description: str
    suffixes: tuple[str, ...]
    target_suffix: str
    first_attempt: Callable[[], Attempt] = field(repr=False)
    retries: Callable[[Sequence[Stream]], list[Attempt]] = field(repr=False)
    verify_success: Callable[[Sequence[Stream]], tuple[str, ...]] | None = field(
        default=None, repr=False
    )


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


def make_attempts(
    profile: Profile,
) -> tuple[Callable[[], Attempt], Callable[[Sequence[Stream]], list[Attempt]]]:
    """Build the ``(first_attempt, retries)`` pair degradation-ladder.md needs."""

    def first_attempt() -> Attempt:
        return _with_container_options(profile.cheap_attempt, profile)

    def retries(streams: Sequence[Stream]) -> list[Attempt]:
        attempts: list[Attempt] = []
        selective = _build_selective(profile, streams)
        if selective is not None:
            attempts.append(_with_container_options(selective, profile))
        if profile.last_resort is not None:
            attempts.append(_with_container_options(profile.last_resort, profile))
        return attempts

    return first_attempt, retries


def make_verifier(profile: Profile) -> Callable[[Sequence[Stream]], tuple[str, ...]] | None:
    """Build the success-side verifier of degradation-ladder.md, if one is owed.

    A profile whose cheap attempt maps the source exhaustively gets ``None``, and
    its happy path then still costs no ffprobe round-trip -- the narrowed form of
    the rule in ``docs/constitution.md``.
    """
    if not profile.partial_mapping:
        return None

    def verify(streams: Sequence[Stream]) -> tuple[str, ...]:
        return _unmapped_notes(profile, streams)

    return verify


@dataclass(frozen=True)
class _Binding:
    """A source-pair binding: CLI-visible name plus which suffixes feed which
    profile. This is CLI wiring, not target-format knowledge -- the exemption
    the module docstring describes -- and is phase-2 scaffolding, removed once
    ``--to`` replaces the ``video``/``audio`` sub-commands.
    """

    name: str
    description: str
    suffixes: tuple[str, ...]
    profile: Profile


#: Phase-2 scaffolding (see the module docstring and ``_Binding``).
JOB_BINDINGS: dict[str, _Binding] = {
    "video": _Binding(
        name="mkv-to-mp4",
        description="Convert .mkv files to .mp4 (stream copy where possible)",
        suffixes=(".mkv",),
        profile=MP4,
    ),
    "audio": _Binding(
        name="opus-to-wav",
        description="Convert .opus files to uncompressed .wav",
        suffixes=(".opus",),
        profile=WAV,
    ),
}


def _job_from_binding(binding: _Binding) -> Job:
    """The factory the issue asks for: wire the generic engine to one profile."""
    first_attempt, retries = make_attempts(binding.profile)
    return Job(
        name=binding.name,
        description=binding.description,
        suffixes=binding.suffixes,
        target_suffix=binding.profile.target_suffix,
        first_attempt=first_attempt,
        retries=retries,
        verify_success=make_verifier(binding.profile),
    )


MKV_TO_MP4 = _job_from_binding(JOB_BINDINGS["video"])
OPUS_TO_WAV = _job_from_binding(JOB_BINDINGS["audio"])

#: Sub-command name -> job.
JOBS: dict[str, Job] = {"video": MKV_TO_MP4, "audio": OPUS_TO_WAV}

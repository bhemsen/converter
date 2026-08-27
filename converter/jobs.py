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
``docs/specs/archive/spec-target-driven-cli.md`` for the ``unsupported`` discriminator
:func:`describe_unsupported` implements.
"""

from collections.abc import Sequence
from dataclasses import replace
from typing import TypeVar

from converter.ffmpegtool import Stream
from converter.profiles import Attempt, Profile

#: What a stream is counted under -- either its full :func:`_stream_key` or its
#: bare type. :func:`_surplus` does the same arithmetic for both.
_K = TypeVar("_K")


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


def _rule_key(profile: Profile, stream: Stream) -> str:
    """PIC node of stream-decision.md: resolve *stream* to its rule key.

    An attached picture resolves to the ``"attached_pic"`` key when the profile
    declares one, falling back to ``codec_type`` -- the fallback that leaves a
    profile with no ``attached_pic`` rule byte-for-byte unchanged, since that is
    exactly what it already did.
    """
    if stream.attached_pic and "attached_pic" in profile.rules:
        return "attached_pic"
    return stream.codec_type


def _structural_drop(profile: Profile, stream: Stream, counts: dict[str, int]) -> str | None:
    """D1 and D2 of stream-decision.md: the drops the profile's *shape* forces.

    Split out because both verdicts are reached from the declared rules alone,
    without ever looking at the stream's codec. That is what lets the
    success-side verification in :func:`_predict_unmapped` reuse them without
    asserting anything about what an already-successful attempt encoded.
    """
    rule = profile.rules.get(_rule_key(profile, stream))
    if rule is None:
        return _drop_note(stream, f"not supported by {profile.label}")

    position = counts.get(stream.codec_type, 0)
    if rule.stream_limit is not None and position >= rule.stream_limit:
        return _drop_note(stream, _room_reason(profile, stream.codec_type, rule.stream_limit))
    return None


def _stream_key(stream: Stream) -> tuple[str, str, str]:
    """What a source stream and its counterpart in an output are matched by.

    Type, codec name *and* container tag. An index cannot serve: a stream the
    muxer put back on its own carries whatever index the output happens to give
    it -- the regenerated timecode of an iPhone MOV arrives at index 2 where its
    source sat at index 3.

    All three fields earn their place, each against a measured case (ffmpeg 9.0)
    where dropping it let :func:`confirm_drops` forgive the wrong drop:

    * codec name, because no profile declares a ``data`` rule, so by type alone
      a regenerated `tmcd` forgives the loss of `gpmd`/ANC telemetry in the same
      file -- telemetry reports ``bin_data``, a timecode reports no codec name;
    * container tag, because *any* MOV/MP4 track whose 4CC maps to no codec id
      demuxes with ``codec_id = NONE`` and so reports no codec name either. An
      Apple `mebx` metadata track -- every iPhone `.mov` carries one -- is then
      indistinguishable from the `tmcd` beside it, and the timecode's survival
      forgives the metadata track's genuine loss. Their tags differ, and a
      regenerated `tmcd` carries the same `tmcd` tag as its source.
    """
    return (stream.codec_type, stream.codec_name, stream.codec_tag)


def _predict_unmapped(
    profile: Profile, streams: Sequence[Stream]
) -> tuple[dict[tuple[str, str, str], int], tuple[tuple[tuple[str, str, str], str], ...]]:
    """What a structurally partial cheap attempt's *mapping* cannot have carried.

    Returns how many streams of each :func:`_stream_key` the mapping is expected
    to keep, and one ``(key, note)`` pair per stream it is expected to leave
    behind -- the key travels alongside the note so :func:`confirm_drops` can
    weigh the prediction against the file that was actually written.

    Only the structural verdicts above are consulted. Codec-level ones are
    deliberately left out: the cheap attempt has already exited 0, so whatever
    it did with a stream's codec worked, and announcing a re-encode it never
    performed would just swap one dishonest report for another.
    """
    predicted: list[tuple[tuple[str, str, str], str]] = []
    positions: dict[str, int] = {}
    kept: dict[tuple[str, str, str], int] = {}
    for stream in streams:
        note = _structural_drop(profile, stream, positions)
        if note is None:
            positions[stream.codec_type] = positions.get(stream.codec_type, 0) + 1
            kept[_stream_key(stream)] = kept.get(_stream_key(stream), 0) + 1
        else:
            predicted.append((_stream_key(stream), note))
    return kept, tuple(predicted)


def _count_keys(streams: Sequence[Stream]) -> dict[tuple[str, str, str], int]:
    """How many streams of each :func:`_stream_key` a probed stream list holds."""
    counts: dict[tuple[str, str, str], int] = {}
    for stream in streams:
        counts[_stream_key(stream)] = counts.get(_stream_key(stream), 0) + 1
    return counts


def _surplus(kept: dict[_K, int], produced: dict[_K, int]) -> dict[_K, int]:
    """How many streams the output holds beyond what the mapping expected to keep."""
    return {unit: max(count - kept.get(unit, 0), 0) for unit, count in produced.items()}


def _by_type(counts: dict[tuple[str, str, str], int]) -> dict[str, int]:
    """Collapse per-key counts onto the stream type alone.

    Derived from the per-key counts rather than counted a second time from the
    stream list, so the two readings :func:`confirm_drops` compares cannot drift.
    """
    totals: dict[str, int] = {}
    for (kind, _codec, _tag), count in counts.items():
        totals[kind] = totals.get(kind, 0) + count
    return totals


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

    rule = profile.rules[_rule_key(profile, stream)]
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
    attempt's mapping could not have carried over, named per stream.

    A *prediction*, drawn from the mapping alone. It has to be confirmed against
    the written file by :func:`confirm_drops` before it is reported, because a
    muxer may put back what no ``-map`` selected (issue #66).
    """
    _, predicted = _predict_unmapped(profile, streams)
    return tuple(note for _, note in predicted)


def confirm_drops(
    profile: Profile, streams: Sequence[Stream], produced: Sequence[Stream]
) -> tuple[str, ...]:
    """Keep only the predicted drops the written file does *not* in fact contain.

    A ``-map`` set says what ffmpeg was asked to carry, which is not the same as
    what the muxer wrote: MP4 and MOV regenerate a timecode track from source
    metadata, so a ``tmcd`` stream no selector names is in the output anyway
    (issue #66). Comparing what the two files *hold*, rather than reasoning about
    `tmcd` in particular, is what makes this general.

    A predicted drop is forgiven only when the output holds a surplus under
    **both** counts, and each forgiveness spends one of each budget. Neither
    count is sound alone, and each covers the other's blind spot:

    * By stream type alone, a regenerated `tmcd` would forgive the drop of a
      `gpmd`/ANC telemetry stream in the same file -- no profile declares a
      ``data`` rule, so every data stream in the output forgives one predicted
      data drop, whichever it actually was.
    * By :func:`_stream_key` alone, a cheap attempt that *re-encodes* makes the
      two sides disagree by construction: ``kept`` carries the source's codec
      name and the output carries the encoder's. WAV's ``-map 0:a:0 -c:a
      pcm_s16le`` over an ``[aac, pcm_s16le]`` source writes one ``pcm_s16le``
      stream, which reads as a surplus under that key and forgives the drop of
      the source's second, genuinely lost, ``pcm_s16le`` track. A re-encode
      preserves a stream's *type* but not its codec name, which is exactly why
      the type count is immune to that phantom.

    Both readings therefore have to agree before a note is dropped, and the
    surplus must cover *every* predicted drop sharing a key before any of them
    is forgiven. That last clause is what keeps the arithmetic from having to
    guess which of several indistinguishable streams survived: where the
    evidence is ambiguous, every candidate keeps its note. Over-reporting is a
    cost; picking the wrong one would mean claiming a loss that did not happen
    *and* falling silent about one that did (``docs/constitution.md``).
    """
    kept, predicted = _predict_unmapped(profile, streams)
    by_key = _surplus(kept, _count_keys(produced))
    by_type = _surplus(_by_type(kept), _by_type(_count_keys(produced)))
    forgiven: set[tuple[str, str, str]] = set()
    for key in dict.fromkeys(key for key, _note in predicted):
        wanted = sum(1 for other, _note in predicted if other == key)
        if by_key.get(key, 0) >= wanted and by_type.get(key[0], 0) >= wanted:
            by_type[key[0]] -= wanted
            forgiven.add(key)
    return tuple(note for key, note in predicted if key not in forgiven)


def describe_unsupported(profile: Profile, streams: Sequence[Stream]) -> tuple[str, ...] | None:
    """The ``unsupported`` discriminator: "no rule matches any present stream".

    ``None`` means the source carries at least one stream type *profile* has a
    rule for -- that stream may still be dropped for shape or codec reasons, but
    that is a genuine ``failed``, not this (``docs/specs/archive/spec-target-driven-cli.md``).
    ``None`` also for an *empty* stream list: that is the fingerprint of a probe
    that could not find anything to work with -- typically a corrupt or
    truncated source -- not positive evidence that the format holds nothing the
    profile could use, so it stays a genuine ``failed`` with ffmpeg's stderr
    rather than being reported as a silent, note-less ``unsupported``. Otherwise
    returns one drop note per stream, reusing D1 of
    ``docs/design/stream-decision.md`` so the reporting stays identical to an
    ordinary unsupported-type drop. Derived entirely from the probe, never from
    ffmpeg's stderr (``docs/constitution.md``).
    """
    if not streams or any(stream.codec_type in profile.rules for stream in streams):
        return None
    return tuple(_drop_note(stream, f"not supported by {profile.label}") for stream in streams)


# Invariant this discriminator leans on, and does not itself check: a profile's
# `last_resort` must never map a stream type it declares no rule for, or the
# short-circuit in `batch._attempt_conversion` -- which reports `unsupported`
# and never calls `retries()` -- would skip a rung that could have succeeded.
# Both shipped profiles satisfy this by construction (MP4's last resort maps
# only the video/audio types its own rules cover; WAV declares none at all),
# the same way `docs/design/degradation-ladder.md` already asks
# `partial_mapping` profiles to keep their rules and their cheap attempt in
# agreement.

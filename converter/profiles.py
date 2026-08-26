"""Declarative target-format profiles: value types, the registry, and lookup.

A leaf module by design (`docs/architecture.md`): it holds no ``from converter``
or ``import converter`` statement at all, so a target format can only ever be
data, never new logic. That is also why ``flags()`` and ``Attempt`` live here
instead of being imported from ``jobs.py`` -- importing them would break the
leaf property in the other direction.

``PROFILES`` is the target-name -> profile registry a target-driven CLI needs,
``resolve_target`` is how it looks a target up, and ``SOURCE_SUFFIXES`` is the
curated set of suffixes discovery walks (`docs/design/source-selection.md`) --
curated by hand for the same reason a profile's copy mask is: ffmpeg can be
asked what a file contains, never what it will accept as an input.

See ``docs/design/degradation-ladder.md`` for how the engine in ``jobs.py``
turns one profile into an ordered ladder of attempts, and
``docs/design/stream-decision.md`` for how it decides one stream's fate
against the profile's per-type rule.
"""

from dataclasses import dataclass


def flags(spec: str) -> tuple[str, ...]:
    """Split a command-line-shaped string into argv items.

    Recipes then read exactly like what you would type after ``ffmpeg -i in.mkv``,
    and flag/value pairs stay on one line regardless of how the formatter feels
    about trailing commas.  Only ever used for flags and their values -- paths go
    through :func:`converter.ffmpegtool.build_argv`, never through here.
    """
    return tuple(spec.split())


@dataclass(frozen=True)
class Attempt:
    """One ffmpeg option list, with a note of anything it sacrifices."""

    label: str
    options: tuple[str, ...]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class StreamRule:
    """How one stream type is handled: accept, re-encode, or drop.

    ``accept_options`` and ``fallback_options`` may carry the literal ``{n}``
    placeholder, which the engine replaces with the stream's position among
    output streams of its type. A rule whose ``stream_limit`` is 1 can only
    ever produce one output stream of its type, so it writes the bare
    specifier instead and leaves the placeholder out.
    """

    copy_mask: frozenset[str]
    accept_options: tuple[str, ...]
    fallback_options: tuple[str, ...] | None = None
    fallback_name: str | None = None
    stream_limit: int | None = None
    #: Why a stream is dropped when the copy mask misses and no fallback is
    #: declared -- irrelevant, and left ``None``, for a rule that always has one.
    drop_reason: str | None = None


@dataclass(frozen=True)
class Profile:
    """One target format, declared entirely as data.

    ``explicit_streams`` says whether ``cheap_attempt`` already selects streams
    by index (WAV's ``-map 0:a:0``) rather than blindly by type (MP4's
    ``-map 0:v?``) -- the one fact the engine cannot derive without parsing
    ffmpeg's own option syntax, per ``docs/design/degradation-ladder.md``.

    ``partial_mapping`` says whether ``cheap_attempt``'s mapping can, *by
    construction*, leave source streams unmapped. It is declared for the same
    reason ``explicit_streams`` is: deriving it would mean parsing the option
    list. A profile that declares it true is verified by an ffprobe round-trip
    even when its cheap attempt exits 0, so a stream that attempt silently left
    behind is named rather than reported as a plain success
    (``docs/design/degradation-ladder.md``).

    ``name`` is the registry key and the ``--to`` token (``"mp4"``); ``label``
    stays the display form ``--list-formats`` and progress bars print
    (``"MP4"``). ``description`` is the one-line explanation
    ``--list-formats`` and the interactive prompt print next to ``name``.
    """

    label: str
    name: str
    description: str
    target_suffix: str
    container_options: tuple[str, ...]
    cheap_attempt: Attempt
    explicit_streams: bool
    partial_mapping: bool
    rules: dict[str, StreamRule]
    last_resort: Attempt | None = None


#: Move the MP4 index to the front so the file plays before it is fully read.
FASTSTART = flags("-movflags +faststart")

#: Codecs a standard MP4 container accepts, so they can be stream-copied.
MP4_VIDEO_CODECS = frozenset({"h264", "hevc", "av1", "vp9", "mpeg4", "mpeg2video", "mjpeg"})
MP4_AUDIO_CODECS = frozenset({"aac", "mp3", "ac3", "eac3", "alac", "opus", "flac"})
#: Subtitle codecs that convert cleanly into MP4's own ``mov_text``.
TEXT_SUBTITLE_CODECS = frozenset({"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"})

MP4 = Profile(
    label="MP4",
    name="mp4",
    description="Video: copies compatible streams, re-encodes the rest to h264/aac",
    target_suffix=".mp4",
    container_options=FASTSTART,
    # Deliberately not "-map 0": that also selects MKV attachments (font files
    # for ASS subtitles) and data streams, which MP4 cannot hold, so an
    # otherwise perfectly remuxable file would fail. The trailing "?" makes
    # each selector optional instead of fatal.
    cheap_attempt=Attempt(
        label="remux",
        options=flags("-map 0:v? -map 0:a? -map 0:s? -c copy -c:s mov_text"),
    ),
    explicit_streams=False,
    # The same "?" selectors that make the remux survivable also make it
    # incomplete: nothing selects attachments or data streams, so a source
    # carrying either loses it without ffmpeg ever complaining.
    partial_mapping=True,
    rules={
        "video": StreamRule(
            copy_mask=MP4_VIDEO_CODECS,
            accept_options=flags("-c:v:{n} copy"),
            fallback_options=flags("-c:v:{n} libx264 -crf:v:{n} 18"),
            fallback_name="h264",
        ),
        "audio": StreamRule(
            copy_mask=MP4_AUDIO_CODECS,
            accept_options=flags("-c:a:{n} copy"),
            fallback_options=flags("-c:a:{n} aac -b:a:{n} 192k"),
            fallback_name="aac",
        ),
        "subtitle": StreamRule(
            copy_mask=TEXT_SUBTITLE_CODECS,
            # A cheap in-kind transcode, not a literal copy: MP4 only holds
            # text subtitles as its own mov_text.
            accept_options=flags("-c:s:{n} mov_text"),
            drop_reason="bitmap subtitles cannot be stored in MP4",
        ),
    },
    last_resort=Attempt(
        label="re-encode",
        options=flags(
            "-map 0:v:0? -map 0:a? "
            "-c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "
            "-c:a aac -b:a 192k"
        ),
        notes=(
            "re-encoded to h264/aac (lossy); subtitles and extra video streams dropped",
            "10-bit or HDR sources are reduced to 8-bit yuv420p for player compatibility",
        ),
    ),
)

WAV = Profile(
    label="WAV",
    name="wav",
    description="Audio: single stream, uncompressed 16-bit PCM",
    target_suffix=".wav",
    container_options=(),
    # The stream is selected explicitly rather than left to ffmpeg's implicit
    # "best stream" heuristic, so a file with several audio streams converts
    # predictably instead of quietly depending on which one ffmpeg prefers.
    cheap_attempt=Attempt(label="pcm_s16le", options=flags("-map 0:a:0 -c:a pcm_s16le")),
    explicit_streams=True,
    # One index is named and nothing else is, so every further stream the
    # source carries -- a second audio track, cover art -- is left behind.
    partial_mapping=True,
    rules={
        "audio": StreamRule(
            # Empty by construction: WAV holds nothing as-is, only PCM.
            copy_mask=frozenset(),
            # Never emitted -- the empty copy mask means the accept branch of
            # stream-decision.md can never be reached -- so it carries no
            # placeholder either, same as the fallback below.
            accept_options=(),
            fallback_options=flags("-c:a pcm_s16le"),
            # No fallback_name: decoding to PCM is the definition of WAV, not
            # a loss, so the re-encode carries no note.
            stream_limit=1,
        ),
    },
)

MP3 = Profile(
    label="MP3",
    name="mp3",
    description="Audio: single stream, MP3 (libmp3lame if re-encoded)",
    target_suffix=".mp3",
    container_options=(),
    # Blind by type, not by index: the mp3 muxer -- not this mapping --
    # enforces "at most one audio stream" (measured against ffmpeg 9.0,
    # docs/specs/spec-audio-formats.md), so a second stream fails the cheap
    # attempt outright rather than needing an index-based selector to keep it
    # out; that is what lets stream_limit=1 coexist with a blind "-map 0:a?"
    # below, the muxer-enforced exemption docs/design/degradation-ladder.md
    # names, rather than WAV's index-named one.
    cheap_attempt=Attempt(
        label="remux",
        options=flags("-map 0:a? -c:a copy"),
        # partial_mapping's success-side verification (docs/design/degradation-
        # ladder.md) already names a dropped stream precisely when the ladder
        # actually drops one; this line is the standing note the audio-formats
        # spec's gate chose to keep alongside it -- always true, so it costs
        # nothing to state even for the many files that had nothing to lose.
        notes=("non-audio streams, including cover art, are not carried into MP3",),
    ),
    explicit_streams=False,
    # "-map 0:a?" selects no video, subtitle or attachment stream, so any of
    # those a source carries is left behind without ffmpeg ever complaining.
    partial_mapping=True,
    rules={
        "audio": StreamRule(
            copy_mask=frozenset({"mp3"}),
            # stream_limit=1 means at most one output audio stream ever exists,
            # so the position placeholder StreamRule's docstring describes is
            # left out -- there is only ever "{n} == 0" to substitute.
            accept_options=flags("-c:a copy"),
            fallback_options=flags("-c:a libmp3lame -q:a 2"),
            fallback_name="mp3",
            stream_limit=1,
        ),
    },
    last_resort=Attempt(
        label="re-encode",
        options=flags("-map 0:a:0 -c:a libmp3lame -q:a 2"),
        # Rescues the one case the selective rung cannot: a mask hit whose
        # -c:a copy the mp3 muxer refuses regardless. Explicit-index, so unlike
        # the selective rung it cannot name a per-stream drop itself -- this is
        # the only place that information about it exists.
        notes=(
            "non-audio streams, and any audio stream beyond the first, are not carried into MP3",
        ),
    ),
)

FLAC = Profile(
    label="FLAC",
    name="flac",
    description="Audio: single stream, lossless FLAC",
    target_suffix=".flac",
    container_options=(),
    # Same blind-by-type shape and the same reason as MP3's above: the flac
    # muxer enforces "at most one audio stream" itself.
    cheap_attempt=Attempt(
        label="remux",
        options=flags("-map 0:a? -c:a copy"),
        notes=("non-audio streams, including cover art, are not carried into FLAC",),
    ),
    explicit_streams=False,
    partial_mapping=True,
    rules={
        "audio": StreamRule(
            copy_mask=frozenset({"flac"}),
            accept_options=flags("-c:a copy"),
            fallback_options=flags("-c:a flac"),
            # No fallback_name: encoding into a container's own lossless codec
            # gives up nothing, the same rule WAV's PCM fallback carries.
            stream_limit=1,
        ),
    },
    last_resort=Attempt(
        label="re-encode",
        options=flags("-map 0:a:0 -c:a flac"),
        # Unlike MP3's, this note names no codec loss -- flac is lossless --
        # only the streams -map 0:a:0 cannot reach, the same information MP3's
        # last-resort note carries for the same structural reason.
        notes=(
            "non-audio streams, and any audio stream beyond the first, are not carried into FLAC",
        ),
    ),
)

#: Target name -> profile. Built from each profile's own ``name`` rather than
#: repeating it as a literal key, so the two can never drift apart.
PROFILES: dict[str, Profile] = {profile.name: profile for profile in (MP4, WAV, MP3, FLAC)}

#: The curated set of suffixes discovery walks (`docs/design/source-selection.md`):
#: a file is a candidate only if its suffix is in this set, never discovered from
#: what ffmpeg happens to accept. Phase 2 seeds it with exactly what the old
#: ``video``/``audio`` sub-commands read (``.mkv``, ``.opus``) plus each shipped
#: profile's own target suffix (``.mp4``, ``.wav``) -- the latter is what lets a
#: source that already carries the target suffix take part in selection at all
#: (the self-write and existing-output-skip cases `source-selection.md` and this
#: phase's QA gate both need). Phase 3 (issue #20, `spec-audio-formats.md`) widens
#: it three ways: the audio containers people actually have that were not yet
#: readable as a source, the video containers a "rip the audio" run needs, and the
#: remaining audio target suffixes (``.mp3``, ``.m4a``, ``.flac``, ``.ogg``) so the
#: profiles this milestone still adds already have their own suffix covered when
#: they land -- `.opus` and `.wav` are covered already. Phase 4 (issue #26,
#: `spec-video-formats.md`) widens it once more with the video containers no
#: earlier phase added, ahead of the `mkv`/`webm`/`mov` profiles that milestone
#: still adds. Phase 5 (issue #33, `spec-image-formats.md`) widens it once more
#: with the image containers the seven image profiles that milestone still adds
#: will need, ahead of those profiles landing. None of them re-adds a suffix this
#: set already holds.
SOURCE_SUFFIXES: frozenset[str] = frozenset(
    {
        # phase 2: old sub-commands plus the two shipped profiles' own suffixes
        ".mkv",
        ".mp4",
        ".opus",
        ".wav",
        # phase 3: audio containers people actually have
        ".aac",
        ".m4b",
        ".wma",
        ".aiff",
        ".aif",
        ".ape",
        ".wv",
        ".caf",
        # phase 3: video containers a "rip the audio" run needs
        ".mov",
        ".avi",
        ".webm",
        ".m4v",
        ".wmv",
        ".flv",
        # phase 3: the remaining audio target suffixes, ahead of their profiles
        ".mp3",
        ".m4a",
        ".flac",
        ".ogg",
        # phase 4: video containers no earlier phase added
        ".mpg",
        ".mpeg",
        ".ts",
        ".m2ts",
        ".mts",
        ".vob",
        ".ogv",
        ".3gp",
        # phase 5: image containers ahead of the seven image profiles
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
)


def resolve_target(target: str) -> Profile:
    """Look up *target* in ``PROFILES``, accepting a name or a dotted suffix.

    ``mp4``, ``MP4`` and ``.mp4`` all resolve to the same profile (Prior
    decisions, ``spec-target-driven-cli.md``). An unknown target is a usage
    error, not a conversion failure -- the same shape as ``--jobs`` being out
    of range -- so it is raised as a plain ``ValueError`` for ``cli.py`` to
    turn into its exit-2 ``UsageError``, with a message that lists every
    target actually available rather than just naming the typo.
    """
    name = target.lower().removeprefix(".")
    try:
        return PROFILES[name]
    except KeyError:
        available = ", ".join(sorted(PROFILES))
        raise ValueError(f"unknown target {target!r}; available targets: {available}") from None

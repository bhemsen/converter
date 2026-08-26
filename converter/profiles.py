"""Declarative target-format profiles: value types plus the MP4 and WAV entries.

A leaf module by design (`docs/architecture.md`): it holds no ``from converter``
or ``import converter`` statement at all, so a target format can only ever be
data, never new logic. That is also why ``flags()`` and ``Attempt`` live here
instead of being imported from ``jobs.py`` -- importing them would break the
leaf property in the other direction.

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
    """

    label: str
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

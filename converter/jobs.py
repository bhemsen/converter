"""The conversion recipes, expressed as ffmpeg option lists.

Each job is a cheap first attempt plus an optional ladder of fallbacks that is
only consulted -- and only pays for an ffprobe round-trip -- once the first
attempt has actually failed.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from converter.ffmpegtool import Stream

#: Codecs a standard MP4 container accepts, so they can be stream-copied.
MP4_VIDEO_CODECS = frozenset({"h264", "hevc", "av1", "vp9", "mpeg4", "mpeg2video", "mjpeg"})
MP4_AUDIO_CODECS = frozenset({"aac", "mp3", "ac3", "eac3", "alac", "opus", "flac"})
#: Subtitle codecs that convert cleanly into MP4's own ``mov_text``.
TEXT_SUBTITLE_CODECS = frozenset({"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"})

#: Move the MP4 index to the front so the file plays before it is fully read.
FASTSTART = ("-movflags", "+faststart")


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
class Job:
    """A source suffix, a target suffix, and how to get from one to the other."""

    name: str
    description: str
    suffixes: tuple[str, ...]
    target_suffix: str
    first_attempt: Callable[[], Attempt] = field(repr=False)
    retries: Callable[[Sequence[Stream]], list[Attempt]] = field(repr=False)


def mp4_remux() -> Attempt:
    """Stream-copy everything a viewer cares about: lossless and near-instant."""
    # Deliberately not "-map 0": that also selects MKV attachments (font files
    # for ASS subtitles) and data streams, which MP4 cannot hold, so an
    # otherwise perfectly remuxable file would fail.  The trailing "?" makes
    # each selector optional instead of fatal.
    return Attempt(
        label="remux",
        options=flags("-map 0:v? -map 0:a? -map 0:s? -c copy -c:s mov_text") + FASTSTART,
    )


def _mp4_selective(streams: Sequence[Stream]) -> Attempt | None:
    """Copy what MP4 accepts, re-encode what it does not, drop what it cannot hold.

    Output stream specifiers such as ``-c:a:1`` count per type in mapping order,
    which is exactly what the per-type counters below track.
    """
    maps: list[str] = []
    codecs: list[str] = []
    notes: list[str] = []
    seen = {"video": 0, "audio": 0, "subtitle": 0}

    for stream in streams:
        codec = stream.codec_name or "unknown"
        if stream.codec_type == "video":
            position = seen["video"]
            maps += ["-map", f"0:{stream.index}"]
            if stream.codec_name in MP4_VIDEO_CODECS:
                codecs += [f"-c:v:{position}", "copy"]
            else:
                codecs += [f"-c:v:{position}", "libx264", f"-crf:v:{position}", "18"]
                notes.append(f"video stream {stream.index} ({codec}) re-encoded to h264")
            seen["video"] += 1
        elif stream.codec_type == "audio":
            position = seen["audio"]
            maps += ["-map", f"0:{stream.index}"]
            if stream.codec_name in MP4_AUDIO_CODECS:
                codecs += [f"-c:a:{position}", "copy"]
            else:
                codecs += [f"-c:a:{position}", "aac", f"-b:a:{position}", "192k"]
                notes.append(f"audio stream {stream.index} ({codec}) re-encoded to aac")
            seen["audio"] += 1
        elif stream.codec_type == "subtitle":
            if stream.codec_name in TEXT_SUBTITLE_CODECS:
                position = seen["subtitle"]
                maps += ["-map", f"0:{stream.index}"]
                codecs += [f"-c:s:{position}", "mov_text"]
                seen["subtitle"] += 1
            else:
                notes.append(
                    f"subtitle stream {stream.index} ({codec}) dropped: "
                    "bitmap subtitles cannot be stored in MP4"
                )
        else:
            notes.append(
                f"{stream.codec_type or 'unknown'} stream {stream.index} dropped: "
                "not supported by MP4"
            )

    if not maps:
        return None
    return Attempt("selective", (*maps, *codecs, *FASTSTART), tuple(notes))


def mp4_reencode() -> Attempt:
    """Last resort: one video and all audio streams, re-encoded for compatibility."""
    return Attempt(
        label="re-encode",
        options=flags(
            "-map 0:v:0? -map 0:a? "
            "-c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "
            "-c:a aac -b:a 192k"
        )
        + FASTSTART,
        notes=(
            "re-encoded to h264/aac (lossy); subtitles and extra video streams dropped",
            "10-bit or HDR sources are reduced to 8-bit yuv420p for player compatibility",
        ),
    )


def mp4_retries(streams: Sequence[Stream]) -> list[Attempt]:
    """The fallback ladder for MKV -> MP4, most conservative first."""
    attempts = []
    selective = _mp4_selective(streams)
    if selective is not None:
        attempts.append(selective)
    attempts.append(mp4_reencode())
    return attempts


def wav_pcm() -> Attempt:
    """Decode the first audio stream to signed 16-bit PCM.

    The stream is selected explicitly rather than left to ffmpeg's implicit
    "best stream" heuristic, so a file with several audio streams converts
    predictably instead of quietly depending on which one ffmpeg prefers.
    Mapping audio only also drops any embedded cover art, which WAV cannot hold.
    """
    return Attempt(label="pcm_s16le", options=flags("-map 0:a:0 -c:a pcm_s16le"))


def wav_retries(streams: Sequence[Stream]) -> list[Attempt]:
    """WAV holds a single audio stream, so fall back to keeping just the first."""
    audio = [stream for stream in streams if stream.codec_type == "audio"]
    if len(audio) <= 1:
        return []
    return [
        Attempt(
            label="first-audio-stream",
            options=("-map", f"0:{audio[0].index}", "-c:a", "pcm_s16le"),
            notes=(
                f"{len(audio)} audio streams present; kept stream {audio[0].index} "
                "only (WAV holds one)",
            ),
        )
    ]


MKV_TO_MP4 = Job(
    name="mkv-to-mp4",
    description="Convert .mkv files to .mp4 (stream copy where possible)",
    suffixes=(".mkv",),
    target_suffix=".mp4",
    first_attempt=mp4_remux,
    retries=mp4_retries,
)

OPUS_TO_WAV = Job(
    name="opus-to-wav",
    description="Convert .opus files to uncompressed .wav",
    suffixes=(".opus",),
    target_suffix=".wav",
    first_attempt=wav_pcm,
    retries=wav_retries,
)

#: Sub-command name -> job.
JOBS: dict[str, Job] = {"video": MKV_TO_MP4, "audio": OPUS_TO_WAV}

"""Thin wrapper around the ``ffmpeg`` / ``ffprobe`` command-line programs.

We shell out on purpose instead of using a wrapper library.  ``ffmpeg-python``
has had no release since 2019, the PyPI package literally named ``ffmpeg`` is an
unrelated stub that collides with it in ``site-packages/ffmpeg/``, and ``pydub``
imports the ``audioop`` stdlib module that PEP 594 removed in Python 3.13.  All
three only ever assembled an argv list and called ffmpeg -- which is what this
module does, in fewer lines and without the dependency.

No shell is ever involved: every invocation is an argv list.
"""

import json
import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from shutil import which

#: Flags that every invocation receives.
#:
#: ``-nostdin`` is the load-bearing one.  Without it ffmpeg reads the console
#: stdin it inherits, so concurrent conversions fight over the same terminal --
#: and if the output file already exists, ffmpeg blocks on an "overwrite?"
#: prompt that a background worker can never answer.
BASE_FLAGS: tuple[str, ...] = ("-nostdin", "-hide_banner", "-loglevel", "error")

INSTALL_HINT = (
    "Install it and make sure it is on PATH:\n"
    "  Windows: winget install Gyan.FFmpeg\n"
    "  macOS:   brew install ffmpeg\n"
    "  Linux:   sudo apt install ffmpeg\n"
    "See https://ffmpeg.org/download.html for other options."
)


class FfmpegMissingError(RuntimeError):
    """The ``ffmpeg`` or ``ffprobe`` executable could not be located."""


class ProbeError(RuntimeError):
    """``ffprobe`` could not describe an input file."""


@dataclass(frozen=True)
class Tools:
    """Absolute paths to the two executables we drive."""

    ffmpeg: str
    ffprobe: str


@dataclass(frozen=True)
class Stream:
    """One elementary stream of a media file, as reported by ffprobe."""

    index: int
    codec_type: str
    codec_name: str


@dataclass(frozen=True)
class CommandResult:
    """Outcome of a single subprocess invocation."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def cli_path(path: str | os.PathLike[str]) -> str:
    """Render *path* so ffmpeg cannot mistake it for an option.

    A file called ``-vf`` is a perfectly legal filename, and ffmpeg would parse
    it as a flag.  Anchoring it to the current directory keeps the exact same
    target while guaranteeing the argument never starts with a dash.
    """
    text = os.fspath(path)
    if text.startswith("-"):
        # os.path.join, not pathlib: PurePath("./-vf") normalises straight back
        # to "-vf" and would undo the very thing this guard is for.
        return os.path.join(os.curdir, text)  # noqa: PTH118
    return text


def build_argv(
    ffmpeg: str,
    src: str | os.PathLike[str],
    options: Sequence[str],
    dst: str | os.PathLike[str],
) -> list[str]:
    """Assemble a full ffmpeg command line.

    ``-y`` is always passed.  Whether an existing output may be replaced is
    decided in Python before we get here -- ffmpeg's own ``-n`` does not "skip"
    a present file, it aborts with a non-zero exit status, which would make
    every already-converted file look like a failure.

    Note that no ``--`` separator is used: ffmpeg treats ``-i`` as a group
    separator and would swallow ``--`` as the input filename.  ``cli_path``
    handles dash-leading names instead.
    """
    return [
        ffmpeg,
        *BASE_FLAGS,
        "-y",
        "-i",
        cli_path(src),
        *options,
        cli_path(dst),
    ]


def run(argv: Sequence[str], *, timeout: float | None = None) -> CommandResult:
    """Run *argv* with no shell and no inherited stdin."""
    argv = list(argv)
    completed = subprocess.run(  # noqa: S603 - argv list, shell=False, no interpolation
        argv,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return CommandResult(
        argv=tuple(argv),
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=(completed.stderr or "").strip(),
    )


def _is_on_path(directory: Path) -> bool:
    """Is *directory* genuinely one of the PATH entries?"""
    entries = os.environ.get("PATH", "").split(os.pathsep)
    return any(entry and Path(entry).resolve() == directory for entry in entries)


def _locate(name: str, override: str | None) -> str:
    """Resolve *name*, or the user's *override*, to an executable path."""
    wanted = override or name

    # A bare command name is looked up on PATH; anything carrying a directory
    # component is an explicit path the user picked deliberately.
    if Path(wanted).name != wanted:
        candidate = Path(wanted)
        if not candidate.is_file():
            raise FfmpegMissingError(f"{name}: {wanted!r} is not a file.")
        return os.fspath(candidate.resolve())

    found = which(wanted)
    if found is None:
        hint = "" if override else f"\n{INSTALL_HINT}"
        raise FfmpegMissingError(f"{name} was not found on PATH (looked for {wanted!r}).{hint}")

    # On Python 3.11, shutil.which() searches the current directory first on
    # Windows, so running the tool from a directory that happens to contain an
    # ffmpeg.exe would silently execute that one instead of the installed one.
    # Python 3.12 dropped that behaviour; this keeps 3.11 honest as well.
    directory = Path(found).parent.resolve()
    if directory == Path.cwd() and not _is_on_path(directory):
        raise FfmpegMissingError(
            f"refusing to use {found}: it sits in the current directory, "
            f"which is not on PATH.\n{INSTALL_HINT}"
        )
    return found


def resolve_tools(ffmpeg: str | None = None, ffprobe: str | None = None) -> Tools:
    """Locate ffmpeg and ffprobe, or raise with an actionable message.

    Checked once up front, so a missing ffmpeg fails with one clear error
    instead of one confusing error per input file.
    """
    return Tools(ffmpeg=_locate("ffmpeg", ffmpeg), ffprobe=_locate("ffprobe", ffprobe))


def version(tools: Tools) -> str:
    """Return ffmpeg's version banner line, or a placeholder if unreadable."""
    result = run([tools.ffmpeg, "-version"])
    if not result.ok:
        return "unknown"
    first_line = result.stdout.splitlines()[0] if result.stdout else ""
    return first_line.strip() or "unknown"


def probe_streams(tools: Tools, src: str | os.PathLike[str]) -> list[Stream]:
    """List the elementary streams of *src*.

    Only called after a stream-copy attempt has already failed, so the ffprobe
    round-trip is never on the happy path.
    """
    result = run(
        [
            tools.ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=index,codec_type,codec_name",
            "-of",
            "json",
            cli_path(src),
        ]
    )
    if not result.ok:
        raise ProbeError(result.stderr or f"ffprobe exited with {result.returncode}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - malformed ffprobe output
        raise ProbeError(f"could not parse ffprobe output: {exc}") from exc

    streams = []
    for raw in payload.get("streams", []):
        try:
            index = int(raw["index"])
        except (KeyError, TypeError, ValueError):
            continue
        streams.append(
            Stream(
                index=index,
                codec_type=str(raw.get("codec_type", "")),
                codec_name=str(raw.get("codec_name", "")),
            )
        )
    return streams

"""Thin wrapper around the ``ffmpeg`` / ``ffprobe`` command-line programs.

We shell out on purpose instead of using a wrapper library.  ``ffmpeg-python``
has had no release since 2019, the PyPI package literally named ``ffmpeg`` is an
unrelated stub that collides with it in ``site-packages/ffmpeg/``, and ``pydub``
imports the ``audioop`` stdlib module that PEP 594 removed in Python 3.13.  All
three only ever assembled an argv list and called ffmpeg -- which is what this
module does, in fewer lines and without the dependency.

No shell is ever involved: every invocation is an argv list.
"""

import contextlib
import ctypes
import json
import os
import subprocess
import sys
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import Any

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


class Terminated(BaseException):
    """Raised by :func:`run` once :func:`terminate_all` has closed the registry.

    Subclasses ``BaseException``, not ``Exception``: a worker's ``except
    Exception`` handler for an ordinary ffmpeg failure must never swallow a
    termination in flight, the same way ``KeyboardInterrupt`` is not an
    ``Exception`` either.
    """


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
    #: The container's own four-character code (``avc1``, ``tmcd``, ``mebx``).
    #: Carried because it is the only thing that tells two data tracks apart:
    #: any MOV/MP4 track whose 4CC ffmpeg maps to no codec id demuxes with
    #: ``codec_id = NONE`` and ffprobe then omits ``codec_name`` entirely, so a
    #: regenerated timecode and an iPhone metadata track are indistinguishable
    #: without it (measured, ffmpeg 9.0). Defaults to empty so a caller that
    #: does not care -- every test that builds a Stream by hand -- can leave it
    #: out. Read by :func:`converter.jobs.confirm_drops`, nothing else.
    codec_tag: str = ""
    #: Whether ffprobe's ``disposition`` object flags this stream as an
    #: embedded picture (cover art). Not a general disposition set -- only
    #: this one flag has a decision resting on it, because ``mjpeg`` and
    #: ``png`` are the codec of both a cover picture and a real video and
    #: nothing else distinguishes them (docs/specs/archive/spec-stream-disposition.md).
    #: Defaults to false so existing construction sites are unaffected.
    attached_pic: bool = False
    #: The stream's reported pixel format (``yuv420p``, ``rgba``, ``pal8``,
    #: ...) -- meaningful for a video stream only. In ffprobe's ``-of json``
    #: output the ``pix_fmt`` key is simply **absent** for a non-video stream,
    #: not the string ``"N/A"`` (that string is only ever produced by
    #: ffprobe's default/CSV writers), so this defaults to empty the same way
    #: ``codec_name``/``codec_tag`` above do. Feeds the within-stream
    #: transparency verdict against
    #: :data:`converter.profiles.ALPHA_FREE_PIX_FMTS`
    #: (docs/specs/archive/spec-within-stream-loss-notes.md, issue #105).
    pix_fmt: str = ""


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
    output_format: str | None = None,
) -> list[str]:
    """Assemble a full ffmpeg command line.

    ``-y`` is always passed.  Whether an existing output may be replaced is
    decided in Python before we get here -- ffmpeg's own ``-n`` does not "skip"
    a present file, it aborts with a non-zero exit status, which would make
    every already-converted file look like a failure.

    Note that no ``--`` separator is used: ffmpeg treats ``-i`` as a group
    separator and would swallow ``--`` as the input filename.  ``cli_path``
    handles dash-leading names instead.

    *output_format*, when given, is emitted as ``-f <output_format>`` directly
    before the output path. Writing to a ``.partial`` name defeats ffmpeg's own
    suffix-based muxer choice, so the caller passes the profile's declared
    ``muxer`` here to force the same choice ffmpeg would have made writing
    straight to the final path (``docs/specs/archive/spec-abort-safe-writes.md``).
    Omitted (``None``) by default, so every existing call site -- and every
    argv pin in ``tests/test_argv.py`` -- is unaffected.
    """
    return [
        ffmpeg,
        *BASE_FLAGS,
        "-y",
        "-i",
        cli_path(src),
        *options,
        *(("-f", output_format) if output_format is not None else ()),
        cli_path(dst),
    ]


#: Guards `_shutdown` and `_live_processes` below, and is held across `run`'s
#: `Popen` call too -- spawning is quick, and holding it there is what makes
#: spawn-and-register atomic with `terminate_all`'s flag-flip-and-snapshot.
#: Never held across a process's `communicate()`/`wait()`: `terminate_all`
#: releases it before waiting on a process, so a slow ffmpeg exit never
#: blocks another worker from registering or checking the flag.
_lock = threading.Lock()

#: Live `Popen` objects, keyed by `id()` so two processes can never collide.
_live_processes: dict[int, subprocess.Popen[str]] = {}

#: One-way for the life of the process: production code only ever sets this,
#: never clears it. Tests reset it through the autouse fixture in
#: tests/conftest.py, via `_reset_termination_state_for_tests` below.
_shutdown = False


def terminated() -> bool:
    """Whether :func:`terminate_all` has been called in this process."""
    return _shutdown


def terminate_all(timeout: float = 10.0) -> None:
    """Close the registry to new spawns, then kill and reap every live process.

    Setting the flag and snapshotting the registry happens under `_lock`, the
    same lock `run` holds while it spawns and registers -- so a process whose
    `Popen` call is still in flight when this runs is either not registered
    yet (and `run` will see the flag and refuse to let it loose) or already
    registered (and is in the snapshot here). Either way nothing spawned
    around a call to this function escapes it. The actual kill/reap happens
    outside the lock, since a slow process exit must not block `run` from
    registering or checking the flag for an unrelated file.
    """
    global _shutdown
    with _lock:
        _shutdown = True
        processes = list(_live_processes.values())
    for process in processes:
        process.kill()
    for process in processes:
        # A process that ignores its kill signal (stuck in uninterruptible
        # I/O) must not stall the whole shutdown -- give up on it after
        # *timeout* and move on to reaping the rest.
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=timeout)


def _reset_termination_state_for_tests() -> None:
    """Clear the shutdown flag and registry between tests.

    Production code never calls this -- the flag is one-way. Exists because
    `tests/test_cli.py` calls `cli.main` repeatedly inside one pytest process,
    so without a reset the first SIGTERM/Ctrl+C test would leave every later
    test unable to spawn anything.
    """
    global _shutdown
    with _lock:
        _shutdown = False
        _live_processes.clear()


def run(argv: Sequence[str], *, timeout: float | None = None) -> CommandResult:
    """Run *argv* with no shell and no inherited stdin.

    The spawn and the registration into the live-process registry happen
    under the same lock as :func:`terminate_all`'s flag flip, so a shutdown
    racing a spawn can never observe a process that is running but not yet
    registered (see that function's docstring). Once the shutdown flag is
    set, a call here raises :class:`Terminated` before touching the process
    table at all.

    On a timeout this mirrors what ``subprocess.run`` itself does: kill the
    process, drain its pipes so it is properly reaped rather than left a
    zombie, then re-raise ``TimeoutExpired`` to the caller. The same happens
    for *any* exception out of ``communicate()`` -- not just a timeout --
    because a ``KeyboardInterrupt`` or a :class:`Terminated` raised by a
    signal handler can land here on the calling thread just as easily, and
    letting the process outlive that exception would orphan it outside the
    registry (it is deregistered in the ``finally`` below either way).
    """
    argv = list(argv)
    with _lock:
        if _shutdown:
            raise Terminated
        process = subprocess.Popen(  # noqa: S603 - argv list, shell=False, no interpolation
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
        )
        _live_processes[id(process)] = process
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except BaseException:
        process.kill()
        process.communicate()
        raise
    finally:
        with _lock:
            _live_processes.pop(id(process), None)
    return CommandResult(
        argv=tuple(argv),
        returncode=process.returncode,
        stdout=stdout or "",
        stderr=(stderr or "").strip(),
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


def _parse_stream(raw: dict[str, object]) -> Stream | None:
    """Build a :class:`Stream` from one ffprobe JSON stream object.

    Returns ``None`` for an entry with no usable index, so the caller can drop
    it without duplicating the guard. Split out of :func:`probe_streams` to
    keep that function under the constitution's 50-line ceiling.
    """
    try:
        index = int(raw["index"])
    except (KeyError, TypeError, ValueError):
        return None
    # A stream with no disposition flagged at all -- most of them -- omits
    # the "disposition" object entirely rather than reporting zeros, so the
    # fallback to {} is what makes attached_pic default to false.
    disposition = raw.get("disposition") or {}
    return Stream(
        index=index,
        codec_type=str(raw.get("codec_type", "")),
        codec_name=str(raw.get("codec_name", "")),
        codec_tag=str(raw.get("codec_tag_string", "")),
        attached_pic=bool(disposition.get("attached_pic", 0)),
        # Absent entirely for a non-video stream, not "N/A" -- that string is
        # only ever produced by ffprobe's default/CSV writers, never by its
        # JSON one, so the plain str(..., "") fallback every other field above
        # already uses is correct here too.
        pix_fmt=str(raw.get("pix_fmt", "")),
    )


def probe_streams(tools: Tools, src: str | os.PathLike[str]) -> list[Stream]:
    """List the elementary streams of *src*.

    Called once per file, and never for a cheap attempt whose mapping is
    exhaustive: either after an attempt has failed, or -- when the profile
    declares its cheap attempt partial by construction -- to name what that
    attempt could not carry. A run that is about to report such a loss calls it
    once more, on the *output* file, to confirm the claim against what the muxer
    actually wrote (``docs/design/degradation-ladder.md``).
    """
    result = run(
        [
            tools.ffprobe,
            "-v",
            "error",
            "-show_entries",
            # One query, one process: an extra field costs nothing here, and
            # codec_tag_string is the only thing that distinguishes two data
            # tracks ffprobe reports no codec name for. pix_fmt rides the same
            # free query (docs/specs/archive/spec-within-stream-loss-notes.md) -- it
            # costs nothing extra either, unlike -count_packets, which the
            # spec's own measurements ruled out. stream_disposition= is a
            # separate entry clause because disposition flags arrive nested
            # under their own JSON object rather than alongside the plain
            # stream fields.
            "stream=index,codec_type,codec_name,codec_tag_string,pix_fmt:"
            "stream_disposition=attached_pic",
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

    parsed = (_parse_stream(raw) for raw in payload.get("streams", []))
    return [stream for stream in parsed if stream is not None]


# --- Windows Job Object: kill ffmpeg when the converter itself is killed ---
#
# A caller that can only reach for TerminateProcess -- Node's child.kill() on
# Windows maps every signal name to exactly that -- gives the converter no
# chance to run its SIGTERM handler, so ffmpeg would be orphaned and keep
# running. Binding *this* process to a Job Object with
# JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE closes that gap without it: when Windows
# tears the converter down it also closes the job handle, and that alone
# kills every process still in the job, including any ffmpeg/ffprobe child
# (docs/specs/archive/spec-abort-safe-writes.md).

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


class _IoCounters(ctypes.Structure):
    """Win32 ``IO_COUNTERS`` -- unused fields the extended limit struct needs
    for its layout to match the real one; only their sizes/order matter."""

    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "read_ops",
            "write_ops",
            "other_ops",
            "read_bytes",
            "write_bytes",
            "other_bytes",
        )
    ]


class _BasicLimitInformation(ctypes.Structure):
    """Win32 ``JOBOBJECT_BASIC_LIMIT_INFORMATION``."""

    _fields_ = [
        ("per_process_user_time_limit", ctypes.c_int64),
        ("per_job_user_time_limit", ctypes.c_int64),
        ("limit_flags", ctypes.c_ulong),
        ("minimum_working_set_size", ctypes.c_size_t),
        ("maximum_working_set_size", ctypes.c_size_t),
        ("active_process_limit", ctypes.c_ulong),
        ("affinity", ctypes.c_size_t),
        ("priority_class", ctypes.c_ulong),
        ("scheduling_class", ctypes.c_ulong),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    """Win32 ``JOBOBJECT_EXTENDED_LIMIT_INFORMATION``. Only
    ``basic_limit_information.limit_flags`` is ever set; the rest is zeroed
    by ctypes and ignored by Windows because that flag is the only one on."""

    _fields_ = [
        ("basic_limit_information", _BasicLimitInformation),
        ("io_info", _IoCounters),
        ("process_memory_limit", ctypes.c_size_t),
        ("job_memory_limit", ctypes.c_size_t),
        ("peak_process_memory_used", ctypes.c_size_t),
        ("peak_job_memory_used", ctypes.c_size_t),
    ]


def _kernel32() -> Any:
    """The ctypes handle to ``kernel32.dll``. A seam tests replace with a stub
    so the real Win32 API is never touched by the test suite.

    A private ``WinDLL`` instance, not the shared ``ctypes.windll.kernel32``
    singleton: the ``restype``/``argtypes`` this module sets on individual
    function pointers below would otherwise mutate state visible to every
    other user of that singleton in the process. ``use_last_error=True``
    lets a failure below report Windows' own error code.
    """
    return ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]


def _is_windows() -> bool:
    """Whether this process runs on Windows. A seam tests can flip without
    touching the real ``sys.platform``."""
    return sys.platform == "win32"


def _win_error_suffix() -> str:
    """Windows' own last-error code, if reachable, else an empty string.

    ``ctypes.get_last_error`` is meaningful only on Windows; guarding it
    keeps this callable from a stubbed failure test on Linux CI, where the
    attribute may not exist at all, without changing what it reports on the
    real target platform.
    """
    getter = getattr(ctypes, "get_last_error", None)
    return f" (error {getter()})" if getter is not None else ""


def _create_job_object(kernel32: Any) -> int:
    """Create an unnamed Job Object and return its handle, or raise OSError."""
    kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise OSError(f"CreateJobObjectW failed{_win_error_suffix()}")
    return job


def _set_kill_on_close(kernel32: Any, job: int) -> None:
    """Flag *job* so every member process dies when its handle is closed."""
    info = _ExtendedLimitInformation()
    info.basic_limit_information.limit_flags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    kernel32.SetInformationJobObject.restype = ctypes.c_int
    kernel32.SetInformationJobObject.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_ulong,
    ]
    ok = kernel32.SetInformationJobObject(
        job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)
    )
    if not ok:
        raise OSError(f"SetInformationJobObject failed{_win_error_suffix()}")


def _assign_current_process(kernel32: Any, job: int) -> None:
    """Put the current process into *job*."""
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.AssignProcessToJobObject.restype = ctypes.c_int
    kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    process = kernel32.GetCurrentProcess()
    if not kernel32.AssignProcessToJobObject(job, process):
        raise OSError(f"AssignProcessToJobObject failed{_win_error_suffix()}")


def _create_kill_on_close_job() -> int:
    """Create a job, flag it ``KILL_ON_JOB_CLOSE``, and join it -- return its
    handle. Split from :func:`bind_to_kill_on_close_job` so that function's
    only job is deciding whether to try and what to do if this raises."""
    kernel32 = _kernel32()
    job = _create_job_object(kernel32)
    _set_kill_on_close(kernel32, job)
    _assign_current_process(kernel32, job)
    return job


#: Kept for the rest of the process's life and never closed: closing this
#: handle is exactly what would trigger KILL_ON_JOB_CLOSE against ourselves,
#: since the converter is itself a member of the job. A module-level global
#: is the simplest thing that cannot be garbage-collected or accidentally
#: dropped by a caller holding no reference to it.
_job_handle: int | None = None


def bind_to_kill_on_close_job() -> None:
    """Assign this process to a Job Object that terminates it with ffmpeg.

    Windows-only; a no-op everywhere else. Meant to be called once, at the
    start of the convert command, before anything is spawned -- every
    ffmpeg/ffprobe child then inherits job membership automatically;
    ``cli.convert_command`` does exactly that. A failure to create or assign
    the job removes only the
    orphan protection, never a conversion, so it is reported once on stderr
    and swallowed rather than raised: the broad ``except Exception`` is
    deliberate here, this is a best-effort safety net whose precise failure
    mode (a missing DLL entry point, a permission error, a stubbed test
    double) does not matter to the caller.
    """
    global _job_handle
    if not _is_windows():
        return
    try:
        _job_handle = _create_kill_on_close_job()
    except Exception as exc:
        print(f"warning: could not bind to a Windows Job Object: {exc}", file=sys.stderr)

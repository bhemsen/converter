"""Bounded parallel execution of a job over many files, with honest reporting.

Two deliberate departures from the code this replaces:

* A bounded pool instead of one process per input file.  Spawning N processes
  for N files oversubscribes the machine badly, since each one starts an ffmpeg
  that is itself multi-threaded.
* Threads, not processes.  A worker here does nothing but wait on an ffmpeg
  child, so the GIL is irrelevant, and threads avoid Windows spawn/pickling
  pitfalls while leaving the progress bar as the single writer to the terminal.
"""

import enum
import os
import sys
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from tqdm import tqdm

from converter import ffmpegtool
from converter.ffmpegtool import ProbeError, Tools
from converter.jobs import Job
from converter.paths import ensure_directory


def default_jobs() -> int:
    """A conservative parallelism default: ffmpeg already threads internally."""
    return min(4, os.cpu_count() or 4)


class Outcome(enum.StrEnum):
    CONVERTED = "converted"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class Task:
    """One input file and the output file it should become."""

    src: Path
    dst: Path


@dataclass(frozen=True)
class Result:
    """What actually happened to a task."""

    task: Task
    outcome: Outcome
    attempt: str = ""
    notes: tuple[str, ...] = ()
    error: str = ""


def _discard_partial_output(dst: Path, *, existed: bool) -> None:
    """Delete a truncated output so the next run does not mistake it for done."""
    if existed:
        return
    with suppress(OSError):  # best effort: a locked file is not worth failing over
        dst.unlink(missing_ok=True)


def _attempt_conversion(job: Job, task: Task, tools: Tools, *, overwrite: bool) -> Result:
    existed = task.dst.exists()
    if existed and not overwrite:
        return Result(
            task,
            Outcome.SKIPPED,
            notes=("output already exists; pass --overwrite to replace it",),
        )

    pending = [job.first_attempt()]
    errors: list[str] = []
    probed = False

    while pending:
        attempt = pending.pop(0)
        argv = ffmpegtool.build_argv(tools.ffmpeg, task.src, attempt.options, task.dst)
        result = ffmpegtool.run(argv)
        if result.ok:
            return Result(task, Outcome.CONVERTED, attempt.label, attempt.notes)

        errors.append(f"[{attempt.label}] {result.stderr or f'exit code {result.returncode}'}")
        if not probed:
            # Only now is an ffprobe round-trip worth paying for: the cheap
            # stream-copy failed, so we need to know which streams are to blame.
            probed = True
            try:
                streams = ffmpegtool.probe_streams(tools, task.src)
            except ProbeError as exc:
                errors.append(f"[probe] {exc}")
            else:
                pending.extend(job.retries(streams))

    _discard_partial_output(task.dst, existed=existed)
    return Result(task, Outcome.FAILED, error=" | ".join(errors))


def convert_one(job: Job, task: Task, tools: Tools, *, overwrite: bool) -> Result:
    """Convert a single file, never raising: a bad file must not kill the batch."""
    try:
        return _attempt_conversion(job, task, tools, overwrite=overwrite)
    except Exception as exc:  # one broken file must not abort the whole run
        return Result(task, Outcome.FAILED, error=f"{type(exc).__name__}: {exc}")


def run_batch(
    job: Job,
    tasks: Sequence[Task],
    tools: Tools,
    *,
    jobs: int | None = None,
    overwrite: bool = False,
    progress: bool = True,
) -> list[Result]:
    """Run *job* over *tasks* with at most *jobs* conversions in flight."""
    tasks = list(tasks)
    workers = max(1, jobs or default_jobs())

    # Created up front, single-threaded, in the parent.  The old code ran
    # "if not exists: makedirs()" inside every worker, which races: the losers
    # died with FileExistsError and their files were never converted.
    for task in tasks:
        ensure_directory(task.dst.parent)

    results: list[Result] = []
    # Not ThreadPoolExecutor's own context manager: its __exit__ shuts down with
    # wait=True and no cancellation, so after Ctrl+C every queued file would
    # still be converted before the interrupt was ever noticed.
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        with tqdm(total=len(tasks), desc=job.name, unit="file", disable=not progress) as bar:
            futures = [
                pool.submit(convert_one, job, task, tools, overwrite=overwrite) for task in tasks
            ]
            try:
                # as_completed, so the bar advances when a file is actually done
                # rather than in submission order.
                for future in as_completed(futures):
                    result = future.result()
                    results.append(result)
                    _report(result, bar)
                    bar.update(1)
            except KeyboardInterrupt:
                # Drop everything that has not started. Conversions already in
                # flight still finish the file they are on, because they are
                # blocked in an ffmpeg subprocess we cannot interrupt from here.
                pool.shutdown(wait=False, cancel_futures=True)
                raise
    finally:
        pool.shutdown(wait=False)
    return results


def _report(result: Result, bar: tqdm) -> None:
    """Emit per-file detail without fighting the progress bar for the cursor."""
    name = result.task.src.name
    if result.outcome is Outcome.FAILED:
        bar.write(f"FAILED  {name}: {result.error}", file=sys.stderr)
        return
    for note in result.notes:
        bar.write(f"note    {name}: {note}")


@dataclass(frozen=True)
class Summary:
    """Aggregate outcome of a batch."""

    converted: int = 0
    skipped: int = 0
    failed: int = 0
    failures: tuple[Result, ...] = field(default_factory=tuple)

    @property
    def total(self) -> int:
        return self.converted + self.skipped + self.failed

    @property
    def exit_code(self) -> int:
        return 1 if self.failed else 0

    def describe(self) -> str:
        return (
            f"{self.converted} converted, {self.skipped} skipped, "
            f"{self.failed} failed (of {self.total})"
        )


def summarise(results: Iterable[Result]) -> Summary:
    """Fold results into a Summary; the exit code is derived, never assumed."""
    counts = {Outcome.CONVERTED: 0, Outcome.SKIPPED: 0, Outcome.FAILED: 0}
    failures: list[Result] = []
    for result in results:
        counts[result.outcome] += 1
        if result.outcome is Outcome.FAILED:
            failures.append(result)
    return Summary(
        converted=counts[Outcome.CONVERTED],
        skipped=counts[Outcome.SKIPPED],
        failed=counts[Outcome.FAILED],
        failures=tuple(failures),
    )

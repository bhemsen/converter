"""Bounded parallel execution of a target profile over many files, with honest
reporting.

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
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from tqdm import tqdm

from converter import ffmpegtool

# Aliased: run_batch's own `jobs` keyword (parallelism count) would otherwise
# shadow the module name inside this file.
from converter import jobs as engine
from converter.ffmpegtool import ProbeError, Stream, Tools
from converter.paths import ensure_directory, partial_for
from converter.profiles import Attempt, Profile


def default_jobs() -> int:
    """A conservative parallelism default: ffmpeg already threads internally."""
    return min(4, os.cpu_count() or 4)


class Outcome(enum.StrEnum):
    CONVERTED = "converted"
    SKIPPED = "skipped"
    FAILED = "failed"
    #: The source carries no stream of any type the target profile has a rule
    #: for at all -- distinct from FAILED, which still sets the exit code
    #: (docs/specs/archive/spec-target-driven-cli.md). Its discriminator is decided by
    #: the engine (converter.jobs.describe_unsupported), never here.
    UNSUPPORTED = "unsupported"


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


def _delete_partial(partial: Path) -> None:
    """Best-effort delete: a locked file on Windows is not worth failing over."""
    with suppress(OSError):
        partial.unlink(missing_ok=True)


def _raise_if_terminated(partial: Path) -> None:
    """Stop a killed attempt before it climbs, verifies or renames.

    Checked after every :func:`ffmpegtool.run` call and again right before the
    rename: a process killed mid-attempt still returns a (failing)
    ``CommandResult`` rather than raising, so a worker's own ffmpeg exiting is
    not itself proof the run should continue once :func:`ffmpegtool.terminate_all`
    has closed the registry. Each partial has exactly one owner at any moment,
    so deleting it here cannot race the main thread's own clean-up after the
    bounded wait (``docs/specs/archive/spec-abort-safe-writes.md``).
    """
    if not ffmpegtool.terminated():
        return
    _delete_partial(partial)
    raise ffmpegtool.Terminated


def _confirm_against_output(
    profile: Profile,
    tools: Tools,
    streams: Sequence[Stream],
    predicted: tuple[str, ...],
    output_path: Path,
) -> tuple[str, ...]:
    """Weigh a predicted loss against the file that was actually written.

    The second probe of ``docs/design/degradation-ladder.md``, and the only one
    ever aimed at an output. It is spent solely on a run that is *about to claim
    a loss*, so a conversion whose mapping gives nothing up still costs a single
    probe. *output_path* is the partial: the rename into place only happens
    after this probe, so the file at the final path has not been written yet
    (``docs/specs/archive/spec-abort-safe-writes.md``).
    """
    try:
        produced = ffmpegtool.probe_streams(tools, output_path)
    except (ProbeError, OSError) as exc:
        # Over-reporting is the safe side of "never report success for a
        # conversion that silently dropped something" (``docs/constitution.md``):
        # keep the prediction and say it could not be checked, rather than
        # discarding notes on the strength of a probe that never answered.
        return (*predicted, f"could not confirm this against the output: {exc}")
    return engine.confirm_drops(profile, streams, produced)


def _verify_cheap_attempt(
    profile: Profile, task: Task, tools: Tools, output_path: Path
) -> tuple[str, ...]:
    """Name whatever a structurally partial cheap attempt left behind.

    The one place ffprobe runs after an attempt has *succeeded*. A profile
    whose cheap attempt maps the source exhaustively needs no verification and
    never gets here, so the common case keeps its probe-free happy path
    (``docs/design/degradation-ladder.md``). *output_path* is the partial file,
    not ``task.dst``: the rename has not happened yet at this point.

    The within-stream transparency verdict (``engine.transparency_notes``,
    issue #105) is computed separately from ``predicted`` and returned on
    *both* paths below, early return included -- it must never become part of
    ``predicted``, or an alpha source with nothing structurally dropped would
    be sent into :func:`_confirm_against_output` for a second probe it does
    not need (spec-within-stream-loss-notes.md's Trap 1).
    """
    if not engine.needs_verification(profile):
        return ()
    try:
        streams = ffmpegtool.probe_streams(tools, task.src)
    # Both probes on this side run *after* ffmpeg already produced a good file,
    # so a spawn failure must degrade the bookkeeping, never the conversion:
    # letting an OSError escape would report FAILED for a file that converted
    # fine and leave the output behind for the next run to skip.
    except (ProbeError, OSError) as exc:
        # A run whose completeness could not be established must not read as a
        # plain success either (``docs/constitution.md``).
        return (f"could not verify which source streams were kept: {exc}",)
    within = engine.transparency_notes(profile, streams)
    predicted = engine.verify_success(profile, streams)
    if not predicted:
        return within
    # Confirmed structural drops lead, the within-stream note follows -- the
    # same order `jobs.retries` already uses for its own selective rung.
    return (*_confirm_against_output(profile, tools, streams, predicted, output_path), *within)


#: Windows-only backoff for a rename that lost a race with a reader (a scanner
#: or an indexer briefly holding the target open) -- about 3 s in all
#: (``docs/specs/archive/spec-abort-safe-writes.md``'s Prior decisions).
_RENAME_BACKOFFS: tuple[float, ...] = (0.1, 0.2, 0.4, 0.8, 1.6)


def _is_windows() -> bool:
    """Whether this process runs on Windows -- a seam tests can flip without
    touching the real ``sys.platform``."""
    return sys.platform == "win32"


def _rename_with_retry(partial: Path, dst: Path) -> str | None:
    """Move *partial* into *dst*, retrying a Windows lock with backoff.

    Only Windows retries: a scanner or indexer briefly holding the target is
    routine there, and failing a finished conversion over it would be the
    worse outcome. POSIX's rename is atomic and gets exactly one attempt.
    Returns ``None`` on success, or an explanatory string once every attempt
    is exhausted -- the caller reports that as a failure and deletes the
    partial, leaving whatever was at *dst* before untouched.
    """
    delays = _RENAME_BACKOFFS if _is_windows() else ()
    last_exc: PermissionError | None = None
    for delay in (0.0, *delays):
        if delay:
            time.sleep(delay)
        try:
            partial.replace(dst)
            return None
        except PermissionError as exc:
            last_exc = exc
    return f"could not replace the existing output; it appears locked: {last_exc}"


def _finish_conversion(
    profile: Profile,
    task: Task,
    tools: Tools,
    partial: Path,
    attempt: Attempt,
    *,
    probed: bool,
) -> Result:
    """Verify a successful rung (if it needs it), then rename it into place."""
    # `probed` still being false means this was the cheap attempt: every later
    # rung was built from the stream list itself and already carries accurate
    # notes, so only this one needs verifying.
    extra = () if probed else _verify_cheap_attempt(profile, task, tools, partial)
    _raise_if_terminated(partial)
    error = _rename_with_retry(partial, task.dst)
    if error is not None:
        _delete_partial(partial)
        return Result(task, Outcome.FAILED, error=error)
    return Result(task, Outcome.CONVERTED, attempt.label, (*attempt.notes, *extra))


def _climb_ladder(
    profile: Profile, task: Task, tools: Tools, errors: list[str], pending: list[Attempt]
) -> Result | None:
    """After a rung fails, probe once to find the next rung.

    Only now is an ffprobe round-trip worth paying for: the cheap stream-copy
    failed, so we need to know which streams are to blame. Returns a
    ready-made ``Result`` when the source turns out to hold nothing this
    profile could ever have produced, mutates *pending* with the next rung(s)
    otherwise, and returns ``None`` in both continuing cases.
    """
    try:
        streams = ffmpegtool.probe_streams(tools, task.src)
    except ProbeError as exc:
        errors.append(f"[probe] {exc}")
        return None
    # The engine's own signal, read once: a source with no stream of any type
    # the profile has a rule for can never climb the rest of the ladder, so
    # spending further ffmpeg attempts on it would only reconfirm a foregone
    # conclusion.
    unsupported = engine.describe_unsupported(profile, streams)
    if unsupported is not None:
        return Result(task, Outcome.UNSUPPORTED, notes=unsupported)
    pending.extend(engine.retries(profile, streams))
    return None


def _climb_the_ladder(profile: Profile, task: Task, tools: Tools, partial: Path) -> Result:
    """Run every rung until one succeeds or the ladder is exhausted.

    Split out of :func:`_attempt_conversion` so that function can wrap this
    one in a single ``try``/``except`` and guarantee the partial is gone on
    *any* exit that is not one of the explicit ``Result``-returning paths
    below -- a termination raised mid-probe included.
    """
    pending: list[Attempt] = [engine.first_attempt(profile)]
    errors: list[str] = []
    probed = False

    while pending:
        attempt = pending.pop(0)
        argv = ffmpegtool.build_argv(
            tools.ffmpeg, task.src, attempt.options, partial, output_format=profile.muxer
        )
        result = ffmpegtool.run(argv)
        _raise_if_terminated(partial)
        if result.ok:
            return _finish_conversion(profile, task, tools, partial, attempt, probed=probed)

        errors.append(f"[{attempt.label}] {result.stderr or f'exit code {result.returncode}'}")
        if not probed:
            probed = True
            outcome = _climb_ladder(profile, task, tools, errors, pending)
            # `_climb_ladder`'s own probe can be the thing that gets killed --
            # it surfaces as an ordinary `ProbeError`, appended to `errors`,
            # not as `Terminated`, so nothing short of checking here would
            # ever notice and this attempt would silently become FAILED.
            _raise_if_terminated(partial)
            if outcome is not None:
                _delete_partial(partial)
                return outcome

    _delete_partial(partial)
    return Result(task, Outcome.FAILED, error=" | ".join(errors))


def _attempt_conversion(profile: Profile, task: Task, tools: Tools, *, overwrite: bool) -> Result:
    partial = partial_for(task.dst)
    # A stale partial from an earlier, killed run -- swept whether this task
    # ends up converting or being skipped (``docs/specs/archive/spec-abort-safe-writes.md``).
    _delete_partial(partial)

    if task.dst.exists() and not overwrite:
        return Result(
            task,
            Outcome.SKIPPED,
            notes=("output already exists; pass --overwrite to replace it",),
        )

    try:
        return _climb_the_ladder(profile, task, tools, partial)
    except BaseException:
        # A belt-and-braces net around the explicit clean-up calls above and
        # inside `_finish_conversion`/`_raise_if_terminated`: `Terminated` can
        # also be raised directly by `ffmpegtool.run` itself (a *new* spawn
        # attempted after the shutdown flag is already set), which unwinds
        # straight out of this call stack without passing through any of
        # them. Whatever the cause, `docs/constitution.md` is unconditional --
        # "a partially written output file is removed when its conversion
        # fails" -- so this is not narrowed to `Terminated`/`KeyboardInterrupt`.
        _delete_partial(partial)
        raise


def convert_one(profile: Profile, task: Task, tools: Tools, *, overwrite: bool) -> Result:
    """Convert a single file, never raising: a bad file must not kill the batch."""
    try:
        return _attempt_conversion(profile, task, tools, overwrite=overwrite)
    except Exception as exc:  # one broken file must not abort the whole run
        return Result(task, Outcome.FAILED, error=f"{type(exc).__name__}: {exc}")


def _interruptible(
    profile: Profile,
    tools: Tools,
    *,
    overwrite: bool,
    interrupted: threading.Event,
) -> Callable[[Task], Result]:
    """Wrap :func:`convert_one` so a worker stops itself after any Ctrl+C.

    ``cancel_futures`` on the pool is not enough on its own: every file is
    submitted up front, and the interrupt only reaches the main thread when it
    consumes the future carrying it -- by which time a fast worker has already
    pulled the rest of the queue and converted it.  A worker that checks a shared
    flag before starting does not depend on that timing, which is why the same
    batch used to abort on one platform and drain to the end on another.
    """

    def work(task: Task) -> Result:
        if ffmpegtool.terminated():
            # A shutdown is already in progress -- SIGTERM, or Ctrl+C noticed
            # by another worker first. Raise the real reason rather than
            # relabelling it KeyboardInterrupt, so cli.py still maps a SIGTERM
            # run to 143 even when it is this check, not the one inside
            # `_attempt_conversion`, that catches it.
            raise ffmpegtool.Terminated
        if interrupted.is_set():
            # Raise rather than fabricate a Result: this file was never touched,
            # and SKIPPED already means "the output was already there", which is
            # a different statement.  KeyboardInterrupt specifically, so that
            # whichever future the main thread happens to consume first still
            # aborts the batch for the right reason.
            raise KeyboardInterrupt
        try:
            return convert_one(profile, task, tools, overwrite=overwrite)
        except KeyboardInterrupt:
            interrupted.set()
            raise

    return work


def _stage_output_directories(tasks: Sequence[Task]) -> tuple[list[Task], list[Result]]:
    """Create each task's output directory, containing a path-length failure to its file.

    Run single-threaded in the parent before the pool starts (see run_batch's
    docstring note on why directory creation happens up front at all). The old
    code let ``ensure_directory`` raise straight out of this loop: an OSError
    from one source -- typically a derived output path over Windows' MAX_PATH --
    propagated out of ``run_batch`` and aborted every remaining file in the
    tree, which is exactly what ``docs/constitution.md`` rules out ("one broken
    input file must not abort the batch"). Only ``OSError`` is caught here, not
    a bare ``Exception``: a genuine programming error in this loop must still
    surface as a crash rather than be filed away as a failed conversion.
    """
    runnable: list[Task] = []
    failures: list[Result] = []
    for task in tasks:
        try:
            ensure_directory(task.dst.parent)
        except OSError as exc:
            failures.append(Result(task, Outcome.FAILED, error=str(exc)))
        else:
            runnable.append(task)
    return runnable, failures


def _record(
    result: Result,
    results: list[Result],
    bar: tqdm,
    on_result: Callable[[Result], None] | None,
) -> None:
    """Append *result*, hand it to *on_result*, then advance the bar.

    The single choke point every result passes through -- the normal
    ``as_completed``-style loop, a staging failure reported before the pool
    even starts, and one drained during the bounded interrupt wait -- so
    *on_result* is called exactly once per result, from the main thread
    (``docs/specs/archive/spec-json-output.md``). ``None`` means no per-file output,
    matching the progress bar's own ``disable`` flag.
    """
    results.append(result)
    if on_result is not None:
        on_result(result)
    bar.update(1)


def _drain(
    future_tasks: dict[Future[Result], Task],
    results: list[Result],
    bar: tqdm,
    on_result: Callable[[Result], None] | None,
) -> None:
    """Report each future's Result as it lands, polling rather than blocking.

    ``concurrent.futures.wait`` in a loop instead of ``as_completed``: whether a
    blocking wait in the main thread is interruptible by Ctrl+C on Windows is
    unverified, so returning every half second makes signal delivery
    independent of that (``docs/specs/archive/spec-abort-safe-writes.md``). A
    ``KeyboardInterrupt`` or :class:`ffmpegtool.Terminated` out of
    ``future.result()`` propagates to the caller, which owns the clean-up.
    """
    pending = set(future_tasks)
    while pending:
        done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
        for future in done:
            result = future.result()
            # Removed before reporting: an interrupt landing between the two
            # would otherwise leave the future both reported here and still
            # present for `_handle_interrupt` to report a second time.
            del future_tasks[future]
            _record(result, results, bar, on_result)


#: How long the main thread waits for an in-flight conversion to notice a
#: termination before giving up on it as stuck (``docs/specs/archive/spec-abort-safe-writes.md``
#: says "bounded ~10 s"). A module-level seam so a test can shrink it rather
#: than genuinely block for ten seconds to reach the stuck-future branch.
_SHUTDOWN_WAIT_TIMEOUT = 10.0


def _handle_interrupt(
    future_tasks: dict[Future[Result], Task],
    results: list[Result],
    bar: tqdm,
    on_result: Callable[[Result], None] | None,
) -> None:
    """Stop every ffmpeg, drop what never started, and account for the rest.

    Cancelling an already-running future does nothing -- a thread pool cannot
    pull a thread out of a blocking call -- so ``terminate_all`` is what
    actually stops those; their own ``run()`` then returns promptly and the
    worker's post-run check (``_raise_if_terminated``) raises before it can
    verify or rename anything. Only a future still not done after the bounded
    wait is treated as stuck: its partial is removed directly, since its
    worker may never reach its own clean-up. A future that had *already*
    completed -- successfully or not -- before this function was even called
    (the main thread's own poll can be the thing that raised, not a future)
    is reported exactly like one that completes during the bounded wait: its
    result is not conditional on when it finished, only on whether it has one.
    """
    ffmpegtool.terminate_all()
    for future in future_tasks:
        future.cancel()
    pending = {future for future in future_tasks if not future.done()}
    done, timed_out = wait(pending, timeout=_SHUTDOWN_WAIT_TIMEOUT)
    for future in (*(set(future_tasks) - pending), *done):
        result = _safe_result(future)
        if result is not None:
            _record(result, results, bar, on_result)
    for future in timed_out:
        _delete_partial(partial_for(future_tasks[future].dst))


def _safe_result(future: Future[Result]) -> Result | None:
    """``future.result()``, or ``None`` for a cancelled/killed/terminated worker.

    Narrowed to this one call so a genuine bug in the reporting that follows
    -- appending to *results*, writing to the progress bar -- is never
    silently eaten alongside it.
    """
    with suppress(BaseException):
        return future.result()
    return None


def run_batch(
    profile: Profile,
    tasks: Sequence[Task],
    tools: Tools,
    *,
    jobs: int | None = None,
    overwrite: bool = False,
    progress: bool = True,
    on_result: Callable[[Result], None] | None = None,
) -> list[Result]:
    """Run *tasks* through *profile* with at most *jobs* conversions in flight.

    *on_result* is called exactly once per result, from the main thread,
    including staging failures reported before the pool starts and results
    drained during a bounded interrupt wait; ``None`` prints nothing per file.
    This is the only seam into per-file output -- ``batch`` never imports
    ``converter.report``, so ``cli`` is the one that decides which renderer,
    if any, sees each result (``docs/specs/archive/spec-json-output.md``).
    """
    tasks = list(tasks)
    workers = max(1, jobs or default_jobs())

    # Created up front, single-threaded, in the parent.  The old code ran
    # "if not exists: makedirs()" inside every worker, which races: the losers
    # died with FileExistsError and their files were never converted.
    runnable_tasks, early_failures = _stage_output_directories(tasks)

    results: list[Result] = []
    work = _interruptible(profile, tools, overwrite=overwrite, interrupted=threading.Event())

    # Not ThreadPoolExecutor's own context manager: its __exit__ shuts down with
    # wait=True and no cancellation, so after Ctrl+C every queued file would
    # still be converted before the interrupt was ever noticed.
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        with tqdm(total=len(tasks), desc=profile.label, unit="file", disable=not progress) as bar:
            for result in early_failures:
                _record(result, results, bar, on_result)
            _submit_and_drain(pool, work, runnable_tasks, results, bar, on_result)
    finally:
        pool.shutdown(wait=False)
    return results


def _submit_and_drain(
    pool: ThreadPoolExecutor,
    work: Callable[[Task], Result],
    tasks: Sequence[Task],
    results: list[Result],
    bar: tqdm,
    on_result: Callable[[Result], None] | None,
) -> None:
    """Submit *tasks* and drain them, with submission inside the interrupt's reach.

    A signal can land while tasks are still being submitted, not only while the
    main thread waits on them (issue #159). Submitting one at a time into the
    same dict ``_handle_interrupt`` receives means such an interrupt still
    reaches ``terminate_all`` and sees every future started so far. One raised
    between ``submit()`` returning and the assignment leaves that single future
    out of the dict; its worker is still covered by its own post-run check.
    """
    future_tasks: dict[Future[Result], Task] = {}
    try:
        for task in tasks:
            future_tasks[pool.submit(work, task)] = task
        _drain(future_tasks, results, bar, on_result)
    except (KeyboardInterrupt, ffmpegtool.Terminated):
        # Conversions already in flight are stopped by terminate_all
        # rather than left to finish the file they are on.
        _handle_interrupt(future_tasks, results, bar, on_result)
        raise


@dataclass(frozen=True)
class Summary:
    """Aggregate outcome of a batch."""

    converted: int = 0
    skipped: int = 0
    failed: int = 0
    unsupported: int = 0
    failures: tuple[Result, ...] = field(default_factory=tuple)

    @property
    def total(self) -> int:
        return self.converted + self.skipped + self.failed + self.unsupported

    @property
    def exit_code(self) -> int:
        # `unsupported` never sets the exit code (docs/specs/archive/spec-target-driven-cli.md):
        # a source the target cannot produce at all is reported honestly, not
        # treated as a run failure -- that is the whole point of the outcome.
        return 1 if self.failed else 0

    def describe(self) -> str:
        return (
            f"{self.converted} converted, {self.skipped} skipped, "
            f"{self.failed} failed, {self.unsupported} unsupported (of {self.total})"
        )


def summarise(results: Iterable[Result]) -> Summary:
    """Fold results into a Summary; the exit code is derived, never assumed."""
    counts = {
        Outcome.CONVERTED: 0,
        Outcome.SKIPPED: 0,
        Outcome.FAILED: 0,
        Outcome.UNSUPPORTED: 0,
    }
    failures: list[Result] = []
    for result in results:
        counts[result.outcome] += 1
        if result.outcome is Outcome.FAILED:
            failures.append(result)
    return Summary(
        converted=counts[Outcome.CONVERTED],
        skipped=counts[Outcome.SKIPPED],
        failed=counts[Outcome.FAILED],
        unsupported=counts[Outcome.UNSUPPORTED],
        failures=tuple(failures),
    )

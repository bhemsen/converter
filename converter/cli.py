"""Command-line interface.

The tool is driven by a *target format* rather than by a sub-command per format
pair: ``converter --to <format> INPUT [OUTPUT]``.  There are two parsers -- the
convert parser and the mirror parser -- because the two shapes genuinely cannot
coexist in one: argparse's sub-parser action is itself a positional, so a
top-level positional ``INPUT`` swallows the command name.  :func:`dispatch`
therefore routes the raw argument list *before* anything is parsed, which is
also what makes ``--list-formats`` reachable next to a required ``--to``
(``docs/specs/archive/spec-target-driven-cli.md``).

The interactive prompt of the old ``prepare*`` scripts is kept, but it only
assembles an argument list and hands it to :func:`dispatch` -- so the
interactive path and the scripted path are literally the same code.

This module deliberately names no target format anywhere: every one of them
comes out of ``converter.profiles``, which is what lets a new format be data
rather than a diff here (``docs/constitution.md``).  A test walks this file with
``ast`` and fails if a string literal ever says otherwise.
"""

import argparse
import signal
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from types import FrameType

from converter import __version__, ffmpegtool, paths, report
from converter.batch import Outcome, Result, Task, default_jobs, run_batch, summarise
from converter.profiles import PROFILES, SOURCE_SUFFIXES, Profile, resolve_target


class UsageError(Exception):
    """Bad combination of otherwise valid arguments."""


#: The one sub-command that survives the move to ``--to``: it converts nothing,
#: so it has no target format and cannot be expressed as one.
MIRROR_COMMAND = "mirror"

#: Recognised only to produce a useful error -- these no longer run anything.
LEGACY_COMMANDS: tuple[str, ...] = ("video", "audio")

#: Routed before parsing, so it works without INPUT or --to (see :func:`dispatch`).
LIST_FORMATS_FLAG = "--list-formats"


def _add_convert_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the conversion arguments.

    Unchanged in name and meaning from the sub-commands they replace, so an
    existing invocation only loses its verb.
    """
    parser.add_argument(
        "input_dir",
        metavar="INPUT",
        type=Path,
        help="a file to convert, or a directory containing the input files",
    )
    parser.add_argument(
        "output_dir",
        metavar="OUTPUT",
        nargs="?",
        type=Path,
        default=None,
        help=(
            "directory to write the results to; optional when INPUT is a file "
            "(defaults to its own directory), or omit either way when using --mirror-to"
        ),
    )
    parser.add_argument(
        "--mirror-to",
        metavar="ROOT",
        default=None,
        help=(
            "derive the output directory by re-rooting INPUT onto ROOT, "
            r"e.g. 'E:' or 'E:\Backup'"
        ),
    )
    parser.add_argument(
        "-r", "--recursive", action="store_true", help="also convert files in sub-directories"
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=None,
        metavar="N",
        help=f"conversions to run in parallel, not capped (default: {default_jobs()})",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace existing output files instead of skipping them",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="list what would be converted and stop"
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="hide the progress bar")
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit JSON Lines on stdout instead of prose (implies no progress bar)",
    )
    parser.add_argument("--ffmpeg", default=None, help="path to the ffmpeg executable")
    parser.add_argument("--ffprobe", default=None, help="path to the ffprobe executable")


def build_parser() -> argparse.ArgumentParser:
    """Build the convert parser -- the one that runs a conversion.

    It carries ``--version`` and an epilog naming the mirror sub-command and the
    list flag, because with ``mirror`` off a sub-parser list neither would
    otherwise be discoverable from ``converter --help``.
    """
    parser = argparse.ArgumentParser(
        prog="converter",
        description="Batch media conversion driven by the ffmpeg command-line program.",
        epilog=(
            f"Run 'converter {LIST_FORMATS_FLAG}' for the target formats available, "
            f"and 'converter {MIRROR_COMMAND} --help' for the directory-mirroring "
            "sub-command."
        ),
    )
    parser.add_argument("--version", action="version", version=f"converter {__version__}")
    parser.add_argument(
        "--to",
        required=True,
        metavar="FORMAT",
        help=f"target format to convert everything to; see {LIST_FORMATS_FLAG}",
    )
    # Declared so 'converter --help' lists it, but dispatch() intercepts it
    # first: a required --to and a required INPUT would otherwise reject it.
    parser.add_argument(
        LIST_FORMATS_FLAG, action="store_true", help="list the target formats and exit"
    )
    _add_convert_arguments(parser)
    return parser


def build_mirror_parser() -> argparse.ArgumentParser:
    """Build the mirror parser: re-create a directory tree on another drive."""
    parser = argparse.ArgumentParser(
        prog=f"converter {MIRROR_COMMAND}",
        description=(
            "Print (and optionally create) the directory tree that INPUT_ROOT would "
            "map to underneath OUTPUT_ROOT."
        ),
    )
    parser.add_argument("input_root", type=Path)
    parser.add_argument("output_root", help=r"target drive or directory, e.g. 'E:' or 'E:\Backup'")
    parser.add_argument(
        "--create", action="store_true", help="actually create the directories, not just list them"
    )
    parser.add_argument(
        "--no-recursive", dest="recursive", action="store_false", help="only the top level"
    )
    return parser


def _legacy_message(command: str) -> str:
    """Explain the removal generically.

    Which target replaces which sub-command is documented in the README and in
    the breaking release's migration note -- naming one here would be the single
    string that defeats this module's own format-name check, and every phase
    that adds a format depends on that check.
    """
    return (
        f"the {command!r} sub-command is gone; converter is driven by a target format now:\n"
        "  converter --to <format> IN OUT\n"
        f"Run 'converter {LIST_FORMATS_FLAG}' for the formats available."
    )


def list_formats_command() -> int:
    """Print one line per registry target, sorted by name.

    Resolves no tools and touches no filesystem: someone who guessed a format
    name wrong needs the list without owning a valid input directory, and
    without ffmpeg being installed yet.
    """
    names = sorted(PROFILES)
    width = max(len(name) for name in names)
    print("Target formats:")
    for name in names:
        profile = PROFILES[name]
        print(f"  {name:<{width}}  {profile.target_suffix}  {profile.description}")
    return 0


def _resolve_output_root(args: argparse.Namespace) -> Path:
    """Derive OUTPUT from ``--mirror-to``, or return the OUTPUT the user gave.

    ``--mirror-to`` re-roots ``paths.input_root(args.input_dir)`` -- INPUT's
    parent *as typed* for a file, INPUT itself for a directory -- never
    ``.resolve()``: a `subst`/junction/symlinked INPUT would otherwise mirror
    onto the physical path it resolves to, nesting the whole physical prefix
    into the output tree instead of the shallow tree the user asked for (issue
    #72). This is safe: the self-write and overwrite-hazard guards
    (``paths.is_self_write``, ``paths.find_overwrite_hazards``) resolve both
    the source and the derived output path themselves, independently, at
    comparison time -- so a mirrored output that physically lands back on an
    input is still caught no matter how the output root was built. Only
    ``README.md``'s documented shape of the mirrored tree depends on this
    choice, not the safety of the guards.

    A file INPUT may omit OUTPUT altogether: the result then lands beside the
    source, its own directory (``docs/specs/archive/spec-single-file-input.md``). A
    directory INPUT keeps the existing requirement.
    """
    if args.output_dir is not None and args.mirror_to is not None:
        raise UsageError("give either OUTPUT or --mirror-to, not both")
    if args.mirror_to is not None:
        try:
            return paths.mirror_to_drive(paths.input_root(args.input_dir), args.mirror_to)
        except ValueError as exc:
            raise UsageError(str(exc)) from exc
    if args.output_dir is not None:
        return args.output_dir
    if args.input_dir.is_file():
        return paths.input_root(args.input_dir)
    raise UsageError("OUTPUT is required unless --mirror-to is given")


def _check_output_shape(output: Path | None, target_suffix: str) -> None:
    """Refuse an OUTPUT that looks like a file name, for a file INPUT.

    OUTPUT stays a directory; the output file name comes from INPUT and
    ``--to``, never from OUTPUT itself. An existing non-directory OUTPUT, or a
    missing one whose suffix already matches the target's (case-insensitive,
    the ImageMagick reflex recorded as an AVOID in ``docs/prior-art.md``),
    would otherwise create a directory of that name and write into it --
    surprising rather than destructive, but worth refusing up front. A missing
    OUTPUT with no such suffix, or an existing directory whatever its name, is
    accepted unchanged (``docs/specs/archive/spec-single-file-input.md``).
    """
    if output is None:
        return
    exists = output.exists()
    existing_non_directory = exists and not output.is_dir()
    missing_but_target_shaped = not exists and output.suffix.lower() == target_suffix.lower()
    if existing_non_directory or missing_but_target_shaped:
        raise UsageError(
            "OUTPUT must be a directory; the output file name comes from INPUT and --to"
        )


def _resolve_profile(target: str) -> Profile:
    """Turn ``--to``'s value into a profile, or a usage error naming the alternatives."""
    try:
        return resolve_target(target)
    except ValueError as exc:
        # A wrong format name is a typo, not a conversion failure.
        raise UsageError(str(exc)) from exc


def _selected_pairs(
    args: argparse.Namespace, profile: Profile, input_root: Path, output_root: Path
) -> list[tuple[Path, Path]]:
    """Pair every candidate under INPUT with the output path it would produce.

    ``paths.select_input`` covers a file INPUT (the file itself, the suffix set
    bypassed) and a directory INPUT (``find_sources``, unchanged) with one call
    (``docs/specs/archive/spec-single-file-input.md``). The output root is handed to
    it unconditionally: it is skipped only when it really is a strict
    descendant of the input root, which is the one shape where a directory
    walk could otherwise rediscover its own output
    (``docs/design/source-selection.md``).
    """
    try:
        sources = paths.select_input(
            args.input_dir, SOURCE_SUFFIXES, recursive=args.recursive, exclude=output_root
        )
    except NotADirectoryError as exc:
        # A bad path is a usage error, not a conversion failure.
        raise UsageError(str(exc)) from exc
    return [
        (src, paths.output_for(src, input_root, output_root, profile.target_suffix))
        for src in sources
    ]


def _partition_self_writes(
    pairs: Sequence[tuple[Path, Path]],
) -> tuple[list[Result], list[Task]]:
    """Split candidates into self-writing sources and real tasks.

    A source whose output path resolves to its own input path leaves the run as
    a counted skip rather than a silent drop, so converting a tree in place
    stays idempotent and still reports what it did not do.
    """
    skipped: list[Result] = []
    tasks: list[Task] = []
    for src, dst in pairs:
        if paths.is_self_write(src, dst):
            skipped.append(
                Result(
                    Task(src, dst),
                    Outcome.SKIPPED,
                    notes=("the output path is this file itself; nothing to convert",),
                )
            )
        else:
            tasks.append(Task(src, dst))
    return skipped, tasks


def _refuse_destructive(
    pairs: Sequence[tuple[Path, Path]], tasks: Sequence[Task], *, overwrite: bool
) -> int | None:
    """Refuse the whole run up front, or return ``None`` to let it proceed.

    The two passes deliberately look at different sets: collisions at what will
    actually be written, hazards at every selected source including the
    self-writers -- the motivating hazard *is* a self-writer being overwritten
    by a sibling (``docs/design/source-selection.md``).
    """
    collisions = paths.find_collisions((task.src, task.dst) for task in tasks)
    if collisions:
        print("error: several inputs would be written to the same output:", file=sys.stderr)
        for dst, srcs in collisions.items():
            print(f"  {dst}", file=sys.stderr)
            for src in srcs:
                print(f"    <- {src}", file=sys.stderr)
        return 2

    hazards = paths.find_overwrite_hazards(pairs) if overwrite else []
    if hazards:
        print("error: --overwrite would destroy inputs this run also reads:", file=sys.stderr)
        for victim, writer in hazards:
            print(f"  {victim}", file=sys.stderr)
            print(f"    <- would be overwritten by {writer}", file=sys.stderr)
        return 2
    return None


def _nothing_found_hint(args: argparse.Namespace) -> str:
    """The stderr note for a run with no candidates.

    It names no suffix: the curated set is dozens of entries, so interpolating
    it would be unreadable -- and the summary on stdout is what carries the
    result, which is why this is a hint rather than an error.
    """
    hint = "" if args.recursive else " (pass --recursive to include sub-directories)"
    return f"note: no convertible files found in {args.input_dir}{hint}."


def _announce_skips(skipped: Sequence[Result]) -> None:
    """Name every skip decided before the batch started.

    The batch reports its own skips through the progress bar; these never reach
    it, and a file the user pointed at and did not get must not be passed over
    in silence (``docs/constitution.md``).  Not gated on ``--quiet``, which
    hides the progress bar rather than the reasons -- the batch's own notes are
    not gated either, and a file reported by one path and not the other would
    read as an inconsistency in the tool.
    """
    for result in skipped:
        for note in result.notes:
            print(f"note    {result.task.src.name}: {note}")


def _emit_json(record: dict[str, object]) -> None:
    """Write one JSON Lines record to stdout, bypassing the text layer.

    The single choke point every JSON record passes through, so stdout under
    ``--json`` carries records only -- never prose
    (``docs/specs/spec-json-output.md``).
    """
    report.write_json(record, sys.stdout.buffer, text_stream=sys.stdout)


def _report_using_ffmpeg(tools: ffmpegtool.Tools, args: argparse.Namespace) -> None:
    """Print the ffmpeg banner unless quiet -- stdout normally, stderr under ``--json``.

    Moved off stdout under ``--json`` so that stream stays pure JSON Lines;
    still suppressed by ``-q`` either way (``docs/specs/spec-json-output.md``).
    """
    if args.quiet:
        return
    print(f"Using {ffmpegtool.version(tools)}", file=sys.stderr if args.json else sys.stdout)


def _flush_skips_json(skipped: Sequence[Result]) -> Callable[[], None]:
    """Bind *skipped* into a zero-argument callback that emits it as ``file`` records.

    Passed to :func:`_run_tasks` as ``before_start``, so the records wait
    until tools have resolved -- an exit-2 tool failure must still leave
    stdout empty (``docs/specs/spec-json-output.md``).
    """

    def flush() -> None:
        for result in skipped:
            _emit_json(report.file_record(result))

    return flush


def _run_tasks(
    profile: Profile,
    tasks: Sequence[Task],
    args: argparse.Namespace,
    *,
    on_result: Callable[[Result], None] | None,
    before_start: Callable[[], None] | None = None,
) -> list[Result]:
    """Locate the tools and convert.

    Short-circuited when there is nothing to convert, so a run that consists
    only of skips still works on a machine with no ffmpeg installed.
    *before_start* runs once tools have resolved, or immediately when there
    are no tasks -- the one path that never resolves them at all -- which is
    the seam ``--json`` uses to hold its pre-batch skip records back until
    stdout is safe to write to (``docs/specs/spec-json-output.md``).
    """
    if not tasks:
        if before_start is not None:
            before_start()
        return []
    tools = ffmpegtool.resolve_tools(args.ffmpeg, args.ffprobe)
    if before_start is not None:
        before_start()
    _report_using_ffmpeg(tools, args)
    return run_batch(
        profile,
        tasks,
        tools,
        jobs=args.jobs,
        overwrite=args.overwrite,
        progress=not args.quiet and not args.json,
        on_result=on_result,
    )


def _raise_terminated(_signum: int, _frame: FrameType | None) -> None:
    """SIGTERM handler for the convert command: raise, and do nothing else.

    ``signal.signal`` requires this exact two-argument shape; both are unused
    -- the whole point is to do nothing with the signal number or the
    interrupted frame. A handler installed this way runs in the main thread
    only, between bytecode instructions, and must not take a lock or shut
    anything down itself -- doing real work here is exactly what
    cpython#121649 warns against. Raising is what breaks a blocked syscall
    out of PEP 475's automatic retry-on-EINTR, so this is the whole handler:
    ``ffmpegtool.terminate_all`` and the batch's own clean-up run from the
    exception's unwind, never from here (``docs/specs/spec-abort-safe-writes.md``).
    """
    raise ffmpegtool.Terminated


def convert_command(args: argparse.Namespace) -> int:
    """Bind the Windows Job Object and the SIGTERM handler, then convert.

    Both happen before anything can be spawned: the Job Object only protects
    processes started after the current one joins it, and a SIGTERM landing
    before the handler is installed would fall back to Python's default
    handling -- silent process death -- instead of today's exit-143 contract.
    SIGINT is left untouched, so Ctrl+C keeps Python's default
    ``KeyboardInterrupt``. The previous SIGTERM handler is restored on every
    way out, including when ``_convert`` raises, so the repeated in-process
    ``main()`` calls the test suite makes never stack a second handler on top
    of this one (``docs/specs/spec-abort-safe-writes.md``).
    """
    ffmpegtool.bind_to_kill_on_close_job()
    previous_handler = signal.signal(signal.SIGTERM, _raise_terminated)
    try:
        return _convert(args)
    finally:
        signal.signal(signal.SIGTERM, previous_handler)


def _report_no_candidates(args: argparse.Namespace) -> int:
    """Handle a run with no candidates: a zero summary, the hint stays on stderr."""
    summary = summarise(())
    if args.json:
        record = report.summary_record(summary, planned=0, exit_code=0, dry_run=args.dry_run)
        _emit_json(record)
    else:
        print(summary.describe())
    print(_nothing_found_hint(args), file=sys.stderr)
    return 0


def _dry_run_text(skipped: Sequence[Result], tasks: Sequence[Task]) -> int:
    """List what would be converted, exactly as today."""
    _announce_skips(skipped)
    for task in tasks:
        print(f"{task.src} -> {task.dst}")
    print(f"{len(tasks)} file(s) would be converted.")
    return 0


def _dry_run_json(skipped: Sequence[Result], tasks: Sequence[Task]) -> int:
    """List what would be converted as ``planned`` records, plus a summary.

    Tools are never resolved for a dry run, so the pre-batch skip records need
    no deferral here -- they are written straight away, as ``file`` records
    (``docs/specs/spec-json-output.md``).
    """
    for result in skipped:
        _emit_json(report.file_record(result))
    for task in tasks:
        _emit_json(report.planned_record(task))
    summary = summarise(skipped)
    _emit_json(report.summary_record(summary, planned=len(tasks), exit_code=0, dry_run=True))
    return 0


def _run_and_report_text(
    profile: Profile, skipped: Sequence[Result], tasks: Sequence[Task], args: argparse.Namespace
) -> int:
    """Convert, printing every note/failure and a closing summary sentence."""
    _announce_skips(skipped)
    converted = _run_tasks(profile, tasks, args, on_result=report.render_text)
    summary = summarise([*skipped, *converted])
    print(summary.describe())
    return summary.exit_code


def _run_and_report_json(
    profile: Profile, skipped: Sequence[Result], tasks: Sequence[Task], args: argparse.Namespace
) -> int:
    """Convert, emitting one ``file`` record per file and a closing ``summary``.

    No summary is emitted on an interrupt or an aborting error: those unwind
    out of ``_run_tasks`` as an exception, so the lines below never run
    (``docs/specs/spec-json-output.md``).
    """
    converted = _run_tasks(
        profile,
        tasks,
        args,
        on_result=lambda result: _emit_json(report.file_record(result)),
        before_start=_flush_skips_json(skipped),
    )
    summary = summarise([*skipped, *converted])
    record = report.summary_record(summary, planned=0, exit_code=summary.exit_code, dry_run=False)
    _emit_json(record)
    return summary.exit_code


def _convert(args: argparse.Namespace) -> int:
    """Select, refuse or convert -- the whole of ``docs/design/source-selection.md``.

    Selection finishes before ffmpeg is ever located, which is what lets
    ``--dry-run`` and a refusal work on a machine that has no ffmpeg. The
    existence check runs first among the path-handling steps, before
    ``_resolve_output_root``, so a missing file INPUT is never mistaken for a
    missing OUTPUT (``docs/specs/archive/spec-single-file-input.md``).
    """
    if args.jobs is not None and args.jobs < 1:
        raise UsageError(f"--jobs must be 1 or more, got {args.jobs}")
    if not args.input_dir.exists():
        raise UsageError(f"input does not exist: {args.input_dir}")
    profile = _resolve_profile(args.to)
    if args.input_dir.is_file() and args.mirror_to is None:
        _check_output_shape(args.output_dir, profile.target_suffix)
    input_root = paths.input_root(args.input_dir)
    output_root = _resolve_output_root(args)

    pairs = _selected_pairs(args, profile, input_root, output_root)
    if not pairs:
        return _report_no_candidates(args)

    skipped, tasks = _partition_self_writes(pairs)
    refusal = _refuse_destructive(pairs, tasks, overwrite=args.overwrite)
    if refusal is not None:
        return refusal

    if args.dry_run:
        return _dry_run_json(skipped, tasks) if args.json else _dry_run_text(skipped, tasks)
    if args.json:
        return _run_and_report_json(profile, skipped, tasks, args)
    return _run_and_report_text(profile, skipped, tasks, args)


def mirror_command(args: argparse.Namespace) -> int:
    """Print, and optionally create, the mirrored directory tree.

    Re-roots each directory *as typed*, matching ``_resolve_output_root``: this
    command exists to preview what ``--mirror-to`` will do, so resolving here
    and not there would make the preview lie about the tree that gets built.
    """
    try:
        directories = paths.list_directories(args.input_root, recursive=args.recursive)
    except NotADirectoryError as exc:
        raise UsageError(str(exc)) from exc
    for directory in directories:
        try:
            target = paths.mirror_to_drive(directory, args.output_root)
        except ValueError as exc:
            raise UsageError(str(exc)) from exc
        print(f"{directory} -> {target}")
        if args.create:
            paths.ensure_directory(target)
    verb = "created" if args.create else "would be created"
    print(f"{len(directories)} director{'y' if len(directories) == 1 else 'ies'} {verb}.")
    return 0


def dispatch(raw: Sequence[str]) -> int:
    """Route *raw* to the command that owns it, before any parsing happens.

    The order is the one ``docs/specs/archive/spec-target-driven-cli.md`` fixes: a
    leading mirror token, then a leading legacy token, then the list flag
    anywhere, then the convert parser.  Both the prompt's output and a typed
    argument list come through here, which is what keeps them one code path.
    """
    if raw and raw[0] == MIRROR_COMMAND:
        return mirror_command(build_mirror_parser().parse_args(raw[1:]))
    if raw and raw[0] in LEGACY_COMMANDS:
        raise UsageError(_legacy_message(raw[0]))
    if LIST_FORMATS_FLAG in raw:
        return list_formats_command()
    return convert_command(build_parser().parse_args(raw))


def _ask(question: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{question}{suffix}: ").strip().strip('"')
    return answer or default


def _ask_yes_no(question: str, *, default: bool = False) -> bool:
    answer = _ask(f"{question} [y/n]", "y" if default else "n").lower()
    return answer.startswith("y")


def _selection(choice: str, targets: Sequence[str]) -> str | None:
    """Map a menu answer onto a target name or the mirror token.

    A number indexes the menu; anything else is offered to the registry, so a
    format name typed straight out is the escape hatch once counting entries
    gets silly.  ``None`` means the answer matched nothing.
    """
    if choice == str(len(targets) + 1) or choice.strip().lower() == MIRROR_COMMAND:
        return MIRROR_COMMAND
    # isdecimal, not isdigit: the latter is true for characters int() rejects,
    # such as a superscript digit, and the prompt runs outside main()'s exception
    # handling -- such an answer would escape as a traceback rather than being
    # reported as an unknown selection.
    if choice.isdecimal():
        index = int(choice)
        return targets[index - 1] if 1 <= index <= len(targets) else None
    try:
        return resolve_target(choice).name
    except ValueError:
        return None


def _prompt_menu() -> list[str]:
    """Print the numbered menu and return the target names it offered, in order."""
    targets = sorted(PROFILES)
    for number, name in enumerate(targets, start=1):
        print(f"  {number}) {name} - {PROFILES[name].description}")
    print(f"  {len(targets) + 1}) {MIRROR_COMMAND} - re-create a directory tree on another drive")
    return targets


def _prompt_mirror_argv(input_root: str) -> list[str] | None:
    """Ask for the rest of a mirror invocation."""
    output_root = _ask("Output drive or directory")
    if not output_root:
        print("An output drive or directory is required.", file=sys.stderr)
        return None
    argv = [MIRROR_COMMAND, input_root, output_root]
    if _ask_yes_no("Create the directories now?"):
        argv.append("--create")
    return argv


def _prompt_convert_argv(target: str, input_root: str) -> list[str] | None:
    """Ask for the rest of a conversion invocation.

    A file `input_root` matches the CLI's own defaults: OUTPUT is optional (an
    empty answer lands beside the source), `--mirror-to` is not offered, and
    "Include sub-directories?" is not asked -- a file has none
    (``docs/specs/archive/spec-single-file-input.md``). A directory answer keeps every
    prompt and default exactly as before.
    """
    argv = ["--to", target, input_root]
    if Path(input_root).is_file():
        output_dir = _ask("Output directory (empty for the file's own directory)")
        if output_dir:
            argv.append(output_dir)
    else:
        output_dir = _ask("Output directory (empty to mirror onto another drive instead)")
        if output_dir:
            argv.append(output_dir)
        else:
            mirror_to = _ask("Output drive or directory")
            if not mirror_to:
                print("An output directory or drive is required.", file=sys.stderr)
                return None
            argv += ["--mirror-to", mirror_to]
        if _ask_yes_no("Include sub-directories?", default=True):
            argv.append("--recursive")

    if _ask_yes_no("Overwrite existing output files?"):
        argv.append("--overwrite")
    return argv


def prompt_for_argv() -> list[str] | None:
    """Ask for the options interactively and return them as an argument list.

    Returning an argv list rather than acting directly keeps the interactive
    path and the scripted path on exactly the same code -- and the menu is built
    from the registry, so it grows with it instead of being maintained here.
    """
    print(f"converter {__version__} - interactive mode")
    targets = _prompt_menu()
    choice = _ask("Select", "1")

    selection = _selection(choice, targets)
    if selection is None:
        print(f"Unknown selection: {choice!r}", file=sys.stderr)
        return None

    input_root = _ask("Input file or directory")
    if not input_root:
        print("An input file or directory is required.", file=sys.stderr)
        return None

    if selection == MIRROR_COMMAND:
        return _prompt_mirror_argv(input_root)
    return _prompt_convert_argv(selection, input_root)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one invocation and return its exit code.

    The prompt fills ``raw`` *before* routing, so a prompted mirror argument
    list reaches the mirror parser exactly like a typed one does.
    """
    raw = list(sys.argv[1:] if argv is None else argv)

    if not raw:
        try:
            prompted = prompt_for_argv()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            return 130
        if prompted is None:
            return 2
        raw = prompted

    try:
        return dispatch(raw)
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ffmpegtool.FfmpegMissingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except ffmpegtool.Terminated:
        print("\nTerminated.", file=sys.stderr)
        return 143


__all__ = ["build_mirror_parser", "build_parser", "dispatch", "main"]

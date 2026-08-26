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
import sys
from collections.abc import Sequence
from pathlib import Path

from converter import __version__, ffmpegtool, paths
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
        "input_dir", metavar="INPUT", type=Path, help="directory containing the input files"
    )
    parser.add_argument(
        "output_dir",
        metavar="OUTPUT",
        nargs="?",
        type=Path,
        default=None,
        help="directory to write the results to; omit when using --mirror-to",
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
        help=f"conversions to run in parallel (default: {default_jobs()})",
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
    if args.output_dir is not None and args.mirror_to is not None:
        raise UsageError("give either OUTPUT or --mirror-to, not both")
    if args.mirror_to is not None:
        try:
            return paths.mirror_to_drive(args.input_dir.resolve(), args.mirror_to)
        except ValueError as exc:
            raise UsageError(str(exc)) from exc
    if args.output_dir is not None:
        return args.output_dir
    raise UsageError("OUTPUT is required unless --mirror-to is given")


def _resolve_profile(target: str) -> Profile:
    """Turn ``--to``'s value into a profile, or a usage error naming the alternatives."""
    try:
        return resolve_target(target)
    except ValueError as exc:
        # A wrong format name is a typo, not a conversion failure.
        raise UsageError(str(exc)) from exc


def _selected_pairs(
    args: argparse.Namespace, profile: Profile, output_root: Path
) -> list[tuple[Path, Path]]:
    """Pair every candidate under INPUT with the output path it would produce.

    The output root is handed to discovery unconditionally: it is skipped only
    when it really is a strict descendant of the input root, which is the one
    shape where the walk could otherwise rediscover its own output
    (``docs/design/source-selection.md``).
    """
    try:
        sources = paths.find_sources(
            args.input_dir, SOURCE_SUFFIXES, recursive=args.recursive, exclude=output_root
        )
    except NotADirectoryError as exc:
        # A bad path is a usage error, not a conversion failure.
        raise UsageError(str(exc)) from exc
    return [
        (src, paths.output_for(src, args.input_dir, output_root, profile.target_suffix))
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


def _run_tasks(profile: Profile, tasks: Sequence[Task], args: argparse.Namespace) -> list[Result]:
    """Locate the tools and convert.

    Short-circuited when there is nothing to convert, so a run that consists
    only of skips still works on a machine with no ffmpeg installed.
    """
    if not tasks:
        return []
    tools = ffmpegtool.resolve_tools(args.ffmpeg, args.ffprobe)
    if not args.quiet:
        print(f"Using {ffmpegtool.version(tools)}")
    return run_batch(
        profile,
        tasks,
        tools,
        jobs=args.jobs,
        overwrite=args.overwrite,
        progress=not args.quiet,
    )


def convert_command(args: argparse.Namespace) -> int:
    """Select, refuse or convert -- the whole of ``docs/design/source-selection.md``.

    Selection finishes before ffmpeg is ever located, which is what lets
    ``--dry-run`` and a refusal work on a machine that has no ffmpeg.
    """
    if args.jobs is not None and args.jobs < 1:
        raise UsageError(f"--jobs must be 1 or more, got {args.jobs}")
    profile = _resolve_profile(args.to)
    output_root = _resolve_output_root(args)

    pairs = _selected_pairs(args, profile, output_root)
    if not pairs:
        print(summarise(()).describe())
        print(_nothing_found_hint(args), file=sys.stderr)
        return 0

    skipped, tasks = _partition_self_writes(pairs)
    refusal = _refuse_destructive(pairs, tasks, overwrite=args.overwrite)
    if refusal is not None:
        return refusal

    _announce_skips(skipped)
    if args.dry_run:
        for task in tasks:
            print(f"{task.src} -> {task.dst}")
        print(f"{len(tasks)} file(s) would be converted.")
        return 0

    summary = summarise([*skipped, *_run_tasks(profile, tasks, args)])
    print(summary.describe())
    return summary.exit_code


def mirror_command(args: argparse.Namespace) -> int:
    """Print, and optionally create, the mirrored directory tree."""
    try:
        directories = paths.list_directories(args.input_root, recursive=args.recursive)
    except NotADirectoryError as exc:
        raise UsageError(str(exc)) from exc
    for directory in directories:
        try:
            target = paths.mirror_to_drive(directory.resolve(), args.output_root)
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
    """Ask for the rest of a conversion invocation."""
    argv = ["--to", target, input_root]
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

    input_root = _ask("Input directory")
    if not input_root:
        print("An input directory is required.", file=sys.stderr)
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


__all__ = ["build_mirror_parser", "build_parser", "dispatch", "main"]

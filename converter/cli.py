"""Command-line interface.

One parser with sub-commands replaces the four stand-alone scripts.  The
interactive prompts of the old ``prepare*`` scripts are kept, but they now only
assemble an argument list and hand it to the very same parser -- so there is a
single code path to reason about and to test.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from converter import __version__, ffmpegtool, paths
from converter.batch import Task, default_jobs, run_batch, summarise
from converter.profiles import MP4, WAV, Profile


class UsageError(Exception):
    """Bad combination of otherwise valid arguments."""


@dataclass(frozen=True)
class _Binding:
    """A sub-command's CLI-visible name plus which source suffixes feed which
    target profile. Phase-2 scaffolding (``docs/specs/spec-target-driven-cli.md``):
    replaced once ``--to`` takes over from the ``video``/``audio`` sub-commands.
    """

    description: str
    suffixes: tuple[str, ...]
    profile: Profile


#: Sub-command name -> binding. See :class:`_Binding`.
_BINDINGS: dict[str, _Binding] = {
    "video": _Binding(
        description="Convert .mkv files to .mp4 (stream copy where possible)",
        suffixes=(".mkv",),
        profile=MP4,
    ),
    "audio": _Binding(
        description="Convert .opus files to uncompressed .wav",
        suffixes=(".opus",),
        profile=WAV,
    ),
}


def _add_convert_arguments(sub: argparse.ArgumentParser, binding: _Binding) -> None:
    sub.add_argument("input_dir", type=Path, help="directory containing the input files")
    sub.add_argument(
        "output_dir",
        nargs="?",
        type=Path,
        default=None,
        help="directory to write the results to; omit when using --mirror-to",
    )
    sub.add_argument(
        "--mirror-to",
        metavar="ROOT",
        default=None,
        help=(
            "derive the output directory by re-rooting INPUT_DIR onto ROOT, "
            r"e.g. 'E:' or 'E:\Backup'"
        ),
    )
    sub.add_argument(
        "-r", "--recursive", action="store_true", help="also convert files in sub-directories"
    )
    sub.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=None,
        metavar="N",
        help=f"conversions to run in parallel (default: {default_jobs()})",
    )
    sub.add_argument(
        "--overwrite",
        action="store_true",
        help="replace existing output files instead of skipping them",
    )
    sub.add_argument("--dry-run", action="store_true", help="list what would be converted and stop")
    sub.add_argument("-q", "--quiet", action="store_true", help="hide the progress bar")
    sub.add_argument("--ffmpeg", default=None, help="path to the ffmpeg executable")
    sub.add_argument("--ffprobe", default=None, help="path to the ffprobe executable")
    sub.set_defaults(binding=binding, handler=convert_command)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="converter",
        description="Batch media conversion driven by the ffmpeg command-line program.",
    )
    parser.add_argument("--version", action="version", version=f"converter {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    for name, binding in _BINDINGS.items():
        sub = subparsers.add_parser(name, help=binding.description, description=binding.description)
        _add_convert_arguments(sub, binding)

    mirror = subparsers.add_parser(
        "mirror",
        help="Re-create a directory tree on another drive",
        description=(
            "Print (and optionally create) the directory tree that INPUT_ROOT would "
            "map to underneath OUTPUT_ROOT."
        ),
    )
    mirror.add_argument("input_root", type=Path)
    mirror.add_argument("output_root", help=r"target drive or directory, e.g. 'E:' or 'E:\Backup'")
    mirror.add_argument(
        "--create", action="store_true", help="actually create the directories, not just list them"
    )
    mirror.add_argument(
        "--no-recursive", dest="recursive", action="store_false", help="only the top level"
    )
    mirror.set_defaults(handler=mirror_command)

    return parser


def _resolve_output_root(args: argparse.Namespace) -> Path:
    if args.output_dir is not None and args.mirror_to is not None:
        raise UsageError("give either OUTPUT_DIR or --mirror-to, not both")
    if args.mirror_to is not None:
        try:
            return paths.mirror_to_drive(args.input_dir.resolve(), args.mirror_to)
        except ValueError as exc:
            raise UsageError(str(exc)) from exc
    if args.output_dir is not None:
        return args.output_dir
    raise UsageError("OUTPUT_DIR is required unless --mirror-to is given")


def convert_command(args: argparse.Namespace) -> int:
    binding: _Binding = args.binding
    if args.jobs is not None and args.jobs < 1:
        raise UsageError(f"--jobs must be 1 or more, got {args.jobs}")
    output_root = _resolve_output_root(args)

    try:
        sources = paths.find_sources(args.input_dir, binding.suffixes, recursive=args.recursive)
    except NotADirectoryError as exc:
        # A bad path is a usage error, not a conversion failure.
        raise UsageError(str(exc)) from exc
    if not sources:
        hint = "" if args.recursive else " (pass --recursive to include sub-directories)"
        print(
            f"No {' / '.join(binding.suffixes)} files found in {args.input_dir}{hint}.",
            file=sys.stderr,
        )
        return 0

    tasks = [
        Task(src, paths.output_for(src, args.input_dir, output_root, binding.profile.target_suffix))
        for src in sources
    ]

    collisions = paths.find_collisions((task.src, task.dst) for task in tasks)
    if collisions:
        print("error: several inputs would be written to the same output:", file=sys.stderr)
        for dst, srcs in collisions.items():
            print(f"  {dst}", file=sys.stderr)
            for src in srcs:
                print(f"    <- {src}", file=sys.stderr)
        return 2

    if args.dry_run:
        for task in tasks:
            print(f"{task.src} -> {task.dst}")
        print(f"{len(tasks)} file(s) would be converted.")
        return 0

    tools = ffmpegtool.resolve_tools(args.ffmpeg, args.ffprobe)
    if not args.quiet:
        print(f"Using {ffmpegtool.version(tools)}")

    results = run_batch(
        binding.profile,
        tasks,
        tools,
        jobs=args.jobs,
        overwrite=args.overwrite,
        progress=not args.quiet,
    )
    summary = summarise(results)
    print(summary.describe())
    return summary.exit_code


def mirror_command(args: argparse.Namespace) -> int:
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


def _ask(question: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{question}{suffix}: ").strip().strip('"')
    return answer or default


def _ask_yes_no(question: str, *, default: bool = False) -> bool:
    answer = _ask(f"{question} [y/n]", "y" if default else "n").lower()
    return answer.startswith("y")


def prompt_for_argv() -> list[str] | None:
    """Ask for the options interactively and return them as an argument list.

    Returning an argv list rather than acting directly keeps the interactive
    path and the scripted path on exactly the same code.
    """
    print(f"converter {__version__} - interactive mode")
    print("  1) .mkv -> .mp4")
    print("  2) .opus -> .wav")
    print("  3) mirror a directory tree onto another drive")
    choice = _ask("Select", "1")

    commands = {"1": "video", "2": "audio", "3": "mirror"}
    command = commands.get(choice)
    if command is None:
        print(f"Unknown selection: {choice!r}", file=sys.stderr)
        return None

    input_root = _ask("Input directory")
    if not input_root:
        print("An input directory is required.", file=sys.stderr)
        return None

    if command == "mirror":
        output_root = _ask("Output drive or directory")
        if not output_root:
            print("An output drive or directory is required.", file=sys.stderr)
            return None
        argv = [command, input_root, output_root]
        if _ask_yes_no("Create the directories now?"):
            argv.append("--create")
        return argv

    argv = [command, input_root]
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    raw = list(sys.argv[1:] if argv is None else argv)

    if not raw:
        try:
            raw = prompt_for_argv()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            return 130
        if raw is None:
            return 2

    args = parser.parse_args(raw)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 2

    try:
        return args.handler(args)
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


__all__ = ["build_parser", "main"]

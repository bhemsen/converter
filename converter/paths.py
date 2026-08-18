"""Input discovery and output-path construction.

Every path bug the old scripts had lived in these few functions, so they are
kept pure and side-effect free -- which also makes them the part of the tool
that is worth unit-testing.
"""

import errno
import os
from collections.abc import Iterable
from pathlib import Path


def normalise_suffixes(suffixes: Iterable[str]) -> frozenset[str]:
    """Return *suffixes* lower-cased and dot-prefixed."""
    normalised = set()
    for suffix in suffixes:
        lowered = suffix.lower()
        normalised.add(lowered if lowered.startswith(".") else f".{lowered}")
    return frozenset(normalised)


def find_sources(
    root: str | os.PathLike[str],
    suffixes: Iterable[str],
    *,
    recursive: bool = False,
) -> list[Path]:
    """Collect the files under *root* whose suffix is in *suffixes*.

    Matching is case-insensitive -- ``str.endswith(".mkv")`` used to skip
    ``Movie.MKV`` without a word -- and directories are excluded, so a folder
    named ``season.mkv`` is no longer handed to ffmpeg as an input file.
    Results are sorted so runs are reproducible.
    """
    wanted = normalise_suffixes(suffixes)
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(f"input directory does not exist: {root}")
    candidates = root.rglob("*") if recursive else root.glob("*")
    return sorted(p for p in candidates if p.suffix.lower() in wanted and p.is_file())


def output_for(
    src: Path,
    input_root: str | os.PathLike[str],
    output_root: str | os.PathLike[str],
    target_suffix: str,
) -> Path:
    """Map *src* to its output path, preserving the tree below *input_root*.

    Keeping the relative directory is what stops ``a/ep1.mkv`` and ``b/ep1.mkv``
    from both wanting to become ``out/ep1.mp4``.
    """
    relative = Path(src).relative_to(input_root)
    return Path(output_root) / relative.with_suffix(target_suffix)


def mirror_to_drive(
    path: str | os.PathLike[str],
    output_root: str | os.PathLike[str],
) -> Path:
    r"""Re-root *path* onto *output_root*, keeping its directory structure.

    ``os.path.join("D:", "Users\me")`` yields the *drive-relative* string
    ``"D:Users\me"``, which Windows resolves against whatever the current
    directory on ``D:`` happens to be -- not ``D:\Users\me``.  That was the
    original bug, so the separator is inserted explicitly here.
    """
    text = os.fspath(path)
    rest = text[len(os.path.splitdrive(text)[0]) :].lstrip("\\/")

    raw_root = os.fspath(output_root)
    if not raw_root:
        raise ValueError("output root must not be empty")
    base = raw_root.rstrip("\\/")
    if not base:  # the output root is the filesystem root itself
        return Path(os.sep + rest)
    return Path(base + os.sep + rest)


def list_directories(
    root: str | os.PathLike[str],
    *,
    recursive: bool = True,
) -> list[Path]:
    """List the directories under *root*, **including root itself**.

    The old helper collected only sub-directories, so files sitting directly in
    the input root were silently never converted.
    """
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(f"directory does not exist: {root}")
    pattern = root.rglob("*") if recursive else root.glob("*")
    return [root, *sorted(p for p in pattern if p.is_dir())]


#: Length at which a failing Windows path is probably hitting the MAX_PATH limit.
LONG_PATH_THRESHOLD = 240


#: Windows error codes that a path-length problem actually surfaces as.
#: 3 = ERROR_PATH_NOT_FOUND, 206 = ERROR_FILENAME_EXCED_RANGE.
_LENGTH_WINERRORS = frozenset({3, 206})


def _may_be_a_length_problem(exc: OSError, text: str) -> bool:
    """Does *exc* plausibly come from the path being too long, rather than
    from a name collision, a permission problem or a full disk?"""
    if len(text) < LONG_PATH_THRESHOLD:
        return False
    if exc.errno == errno.ENAMETOOLONG:
        return True
    return os.name == "nt" and getattr(exc, "winerror", None) in _LENGTH_WINERRORS


def ensure_directory(path: Path) -> None:
    """Create *path* including parents, explaining the Windows path-length trap.

    Mirroring a deep source tree onto a sub-directory doubles its depth, which
    trips Windows' 260-character limit and surfaces as a bare "path not found".
    The original error is always kept: only a matching error code earns the extra
    explanation, so an unrelated failure on a long path is not misdiagnosed.
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        text = os.fspath(path)
        if _may_be_a_length_problem(exc, text):
            message = (
                f"{exc}\n"
                f"The path is {len(text)} characters long, and Windows rejects paths over 260 "
                "characters unless long-path support is enabled -- a common cause of this "
                "error. Choose a shorter output root, or see the README."
            )
            raise OSError(message) from exc
        raise


def find_collisions(pairs: Iterable[tuple[Path, Path]]) -> dict[Path, list[Path]]:
    """Return output paths that more than one input would write to.

    ``os.path.normcase`` is used for the comparison because Windows would let
    two differently-cased outputs silently overwrite each other.
    """
    seen: dict[str, tuple[Path, list[Path]]] = {}
    for src, dst in pairs:
        key = os.path.normcase(os.fspath(dst))
        if key in seen:
            seen[key][1].append(src)
        else:
            seen[key] = (dst, [src])
    return {dst: sources for dst, sources in seen.values() if len(sources) > 1}

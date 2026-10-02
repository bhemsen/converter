"""Input discovery and output-path construction.

Every path bug the old scripts had lived in these few functions, so they are
kept pure and side-effect free -- which also makes them the part of the tool
that is worth unit-testing.
"""

import errno
import os
import re
from collections.abc import Iterable, Sequence
from pathlib import Path


def normalise_suffixes(suffixes: Iterable[str]) -> frozenset[str]:
    """Return *suffixes* lower-cased and dot-prefixed."""
    normalised = set()
    for suffix in suffixes:
        lowered = suffix.lower()
        normalised.add(lowered if lowered.startswith(".") else f".{lowered}")
    return frozenset(normalised)


def _resolved_key(path: str | os.PathLike[str]) -> str:
    """Return a case-folded string of *path*, resolved, for identity comparisons.

    Resolving first -- rather than comparing the paths as given -- is what
    catches a ``--mirror-to`` self-write or hazard when a `subst`/junction/
    symlinked INPUT and the ``--mirror-to`` target can each be spelled through
    the alias or through the real path behind it: two paths that name the same
    file can look completely different strings until both sides are resolved.
    """
    return os.path.normcase(os.fspath(Path(path).resolve()))


def _is_within(path: Path, ancestor: Path) -> bool:
    """Return whether *path* lies strictly inside *ancestor* (both already resolved)."""
    ancestor_text = os.fspath(ancestor)
    prefix = ancestor_text if ancestor_text.endswith(os.sep) else ancestor_text + os.sep
    return os.path.normcase(os.fspath(path)).startswith(os.path.normcase(prefix))


def _excluded_subtree(root: Path, exclude: str | os.PathLike[str] | None) -> Path | None:
    """Resolve *exclude* against *root*, keeping it only if it is a strict descendant.

    An output root that is an ancestor or a sibling of *root* is already
    outside the walk, and one equal to *root* is the self-write guard's job --
    see ``docs/design/source-selection.md``'s OWN node for why only the
    strict-descendant shape is excluded here.
    """
    if exclude is None:
        return None
    resolved_root = root.resolve()
    resolved_exclude = Path(exclude).resolve()
    return resolved_exclude if _is_within(resolved_exclude, resolved_root) else None


def find_sources(
    root: str | os.PathLike[str],
    suffixes: Iterable[str],
    *,
    recursive: bool = False,
    exclude: str | os.PathLike[str] | None = None,
) -> list[Path]:
    """Collect the files under *root* whose suffix is in *suffixes*.

    Matching is case-insensitive -- ``str.endswith(".mkv")`` used to skip
    ``Movie.MKV`` without a word -- and directories are excluded, so a folder
    named ``season.mkv`` is no longer handed to ffmpeg as an input file.
    Results are sorted so runs are reproducible.

    *exclude*, when given, is a subtree to skip -- meant for an output root
    nested inside *root*, so a converted tree is never rediscovered as input on
    the next run. It only takes effect when it actually is a strict descendant
    of *root* once both are resolved; see ``_excluded_subtree``.
    """
    wanted = normalise_suffixes(suffixes)
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(f"input directory does not exist: {root}")
    excluded = _excluded_subtree(root, exclude)
    candidates = root.rglob("*") if recursive else root.glob("*")
    return sorted(
        p
        for p in candidates
        if p.suffix.lower() in wanted
        and p.is_file()
        and (excluded is None or not _is_within(p.resolve(), excluded))
    )


def input_root(path: str | os.PathLike[str]) -> Path:
    """Return the directory a file `INPUT` behaves as, per the spec's model.

    A file's parent -- ``.`` for a bare relative name -- as typed and never
    resolved (``docs/specs/archive/spec-single-file-input.md``, *Prior decisions*), so
    a `subst`/junction input still mirrors onto the shallow tree the user
    sees. A directory, or anything else including a missing path, is returned
    unchanged; ``select_input`` is what raises for those.
    """
    typed = Path(path)
    return typed.parent if typed.is_file() else typed


def select_input(
    path: str | os.PathLike[str],
    suffixes: Iterable[str],
    *,
    recursive: bool = False,
    exclude: str | os.PathLike[str] | None = None,
) -> list[Path]:
    """Return the candidate files for `INPUT`, file or directory alike.

    A file is its own one-file batch -- *suffixes* is not consulted, since the
    user named the file and ffprobe, not an extension list, decides whether it
    is readable. Anything else goes through ``find_sources`` unchanged,
    including its ``NotADirectoryError`` for a missing path.
    """
    typed = Path(path)
    if typed.is_file():
        return [typed]
    return find_sources(typed, suffixes, recursive=recursive, exclude=exclude)


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


def partial_for(dst: str | os.PathLike[str]) -> Path:
    """Return the temporary name a conversion writes to before it succeeds.

    ``clip.mp4`` becomes ``clip.mp4.partial`` -- appended, not substituted for
    the suffix, so the final rename is a plain truncation of the name rather
    than a second suffix computation, and so ``.partial`` collects in no
    source-suffix set a directory walk could ever match
    (``docs/specs/archive/spec-abort-safe-writes.md``'s *Prior decisions*). Pure: no
    filesystem access, so it is as cheap to call speculatively as it is to
    call once and hold onto the result.
    """
    return Path(os.fspath(dst) + ".partial")


#: A normalised sidecar language, also what ``sidecar_language`` accepts. Two
#: letters at least in the first component keep it from ever being purely
#: numeric, so it can never be mistaken for a duplicate counter.
_LANGUAGE_PATTERN = r"[a-z]{2,3}(?:-[a-z0-9]{1,8})*"
_LANGUAGE_RE = re.compile(_LANGUAGE_PATTERN)

#: The duplicate counter of a sidecar name: an integer of at least 2.
_DUPLICATE_PATTERN = r"(?:\.(?:[2-9]|[1-9][0-9]+))?"


def sidecar_language(tag: str) -> str:
    """Return the sidecar language for a raw stream language *tag*.

    The lower-cased tag when it matches ``[a-z]{2,3}(-[a-z0-9]{1,8})*``,
    otherwise ``und``. The pattern admits no ``.`` and nothing purely numeric,
    which is what keeps the dot-separated components of a sidecar name from
    lining up with another MP4's (``docs/specs/archive/spec-subtitle-sidecars.md``,
    *Guards by construction*; ``docs/design/source-selection.md``).
    """
    lowered = tag.lower()
    return lowered if _LANGUAGE_RE.fullmatch(lowered) else "und"


def sidecar_paths(dst: Path, languages: Sequence[str], suffix: str) -> list[Path]:
    """Return one sidecar path per entry of *languages*, beside *dst*.

    *languages* are raw tags and are normalised here. The first stream of a
    language gets ``<stem>.<lang><suffix>``, further ones ``.2``, ``.3``, ...
    per language in order, ``und`` included. The counter is always numeric and
    the language never is, so for two distinct MP4 names no component sequence
    coincides: a sidecar equals no other source's sidecar or MP4, and *suffix*
    (in no source-suffix set, no target suffix) keeps it from any walked input.
    See ``docs/specs/archive/spec-subtitle-sidecars.md`` (*Guards by construction*) and
    ``docs/design/source-selection.md``. Pure: no filesystem access.
    """
    seen: dict[str, int] = {}
    paths = []
    for tag in languages:
        language = sidecar_language(tag)
        count = seen.get(language, 0) + 1
        seen[language] = count
        dup = "" if count == 1 else f".{count}"
        paths.append(dst.with_name(f"{dst.stem}.{language}{dup}{suffix}"))
    return paths


def stale_sidecar_partials(dst: Path, suffix: str) -> list[Path]:
    """List the sidecar partials in ``dst.parent`` that only *dst*'s task can produce.

    A name matches ``<stem>.<lang>[.<k>]<suffix>.partial``: *stem* is *dst*'s
    name minus its suffix, run through ``re.escape``; *lang* the normalised
    language pattern; *k* an integer of at least 2. Both sides are compared
    through ``os.path.normcase`` -- the comparison ``find_collisions`` uses --
    and never ``str.casefold``, which folds ``ß`` to ``ss`` and would join names
    NTFS keeps apart. So exactly the names the collision check treats as one are
    one here, and two concurrent tasks never sweep each other's partials
    (``docs/specs/archive/spec-subtitle-sidecars.md``, *Prior decisions*;
    ``docs/design/source-selection.md``). The one filesystem read among the
    sidecar helpers; a missing directory yields ``[]``.
    """
    pattern = re.compile(
        re.escape(os.path.normcase(dst.stem))
        + r"\."
        + _LANGUAGE_PATTERN
        + _DUPLICATE_PATTERN
        + re.escape(os.path.normcase(suffix))
        + r"\.partial"
    )
    try:
        names = sorted(p.name for p in dst.parent.iterdir())
    except (FileNotFoundError, NotADirectoryError):
        return []
    return [dst.parent / name for name in names if pattern.fullmatch(os.path.normcase(name))]


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
    two differently-cased outputs silently overwrite each other. A
    self-writing source (see ``is_self_write``) should be filtered out of
    *pairs* by the caller first: it produces no conversion, so it cannot
    contend for its own path -- per ``docs/design/source-selection.md``'s COLL
    node.
    """
    seen: dict[str, tuple[Path, list[Path]]] = {}
    for src, dst in pairs:
        key = os.path.normcase(os.fspath(dst))
        if key in seen:
            seen[key][1].append(src)
        else:
            seen[key] = (dst, [src])
    return {dst: sources for dst, sources in seen.values() if len(sources) > 1}


def is_self_write(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> bool:
    """Return whether writing *dst* would overwrite *src* itself.

    Both paths are resolved before comparison, then compared case-folded --
    unlike ``find_collisions``, which case-folds the paths as given. The
    difference is load-bearing under ``--mirror-to``: a `subst`/junction/
    symlinked INPUT and the ``--mirror-to`` target can each be named through
    the alias or through the real path behind it, so comparing as given would
    miss a self-write where the two spellings resolve to the same file.
    Per ``docs/design/source-selection.md``'s SELF node, a true self-write is
    reported as a counted skip, never silently dropped, and never refuses the
    run by itself.
    """
    return _resolved_key(src) == _resolved_key(dst)


def find_overwrite_hazards(pairs: Iterable[tuple[Path, Path]]) -> list[tuple[Path, Path]]:
    """Return (victim, writer) pairs where *writer*'s output would destroy *victim*.

    *victim* is a different selected source whose own input path *writer*'s
    output resolves to. Every selected source is a potential victim,
    self-writers included -- the motivating case is exactly a self-writer
    (``a.mp4``) being overwritten by a sibling (``a.mkv``) -- which is why
    this is its own two-pass check over *pairs*, like ``find_collisions``,
    rather than a filter on top of it: the first pass indexes every source by
    its resolved, case-folded path, the second asks whether each output
    resolves to a *different* source's entry. Per
    ``docs/design/source-selection.md``'s HAZ node, both sides are resolved
    before comparison, and this check is meant to fire only under
    ``--overwrite``, which is the caller's decision, not this function's.
    """
    resolved = [(src, _resolved_key(src), dst, _resolved_key(dst)) for src, dst in pairs]
    victims_by_key: dict[str, Path] = {}
    for entry_src, entry_src_key, _entry_dst, _entry_dst_key in resolved:
        victims_by_key[entry_src_key] = entry_src

    hazards = []
    for src, src_key, _dst, dst_key in resolved:
        victim = victims_by_key.get(dst_key)
        if victim is not None and dst_key != src_key:
            hazards.append((victim, src))
    return hazards

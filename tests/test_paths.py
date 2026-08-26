"""Tests for path handling -- the code that carried the original bugs."""

import errno
import os
from pathlib import Path

import pytest

from converter.paths import (
    LONG_PATH_THRESHOLD,
    _may_be_a_length_problem,
    ensure_directory,
    find_collisions,
    find_overwrite_hazards,
    find_sources,
    is_self_write,
    list_directories,
    mirror_to_drive,
    normalise_suffixes,
    output_for,
)

on_windows = pytest.mark.skipif(os.name != "nt", reason="Windows drive-letter semantics")


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def select(
    input_root: Path,
    output_root: Path,
    suffixes: list[str],
    target_suffix: str,
    *,
    recursive: bool = True,
    overwrite: bool = False,
) -> tuple[list[Path], list[Path], list[tuple[Path, Path]]]:
    """Run the whole selection pipeline `docs/design/source-selection.md` draws.

    Composes the paths.py predicates the way a future caller (cli.py, #15)
    will, so this test file can exercise the design's per-file flow --
    candidate -> self-write / collision / hazard / exists -- without any
    ffmpeg or profile involved. Returns (converted, skipped, hazards): the
    hazards list is non-empty exactly when the whole run would be refused.
    """
    sources = find_sources(input_root, suffixes, recursive=recursive, exclude=output_root)
    pairs = [(src, output_for(src, input_root, output_root, target_suffix)) for src in sources]

    if overwrite:
        hazards = find_overwrite_hazards(pairs)
        if hazards:
            return [], [], hazards

    convertible = [(src, dst) for src, dst in pairs if not is_self_write(src, dst)]
    if find_collisions(convertible):
        raise AssertionError("selection produced a collision the test did not expect")

    converted, skipped = [], []
    for src, dst in pairs:
        if is_self_write(src, dst) or (dst.exists() and not overwrite):
            skipped.append(src)
        else:
            converted.append(src)
    return converted, skipped, []


class TestNormaliseSuffixes:
    def test_adds_dot_and_lowercases(self):
        assert normalise_suffixes(["MKV", ".Opus"]) == frozenset({".mkv", ".opus"})


class TestFindSources:
    def test_matches_case_insensitively(self, tmp_path):
        """str.endswith('.mkv') skipped 'Movie.MKV' without a word of warning."""
        touch(tmp_path / "lower.mkv")
        touch(tmp_path / "UPPER.MKV")
        touch(tmp_path / "Mixed.Mkv")

        found = find_sources(tmp_path, [".mkv"])

        assert {p.name for p in found} == {"lower.mkv", "UPPER.MKV", "Mixed.Mkv"}

    def test_results_are_sorted_for_reproducible_runs(self, tmp_path):
        for name in ("c.mkv", "a.mkv", "b.mkv"):
            touch(tmp_path / name)

        found = find_sources(tmp_path, [".mkv"])

        assert found == sorted(found)

    def test_ignores_other_suffixes(self, tmp_path):
        touch(tmp_path / "keep.mkv")
        touch(tmp_path / "skip.mp4")
        touch(tmp_path / "skip.txt")

        assert [p.name for p in find_sources(tmp_path, [".mkv"])] == ["keep.mkv"]

    def test_ignores_directories_that_look_like_files(self, tmp_path):
        """A folder called 'season.mkv' used to be handed to ffmpeg as an input."""
        (tmp_path / "season.mkv").mkdir()
        touch(tmp_path / "real.mkv")

        assert [p.name for p in find_sources(tmp_path, [".mkv"])] == ["real.mkv"]

    def test_non_recursive_by_default(self, tmp_path):
        touch(tmp_path / "top.mkv")
        touch(tmp_path / "nested" / "deep.mkv")

        assert [p.name for p in find_sources(tmp_path, [".mkv"])] == ["top.mkv"]

    def test_recursive_finds_nested_and_root_level_files(self, tmp_path):
        touch(tmp_path / "top.mkv")
        touch(tmp_path / "nested" / "deep.mkv")

        found = find_sources(tmp_path, [".mkv"], recursive=True)

        assert {p.name for p in found} == {"top.mkv", "deep.mkv"}

    def test_missing_directory_raises(self, tmp_path):
        with pytest.raises(NotADirectoryError):
            find_sources(tmp_path / "nope", [".mkv"])


class TestOutputFor:
    def test_replaces_suffix(self, tmp_path):
        result = output_for(tmp_path / "clip.mkv", tmp_path, Path("out"), ".mp4")

        assert result == Path("out") / "clip.mp4"

    def test_keeps_only_the_last_suffix(self, tmp_path):
        result = output_for(tmp_path / "Show.S01E02.1080p.mkv", tmp_path, Path("out"), ".mp4")

        assert result == Path("out") / "Show.S01E02.1080p.mp4"

    def test_preserves_the_directory_tree(self, tmp_path):
        """Flattening would make a/ep1.mkv and b/ep1.mkv collide on one output."""
        result = output_for(tmp_path / "a" / "ep1.mkv", tmp_path, Path("out"), ".mp4")

        assert result == Path("out") / "a" / "ep1.mp4"


class TestMirrorToDrive:
    @on_windows
    def test_result_is_absolute_not_drive_relative(self):
        r"""os.path.join('D:', r'Users\me') returns 'D:Users\me' -- the original bug.

        That is a *drive-relative* path, resolved against the current directory
        on D:, so output silently landed somewhere else entirely.
        """
        result = mirror_to_drive(r"C:\Users\me\Videos", "D:")

        assert result == Path(r"D:\Users\me\Videos")
        assert result.is_absolute()
        assert os.fspath(result) != os.path.join("D:", r"Users\me\Videos")

    @on_windows
    @pytest.mark.parametrize("output_root", ["D:", "D:\\", "D:/"])
    def test_trailing_separators_do_not_double_up(self, output_root):
        assert mirror_to_drive(r"C:\Videos", output_root) == Path(r"D:\Videos")

    @on_windows
    def test_mirrors_onto_a_subdirectory(self):
        result = mirror_to_drive(r"C:\Users\me\Videos", r"E:\Backup")

        assert result == Path(r"E:\Backup\Users\me\Videos")
        assert result.is_absolute()

    @on_windows
    def test_unc_source_keeps_the_share_relative_part(self):
        result = mirror_to_drive(r"\\server\share\media\clip", "D:")

        assert result == Path(r"D:\media\clip")

    def test_posix_style_roots(self):
        result = mirror_to_drive("/home/me/vid", "/mnt/backup")

        assert result == Path("/mnt/backup/home/me/vid")

    def test_empty_output_root_is_rejected(self):
        with pytest.raises(ValueError, match="must not be empty"):
            mirror_to_drive("/home/me", "")


class TestListDirectories:
    def test_includes_the_root_itself(self, tmp_path):
        """The old helper only collected sub-directories, so files sitting
        directly in the input root were never converted."""
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "b").mkdir()

        found = list_directories(tmp_path)

        assert found[0] == tmp_path
        assert set(found) == {tmp_path, tmp_path / "a", tmp_path / "a" / "b"}

    def test_non_recursive_stops_at_the_top_level(self, tmp_path):
        (tmp_path / "a" / "b").mkdir(parents=True)

        found = list_directories(tmp_path, recursive=False)

        assert set(found) == {tmp_path, tmp_path / "a"}

    def test_missing_directory_raises(self, tmp_path):
        with pytest.raises(NotADirectoryError):
            list_directories(tmp_path / "nope")


class TestEnsureDirectory:
    def test_creates_nested_directories(self, tmp_path):
        target = tmp_path / "a" / "b" / "c"

        ensure_directory(target)

        assert target.is_dir()

    def test_is_idempotent(self, tmp_path):
        """Workers used to race on 'if not exists: makedirs()' and lose."""
        target = tmp_path / "a"

        ensure_directory(target)
        ensure_directory(target)

        assert target.is_dir()

    @on_windows
    def test_long_path_failure_explains_itself(self, tmp_path):
        deep = tmp_path.joinpath(*[f"segment{i:03d}" for i in range(30)])
        assert len(os.fspath(deep)) >= LONG_PATH_THRESHOLD

        try:
            ensure_directory(deep)
        except OSError as exc:
            assert "characters long" in str(exc)
        else:
            pytest.skip("long-path support is enabled on this machine")


class TestLengthDiagnosis:
    """The path-length hint must not be pinned on unrelated failures."""

    LONG = "C:\\" + "x" * 300

    @on_windows
    def test_path_not_found_on_a_long_path_earns_the_hint(self):
        exc = OSError(2, "The system cannot find the path specified", self.LONG, 3)

        assert _may_be_a_length_problem(exc, self.LONG) is True

    @on_windows
    def test_existing_file_in_the_way_does_not_earn_the_hint(self):
        """mkdir can fail for many reasons; a long path must not hide the real one."""
        exc = OSError(17, "Cannot create a file when it already exists", self.LONG, 183)

        assert _may_be_a_length_problem(exc, self.LONG) is False

    @on_windows
    def test_permission_denied_does_not_earn_the_hint(self):
        exc = OSError(13, "Access is denied", self.LONG, 5)

        assert _may_be_a_length_problem(exc, self.LONG) is False

    def test_short_paths_never_earn_the_hint(self):
        assert _may_be_a_length_problem(OSError(2, "nope"), "C:\\short") is False

    def test_enametoolong_earns_the_hint_on_any_platform(self):
        long_posix = "/" + "y" * 300
        exc = OSError(errno.ENAMETOOLONG, "File name too long", long_posix)

        assert _may_be_a_length_problem(exc, long_posix) is True

    def test_the_original_error_text_is_preserved(self, tmp_path):
        blocker = tmp_path / "afile"
        blocker.write_bytes(b"")

        with pytest.raises(OSError) as exc_info:
            ensure_directory(blocker / "sub")

        assert "characters long" not in str(exc_info.value)

    @on_windows
    def test_a_long_path_failing_for_another_reason_keeps_its_own_message(self, tmp_path):
        """The guard has to be wired into ensure_directory, not just exist:
        a long path plus an unrelated cause must still report the real cause."""
        # Long enough to cross the threshold, short enough that Windows can still
        # create it, so the failure genuinely comes from the file in the way.
        padding = LONG_PATH_THRESHOLD - len(os.fspath(tmp_path)) - len("/sub")
        if padding < 1:
            pytest.skip("the temporary directory is already too long for this test")
        blocker = tmp_path / ("b" * padding)
        blocker.write_bytes(b"")
        target = blocker / "sub"
        assert len(os.fspath(target)) >= LONG_PATH_THRESHOLD

        with pytest.raises(OSError) as exc_info:
            ensure_directory(target)

        assert "characters long" not in str(exc_info.value)


class TestFindCollisions:
    def test_detects_two_inputs_writing_to_one_output(self):
        pairs = [
            (Path("a/ep1.mkv"), Path("out/ep1.mp4")),
            (Path("b/ep1.mkv"), Path("out/ep1.mp4")),
        ]

        collisions = find_collisions(pairs)

        assert list(collisions) == [Path("out/ep1.mp4")]
        assert len(next(iter(collisions.values()))) == 2

    def test_distinct_outputs_are_not_collisions(self):
        pairs = [
            (Path("a/ep1.mkv"), Path("out/a/ep1.mp4")),
            (Path("b/ep1.mkv"), Path("out/b/ep1.mp4")),
        ]

        assert find_collisions(pairs) == {}

    @on_windows
    def test_case_differences_collide_on_windows(self):
        pairs = [
            (Path("a/EP1.mkv"), Path("out/EP1.mp4")),
            (Path("b/ep1.mkv"), Path("out/ep1.mp4")),
        ]

        assert len(find_collisions(pairs)) == 1


class TestIsSelfWrite:
    def test_true_when_resolved_paths_match(self, tmp_path):
        touch(tmp_path / "a.mp4")

        assert is_self_write(tmp_path / "a.mp4", tmp_path / "a.mp4") is True

    def test_false_for_different_files(self, tmp_path):
        touch(tmp_path / "a.mp4")
        touch(tmp_path / "b.mp4")

        assert is_self_write(tmp_path / "a.mp4", tmp_path / "b.mp4") is False

    def test_resolves_before_comparing(self, tmp_path):
        """A ``..`` segment must not hide a self-write -- the --mirror-to case,
        where discovery returns the root as typed but the output root is
        derived from a resolved input path, so comparing as given would miss it."""
        touch(tmp_path / "a.mp4")
        typed_src = tmp_path / "sub" / ".." / "a.mp4"

        assert is_self_write(typed_src, tmp_path / "a.mp4") is True

    @on_windows
    def test_case_folded(self, tmp_path):
        touch(tmp_path / "a.mp4")

        upper = Path(str(tmp_path).upper()) / "A.MP4"
        assert is_self_write(tmp_path / "a.mp4", upper) is True


class TestFindSourcesExcludesSubtree:
    def test_excludes_a_nested_output_root(self, tmp_path):
        touch(tmp_path / "top.mkv")
        touch(tmp_path / "converted" / "done.mkv")

        found = find_sources(tmp_path, [".mkv"], recursive=True, exclude=tmp_path / "converted")

        assert [p.name for p in found] == ["top.mkv"]

    def test_ancestor_output_root_is_not_excluded(self, tmp_path):
        """An ancestor output root is already outside the walk: excluding
        "lies under it" without the strict-descendant clause would drop every
        candidate here and report a successful run that did nothing."""
        sub = tmp_path / "Sub"
        touch(sub / "a.mkv")

        found = find_sources(sub, [".mkv"], recursive=True, exclude=tmp_path)

        assert [p.name for p in found] == ["a.mkv"]

    def test_sibling_output_root_is_not_excluded(self, tmp_path):
        input_root = tmp_path / "in"
        sibling = tmp_path / "out"
        touch(input_root / "a.mkv")

        found = find_sources(input_root, [".mkv"], recursive=True, exclude=sibling)

        assert [p.name for p in found] == ["a.mkv"]

    def test_output_root_equal_to_input_root_is_not_excluded(self, tmp_path):
        """Equal roots are the self-write guard's job, not this exclusion."""
        touch(tmp_path / "a.mkv")

        found = find_sources(tmp_path, [".mkv"], recursive=True, exclude=tmp_path)

        assert [p.name for p in found] == ["a.mkv"]

    def test_no_exclude_means_no_filtering(self, tmp_path):
        touch(tmp_path / "a.mkv")

        assert find_sources(tmp_path, [".mkv"], recursive=True) == [tmp_path / "a.mkv"]


class TestFindOverwriteHazards:
    def test_detects_a_sibling_overwriting_a_self_writer(self):
        """The motivating case: a.mp4 self-writes and would be skipped, and
        a.mkv's output would then overwrite it under --overwrite."""
        pairs = [
            (Path("a.mp4"), Path("a.mp4")),
            (Path("a.mkv"), Path("a.mp4")),
        ]

        hazards = find_overwrite_hazards(pairs)

        assert hazards == [(Path("a.mp4"), Path("a.mkv"))]

    def test_a_files_own_self_write_is_not_its_own_hazard(self):
        pairs = [(Path("a.mp4"), Path("a.mp4"))]

        assert find_overwrite_hazards(pairs) == []

    def test_no_hazard_when_outputs_do_not_collide_with_a_source(self):
        pairs = [(Path("a.mkv"), Path("out/a.mp4")), (Path("b.mkv"), Path("out/b.mp4"))]

        assert find_overwrite_hazards(pairs) == []

    def test_resolves_before_comparing(self, tmp_path):
        """The --mirror-to shape: the victim's source path is typed with a
        ``..`` segment, so only a resolved comparison catches the hazard."""
        victim_typed = tmp_path / "sub" / ".." / "a.mp4"
        pairs = [
            (victim_typed, tmp_path / "a.mp4"),
            (tmp_path / "a.mkv", tmp_path / "a.mp4"),
        ]

        hazards = find_overwrite_hazards(pairs)

        assert hazards == [(victim_typed, tmp_path / "a.mkv")]


class TestSourceSelectionScenarios:
    """End-to-end per `docs/design/source-selection.md`, composing the
    paths.py predicates the way a future cli.py (issue #15) will -- no ffmpeg
    or profile involved, matching the design's claim that selection finishes
    before any subprocess call.
    """

    def test_nested_output_root_converges_on_the_second_run(self, tmp_path):
        """`-r IN IN\\converted` must not grow a `converted\\converted\\...`
        generation on every run."""
        input_root = tmp_path / "Media"
        output_root = input_root / "converted"
        touch(input_root / "a.mkv")

        converted, _skipped, hazards = select(input_root, output_root, [".mkv"], ".mp4")
        assert [p.name for p in converted] == ["a.mkv"]
        assert hazards == []
        for src in converted:
            touch(output_for(src, input_root, output_root, ".mp4"))

        converted2, _skipped2, _hazards2 = select(input_root, output_root, [".mkv"], ".mp4")
        assert converted2 == []

    def test_ancestor_output_root_converts_and_stays_idempotent(self, tmp_path):
        """`-r IN\\Sub IN` writes one level up; a rule written as "lies under
        the output root" alone would exclude the candidate and report a
        successful run that did nothing."""
        input_root = tmp_path / "Media" / "Sub"
        output_root = tmp_path / "Media"
        touch(input_root / "a.mkv")

        converted, _skipped, hazards = select(input_root, output_root, [".mkv"], ".mp4")
        assert [p.name for p in converted] == ["a.mkv"]
        assert hazards == []
        for src in converted:
            touch(output_for(src, input_root, output_root, ".mp4"))

        converted2, _skipped2, _hazards2 = select(input_root, output_root, [".mkv"], ".mp4")
        assert converted2 == []

    def test_overwrite_pair_without_overwrite_reports_two_skipped(self, tmp_path):
        """a.mp4 self-writes and is skipped; a.mkv sees an existing output and
        is skipped too. Nothing is at risk, so the run stays harmless."""
        touch(tmp_path / "a.mkv")
        touch(tmp_path / "a.mp4")

        converted, skipped, hazards = select(
            tmp_path, tmp_path, [".mkv", ".mp4"], ".mp4", overwrite=False
        )

        assert converted == []
        assert {p.name for p in skipped} == {"a.mkv", "a.mp4"}
        assert hazards == []

    def test_overwrite_pair_with_overwrite_refuses_the_run(self, tmp_path):
        """With --overwrite, a.mkv would destroy a.mp4 -- a file the run would
        otherwise have reported as kept -- so the whole run is refused,
        naming both files."""
        touch(tmp_path / "a.mkv")
        touch(tmp_path / "a.mp4")

        _converted, _skipped, hazards = select(
            tmp_path, tmp_path, [".mkv", ".mp4"], ".mp4", overwrite=True
        )

        assert [(v.name, w.name) for v, w in hazards] == [("a.mp4", "a.mkv")]

    def test_mirror_to_self_write_is_still_caught(self, tmp_path):
        """Under --mirror-to the output root is derived from a *resolved*
        input path while discovery returns paths built from the root as
        typed -- simulated here with a `..` segment standing in for a second
        drive, since comparing as given would miss this self-write."""
        real_input = tmp_path / "Media"
        touch(real_input / "a.mp4")
        typed_input = tmp_path / "Media" / "x" / ".."

        src = typed_input / "a.mp4"
        dst = output_for(src, typed_input, real_input.resolve(), ".mp4")

        assert is_self_write(src, dst) is True

    def test_mirror_to_overwrite_hazard_is_still_caught(self, tmp_path):
        """The same typed-vs-resolved mismatch, now for the hazard guard:
        the one-directory test above cannot tell "compares as given" and
        "compares resolved" apart, this one can."""
        real_input = tmp_path / "Media"
        touch(real_input / "a.mp4")
        touch(real_input / "a.mkv")
        typed_input = tmp_path / "Media" / "x" / ".."

        pairs = [
            (src, output_for(src, typed_input, real_input.resolve(), ".mp4"))
            for src in (typed_input / "a.mp4", typed_input / "a.mkv")
        ]

        hazards = find_overwrite_hazards(pairs)

        assert len(hazards) == 1
        victim, writer = hazards[0]
        assert victim.name == "a.mp4"
        assert writer.name == "a.mkv"

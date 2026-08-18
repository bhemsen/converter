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
    find_sources,
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

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
    input_root,
    is_self_write,
    list_directories,
    mirror_to_drive,
    normalise_suffixes,
    output_for,
    partial_for,
    select_input,
    sidecar_language,
    sidecar_paths,
    stale_sidecar_partials,
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


class TestInputRoot:
    """`docs/specs/archive/spec-single-file-input.md`: a file INPUT behaves like its
    parent directory, so the root these functions build on is the parent,
    as typed and never resolved."""

    def test_file_returns_its_parent(self, tmp_path):
        touch(tmp_path / "song.flac")

        assert input_root(tmp_path / "song.flac") == tmp_path

    def test_bare_relative_file_name_returns_dot(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        touch(tmp_path / "song.flac")

        assert input_root("song.flac") == Path()

    def test_directory_is_returned_unchanged(self, tmp_path):
        assert input_root(tmp_path) == tmp_path

    def test_missing_path_is_returned_unchanged(self, tmp_path):
        missing = tmp_path / "nope"

        assert input_root(missing) == missing


class TestSelectInput:
    """A file bypasses the suffix set and the directory walk entirely; a
    directory or a missing path defers to `find_sources` unchanged."""

    def test_file_is_its_own_one_file_batch(self, tmp_path):
        target = touch(tmp_path / "song.flac")

        assert select_input(target, [".mkv"]) == [target]

    def test_file_suffix_outside_the_set_still_yields_it(self, tmp_path):
        """The user named the file, so ffprobe -- not an extension list --
        decides whether it is readable."""
        target = touch(tmp_path / "clip.dat")

        assert select_input(target, [".mkv", ".mp4"]) == [target]

    def test_bare_relative_file_name(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        touch(tmp_path / "song.flac")

        assert select_input("song.flac", [".mkv"]) == [Path("song.flac")]

    def test_directory_matches_find_sources(self, tmp_path):
        touch(tmp_path / "a.mkv")
        touch(tmp_path / "b.mp4")

        assert select_input(tmp_path, [".mkv"]) == find_sources(tmp_path, [".mkv"])

    def test_directory_honours_recursive_and_exclude(self, tmp_path):
        touch(tmp_path / "top.mkv")
        touch(tmp_path / "nested" / "deep.mkv")
        touch(tmp_path / "converted" / "done.mkv")

        result = select_input(tmp_path, [".mkv"], recursive=True, exclude=tmp_path / "converted")

        assert result == find_sources(
            tmp_path, [".mkv"], recursive=True, exclude=tmp_path / "converted"
        )
        assert [p.name for p in result] == ["deep.mkv", "top.mkv"]

    def test_missing_path_raises_not_a_directory(self, tmp_path):
        with pytest.raises(NotADirectoryError):
            select_input(tmp_path / "nope", [".mkv"])


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


class TestPartialFor:
    def test_appends_the_partial_suffix(self):
        assert partial_for(Path("clip.mp4")) == Path("clip.mp4.partial")

    def test_does_not_replace_the_existing_suffix(self):
        """`.partial` is appended, not substituted for -- a `with_suffix` call
        would turn `clip.mp4` into `clip.partial`, losing the container."""
        result = partial_for(Path("clip.mp4"))

        assert result.suffix == ".partial"
        assert result.name == "clip.mp4.partial"

    def test_keeps_the_directory_tree(self, tmp_path):
        result = partial_for(tmp_path / "a" / "clip.mkv")

        assert result == tmp_path / "a" / "clip.mkv.partial"

    def test_accepts_a_plain_string(self):
        assert partial_for("clip.mp4") == Path("clip.mp4.partial")

    def test_does_not_touch_the_filesystem(self, tmp_path, monkeypatch):
        """Pure by contract (docs/specs/archive/spec-abort-safe-writes.md): no
        Path.exists/stat/mkdir call is allowed to sneak in."""

        def fail(*_args, **_kwargs):
            raise AssertionError("partial_for must not touch the filesystem")

        monkeypatch.setattr(Path, "exists", fail)
        monkeypatch.setattr(Path, "stat", fail)

        partial_for(tmp_path / "clip.mp4")


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
        """A ``..`` segment must not hide a self-write -- ``--mirror-to`` can be
        pointed at the same file two different ways (a `subst`/junction/
        symlinked INPUT, or the real path behind it), so comparing as given
        would miss it."""
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
        """A `subst`/junction/symlinked INPUT can name the same file as
        ``--mirror-to``'s target under a different spelling: the victim's
        source path is typed with a ``..`` segment standing in for that, so
        only a resolved comparison catches the hazard."""
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
        """A `subst`/junction/symlinked INPUT can be named through the alias
        or through the real path behind it, and so can --mirror-to's target --
        simulated here with a `..` segment standing in for the alias, since
        comparing as given would miss this self-write once the two spellings
        diverge textually."""
        real_input = tmp_path / "Media"
        touch(real_input / "a.mp4")
        typed_input = tmp_path / "Media" / "x" / ".."

        src = typed_input / "a.mp4"
        dst = output_for(src, typed_input, real_input.resolve(), ".mp4")

        assert is_self_write(src, dst) is True

    def test_mirror_to_overwrite_hazard_is_still_caught(self, tmp_path):
        """The same alias-vs-real-path mismatch, now for the hazard guard:
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


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("eng", "eng"),
        ("EN", "en"),
        ("pt-BR", "pt-br"),
        ("", "und"),
        ("12", "und"),
        ("en.x", "und"),
        ("english", "und"),
    ],
)
def test_sidecar_language_normalises_or_falls_back_to_und(tag, expected):
    assert sidecar_language(tag) == expected


class TestSidecarPaths:
    dst = Path("out") / "ep1.mp4"

    def names(self, languages):
        return [p.name for p in sidecar_paths(self.dst, languages, ".vtt")]

    def test_one_stream_is_bare(self):
        assert self.names(["eng"]) == ["ep1.eng.vtt"]

    def test_same_language_counts_from_two(self):
        assert self.names(["eng", "eng"]) == ["ep1.eng.vtt", "ep1.eng.2.vtt"]
        assert self.names(["eng"] * 3) == ["ep1.eng.vtt", "ep1.eng.2.vtt", "ep1.eng.3.vtt"]

    def test_raw_tags_are_normalised_before_counting(self):
        assert self.names(["EN", "en"]) == ["ep1.en.vtt", "ep1.en.2.vtt"]

    def test_several_und_are_counted_like_any_language(self):
        assert self.names(["", "12", "english"]) == [
            "ep1.und.vtt",
            "ep1.und.2.vtt",
            "ep1.und.3.vtt",
        ]

    def test_mixed_languages_count_independently_in_order(self):
        assert self.names(["eng", "ger", "eng", "", "ger", ""]) == [
            "ep1.eng.vtt",
            "ep1.ger.vtt",
            "ep1.eng.2.vtt",
            "ep1.und.vtt",
            "ep1.ger.2.vtt",
            "ep1.und.2.vtt",
        ]

    def test_sidecars_sit_beside_the_mp4(self):
        assert sidecar_paths(self.dst, ["eng"], ".vtt") == [Path("out") / "ep1.eng.vtt"]


def test_adversarial_stems_never_share_a_sidecar_or_mp4_name():
    stems = ["ep1", "ep1.eng", "ep1.eng.2", "ep1.und", "ep1.eng.2.eng", "Ep1"]
    languages = ["eng", "eng", "eng", "und", "", "12", "pt-BR", "en.x"]
    owners: dict[str, tuple[str, str]] = {}
    for stem in stems:
        dst = Path(f"{stem}.mp4")
        entries = [(dst, "mp4")] + [(p, "sidecar") for p in sidecar_paths(dst, languages, ".vtt")]
        for path, kind in entries:
            key = os.path.normcase(path.name)
            if key in owners:
                # Two names of one stem may repeat only if normcase folds the stems together.
                assert owners[key][0] != stem or kind == "sidecar"
                assert os.path.normcase(owners[key][0]) == os.path.normcase(stem), (
                    f"{path.name} produced by {owners[key]} and {(stem, kind)}"
                )
            owners[key] = (stem, kind)


class TestStaleSidecarPartials:
    def names(self, directory, stem="ep1", suffix=".vtt"):
        return sorted(p.name for p in stale_sidecar_partials(directory / f"{stem}.mp4", suffix))

    def test_finds_the_partials_of_this_stem_only(self, tmp_path):
        for name in ("ep1.eng.vtt.partial", "ep1.eng.2.vtt.partial", "ep1.und.vtt.partial"):
            touch(tmp_path / name)
        touch(tmp_path / "ep1.eng.vtt")
        touch(tmp_path / "ep1.mp4.partial")
        touch(tmp_path / "ep10.eng.vtt.partial")
        touch(tmp_path / "other.eng.vtt.partial")

        assert self.names(tmp_path) == [
            "ep1.eng.2.vtt.partial",
            "ep1.eng.vtt.partial",
            "ep1.und.vtt.partial",
        ]

    def test_does_not_take_the_partials_of_a_longer_dotted_stem(self, tmp_path):
        touch(tmp_path / "ep1.eng.eng.vtt.partial")
        touch(tmp_path / "ep1.eng.2.eng.vtt.partial")
        touch(tmp_path / "ep1.eng.2.vtt.partial")

        assert self.names(tmp_path, "ep1.eng") == ["ep1.eng.eng.vtt.partial"]
        assert self.names(tmp_path, "ep1.eng.2") == ["ep1.eng.2.eng.vtt.partial"]
        assert self.names(tmp_path, "ep1") == ["ep1.eng.2.vtt.partial"]

    def test_counter_is_an_integer_of_at_least_two(self, tmp_path):
        for name in ("ep1.eng.1.vtt.partial", "ep1.eng.0.vtt.partial", "ep1.eng.12.vtt.partial"):
            touch(tmp_path / name)

        assert self.names(tmp_path) == ["ep1.eng.12.vtt.partial"]

    def test_strasse_does_not_sweep_strasse_sharp_s(self, tmp_path):
        touch(tmp_path / "Straße.eng.vtt.partial")
        touch(tmp_path / "Strasse.eng.vtt.partial")

        assert self.names(tmp_path, "Strasse") == ["Strasse.eng.vtt.partial"]
        assert self.names(tmp_path, "Straße") == ["Straße.eng.vtt.partial"]

    @pytest.mark.skipif(
        os.path.normcase("Ep1") != "Ep1",
        reason="normcase folds case here, so Ep1 and ep1 are one name",
    )
    def test_case_distinct_stems_stay_apart_where_normcase_is_identity(self, tmp_path):
        touch(tmp_path / "Ep1.eng.vtt.partial")
        touch(tmp_path / "ep1.eng.vtt.partial")

        assert self.names(tmp_path, "ep1") == ["ep1.eng.vtt.partial"]
        assert self.names(tmp_path, "Ep1") == ["Ep1.eng.vtt.partial"]

    @pytest.mark.skipif(os.path.normcase("Ep1") == "Ep1", reason="normcase is the identity here")
    def test_case_variants_are_one_name_where_normcase_folds(self, tmp_path):
        touch(tmp_path / "Ep1.eng.vtt.partial")

        assert self.names(tmp_path, "ep1") == ["Ep1.eng.vtt.partial"]

    def test_a_stem_with_regex_metacharacters_matches_literally(self, tmp_path):
        stem = "a[1](x)+b"
        touch(tmp_path / f"{stem}.eng.vtt.partial")
        touch(tmp_path / "a1x+b.eng.vtt.partial")
        touch(tmp_path / "a[1](x)b.eng.vtt.partial")

        assert self.names(tmp_path, stem) == [f"{stem}.eng.vtt.partial"]

    def test_a_missing_directory_yields_nothing(self, tmp_path):
        assert stale_sidecar_partials(tmp_path / "gone" / "ep1.mp4", ".vtt") == []

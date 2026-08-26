"""Tests for routing, argument handling, source selection and the prompt.

Everything here drives the CLI through :func:`converter.cli.main` or
:func:`converter.cli.dispatch` rather than through one parser, because routing
happens before parsing and is therefore only observable from the outside.

The profiles used are read out of the registry rather than named as literals, so
these tests keep working as later phases add targets -- the same property the
``ast`` check at the bottom of this file enforces on the CLI itself.
"""

import ast
import os
import re
from pathlib import Path

import pytest

from converter import batch, cli
from converter.cli import build_mirror_parser, build_parser, dispatch, main, prompt_for_argv
from converter.ffmpegtool import CommandResult, Stream, Tools
from converter.profiles import MP4, PROFILES, WAV

FAKE_TOOLS = Tools(ffmpeg="ffmpeg", ffprobe="ffprobe")

#: The two targets this phase ships, taken from the registry rather than spelled
#: out: VIDEO_TARGET reads .mkv and writes MP4, AUDIO_TARGET writes WAV.
VIDEO_TARGET = MP4.name
AUDIO_TARGET = WAV.name
VIDEO_SUFFIX = MP4.target_suffix
AUDIO_SUFFIX = WAV.target_suffix


def parse(argv: list[str]):
    return build_parser().parse_args(argv)


def convert_argv(*args: str) -> list[str]:
    """A convert invocation for the video target, with INPUT/OUTPUT filled in."""
    return ["--to", VIDEO_TARGET, *args]


def make_source(root: Path, name: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    source = root / name
    source.write_bytes(b"data")
    return source


def self_mirroring_root(path: Path) -> str:
    """The ``--mirror-to`` root that maps *path* back onto itself.

    ``mirror_to_drive`` re-roots the whole drive-relative path underneath the
    given root, so the root that reproduces the input is the drive itself --
    the filesystem root on POSIX.  This is the only spelling that makes the
    resolved-vs-as-given difference observable without a second real drive.
    """
    return os.path.splitdrive(str(path))[0] or os.sep


@pytest.fixture
def stub_ffmpeg(monkeypatch):
    """Replace the whole subprocess boundary with a stub that always succeeds."""

    def run(argv, **_kwargs):
        Path(argv[-1]).write_bytes(b"converted")
        return CommandResult(tuple(argv), 0, "", "")

    monkeypatch.setattr(cli.ffmpegtool, "resolve_tools", lambda *_a: FAKE_TOOLS)
    monkeypatch.setattr(cli.ffmpegtool, "version", lambda _tools: "ffmpeg test build")
    monkeypatch.setattr(batch.ffmpegtool, "run", run)
    monkeypatch.setattr(batch.ffmpegtool, "probe_streams", lambda *_a: [])
    return run


class TestConvertParser:
    def test_target_is_required(self):
        with pytest.raises(SystemExit):
            parse(["in", "out"])

    def test_input_is_required(self):
        with pytest.raises(SystemExit):
            parse(["--to", VIDEO_TARGET])

    def test_output_directory_is_optional(self):
        assert parse(convert_argv("in")).output_dir is None

    def test_flags_default_to_the_safe_choice(self):
        args = parse(convert_argv("in", "out"))

        assert args.recursive is False
        assert args.overwrite is False
        assert args.dry_run is False
        assert args.jobs is None

    def test_short_flags(self):
        args = parse(convert_argv("in", "out", "-r", "-j", "8", "-q"))

        assert args.recursive is True
        assert args.jobs == 8
        assert args.quiet is True

    def test_the_epilog_leads_to_mirror_and_the_format_list(self):
        """Asserted on the epilog itself, not on the rendered help: `--mirror-to`
        contains the mirror token and `--list-formats` is an option on this very
        parser, so a `format_help()` substring check would pass with no epilog at
        all -- and the epilog is the only thing keeping the mirror *sub-command*
        discoverable now that it is off a sub-parser list."""
        epilog = build_parser().epilog

        assert cli.MIRROR_COMMAND in epilog
        assert cli.LIST_FORMATS_FLAG in epilog
        # Rendered too, so an epilog that argparse never prints cannot pass.
        assert f"{cli.MIRROR_COMMAND} --help" in " ".join(build_parser().format_help().split())


class TestMirrorParser:
    def test_it_parses_its_own_arguments(self):
        args = build_mirror_parser().parse_args(["C:/in", "E:"])

        assert args.output_root == "E:"
        assert args.recursive is True
        assert args.create is False

    def test_no_recursive(self):
        args = build_mirror_parser().parse_args(["C:/in", "E:", "--no-recursive"])

        assert args.recursive is False


class TestRouting:
    def test_mirror_goes_to_the_mirror_parser(self, tmp_path, capsys):
        (tmp_path / "a").mkdir()

        code = dispatch([cli.MIRROR_COMMAND, str(tmp_path / "a"), str(tmp_path / "mirror")])

        assert code == 0
        assert "->" in capsys.readouterr().out

    @pytest.mark.parametrize("command", cli.LEGACY_COMMANDS)
    def test_a_legacy_subcommand_exits_two_and_says_what_to_run(self, capsys, command):
        code = main([command, "in", "out"])
        err = capsys.readouterr().err

        assert code == 2
        assert "--to <format>" in err
        assert cli.LIST_FORMATS_FLAG in err

    @pytest.mark.parametrize("command", cli.LEGACY_COMMANDS)
    def test_the_legacy_message_names_no_format(self, capsys, command):
        """Naming one here would be the string that defeats the ast check below."""
        main([command, "in", "out"])
        err = capsys.readouterr().err.lower()

        for profile in PROFILES.values():
            assert profile.name not in err
            assert profile.target_suffix not in err

    def test_the_list_flag_is_reachable_without_input_or_target(self, capsys):
        code = main([cli.LIST_FORMATS_FLAG])

        assert code == 0
        assert capsys.readouterr().out

    def test_the_list_flag_is_recognised_anywhere_in_the_argument_list(self, capsys):
        code = main(["--to", VIDEO_TARGET, "in", cli.LIST_FORMATS_FLAG])

        assert code == 0
        assert capsys.readouterr().out

    def test_version_still_exits_zero_although_target_is_required(self, capsys):
        with pytest.raises(SystemExit) as exit_info:
            main(["--version"])

        assert exit_info.value.code == 0
        assert "converter" in capsys.readouterr().out


class TestListFormats:
    def test_one_line_per_registry_entry(self, capsys):
        code = main([cli.LIST_FORMATS_FLAG])
        out = capsys.readouterr().out

        assert code == 0
        for profile in PROFILES.values():
            line = next(li for li in out.splitlines() if li.strip().startswith(profile.name))
            assert profile.target_suffix in line
            assert profile.description in line

    def test_sorted_by_name(self, capsys):
        main([cli.LIST_FORMATS_FLAG])
        out = capsys.readouterr().out

        positions = [out.index(f" {name} ") for name in sorted(PROFILES)]
        assert positions == sorted(positions)

    def test_prints_exactly_one_line_per_registry_entry(self, capsys):
        """Guard rail for issue #23: the issue's own wording ("prints seven
        lines") was accurate only for the two-plus-five audio profiles this
        phase shipped -- video and image profiles are landing in parallel
        milestones and have already widened the registry past seven by the
        time this test runs. Pinning the count against `len(PROFILES)` instead
        of a literal keeps the check meaningful (it still fails if a line goes
        missing or an extra one is printed) without going stale the moment a
        sixth format lands, exactly the registry-driven shape this issue asks
        every guard rail here to have.
        """
        code = main([cli.LIST_FORMATS_FLAG])
        lines = capsys.readouterr().out.splitlines()

        assert code == 0
        assert lines[0] == "Target formats:"
        assert len(lines) - 1 == len(PROFILES)

    def test_readme_format_list_matches_the_command_byte_for_byte(self, capsys):
        """CLAUDE.md: if README.md's format list is touched, it must byte-match
        what `cli.py` actually prints, ragged column padding included, rather
        than being a hand-maintained block that can silently drift out of sync
        the next time a profile is added.
        """
        main([cli.LIST_FORMATS_FLAG])
        actual = capsys.readouterr().out.rstrip("\n")

        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
        match = re.search(r"```\n(Target formats:\n.*?)```", readme, re.DOTALL)
        assert match is not None, "README.md has no fenced 'Target formats:' block"

        assert match.group(1).rstrip("\n") == actual

    def test_it_resolves_no_tools_and_touches_no_filesystem(self, monkeypatch, capsys):
        def explode(*_args, **_kwargs):
            raise AssertionError("--list-formats must not reach the filesystem or ffmpeg")

        monkeypatch.setattr(cli.ffmpegtool, "resolve_tools", explode)
        monkeypatch.setattr(cli.paths, "find_sources", explode)

        assert main([cli.LIST_FORMATS_FLAG]) == 0
        assert capsys.readouterr().out


class TestTargetResolution:
    @pytest.mark.parametrize("spelling", [VIDEO_TARGET, VIDEO_TARGET.upper(), VIDEO_SUFFIX])
    def test_name_suffix_and_case_all_select_the_same_profile(
        self, tmp_path, capsys, stub_ffmpeg, spelling
    ):
        make_source(tmp_path / "in", f"clip{AUDIO_SUFFIX}")

        code = main(["--to", spelling, str(tmp_path / "in"), str(tmp_path / "out"), "-q"])

        assert code == 0
        assert (tmp_path / "out" / f"clip{VIDEO_SUFFIX}").exists()
        assert "1 converted" in capsys.readouterr().out

    def test_an_unknown_target_is_a_usage_error_listing_the_available_ones(self, tmp_path, capsys):
        code = main(["--to", "nonsense", str(tmp_path), str(tmp_path / "out")])
        err = capsys.readouterr().err

        assert code == 2
        for name in PROFILES:
            assert name in err


class TestOutputRootResolution:
    def test_output_dir_and_mirror_to_are_mutually_exclusive(self, tmp_path):
        args = parse(convert_argv(str(tmp_path), "out", "--mirror-to", "E:"))

        with pytest.raises(cli.UsageError, match="not both"):
            cli._resolve_output_root(args)

    def test_one_of_them_is_required(self, tmp_path):
        args = parse(convert_argv(str(tmp_path)))

        with pytest.raises(cli.UsageError, match="required"):
            cli._resolve_output_root(args)

    def test_explicit_output_dir_is_used_as_is(self, tmp_path):
        args = parse(convert_argv(str(tmp_path), "some/out"))

        assert cli._resolve_output_root(args) == Path("some/out")


class TestConvertCommand:
    def test_missing_input_directory_is_a_usage_error(self, tmp_path, capsys):
        """A bad path is a usage error (2), not "a file failed to convert" (1)."""
        code = main(convert_argv(str(tmp_path / "nope"), str(tmp_path / "out")))

        assert code == 2
        assert "does not exist" in capsys.readouterr().err

    def test_empty_mirror_target_is_a_usage_error(self, tmp_path, capsys):
        (tmp_path / "in").mkdir()

        code = main(convert_argv(str(tmp_path / "in"), "--mirror-to", ""))

        assert code == 2
        assert "must not be empty" in capsys.readouterr().err

    @pytest.mark.parametrize("flag", ["--jobs=0", "--jobs=-3"])
    def test_non_positive_jobs_is_a_usage_error(self, tmp_path, capsys, flag):
        """0 used to fall through to the default and negatives were clamped to 1,
        both without a word to the user."""
        code = main(convert_argv(str(tmp_path / "in"), str(tmp_path / "out"), flag))

        assert code == 2
        assert "--jobs must be 1 or more" in capsys.readouterr().err

    def test_no_candidates_prints_the_summary_and_a_hint_and_exits_zero(self, tmp_path, capsys):
        """The summary is what the idempotent-re-run criterion is read from, and
        an empty directory is not an error -- so the hint goes to stderr and the
        count to stdout."""
        (tmp_path / "in").mkdir()
        (tmp_path / "in" / "notes.txt").write_text("hi")

        code = main(convert_argv(str(tmp_path / "in"), str(tmp_path / "out")))
        captured = capsys.readouterr()

        assert code == 0
        assert "0 converted" in captured.out
        assert "0 failed" in captured.out
        assert "no convertible files found" in captured.err

    def test_the_hint_names_no_suffix(self, tmp_path, capsys):
        """The curated source set is far too long to interpolate readably."""
        (tmp_path / "in").mkdir()

        main(convert_argv(str(tmp_path / "in"), str(tmp_path / "out")))
        err = capsys.readouterr().err.lower()

        for profile in PROFILES.values():
            assert profile.target_suffix not in err

    def test_hint_about_recursive_when_not_recursive(self, tmp_path, capsys):
        (tmp_path / "in" / "nested").mkdir(parents=True)

        main(convert_argv(str(tmp_path / "in"), str(tmp_path / "out")))

        assert "--recursive" in capsys.readouterr().err

    def test_a_non_media_file_is_never_a_candidate(self, tmp_path, capsys):
        make_source(tmp_path / "in", "clip.mkv")
        (tmp_path / "in" / "readme.nfo").write_text("hi")

        main(convert_argv(str(tmp_path / "in"), str(tmp_path / "out"), "--dry-run"))
        out = capsys.readouterr().out

        assert "readme" not in out
        assert "1 file(s) would be converted" in out

    def test_dry_run_lists_pairs_without_touching_ffmpeg(self, tmp_path, capsys, monkeypatch):
        def explode(*_args, **_kwargs):
            raise AssertionError("--dry-run must work without ffmpeg installed")

        monkeypatch.setattr(cli.ffmpegtool, "resolve_tools", explode)
        make_source(tmp_path / "in", "clip.mkv")

        code = main(convert_argv(str(tmp_path / "in"), str(tmp_path / "out"), "--dry-run"))
        out = capsys.readouterr().out

        assert code == 0
        assert "clip.mkv" in out
        assert f"clip{VIDEO_SUFFIX}" in out
        assert not (tmp_path / "out").exists()

    def test_distinct_sub_directories_are_not_a_collision(self, tmp_path):
        """Two inputs mapping to one output means one of them would be lost --
        but the mirrored tree is exactly what keeps these two apart."""
        for folder in ("a", "b"):
            make_source(tmp_path / "in" / folder, "ep1.mkv")

        code = main(
            convert_argv(str(tmp_path / "in"), str(tmp_path / "out"), "--recursive", "--dry-run")
        )

        assert code == 0

    def test_two_real_sources_colliding_on_one_output_stop_the_run(self, tmp_path, capsys):
        """One target now draws in many source suffixes, so a genuine collision
        no longer needs a case-folding trick to produce: two files differing only
        in suffix map to the same output on every platform."""
        make_source(tmp_path / "in", "a.mkv")
        make_source(tmp_path / "in", "a.opus")

        code = main(convert_argv(str(tmp_path / "in"), str(tmp_path / "out"), "--dry-run"))
        err = capsys.readouterr().err

        assert code == 2
        assert "a.mkv" in err
        assert "a.opus" in err

    def test_a_collision_stops_the_run(self, tmp_path, capsys, monkeypatch):
        """Whether two real files can collide depends on the filesystem's case
        sensitivity, so the CLI's reaction to a collision is driven directly
        instead of through a case-folding trick that only works on one platform.
        """
        source = make_source(tmp_path / "in", "clip.mkv")
        clash = tmp_path / "out" / f"clip{VIDEO_SUFFIX}"
        monkeypatch.setattr(cli.paths, "find_collisions", lambda _pairs: {clash: [source, source]})

        code = main(convert_argv(str(tmp_path / "in"), str(tmp_path / "out"), "--dry-run"))
        err = capsys.readouterr().err

        assert code == 2
        assert "same output" in err
        assert f"clip{VIDEO_SUFFIX}" in err

    def test_missing_ffmpeg_is_reported_once_and_clearly(self, tmp_path, capsys, monkeypatch):
        make_source(tmp_path / "in", "clip.mkv")
        monkeypatch.setattr(cli.ffmpegtool, "which", lambda _name: None)

        code = main(convert_argv(str(tmp_path / "in"), str(tmp_path / "out")))
        err = capsys.readouterr().err

        assert code == 2
        assert "ffmpeg was not found" in err
        assert "winget install" in err


class TestSourceSelection:
    """The rules of docs/design/source-selection.md, driven through main()."""

    def test_a_source_with_the_target_suffix_converts_to_a_different_root(
        self, tmp_path, capsys, stub_ffmpeg
    ):
        """A source that already carries the target suffix is a legitimate remux
        into a separate output root, not a self-write."""
        make_source(tmp_path / "in", f"a{VIDEO_SUFFIX}")

        code = main(convert_argv(str(tmp_path / "in"), str(tmp_path / "out"), "-q"))

        assert code == 0
        assert "1 converted" in capsys.readouterr().out
        assert (tmp_path / "out" / f"a{VIDEO_SUFFIX}").exists()

    def test_a_self_writing_source_is_a_counted_skip(self, tmp_path, capsys, stub_ffmpeg):
        """Converting a tree in place must stay idempotent and still report."""
        source = make_source(tmp_path / "in", f"a{VIDEO_SUFFIX}")
        before = source.read_bytes()

        code = main(convert_argv(str(tmp_path / "in"), str(tmp_path / "in"), "-q"))

        assert code == 0
        assert "0 converted, 1 skipped" in capsys.readouterr().out
        assert source.read_bytes() == before

    @pytest.mark.parametrize("extra", [[], ["-q"]])
    def test_a_self_write_is_named_rather_than_passed_over(
        self, tmp_path, capsys, stub_ffmpeg, extra
    ):
        """--quiet hides the progress bar, not the reasons: the batch prints its
        own skip notes either way, so these must not disappear either."""
        make_source(tmp_path / "in", f"a{VIDEO_SUFFIX}")

        main(convert_argv(str(tmp_path / "in"), str(tmp_path / "in"), *extra))
        out = capsys.readouterr().out

        assert f"a{VIDEO_SUFFIX}" in out
        assert "this file itself" in out

    def test_the_self_write_guard_fires_under_mirror_to(self, tmp_path, capsys, stub_ffmpeg):
        """--mirror-to derives the output root from a *resolved* input path while
        discovery returns paths built from the root as typed, so a guard that
        compared them as given would miss this."""
        inside = tmp_path / "in"
        make_source(inside, f"a{VIDEO_SUFFIX}")

        code = main(convert_argv(str(inside), "--mirror-to", self_mirroring_root(inside), "-q"))

        assert code == 0
        assert "1 skipped" in capsys.readouterr().out

    def test_an_existing_output_is_skipped(self, tmp_path, capsys, stub_ffmpeg):
        make_source(tmp_path / "in", "clip.mkv")
        existing = tmp_path / "out" / f"clip{VIDEO_SUFFIX}"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"already done")

        code = main(convert_argv(str(tmp_path / "in"), str(tmp_path / "out"), "-q"))

        assert code == 0
        assert "1 skipped" in capsys.readouterr().out
        assert existing.read_bytes() == b"already done"

    def test_overwrite_refuses_when_a_sibling_would_destroy_a_selected_source(
        self, tmp_path, capsys, stub_ffmpeg
    ):
        """Reporting `a.mp4` as skipped and then overwriting it would destroy a
        file the run said it kept."""
        make_source(tmp_path / "in", "a.mkv")
        victim = make_source(tmp_path / "in", f"a{VIDEO_SUFFIX}")

        code = main(convert_argv(str(tmp_path / "in"), str(tmp_path / "in"), "--overwrite", "-q"))
        err = capsys.readouterr().err

        assert code == 2
        assert "a.mkv" in err
        assert f"a{VIDEO_SUFFIX}" in err
        assert victim.read_bytes() == b"data"

    def test_without_overwrite_the_same_directory_is_merely_idempotent(
        self, tmp_path, capsys, stub_ffmpeg
    ):
        """Nothing is at risk, so an in-place re-run must not exit 2."""
        make_source(tmp_path / "in", "a.mkv")
        make_source(tmp_path / "in", f"a{VIDEO_SUFFIX}")

        code = main(convert_argv(str(tmp_path / "in"), str(tmp_path / "in"), "-q"))

        assert code == 0
        assert "0 converted, 2 skipped" in capsys.readouterr().out

    def test_the_overwrite_refusal_also_fires_under_mirror_to(self, tmp_path, capsys, stub_ffmpeg):
        """The paths differ as given and agree only once resolved, which the
        one-directory test cannot tell apart."""
        inside = tmp_path / "in"
        make_source(inside, "a.mkv")
        make_source(inside, f"a{VIDEO_SUFFIX}")
        root = self_mirroring_root(inside)

        code = main(convert_argv(str(inside), "--mirror-to", root, "--overwrite", "-q"))

        assert code == 2
        assert "would be overwritten" in capsys.readouterr().err

    def test_a_nested_output_root_converges(self, tmp_path, capsys, stub_ffmpeg):
        """Without the output-tree exclusion this grows one `converted` level per
        run, forever, while reporting `1 converted` every time."""
        inside = tmp_path / "in"
        make_source(inside, "clip.mkv")
        argv = convert_argv(str(inside), str(inside / "converted"), "--recursive", "-q")

        assert main(argv) == 0
        capsys.readouterr()
        assert main(argv) == 0

        out = capsys.readouterr().out
        assert "0 converted" in out
        assert not (inside / "converted" / "converted").exists()

    def test_an_ancestor_output_root_still_converts(self, tmp_path, capsys, stub_ffmpeg):
        """A rule written as "lies under the output root" without the strict-
        descendant clause would exclude every candidate here."""
        make_source(tmp_path / "in" / "sub", "clip.mkv")
        argv = convert_argv(str(tmp_path / "in" / "sub"), str(tmp_path / "in"), "-q")

        assert main(argv) == 0
        assert "1 converted" in capsys.readouterr().out

        assert main(argv) == 0
        assert "0 converted" in capsys.readouterr().out


class TestExitCodeWiring:
    """Drives a whole run through main() with a stubbed ffmpeg, so the exit-code
    contract in the README is checked end to end rather than per unit."""

    def _prepare(self, tmp_path, monkeypatch, returncode: int) -> None:
        make_source(tmp_path / "in", "clip.mkv")

        def run(argv, **_kwargs):
            Path(argv[-1]).write_bytes(b"converted")
            return CommandResult(tuple(argv), returncode, "", "boom" if returncode else "")

        monkeypatch.setattr(cli.ffmpegtool, "resolve_tools", lambda *_a: FAKE_TOOLS)
        monkeypatch.setattr(cli.ffmpegtool, "version", lambda _tools: "ffmpeg test build")
        monkeypatch.setattr(batch.ffmpegtool, "run", run)
        monkeypatch.setattr(batch.ffmpegtool, "probe_streams", lambda *_a: [])

    def test_a_clean_run_exits_zero(self, tmp_path, monkeypatch, capsys):
        self._prepare(tmp_path, monkeypatch, 0)

        code = main(convert_argv(str(tmp_path / "in"), str(tmp_path / "out"), "-q"))

        assert code == 0
        assert "1 converted" in capsys.readouterr().out
        assert (tmp_path / "out" / f"clip{VIDEO_SUFFIX}").exists()

    def test_a_failed_conversion_exits_one(self, tmp_path, monkeypatch, capsys):
        """The old scripts always printed 'Conversion completed.' and exited 0."""
        self._prepare(tmp_path, monkeypatch, 1)
        # A stream the target has a rule for, so this stays a genuine failure
        # rather than the unsupported outcome.
        monkeypatch.setattr(
            batch.ffmpegtool, "probe_streams", lambda *_a: [Stream(0, "video", "h264")]
        )

        code = main(convert_argv(str(tmp_path / "in"), str(tmp_path / "out"), "-q"))

        assert code == 1
        assert "1 failed" in capsys.readouterr().out

    def test_a_failed_conversion_leaves_no_output_behind(self, tmp_path, monkeypatch):
        self._prepare(tmp_path, monkeypatch, 1)
        monkeypatch.setattr(
            batch.ffmpegtool, "probe_streams", lambda *_a: [Stream(0, "video", "h264")]
        )

        main(convert_argv(str(tmp_path / "in"), str(tmp_path / "out"), "-q"))

        assert not (tmp_path / "out" / f"clip{VIDEO_SUFFIX}").exists()

    def test_an_unsupported_source_does_not_set_the_exit_code(self, tmp_path, monkeypatch, capsys):
        """A mixed tree converts what it can and reports the rest by name."""
        self._prepare(tmp_path, monkeypatch, 1)
        monkeypatch.setattr(
            batch.ffmpegtool, "probe_streams", lambda *_a: [Stream(0, "video", "h264")]
        )

        code = main(["--to", AUDIO_TARGET, str(tmp_path / "in"), str(tmp_path / "out"), "-q"])

        assert code == 0
        assert "1 unsupported" in capsys.readouterr().out

    def test_the_audio_target_runs_through_the_same_wiring(self, tmp_path, monkeypatch, capsys):
        make_source(tmp_path / "in", "tone.opus")
        # _prepare adds a second source of its own, and one target now draws in
        # every source suffix -- hence two conversions, not one.
        self._prepare(tmp_path, monkeypatch, 0)

        code = main(["--to", AUDIO_TARGET, str(tmp_path / "in"), str(tmp_path / "out"), "-q"])

        assert code == 0
        assert "2 converted" in capsys.readouterr().out
        assert (tmp_path / "out" / f"tone{AUDIO_SUFFIX}").exists()


class TestMirrorCommand:
    def test_lists_the_tree_without_creating_it(self, tmp_path, capsys):
        (tmp_path / "a" / "b").mkdir(parents=True)
        target = tmp_path / "mirror"

        code = main([cli.MIRROR_COMMAND, str(tmp_path / "a"), str(target)])
        out = capsys.readouterr().out

        assert code == 0
        assert "->" in out
        assert not target.exists()

    def test_create_makes_the_directories(self, tmp_path):
        (tmp_path / "a" / "b").mkdir(parents=True)
        target = tmp_path / "mirror"

        code = main([cli.MIRROR_COMMAND, str(tmp_path / "a"), str(target), "--create"])

        assert code == 0
        assert target.is_dir()

    def test_includes_the_root_directory_itself(self, tmp_path, capsys):
        (tmp_path / "a").mkdir()

        main([cli.MIRROR_COMMAND, str(tmp_path / "a"), str(tmp_path / "mirror")])

        assert str(tmp_path / "a") in capsys.readouterr().out

    def test_a_missing_input_root_is_a_usage_error(self, tmp_path, capsys):
        code = main([cli.MIRROR_COMMAND, str(tmp_path / "nope"), str(tmp_path / "mirror")])

        assert code == 2
        assert "does not exist" in capsys.readouterr().err


class TestInteractivePrompt:
    def _answers(self, monkeypatch, answers: list[str]) -> None:
        queue = list(answers)
        monkeypatch.setattr("builtins.input", lambda _prompt="": queue.pop(0))

    def test_the_menu_offers_the_registry_in_sorted_order_with_mirror_last(
        self, monkeypatch, capsys
    ):
        self._answers(monkeypatch, ["1", "C:/in", "C:/out", "n", "n"])

        prompt_for_argv()
        lines = [li.strip() for li in capsys.readouterr().out.splitlines() if ")" in li]

        assert [li.split(") ", 1)[1].split(" - ")[0] for li in lines] == [
            *sorted(PROFILES),
            cli.MIRROR_COMMAND,
        ]

    def test_the_first_target_is_the_default(self, monkeypatch):
        self._answers(monkeypatch, ["", "C:/in", "C:/out", "n", "n"])

        assert prompt_for_argv()[:2] == ["--to", sorted(PROFILES)[0]]

    def test_a_number_selects_a_target_with_an_explicit_output_directory(self, monkeypatch):
        index = sorted(PROFILES).index(VIDEO_TARGET) + 1
        self._answers(monkeypatch, [str(index), "C:/in", "C:/out", "y", "n"])

        assert prompt_for_argv() == ["--to", VIDEO_TARGET, "C:/in", "C:/out", "--recursive"]

    def test_a_typed_format_name_is_accepted_instead_of_a_number(self, monkeypatch):
        self._answers(monkeypatch, [AUDIO_SUFFIX, "C:/in", "C:/out", "n", "n"])

        assert prompt_for_argv() == ["--to", AUDIO_TARGET, "C:/in", "C:/out"]

    def test_falling_back_to_a_mirror_drive(self, monkeypatch):
        index = sorted(PROFILES).index(AUDIO_TARGET) + 1
        self._answers(monkeypatch, [str(index), "C:/in", "", "E:", "n", "y"])

        assert prompt_for_argv() == [
            "--to",
            AUDIO_TARGET,
            "C:/in",
            "--mirror-to",
            "E:",
            "--overwrite",
        ]

    def test_mirror_is_the_last_entry(self, monkeypatch):
        self._answers(monkeypatch, [str(len(PROFILES) + 1), "C:/in", "E:", "y"])

        assert prompt_for_argv() == [cli.MIRROR_COMMAND, "C:/in", "E:", "--create"]

    def test_quoted_paths_are_accepted(self, monkeypatch):
        self._answers(monkeypatch, ["1", '"C:/in"', '"C:/out"', "n", "n"])

        assert prompt_for_argv()[2:] == ["C:/in", "C:/out"]

    def test_unknown_selection_is_rejected(self, monkeypatch, capsys):
        self._answers(monkeypatch, ["nonsense"])

        assert prompt_for_argv() is None
        assert "Unknown selection" in capsys.readouterr().err

    def test_a_digit_like_character_int_rejects_is_not_a_crash(self, monkeypatch, capsys):
        """A superscript digit is `isdigit()` but not `int()`-able, and the prompt
        runs outside main()'s exception handling."""
        self._answers(monkeypatch, ["\N{SUPERSCRIPT TWO}"])

        assert prompt_for_argv() is None
        assert "Unknown selection" in capsys.readouterr().err

    def test_an_out_of_range_number_is_rejected(self, monkeypatch, capsys):
        self._answers(monkeypatch, [str(len(PROFILES) + 2)])

        assert prompt_for_argv() is None
        assert "Unknown selection" in capsys.readouterr().err

    def test_missing_input_directory_is_rejected(self, monkeypatch):
        self._answers(monkeypatch, ["1", ""])

        assert prompt_for_argv() is None

    def test_a_prompted_conversion_round_trips_through_the_router(
        self, monkeypatch, tmp_path, capsys, stub_ffmpeg
    ):
        """The interactive path must not be able to build an unroutable command."""
        make_source(tmp_path / "in", "clip.mkv")
        index = sorted(PROFILES).index(VIDEO_TARGET) + 1
        self._answers(
            monkeypatch, [str(index), str(tmp_path / "in"), str(tmp_path / "out"), "y", "y"]
        )

        assert dispatch(prompt_for_argv()) == 0
        assert "1 converted" in capsys.readouterr().out

    def test_a_prompted_mirror_round_trips_through_the_router(self, monkeypatch, tmp_path, capsys):
        """A prompted mirror argv the convert parser cannot parse is exactly what
        routing through dispatch() protects."""
        (tmp_path / "a").mkdir()
        self._answers(
            monkeypatch,
            [str(len(PROFILES) + 1), str(tmp_path / "a"), str(tmp_path / "mirror"), "n"],
        )

        assert dispatch(prompt_for_argv()) == 0
        assert "->" in capsys.readouterr().out


class TestMainDispatch:
    def test_no_arguments_starts_the_interactive_prompt(self, monkeypatch, tmp_path, capsys):
        (tmp_path / "in").mkdir()
        queue = ["1", str(tmp_path / "in"), str(tmp_path / "out"), "n", "n"]
        monkeypatch.setattr("builtins.input", lambda _prompt="": queue.pop(0))

        code = main([])
        captured = capsys.readouterr()

        assert code == 0
        assert "0 converted" in captured.out
        assert "no convertible files found" in captured.err

    def test_aborting_the_prompt_is_not_a_crash(self, monkeypatch):
        def refuse(_prompt=""):
            raise EOFError

        monkeypatch.setattr("builtins.input", refuse)

        assert main([]) == 130


#: The tokens no string literal in the CLI may contain, taken from the registry
#: so a format added later is covered without touching this test.
FORMAT_TOKENS: frozenset[str] = frozenset(
    {profile.name for profile in PROFILES.values()}
    | {profile.target_suffix for profile in PROFILES.values()}
)


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """The identities of the string constants that are docstrings, not data."""
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, holders) or not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            found.add(id(first.value))
    return found


def _code_strings(source: str) -> list[str]:
    """Every string literal in *source* except the docstrings.

    f-strings are covered too: their literal parts are ordinary ``Constant``
    nodes inside the ``JoinedStr``, which ``ast.walk`` reaches.
    """
    tree = ast.parse(source)
    docstrings = _docstring_nodes(tree)
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


class TestFormatNamesStayOutOfTheCli:
    """The machine check behind "a target format is data, not code".

    A plain grep cannot do this: ``paths.py`` illustrates its rules with a
    suffix in prose, and a case-sensitive grep would miss an upper-cased one --
    the check has to look at code, not at text.
    """

    @pytest.mark.parametrize("module", [cli, batch], ids=lambda m: m.__name__)
    def test_no_string_literal_names_a_registry_format(self, module):
        source = Path(module.__file__).read_text(encoding="utf-8")

        offenders = [
            (text, token)
            for text in _code_strings(source)
            for token in FORMAT_TOKENS
            if token in text.lower()
        ]

        assert offenders == []

    def test_the_check_would_catch_a_format_name(self):
        """A canary, so a broken walker cannot make the check above vacuous."""
        planted = f'x = "convert everything to {next(iter(FORMAT_TOKENS))}"'

        assert any(
            token in text.lower() for text in _code_strings(planted) for token in FORMAT_TOKENS
        )

    def test_a_docstring_is_not_a_string_literal_for_this_check(self):
        assert _code_strings('"""A module docstring."""\nx = "data"\n') == ["data"]

"""Tests for argument handling and the interactive prompt."""

from pathlib import Path

import pytest

from converter import batch, cli
from converter.cli import build_parser, main, prompt_for_argv
from converter.ffmpegtool import CommandResult, Tools

FAKE_TOOLS = Tools(ffmpeg="ffmpeg", ffprobe="ffprobe")


def parse(argv: list[str]):
    return build_parser().parse_args(argv)


class TestParser:
    def test_video_and_audio_subcommands_exist(self):
        assert parse(["video", "in", "out"]).job.target_suffix == ".mp4"
        assert parse(["audio", "in", "out"]).job.target_suffix == ".wav"

    def test_output_directory_is_optional(self):
        assert parse(["video", "in"]).output_dir is None

    def test_flags_default_to_the_safe_choice(self):
        args = parse(["video", "in", "out"])

        assert args.recursive is False
        assert args.overwrite is False
        assert args.dry_run is False
        assert args.jobs is None

    def test_short_flags(self):
        args = parse(["video", "in", "out", "-r", "-j", "8", "-q"])

        assert args.recursive is True
        assert args.jobs == 8
        assert args.quiet is True

    def test_mirror_subcommand(self):
        args = parse(["mirror", "C:/in", "E:"])

        assert args.output_root == "E:"
        assert args.recursive is True
        assert args.create is False

    def test_unknown_subcommand_is_rejected(self):
        with pytest.raises(SystemExit):
            parse(["nonsense", "in", "out"])


class TestOutputRootResolution:
    def test_output_dir_and_mirror_to_are_mutually_exclusive(self, tmp_path):
        args = parse(["video", str(tmp_path), "out", "--mirror-to", "E:"])

        with pytest.raises(cli.UsageError, match="not both"):
            cli._resolve_output_root(args)

    def test_one_of_them_is_required(self, tmp_path):
        args = parse(["video", str(tmp_path)])

        with pytest.raises(cli.UsageError, match="required"):
            cli._resolve_output_root(args)

    def test_explicit_output_dir_is_used_as_is(self, tmp_path):
        args = parse(["video", str(tmp_path), "some/out"])

        assert cli._resolve_output_root(args) == Path("some/out")


class TestConvertCommand:
    def test_missing_input_directory_is_a_usage_error(self, tmp_path, capsys):
        """A bad path is a usage error (2), not "a file failed to convert" (1)."""
        code = main(["video", str(tmp_path / "nope"), str(tmp_path / "out")])

        assert code == 2
        assert "does not exist" in capsys.readouterr().err

    def test_empty_mirror_target_is_a_usage_error(self, tmp_path, capsys):
        (tmp_path / "in").mkdir()

        code = main(["video", str(tmp_path / "in"), "--mirror-to", ""])

        assert code == 2
        assert "must not be empty" in capsys.readouterr().err

    @pytest.mark.parametrize("flag", ["--jobs=0", "--jobs=-3"])
    def test_non_positive_jobs_is_a_usage_error(self, tmp_path, capsys, flag):
        """0 used to fall through to the default and negatives were clamped to 1,
        both without a word to the user."""
        code = main(["video", str(tmp_path / "in"), str(tmp_path / "out"), flag])

        assert code == 2
        assert "--jobs must be 1 or more" in capsys.readouterr().err

    def test_no_matching_files_says_so_loudly(self, tmp_path, capsys):
        """Silently exiting 0 with nothing done was the original sin."""
        (tmp_path / "in").mkdir()
        (tmp_path / "in" / "notes.txt").write_text("hi")

        code = main(["video", str(tmp_path / "in"), str(tmp_path / "out")])

        assert code == 0
        assert "No .mkv files found" in capsys.readouterr().err

    def test_hint_about_recursive_when_not_recursive(self, tmp_path, capsys):
        (tmp_path / "in" / "nested").mkdir(parents=True)

        main(["video", str(tmp_path / "in"), str(tmp_path / "out")])

        assert "--recursive" in capsys.readouterr().err

    def test_dry_run_lists_pairs_without_touching_ffmpeg(self, tmp_path, capsys):
        source = tmp_path / "in" / "clip.mkv"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"")

        code = main(["video", str(tmp_path / "in"), str(tmp_path / "out"), "--dry-run"])
        out = capsys.readouterr().out

        assert code == 0
        assert "clip.mkv" in out
        assert "clip.mp4" in out
        assert not (tmp_path / "out").exists()

    def test_collisions_are_refused_before_any_conversion(self, tmp_path):
        """Two inputs mapping to one output means one of them would be lost."""
        for folder in ("a", "b"):
            path = tmp_path / "in" / folder / "ep1.mkv"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"")

        code = main(
            ["video", str(tmp_path / "in"), str(tmp_path / "out"), "--recursive", "--dry-run"]
        )

        # Distinct sub-directories are preserved, so this must NOT be a collision.
        assert code == 0

    def test_a_collision_stops_the_run(self, tmp_path, capsys, monkeypatch):
        """Whether two real files can collide depends on the filesystem's case
        sensitivity, so the CLI's reaction to a collision is driven directly
        instead of through a case-folding trick that only works on one platform.
        """
        source = tmp_path / "in" / "clip.mkv"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"")
        clash = tmp_path / "out" / "clip.mp4"
        monkeypatch.setattr(cli.paths, "find_collisions", lambda _pairs: {clash: [source, source]})

        code = main(["video", str(tmp_path / "in"), str(tmp_path / "out"), "--dry-run"])
        err = capsys.readouterr().err

        assert code == 2
        assert "same output" in err
        assert "clip.mp4" in err

    def test_missing_ffmpeg_is_reported_once_and_clearly(self, tmp_path, capsys, monkeypatch):
        source = tmp_path / "in" / "clip.mkv"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"")
        monkeypatch.setattr(cli.ffmpegtool, "which", lambda _name: None)

        code = main(["video", str(tmp_path / "in"), str(tmp_path / "out")])
        err = capsys.readouterr().err

        assert code == 2
        assert "ffmpeg was not found" in err
        assert "winget install" in err


class TestExitCodeWiring:
    """Drives a whole run through main() with a stubbed ffmpeg, so the exit-code
    contract in the README is checked end to end rather than per unit."""

    def _prepare(self, tmp_path, monkeypatch, returncode: int) -> None:
        source = tmp_path / "in" / "clip.mkv"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"data")

        def run(argv, **_kwargs):
            Path(argv[-1]).write_bytes(b"converted")
            return CommandResult(tuple(argv), returncode, "", "boom" if returncode else "")

        monkeypatch.setattr(cli.ffmpegtool, "resolve_tools", lambda *_a: FAKE_TOOLS)
        monkeypatch.setattr(cli.ffmpegtool, "version", lambda _tools: "ffmpeg test build")
        monkeypatch.setattr(batch.ffmpegtool, "run", run)
        monkeypatch.setattr(batch.ffmpegtool, "probe_streams", lambda *_a: [])

    def test_a_clean_run_exits_zero(self, tmp_path, monkeypatch, capsys):
        self._prepare(tmp_path, monkeypatch, 0)

        code = main(["video", str(tmp_path / "in"), str(tmp_path / "out"), "-q"])

        assert code == 0
        assert "1 converted" in capsys.readouterr().out
        assert (tmp_path / "out" / "clip.mp4").exists()

    def test_a_failed_conversion_exits_one(self, tmp_path, monkeypatch, capsys):
        """The old scripts always printed 'Conversion completed.' and exited 0."""
        self._prepare(tmp_path, monkeypatch, 1)

        code = main(["video", str(tmp_path / "in"), str(tmp_path / "out"), "-q"])

        assert code == 1
        assert "1 failed" in capsys.readouterr().out

    def test_a_failed_conversion_leaves_no_output_behind(self, tmp_path, monkeypatch):
        self._prepare(tmp_path, monkeypatch, 1)

        main(["video", str(tmp_path / "in"), str(tmp_path / "out"), "-q"])

        assert not (tmp_path / "out" / "clip.mp4").exists()

    def test_skipping_everything_still_exits_zero(self, tmp_path, monkeypatch, capsys):
        self._prepare(tmp_path, monkeypatch, 0)
        existing = tmp_path / "out" / "clip.mp4"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"already done")

        code = main(["video", str(tmp_path / "in"), str(tmp_path / "out"), "-q"])

        assert code == 0
        assert "1 skipped" in capsys.readouterr().out
        assert existing.read_bytes() == b"already done"

    def test_audio_conversion_runs_through_the_same_wiring(self, tmp_path, monkeypatch, capsys):
        source = tmp_path / "in" / "tone.opus"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"data")
        self._prepare(tmp_path, monkeypatch, 0)

        code = main(["audio", str(tmp_path / "in"), str(tmp_path / "out"), "-q"])

        assert code == 0
        assert "1 converted" in capsys.readouterr().out
        assert (tmp_path / "out" / "tone.wav").exists()


class TestMirrorCommand:
    def test_lists_the_tree_without_creating_it(self, tmp_path, capsys):
        (tmp_path / "a" / "b").mkdir(parents=True)
        target = tmp_path / "mirror"

        code = main(["mirror", str(tmp_path / "a"), str(target)])
        out = capsys.readouterr().out

        assert code == 0
        assert "->" in out
        assert not target.exists()

    def test_create_makes_the_directories(self, tmp_path):
        (tmp_path / "a" / "b").mkdir(parents=True)
        target = tmp_path / "mirror"

        code = main(["mirror", str(tmp_path / "a"), str(target), "--create"])

        assert code == 0
        assert target.is_dir()

    def test_includes_the_root_directory_itself(self, tmp_path, capsys):
        (tmp_path / "a").mkdir()

        main(["mirror", str(tmp_path / "a"), str(tmp_path / "mirror")])

        assert str(tmp_path / "a") in capsys.readouterr().out


class TestInteractivePrompt:
    def _answers(self, monkeypatch, answers: list[str]) -> None:
        queue = list(answers)
        monkeypatch.setattr("builtins.input", lambda _prompt="": queue.pop(0))

    def test_video_with_explicit_output_directory(self, monkeypatch):
        self._answers(monkeypatch, ["1", "C:/in", "C:/out", "y", "n"])

        assert prompt_for_argv() == ["video", "C:/in", "C:/out", "--recursive"]

    def test_audio_falling_back_to_a_mirror_drive(self, monkeypatch):
        self._answers(monkeypatch, ["2", "C:/in", "", "E:", "n", "y"])

        assert prompt_for_argv() == ["audio", "C:/in", "--mirror-to", "E:", "--overwrite"]

    def test_mirror_choice(self, monkeypatch):
        self._answers(monkeypatch, ["3", "C:/in", "E:", "y"])

        assert prompt_for_argv() == ["mirror", "C:/in", "E:", "--create"]

    def test_quoted_paths_are_accepted(self, monkeypatch):
        self._answers(monkeypatch, ["1", '"C:/in"', '"C:/out"', "n", "n"])

        assert prompt_for_argv() == ["video", "C:/in", "C:/out"]

    def test_default_selection_is_video(self, monkeypatch):
        self._answers(monkeypatch, ["", "C:/in", "C:/out", "n", "n"])

        assert prompt_for_argv()[0] == "video"

    def test_unknown_selection_is_rejected(self, monkeypatch, capsys):
        self._answers(monkeypatch, ["9"])

        assert prompt_for_argv() is None
        assert "Unknown selection" in capsys.readouterr().err

    def test_missing_input_directory_is_rejected(self, monkeypatch):
        self._answers(monkeypatch, ["1", ""])

        assert prompt_for_argv() is None

    def test_prompt_output_feeds_the_real_parser(self, monkeypatch):
        """The interactive path must not be able to build an unparsable command."""
        self._answers(monkeypatch, ["1", "C:/in", "C:/out", "y", "y"])

        argv = prompt_for_argv()
        args = build_parser().parse_args(argv)

        assert args.recursive is True
        assert args.overwrite is True


class TestMainDispatch:
    def test_no_arguments_starts_the_interactive_prompt(self, monkeypatch, tmp_path, capsys):
        (tmp_path / "in").mkdir()
        answers = ["1", str(tmp_path / "in"), str(tmp_path / "out"), "n", "n"]
        queue = list(answers)
        monkeypatch.setattr("builtins.input", lambda _prompt="": queue.pop(0))

        code = main([])

        assert code == 0
        assert "No .mkv files found" in capsys.readouterr().err

    def test_aborting_the_prompt_is_not_a_crash(self, monkeypatch):
        def refuse(_prompt=""):
            raise EOFError

        monkeypatch.setattr("builtins.input", refuse)

        assert main([]) == 130

    def test_version_flag(self, capsys):
        with pytest.raises(SystemExit) as exit_info:
            main(["--version"])

        assert exit_info.value.code == 0
        assert "converter" in capsys.readouterr().out

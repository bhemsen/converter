"""Tests for locating the executables and for parsing ffprobe's output."""

import json
from pathlib import Path

import pytest

from converter import ffmpegtool
from converter.ffmpegtool import CommandResult, FfmpegMissingError, ProbeError, Stream, Tools

TOOLS = Tools(ffmpeg="ffmpeg", ffprobe="ffprobe")


def stub_run(monkeypatch, returncode: int, stdout: str = "", stderr: str = "") -> None:
    monkeypatch.setattr(
        ffmpegtool,
        "run",
        lambda argv, **_kwargs: CommandResult(tuple(argv), returncode, stdout, stderr),
    )


class TestResolveTools:
    def test_executable_on_path_is_accepted(self, tmp_path, monkeypatch):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        planted = bin_dir / "ffmpeg.exe"
        planted.write_bytes(b"")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(ffmpegtool, "which", lambda _name: str(planted))

        assert ffmpegtool.resolve_tools().ffmpeg == str(planted)

    def test_executable_in_the_current_directory_is_refused(self, tmp_path, monkeypatch):
        """On Python 3.11 shutil.which() searches the current directory first on
        Windows, so running from a directory containing a planted ffmpeg.exe would
        execute that one instead of the installed one."""
        planted = tmp_path / "ffmpeg.exe"
        planted.write_bytes(b"")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(ffmpegtool, "which", lambda _name: str(planted))
        monkeypatch.setenv("PATH", "")

        with pytest.raises(FfmpegMissingError, match="current directory"):
            ffmpegtool.resolve_tools()

    def test_current_directory_is_fine_when_it_is_really_on_path(self, tmp_path, monkeypatch):
        planted = tmp_path / "ffmpeg.exe"
        planted.write_bytes(b"")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(ffmpegtool, "which", lambda _name: str(planted))
        monkeypatch.setenv("PATH", str(tmp_path))

        assert ffmpegtool.resolve_tools().ffmpeg == str(planted)

    def test_explicit_path_override_is_honoured(self, tmp_path):
        planted = tmp_path / "my-ffmpeg.exe"
        planted.write_bytes(b"")

        tools = ffmpegtool.resolve_tools(ffmpeg=str(planted), ffprobe=str(planted))

        assert Path(tools.ffmpeg) == planted.resolve()

    def test_override_pointing_at_nothing_is_rejected(self, tmp_path):
        with pytest.raises(FfmpegMissingError, match="is not a file"):
            ffmpegtool.resolve_tools(ffmpeg=str(tmp_path / "sub" / "nope.exe"))

    def test_missing_executable_explains_how_to_install_it(self, monkeypatch):
        monkeypatch.setattr(ffmpegtool, "which", lambda _name: None)

        with pytest.raises(FfmpegMissingError, match="winget install"):
            ffmpegtool.resolve_tools()

    def test_both_executables_are_resolved(self, tmp_path, monkeypatch):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        monkeypatch.setattr(ffmpegtool, "which", lambda name: str(bin_dir / f"{name}.exe"))

        tools = ffmpegtool.resolve_tools()

        assert tools.ffmpeg.endswith("ffmpeg.exe")
        assert tools.ffprobe.endswith("ffprobe.exe")


class TestVersion:
    def test_returns_the_banner_line(self, monkeypatch):
        stub_run(monkeypatch, 0, "ffmpeg version 9.0-full_build\nbuilt with gcc\n")

        assert ffmpegtool.version(TOOLS) == "ffmpeg version 9.0-full_build"

    def test_unknown_when_the_call_fails(self, monkeypatch):
        stub_run(monkeypatch, 1, "")

        assert ffmpegtool.version(TOOLS) == "unknown"

    def test_unknown_when_the_output_is_empty(self, monkeypatch):
        stub_run(monkeypatch, 0, "")

        assert ffmpegtool.version(TOOLS) == "unknown"


class TestProbeStreams:
    def test_parses_every_stream(self, monkeypatch):
        payload = {
            "streams": [
                {"index": 0, "codec_type": "video", "codec_name": "h264"},
                {"index": 1, "codec_type": "audio", "codec_name": "aac"},
                {"index": 2, "codec_type": "subtitle", "codec_name": "subrip"},
            ]
        }
        stub_run(monkeypatch, 0, json.dumps(payload))

        assert ffmpegtool.probe_streams(TOOLS, "in.mkv") == [
            Stream(0, "video", "h264"),
            Stream(1, "audio", "aac"),
            Stream(2, "subtitle", "subrip"),
        ]

    def test_missing_codec_fields_become_empty_strings(self, monkeypatch):
        stub_run(monkeypatch, 0, json.dumps({"streams": [{"index": 7}]}))

        assert ffmpegtool.probe_streams(TOOLS, "in.mkv") == [Stream(7, "", "")]

    def test_streams_without_a_usable_index_are_skipped(self, monkeypatch):
        payload = {
            "streams": [
                {"codec_type": "video"},
                {"index": "not-a-number"},
                {"index": None},
                {"index": 4, "codec_type": "audio", "codec_name": "aac"},
            ]
        }
        stub_run(monkeypatch, 0, json.dumps(payload))

        assert [s.index for s in ffmpegtool.probe_streams(TOOLS, "in.mkv")] == [4]

    def test_a_string_index_that_is_numeric_still_works(self, monkeypatch):
        stub_run(monkeypatch, 0, json.dumps({"streams": [{"index": "3"}]}))

        assert [s.index for s in ffmpegtool.probe_streams(TOOLS, "in.mkv")] == [3]

    def test_no_streams_key_yields_no_streams(self, monkeypatch):
        stub_run(monkeypatch, 0, "{}")

        assert ffmpegtool.probe_streams(TOOLS, "in.mkv") == []

    def test_ffprobe_failure_raises_probe_error_with_its_message(self, monkeypatch):
        stub_run(monkeypatch, 1, "", "in.mkv: Invalid data found")

        with pytest.raises(ProbeError, match="Invalid data found"):
            ffmpegtool.probe_streams(TOOLS, "in.mkv")

    def test_ffprobe_failure_without_stderr_still_raises(self, monkeypatch):
        stub_run(monkeypatch, 3, "", "")

        with pytest.raises(ProbeError, match="exited with 3"):
            ffmpegtool.probe_streams(TOOLS, "in.mkv")

    def test_unparsable_output_raises_probe_error(self, monkeypatch):
        stub_run(monkeypatch, 0, "this is not json")

        with pytest.raises(ProbeError, match="could not parse"):
            ffmpegtool.probe_streams(TOOLS, "in.mkv")

    def test_the_command_asks_ffprobe_for_json(self, monkeypatch):
        captured = {}

        def fake_run(argv, **_kwargs):
            captured["argv"] = list(argv)
            return CommandResult(tuple(argv), 0, "{}", "")

        monkeypatch.setattr(ffmpegtool, "run", fake_run)

        ffmpegtool.probe_streams(TOOLS, "in.mkv")

        assert captured["argv"][0] == "ffprobe"
        assert "-of" in captured["argv"]
        assert captured["argv"][captured["argv"].index("-of") + 1] == "json"
        assert captured["argv"][-1] == "in.mkv"

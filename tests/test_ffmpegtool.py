"""Tests for locating the executables, running them, and parsing ffprobe's
output. Also owns the Popen/registry/termination machinery -- the subprocess
boundary at ``ffmpegtool.run`` -- and the Windows Job Object binding."""

import ctypes
import json
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from converter import ffmpegtool
from converter.ffmpegtool import (
    CommandResult,
    FfmpegMissingError,
    ProbeError,
    Stream,
    Tools,
    build_argv,
)

TOOLS = Tools(ffmpeg="ffmpeg", ffprobe="ffprobe")


class TestBuildMultiOutputArgv:
    """One input, several outputs (issue #176)."""

    def test_two_outputs_pin_their_options_muxer_and_path_in_order(self):
        argv = ffmpegtool.build_multi_output_argv(
            "ffmpeg",
            "in.mkv",
            [
                ffmpegtool.OutputSpec(("-map", "0:3", "-c:s", "webvtt"), "webvtt", "a.vtt.partial"),
                ffmpegtool.OutputSpec(("-map", "0:5", "-c:s", "webvtt"), "webvtt", "b.vtt.partial"),
            ],
        )

        assert argv == [
            "ffmpeg",
            *ffmpegtool.BASE_FLAGS,
            "-y",
            "-i",
            "in.mkv",
            "-map",
            "0:3",
            "-c:s",
            "webvtt",
            "-f",
            "webvtt",
            "a.vtt.partial",
            "-map",
            "0:5",
            "-c:s",
            "webvtt",
            "-f",
            "webvtt",
            "b.vtt.partial",
        ]

    def test_dash_leading_paths_are_anchored_for_input_and_every_output(self):
        argv = ffmpegtool.build_multi_output_argv(
            "ffmpeg",
            "-in.mkv",
            [
                ffmpegtool.OutputSpec(("-map", "0:1"), "webvtt", "-a.vtt.partial"),
                ffmpegtool.OutputSpec(("-map", "0:2"), "webvtt", Path("-b.vtt.partial")),
            ],
        )

        assert argv[argv.index("-i") + 1] == ffmpegtool.cli_path("-in.mkv")
        assert ffmpegtool.cli_path("-a.vtt.partial") in argv
        assert argv[-1] == ffmpegtool.cli_path("-b.vtt.partial")
        assert not any(arg.startswith("-") and arg.endswith((".mkv", ".partial")) for arg in argv)

    def test_build_argv_is_unchanged_alongside(self):
        assert build_argv("ffmpeg", "in.mkv", ("-c", "copy"), "out.mp4") == [
            "ffmpeg",
            *ffmpegtool.BASE_FLAGS,
            "-y",
            "-i",
            "in.mkv",
            "-c",
            "copy",
            "out.mp4",
        ]


class TestBuildArgvOutputFormat:
    """``output_format`` (issue #144): the ``-f <muxer>`` a ``.partial`` write
    needs, since it defeats ffmpeg's own suffix-based muxer choice."""

    def test_nothing_is_emitted_when_omitted(self):
        argv = build_argv("ffmpeg", "in.mkv", ("-c", "copy"), "out.mp4")

        assert "-f" not in argv

    def test_nothing_is_emitted_when_none(self):
        argv = build_argv("ffmpeg", "in.mkv", ("-c", "copy"), "out.mp4", output_format=None)

        assert "-f" not in argv

    def test_f_and_the_muxer_sit_directly_before_the_output_path(self):
        argv = build_argv(
            "ffmpeg", "in.mkv", ("-c", "copy"), "out.mp4.partial", output_format="mp4"
        )

        assert argv[-3:] == ["-f", "mp4", "out.mp4.partial"]

    def test_the_muxer_follows_the_recipe_options_not_replaces_them(self):
        argv = build_argv(
            "ffmpeg", "in.mkv", ("-c", "copy", "-map", "0"), "out.mkv.partial", "matroska"
        )

        assert argv == [
            "ffmpeg",
            *ffmpegtool.BASE_FLAGS,
            "-y",
            "-i",
            "in.mkv",
            "-c",
            "copy",
            "-map",
            "0",
            "-f",
            "matroska",
            "out.mkv.partial",
        ]

    def test_existing_argv_pins_are_unaffected(self):
        """The exact call every existing recipe test already makes -- no
        `output_format` argument at all -- must keep building the same argv."""
        argv = build_argv("ffmpeg", "in.mkv", ("-c", "copy"), "out.mp4")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.mkv",
            "-c",
            "copy",
            "out.mp4",
        ]


class FakePopen:
    """Stand-in for ``subprocess.Popen`` that never starts a real process."""

    def __init__(self, argv, **kwargs):
        self.argv = argv
        self.kwargs = kwargs
        self.returncode = 0
        self.killed = False
        self._communicate_result = ("out", "err")

    def communicate(self, timeout=None):
        return self._communicate_result

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return self.returncode


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

    def test_the_container_tag_is_asked_for_and_parsed(self, monkeypatch):
        """A `tmcd` timecode track and an Apple `mebx` metadata track both report
        no `codec_name` at all, so the tag is the only thing that tells them
        apart -- and `jobs.confirm_drops` needs to (issue #66)."""
        payload = {
            "streams": [
                {"index": 0, "codec_type": "data", "codec_tag_string": "tmcd"},
                {"index": 1, "codec_type": "data", "codec_tag_string": "mebx"},
            ]
        }
        seen: list[list[str]] = []

        def record(argv, **_kwargs):
            seen.append(list(argv))
            return CommandResult(tuple(argv), 0, json.dumps(payload), "")

        monkeypatch.setattr(ffmpegtool, "run", record)

        streams = ffmpegtool.probe_streams(TOOLS, "in.mov")

        assert (
            "stream=index,codec_type,codec_name,codec_tag_string,pix_fmt:"
            "stream_disposition=attached_pic:stream_tags=language" in seen[0]
        )
        assert [stream.codec_tag for stream in streams] == ["tmcd", "mebx"]

    def test_the_show_entries_argument_is_pinned_verbatim(self, monkeypatch):
        """Issue #104: `pix_fmt` rides the existing query for free -- it must
        show up in the same single `-show_entries` argument, not cost a
        second ffprobe process, and never pull in `-count_packets` (the spec's
        own measurements ruled that field's cost out entirely)."""
        calls: list[list[str]] = []

        def record(argv, **_kwargs):
            calls.append(list(argv))
            return CommandResult(tuple(argv), 0, "{}", "")

        monkeypatch.setattr(ffmpegtool, "run", record)

        ffmpegtool.probe_streams(TOOLS, "in.mkv")

        assert (
            "stream=index,codec_type,codec_name,codec_tag_string,pix_fmt:"
            "stream_disposition=attached_pic:stream_tags=language" in calls[0]
        )
        assert "-count_packets" not in calls[0]
        assert len(calls) == 1

    def test_pix_fmt_is_parsed_for_a_video_stream(self, monkeypatch):
        payload = {"streams": [{"index": 0, "codec_type": "video", "pix_fmt": "yuvj420p"}]}
        stub_run(monkeypatch, 0, json.dumps(payload))

        streams = ffmpegtool.probe_streams(TOOLS, "in.jpg")

        assert streams[0].pix_fmt == "yuvj420p"

    def test_pix_fmt_defaults_to_empty_when_the_key_is_absent(self, monkeypatch):
        """An audio stream carries no `pix_fmt` key at all in ffprobe's JSON
        output -- `"N/A"` is only the CSV writer's rendering of absence, never
        what the JSON parser sees (docs/specs/archive/spec-within-stream-loss-notes.md).
        Asserting the empty string, not just "falsy", is what would catch a
        regression to the literal string `"N/A"`."""
        payload = {"streams": [{"index": 1, "codec_type": "audio", "codec_name": "aac"}]}
        stub_run(monkeypatch, 0, json.dumps(payload))

        streams = ffmpegtool.probe_streams(TOOLS, "in.mp3")

        assert streams[0].pix_fmt == ""

    def test_language_is_parsed_from_the_tags_object(self, monkeypatch):
        payload = {
            "streams": [
                {"index": 0, "codec_type": "subtitle", "tags": {"language": "eng"}},
                {"index": 1, "codec_type": "subtitle", "tags": {}},
                {"index": 2, "codec_type": "subtitle"},
            ]
        }
        stub_run(monkeypatch, 0, json.dumps(payload))

        streams = ffmpegtool.probe_streams(TOOLS, "in.mkv")

        assert [stream.language for stream in streams] == ["eng", "", ""]

    def test_exactly_one_ffprobe_call_is_made_per_file(self, monkeypatch):
        calls: list[list[str]] = []

        def record(argv, **_kwargs):
            calls.append(list(argv))
            return CommandResult(tuple(argv), 0, "{}", "")

        monkeypatch.setattr(ffmpegtool, "run", record)

        ffmpegtool.probe_streams(TOOLS, "in.mkv")

        assert len(calls) == 1

    def test_attached_pic_is_true_for_a_picture(self, monkeypatch):
        payload = {
            "streams": [
                {
                    "index": 1,
                    "codec_type": "video",
                    "codec_name": "png",
                    "disposition": {"attached_pic": 1},
                }
            ]
        }
        stub_run(monkeypatch, 0, json.dumps(payload))

        streams = ffmpegtool.probe_streams(TOOLS, "in.mp3")

        assert streams == [Stream(1, "video", "png", attached_pic=True)]

    def test_attached_pic_is_false_for_a_plain_video(self, monkeypatch):
        payload = {
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "h264",
                    "disposition": {"attached_pic": 0},
                }
            ]
        }
        stub_run(monkeypatch, 0, json.dumps(payload))

        streams = ffmpegtool.probe_streams(TOOLS, "in.mkv")

        assert streams == [Stream(0, "video", "h264", attached_pic=False)]

    def test_attached_pic_defaults_to_false_when_disposition_is_absent(self, monkeypatch):
        stub_run(monkeypatch, 0, json.dumps({"streams": [{"index": 0, "codec_type": "audio"}]}))

        streams = ffmpegtool.probe_streams(TOOLS, "in.mkv")

        assert streams[0].attached_pic is False

    def test_attached_pic_defaults_to_false_when_the_key_is_absent(self, monkeypatch):
        """The disposition object can be present without the one flag we read --
        ffprobe reports it alongside every other disposition flag it knows."""
        payload = {"streams": [{"index": 0, "codec_type": "video", "disposition": {"default": 1}}]}
        stub_run(monkeypatch, 0, json.dumps(payload))

        streams = ffmpegtool.probe_streams(TOOLS, "in.mkv")

        assert streams[0].attached_pic is False

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


class TestRunIsShellFree:
    """Moved from tests/test_argv.py and rewritten against Popen (issue #145):
    `run` no longer calls `subprocess.run` at all."""

    def test_argv_list_no_shell_and_stdin_closed(self, monkeypatch):
        captured = {}

        def fake_popen(argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            return FakePopen(argv, **kwargs)

        monkeypatch.setattr(subprocess, "Popen", fake_popen)

        result = ffmpegtool.run(["ffmpeg", "-version"])

        assert isinstance(captured["argv"], list)
        assert "shell" not in captured["kwargs"]
        assert captured["kwargs"]["stdin"] is subprocess.DEVNULL
        assert captured["kwargs"]["text"] is True
        assert captured["kwargs"]["errors"] == "replace"
        assert result.stdout == "out"
        assert result.stderr == "err"
        assert result.returncode == 0

    def test_timeout_kills_the_process_reaps_it_and_reraises(self, monkeypatch):
        spawned = []

        class TimingOutPopen(FakePopen):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                spawned.append(self)

            def communicate(self, timeout=None):
                if not self.killed:
                    raise subprocess.TimeoutExpired(cmd=self.argv, timeout=timeout)
                return ("", "")

        monkeypatch.setattr(subprocess, "Popen", TimingOutPopen)

        with pytest.raises(subprocess.TimeoutExpired):
            ffmpegtool.run(["ffmpeg", "-version"], timeout=1)

        assert spawned[0].killed
        assert len(ffmpegtool._live_processes) == 0

    def test_any_exception_from_communicate_kills_reaps_and_reraises(self, monkeypatch):
        """Not just `TimeoutExpired`: a `KeyboardInterrupt` or the future
        SIGTERM handler's `Terminated` can land on the calling thread inside
        `communicate()` just as easily, and must not leave the child running
        unregistered and unkilled (issue #145 review)."""
        spawned = []

        class InterruptedPopen(FakePopen):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                spawned.append(self)

            def communicate(self, timeout=None):
                if not self.killed:
                    raise KeyboardInterrupt
                return ("", "")

        monkeypatch.setattr(subprocess, "Popen", InterruptedPopen)

        with pytest.raises(KeyboardInterrupt):
            ffmpegtool.run(["ffmpeg", "-version"])

        assert spawned[0].killed
        assert len(ffmpegtool._live_processes) == 0


class TestRegistry:
    """The live-process registry `terminate_all` kills from."""

    def test_a_process_is_registered_only_while_it_runs(self, monkeypatch):
        seen_during_communicate = {}

        class ObservingPopen(FakePopen):
            def communicate(self, timeout=None):
                seen_during_communicate["count"] = len(ffmpegtool._live_processes)
                return super().communicate(timeout=timeout)

        monkeypatch.setattr(subprocess, "Popen", ObservingPopen)

        assert len(ffmpegtool._live_processes) == 0

        ffmpegtool.run(["ffmpeg"])

        assert seen_during_communicate["count"] == 1
        assert len(ffmpegtool._live_processes) == 0

    def test_a_failing_process_is_still_deregistered(self, monkeypatch):
        class RaisingPopen(FakePopen):
            def communicate(self, timeout=None):
                raise subprocess.TimeoutExpired(cmd=self.argv, timeout=timeout)

        monkeypatch.setattr(subprocess, "Popen", RaisingPopen)

        with pytest.raises(subprocess.TimeoutExpired):
            ffmpegtool.run(["ffmpeg"], timeout=1)

        assert len(ffmpegtool._live_processes) == 0


class TestTerminateAll:
    """`terminate_all` closes the registry and kills/reaps every process."""

    def test_sets_the_shutdown_flag(self):
        assert ffmpegtool.terminated() is False

        ffmpegtool.terminate_all()

        assert ffmpegtool.terminated() is True

    def test_kills_and_reaps_every_registered_process(self):
        first, second = FakePopen([], stdin=None), FakePopen([], stdin=None)
        ffmpegtool._live_processes[id(first)] = first
        ffmpegtool._live_processes[id(second)] = second

        ffmpegtool.terminate_all(timeout=5)

        assert first.killed and second.killed

    def test_a_process_that_will_not_die_does_not_block_forever(self):
        class StuckPopen(FakePopen):
            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired(cmd=[], timeout=timeout)

        stuck = StuckPopen([], stdin=None)
        ffmpegtool._live_processes[id(stuck)] = stuck

        ffmpegtool.terminate_all(timeout=0.01)  # must return, not raise

        assert stuck.killed

    def test_a_process_registered_while_terminate_all_waits_for_the_lock_is_still_killed(
        self, monkeypatch
    ):
        """Exercises the real `run()` path, not just `_lock` in isolation:
        `run()` holds `ffmpegtool._lock` for its whole spawn-and-register
        step, `Popen` call included, so `terminate_all` -- which needs the
        same lock to take its registry snapshot -- cannot take that snapshot
        until `run()` has either registered the process or bailed out on the
        shutdown flag. There is no window where a process is running but
        invisible to a `terminate_all` that started while the spawn was
        still in flight (issue #145 review)."""
        entered_popen = threading.Event()
        release_popen = threading.Event()
        release_communicate = threading.Event()
        spawned = []

        class SlowPopen(FakePopen):
            def __init__(self, *args, **kwargs):
                entered_popen.set()
                assert release_popen.wait(timeout=2)
                super().__init__(*args, **kwargs)
                spawned.append(self)

            def communicate(self, timeout=None):
                # Kept "running" (still registered) until the test says
                # otherwise, so terminate_all's snapshot is forced to catch
                # it rather than racing run()'s own, unrelated completion.
                assert release_communicate.wait(timeout=2)
                return super().communicate(timeout=timeout)

        monkeypatch.setattr(subprocess, "Popen", SlowPopen)

        runner = threading.Thread(target=ffmpegtool.run, args=(["ffmpeg"],))
        runner.start()
        assert entered_popen.wait(timeout=2)  # run() is inside Popen(), holding _lock

        terminator = threading.Thread(target=ffmpegtool.terminate_all, kwargs={"timeout": 1})
        terminator.start()
        release_popen.set()  # let the spawn, and the registration, complete
        terminator.join(timeout=2)  # terminate_all has taken its snapshot by now

        assert spawned and spawned[0].killed

        release_communicate.set()
        runner.join(timeout=2)


class TestTerminated:
    """The `Terminated` exception and `run`'s post-shutdown behaviour."""

    def test_is_a_base_exception_not_a_plain_exception(self):
        assert issubclass(ffmpegtool.Terminated, BaseException)
        assert not issubclass(ffmpegtool.Terminated, Exception)

    def test_run_raises_without_spawning_once_terminated(self, monkeypatch):
        def fail_if_called(argv, **kwargs):
            raise AssertionError("run() must not spawn once terminated")

        monkeypatch.setattr(subprocess, "Popen", fail_if_called)
        ffmpegtool.terminate_all()

        with pytest.raises(ffmpegtool.Terminated):
            ffmpegtool.run(["ffmpeg"])


def _fake_kernel32(*, create_ok=True, set_ok=True, assign_ok=True):
    """A SimpleNamespace, not a class: its callables are plain functions, so
    production code's `kernel32.X.restype = ...` assignments succeed the same
    way they would on a real ctypes function pointer -- a bound method would
    reject that assignment."""
    state = {"set_info_args": None, "limit_flags": None}

    def create_job_object_w(*_args):
        return 4242 if create_ok else 0

    def set_information_job_object(job, info_class, info_ptr, info_size):
        info = ctypes.cast(info_ptr, ctypes.POINTER(ffmpegtool._ExtendedLimitInformation)).contents
        state["set_info_args"] = (job, info_class, info_size)
        state["limit_flags"] = info.basic_limit_information.limit_flags
        return 1 if set_ok else 0

    def get_current_process():
        return 999

    def assign_process_to_job_object(job, process):
        return 1 if assign_ok else 0

    kernel32 = SimpleNamespace(
        CreateJobObjectW=create_job_object_w,
        SetInformationJobObject=set_information_job_object,
        GetCurrentProcess=get_current_process,
        AssignProcessToJobObject=assign_process_to_job_object,
    )
    kernel32.state = state
    return kernel32


class TestBindToKillOnCloseJob:
    """The Windows Job Object binding -- Win32 calls always stubbed, on
    every platform, via the `_is_windows`/`_kernel32` seams."""

    def test_noop_on_non_windows(self, monkeypatch):
        monkeypatch.setattr(ffmpegtool, "_is_windows", lambda: False)
        touched = []
        monkeypatch.setattr(ffmpegtool, "_kernel32", lambda: touched.append(True))

        ffmpegtool.bind_to_kill_on_close_job()

        assert touched == []

    def test_success_sets_the_kill_on_close_flag_and_keeps_the_handle(self, monkeypatch):
        monkeypatch.setattr(ffmpegtool, "_is_windows", lambda: True)
        monkeypatch.setattr(ffmpegtool, "_job_handle", None)
        kernel32 = _fake_kernel32()
        monkeypatch.setattr(ffmpegtool, "_kernel32", lambda: kernel32)

        ffmpegtool.bind_to_kill_on_close_job()

        assert ffmpegtool._job_handle == 4242
        assert kernel32.state["limit_flags"] == ffmpegtool._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

    def test_a_failed_creation_only_warns_and_leaves_no_handle(self, monkeypatch, capsys):
        monkeypatch.setattr(ffmpegtool, "_is_windows", lambda: True)
        monkeypatch.setattr(ffmpegtool, "_job_handle", None)
        kernel32 = _fake_kernel32(create_ok=False)
        monkeypatch.setattr(ffmpegtool, "_kernel32", lambda: kernel32)

        ffmpegtool.bind_to_kill_on_close_job()  # must not raise

        assert ffmpegtool._job_handle is None
        assert "warning" in capsys.readouterr().err.lower()

    def test_a_failed_assignment_only_warns_and_leaves_no_handle(self, monkeypatch, capsys):
        monkeypatch.setattr(ffmpegtool, "_is_windows", lambda: True)
        monkeypatch.setattr(ffmpegtool, "_job_handle", None)
        kernel32 = _fake_kernel32(assign_ok=False)
        monkeypatch.setattr(ffmpegtool, "_kernel32", lambda: kernel32)

        ffmpegtool.bind_to_kill_on_close_job()  # must not raise

        assert ffmpegtool._job_handle is None
        assert "warning" in capsys.readouterr().err.lower()

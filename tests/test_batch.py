"""Tests for batch behaviour: the failures the old scripts swallowed."""

from pathlib import Path

import pytest

from converter import batch
from converter.batch import Outcome, Result, Task, convert_one, run_batch, summarise
from converter.ffmpegtool import CommandResult, ProbeError, Stream, Tools
from converter.jobs import MKV_TO_MP4, OPUS_TO_WAV

TOOLS = Tools(ffmpeg="ffmpeg", ffprobe="ffprobe")


@pytest.fixture
def fake_ffmpeg(monkeypatch):
    """Replace ffmpeg with a scripted stand-in and record every invocation."""

    class Fake:
        def __init__(self):
            self.calls: list[list[str]] = []
            self.exit_codes: list[int] = [0]
            self.streams: list[Stream] = []
            self.probe_error: str | None = None
            self.creates_output = True

        def run(self, argv, **_kwargs):
            argv = list(argv)
            self.calls.append(argv)
            code = self.exit_codes[min(len(self.calls) - 1, len(self.exit_codes) - 1)]
            if self.creates_output:
                Path(argv[-1]).write_bytes(b"partial")
            return CommandResult(tuple(argv), code, "", "boom" if code else "")

        def probe_streams(self, _tools, _src):
            if self.probe_error is not None:
                raise ProbeError(self.probe_error)
            return self.streams

    fake = Fake()
    monkeypatch.setattr(batch.ffmpegtool, "run", fake.run)
    monkeypatch.setattr(batch.ffmpegtool, "probe_streams", fake.probe_streams)
    return fake


def make_task(tmp_path: Path, name: str = "clip") -> Task:
    src = tmp_path / f"{name}.mkv"
    src.write_bytes(b"data")
    return Task(src, tmp_path / "out" / f"{name}.mp4")


def spy_on_probe(monkeypatch, streams: list[Stream]) -> list[Path]:
    """Replace probe_streams on the module and record what it was asked about.

    Patching the module attribute matters: rebinding the attribute on the fake
    object would leave the already-installed reference untouched, and the spy
    would silently never be called.
    """
    seen: list[Path] = []

    def probe(_tools, src):
        seen.append(src)
        return list(streams)

    monkeypatch.setattr(batch.ffmpegtool, "probe_streams", probe)
    return seen


class TestConvertOne:
    def test_success_reports_the_attempt_that_worked(self, tmp_path, fake_ffmpeg):
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)

        result = convert_one(MKV_TO_MP4, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.CONVERTED
        assert result.attempt == "remux"
        assert len(fake_ffmpeg.calls) == 1

    def test_existing_output_is_skipped_by_default(self, tmp_path, fake_ffmpeg):
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        task.dst.write_bytes(b"already there")

        result = convert_one(MKV_TO_MP4, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.SKIPPED
        assert fake_ffmpeg.calls == []
        assert task.dst.read_bytes() == b"already there"

    def test_overwrite_replaces_an_existing_output(self, tmp_path, fake_ffmpeg):
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        task.dst.write_bytes(b"already there")

        result = convert_one(MKV_TO_MP4, task, TOOLS, overwrite=True)

        assert result.outcome is Outcome.CONVERTED
        assert len(fake_ffmpeg.calls) == 1

    def test_failed_remux_climbs_the_fallback_ladder(self, tmp_path, fake_ffmpeg):
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.exit_codes = [1, 0]
        fake_ffmpeg.streams = [Stream(0, "video", "h264"), Stream(1, "audio", "pcm_s16le")]

        result = convert_one(MKV_TO_MP4, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.CONVERTED
        assert result.attempt == "selective"
        assert len(fake_ffmpeg.calls) == 2
        assert any("pcm_s16le" in note for note in result.notes)

    def test_probe_does_not_run_when_the_first_attempt_succeeds(
        self, tmp_path, fake_ffmpeg, monkeypatch
    ):
        """An ffprobe round-trip per file would be pure waste on the happy path."""
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        probes = spy_on_probe(monkeypatch, [])

        convert_one(MKV_TO_MP4, task, TOOLS, overwrite=False)

        assert probes == []

    def test_probe_does_run_once_the_first_attempt_fails(self, tmp_path, fake_ffmpeg, monkeypatch):
        """Counterpart to the test above: proves the spy would notice a probe."""
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.exit_codes = [1, 0]
        probes = spy_on_probe(monkeypatch, [Stream(0, "video", "h264")])

        convert_one(MKV_TO_MP4, task, TOOLS, overwrite=False)

        assert probes == [task.src]

    def test_all_attempts_failing_is_reported_as_failure(self, tmp_path, fake_ffmpeg):
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.exit_codes = [1]
        fake_ffmpeg.streams = [Stream(0, "video", "h264")]

        result = convert_one(MKV_TO_MP4, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.FAILED
        assert "remux" in result.error
        assert "re-encode" in result.error

    def test_truncated_output_is_removed_after_failure(self, tmp_path, fake_ffmpeg):
        """Leaving a partial file behind would make the next run 'skip' it."""
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.exit_codes = [1]

        result = convert_one(MKV_TO_MP4, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.FAILED
        assert not task.dst.exists()

    def test_pre_existing_output_survives_a_failed_overwrite(self, tmp_path, fake_ffmpeg):
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        task.dst.write_bytes(b"good older file")
        fake_ffmpeg.exit_codes = [1]
        fake_ffmpeg.creates_output = False

        convert_one(MKV_TO_MP4, task, TOOLS, overwrite=True)

        assert task.dst.read_bytes() == b"good older file"

    def test_probe_failure_is_recorded_not_raised(self, tmp_path, fake_ffmpeg):
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.exit_codes = [1]
        fake_ffmpeg.probe_error = "unreadable"

        result = convert_one(MKV_TO_MP4, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.FAILED
        assert "unreadable" in result.error

    def test_unexpected_exception_does_not_escape(self, tmp_path, monkeypatch):
        task = make_task(tmp_path)

        def explode(*_args, **_kwargs):
            raise RuntimeError("kaboom")

        monkeypatch.setattr(batch.ffmpegtool, "run", explode)

        result = convert_one(MKV_TO_MP4, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.FAILED
        assert "kaboom" in result.error


class TestRunBatch:
    def test_creates_output_directories_once_in_the_parent(self, tmp_path, fake_ffmpeg):
        """Every worker used to run 'if not exists: makedirs()' itself, so they
        raced and the losers died with FileExistsError."""
        tasks = [make_task(tmp_path, f"clip{i}") for i in range(5)]

        results = run_batch(MKV_TO_MP4, tasks, TOOLS, jobs=4, progress=False)

        assert (tmp_path / "out").is_dir()
        assert all(r.outcome is Outcome.CONVERTED for r in results)

    def test_nested_output_directories_are_created(self, tmp_path, fake_ffmpeg):
        src = tmp_path / "a" / "b" / "clip.mkv"
        src.parent.mkdir(parents=True)
        src.write_bytes(b"data")
        task = Task(src, tmp_path / "out" / "a" / "b" / "clip.mp4")

        results = run_batch(MKV_TO_MP4, [task], TOOLS, progress=False)

        assert results[0].outcome is Outcome.CONVERTED
        assert task.dst.parent.is_dir()

    def test_returns_one_result_per_task(self, tmp_path, fake_ffmpeg):
        tasks = [make_task(tmp_path, f"clip{i}") for i in range(7)]

        results = run_batch(OPUS_TO_WAV, tasks, TOOLS, jobs=3, progress=False)

        assert len(results) == len(tasks)
        assert {r.task.src for r in results} == {t.src for t in tasks}

    def test_empty_task_list_is_harmless(self, tmp_path, fake_ffmpeg):
        assert run_batch(MKV_TO_MP4, [], TOOLS, progress=False) == []

    def test_interrupt_drops_work_that_has_not_started(self, tmp_path, monkeypatch):
        """Ctrl+C used to be noticed only after every queued file had converted:
        ThreadPoolExecutor's context manager shuts down with wait=True and no
        cancellation, so the whole batch drained before the interrupt surfaced."""
        tasks = [make_task(tmp_path, f"clip{i:02d}") for i in range(12)]
        calls: list[list[str]] = []

        def run(argv, **_kwargs):
            calls.append(list(argv))
            if len(calls) == 3:
                raise KeyboardInterrupt
            return CommandResult(tuple(argv), 0, "", "")

        monkeypatch.setattr(batch.ffmpegtool, "run", run)

        with pytest.raises(KeyboardInterrupt):
            run_batch(MKV_TO_MP4, tasks, TOOLS, jobs=1, progress=False)

        assert len(calls) < len(tasks)


class TestSummarise:
    def _result(self, outcome: Outcome) -> Result:
        return Result(Task(Path("in.mkv"), Path("out.mp4")), outcome)

    def test_counts_each_outcome(self):
        summary = summarise(
            [
                self._result(Outcome.CONVERTED),
                self._result(Outcome.CONVERTED),
                self._result(Outcome.SKIPPED),
                self._result(Outcome.FAILED),
            ]
        )

        assert (summary.converted, summary.skipped, summary.failed) == (2, 1, 1)
        assert summary.total == 4

    def test_any_failure_makes_the_exit_code_non_zero(self):
        """The old scripts always printed 'Conversion completed.' and exited 0."""
        assert summarise([self._result(Outcome.FAILED)]).exit_code == 1

    def test_a_clean_run_exits_zero(self):
        assert summarise([self._result(Outcome.CONVERTED)]).exit_code == 0

    def test_skipped_only_is_not_a_failure(self):
        assert summarise([self._result(Outcome.SKIPPED)]).exit_code == 0

    def test_describe_mentions_every_bucket(self):
        text = summarise([self._result(Outcome.CONVERTED)]).describe()

        assert "1 converted" in text
        assert "0 failed" in text


class TestDefaultJobs:
    def test_is_bounded(self):
        """One process per input file oversubscribed the machine badly."""
        assert 1 <= batch.default_jobs() <= 4

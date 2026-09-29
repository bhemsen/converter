"""Tests for the text and JSON renderers over ``batch.Result`` / ``batch.Summary``.

Per record type, these pin the exact key set and order (``docs/specs/archive/spec-json-output.md``,
*The record contract*), the null rules for ``attempt``/``error``, that ``notes``
is always an array, that paths are absolute via ``Path.absolute()`` and not
``Path.resolve()``, that a non-ASCII or lone-surrogate name still produces a
pure-ASCII line ``json.loads`` round-trips, and that the text renderer prints
the exact lines the now-removed ``batch._report`` used to (issue #139 moved
these expectations here unchanged, since ``batch`` no longer prints anything
itself).
"""

import io
import json
from pathlib import Path

from converter import report
from converter.batch import Outcome, Result, Summary, Task


def _task(tmp_path: Path, name: str = "in.mkv", out: str = "out.mp4") -> Task:
    return Task(tmp_path / name, tmp_path / out)


class TestRenderText:
    """Pins the exact lines the removed ``batch._report`` used to print
    (issue #139: its test expectations moved here unchanged)."""

    def _results(self, tmp_path: Path) -> list[Result]:
        task = _task(tmp_path)
        return [
            Result(task, Outcome.CONVERTED, "remux", ("note one", "note two")),
            Result(task, Outcome.FAILED, error="ffmpeg exited 1"),
            Result(task, Outcome.SKIPPED, notes=("output already exists",)),
            Result(task, Outcome.UNSUPPORTED, notes=("no audio or video stream",)),
            Result(task, Outcome.CONVERTED),  # no notes at all
        ]

    def test_matches_the_original_report_lines(self, tmp_path, capsys):
        name = _task(tmp_path).src.name
        expected_out = (
            f"note    {name}: note one\nnote    {name}: note two\n"
            f"note    {name}: output already exists\n"
            f"note    {name}: no audio or video stream\n"
        )
        expected_err = f"FAILED  {name}: ffmpeg exited 1\n"

        for result in self._results(tmp_path):
            report.render_text(result)
        actual = capsys.readouterr()

        assert actual.out == expected_out
        assert actual.err == expected_err

    def test_failed_goes_to_stderr_only(self, tmp_path, capsys):
        task = _task(tmp_path)
        report.render_text(Result(task, Outcome.FAILED, error="boom"))

        captured = capsys.readouterr()
        assert captured.out == ""
        assert f"FAILED  {task.src.name}: boom" in captured.err

    def test_notes_go_to_stdout(self, tmp_path, capsys):
        task = _task(tmp_path)
        report.render_text(Result(task, Outcome.CONVERTED, "remux", ("hello",)))

        captured = capsys.readouterr()
        assert captured.err == ""
        assert f"note    {task.src.name}: hello" in captured.out

    def test_no_notes_prints_nothing(self, tmp_path, capsys):
        task = _task(tmp_path)
        report.render_text(Result(task, Outcome.SKIPPED))

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""


class TestFileRecord:
    def test_key_set_and_order(self, tmp_path):
        task = _task(tmp_path)
        record = report.file_record(Result(task, Outcome.CONVERTED, "remux", ("a",)))

        assert list(record.keys()) == [
            "type",
            "schema",
            "source",
            "output",
            "outcome",
            "attempt",
            "notes",
            "error",
        ]

    def test_type_and_schema(self, tmp_path):
        record = report.file_record(Result(_task(tmp_path), Outcome.CONVERTED, "remux"))

        assert record["type"] == "file"
        assert record["schema"] == 1

    def test_outcome_value(self, tmp_path):
        record = report.file_record(Result(_task(tmp_path), Outcome.SKIPPED, notes=("x",)))

        assert record["outcome"] == "skipped"

    def test_attempt_null_unless_converted(self, tmp_path):
        task = _task(tmp_path)
        for outcome in (Outcome.SKIPPED, Outcome.FAILED, Outcome.UNSUPPORTED):
            record = report.file_record(Result(task, outcome, error="e", notes=("n",)))
            assert record["attempt"] is None

    def test_attempt_set_when_converted(self, tmp_path):
        record = report.file_record(Result(_task(tmp_path), Outcome.CONVERTED, "selective"))

        assert record["attempt"] == "selective"

    def test_error_null_unless_failed(self, tmp_path):
        task = _task(tmp_path)
        for outcome in (Outcome.CONVERTED, Outcome.SKIPPED, Outcome.UNSUPPORTED):
            record = report.file_record(Result(task, outcome, attempt="remux"))
            assert record["error"] is None

    def test_error_set_when_failed(self, tmp_path):
        record = report.file_record(Result(_task(tmp_path), Outcome.FAILED, error="ffmpeg died"))

        assert record["error"] == "ffmpeg died"

    def test_notes_defaults_to_empty_array(self, tmp_path):
        record = report.file_record(Result(_task(tmp_path), Outcome.CONVERTED, "remux"))

        assert record["notes"] == []

    def test_notes_preserve_order(self, tmp_path):
        task = _task(tmp_path)
        result = Result(task, Outcome.CONVERTED, "remux", ("first", "second", "third"))

        assert report.file_record(result)["notes"] == ["first", "second", "third"]

    def test_source_and_output_are_absolute(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task = Task(Path("in.mkv"), Path("out.mp4"))
        record = report.file_record(Result(task, Outcome.SKIPPED, notes=("x",)))

        assert record["source"] == str(tmp_path / "in.mkv")
        assert record["output"] == str(tmp_path / "out.mp4")
        assert Path(record["source"]).is_absolute()
        assert Path(record["output"]).is_absolute()

    def test_paths_use_absolute_not_resolve(self, tmp_path, monkeypatch):
        def boom(self, *args, **kwargs):
            raise AssertionError("Path.resolve() must not be called")

        monkeypatch.setattr(Path, "resolve", boom)
        task = _task(tmp_path)
        record = report.file_record(Result(task, Outcome.CONVERTED, "remux"))

        assert record["source"] == str(task.src.absolute())
        assert record["output"] == str(task.dst.absolute())


class TestPlannedRecord:
    def test_key_set_and_order(self, tmp_path):
        record = report.planned_record(_task(tmp_path))

        assert list(record.keys()) == ["type", "schema", "source", "output"]

    def test_type_and_schema(self, tmp_path):
        record = report.planned_record(_task(tmp_path))

        assert record["type"] == "planned"
        assert record["schema"] == 1

    def test_paths_are_absolute(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task = Task(Path("in.mkv"), Path("out.mp4"))
        record = report.planned_record(task)

        assert record["source"] == str(tmp_path / "in.mkv")
        assert record["output"] == str(tmp_path / "out.mp4")


class TestSummaryRecord:
    def test_key_set_and_order(self):
        summary = Summary(converted=1, skipped=2, failed=3, unsupported=4)
        record = report.summary_record(summary, planned=0, exit_code=1, dry_run=False)

        assert list(record.keys()) == [
            "type",
            "schema",
            "converted",
            "skipped",
            "failed",
            "unsupported",
            "total",
            "planned",
            "exit_code",
            "dry_run",
        ]

    def test_type_and_schema(self):
        record = report.summary_record(Summary(), planned=0, exit_code=0, dry_run=False)

        assert record["type"] == "summary"
        assert record["schema"] == 1

    def test_counts_come_from_summary(self):
        summary = Summary(converted=1, skipped=2, failed=3, unsupported=4)
        record = report.summary_record(summary, planned=0, exit_code=1, dry_run=False)

        assert record["converted"] == 1
        assert record["skipped"] == 2
        assert record["failed"] == 3
        assert record["unsupported"] == 4
        assert record["total"] == 10

    def test_planned_is_the_renderer_argument_not_a_summary_field(self):
        """`planned` must never be read off `Summary` -- it has no such field."""
        assert not hasattr(Summary(), "planned")

        record = report.summary_record(Summary(), planned=7, exit_code=0, dry_run=True)

        assert record["planned"] == 7

    def test_exit_code_and_dry_run_pass_through(self):
        record = report.summary_record(Summary(failed=1), planned=0, exit_code=1, dry_run=False)
        assert record["exit_code"] == 1
        assert record["dry_run"] is False

        record = report.summary_record(Summary(), planned=3, exit_code=0, dry_run=True)
        assert record["exit_code"] == 0
        assert record["dry_run"] is True

    def test_total_is_summary_total_when_not_a_dry_run(self):
        """The general rule: `total` is `batch.Summary`'s own aggregate."""
        summary = Summary(converted=1, skipped=2, failed=3, unsupported=4)
        record = report.summary_record(summary, planned=5, exit_code=1, dry_run=False)

        assert record["total"] == summary.total == 10

    def test_total_is_planned_plus_skipped_for_a_dry_run(self):
        """A dry run never touches the batch, so `summary.total` alone would
        leave `planned` out entirely -- `docs/specs/archive/spec-json-output.md` fixes
        `total` at `planned + skipped` for this case instead.
        """
        summary = Summary(skipped=2)
        record = report.summary_record(summary, planned=7, exit_code=0, dry_run=True)

        assert record["total"] == 9
        assert record["converted"] == 0
        assert record["failed"] == 0
        assert record["unsupported"] == 0


class TestEveryRecordTypeLeadsWithTypeThenSchema:
    def test_first_two_keys(self, tmp_path):
        records = [
            report.file_record(Result(_task(tmp_path), Outcome.CONVERTED, "remux")),
            report.planned_record(_task(tmp_path)),
            report.summary_record(Summary(), planned=0, exit_code=0, dry_run=False),
        ]

        for record in records:
            assert list(record.keys())[:2] == ["type", "schema"]
            assert record["schema"] == 1


class _CallLog(list):
    """Records the order flush()/write() are invoked in, across two fakes."""


class _TextStreamFake:
    def __init__(self, log: _CallLog) -> None:
        self._log = log

    def flush(self) -> None:
        self._log.append("text_flush")


class _BinaryStreamFake(io.BytesIO):
    def __init__(self, log: _CallLog) -> None:
        super().__init__()
        self._log = log

    def write(self, data: bytes) -> int:
        self._log.append(("write", bytes(data)))
        return super().write(data)

    def flush(self) -> None:
        self._log.append("stream_flush")
        super().flush()


class TestWriteJson:
    def test_writes_ascii_bytes_terminated_by_newline_only(self):
        stream = io.BytesIO()
        report.write_json({"type": "summary", "schema": 1}, stream, text_stream=io.StringIO())

        data = stream.getvalue()
        assert data == b'{"type": "summary", "schema": 1}\n'
        assert data.count(b"\n") == 1
        assert b"\r\n" not in data
        assert all(byte < 128 for byte in data)

    def test_round_trips_through_json_loads(self):
        record = {"type": "file", "schema": 1, "source": "a", "notes": [], "error": None}
        stream = io.BytesIO()
        report.write_json(record, stream, text_stream=io.StringIO())

        line = stream.getvalue()
        assert line.endswith(b"\n")
        assert json.loads(line.decode("ascii")) == record

    def test_non_ascii_name_is_escaped_and_round_trips(self):
        record = report.planned_record(Task(Path("Übung.mkv"), Path("Übung.mp4")))
        stream = io.BytesIO()
        report.write_json(record, stream, text_stream=io.StringIO())

        line = stream.getvalue()
        assert all(byte < 128 for byte in line)
        decoded = json.loads(line.decode("ascii"))
        assert decoded["source"].endswith("Übung.mkv")
        assert decoded["output"].endswith("Übung.mp4")

    def test_lone_surrogate_name_is_escaped_and_round_trips(self):
        # A POSIX file name that is not valid UTF-8 reaches Python as a lone
        # surrogate (docs/specs/archive/spec-json-output.md, Prior decisions).
        surrogate_name = "clip-\udcff.mkv"
        record = report.planned_record(Task(Path(surrogate_name), Path("out.mp4")))
        stream = io.BytesIO()
        report.write_json(record, stream, text_stream=io.StringIO())

        line = stream.getvalue()
        assert all(byte < 128 for byte in line)
        decoded = json.loads(line.decode("ascii"))
        assert decoded["source"].endswith(surrogate_name)

    def test_flushes_text_stream_before_writing_bytes_then_flushes_stream(self):
        log = _CallLog()
        text_stream = _TextStreamFake(log)
        stream = _BinaryStreamFake(log)

        report.write_json({"type": "summary", "schema": 1}, stream, text_stream=text_stream)

        assert log[0] == "text_flush"
        assert log[1][0] == "write"
        assert log[-1] == "stream_flush"

    def test_each_record_is_flushed_individually(self):
        log = _CallLog()
        text_stream = _TextStreamFake(log)
        stream = _BinaryStreamFake(log)

        report.write_json({"type": "summary", "schema": 1}, stream, text_stream=text_stream)
        report.write_json({"type": "summary", "schema": 1}, stream, text_stream=text_stream)

        assert log.count("stream_flush") == 2
        assert log.count("text_flush") == 2

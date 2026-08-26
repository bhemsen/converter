"""Tests for batch behaviour: the failures the old scripts swallowed."""

from pathlib import Path

import pytest

from converter import batch
from converter.batch import Outcome, Result, Task, convert_one, run_batch, summarise
from converter.ffmpegtool import CommandResult, ProbeError, Stream, Tools
from converter.profiles import MP4, WAV, Attempt, Profile, StreamRule, flags

TOOLS = Tools(ffmpeg="ffmpeg", ffprobe="ffprobe")


def exhaustive_profile() -> Profile:
    """A profile whose cheap attempt maps everything its source can carry.

    No shipped profile is exhaustive -- MP4's ``?``-selectors and WAV's single
    index are both partial by construction -- so the half of the narrowed
    happy-path rule that keeps an exhaustive cheap attempt probe-free needs a
    profile of its own before it can be asserted at all.
    """
    return Profile(
        label="EXH",
        name="exh",
        description="a test double, not a shipped format",
        target_suffix=".exh",
        container_options=(),
        cheap_attempt=Attempt(label="copy-all", options=flags("-c copy")),
        explicit_streams=False,
        partial_mapping=False,
        rules={"video": StreamRule(frozenset({"h264"}), flags("-c:v copy"))},
    )


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

        result = convert_one(MP4, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.CONVERTED
        assert result.attempt == "remux"
        assert len(fake_ffmpeg.calls) == 1

    def test_existing_output_is_skipped_by_default(self, tmp_path, fake_ffmpeg):
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        task.dst.write_bytes(b"already there")

        result = convert_one(MP4, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.SKIPPED
        assert fake_ffmpeg.calls == []
        assert task.dst.read_bytes() == b"already there"

    def test_overwrite_replaces_an_existing_output(self, tmp_path, fake_ffmpeg):
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        task.dst.write_bytes(b"already there")

        result = convert_one(MP4, task, TOOLS, overwrite=True)

        assert result.outcome is Outcome.CONVERTED
        assert len(fake_ffmpeg.calls) == 1

    def test_failed_remux_climbs_the_fallback_ladder(self, tmp_path, fake_ffmpeg):
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.exit_codes = [1, 0]
        fake_ffmpeg.streams = [Stream(0, "video", "h264"), Stream(1, "audio", "pcm_s16le")]

        result = convert_one(MP4, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.CONVERTED
        assert result.attempt == "selective"
        assert len(fake_ffmpeg.calls) == 2
        assert any("pcm_s16le" in note for note in result.notes)

    def test_probe_does_not_run_when_an_exhaustive_first_attempt_succeeds(
        self, tmp_path, fake_ffmpeg, monkeypatch
    ):
        """An ffprobe round-trip per file would be pure waste on the happy path.

        The narrowed rule (`docs/constitution.md`): a cheap attempt whose mapping
        is exhaustive has nothing a probe could reveal, so it never pays for one.
        """
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        probes = spy_on_probe(monkeypatch, [])

        result = convert_one(exhaustive_profile(), task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.CONVERTED
        assert probes == []

    def test_probe_does_run_once_the_first_attempt_fails(self, tmp_path, fake_ffmpeg, monkeypatch):
        """Counterpart to the test above: proves the spy would notice a probe."""
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.exit_codes = [1, 0]
        probes = spy_on_probe(monkeypatch, [Stream(0, "video", "h264")])

        convert_one(MP4, task, TOOLS, overwrite=False)

        assert probes == [task.src]

    def test_all_attempts_failing_is_reported_as_failure(self, tmp_path, fake_ffmpeg):
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.exit_codes = [1]
        fake_ffmpeg.streams = [Stream(0, "video", "h264")]

        result = convert_one(MP4, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.FAILED
        assert "remux" in result.error
        assert "re-encode" in result.error

    def test_truncated_output_is_removed_after_failure(self, tmp_path, fake_ffmpeg):
        """Leaving a partial file behind would make the next run 'skip' it."""
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.exit_codes = [1]
        # A stream MP4 has a rule for, so the whole ladder is climbed and
        # exhausted -- a genuine failure, not the unsupported outcome.
        fake_ffmpeg.streams = [Stream(0, "video", "h264")]

        result = convert_one(MP4, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.FAILED
        assert not task.dst.exists()

    def test_pre_existing_output_survives_a_failed_overwrite(self, tmp_path, fake_ffmpeg):
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        task.dst.write_bytes(b"good older file")
        fake_ffmpeg.exit_codes = [1]
        fake_ffmpeg.creates_output = False

        convert_one(MP4, task, TOOLS, overwrite=True)

        assert task.dst.read_bytes() == b"good older file"

    def test_probe_failure_is_recorded_not_raised(self, tmp_path, fake_ffmpeg):
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.exit_codes = [1]
        fake_ffmpeg.probe_error = "unreadable"

        result = convert_one(MP4, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.FAILED
        assert "unreadable" in result.error

    def test_unexpected_exception_does_not_escape(self, tmp_path, monkeypatch):
        task = make_task(tmp_path)

        def explode(*_args, **_kwargs):
            raise RuntimeError("kaboom")

        monkeypatch.setattr(batch.ffmpegtool, "run", explode)

        result = convert_one(MP4, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.FAILED
        assert "kaboom" in result.error


class TestPartialCheapAttemptVerification:
    """The success-side probe: a silent drop must never read as a plain success.

    Every test here drives the *cheap-attempt-succeeds* path -- `exit_codes` stays
    at its default `[0]` -- rather than calling `.retries()` directly, because
    that path is the one that used to report `converted` with no note at all.
    """

    def test_a_dropped_attachment_is_named_on_a_successful_remux(
        self, tmp_path, fake_ffmpeg, monkeypatch
    ):
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        probes = spy_on_probe(
            monkeypatch, [Stream(0, "video", "h264"), Stream(1, "attachment", "ttf")]
        )

        result = convert_one(MP4, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.CONVERTED
        assert result.attempt == "remux"
        assert len(fake_ffmpeg.calls) == 1
        # The other half of "at most one probe per file": the success side pays
        # for exactly one, never one per rung and never a second on the way out.
        assert probes == [task.src]
        assert result.notes == ("attachment stream 1 (ttf) dropped: not supported by MP4",)

    def test_a_dropped_surplus_audio_stream_is_named_on_a_successful_pcm_run(
        self, tmp_path, fake_ffmpeg
    ):
        src = tmp_path / "two-tone.opus"
        src.write_bytes(b"data")
        task = Task(src, tmp_path / "out" / "two-tone.wav")
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.streams = [Stream(0, "audio", "opus"), Stream(1, "audio", "opus")]

        result = convert_one(WAV, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.CONVERTED
        assert result.attempt == "pcm_s16le"
        assert len(fake_ffmpeg.calls) == 1
        assert result.notes == ("audio stream 1 (opus) dropped: WAV holds 1 audio stream",)

    def test_a_source_the_cheap_attempt_fully_maps_still_gets_no_note(self, tmp_path, fake_ffmpeg):
        """The probe is spent, but it must not invent a loss that did not happen."""
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.streams = [Stream(0, "video", "h264"), Stream(1, "audio", "aac")]

        result = convert_one(MP4, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.CONVERTED
        assert result.notes == ()

    def test_a_codec_the_copy_mask_misses_is_not_reported_as_re_encoded(
        self, tmp_path, fake_ffmpeg
    ):
        """ffmpeg exited 0, so it copied the stream; claiming a re-encode that
        never ran would swap one dishonest report for another."""
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.streams = [Stream(0, "video", "ffv1")]

        result = convert_one(MP4, task, TOOLS, overwrite=False)

        assert result.notes == ()

    def test_an_unreadable_source_is_not_reported_as_a_plain_success(self, tmp_path, fake_ffmpeg):
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.probe_error = "unreadable"

        result = convert_one(MP4, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.CONVERTED
        assert result.notes == ("could not verify which source streams were kept: unreadable",)

    def test_a_later_rung_is_not_verified_a_second_time(self, tmp_path, fake_ffmpeg, monkeypatch):
        """The selective rung was built from the stream list itself, so its own
        notes are already accurate and a second probe would buy nothing."""
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.exit_codes = [1, 0]
        probes = spy_on_probe(monkeypatch, [Stream(0, "video", "vp8")])

        result = convert_one(MP4, task, TOOLS, overwrite=False)

        assert result.attempt == "selective"
        assert len(probes) == 1
        assert result.notes == ("video stream 0 (vp8) re-encoded to h264",)


class TestUnsupportedOutcome:
    """The `unsupported` outcome (docs/specs/spec-target-driven-cli.md): a
    source that carries no stream of any type the target profile has a rule
    for at all, distinct from a stream a rule drops or fails to re-encode.
    """

    def _video_only_task(self, tmp_path: Path) -> Task:
        src = tmp_path / "clip.mkv"
        src.write_bytes(b"data")
        return Task(src, tmp_path / "out" / "clip.wav")

    def test_a_video_only_source_under_a_wav_target_is_unsupported(self, tmp_path, fake_ffmpeg):
        """The mixed-tree case the outcome exists for: WAV has no rule for a
        video stream, so a video-only source can never climb its ladder."""
        task = self._video_only_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.exit_codes = [1]
        fake_ffmpeg.streams = [Stream(0, "video", "h264")]

        result = convert_one(WAV, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.UNSUPPORTED
        assert result.notes == ("video stream 0 (h264) dropped: not supported by WAV",)

    def test_unsupported_does_not_climb_the_rest_of_the_ladder(self, tmp_path, fake_ffmpeg):
        """Only the cheap attempt and one probe are spent. WAV declares no
        last-resort rung at all, so a video-only source proves nothing here --
        MP4 does declare one, and an attachment-only source would let it
        *succeed* if the short-circuit did not stop the ladder first."""
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.exit_codes = [1, 0]  # the last-resort rung would succeed if it ran
        fake_ffmpeg.streams = [Stream(0, "attachment", "ttf")]

        result = convert_one(MP4, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.UNSUPPORTED
        assert len(fake_ffmpeg.calls) == 1

    def test_unsupported_output_is_removed_like_a_failure(self, tmp_path, fake_ffmpeg):
        task = self._video_only_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.exit_codes = [1]
        fake_ffmpeg.streams = [Stream(0, "video", "h264")]

        convert_one(WAV, task, TOOLS, overwrite=False)

        assert not task.dst.exists()

    def test_a_re_run_over_the_same_unsupported_source_reports_the_same_outcome(
        self, tmp_path, fake_ffmpeg
    ):
        """The idempotent-re-run criterion (docs/vision.md): the outcome exists
        precisely so a second run does not turn this into a permanent failure."""
        task = self._video_only_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.exit_codes = [1]
        fake_ffmpeg.streams = [Stream(0, "video", "h264")]

        first = summarise([convert_one(WAV, task, TOOLS, overwrite=False)])
        second = summarise([convert_one(WAV, task, TOOLS, overwrite=False)])

        assert (first.unsupported, first.exit_code) == (1, 0)
        assert (second.unsupported, second.exit_code) == (1, 0)

    def test_a_stream_the_profile_has_a_rule_for_is_a_genuine_failure(self, tmp_path, fake_ffmpeg):
        """The distinction that matters: a stream the profile declares a rule
        for is never unsupported, even when every attempt still fails -- or a
        corrupt file would be quietly relabelled (spec-target-driven-cli.md)."""
        task = self._video_only_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.exit_codes = [1]
        fake_ffmpeg.streams = [Stream(0, "audio", "opus")]

        result = convert_one(WAV, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.FAILED

    def test_summarise_counts_unsupported_and_it_does_not_set_the_exit_code(self):
        summary = summarise(
            [
                Result(Task(Path("video.mkv"), Path("video.wav")), Outcome.UNSUPPORTED),
                Result(Task(Path("clip.mkv"), Path("clip.mp4")), Outcome.CONVERTED),
            ]
        )

        assert (summary.converted, summary.unsupported, summary.failed) == (1, 1, 0)
        assert summary.total == 2
        assert summary.exit_code == 0

    def test_a_probe_that_finds_no_streams_at_all_stays_a_genuine_failure(
        self, tmp_path, fake_ffmpeg
    ):
        """A probe that succeeds but reports zero streams is what a corrupt or
        truncated source looks like -- not evidence the format holds nothing
        usable -- so it must not be quietly relabelled `unsupported` with no
        notes and no error text (docs/specs/spec-target-driven-cli.md)."""
        task = self._video_only_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.exit_codes = [1]
        fake_ffmpeg.streams = []

        result = convert_one(WAV, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.FAILED
        assert "boom" in result.error


class TestRunBatch:
    def test_creates_output_directories_once_in_the_parent(self, tmp_path, fake_ffmpeg):
        """Every worker used to run 'if not exists: makedirs()' itself, so they
        raced and the losers died with FileExistsError."""
        tasks = [make_task(tmp_path, f"clip{i}") for i in range(5)]

        results = run_batch(MP4, tasks, TOOLS, jobs=4, progress=False)

        assert (tmp_path / "out").is_dir()
        assert all(r.outcome is Outcome.CONVERTED for r in results)

    def test_nested_output_directories_are_created(self, tmp_path, fake_ffmpeg):
        src = tmp_path / "a" / "b" / "clip.mkv"
        src.parent.mkdir(parents=True)
        src.write_bytes(b"data")
        task = Task(src, tmp_path / "out" / "a" / "b" / "clip.mp4")

        results = run_batch(MP4, [task], TOOLS, progress=False)

        assert results[0].outcome is Outcome.CONVERTED
        assert task.dst.parent.is_dir()

    def test_returns_one_result_per_task(self, tmp_path, fake_ffmpeg):
        tasks = [make_task(tmp_path, f"clip{i}") for i in range(7)]

        results = run_batch(WAV, tasks, TOOLS, jobs=3, progress=False)

        assert len(results) == len(tasks)
        assert {r.task.src for r in results} == {t.src for t in tasks}

    def test_empty_task_list_is_harmless(self, tmp_path, fake_ffmpeg):
        assert run_batch(MP4, [], TOOLS, progress=False) == []

    def test_interrupt_drops_work_that_has_not_started(self, tmp_path, monkeypatch):
        """Ctrl+C used to be noticed only after every queued file had converted:
        ThreadPoolExecutor's context manager shuts down with wait=True and no
        cancellation, so the whole batch drained before the interrupt surfaced.

        Asserted as an exact count, not as "fewer than all".  Cancelling the
        futures alone left this timing-dependent -- the single worker can drain
        the queue before the main thread ever consumes the future carrying the
        interrupt -- so the loose bound passed on Windows while the same batch
        ran to completion on Linux.  With one worker and the interrupt on the
        third file, exactly three conversions may ever start.
        """
        tasks = [make_task(tmp_path, f"clip{i:02d}") for i in range(12)]
        calls: list[list[str]] = []

        def run(argv, **_kwargs):
            calls.append(list(argv))
            if len(calls) == 3:
                raise KeyboardInterrupt
            return CommandResult(tuple(argv), 0, "", "")

        monkeypatch.setattr(batch.ffmpegtool, "run", run)

        with pytest.raises(KeyboardInterrupt):
            run_batch(MP4, tasks, TOOLS, jobs=1, progress=False)

        assert len(calls) == 3


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
                self._result(Outcome.UNSUPPORTED),
            ]
        )

        assert (summary.converted, summary.skipped, summary.failed, summary.unsupported) == (
            2,
            1,
            1,
            1,
        )
        assert summary.total == 5

    def test_any_failure_makes_the_exit_code_non_zero(self):
        """The old scripts always printed 'Conversion completed.' and exited 0."""
        assert summarise([self._result(Outcome.FAILED)]).exit_code == 1

    def test_a_clean_run_exits_zero(self):
        assert summarise([self._result(Outcome.CONVERTED)]).exit_code == 0

    def test_skipped_only_is_not_a_failure(self):
        assert summarise([self._result(Outcome.SKIPPED)]).exit_code == 0

    def test_unsupported_only_is_not_a_failure(self):
        """The whole point of the outcome: it must never set the exit code."""
        assert summarise([self._result(Outcome.UNSUPPORTED)]).exit_code == 0

    def test_describe_mentions_every_bucket(self):
        text = summarise([self._result(Outcome.CONVERTED)]).describe()

        assert "1 converted" in text
        assert "0 failed" in text
        assert "0 unsupported" in text


class TestDefaultJobs:
    def test_is_bounded(self):
        """One process per input file oversubscribed the machine badly."""
        assert 1 <= batch.default_jobs() <= 4

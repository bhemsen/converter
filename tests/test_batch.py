"""Tests for batch behaviour: the failures the old scripts swallowed."""

from pathlib import Path

import pytest

from converter import batch, jobs
from converter.batch import Outcome, Result, Task, convert_one, run_batch, summarise
from converter.ffmpegtool import CommandResult, ProbeError, Stream, Tools
from converter.profiles import (
    BMP,
    FLAC,
    MKV,
    MOV,
    MP3,
    MP4,
    PNG,
    TIFF,
    WAV,
    WEBM,
    Attempt,
    Profile,
    StreamRule,
    flags,
)

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


def picture_carrying_profile() -> Profile:
    """A profile shaped like the audio targets spec-stream-disposition.md
    amends (mp3, m4a, flac): an audio rule plus an ``attached_pic`` one, so the
    full `batch.convert_one` path can be proven end-to-end without waiting on
    a shipped profile to gain the rule (issue #87, a sibling of this one).
    """
    return Profile(
        label="PICT",
        name="pict",
        description="a test double, not a shipped format",
        target_suffix=".pict",
        container_options=(),
        cheap_attempt=Attempt(
            label="remux", options=flags("-map 0:a? -map 0:disp:attached_pic? -c copy")
        ),
        explicit_streams=False,
        partial_mapping=True,
        rules={
            "audio": StreamRule(frozenset({"aac"}), flags("-c:a copy"), stream_limit=1),
            "attached_pic": StreamRule(frozenset({"png", "mjpeg"}), flags("-c:v:{n} copy")),
        },
    )


@pytest.fixture
def fake_ffmpeg(monkeypatch):
    """Replace ffmpeg with a scripted stand-in and record every invocation."""

    class Fake:
        def __init__(self):
            self.calls: list[list[str]] = []
            self.exit_codes: list[int] = [0]
            self.streams: list[Stream] = []
            #: What a probe of the *written file* reports, as opposed to
            #: ``streams`` (the source). Empty by default: the muxer kept
            #: nothing the mapping did not ask for, so every predicted drop
            #: stands. A profile whose container puts a stream back (MOV's
            #: regenerated timecode track, issue #66) sets this instead.
            self.output_streams: list[Stream] = []
            self.probe_error: str | None = None
            self.creates_output = True
            self.written: set[Path] = set()

        def run(self, argv, **_kwargs):
            argv = list(argv)
            self.calls.append(argv)
            code = self.exit_codes[min(len(self.calls) - 1, len(self.exit_codes) - 1)]
            if self.creates_output:
                Path(argv[-1]).write_bytes(b"partial")
                self.written.add(Path(argv[-1]))
            return CommandResult(tuple(argv), code, "", "boom" if code else "")

        def probe_streams(self, _tools, src):
            if self.probe_error is not None:
                raise ProbeError(self.probe_error)
            # Which file is being probed is the whole point of the
            # confirmation step, so the fake has to tell the two apart rather
            # than answering the same list for both.
            return self.output_streams if Path(src) in self.written else self.streams

    fake = Fake()
    monkeypatch.setattr(batch.ffmpegtool, "run", fake.run)
    monkeypatch.setattr(batch.ffmpegtool, "probe_streams", fake.probe_streams)
    return fake


def make_task(tmp_path: Path, name: str = "clip") -> Task:
    src = tmp_path / f"{name}.mkv"
    src.write_bytes(b"data")
    return Task(src, tmp_path / "out" / f"{name}.mp4")


def spy_on_probe(
    monkeypatch,
    streams: list[Stream],
    output_streams: list[Stream] | None = None,
    task: Task | None = None,
) -> list[Path]:
    """Replace probe_streams on the module and record what it was asked about.

    Patching the module attribute matters: rebinding the attribute on the fake
    object would leave the already-installed reference untouched, and the spy
    would silently never be called.

    Source and output are told apart by *path*, the same way the `fake_ffmpeg`
    fixture does it, so a test cannot pass on the strength of the order the two
    probes happen to run in. Pass `task` to answer differently for the output;
    passing `output_streams` without it is refused rather than silently ignored,
    so a test cannot look like it exercises the output probe while in fact
    answering the source list twice.
    """
    if output_streams is not None and task is None:
        raise TypeError("output_streams needs task, to tell the output path apart")
    seen: list[Path] = []

    def probe(_tools, src):
        seen.append(src)
        if task is not None and Path(src) == task.dst:
            return list(output_streams or [])
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

    def test_flac_from_a_pcm_source_reaches_the_selective_rung_not_failed(
        self, tmp_path, fake_ffmpeg
    ):
        """Guard rail for issue #23: `--to flac` over a PCM source (`tone.wav`
        in the milestone's QA gate) must climb to the selective rung's re-encode
        rather than exhaust the whole ladder into `Outcome.FAILED` -- verified
        against the real engine during the audio-formats spec's review
        (docs/specs/archive/spec-audio-formats.md's Decision log, 2026-08-25 entry: "a
        PCM stream yields `selective` then `re-encode`"). `mp3`/`flac`'s
        `last_resort` exists to rescue a *different* case -- a mask hit whose
        copy the muxer then refuses -- so a PCM source landing there instead of
        on `selective` would be the wrong rung succeeding for the wrong reason.
        """
        src = tmp_path / "clip.wav"
        src.write_bytes(b"data")
        task = Task(src, tmp_path / "out" / "clip.flac")
        task.dst.parent.mkdir(parents=True)
        # FLAC's cheap attempt is a blind "-c:a copy": a PCM stream cannot copy
        # into FLAC, so it fails and the ladder must be climbed.
        fake_ffmpeg.exit_codes = [1, 0]
        fake_ffmpeg.streams = [Stream(0, "audio", "pcm_s16le")]

        result = convert_one(FLAC, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.CONVERTED
        assert result.attempt == "selective"
        assert len(fake_ffmpeg.calls) == 2

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
            monkeypatch,
            [Stream(0, "video", "h264"), Stream(1, "attachment", "ttf")],
            # MP4 really cannot hold a font attachment, so the output has none.
            output_streams=[Stream(0, "video", "h264")],
            task=task,
        )

        result = convert_one(MP4, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.CONVERTED
        assert result.attempt == "remux"
        assert len(fake_ffmpeg.calls) == 1
        # One probe per file, plus the one the claim itself pays for: the source
        # says what was there, the output says what survived. Never one per rung.
        assert probes == [task.src, task.dst]
        assert result.notes == ("attachment stream 1 (ttf) dropped: not supported by MP4",)

    def test_a_dropped_surplus_audio_stream_is_named_on_a_successful_pcm_run(
        self, tmp_path, fake_ffmpeg
    ):
        src = tmp_path / "two-tone.opus"
        src.write_bytes(b"data")
        task = Task(src, tmp_path / "out" / "two-tone.wav")
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.streams = [Stream(0, "audio", "opus"), Stream(1, "audio", "opus")]
        # WAV really does hold one: the drop the mapping predicts is confirmed
        # by the written file rather than assumed from the mapping alone.
        fake_ffmpeg.output_streams = [Stream(0, "audio", "pcm_s16le")]

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

    @pytest.mark.parametrize(
        "failure",
        [ProbeError("output vanished"), OSError("output vanished")],
        ids=["ProbeError", "OSError"],
    )
    def test_a_probe_of_the_output_that_fails_leaves_the_prediction_standing(
        self, tmp_path, fake_ffmpeg, monkeypatch, failure
    ):
        """The confirmation is what can *remove* a note, so losing it must fall
        back to over-reporting, never to silence (``docs/constitution.md``).

        `OSError` as well: the probe is a spawn, and this one happens after
        ffmpeg already wrote a good file, so a failure to start it must not turn
        that conversion into a reported failure."""
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)

        def probe(_tools, src):
            if Path(src) == task.dst:
                raise failure
            return [Stream(0, "video", "h264"), Stream(1, "attachment", "ttf")]

        monkeypatch.setattr(batch.ffmpegtool, "probe_streams", probe)

        result = convert_one(MP4, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.CONVERTED
        assert result.notes == (
            "attachment stream 1 (ttf) dropped: not supported by MP4",
            "could not confirm this against the output: output vanished",
        )

    def test_a_source_probe_that_cannot_even_spawn_is_not_a_failed_conversion(
        self, tmp_path, fake_ffmpeg, monkeypatch
    ):
        """Same argument one function up: the success-side source probe also runs
        after ffmpeg produced a good file, so an `OSError` there degrades the
        bookkeeping rather than the conversion."""
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)

        def probe(_tools, _src):
            raise OSError("ffprobe could not be started")

        monkeypatch.setattr(batch.ffmpegtool, "probe_streams", probe)

        result = convert_one(MP4, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.CONVERTED
        assert result.notes == (
            "could not verify which source streams were kept: ffprobe could not be started",
        )

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


class TestAttachedPictureVerification:
    """stream-decision.md's PIC node, exercised through the full
    `convert_one` path rather than `jobs` in isolation (issue #76): a carried
    picture must never read as a drop, and a real video stream still must."""

    def test_a_carried_picture_is_not_reported_as_dropped(self, tmp_path, fake_ffmpeg):
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        picture = Stream(1, "video", "png", attached_pic=True)
        fake_ffmpeg.streams = [Stream(0, "audio", "aac"), picture]
        # The muxer wrote back exactly what the mapping asked for.
        fake_ffmpeg.output_streams = [Stream(0, "audio", "aac"), picture]

        result = convert_one(picture_carrying_profile(), task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.CONVERTED
        assert result.notes == ()

    def test_a_real_video_stream_is_still_named_as_dropped(self, tmp_path, fake_ffmpeg):
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.streams = [Stream(0, "audio", "aac"), Stream(1, "video", "h264")]
        # The profile has no ``video`` rule, so the disposition-less video
        # stream really was left behind.
        fake_ffmpeg.output_streams = [Stream(0, "audio", "aac")]

        result = convert_one(picture_carrying_profile(), task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.CONVERTED
        assert result.notes == ("video stream 1 (h264) dropped: not supported by PICT",)


class TestDropsAreConfirmedAgainstTheOutput:
    """Issue #66: a `-map` set says what ffmpeg was *asked* to carry, which is
    not the same as what the muxer wrote.

    Measured against ffmpeg 9.0: MP4 and MOV regenerate a `tmcd` timecode track
    from the source's metadata although no selector names it, while MKV and
    WebM really do leave it behind. Every test here drives the
    cheap-attempt-succeeds path through `convert_one`, so it exercises the
    success-side verification rather than `jobs.confirm_drops` in isolation.
    """

    #: What ffprobe reports for a `tmcd` stream: a data stream whose codec name
    #: is absent on both sides, which is what lets the confirmation match a
    #: regenerated timecode to its source without ever matching indices.
    TIMECODE = Stream(2, "data", "")

    def _task(self, tmp_path: Path, suffix: str) -> Task:
        src = tmp_path / "tcsrc.mp4"
        src.write_bytes(b"data")
        task = Task(src, tmp_path / "out" / f"tcsrc.{suffix}")
        task.dst.parent.mkdir(parents=True)
        return task

    @pytest.mark.parametrize("profile", [MP4, MOV], ids=lambda profile: profile.label)
    def test_a_timecode_stream_the_muxer_puts_back_is_not_reported_as_dropped(
        self, tmp_path, fake_ffmpeg, profile
    ):
        task = self._task(tmp_path, profile.target_suffix.lstrip("."))
        fake_ffmpeg.streams = [Stream(0, "video", "h264"), Stream(1, "audio", "aac"), self.TIMECODE]
        fake_ffmpeg.output_streams = list(fake_ffmpeg.streams)

        result = convert_one(profile, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.CONVERTED
        assert result.notes == ()

    @pytest.mark.parametrize("profile", [MKV, WEBM], ids=lambda profile: profile.label)
    def test_a_timecode_stream_the_muxer_really_drops_is_still_named(
        self, tmp_path, fake_ffmpeg, profile
    ):
        task = self._task(tmp_path, profile.target_suffix.lstrip("."))
        fake_ffmpeg.streams = [Stream(0, "video", "h264"), Stream(1, "audio", "aac"), self.TIMECODE]
        fake_ffmpeg.output_streams = [Stream(0, "video", "h264"), Stream(1, "audio", "aac")]

        result = convert_one(profile, task, TOOLS, overwrite=False)

        # The full tuple, not a membership check: the standing note these two
        # profiles still carry is part of what must not have changed.
        assert result.notes == (
            *profile.cheap_attempt.notes,
            f"data stream 2 (unknown) dropped: not supported by {profile.label}",
        )

    def test_an_ambiguous_surplus_forgives_nothing(self, tmp_path, fake_ffmpeg):
        """Two streams the probe cannot tell apart are predicted dropped and one
        comes back. Which one survived is unknowable, so both keep their note --
        guessing would claim a loss that did not happen *and* hide one that
        did."""
        task = self._task(tmp_path, "mp4")
        fake_ffmpeg.streams = [
            Stream(0, "video", "h264", "avc1"),
            Stream(1, "data", "", "tmcd"),
            Stream(2, "data", "", "tmcd"),
        ]
        fake_ffmpeg.output_streams = [
            Stream(0, "video", "h264", "avc1"),
            Stream(1, "data", "", "tmcd"),
        ]

        result = convert_one(MP4, task, TOOLS, overwrite=False)

        assert result.notes == (
            "data stream 1 (unknown) dropped: not supported by MP4",
            "data stream 2 (unknown) dropped: not supported by MP4",
        )

    @pytest.mark.parametrize("profile", [MP4, MOV], ids=lambda profile: profile.label)
    def test_a_metadata_track_is_not_hidden_behind_the_timecode_that_survived(
        self, tmp_path, fake_ffmpeg, profile
    ):
        """The iPhone `.mov` shape review measured: an Apple `mebx` metadata
        track and a `tmcd` beside it, neither reporting a codec name. Only the
        timecode comes back, at a *different index*. The container tag is what
        keeps the engine from forgiving the metadata track and reporting the
        survivor in its place."""
        task = self._task(tmp_path, profile.target_suffix.lstrip("."))
        fake_ffmpeg.streams = [
            Stream(0, "video", "h264", "avc1"),
            Stream(1, "audio", "aac", "mp4a"),
            Stream(2, "data", "", "mebx"),
            Stream(3, "data", "", "tmcd"),
        ]
        fake_ffmpeg.output_streams = [
            Stream(0, "video", "h264", "avc1"),
            Stream(1, "audio", "aac", "mp4a"),
            Stream(2, "data", "", "tmcd"),
        ]

        result = convert_one(profile, task, TOOLS, overwrite=False)

        assert result.notes == (
            f"data stream 2 (unknown) dropped: not supported by {profile.label}",
        )

    def test_a_real_drop_is_not_forgiven_by_the_re_encode_that_replaced_it(
        self, tmp_path, fake_ffmpeg
    ):
        """The second regression review caught: WAV's cheap attempt re-encodes,
        so its `pcm_s16le` output stream reads as a surplus under the source's
        own `pcm_s16le` key and forgave a track that really was lost. An
        ordinary camera/pro-video MOV carrying one compressed and one PCM track
        reaches this, so it is not a corner case."""
        src = tmp_path / "two-track.mov"
        src.write_bytes(b"data")
        task = Task(src, tmp_path / "out" / "two-track.wav")
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.streams = [Stream(0, "audio", "aac"), Stream(1, "audio", "pcm_s16le")]
        fake_ffmpeg.output_streams = [Stream(0, "audio", "pcm_s16le")]

        result = convert_one(WAV, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.CONVERTED
        assert result.notes == ("audio stream 1 (pcm_s16le) dropped: WAV holds 1 audio stream",)

    def test_a_real_drop_is_not_forgiven_by_a_stream_the_muxer_synthesised(
        self, tmp_path, fake_ffmpeg
    ):
        """The regression the first review of this fix caught: a `gpmd`/ANC
        telemetry stream really lost, and a `tmcd` the muxer put back. Matching
        on stream type alone reported a clean success while a stream was gone --
        the direction `docs/constitution.md` forbids outright."""
        task = self._task(tmp_path, "mov")
        fake_ffmpeg.streams = [Stream(0, "video", "h264"), Stream(1, "data", "bin_data")]
        fake_ffmpeg.output_streams = [Stream(0, "video", "h264"), Stream(1, "data", "")]

        result = convert_one(MOV, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.CONVERTED
        assert result.notes == ("data stream 1 (bin_data) dropped: not supported by MOV",)

    def test_the_output_is_probed_only_when_a_loss_is_about_to_be_claimed(
        self, tmp_path, fake_ffmpeg, monkeypatch
    ):
        """The confirmation's whole cost argument: a conversion that lost
        nothing still spends the single probe it spent before."""
        task = self._task(tmp_path, "mp4")
        probes = spy_on_probe(monkeypatch, [Stream(0, "video", "h264"), Stream(1, "audio", "aac")])

        result = convert_one(MP4, task, TOOLS, overwrite=False)

        assert result.notes == ()
        assert probes == [task.src]


class TestUnsupportedOutcome:
    """The `unsupported` outcome (docs/specs/archive/spec-target-driven-cli.md): a
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
        notes and no error text (docs/specs/archive/spec-target-driven-cli.md)."""
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


class TestLossySourceAdvisory:
    """Issue #88, `docs/specs/spec-lossy-source-notes.md`: the advisory that
    fires when a lossy source reaches FLAC's selective (failure-side) rung --
    "your FLAC came from a 128 kbit/s MP3." Scoped to `jobs.retries` /
    `convert_one` behaviour; profile definitions and `test_argv.py` are #77's
    concurrent territory and stay untouched.
    """

    def test_lossy_source_into_flac_names_index_and_codec(self):
        """The motivating case: an MP3 fails FLAC's `-c:a copy` cheap attempt,
        lands on the selective rung, and today (pre-#88) that rung carries no
        note at all -- verified unaffected for `test_argv.py`'s own pinned
        cases, none of which name a lossy codec.
        """
        streams = [Stream(0, "audio", "mp3")]

        selective = jobs.retries(FLAC, streams)[0]

        assert selective.options == ("-map", "0:0", "-c:a", "flac")
        assert selective.notes == (
            "audio stream 0 (mp3) was already lossy before this file reached "
            "FLAC; FLAC cannot restore what mp3 discarded",
        )

    def test_lossless_alac_into_flac_carries_no_advisory(self):
        """The negative that actually exercises the guard (spec Verification):
        ALAC fails FLAC's `-c:a copy` cheap attempt exactly like an MP3 does and
        reaches the identical selective rung, so only `LOSSY_CODECS` membership
        -- not merely "reached the rung" -- decides whether the advisory fires.
        """
        streams = [Stream(0, "audio", "alac")]

        selective = jobs.retries(FLAC, streams)[0]

        assert selective.notes == ()

    def test_flac_into_flac_is_a_rung_1_control_and_never_reaches_the_rung(self):
        """flac-into-flac copies and wins at rung 1 (`first_attempt`); it never
        reaches the selective rung the advisory lives on, so it is kept only as
        the control the spec's Verification section names, proving nothing
        about the guard on its own.

        Issue #78, docs/specs/spec-stream-disposition.md: rung 1's standing
        note is retired -- `jobs.verify_success` already names any drop this
        note used to describe, per stream. This control now asserts the
        rung carries no notes of its own at all, still proving nothing about
        the advisory (which lives on the selective rung, never reached here).
        """
        assert jobs.first_attempt(FLAC).notes == ()

    def test_lossy_source_into_a_lossy_target_keeps_the_ordinary_note_only(self):
        """Lossy-to-lossy is out of scope by decision: the engine's own
        re-encode note is the honest report there, and the advisory -- scoped
        to `flac` alone -- must not add a second line.
        """
        streams = [Stream(0, "audio", "opus")]

        selective = jobs.retries(MP3, streams)[0]

        assert selective.notes == ("audio stream 0 (opus) re-encoded to mp3",)

    def test_wav_selective_rung_stays_skipped_trap_1(self):
        """Trap 1, named first in the issue: folding the advisory *inside*
        `_build_selective`'s plan would give its notes list a non-empty entry
        for a lossy source and defeat
        ``if profile.explicit_streams and not notes: return None`` --
        resurrecting the rung WAV's `explicit_streams=True` deliberately skips
        today. Appending the advisory only in `retries`, after that check has
        already run, keeps this `[]` exactly as it was before #88.
        """
        assert jobs.retries(WAV, [Stream(0, "audio", "mp3")]) == []

    @pytest.mark.parametrize("profile", [PNG, TIFF, BMP], ids=lambda p: p.name)
    def test_the_other_lossless_targets_stay_silent(self, profile):
        """The accepted inconsistency (spec Prior decisions, resolved at the
        gate): only `flac` carries the advisory. `wav`, `png`, `tiff` and `bmp`
        always succeed their cheap attempt in practice, but even called
        directly their selective rung must still report nothing for a lossy
        video source -- pinned per profile so a change scoped too widely to
        `jobs.py` cannot silently start naming any of the other four.
        """
        streams = [Stream(0, "video", "mjpeg")]

        selective = jobs.retries(profile, streams)[0]

        assert selective.notes == ()

    def test_copied_through_cover_art_carries_no_advisory(self):
        """Regression: `main` gained FLAC's `attached_pic` rule (issue #77,
        `docs/specs/spec-stream-disposition.md`) between this issue's review
        and its merge. That rule's copy mask (`_AcceptAnyCodec`) accepts every
        codec and the rule declares no fallback, so a cover picture is always
        copied byte-for-byte, never re-encoded into FLAC's own codec -- unlike
        the audio rule, where reaching `LOSSY_CODECS` membership implies the
        fallback branch ran. A common `mjpeg` cover image is a `LOSSY_CODECS`
        member, so without this guard the copy-through would wrongly read as
        "FLAC cannot restore what mjpeg discarded" for a stream nothing was
        discarded from.
        """
        streams = [
            Stream(0, "audio", "mp3"),
            Stream(1, "video", "mjpeg", attached_pic=True),
        ]

        selective = jobs.retries(FLAC, streams)[0]

        assert selective.options == (
            "-map",
            "0:0",
            "-map",
            "0:1",
            "-c:a",
            "flac",
            "-c:v:0",
            "copy",
        )
        assert selective.notes == (
            "audio stream 0 (mp3) was already lossy before this file reached "
            "FLAC; FLAC cannot restore what mp3 discarded",
        )

    def test_end_to_end_advisory_and_probe_count(self, tmp_path, fake_ffmpeg, monkeypatch):
        """Full `convert_one` path, not just `jobs.retries` in isolation: the
        advisory must survive into `Result.notes`, and
        `docs/constitution.md`'s probe budget -- at most one probe on this
        failure-then-succeed path -- must stay exactly what it was before #88.
        The advisory reads only the stream list `retries` already receives, so
        it must not be the thing that adds a second probe.
        """
        task = make_task(tmp_path)
        task.dst.parent.mkdir(parents=True)
        fake_ffmpeg.exit_codes = [1, 0]
        fake_ffmpeg.streams = [Stream(0, "audio", "mp3")]
        probes = spy_on_probe(monkeypatch, [Stream(0, "audio", "mp3")])

        result = convert_one(FLAC, task, TOOLS, overwrite=False)

        assert result.outcome is Outcome.CONVERTED
        assert any("was already lossy" in note for note in result.notes)
        assert probes == [task.src]


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

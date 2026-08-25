"""Tests for the ffmpeg command lines we build, without running ffmpeg."""

import subprocess

import pytest

from converter import ffmpegtool
from converter.ffmpegtool import Stream, build_argv, cli_path
from converter.jobs import MKV_TO_MP4, OPUS_TO_WAV


def options_of(argv: list[str], src: str, dst: str) -> list[str]:
    """The slice of *argv* between the input file and the output file."""
    return argv[argv.index(src) + 1 : argv.index(dst)]


class TestCliPath:
    def test_leaves_ordinary_paths_alone(self):
        assert cli_path("clip.mkv") == "clip.mkv"

    def test_anchors_names_that_start_with_a_dash(self):
        """A file called '-vf' is legal, and ffmpeg would parse it as a flag."""
        result = cli_path("-vf")

        assert not result.startswith("-")
        assert result.endswith("vf")


class TestBuildArgv:
    def test_layout_and_mandatory_flags(self):
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

    def test_nostdin_is_always_present(self):
        """Without it, concurrent ffmpegs fight over the shared console stdin."""
        assert "-nostdin" in build_argv("ffmpeg", "in.mkv", (), "out.mp4")

    def test_overwrite_is_decided_before_ffmpeg_sees_it(self):
        """'-n' does not skip an existing file, it exits non-zero -- which would
        make every already-converted file look like a failure."""
        argv = build_argv("ffmpeg", "in.mkv", (), "out.mp4")

        assert "-y" in argv
        assert "-n" not in argv

    def test_no_separator_that_ffmpeg_would_misparse(self):
        """ffmpeg treats '-i' as a group separator and would take '--' as the
        input filename, so dash-leading names are handled by cli_path instead."""
        assert "--" not in build_argv("ffmpeg", "in.mkv", (), "out.mp4")

    def test_dash_leading_filenames_are_neutralised(self):
        argv = build_argv("ffmpeg", "-in.mkv", (), "-out.mp4")

        after_i = argv[argv.index("-i") + 1]
        assert not after_i.startswith("-")
        assert not argv[-1].startswith("-")


class TestRunIsShellFree:
    def test_argv_list_no_shell_and_stdin_closed(self, monkeypatch):
        captured = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            return subprocess.CompletedProcess(argv, 0, "", "")

        monkeypatch.setattr(subprocess, "run", fake_run)

        ffmpegtool.run(["ffmpeg", "-version"])

        assert isinstance(captured["argv"], list)
        assert captured["kwargs"].get("shell") is None
        assert captured["kwargs"]["stdin"] is subprocess.DEVNULL
        assert captured["kwargs"]["check"] is False


class TestWavJob:
    def test_first_attempt_is_pcm(self):
        attempt = OPUS_TO_WAV.first_attempt()

        assert attempt.options == ("-map", "0:a:0", "-c:a", "pcm_s16le")
        assert attempt.notes == ()

    def test_single_audio_stream_needs_no_fallback(self):
        streams = [Stream(0, "audio", "opus")]

        assert OPUS_TO_WAV.retries(streams) == []

    def test_multiple_audio_streams_fall_back_to_a_selective_rung(self):
        """Deltas 2 and 3: the note names the dropped stream and its codec, and
        the engine-built rung is labelled 'selective' rather than
        'first-audio-stream'. The argv is unchanged."""
        streams = [Stream(0, "audio", "opus"), Stream(1, "audio", "opus")]

        attempts = OPUS_TO_WAV.retries(streams)

        assert len(attempts) == 1
        assert attempts[0].label == "selective"
        assert attempts[0].options == ("-map", "0:0", "-c:a", "pcm_s16le")
        assert attempts[0].notes == ("audio stream 1 (opus) dropped: WAV holds 1 audio stream",)

    def test_non_audio_stream_gains_a_selective_rung_on_the_failure_path(self):
        """Delta 4: an embedded cover-art stream used to produce no retry at
        all; it now reaches a selective rung that drops it with a note."""
        streams = [Stream(0, "audio", "opus"), Stream(1, "video", "mjpeg")]

        attempts = OPUS_TO_WAV.retries(streams)

        assert len(attempts) == 1
        assert attempts[0].label == "selective"
        assert attempts[0].options == ("-map", "0:0", "-c:a", "pcm_s16le")
        assert attempts[0].notes == ("video stream 1 (mjpeg) dropped: not supported by WAV",)

    def test_job_metadata(self):
        assert OPUS_TO_WAV.suffixes == (".opus",)
        assert OPUS_TO_WAV.target_suffix == ".wav"

    def test_pcm_reencode_of_the_kept_stream_carries_no_note(self):
        """Decoding to PCM is WAV's own definition, not a loss (Verification,
        spec-profile-registry): the kept stream takes the fallback branch --
        WAV's copy mask is empty by construction -- yet contributes no note.
        Only the surplus stream's drop is reported."""
        streams = [Stream(0, "audio", "opus"), Stream(1, "audio", "opus")]

        attempts = OPUS_TO_WAV.retries(streams)

        assert len(attempts[0].notes) == 1
        assert not any("stream 0" in note for note in attempts[0].notes)


class TestMp4Remux:
    def test_stream_copies_and_converts_text_subtitles(self):
        options = MKV_TO_MP4.first_attempt().options

        assert "-c" in options
        assert options[options.index("-c") + 1] == "copy"
        assert "mov_text" in options
        assert "+faststart" in options

    def test_does_not_use_bare_map_zero(self):
        """'-map 0' also selects MKV attachments and data streams, which MP4
        cannot hold, so a remuxable file would fail for no good reason."""
        options = list(MKV_TO_MP4.first_attempt().options)
        mapped = [options[i + 1] for i, flag in enumerate(options) if flag == "-map"]

        assert "0" not in mapped
        assert mapped == ["0:v?", "0:a?", "0:s?"]

    def test_job_metadata(self):
        assert MKV_TO_MP4.suffixes == (".mkv",)
        assert MKV_TO_MP4.target_suffix == ".mp4"
        assert MKV_TO_MP4.first_attempt().options == (
            "-map",
            "0:v?",
            "-map",
            "0:a?",
            "-map",
            "0:s?",
            "-c",
            "copy",
            "-c:s",
            "mov_text",
            "-movflags",
            "+faststart",
        )


class TestMp4Retries:
    def test_ladder_ends_with_a_full_reencode(self):
        attempts = MKV_TO_MP4.retries([Stream(0, "video", "h264")])

        assert [a.label for a in attempts] == ["selective", "re-encode"]

    def test_selective_copies_compatible_streams(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "audio", "aac")]

        selective = MKV_TO_MP4.retries(streams)[0]

        assert selective.options[:8] == (
            "-map",
            "0:0",
            "-map",
            "0:1",
            "-c:v:0",
            "copy",
            "-c:a:0",
            "copy",
        )
        assert selective.notes == ()

    def test_selective_reencodes_audio_mp4_cannot_hold(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "audio", "pcm_s16le")]

        selective = MKV_TO_MP4.retries(streams)[0]

        assert "-c:a:0" in selective.options
        assert selective.options[selective.options.index("-c:a:0") + 1] == "aac"
        assert any("pcm_s16le" in note and "aac" in note for note in selective.notes)

    def test_selective_drops_bitmap_subtitles_with_a_note(self):
        streams = [
            Stream(0, "video", "h264"),
            Stream(1, "audio", "aac"),
            Stream(2, "subtitle", "hdmv_pgs_subtitle"),
        ]

        selective = MKV_TO_MP4.retries(streams)[0]

        assert "-map" in selective.options
        assert "0:2" not in selective.options
        assert any("dropped" in note and "hdmv_pgs_subtitle" in note for note in selective.notes)

    def test_selective_keeps_text_subtitles_as_mov_text(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "subtitle", "subrip")]

        selective = MKV_TO_MP4.retries(streams)[0]

        assert "-c:s:0" in selective.options
        assert selective.options[selective.options.index("-c:s:0") + 1] == "mov_text"

    def test_selective_drops_attachments_with_a_note(self):
        """Delta 1: the note now names the codec too."""
        streams = [Stream(0, "video", "h264"), Stream(1, "attachment", "ttf")]

        selective = MKV_TO_MP4.retries(streams)[0]

        assert "0:1" not in selective.options
        assert selective.notes == ("attachment stream 1 (ttf) dropped: not supported by MP4",)

    def test_output_specifiers_count_per_type_in_map_order(self):
        """Interleaved streams must still yield -c:a:0 and -c:a:1, not -c:a:1/-c:a:3."""
        streams = [
            Stream(0, "video", "h264"),
            Stream(1, "audio", "aac"),
            Stream(2, "subtitle", "subrip"),
            Stream(3, "audio", "flac"),
        ]

        selective = MKV_TO_MP4.retries(streams)[0]

        assert "-c:a:0" in selective.options
        assert "-c:a:1" in selective.options
        assert "-c:a:2" not in selective.options
        assert "-c:v:0" in selective.options
        assert "-c:s:0" in selective.options

    def test_no_mappable_stream_skips_straight_to_reencode(self):
        attempts = MKV_TO_MP4.retries([Stream(0, "attachment", "ttf")])

        assert [a.label for a in attempts] == ["re-encode"]

    def test_reencode_states_what_it_sacrifices(self):
        reencode = MKV_TO_MP4.retries([])[-1]

        assert "libx264" in reencode.options
        assert "aac" in reencode.options
        assert reencode.notes
        assert any("lossy" in note for note in reencode.notes)


class TestMp4DegradationNotes:
    """Verification (spec-profile-registry): one test per degradation branch,
    each pinning the exact note -- stream index, that stream's codec, and what
    was given up (docs/design/stream-decision.md)."""

    def test_video_reencode_note_is_exact(self):
        streams = [Stream(0, "video", "vp8"), Stream(1, "audio", "aac")]

        selective = MKV_TO_MP4.retries(streams)[0]

        assert selective.notes == ("video stream 0 (vp8) re-encoded to h264",)

    def test_audio_reencode_note_is_exact(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "audio", "pcm_s16le")]

        selective = MKV_TO_MP4.retries(streams)[0]

        assert selective.notes == ("audio stream 1 (pcm_s16le) re-encoded to aac",)

    def test_bitmap_subtitle_drop_note_is_exact(self):
        streams = [
            Stream(0, "video", "h264"),
            Stream(1, "audio", "aac"),
            Stream(2, "subtitle", "hdmv_pgs_subtitle"),
        ]

        selective = MKV_TO_MP4.retries(streams)[0]

        assert selective.notes == (
            "subtitle stream 2 (hdmv_pgs_subtitle) dropped: "
            "bitmap subtitles cannot be stored in MP4",
        )

    def test_last_resort_notes_are_pinned(self):
        """The two notes are the last-resort attempt's own data (Verification:
        'lossy re-encode; 10-bit/HDR reduced to 8-bit'), not engine wording."""
        reencode = MKV_TO_MP4.retries([])[-1]

        assert reencode.notes == (
            "re-encoded to h264/aac (lossy); subtitles and extra video streams dropped",
            "10-bit or HDR sources are reduced to 8-bit yuv420p for player compatibility",
        )


class TestProfileArgvPinning:
    """Verification: the full argv each profile builds, pinned byte-for-byte
    (docs/specs/spec-profile-registry.md)."""

    def test_mp4_copyable_source(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "audio", "aac")]
        selective = MKV_TO_MP4.retries(streams)[0]

        argv = build_argv("ffmpeg", "in.mkv", selective.options, "out.mp4")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.mkv",
            "-map",
            "0:0",
            "-map",
            "0:1",
            "-c:v:0",
            "copy",
            "-c:a:0",
            "copy",
            "-movflags",
            "+faststart",
            "out.mp4",
        ]

    def test_mp4_non_copyable_source(self):
        streams = [Stream(0, "video", "vp8"), Stream(1, "audio", "pcm_s16le")]
        selective = MKV_TO_MP4.retries(streams)[0]

        argv = build_argv("ffmpeg", "in.mkv", selective.options, "out.mp4")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.mkv",
            "-map",
            "0:0",
            "-map",
            "0:1",
            "-c:v:0",
            "libx264",
            "-crf:v:0",
            "18",
            "-c:a:0",
            "aac",
            "-b:a:0",
            "192k",
            "-movflags",
            "+faststart",
            "out.mp4",
        ]

    def test_wav_single_audio_source(self):
        argv = build_argv("ffmpeg", "in.opus", OPUS_TO_WAV.first_attempt().options, "out.wav")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.opus",
            "-map",
            "0:a:0",
            "-c:a",
            "pcm_s16le",
            "out.wav",
        ]

    def test_wav_two_audio_source(self):
        streams = [Stream(0, "audio", "opus"), Stream(1, "audio", "opus")]
        selective = OPUS_TO_WAV.retries(streams)[0]

        argv = build_argv("ffmpeg", "in.opus", selective.options, "out.wav")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.opus",
            "-map",
            "0:0",
            "-c:a",
            "pcm_s16le",
            "out.wav",
        ]


@pytest.mark.parametrize(
    "attempt",
    [MKV_TO_MP4.first_attempt(), *MKV_TO_MP4.retries([Stream(0, "video", "h264")])],
)
def test_every_attempt_produces_a_wellformed_command(attempt):
    argv = build_argv("ffmpeg", "in.mkv", attempt.options, "out.mp4")

    assert argv[0] == "ffmpeg"
    assert argv[-1] == "out.mp4"
    assert options_of(argv, "in.mkv", "out.mp4") == list(attempt.options)

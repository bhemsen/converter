"""Tests for the ffmpeg command lines we build, without running ffmpeg."""

import subprocess

import pytest

from converter import ffmpegtool
from converter.ffmpegtool import Stream, build_argv, cli_path
from converter.jobs import (
    MKV_TO_MP4,
    OPUS_TO_WAV,
    mp4_remux,
    mp4_retries,
    wav_pcm,
    wav_retries,
)


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
        attempt = wav_pcm()

        assert attempt.options == ("-map", "0:a:0", "-c:a", "pcm_s16le")
        assert attempt.notes == ()

    def test_single_audio_stream_needs_no_fallback(self):
        streams = [Stream(0, "audio", "opus")]

        assert wav_retries(streams) == []

    def test_multiple_audio_streams_fall_back_to_the_first(self):
        streams = [Stream(0, "audio", "opus"), Stream(1, "audio", "opus")]

        attempts = wav_retries(streams)

        assert len(attempts) == 1
        assert attempts[0].options == ("-map", "0:0", "-c:a", "pcm_s16le")
        assert "kept stream 0" in attempts[0].notes[0]

    def test_job_metadata(self):
        assert OPUS_TO_WAV.suffixes == (".opus",)
        assert OPUS_TO_WAV.target_suffix == ".wav"


class TestMp4Remux:
    def test_stream_copies_and_converts_text_subtitles(self):
        options = mp4_remux().options

        assert "-c" in options
        assert options[options.index("-c") + 1] == "copy"
        assert "mov_text" in options
        assert "+faststart" in options

    def test_does_not_use_bare_map_zero(self):
        """'-map 0' also selects MKV attachments and data streams, which MP4
        cannot hold, so a remuxable file would fail for no good reason."""
        options = list(mp4_remux().options)
        mapped = [options[i + 1] for i, flag in enumerate(options) if flag == "-map"]

        assert "0" not in mapped
        assert mapped == ["0:v?", "0:a?", "0:s?"]

    def test_job_metadata(self):
        assert MKV_TO_MP4.suffixes == (".mkv",)
        assert MKV_TO_MP4.target_suffix == ".mp4"
        assert MKV_TO_MP4.first_attempt() == mp4_remux()


class TestMp4Retries:
    def test_ladder_ends_with_a_full_reencode(self):
        attempts = mp4_retries([Stream(0, "video", "h264")])

        assert [a.label for a in attempts] == ["selective", "re-encode"]

    def test_selective_copies_compatible_streams(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "audio", "aac")]

        selective = mp4_retries(streams)[0]

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

        selective = mp4_retries(streams)[0]

        assert "-c:a:0" in selective.options
        assert selective.options[selective.options.index("-c:a:0") + 1] == "aac"
        assert any("pcm_s16le" in note and "aac" in note for note in selective.notes)

    def test_selective_drops_bitmap_subtitles_with_a_note(self):
        streams = [
            Stream(0, "video", "h264"),
            Stream(1, "audio", "aac"),
            Stream(2, "subtitle", "hdmv_pgs_subtitle"),
        ]

        selective = mp4_retries(streams)[0]

        assert "-map" in selective.options
        assert "0:2" not in selective.options
        assert any("dropped" in note and "hdmv_pgs_subtitle" in note for note in selective.notes)

    def test_selective_keeps_text_subtitles_as_mov_text(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "subtitle", "subrip")]

        selective = mp4_retries(streams)[0]

        assert "-c:s:0" in selective.options
        assert selective.options[selective.options.index("-c:s:0") + 1] == "mov_text"

    def test_selective_drops_attachments_with_a_note(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "attachment", "ttf")]

        selective = mp4_retries(streams)[0]

        assert "0:1" not in selective.options
        assert any("attachment" in note for note in selective.notes)

    def test_output_specifiers_count_per_type_in_map_order(self):
        """Interleaved streams must still yield -c:a:0 and -c:a:1, not -c:a:1/-c:a:3."""
        streams = [
            Stream(0, "video", "h264"),
            Stream(1, "audio", "aac"),
            Stream(2, "subtitle", "subrip"),
            Stream(3, "audio", "flac"),
        ]

        selective = mp4_retries(streams)[0]

        assert "-c:a:0" in selective.options
        assert "-c:a:1" in selective.options
        assert "-c:a:2" not in selective.options
        assert "-c:v:0" in selective.options
        assert "-c:s:0" in selective.options

    def test_no_mappable_stream_skips_straight_to_reencode(self):
        attempts = mp4_retries([Stream(0, "attachment", "ttf")])

        assert [a.label for a in attempts] == ["re-encode"]

    def test_reencode_states_what_it_sacrifices(self):
        reencode = mp4_retries([])[-1]

        assert "libx264" in reencode.options
        assert "aac" in reencode.options
        assert reencode.notes
        assert any("lossy" in note for note in reencode.notes)


@pytest.mark.parametrize("attempt", [mp4_remux(), *mp4_retries([Stream(0, "video", "h264")])])
def test_every_attempt_produces_a_wellformed_command(attempt):
    argv = build_argv("ffmpeg", "in.mkv", attempt.options, "out.mp4")

    assert argv[0] == "ffmpeg"
    assert argv[-1] == "out.mp4"
    assert options_of(argv, "in.mkv", "out.mp4") == list(attempt.options)

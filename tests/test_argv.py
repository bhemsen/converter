"""Tests for the ffmpeg command lines we build, without running ffmpeg."""

import subprocess
from dataclasses import replace
from typing import ClassVar

import pytest

from converter import ffmpegtool, jobs
from converter.ffmpegtool import Stream, build_argv, cli_path
from converter.profiles import (
    AVIF,
    BMP,
    FLAC,
    GIF,
    JPG,
    M4A,
    MKV,
    MOV,
    MP3,
    MP4,
    OGG,
    OPUS,
    PNG,
    TIFF,
    WAV,
    WEBM,
    WEBP,
    Attempt,
    Profile,
    StreamRule,
    flags,
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
        attempt = jobs.first_attempt(WAV)

        assert attempt.options == ("-map", "0:a:0", "-c:a", "pcm_s16le")
        assert attempt.notes == ()

    def test_single_audio_stream_needs_no_fallback(self):
        streams = [Stream(0, "audio", "opus")]

        assert jobs.retries(WAV, streams) == []

    def test_multiple_audio_streams_fall_back_to_a_selective_rung(self):
        """Deltas 2 and 3: the note names the dropped stream and its codec, and
        the engine-built rung is labelled 'selective' rather than
        'first-audio-stream'. The argv is unchanged."""
        streams = [Stream(0, "audio", "opus"), Stream(1, "audio", "opus")]

        attempts = jobs.retries(WAV, streams)

        assert len(attempts) == 1
        assert attempts[0].label == "selective"
        assert attempts[0].options == ("-map", "0:0", "-c:a", "pcm_s16le")
        assert attempts[0].notes == ("audio stream 1 (opus) dropped: WAV holds 1 audio stream",)

    def test_non_audio_stream_gains_a_selective_rung_on_the_failure_path(self):
        """Delta 4: an embedded cover-art stream used to produce no retry at
        all; it now reaches a selective rung that drops it with a note."""
        streams = [Stream(0, "audio", "opus"), Stream(1, "video", "mjpeg")]

        attempts = jobs.retries(WAV, streams)

        assert len(attempts) == 1
        assert attempts[0].label == "selective"
        assert attempts[0].options == ("-map", "0:0", "-c:a", "pcm_s16le")
        assert attempts[0].notes == ("video stream 1 (mjpeg) dropped: not supported by WAV",)

    def test_target_suffix(self):
        assert WAV.target_suffix == ".wav"

    def test_pcm_reencode_of_the_kept_stream_carries_no_note(self):
        """Decoding to PCM is WAV's own definition, not a loss (Verification,
        spec-profile-registry): the kept stream takes the fallback branch --
        WAV's copy mask is empty by construction -- yet contributes no note.
        Only the surplus stream's drop is reported."""
        streams = [Stream(0, "audio", "opus"), Stream(1, "audio", "opus")]

        attempts = jobs.retries(WAV, streams)

        assert len(attempts[0].notes) == 1
        assert not any("stream 0" in note for note in attempts[0].notes)


class TestMp3Job:
    """Issue #21, `docs/specs/archive/spec-audio-formats.md`: mp3's cheap attempt maps
    audio *blindly*, unlike WAV's index-explicit one, so unlike WAV a fully
    compatible single-stream source still gets a selective rung -- the same
    shape MP4 has (`TestMp4Retries.test_selective_copies_compatible_streams`)."""

    def test_first_attempt_carries_the_standing_note(self):
        attempt = jobs.first_attempt(MP3)

        assert attempt.options == ("-map", "0:a?", "-c:a", "copy")
        assert attempt.notes == (
            "non-audio streams, including cover art, are not carried into MP3",
        )

    def test_single_mp3_stream_reaches_a_selective_copy(self):
        streams = [Stream(0, "audio", "mp3")]

        attempts = jobs.retries(MP3, streams)

        assert [a.label for a in attempts] == ["selective", "re-encode"]
        assert attempts[0].options == ("-map", "0:0", "-c:a", "copy")
        assert attempts[0].notes == ()

    def test_non_mp3_audio_reencodes_with_a_note(self):
        streams = [Stream(0, "audio", "aac")]

        selective = jobs.retries(MP3, streams)[0]

        assert selective.options == ("-map", "0:0", "-c:a", "libmp3lame", "-q:a", "2")
        assert selective.notes == ("audio stream 0 (aac) re-encoded to mp3",)

    def test_second_audio_stream_is_dropped_by_the_muxer_enforced_limit(self):
        """The mp3 muxer -- not the blind mapping -- is what makes a second
        stream fail, so the drop is named on the failure-side selective rung,
        the same shape WAV's own second-audio-stream drop has."""
        streams = [Stream(0, "audio", "mp3"), Stream(1, "audio", "mp3")]

        selective = jobs.retries(MP3, streams)[0]

        assert selective.options == ("-map", "0:0", "-c:a", "copy")
        assert selective.notes == ("audio stream 1 (mp3) dropped: MP3 holds 1 audio stream",)

    def test_video_only_source_skips_straight_to_the_last_resort(self):
        attempts = jobs.retries(MP3, [Stream(0, "video", "h264")])

        assert [a.label for a in attempts] == ["re-encode"]

    def test_video_stream_alongside_audio_is_dropped_with_a_note(self):
        """No audio profile declares a video rule (spec-audio-formats.md), so
        a video stream -- cover art included -- is always structurally
        unsupported, named the same way MP4 names an attachment it has no
        rule for."""
        streams = [Stream(0, "audio", "mp3"), Stream(1, "video", "h264")]

        selective = jobs.retries(MP3, streams)[0]

        assert selective.notes == ("video stream 1 (h264) dropped: not supported by MP3",)

    def test_last_resort_notes_are_pinned(self):
        """The explicit-index last resort cannot name a per-stream drop itself
        (unlike the selective rung), so what it gives up has to be its own
        declared note -- the only place that information exists."""
        reencode = jobs.retries(MP3, [])[-1]

        assert reencode.notes == (
            "non-audio streams, and any audio stream beyond the first, are not carried into MP3",
        )

    def test_target_suffix(self):
        assert MP3.target_suffix == ".mp3"


class TestFlacJob:
    """Issue #21, `docs/specs/archive/spec-audio-formats.md`: same blind-mapping shape
    as `MP3`, but flac's fallback carries no `fallback_name`, so a re-encode
    into flac itself is never reported as a loss."""

    def test_first_attempt_carries_the_standing_note(self):
        attempt = jobs.first_attempt(FLAC)

        assert attempt.options == ("-map", "0:a?", "-c:a", "copy")
        assert attempt.notes == (
            "non-audio streams, including cover art, are not carried into FLAC",
        )

    def test_single_flac_stream_reaches_a_selective_copy(self):
        streams = [Stream(0, "audio", "flac")]

        attempts = jobs.retries(FLAC, streams)

        assert [a.label for a in attempts] == ["selective", "re-encode"]
        assert attempts[0].options == ("-map", "0:0", "-c:a", "copy")
        assert attempts[0].notes == ()

    def test_non_flac_audio_reencodes_with_no_note(self):
        """Verification (spec-audio-formats.md): converting into flac emits no
        note for the encode itself -- decoding into a lossless container's own
        codec is not a loss, the same rule WAV's PCM fallback carries."""
        streams = [Stream(0, "audio", "pcm_s16le")]

        selective = jobs.retries(FLAC, streams)[0]

        assert selective.options == ("-map", "0:0", "-c:a", "flac")
        assert selective.notes == ()

    def test_second_audio_stream_is_dropped_by_the_muxer_enforced_limit(self):
        streams = [Stream(0, "audio", "flac"), Stream(1, "audio", "flac")]

        selective = jobs.retries(FLAC, streams)[0]

        assert selective.options == ("-map", "0:0", "-c:a", "copy")
        assert selective.notes == ("audio stream 1 (flac) dropped: FLAC holds 1 audio stream",)

    def test_video_only_source_skips_straight_to_the_last_resort(self):
        attempts = jobs.retries(FLAC, [Stream(0, "video", "h264")])

        assert [a.label for a in attempts] == ["re-encode"]

    def test_video_stream_alongside_audio_is_dropped_with_a_note(self):
        streams = [Stream(0, "audio", "flac"), Stream(1, "video", "h264")]

        selective = jobs.retries(FLAC, streams)[0]

        assert selective.notes == ("video stream 1 (h264) dropped: not supported by FLAC",)

    def test_last_resort_notes_are_pinned(self):
        """Unlike its `StreamRule.fallback_name=None`, the last resort still
        needs its own note: it is an explicit-index attempt, so it cannot name
        a per-stream drop the way the selective rung does."""
        reencode = jobs.retries(FLAC, [])[-1]

        assert reencode.notes == (
            "non-audio streams, and any audio stream beyond the first, are not carried into FLAC",
        )

    def test_target_suffix(self):
        assert FLAC.target_suffix == ".flac"


class TestM4aJob:
    """Issue #22, `docs/specs/archive/spec-audio-formats.md`: same blind-mapping shape
    as `MP3`/`FLAC`, but `m4a` declares no `stream_limit` -- the ipod muxer
    holds several audio streams, so every one the source has is carried."""

    def test_first_attempt_carries_the_standing_note(self):
        attempt = jobs.first_attempt(M4A)

        assert attempt.options == ("-map", "0:a?", "-c:a", "copy")
        assert attempt.notes == (
            "non-audio streams, including cover art, are not carried into M4A",
        )

    def test_single_matching_stream_reaches_a_selective_copy(self):
        streams = [Stream(0, "audio", "aac")]

        attempts = jobs.retries(M4A, streams)

        assert [a.label for a in attempts] == ["selective", "re-encode"]
        assert attempts[0].options == ("-map", "0:0", "-c:a:0", "copy")
        assert attempts[0].notes == ()

    def test_non_matching_audio_reencodes_with_a_note(self):
        streams = [Stream(0, "audio", "mp3")]

        selective = jobs.retries(M4A, streams)[0]

        assert selective.options == ("-map", "0:0", "-c:a:0", "aac", "-b:a:0", "192k")
        assert selective.notes == ("audio stream 0 (mp3) re-encoded to aac",)

    def test_second_matching_audio_stream_is_also_carried(self):
        """Unlike mp3/flac's muxer-enforced limit, m4a declares none: a
        second aac/alac stream is copied too, not dropped."""
        streams = [Stream(0, "audio", "aac"), Stream(1, "audio", "alac")]

        selective = jobs.retries(M4A, streams)[0]

        assert selective.options == (
            "-map",
            "0:0",
            "-map",
            "0:1",
            "-c:a:0",
            "copy",
            "-c:a:1",
            "copy",
        )
        assert selective.notes == ()

    def test_mixed_accept_and_fallback_streams_each_take_their_own_fate(self):
        """The position placeholder is what makes this safe: ffmpeg's
        unindexed "-c:a" is not positional (measured against ffmpeg 9.0) --
        without "{n}", the second "-c:a" given would win for *both* output
        streams, silently re-encoding the one that should have been copied."""
        streams = [Stream(0, "audio", "aac"), Stream(1, "audio", "mp3")]

        selective = jobs.retries(M4A, streams)[0]

        assert selective.options == (
            "-map",
            "0:0",
            "-map",
            "0:1",
            "-c:a:0",
            "copy",
            "-c:a:1",
            "aac",
            "-b:a:1",
            "192k",
        )
        assert selective.notes == ("audio stream 1 (mp3) re-encoded to aac",)

    def test_video_only_source_skips_straight_to_the_last_resort(self):
        attempts = jobs.retries(M4A, [Stream(0, "video", "h264")])

        assert [a.label for a in attempts] == ["re-encode"]

    def test_video_stream_alongside_audio_is_dropped_with_a_note(self):
        streams = [Stream(0, "audio", "aac"), Stream(1, "video", "h264")]

        selective = jobs.retries(M4A, streams)[0]

        assert selective.notes == ("video stream 1 (h264) dropped: not supported by M4A",)

    def test_last_resort_notes_are_pinned(self):
        reencode = jobs.retries(M4A, [])[-1]

        assert reencode.notes == (
            "non-audio streams, and any audio stream beyond the first, are not carried into M4A",
        )

    def test_target_suffix(self):
        assert M4A.target_suffix == ".m4a"


class TestOggJob:
    """Issue #22, `docs/specs/archive/spec-audio-formats.md`: same shape as `M4A`,
    with a wider copy mask and no stream limit either -- the ogg muxer holds
    several audio streams too."""

    def test_first_attempt_carries_the_standing_note(self):
        attempt = jobs.first_attempt(OGG)

        assert attempt.options == ("-map", "0:a?", "-c", "copy")
        assert attempt.notes == (
            "non-audio streams, including cover art, are not carried into OGG",
        )

    def test_single_matching_stream_reaches_a_selective_copy(self):
        streams = [Stream(0, "audio", "vorbis")]

        attempts = jobs.retries(OGG, streams)

        assert [a.label for a in attempts] == ["selective", "re-encode"]
        assert attempts[0].options == ("-map", "0:0", "-c:a:0", "copy")
        assert attempts[0].notes == ()

    def test_non_matching_audio_reencodes_with_a_note(self):
        """The ogg muxer rejects mp3 and aac (docs/specs/archive/spec-audio-formats.md)."""
        streams = [Stream(0, "audio", "aac")]

        selective = jobs.retries(OGG, streams)[0]

        assert selective.options == ("-map", "0:0", "-c:a:0", "libvorbis", "-q:a:0", "5")
        assert selective.notes == ("audio stream 0 (aac) re-encoded to vorbis",)

    def test_second_matching_audio_stream_is_also_carried(self):
        streams = [Stream(0, "audio", "vorbis"), Stream(1, "audio", "opus")]

        selective = jobs.retries(OGG, streams)[0]

        assert selective.options == (
            "-map",
            "0:0",
            "-map",
            "0:1",
            "-c:a:0",
            "copy",
            "-c:a:1",
            "copy",
        )
        assert selective.notes == ()

    def test_mixed_accept_and_fallback_streams_each_take_their_own_fate(self):
        """See `TestM4aJob`'s equivalent test for why the placeholder matters."""
        streams = [Stream(0, "audio", "vorbis"), Stream(1, "audio", "aac")]

        selective = jobs.retries(OGG, streams)[0]

        assert selective.options == (
            "-map",
            "0:0",
            "-map",
            "0:1",
            "-c:a:0",
            "copy",
            "-c:a:1",
            "libvorbis",
            "-q:a:1",
            "5",
        )
        assert selective.notes == ("audio stream 1 (aac) re-encoded to vorbis",)

    def test_video_only_source_skips_straight_to_the_last_resort(self):
        attempts = jobs.retries(OGG, [Stream(0, "video", "h264")])

        assert [a.label for a in attempts] == ["re-encode"]

    def test_video_stream_alongside_audio_is_dropped_with_a_note(self):
        streams = [Stream(0, "audio", "vorbis"), Stream(1, "video", "h264")]

        selective = jobs.retries(OGG, streams)[0]

        assert selective.notes == ("video stream 1 (h264) dropped: not supported by OGG",)

    def test_last_resort_notes_are_pinned(self):
        reencode = jobs.retries(OGG, [])[-1]

        assert reencode.notes == (
            "non-audio streams, and any audio stream beyond the first, are not carried into OGG",
        )

    def test_target_suffix(self):
        assert OGG.target_suffix == ".ogg"


class TestOpusJob:
    """Issue #22, `docs/specs/archive/spec-audio-formats.md`: `opus` copies on the
    happy path even though its own muxer also accepts a Vorbis stream (Prior
    decisions) -- the mask below governs only the failure-side selective rung,
    where a Vorbis stream is re-encoded rather than copied."""

    def test_first_attempt_carries_the_standing_note(self):
        attempt = jobs.first_attempt(OPUS)

        assert attempt.options == ("-map", "0:a?", "-c", "copy")
        assert attempt.notes == (
            "non-audio streams, including cover art, are not carried into OPUS",
        )

    def test_single_matching_stream_reaches_a_selective_copy(self):
        streams = [Stream(0, "audio", "opus")]

        attempts = jobs.retries(OPUS, streams)

        assert [a.label for a in attempts] == ["selective", "re-encode"]
        assert attempts[0].options == ("-map", "0:0", "-c:a:0", "copy")
        assert attempts[0].notes == ()

    def test_non_matching_audio_reencodes_with_a_note(self):
        """A Vorbis stream is accepted by the opus muxer itself but not by
        the mask, so the selective rung re-encodes it rather than shipping a
        `.opus` file that is secretly Vorbis."""
        streams = [Stream(0, "audio", "vorbis")]

        selective = jobs.retries(OPUS, streams)[0]

        assert selective.options == ("-map", "0:0", "-c:a:0", "libopus", "-b:a:0", "128k")
        assert selective.notes == ("audio stream 0 (vorbis) re-encoded to opus",)

    def test_second_matching_audio_stream_is_also_carried(self):
        streams = [Stream(0, "audio", "opus"), Stream(1, "audio", "opus")]

        selective = jobs.retries(OPUS, streams)[0]

        assert selective.options == (
            "-map",
            "0:0",
            "-map",
            "0:1",
            "-c:a:0",
            "copy",
            "-c:a:1",
            "copy",
        )
        assert selective.notes == ()

    def test_mixed_accept_and_fallback_streams_each_take_their_own_fate(self):
        """See `TestM4aJob`'s equivalent test for why the placeholder matters
        -- and, for `opus`, the specific reason the spec's original bare-form
        pin was amended after this was measured against ffmpeg 9.0."""
        streams = [Stream(0, "audio", "opus"), Stream(1, "audio", "vorbis")]

        selective = jobs.retries(OPUS, streams)[0]

        assert selective.options == (
            "-map",
            "0:0",
            "-map",
            "0:1",
            "-c:a:0",
            "copy",
            "-c:a:1",
            "libopus",
            "-b:a:1",
            "128k",
        )
        assert selective.notes == ("audio stream 1 (vorbis) re-encoded to opus",)

    def test_video_only_source_skips_straight_to_the_last_resort(self):
        attempts = jobs.retries(OPUS, [Stream(0, "video", "h264")])

        assert [a.label for a in attempts] == ["re-encode"]

    def test_video_stream_alongside_audio_is_dropped_with_a_note(self):
        streams = [Stream(0, "audio", "opus"), Stream(1, "video", "h264")]

        selective = jobs.retries(OPUS, streams)[0]

        assert selective.notes == ("video stream 1 (h264) dropped: not supported by OPUS",)

    def test_last_resort_notes_are_pinned(self):
        reencode = jobs.retries(OPUS, [])[-1]

        assert reencode.notes == (
            "non-audio streams, and any audio stream beyond the first, are not carried into OPUS",
        )

    def test_target_suffix(self):
        assert OPUS.target_suffix == ".opus"


class TestMp4Remux:
    def test_stream_copies_and_converts_text_subtitles(self):
        options = jobs.first_attempt(MP4).options

        assert "-c" in options
        assert options[options.index("-c") + 1] == "copy"
        assert "mov_text" in options
        assert "+faststart" in options

    def test_does_not_use_bare_map_zero(self):
        """'-map 0' also selects MKV attachments and data streams, which MP4
        cannot hold, so a remuxable file would fail for no good reason."""
        options = list(jobs.first_attempt(MP4).options)
        mapped = [options[i + 1] for i, flag in enumerate(options) if flag == "-map"]

        assert "0" not in mapped
        assert mapped == ["0:v?", "0:a?", "0:s?"]

    def test_target_suffix(self):
        assert MP4.target_suffix == ".mp4"
        assert jobs.first_attempt(MP4).options == (
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
        attempts = jobs.retries(MP4, [Stream(0, "video", "h264")])

        assert [a.label for a in attempts] == ["selective", "re-encode"]

    def test_selective_copies_compatible_streams(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "audio", "aac")]

        selective = jobs.retries(MP4, streams)[0]

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

        selective = jobs.retries(MP4, streams)[0]

        assert "-c:a:0" in selective.options
        assert selective.options[selective.options.index("-c:a:0") + 1] == "aac"
        assert any("pcm_s16le" in note and "aac" in note for note in selective.notes)

    def test_selective_drops_bitmap_subtitles_with_a_note(self):
        streams = [
            Stream(0, "video", "h264"),
            Stream(1, "audio", "aac"),
            Stream(2, "subtitle", "hdmv_pgs_subtitle"),
        ]

        selective = jobs.retries(MP4, streams)[0]

        assert "-map" in selective.options
        assert "0:2" not in selective.options
        assert any("dropped" in note and "hdmv_pgs_subtitle" in note for note in selective.notes)

    def test_selective_keeps_text_subtitles_as_mov_text(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "subtitle", "subrip")]

        selective = jobs.retries(MP4, streams)[0]

        assert "-c:s:0" in selective.options
        assert selective.options[selective.options.index("-c:s:0") + 1] == "mov_text"

    def test_selective_drops_attachments_with_a_note(self):
        """Delta 1: the note now names the codec too."""
        streams = [Stream(0, "video", "h264"), Stream(1, "attachment", "ttf")]

        selective = jobs.retries(MP4, streams)[0]

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

        selective = jobs.retries(MP4, streams)[0]

        assert "-c:a:0" in selective.options
        assert "-c:a:1" in selective.options
        assert "-c:a:2" not in selective.options
        assert "-c:v:0" in selective.options
        assert "-c:s:0" in selective.options

    def test_no_mappable_stream_skips_straight_to_reencode(self):
        attempts = jobs.retries(MP4, [Stream(0, "attachment", "ttf")])

        assert [a.label for a in attempts] == ["re-encode"]

    def test_reencode_states_what_it_sacrifices(self):
        reencode = jobs.retries(MP4, [])[-1]

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

        selective = jobs.retries(MP4, streams)[0]

        assert selective.notes == ("video stream 0 (vp8) re-encoded to h264",)

    def test_audio_reencode_note_is_exact(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "audio", "pcm_s16le")]

        selective = jobs.retries(MP4, streams)[0]

        assert selective.notes == ("audio stream 1 (pcm_s16le) re-encoded to aac",)

    def test_bitmap_subtitle_drop_note_is_exact(self):
        streams = [
            Stream(0, "video", "h264"),
            Stream(1, "audio", "aac"),
            Stream(2, "subtitle", "hdmv_pgs_subtitle"),
        ]

        selective = jobs.retries(MP4, streams)[0]

        assert selective.notes == (
            "subtitle stream 2 (hdmv_pgs_subtitle) dropped: "
            "bitmap subtitles cannot be stored in MP4",
        )

    def test_last_resort_notes_are_pinned(self):
        """The two notes are the last-resort attempt's own data (Verification:
        'lossy re-encode; 10-bit/HDR reduced to 8-bit'), not engine wording."""
        reencode = jobs.retries(MP4, [])[-1]

        assert reencode.notes == (
            "re-encoded to h264/aac (lossy); subtitles and extra video streams dropped",
            "10-bit or HDR sources are reduced to 8-bit yuv420p for player compatibility",
        )


class TestMkvRemux:
    def test_maps_every_stream_type_including_attachments(self):
        options = jobs.first_attempt(MKV).options

        assert options == (
            "-map",
            "0:v?",
            "-map",
            "0:a?",
            "-map",
            "0:s?",
            "-map",
            "0:t?",
            "-c",
            "copy",
        )

    def test_does_not_use_bare_map_zero(self):
        """'-map 0' also selects data and timecode streams, which no
        "v/a/s/t" map carries into MKV either (measured), so a bare "-map 0"
        would only turn a remuxable file into a failure for no reason."""
        options = list(jobs.first_attempt(MKV).options)
        mapped = [options[i + 1] for i, flag in enumerate(options) if flag == "-map"]

        assert "0" not in mapped
        assert mapped == ["0:v?", "0:a?", "0:s?", "0:t?"]

    def test_target_suffix(self):
        assert MKV.target_suffix == ".mkv"


class TestMkvRetries:
    def test_ladder_ends_with_a_full_reencode(self):
        attempts = jobs.retries(MKV, [Stream(0, "video", "h264")])

        assert [a.label for a in attempts] == ["selective", "re-encode"]

    def test_selective_copies_compatible_streams(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "audio", "aac")]

        selective = jobs.retries(MKV, streams)[0]

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

    def test_selective_reencodes_video_mkv_cannot_hold(self):
        streams = [Stream(0, "video", "wmv3"), Stream(1, "audio", "aac")]

        selective = jobs.retries(MKV, streams)[0]

        assert "-c:v:0" in selective.options
        assert selective.options[selective.options.index("-c:v:0") + 1] == "libx264"
        assert selective.notes == ("video stream 0 (wmv3) re-encoded to h264",)

    def test_selective_reencodes_audio_mkv_cannot_hold(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "audio", "wmav2")]

        selective = jobs.retries(MKV, streams)[0]

        assert "-c:a:0" in selective.options
        assert selective.options[selective.options.index("-c:a:0") + 1] == "aac"
        assert selective.notes == ("audio stream 1 (wmav2) re-encoded to aac",)

    def test_selective_reencodes_mov_text_subtitle_to_srt(self):
        """Matroska rejects a literal mov_text copy (measured), so the cheap
        attempt's blanket '-c copy' fails on a mov_text source and the ladder
        reaches this rung -- exactly the branch the argv-pinning tests below
        cannot reach, since they only ever build the selective rung directly."""
        streams = [Stream(0, "video", "h264"), Stream(1, "subtitle", "mov_text")]

        selective = jobs.retries(MKV, streams)[0]

        assert "-c:s:0" in selective.options
        assert selective.options[selective.options.index("-c:s:0") + 1] == "srt"
        assert selective.notes == ("subtitle stream 1 (mov_text) re-encoded to subrip",)

    def test_selective_copies_an_attachment_whose_codec_name_is_unknown(self):
        """ffprobe reports a font/ttf or font/otf attachment's codec_name as
        "unknown" (measured), and MKV's attachment rule accepts it anyway."""
        streams = [Stream(0, "video", "h264"), Stream(1, "attachment", "unknown")]

        selective = jobs.retries(MKV, streams)[0]

        assert "-c:t:0" in selective.options
        assert selective.options[selective.options.index("-c:t:0") + 1] == "copy"
        assert selective.notes == ()

    def test_reencode_states_what_it_sacrifices(self):
        reencode = jobs.retries(MKV, [])[-1]

        assert "libx264" in reencode.options
        assert "aac" in reencode.options
        assert reencode.notes
        assert any("lossy" in note for note in reencode.notes)


class TestMkvDegradationNotes:
    """Verification (spec-video-formats): one test per degradation branch this
    profile introduces, each pinning the exact note."""

    def test_video_reencode_note_is_exact(self):
        streams = [Stream(0, "video", "wmv3"), Stream(1, "audio", "aac")]

        selective = jobs.retries(MKV, streams)[0]

        assert selective.notes == ("video stream 0 (wmv3) re-encoded to h264",)

    def test_audio_reencode_note_is_exact(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "audio", "wmav2")]

        selective = jobs.retries(MKV, streams)[0]

        assert selective.notes == ("audio stream 1 (wmav2) re-encoded to aac",)

    def test_subtitle_reencode_note_is_exact(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "subtitle", "mov_text")]

        selective = jobs.retries(MKV, streams)[0]

        assert selective.notes == ("subtitle stream 1 (mov_text) re-encoded to subrip",)

    def test_last_resort_notes_are_pinned(self):
        reencode = jobs.retries(MKV, [])[-1]

        assert reencode.notes == (
            "re-encoded to h264/aac (lossy); subtitles and extra video streams dropped",
            "10-bit or HDR sources are reduced to 8-bit yuv420p for player compatibility",
        )


class TestMovRemux:
    def test_maps_every_stream_type_including_attachments(self):
        """`0:t?` is mapped deliberately so an attachment-bearing source fails
        this attempt (Acceptance, spec-video-formats.md)."""
        options = jobs.first_attempt(MOV).options

        assert options == (
            "-map",
            "0:v?",
            "-map",
            "0:a?",
            "-map",
            "0:s?",
            "-map",
            "0:t?",
            "-c",
            "copy",
            "-c:s",
            "mov_text",
            "-movflags",
            "+faststart",
        )

    def test_does_not_use_bare_map_zero(self):
        options = list(jobs.first_attempt(MOV).options)
        mapped = [options[i + 1] for i, flag in enumerate(options) if flag == "-map"]

        assert "0" not in mapped
        assert mapped == ["0:v?", "0:a?", "0:s?", "0:t?"]

    def test_target_suffix(self):
        assert MOV.target_suffix == ".mov"


class TestMovRetries:
    def test_ladder_ends_with_a_full_reencode(self):
        attempts = jobs.retries(MOV, [Stream(0, "video", "h264")])

        assert [a.label for a in attempts] == ["selective", "re-encode"]

    def test_selective_copies_compatible_streams(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "audio", "aac")]

        selective = jobs.retries(MOV, streams)[0]

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

    def test_selective_reencodes_vp9_video_mov_cannot_hold(self):
        """The likeliest copy-paste mistake in the phase: MOV rejects vp9
        (and av1, and vp8) unlike MP4 (Acceptance, spec-video-formats.md)."""
        streams = [Stream(0, "video", "vp9"), Stream(1, "audio", "aac")]

        selective = jobs.retries(MOV, streams)[0]

        assert "-c:v:0" in selective.options
        assert selective.options[selective.options.index("-c:v:0") + 1] == "libx264"
        assert selective.notes == ("video stream 0 (vp9) re-encoded to h264",)

    def test_selective_reencodes_audio_mov_cannot_hold(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "audio", "opus")]

        selective = jobs.retries(MOV, streams)[0]

        assert "-c:a:0" in selective.options
        assert selective.options[selective.options.index("-c:a:0") + 1] == "aac"
        assert selective.notes == ("audio stream 1 (opus) re-encoded to aac",)

    def test_selective_transcodes_text_subtitle_to_mov_text(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "subtitle", "subrip")]

        selective = jobs.retries(MOV, streams)[0]

        assert "-c:s:0" in selective.options
        assert selective.options[selective.options.index("-c:s:0") + 1] == "mov_text"
        assert selective.notes == ()

    def test_selective_drops_bitmap_subtitles_with_a_note(self):
        streams = [
            Stream(0, "video", "h264"),
            Stream(1, "audio", "aac"),
            Stream(2, "subtitle", "hdmv_pgs_subtitle"),
        ]

        selective = jobs.retries(MOV, streams)[0]

        assert "0:2" not in selective.options
        assert selective.notes == (
            "subtitle stream 2 (hdmv_pgs_subtitle) dropped: "
            "bitmap subtitles cannot be stored in MOV",
        )

    def test_selective_drops_an_attachment_via_the_ladder_with_a_note(self):
        """The point of the phase: MOV has no `attachment` rule, so an
        attachment that reached the ladder (because the cheap attempt's
        mapped `0:t?` made MOV reject it outright) is dropped here with a
        real per-stream note instead of a blanket one."""
        streams = [Stream(0, "video", "h264"), Stream(1, "attachment", "unknown")]

        selective = jobs.retries(MOV, streams)[0]

        assert "0:1" not in selective.options
        assert selective.notes == ("attachment stream 1 (unknown) dropped: not supported by MOV",)

    def test_reencode_states_what_it_sacrifices(self):
        reencode = jobs.retries(MOV, [])[-1]

        assert "libx264" in reencode.options
        assert "aac" in reencode.options
        assert reencode.notes
        assert any("lossy" in note for note in reencode.notes)


class TestMovDegradationNotes:
    """Verification (spec-video-formats): one test per degradation branch this
    profile introduces, each pinning the exact note."""

    def test_video_reencode_note_is_exact(self):
        streams = [Stream(0, "video", "vp9"), Stream(1, "audio", "aac")]

        selective = jobs.retries(MOV, streams)[0]

        assert selective.notes == ("video stream 0 (vp9) re-encoded to h264",)

    def test_audio_reencode_note_is_exact(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "audio", "opus")]

        selective = jobs.retries(MOV, streams)[0]

        assert selective.notes == ("audio stream 1 (opus) re-encoded to aac",)

    def test_bitmap_subtitle_drop_note_is_exact(self):
        streams = [
            Stream(0, "video", "h264"),
            Stream(1, "audio", "aac"),
            Stream(2, "subtitle", "hdmv_pgs_subtitle"),
        ]

        selective = jobs.retries(MOV, streams)[0]

        assert selective.notes == (
            "subtitle stream 2 (hdmv_pgs_subtitle) dropped: "
            "bitmap subtitles cannot be stored in MOV",
        )

    def test_attachment_drop_note_is_exact(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "attachment", "unknown")]

        selective = jobs.retries(MOV, streams)[0]

        assert selective.notes == ("attachment stream 1 (unknown) dropped: not supported by MOV",)

    def test_last_resort_notes_are_pinned(self):
        reencode = jobs.retries(MOV, [])[-1]

        assert reencode.notes == (
            "re-encoded to h264/aac (lossy); subtitles and extra video streams dropped",
            "10-bit or HDR sources are reduced to 8-bit yuv420p for player compatibility",
        )


class TestWebmRemux:
    def test_maps_no_attachment(self):
        """Unlike MKV and MOV, WebM never maps `0:t?`: it does not reject a
        mapped attachment, it silently discards it at exit 0 (measured), so
        mapping it would buy nothing (Acceptance, spec-video-formats.md)."""
        options = jobs.first_attempt(WEBM).options

        assert options == (
            "-map",
            "0:v?",
            "-map",
            "0:a?",
            "-map",
            "0:s?",
            "-c",
            "copy",
            "-c:s",
            "webvtt",
        )

    def test_does_not_use_bare_map_zero(self):
        options = list(jobs.first_attempt(WEBM).options)
        mapped = [options[i + 1] for i, flag in enumerate(options) if flag == "-map"]

        assert "0" not in mapped
        assert mapped == ["0:v?", "0:a?", "0:s?"]

    def test_target_suffix(self):
        assert WEBM.target_suffix == ".webm"


class TestWebmRetries:
    def test_ladder_ends_with_a_full_reencode(self):
        attempts = jobs.retries(WEBM, [Stream(0, "video", "h264")])

        assert [a.label for a in attempts] == ["selective", "re-encode"]

    def test_selective_copies_compatible_streams(self):
        streams = [Stream(0, "video", "vp9"), Stream(1, "audio", "opus")]

        selective = jobs.retries(WEBM, streams)[0]

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

    def test_selective_reencodes_video_webm_cannot_hold(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "audio", "opus")]

        selective = jobs.retries(WEBM, streams)[0]

        assert "-c:v:0" in selective.options
        assert selective.options[selective.options.index("-c:v:0") + 1] == "libvpx-vp9"
        assert selective.notes == ("video stream 0 (h264) re-encoded to vp9",)

    def test_selective_reencodes_audio_webm_cannot_hold(self):
        streams = [Stream(0, "video", "vp9"), Stream(1, "audio", "aac")]

        selective = jobs.retries(WEBM, streams)[0]

        assert "-c:a:0" in selective.options
        assert selective.options[selective.options.index("-c:a:0") + 1] == "libopus"
        assert selective.notes == ("audio stream 1 (aac) re-encoded to opus",)

    def test_selective_transcodes_text_subtitle_to_webvtt(self):
        streams = [Stream(0, "video", "vp9"), Stream(1, "subtitle", "subrip")]

        selective = jobs.retries(WEBM, streams)[0]

        assert "-c:s:0" in selective.options
        assert selective.options[selective.options.index("-c:s:0") + 1] == "webvtt"
        assert selective.notes == ()

    def test_selective_drops_bitmap_subtitles_with_a_note(self):
        streams = [
            Stream(0, "video", "vp9"),
            Stream(1, "audio", "opus"),
            Stream(2, "subtitle", "hdmv_pgs_subtitle"),
        ]

        selective = jobs.retries(WEBM, streams)[0]

        assert "0:2" not in selective.options
        assert selective.notes == (
            "subtitle stream 2 (hdmv_pgs_subtitle) dropped: "
            "bitmap subtitles cannot be stored in WebM",
        )

    def test_selective_drops_an_attachment_with_no_rule(self):
        """WebM's cheap attempt never maps an attachment, so one only ever
        reaches the ladder if some other stream also failed the cheap
        attempt -- but the selective rung still has to account for it, and
        does, the same way MP4's does."""
        streams = [Stream(0, "video", "h264"), Stream(1, "attachment", "unknown")]

        selective = jobs.retries(WEBM, streams)[0]

        assert "0:1" not in selective.options
        assert selective.notes[-1] == "attachment stream 1 (unknown) dropped: not supported by WebM"

    def test_reencode_states_what_it_sacrifices(self):
        reencode = jobs.retries(WEBM, [])[-1]

        assert "libvpx-vp9" in reencode.options
        assert "libopus" in reencode.options
        assert reencode.notes
        assert any("lossy" in note for note in reencode.notes)


class TestWebmDegradationNotes:
    """Verification (spec-video-formats): one test per degradation branch this
    profile introduces, each pinning the exact note."""

    def test_video_reencode_note_is_exact(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "audio", "opus")]

        selective = jobs.retries(WEBM, streams)[0]

        assert selective.notes == ("video stream 0 (h264) re-encoded to vp9",)

    def test_audio_reencode_note_is_exact(self):
        streams = [Stream(0, "video", "vp9"), Stream(1, "audio", "aac")]

        selective = jobs.retries(WEBM, streams)[0]

        assert selective.notes == ("audio stream 1 (aac) re-encoded to opus",)

    def test_bitmap_subtitle_drop_note_is_exact(self):
        streams = [
            Stream(0, "video", "vp9"),
            Stream(1, "audio", "opus"),
            Stream(2, "subtitle", "hdmv_pgs_subtitle"),
        ]

        selective = jobs.retries(WEBM, streams)[0]

        assert selective.notes == (
            "subtitle stream 2 (hdmv_pgs_subtitle) dropped: "
            "bitmap subtitles cannot be stored in WebM",
        )

    def test_standing_note_names_attachments_data_and_timecode(self):
        assert jobs.first_attempt(WEBM).notes == (
            "attachments, data and timecode streams are not carried into WebM",
        )

    def test_attachment_drop_via_success_side_verification_is_exact(self):
        """WebM never maps an attachment, so a successful cheap attempt still
        leaves one behind; the success-side verifier (`jobs.verify_success`)
        names it per stream, alongside the standing note above -- the same
        mechanism MP4 already uses for its own attachment gap."""
        notes = jobs.verify_success(WEBM, [Stream(0, "attachment", "unknown")])

        assert notes == ("attachment stream 0 (unknown) dropped: not supported by WebM",)

    def test_last_resort_notes_are_pinned(self):
        reencode = jobs.retries(WEBM, [])[-1]

        assert reencode.notes == (
            "re-encoded to vp9/opus (lossy); subtitles and extra video streams dropped",
        )


class TestProfileArgvPinning:
    """Verification: the full argv each profile builds, pinned byte-for-byte
    (docs/specs/archive/spec-profile-registry.md)."""

    def test_mp4_copyable_source(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "audio", "aac")]
        selective = jobs.retries(MP4, streams)[0]

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
        selective = jobs.retries(MP4, streams)[0]

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
        argv = build_argv("ffmpeg", "in.opus", jobs.first_attempt(WAV).options, "out.wav")

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

    def test_mkv_copyable_source(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "audio", "aac")]
        selective = jobs.retries(MKV, streams)[0]

        argv = build_argv("ffmpeg", "in.mts", selective.options, "out.mkv")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.mts",
            "-map",
            "0:0",
            "-map",
            "0:1",
            "-c:v:0",
            "copy",
            "-c:a:0",
            "copy",
            "out.mkv",
        ]

    def test_mkv_non_copyable_source(self):
        streams = [Stream(0, "video", "wmv3"), Stream(1, "audio", "wmav2")]
        selective = jobs.retries(MKV, streams)[0]

        argv = build_argv("ffmpeg", "in.mts", selective.options, "out.mkv")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.mts",
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
            "out.mkv",
        ]

    def test_mov_copyable_source(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "audio", "aac")]
        selective = jobs.retries(MOV, streams)[0]

        argv = build_argv("ffmpeg", "in.mts", selective.options, "out.mov")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.mts",
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
            "out.mov",
        ]

    def test_mov_non_copyable_source(self):
        streams = [Stream(0, "video", "vp9"), Stream(1, "audio", "opus")]
        selective = jobs.retries(MOV, streams)[0]

        argv = build_argv("ffmpeg", "in.mts", selective.options, "out.mov")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.mts",
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
            "out.mov",
        ]

    def test_webm_copyable_source(self):
        streams = [Stream(0, "video", "vp9"), Stream(1, "audio", "opus")]
        selective = jobs.retries(WEBM, streams)[0]

        argv = build_argv("ffmpeg", "in.mkv", selective.options, "out.webm")

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
            "out.webm",
        ]

    def test_webm_non_copyable_source(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "audio", "aac")]
        selective = jobs.retries(WEBM, streams)[0]

        argv = build_argv("ffmpeg", "in.mkv", selective.options, "out.webm")

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
            "libvpx-vp9",
            "-crf:v:0",
            "32",
            "-b:v:0",
            "0",
            "-row-mt",
            "1",
            "-cpu-used",
            "4",
            "-c:a:0",
            "libopus",
            "-b:a:0",
            "128k",
            "out.webm",
        ]

    def test_wav_two_audio_source(self):
        streams = [Stream(0, "audio", "opus"), Stream(1, "audio", "opus")]
        selective = jobs.retries(WAV, streams)[0]

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

    def test_mp3_cheap_attempt(self):
        argv = build_argv("ffmpeg", "in.wav", jobs.first_attempt(MP3).options, "out.mp3")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.wav",
            "-map",
            "0:a?",
            "-c:a",
            "copy",
            "out.mp3",
        ]

    def test_flac_cheap_attempt(self):
        argv = build_argv("ffmpeg", "in.wav", jobs.first_attempt(FLAC).options, "out.flac")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.wav",
            "-map",
            "0:a?",
            "-c:a",
            "copy",
            "out.flac",
        ]

    def test_mp3_copyable_source(self):
        selective = jobs.retries(MP3, [Stream(0, "audio", "mp3")])[0]

        argv = build_argv("ffmpeg", "in.wav", selective.options, "out.mp3")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.wav",
            "-map",
            "0:0",
            "-c:a",
            "copy",
            "out.mp3",
        ]

    def test_mp3_non_copyable_source(self):
        selective = jobs.retries(MP3, [Stream(0, "audio", "aac")])[0]

        argv = build_argv("ffmpeg", "in.m4a", selective.options, "out.mp3")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.m4a",
            "-map",
            "0:0",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "2",
            "out.mp3",
        ]

    def test_flac_copyable_source(self):
        selective = jobs.retries(FLAC, [Stream(0, "audio", "flac")])[0]

        argv = build_argv("ffmpeg", "in.mkv", selective.options, "out.flac")

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
            "-c:a",
            "copy",
            "out.flac",
        ]

    def test_flac_non_copyable_source(self):
        """`--to flac` from a PCM source (Verification, spec-audio-formats.md):
        reaches the selective rung, not `mp3`/`flac`'s last-resort."""
        selective = jobs.retries(FLAC, [Stream(0, "audio", "pcm_s16le")])[0]

        argv = build_argv("ffmpeg", "in.wav", selective.options, "out.flac")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.wav",
            "-map",
            "0:0",
            "-c:a",
            "flac",
            "out.flac",
        ]

    def test_m4a_cheap_attempt(self):
        argv = build_argv("ffmpeg", "in.wav", jobs.first_attempt(M4A).options, "out.m4a")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.wav",
            "-map",
            "0:a?",
            "-c:a",
            "copy",
            "out.m4a",
        ]

    def test_m4a_copyable_source(self):
        selective = jobs.retries(M4A, [Stream(0, "audio", "aac")])[0]

        argv = build_argv("ffmpeg", "in.mkv", selective.options, "out.m4a")

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
            "-c:a:0",
            "copy",
            "out.m4a",
        ]

    def test_m4a_non_copyable_source(self):
        selective = jobs.retries(M4A, [Stream(0, "audio", "mp3")])[0]

        argv = build_argv("ffmpeg", "in.mp3", selective.options, "out.m4a")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.mp3",
            "-map",
            "0:0",
            "-c:a:0",
            "aac",
            "-b:a:0",
            "192k",
            "out.m4a",
        ]

    def test_ogg_cheap_attempt(self):
        argv = build_argv("ffmpeg", "in.wav", jobs.first_attempt(OGG).options, "out.ogg")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.wav",
            "-map",
            "0:a?",
            "-c",
            "copy",
            "out.ogg",
        ]

    def test_ogg_copyable_source(self):
        selective = jobs.retries(OGG, [Stream(0, "audio", "vorbis")])[0]

        argv = build_argv("ffmpeg", "in.mkv", selective.options, "out.ogg")

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
            "-c:a:0",
            "copy",
            "out.ogg",
        ]

    def test_ogg_non_copyable_source(self):
        selective = jobs.retries(OGG, [Stream(0, "audio", "aac")])[0]

        argv = build_argv("ffmpeg", "in.m4a", selective.options, "out.ogg")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.m4a",
            "-map",
            "0:0",
            "-c:a:0",
            "libvorbis",
            "-q:a:0",
            "5",
            "out.ogg",
        ]

    def test_opus_cheap_attempt(self):
        argv = build_argv("ffmpeg", "in.wav", jobs.first_attempt(OPUS).options, "out.opus")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.wav",
            "-map",
            "0:a?",
            "-c",
            "copy",
            "out.opus",
        ]

    def test_opus_copyable_source(self):
        selective = jobs.retries(OPUS, [Stream(0, "audio", "opus")])[0]

        argv = build_argv("ffmpeg", "in.ogg", selective.options, "out.opus")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.ogg",
            "-map",
            "0:0",
            "-c:a:0",
            "copy",
            "out.opus",
        ]

    def test_opus_non_copyable_source(self):
        """A Vorbis stream is accepted by the opus muxer itself but not the
        mask, so it is re-encoded rather than copied under a lying extension."""
        selective = jobs.retries(OPUS, [Stream(0, "audio", "vorbis")])[0]

        argv = build_argv("ffmpeg", "in.ogg", selective.options, "out.opus")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.ogg",
            "-map",
            "0:0",
            "-c:a:0",
            "libopus",
            "-b:a:0",
            "128k",
            "out.opus",
        ]


class TestImageProfileArgvPinning:
    """Verification (spec-image-formats.md): the full argv `png`, `jpg`, `tiff`
    and `bmp` build, pinned byte-for-byte, for a copyable and a non-copyable
    input each. png/jpg/tiff/bmp carry the same exception phase 3 recorded for
    `opus`: their cheap attempt never copies -- it always forces the encoder --
    so the copyable case exists only on the selective rung, reached here with a
    second video stream that trips the muxer-enforced `stream_limit=1` and
    forces the cheap attempt to fail."""

    def test_png_cheap_attempt_forces_the_encoder(self):
        argv = build_argv("ffmpeg", "in.jpg", jobs.first_attempt(PNG).options, "out.png")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.jpg",
            "-map",
            "0:v?",
            "-c:v",
            "png",
            "out.png",
        ]

    def test_png_copyable_source_on_the_selective_rung(self):
        streams = [Stream(0, "video", "png"), Stream(1, "video", "h264")]
        selective = jobs.retries(PNG, streams)[0]

        argv = build_argv("ffmpeg", "in.mkv", selective.options, "out.png")

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
            "-c:v",
            "copy",
            "out.png",
        ]
        assert selective.notes == ("video stream 1 (h264) dropped: PNG holds 1 video stream",)

    def test_png_non_copyable_source_on_the_selective_rung(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "video", "h264")]
        selective = jobs.retries(PNG, streams)[0]

        argv = build_argv("ffmpeg", "in.mkv", selective.options, "out.png")

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
            "-c:v",
            "png",
            "out.png",
        ]

    def test_png_last_resort_extracts_the_first_frame(self):
        streams = [Stream(0, "video", "h264")]
        last_resort = jobs.retries(PNG, streams)[-1]

        argv = build_argv("ffmpeg", "in.mp4", last_resort.options, "out.png")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.mp4",
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-c:v",
            "png",
            "out.png",
        ]
        assert last_resort.notes == (
            "only the first frame was kept; PNG cannot hold more than one image",
            "non-video streams, and any video stream beyond the first, are not carried into PNG",
        )

    def test_jpg_cheap_attempt_forces_the_encoder(self):
        argv = build_argv("ffmpeg", "in.png", jobs.first_attempt(JPG).options, "out.jpg")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.png",
            "-map",
            "0:v?",
            "-c:v",
            "mjpeg",
            "-q:v",
            "2",
            "out.jpg",
        ]

    def test_jpg_copyable_source_on_the_selective_rung(self):
        streams = [Stream(0, "video", "mjpeg"), Stream(1, "video", "h264")]
        selective = jobs.retries(JPG, streams)[0]

        argv = build_argv("ffmpeg", "in.mkv", selective.options, "out.jpg")

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
            "-c:v",
            "copy",
            "out.jpg",
        ]
        assert selective.notes == ("video stream 1 (h264) dropped: JPG holds 1 video stream",)

    def test_jpg_non_copyable_source_on_the_selective_rung(self):
        """The re-encode note is now reachable, unlike png/tiff/bmp: jpg is the
        one image2 target whose fallback is declared lossy."""
        streams = [Stream(0, "video", "h264"), Stream(1, "video", "h264")]
        selective = jobs.retries(JPG, streams)[0]

        argv = build_argv("ffmpeg", "in.mkv", selective.options, "out.jpg")

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
            "-c:v",
            "mjpeg",
            "-q:v",
            "2",
            "out.jpg",
        ]
        assert selective.notes == (
            "video stream 0 (h264) re-encoded to mjpeg",
            "video stream 1 (h264) dropped: JPG holds 1 video stream",
        )

    def test_jpg_last_resort_extracts_the_first_frame(self):
        streams = [Stream(0, "video", "h264")]
        last_resort = jobs.retries(JPG, streams)[-1]

        argv = build_argv("ffmpeg", "in.mp4", last_resort.options, "out.jpg")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.mp4",
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-c:v",
            "mjpeg",
            "-q:v",
            "2",
            "out.jpg",
        ]
        assert last_resort.notes == (
            "only the first frame was kept; JPEG cannot hold more than one image",
            "transparency is not carried by JPEG; the image was re-encoded",
            "non-video streams, and any video stream beyond the first, are not carried into JPEG",
        )

    def test_tiff_cheap_attempt_forces_the_encoder(self):
        argv = build_argv("ffmpeg", "in.png", jobs.first_attempt(TIFF).options, "out.tiff")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.png",
            "-map",
            "0:v?",
            "-c:v",
            "tiff",
            "out.tiff",
        ]

    def test_tiff_copyable_source_on_the_selective_rung(self):
        streams = [Stream(0, "video", "tiff"), Stream(1, "video", "h264")]
        selective = jobs.retries(TIFF, streams)[0]

        argv = build_argv("ffmpeg", "in.mkv", selective.options, "out.tiff")

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
            "-c:v",
            "copy",
            "out.tiff",
        ]
        assert selective.notes == ("video stream 1 (h264) dropped: TIFF holds 1 video stream",)

    def test_tiff_non_copyable_source_on_the_selective_rung(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "video", "h264")]
        selective = jobs.retries(TIFF, streams)[0]

        argv = build_argv("ffmpeg", "in.mkv", selective.options, "out.tiff")

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
            "-c:v",
            "tiff",
            "out.tiff",
        ]

    def test_tiff_last_resort_extracts_the_first_frame(self):
        streams = [Stream(0, "video", "h264")]
        last_resort = jobs.retries(TIFF, streams)[-1]

        argv = build_argv("ffmpeg", "in.mp4", last_resort.options, "out.tiff")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.mp4",
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-c:v",
            "tiff",
            "out.tiff",
        ]
        assert last_resort.notes == (
            "only the first frame was kept; TIFF cannot hold more than one image",
            "non-video streams, and any video stream beyond the first, are not carried into TIFF",
        )

    def test_bmp_cheap_attempt_forces_the_encoder(self):
        argv = build_argv("ffmpeg", "in.png", jobs.first_attempt(BMP).options, "out.bmp")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.png",
            "-map",
            "0:v?",
            "-c:v",
            "bmp",
            "out.bmp",
        ]

    def test_bmp_copyable_source_on_the_selective_rung(self):
        streams = [Stream(0, "video", "bmp"), Stream(1, "video", "h264")]
        selective = jobs.retries(BMP, streams)[0]

        argv = build_argv("ffmpeg", "in.mkv", selective.options, "out.bmp")

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
            "-c:v",
            "copy",
            "out.bmp",
        ]
        assert selective.notes == ("video stream 1 (h264) dropped: BMP holds 1 video stream",)

    def test_bmp_non_copyable_source_on_the_selective_rung(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "video", "h264")]
        selective = jobs.retries(BMP, streams)[0]

        argv = build_argv("ffmpeg", "in.mkv", selective.options, "out.bmp")

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
            "-c:v",
            "bmp",
            "out.bmp",
        ]

    def test_bmp_last_resort_extracts_the_first_frame(self):
        streams = [Stream(0, "video", "h264")]
        last_resort = jobs.retries(BMP, streams)[-1]

        argv = build_argv("ffmpeg", "in.mp4", last_resort.options, "out.bmp")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.mp4",
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-c:v",
            "bmp",
            "out.bmp",
        ]
        assert last_resort.notes == (
            "only the first frame was kept; BMP cannot hold more than one image",
            "non-video streams, and any video stream beyond the first, are not carried into BMP",
        )


class TestAnimatedProfileArgvPinning:
    """Verification (spec-image-formats.md): the full argv `gif`, `webp` and
    `avif` build, pinned byte-for-byte, for a copyable and a non-copyable
    input each. `gif` and `avif` force their encoder on the cheap attempt, the
    same exception png/jpg/tiff/bmp carry; `webp` alone keeps a real copy
    there, so its copyable case is reached on the cheap attempt itself rather
    than only on the selective rung. All three reach their selective rung the
    same way png/jpg/tiff/bmp do: a second video stream trips the
    muxer-enforced `stream_limit=1` and forces the cheap attempt to fail."""

    def test_gif_cheap_attempt_forces_the_encoder(self):
        argv = build_argv("ffmpeg", "in.png", jobs.first_attempt(GIF).options, "out.gif")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.png",
            "-map",
            "0:v?",
            "-c:v",
            "gif",
            "out.gif",
        ]

    def test_gif_copyable_source_on_the_selective_rung(self):
        streams = [Stream(0, "video", "gif"), Stream(1, "video", "h264")]
        selective = jobs.retries(GIF, streams)[0]

        argv = build_argv("ffmpeg", "in.mkv", selective.options, "out.gif")

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
            "-c:v",
            "copy",
            "out.gif",
        ]
        assert selective.notes == ("video stream 1 (h264) dropped: GIF holds 1 video stream",)

    def test_gif_non_copyable_source_on_the_selective_rung(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "video", "h264")]
        selective = jobs.retries(GIF, streams)[0]

        argv = build_argv("ffmpeg", "in.mkv", selective.options, "out.gif")

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
            "-c:v",
            "gif",
            "out.gif",
        ]
        assert selective.notes == (
            "video stream 0 (h264) re-encoded to gif",
            "video stream 1 (h264) dropped: GIF holds 1 video stream",
        )

    def test_gif_last_resort_argv(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "video", "h264")]
        last_resort = jobs.retries(GIF, streams)[-1]

        argv = build_argv("ffmpeg", "in.mkv", last_resort.options, "out.gif")

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
            "0:v:0",
            "-c:v",
            "gif",
            "out.gif",
        ]
        assert last_resort.notes == (
            "transparency is not carried by GIF",
            "the image was re-quantised to GIF's 256-colour palette",
            "non-video streams, and any video stream beyond the first, are not carried into GIF",
        )

    def test_webp_cheap_attempt_keeps_a_real_copy(self):
        argv = build_argv("ffmpeg", "in.webp", jobs.first_attempt(WEBP).options, "out.webp")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.webp",
            "-map",
            "0:v?",
            "-c",
            "copy",
            "out.webp",
        ]

    def test_webp_copyable_source_on_the_selective_rung(self):
        streams = [Stream(0, "video", "webp"), Stream(1, "video", "h264")]
        selective = jobs.retries(WEBP, streams)[0]

        argv = build_argv("ffmpeg", "in.mkv", selective.options, "out.webp")

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
            "-c:v",
            "copy",
            "out.webp",
        ]
        assert selective.notes == ("video stream 1 (h264) dropped: WEBP holds 1 video stream",)

    def test_webp_non_copyable_source_on_the_selective_rung(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "video", "h264")]
        selective = jobs.retries(WEBP, streams)[0]

        argv = build_argv("ffmpeg", "in.mkv", selective.options, "out.webp")

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
            "-c:v",
            "libwebp",
            "-quality:v",
            "80",
            "out.webp",
        ]
        assert selective.notes == (
            "video stream 0 (h264) re-encoded to webp",
            "video stream 1 (h264) dropped: WEBP holds 1 video stream",
        )

    def test_webp_last_resort_argv(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "video", "h264")]
        last_resort = jobs.retries(WEBP, streams)[-1]

        argv = build_argv("ffmpeg", "in.mkv", last_resort.options, "out.webp")

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
            "0:v:0",
            "-c:v",
            "libwebp",
            "-quality:v",
            "80",
            "out.webp",
        ]
        assert last_resort.notes == (
            "the image was re-encoded to WebP (lossy)",
            "non-video streams, and any video stream beyond the first, are not carried into WEBP",
        )

    def test_avif_cheap_attempt_forces_the_encoder(self):
        argv = build_argv("ffmpeg", "in.png", jobs.first_attempt(AVIF).options, "out.avif")

        assert argv == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "in.png",
            "-map",
            "0:v?",
            "-c:v",
            "libaom-av1",
            "-crf:v",
            "30",
            "-still-picture",
            "1",
            "out.avif",
        ]

    def test_avif_copyable_source_on_the_selective_rung(self):
        streams = [Stream(0, "video", "av1"), Stream(1, "video", "h264")]
        selective = jobs.retries(AVIF, streams)[0]

        argv = build_argv("ffmpeg", "in.mkv", selective.options, "out.avif")

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
            "-c:v",
            "copy",
            "out.avif",
        ]
        assert selective.notes == ("video stream 1 (h264) dropped: AVIF holds 1 video stream",)

    def test_avif_non_copyable_source_on_the_selective_rung(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "video", "h264")]
        selective = jobs.retries(AVIF, streams)[0]

        argv = build_argv("ffmpeg", "in.mkv", selective.options, "out.avif")

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
            "-c:v",
            "libaom-av1",
            "-crf:v",
            "30",
            "-still-picture",
            "1",
            "out.avif",
        ]
        assert selective.notes == (
            "video stream 0 (h264) re-encoded to av1",
            "video stream 1 (h264) dropped: AVIF holds 1 video stream",
        )

    def test_avif_last_resort_argv(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "video", "h264")]
        last_resort = jobs.retries(AVIF, streams)[-1]

        argv = build_argv("ffmpeg", "in.mkv", last_resort.options, "out.avif")

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
            "0:v:0",
            "-c:v",
            "libaom-av1",
            "-crf",
            "30",
            "-still-picture",
            "1",
            "out.avif",
        ]
        assert last_resort.notes == (
            "transparency is not carried by AVIF",
            "a multi-frame source is reduced to a single frame",
            "non-video streams, and any video stream beyond the first, are not carried into AVIF",
        )


class TestUnsupportedDiscriminator:
    """`jobs.describe_unsupported`: "no rule matches any present stream"
    (docs/specs/archive/spec-target-driven-cli.md), derived from the probe alone."""

    def test_a_type_with_no_rule_at_all_is_unsupported(self):
        notes = jobs.describe_unsupported(WAV, [Stream(0, "video", "h264")])

        assert notes == ("video stream 0 (h264) dropped: not supported by WAV",)

    def test_a_type_the_profile_has_a_rule_for_is_supported(self):
        """The codec itself may still be dropped or re-encoded later -- that is
        a structural or codec-level verdict, not this one."""
        assert jobs.describe_unsupported(WAV, [Stream(0, "audio", "opus")]) is None

    def test_one_matching_stream_among_several_is_enough_to_be_supported(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "attachment", "ttf")]

        assert jobs.describe_unsupported(MP4, streams) is None

    def test_a_source_with_no_stream_the_profile_can_use_at_all_is_unsupported(self):
        """MP4 declares no ``attachment`` rule, same as WAV declares no
        ``video`` one -- the discriminator is type-level, not format-specific."""
        notes = jobs.describe_unsupported(MP4, [Stream(0, "attachment", "ttf")])

        assert notes == ("attachment stream 0 (ttf) dropped: not supported by MP4",)

    def test_a_source_webm_cannot_hold_at_all_is_unsupported(self):
        """WebM declares no ``attachment`` rule either -- a source carrying
        only an attachment (no video, audio or subtitle) is reported
        ``unsupported`` rather than being run through the ladder at all
        (spec-video-formats.md; a real attachment-only or data-only container
        proved impractical to construct with ffmpeg's own muxers -- both
        attempts failed at the ffmpeg tool boundary itself during the manual
        smoke test, before reaching this code -- so this pins the same
        mechanism the real fixture would exercise)."""
        notes = jobs.describe_unsupported(WEBM, [Stream(0, "attachment", "unknown")])

        assert notes == ("attachment stream 0 (unknown) dropped: not supported by WebM",)

    def test_an_empty_stream_list_is_not_reported_as_unsupported(self):
        """An empty probe result is the fingerprint of a corrupt or truncated
        source, not positive evidence the format holds nothing usable -- it
        must fall through to a genuine ``failed`` with ffmpeg's stderr kept,
        rather than a silent, note-less ``unsupported``."""
        assert jobs.describe_unsupported(MP4, []) is None
        assert jobs.describe_unsupported(WAV, []) is None


class TestSuccessSideVerification:
    """`jobs.needs_verification` / `jobs.verify_success`: what the engine owes
    a cheap attempt that already won."""

    def test_a_partial_profile_needs_verification(self):
        assert jobs.needs_verification(MP4) is True
        assert jobs.needs_verification(WAV) is True
        assert jobs.needs_verification(MKV) is True
        assert jobs.needs_verification(MOV) is True
        assert jobs.needs_verification(WEBM) is True

    def test_an_exhaustive_profile_does_not(self):
        """`False` is what keeps the probe off an exhaustive profile's happy path."""
        assert jobs.needs_verification(replace(MP4, partial_mapping=False)) is False

    def test_mp4_names_the_attachment_its_selectors_cannot_reach(self):
        streams = [Stream(0, "video", "h264"), Stream(1, "attachment", "ttf")]

        notes = jobs.verify_success(MP4, streams)

        assert notes == ("attachment stream 1 (ttf) dropped: not supported by MP4",)

    def test_wav_names_the_audio_stream_its_single_index_cannot_reach(self):
        notes = jobs.verify_success(WAV, [Stream(0, "audio", "opus"), Stream(1, "audio", "opus")])

        assert notes == ("audio stream 1 (opus) dropped: WAV holds 1 audio stream",)

    @pytest.mark.parametrize(
        "profile", [MP4, WAV, MKV, MOV, WEBM], ids=lambda profile: profile.label
    )
    def test_no_profile_invents_a_loss_for_a_source_it_fully_maps(self, profile):
        """One stream of each type the profile declares a rule for, and never more
        than one, so nothing in this source can have been left behind.

        Built from ``profile.rules`` rather than the cheap attempt's own
        ``mapped_types`` (`tests/test_profiles.py`), which is sound only because
        ``TestPartialMappingInvariant`` there pins the two as equal for every
        shipped profile (modulo `MOV`'s force-failure exemption for
        `attachment`) -- if that equality ever broke, this source would
        silently stop matching what the cheap attempt actually maps.
        """
        streams = [Stream(i, kind, "whatever") for i, kind in enumerate(profile.rules)]

        assert jobs.verify_success(profile, streams) == ()

    def test_a_codec_outside_the_copy_mask_produces_no_note(self):
        """Codec-level verdicts are out of scope here: the attempt exited 0, so
        the stream was carried over whatever the copy mask says."""
        streams = [Stream(0, "video", "vp8"), Stream(1, "subtitle", "dvd_subtitle")]

        assert jobs.verify_success(MP4, streams) == ()


class TestConfirmDrops:
    """`jobs.confirm_drops`: the prediction weighed against the written file.

    `verify_success` reads the mapping, which says what ffmpeg was *asked* to
    carry. MP4 and MOV regenerate a `tmcd` timecode track from source metadata
    with no selector naming it (issue #66), so the mapping alone over-reports.

    A drop is forgiven only when the output holds a surplus by stream type
    *and* by `(type, codec name, container tag)`, and only when that surplus
    covers every predicted drop sharing the key. Three review rounds killed the
    weaker forms in turn, each with a counter-example that hid a real loss --
    the one direction `docs/constitution.md` forbids outright:

    * by type alone, a regenerated `tmcd` forgave the drop of a `gpmd`/ANC
      telemetry stream in the same file, since no profile declares a `data`
      rule;
    * by type and codec name, WAV's re-encoding cheap attempt made source and
      output disagree on the codec name, so its own `pcm_s16le` output forgave
      the drop of a second, genuinely lost `pcm_s16le` source track;
    * without the container tag, an Apple `mebx` metadata track -- which reports
      no codec name either -- was forgiven in place of the `tmcd` beside it, so
      the survivor was named as the loss and the real loss went unreported;
    * without the all-or-nothing clause, a partial surplus had to guess which of
      several indistinguishable streams survived, and guessing wrong breaks both
      halves of the promise at once.
    """

    SOURCE: ClassVar[list[Stream]] = [
        Stream(0, "video", "h264"),
        Stream(1, "audio", "aac"),
        Stream(2, "data", ""),
    ]

    def test_a_stream_the_output_still_holds_is_not_reported_as_dropped(self):
        assert jobs.confirm_drops(MP4, self.SOURCE, self.SOURCE) == ()

    def test_a_stream_the_output_does_not_hold_keeps_its_note(self):
        produced = [Stream(0, "video", "h264"), Stream(1, "audio", "aac")]

        assert jobs.confirm_drops(MKV, self.SOURCE, produced) == (
            "data stream 2 (unknown) dropped: not supported by MKV",
        )

    def test_an_output_that_holds_nothing_keeps_every_note(self):
        """Nothing survived, so nothing is forgiven -- the direction that
        over-reports rather than falling silent."""
        assert jobs.confirm_drops(MP4, self.SOURCE, []) == jobs.verify_success(MP4, self.SOURCE)

    def test_an_ambiguous_surplus_forgives_nothing(self):
        """Two streams that are indistinguishable to the probe are predicted
        dropped and exactly one comes back. Which one survived is unknowable, so
        both keep their note: forgiving one at a guess would claim a loss that
        did not happen *and* fall silent about one that did."""
        source = [
            Stream(0, "video", "h264", "avc1"),
            Stream(1, "data", "", "tmcd"),
            Stream(2, "data", "", "tmcd"),
        ]
        produced = [Stream(0, "video", "h264", "avc1"), Stream(1, "data", "", "tmcd")]

        assert jobs.confirm_drops(MP4, source, produced) == (
            "data stream 1 (unknown) dropped: not supported by MP4",
            "data stream 2 (unknown) dropped: not supported by MP4",
        )

    def test_the_same_streams_all_surviving_are_all_forgiven(self):
        """The counterpart: the surplus covers every predicted drop of the key,
        so there is nothing to guess and none of them is reported."""
        source = [
            Stream(0, "video", "h264", "avc1"),
            Stream(1, "data", "", "tmcd"),
            Stream(2, "data", "", "tmcd"),
        ]

        assert jobs.confirm_drops(MP4, source, source) == ()

    @pytest.mark.parametrize("profile", [MP4, MOV], ids=lambda profile: profile.label)
    def test_a_regenerated_timecode_never_forgives_a_metadata_drop(self, profile):
        """The counter-example that added the container tag to the key.

        Apple `mebx` metadata -- every iPhone `.mov` has one -- demuxes with no
        codec id, so ffprobe omits `codec_name` for it exactly as it does for a
        `tmcd`. Source stream 2 is genuinely gone and stream 3 is the one the
        muxer put back at a *different index*; without the tag the two were
        indistinguishable, the first was forgiven and the survivor was reported
        as the loss -- issue #66's own failure mode, with the real loss hidden
        behind it.
        """
        source = [
            Stream(0, "video", "h264", "avc1"),
            Stream(1, "audio", "aac", "mp4a"),
            Stream(2, "data", "", "mebx"),
            Stream(3, "data", "", "tmcd"),
        ]
        produced = [
            Stream(0, "video", "h264", "avc1"),
            Stream(1, "audio", "aac", "mp4a"),
            Stream(2, "data", "", "tmcd"),
        ]

        assert jobs.confirm_drops(profile, source, produced) == (
            f"data stream 2 (unknown) dropped: not supported by {profile.label}",
        )

    @pytest.mark.parametrize("profile", [MP4, MOV], ids=lambda profile: profile.label)
    def test_a_regenerated_timecode_never_forgives_a_telemetry_drop(self, profile):
        """The counter-example that decided the match key: one source data
        stream (`gpmd`/ANC telemetry, `bin_data`) genuinely lost, and one data
        stream in the output that the muxer synthesised from metadata (`tmcd`,
        no codec name on either side). Matching on `codec_type` alone reported
        this as a clean success while a real stream was gone."""
        source = [Stream(0, "video", "h264"), Stream(1, "data", "bin_data")]
        produced = [Stream(0, "video", "h264"), Stream(1, "data", "")]

        assert jobs.confirm_drops(profile, source, produced) == (
            f"data stream 1 (bin_data) dropped: not supported by {profile.label}",
        )

    @pytest.mark.parametrize("profile", [MP4, MOV], ids=lambda profile: profile.label)
    def test_both_verdicts_are_reached_when_both_data_streams_are_present(self, profile):
        """The same file carrying both: the timecode is forgiven, the telemetry
        is not. One key forgiving another would collapse the two. Note the
        surviving stream's output index differs from its source index, so an
        index-based match would fail this even though every field agrees."""
        source = [
            Stream(0, "video", "h264", "avc1"),
            Stream(1, "data", "bin_data", "gpmd"),
            Stream(2, "data", "", "tmcd"),
        ]
        produced = [Stream(0, "video", "h264", "avc1"), Stream(1, "data", "", "tmcd")]

        assert jobs.confirm_drops(profile, source, produced) == (
            f"data stream 1 (bin_data) dropped: not supported by {profile.label}",
        )

    def test_a_re_encoded_output_stream_never_forgives_a_real_drop(self):
        """The counter-example that decided the *second* half of the rule.

        WAV's cheap attempt re-encodes (`-map 0:a:0 -c:a pcm_s16le`), so the
        source's codec name and the output's disagree by construction. Its one
        `pcm_s16le` output stream reads as a surplus under that key, and by key
        alone it forgave the drop of the source's second track -- which happens
        to be `pcm_s16le` too and is genuinely gone. The stream-type count is
        what closes it: a re-encode preserves the type, so `audio` shows no
        surplus at all.
        """
        source = [Stream(0, "audio", "aac"), Stream(1, "audio", "pcm_s16le")]
        produced = [Stream(0, "audio", "pcm_s16le")]

        assert jobs.confirm_drops(WAV, source, produced) == (
            "audio stream 1 (pcm_s16le) dropped: WAV holds 1 audio stream",
        )

    def test_a_stream_of_another_type_never_forgives_a_drop(self):
        """Neither budget is spendable across stream types, so an extra audio
        stream in the output cannot silence a dropped attachment."""
        source = [Stream(0, "video", "h264"), Stream(1, "attachment", "ttf")]
        produced = [Stream(0, "video", "h264"), Stream(1, "audio", "aac")]

        assert jobs.confirm_drops(MP4, source, produced) == (
            "attachment stream 1 (ttf) dropped: not supported by MP4",
        )

    def test_a_surplus_of_a_type_with_no_predicted_drop_changes_nothing(self):
        source = [Stream(0, "video", "h264"), Stream(1, "attachment", "ttf")]
        produced = [Stream(0, "video", "h264"), Stream(1, "video", "h264")]

        assert jobs.confirm_drops(MP4, source, produced) == (
            "attachment stream 1 (ttf) dropped: not supported by MP4",
        )

    def test_a_stream_limit_drop_the_output_disproves_is_forgiven(self):
        """Not a `tmcd` special case: the same confirmation covers D2, where the
        prediction is "the container holds only so many of this type"."""
        source = [Stream(0, "audio", "opus"), Stream(1, "audio", "opus")]

        assert jobs.confirm_drops(WAV, source, source) == ()
        assert jobs.confirm_drops(WAV, source, source[:1]) == (
            "audio stream 1 (opus) dropped: WAV holds 1 audio stream",
        )


def _audio_and_picture_profile(*, picture_rule: bool = True) -> Profile:
    """A profile shaped like the audio targets this phase amends (mp3, m4a,
    flac): an audio rule plus, optionally, an ``attached_pic`` one -- built
    locally so the resolution logic can be pinned without waiting on a shipped
    profile to gain the rule (issue #87, a sibling of this one).
    """
    rules = {"audio": StreamRule(frozenset({"aac"}), flags("-c:a copy"))}
    if picture_rule:
        rules["attached_pic"] = StreamRule(frozenset({"png", "mjpeg"}), flags("-c:v:{n} copy"))
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
        rules=rules,
    )


class TestDispositionResolution:
    """`jobs._rule_key` -- stream-decision.md's PIC node: a stream resolves to
    the profile's ``attached_pic`` rule when one is declared, and falls back to
    its ``codec_type`` otherwise (issue #76)."""

    def test_an_attached_picture_resolves_to_its_own_rule(self):
        """A copy mask and accept template distinct from any ``video`` rule
        would use proves it is the ``attached_pic`` rule that actually fired,
        not a coincidence of the two being identical."""
        profile = _audio_and_picture_profile()
        streams = [Stream(0, "audio", "aac"), Stream(1, "video", "png", attached_pic=True)]

        [selective] = jobs.retries(profile, streams)

        assert selective.options == (
            "-map",
            "0:0",
            "-map",
            "0:1",
            "-c:a",
            "copy",
            "-c:v:0",
            "copy",
        )
        assert selective.notes == ()

    def test_falls_back_to_codec_type_when_the_profile_declares_no_rule(self):
        """The same picture, but a profile that never gained the rule --
        stream-decision.md's fallback branch. It resolves to the ``video``
        lookup, finds nothing, and is dropped exactly as it always was."""
        profile = _audio_and_picture_profile(picture_rule=False)
        streams = [Stream(0, "audio", "aac"), Stream(1, "video", "png", attached_pic=True)]

        notes = jobs.verify_success(profile, streams)

        assert notes == ("video stream 1 (png) dropped: not supported by PICT",)

    @pytest.mark.parametrize("profile", [OGG, OPUS, WAV], ids=lambda profile: profile.label)
    def test_ogg_opus_and_wav_are_unaffected_by_the_disposition(self, profile):
        """None of the three declares an ``attached_pic`` rule, so a stream's
        disposition must make no difference at all -- the fallback guard this
        phase must not break (issue #76's Acceptance)."""
        plain = Stream(0, "video", "png")
        picture = Stream(0, "video", "png", attached_pic=True)

        assert jobs.verify_success(profile, [plain]) == jobs.verify_success(profile, [picture])
        assert jobs.retries(profile, [plain]) == jobs.retries(profile, [picture])

    def test_the_engine_still_counts_a_carried_picture_under_video(self):
        """A real video stream and an attached picture share one position
        counter, because ffmpeg numbers a carried picture as a video output
        stream (Prior decisions, spec-stream-disposition.md) -- so the second
        stream here substitutes ``{n} == 1``, not ``{n} == 0``."""
        base = _audio_and_picture_profile()
        profile = replace(
            base,
            rules={**base.rules, "video": StreamRule(frozenset({"h264"}), flags("-c:v:{n} copy"))},
        )
        streams = [
            Stream(0, "video", "h264"),
            Stream(1, "video", "png", attached_pic=True),
        ]

        [selective] = jobs.retries(profile, streams)

        assert selective.options == (
            "-map",
            "0:0",
            "-map",
            "0:1",
            "-c:v:0",
            "copy",
            "-c:v:1",
            "copy",
        )

    def test_two_attached_pictures_both_survive_uncounted_against_a_limit(self):
        """The rule declares no ``stream_limit`` (Prior decisions), so a second
        picture is carried, not reported as dropped for want of room."""
        profile = _audio_and_picture_profile()
        streams = [
            Stream(0, "video", "png", attached_pic=True),
            Stream(1, "video", "mjpeg", attached_pic=True),
        ]

        assert jobs.verify_success(profile, streams) == ()

    def test_describe_unsupported_stays_keyed_on_codec_type(self):
        """Deliberate (Prior decisions, spec-stream-disposition.md): the
        discriminator asks whether the source carries any stream *type* the
        profile could use at all, which a disposition does not change -- even
        though this profile's ``attached_pic`` rule would in fact carry the
        stream once the ladder ran."""
        profile = _audio_and_picture_profile()
        streams = [Stream(0, "video", "png", attached_pic=True)]

        notes = jobs.describe_unsupported(profile, streams)

        assert notes == ("video stream 0 (png) dropped: not supported by PICT",)

    def test_verify_success_does_not_report_a_carried_picture_as_dropped(self):
        """The two outcomes stream-decision.md's PIC node exists to tell apart,
        in one source: a picture the profile carries via its own rule, and an
        ordinary video stream the profile still has no rule for."""
        profile = _audio_and_picture_profile()
        streams = [
            Stream(0, "audio", "aac"),
            Stream(1, "video", "png", attached_pic=True),
            Stream(2, "video", "h264", attached_pic=False),
        ]

        notes = jobs.verify_success(profile, streams)

        assert notes == ("video stream 2 (h264) dropped: not supported by PICT",)


@pytest.mark.parametrize(
    "attempt",
    [jobs.first_attempt(MP4), *jobs.retries(MP4, [Stream(0, "video", "h264")])],
)
def test_every_attempt_produces_a_wellformed_command(attempt):
    argv = build_argv("ffmpeg", "in.mkv", attempt.options, "out.mp4")

    assert argv[0] == "ffmpeg"
    assert argv[-1] == "out.mp4"
    assert options_of(argv, "in.mkv", "out.mp4") == list(attempt.options)

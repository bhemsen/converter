"""Tests for the ffmpeg command lines we build, without running ffmpeg."""

import subprocess
from dataclasses import replace

import pytest

from converter import ffmpegtool, jobs
from converter.ffmpegtool import Stream, build_argv, cli_path
from converter.profiles import FLAC, M4A, MP3, MP4, OGG, OPUS, WAV


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
    """Issue #21, `docs/specs/spec-audio-formats.md`: mp3's cheap attempt maps
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
    """Issue #21, `docs/specs/spec-audio-formats.md`: same blind-mapping shape
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
    """Issue #22, `docs/specs/spec-audio-formats.md`: same blind-mapping shape
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
    """Issue #22, `docs/specs/spec-audio-formats.md`: same shape as `M4A`,
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
        """The ogg muxer rejects mp3 and aac (docs/specs/spec-audio-formats.md)."""
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
    """Issue #22, `docs/specs/spec-audio-formats.md`: `opus` copies on the
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


class TestProfileArgvPinning:
    """Verification: the full argv each profile builds, pinned byte-for-byte
    (docs/specs/spec-profile-registry.md)."""

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


class TestUnsupportedDiscriminator:
    """`jobs.describe_unsupported`: "no rule matches any present stream"
    (docs/specs/spec-target-driven-cli.md), derived from the probe alone."""

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

    @pytest.mark.parametrize("profile", [MP4, WAV], ids=lambda profile: profile.label)
    def test_no_profile_invents_a_loss_for_a_source_it_fully_maps(self, profile):
        """One stream of each type the profile declares a rule for, and never more
        than one, so nothing in this source can have been left behind.

        Built from ``profile.rules`` rather than the cheap attempt's own
        ``mapped_types`` (`tests/test_profiles.py`), which is sound only because
        ``TestPartialMappingInvariant`` there pins the two as equal for every
        shipped profile -- if that equality ever broke for `MP4` or `WAV`, this
        source would silently stop matching what the cheap attempt actually maps.
        """
        streams = [Stream(i, kind, "whatever") for i, kind in enumerate(profile.rules)]

        assert jobs.verify_success(profile, streams) == ()

    def test_a_codec_outside_the_copy_mask_produces_no_note(self):
        """Codec-level verdicts are out of scope here: the attempt exited 0, so
        the stream was carried over whatever the copy mask says."""
        streams = [Stream(0, "video", "vp8"), Stream(1, "subtitle", "dvd_subtitle")]

        assert jobs.verify_success(MP4, streams) == ()


@pytest.mark.parametrize(
    "attempt",
    [jobs.first_attempt(MP4), *jobs.retries(MP4, [Stream(0, "video", "h264")])],
)
def test_every_attempt_produces_a_wellformed_command(attempt):
    argv = build_argv("ffmpeg", "in.mkv", attempt.options, "out.mp4")

    assert argv[0] == "ffmpeg"
    assert argv[-1] == "out.mp4"
    assert options_of(argv, "in.mkv", "out.mp4") == list(attempt.options)

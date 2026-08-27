"""Declarative target-format profiles: value types, the registry, and lookup.

A leaf module by design (`docs/architecture.md`): it holds no ``from converter``
or ``import converter`` statement at all, so a target format can only ever be
data, never new logic. That is also why ``flags()`` and ``Attempt`` live here
instead of being imported from ``jobs.py`` -- importing them would break the
leaf property in the other direction.

``PROFILES`` is the target-name -> profile registry a target-driven CLI needs,
``resolve_target`` is how it looks a target up, and ``SOURCE_SUFFIXES`` is the
curated set of suffixes discovery walks (`docs/design/source-selection.md`) --
curated by hand for the same reason a profile's copy mask is: ffmpeg can be
asked what a file contains, never what it will accept as an input.

See ``docs/design/degradation-ladder.md`` for how the engine in ``jobs.py``
turns one profile into an ordered ladder of attempts, and
``docs/design/stream-decision.md`` for how it decides one stream's fate
against the profile's per-type rule.
"""

from dataclasses import dataclass


def flags(spec: str) -> tuple[str, ...]:
    """Split a command-line-shaped string into argv items.

    Recipes then read exactly like what you would type after ``ffmpeg -i in.mkv``,
    and flag/value pairs stay on one line regardless of how the formatter feels
    about trailing commas.  Only ever used for flags and their values -- paths go
    through :func:`converter.ffmpegtool.build_argv`, never through here.
    """
    return tuple(spec.split())


@dataclass(frozen=True)
class Attempt:
    """One ffmpeg option list, with a note of anything it sacrifices."""

    label: str
    options: tuple[str, ...]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class StreamRule:
    """How one stream type is handled: accept, re-encode, or drop.

    ``accept_options`` and ``fallback_options`` may carry the literal ``{n}``
    placeholder, which the engine replaces with the stream's position among
    output streams of its type. A rule whose ``stream_limit`` is 1 can only
    ever produce one output stream of its type, so it writes the bare
    specifier instead and leaves the placeholder out.
    """

    copy_mask: frozenset[str]
    accept_options: tuple[str, ...]
    fallback_options: tuple[str, ...] | None = None
    fallback_name: str | None = None
    stream_limit: int | None = None
    #: Why a stream is dropped when the copy mask misses and no fallback is
    #: declared -- irrelevant, and left ``None``, for a rule that always has one.
    drop_reason: str | None = None


@dataclass(frozen=True)
class Profile:
    """One target format, declared entirely as data.

    ``explicit_streams`` says whether ``cheap_attempt`` already selects streams
    by index (WAV's ``-map 0:a:0``) rather than blindly by type (MP4's
    ``-map 0:v?``) -- the one fact the engine cannot derive without parsing
    ffmpeg's own option syntax, per ``docs/design/degradation-ladder.md``.

    ``partial_mapping`` says whether ``cheap_attempt``'s mapping can, *by
    construction*, leave source streams unmapped. It is declared for the same
    reason ``explicit_streams`` is: deriving it would mean parsing the option
    list. A profile that declares it true is verified by an ffprobe round-trip
    even when its cheap attempt exits 0, so a stream that attempt silently left
    behind is named rather than reported as a plain success
    (``docs/design/degradation-ladder.md``).

    ``name`` is the registry key and the ``--to`` token (``"mp4"``); ``label``
    stays the display form ``--list-formats`` and progress bars print
    (``"MP4"``). ``description`` is the one-line explanation
    ``--list-formats`` and the interactive prompt print next to ``name``.
    """

    label: str
    name: str
    description: str
    target_suffix: str
    container_options: tuple[str, ...]
    cheap_attempt: Attempt
    explicit_streams: bool
    partial_mapping: bool
    rules: dict[str, StreamRule]
    last_resort: Attempt | None = None


#: Move the MP4 index to the front so the file plays before it is fully read.
FASTSTART = flags("-movflags +faststart")

#: Codecs a standard MP4 container accepts, so they can be stream-copied.
MP4_VIDEO_CODECS = frozenset({"h264", "hevc", "av1", "vp9", "mpeg4", "mpeg2video", "mjpeg"})
MP4_AUDIO_CODECS = frozenset({"aac", "mp3", "ac3", "eac3", "alac", "opus", "flac"})
#: Subtitle codecs that convert cleanly into MP4's own ``mov_text``.
TEXT_SUBTITLE_CODECS = frozenset({"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"})

MP4 = Profile(
    label="MP4",
    name="mp4",
    description="Video: copies compatible streams, re-encodes the rest to h264/aac",
    target_suffix=".mp4",
    container_options=FASTSTART,
    # Deliberately not "-map 0": that also selects MKV attachments (font files
    # for ASS subtitles) and data streams, which MP4 cannot hold, so an
    # otherwise perfectly remuxable file would fail. The trailing "?" makes
    # each selector optional instead of fatal.
    cheap_attempt=Attempt(
        label="remux",
        options=flags("-map 0:v? -map 0:a? -map 0:s? -c copy -c:s mov_text"),
    ),
    explicit_streams=False,
    # The same "?" selectors that make the remux survivable also make it
    # incomplete: nothing selects attachments or data streams, so a source
    # carrying either loses it without ffmpeg ever complaining.
    partial_mapping=True,
    rules={
        "video": StreamRule(
            copy_mask=MP4_VIDEO_CODECS,
            accept_options=flags("-c:v:{n} copy"),
            fallback_options=flags("-c:v:{n} libx264 -crf:v:{n} 18"),
            fallback_name="h264",
        ),
        "audio": StreamRule(
            copy_mask=MP4_AUDIO_CODECS,
            accept_options=flags("-c:a:{n} copy"),
            fallback_options=flags("-c:a:{n} aac -b:a:{n} 192k"),
            fallback_name="aac",
        ),
        "subtitle": StreamRule(
            copy_mask=TEXT_SUBTITLE_CODECS,
            # A cheap in-kind transcode, not a literal copy: MP4 only holds
            # text subtitles as its own mov_text.
            accept_options=flags("-c:s:{n} mov_text"),
            drop_reason="bitmap subtitles cannot be stored in MP4",
        ),
    },
    last_resort=Attempt(
        label="re-encode",
        options=flags(
            "-map 0:v:0? -map 0:a? "
            "-c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "
            "-c:a aac -b:a 192k"
        ),
        notes=(
            "re-encoded to h264/aac (lossy); subtitles and extra video streams dropped",
            "10-bit or HDR sources are reduced to 8-bit yuv420p for player compatibility",
        ),
    ),
)

WAV = Profile(
    label="WAV",
    name="wav",
    description="Audio: single stream, uncompressed 16-bit PCM",
    target_suffix=".wav",
    container_options=(),
    # The stream is selected explicitly rather than left to ffmpeg's implicit
    # "best stream" heuristic, so a file with several audio streams converts
    # predictably instead of quietly depending on which one ffmpeg prefers.
    cheap_attempt=Attempt(label="pcm_s16le", options=flags("-map 0:a:0 -c:a pcm_s16le")),
    explicit_streams=True,
    # One index is named and nothing else is, so every further stream the
    # source carries -- a second audio track, cover art -- is left behind.
    partial_mapping=True,
    rules={
        "audio": StreamRule(
            # Empty by construction: WAV holds nothing as-is, only PCM.
            copy_mask=frozenset(),
            # Never emitted -- the empty copy mask means the accept branch of
            # stream-decision.md can never be reached -- so it carries no
            # placeholder either, same as the fallback below.
            accept_options=(),
            fallback_options=flags("-c:a pcm_s16le"),
            # No fallback_name: decoding to PCM is the definition of WAV, not
            # a loss, so the re-encode carries no note.
            stream_limit=1,
        ),
    },
)


class _AcceptAnyCodec(frozenset):
    """A copy mask that is empty by every ordinary measure yet accepts anything.

    ``len()`` is 0 and iterating it yields nothing -- the "empty-meaning" shape
    ``docs/specs/archive/spec-video-formats.md`` asks for -- but membership testing
    always succeeds, so :func:`converter.jobs._decide_stream`'s
    ``stream.codec_name in rule.copy_mask`` check reads it as "always accept"
    without the engine (a leaf-adjacent module MKV's profile must not import
    anyway) needing to know it. Enumerating font codec names instead would be
    wrong by construction: ffprobe derives an attachment's codec name from its
    MIME type, and a modern font's MIME type (``font/ttf``, ``font/otf``) reads
    back as ``unknown`` -- measured against ffmpeg 9.0.
    """

    def __contains__(self, item: object) -> bool:
        return True


#: Codecs Matroska accepts as a stream copy for video, measured against ffmpeg
#: 9.0 -- includes vp9 and av1 from a WebM source, unlike MP4's narrower mask.
MKV_VIDEO_CODECS = frozenset(
    {
        "h264",
        "hevc",
        "av1",
        "vp8",
        "vp9",
        "mpeg4",
        "mpeg2video",
        "theora",
        "prores",
        "ffv1",
        "mjpeg",
    }
)
#: Codecs Matroska accepts as a stream copy for audio, measured the same way.
MKV_AUDIO_CODECS = frozenset(
    {
        "aac",
        "mp3",
        "ac3",
        "eac3",
        "dts",
        "truehd",
        "flac",
        "opus",
        "vorbis",
        "alac",
        "pcm_s16le",
    }
)
#: Subtitle codecs Matroska accepts as a literal copy -- text *and* bitmap,
#: unlike MP4's text-only mask. ``mov_text`` is deliberately absent: Matroska
#: rejects a mov_text stream copy outright (measured: exit 127, "Subtitle codec
#: mov_text ... is not supported"), so a mov_text source falls through to the
#: ``srt`` fallback below instead of being listed here as copyable.
MKV_SUBTITLE_CODECS = frozenset(
    {
        "subrip",
        "ass",
        "ssa",
        "webvtt",
        "text",
        "hdmv_pgs_subtitle",
        "dvd_subtitle",
        "dvb_subtitle",
    }
)

MKV = Profile(
    label="MKV",
    name="mkv",
    description="Video: copies almost every codec as-is, keeps font attachments",
    target_suffix=".mkv",
    # Measured: +faststart is MP4/MOV furniture that MKV's own muxer ignores,
    # so declaring it here would be noise, not a real container option.
    container_options=(),
    # Matroska is the one target in this phase that rarely re-encodes, so its
    # cheap attempt maps every stream type its muxer can hold -- video, audio,
    # subtitle, *and* attachment ("-map 0:t?"), which no earlier profile has
    # needed. Still not "-map 0": that would also select data and timecode
    # streams, which no "v/a/s/t" map -- MKV's included -- carries at all
    # (measured), so the standing note below says so instead of ffmpeg silently
    # dropping them off a bare "-map 0".
    cheap_attempt=Attempt(
        label="remux",
        options=flags("-map 0:v? -map 0:a? -map 0:s? -map 0:t? -c copy"),
        notes=("data and timecode streams are not carried into MKV",),
    ),
    explicit_streams=False,
    # The blind "?" selectors carry every video, audio, subtitle and attachment
    # stream MKV's muxer can hold, but never a data or timecode one -- exactly
    # the standing note's claim, verified once per successful cheap attempt
    # rather than assumed.
    partial_mapping=True,
    rules={
        "video": StreamRule(
            copy_mask=MKV_VIDEO_CODECS,
            accept_options=flags("-c:v:{n} copy"),
            fallback_options=flags("-c:v:{n} libx264 -crf:v:{n} 18"),
            fallback_name="h264",
        ),
        "audio": StreamRule(
            copy_mask=MKV_AUDIO_CODECS,
            accept_options=flags("-c:a:{n} copy"),
            fallback_options=flags("-c:a:{n} aac -b:a:{n} 192k"),
            fallback_name="aac",
        ),
        "subtitle": StreamRule(
            copy_mask=MKV_SUBTITLE_CODECS,
            accept_options=flags("-c:s:{n} copy"),
            fallback_options=flags("-c:s:{n} srt"),
            fallback_name="subrip",
        ),
        # No fallback and no drop_reason: the accept-everything mask means the
        # fallback branch of stream-decision.md can never be reached, the same
        # reason WAV's empty mask carries no accept_options.
        "attachment": StreamRule(
            copy_mask=_AcceptAnyCodec(),
            accept_options=flags("-c:t:{n} copy"),
        ),
    },
    last_resort=Attempt(
        label="re-encode",
        options=flags(
            "-map 0:v:0? -map 0:a? "
            "-c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "
            "-c:a aac -b:a 192k"
        ),
        notes=(
            "re-encoded to h264/aac (lossy); subtitles and extra video streams dropped",
            "10-bit or HDR sources are reduced to 8-bit yuv420p for player compatibility",
        ),
    ),
)

#: Codecs a MOV container accepts as a stream copy for video, measured against
#: ffmpeg 9.0. Narrower than MP4's mask in *two* codecs -- vp9 and av1, both
#: rejected by MOV's muxer ("vp9 only supported in MP4", "av1 only supported
#: in MP4 and AVIF") -- and also rejects vp8 ("VP8 muxing is currently not
#: supported"). Adds ffv1 and theora, which MP4 does not carry either, so this
#: is its own curated set rather than MP4_VIDEO_CODECS with an entry struck.
MOV_VIDEO_CODECS = frozenset(
    {"h264", "hevc", "prores", "mpeg4", "mpeg2video", "mjpeg", "ffv1", "theora"}
)
#: Codecs a MOV container accepts as a stream copy for audio, measured the same
#: way -- adds dts and pcm_s16le (tags dtsc, sowt) over MP4's mask.
MOV_AUDIO_CODECS = frozenset({"aac", "alac", "mp3", "ac3", "eac3", "dts", "pcm_s16le"})

MOV = Profile(
    label="MOV",
    name="mov",
    description="Video: copies compatible streams, re-encodes the rest to h264/aac; no attachments",
    target_suffix=".mov",
    container_options=FASTSTART,
    # Deliberately maps "0:t?" even though MOV holds no attachment rule below:
    # MOV's muxer rejects any mapped attachment outright ("Could not find tag
    # for codec ttf", measured), so an attachment-bearing source fails this
    # cheap attempt and lands on the ladder's failure side instead, where the
    # missing rule drops it with a real per-stream note -- better than a
    # blanket standing note for the one case MOV can make loud. Still not
    # "-map 0": that would also select data and timecode streams, which no
    # "v/a/s/t" map -- MOV's included -- selects at all (measured).
    #
    # No standing note about data and timecode streams, unlike MKV's otherwise
    # identical shape: MOV's muxer *regenerates* a tmcd timecode track from the
    # source's metadata even though no selector maps it, so the blanket claim
    # was measurably false for the commonest data stream a MOV source carries
    # (issue #66). What actually reaches the output is settled per file by the
    # success-side verification, which reads the written file rather than the
    # mapping -- a real data drop still gets its own per-stream note there.
    cheap_attempt=Attempt(
        label="remux",
        options=flags("-map 0:v? -map 0:a? -map 0:s? -map 0:t? -c copy -c:s mov_text"),
    ),
    explicit_streams=False,
    # The blind "?" selectors carry every video, audio and subtitle stream
    # MOV's muxer can hold, and an attachment only ever forces the cheap attempt
    # to fail; what the muxer does with a data stream is checked against the
    # output per file rather than declared here.
    partial_mapping=True,
    rules={
        "video": StreamRule(
            copy_mask=MOV_VIDEO_CODECS,
            accept_options=flags("-c:v:{n} copy"),
            fallback_options=flags("-c:v:{n} libx264 -crf:v:{n} 18"),
            fallback_name="h264",
        ),
        "audio": StreamRule(
            copy_mask=MOV_AUDIO_CODECS,
            accept_options=flags("-c:a:{n} copy"),
            fallback_options=flags("-c:a:{n} aac -b:a:{n} 192k"),
            fallback_name="aac",
        ),
        "subtitle": StreamRule(
            copy_mask=TEXT_SUBTITLE_CODECS,
            # A cheap in-kind transcode, not a literal copy: MOV only holds
            # text subtitles as its own mov_text, same as MP4.
            accept_options=flags("-c:s:{n} mov_text"),
            drop_reason="bitmap subtitles cannot be stored in MOV",
        ),
        # No "attachment" rule: MOV's muxer rejects any mapped attachment, so
        # mapping "0:t?" only ever forces this cheap attempt to fail when the
        # source has one. The type never reaches the success side, so it is
        # exempted from the partial_mapping equality (FORCED_FAILURE_TYPES,
        # docs/design/degradation-ladder.md, issue #39) rather than needing a
        # drop-only rule here. An attachment-bearing source falls through to
        # the selective rung, where the missing rule drops it with a real
        # per-stream note via _structural_drop (converter/jobs.py).
    },
    last_resort=Attempt(
        label="re-encode",
        options=flags(
            "-map 0:v:0? -map 0:a? "
            "-c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "
            "-c:a aac -b:a 192k"
        ),
        notes=(
            "re-encoded to h264/aac (lossy); subtitles and extra video streams dropped",
            "10-bit or HDR sources are reduced to 8-bit yuv420p for player compatibility",
        ),
    ),
)

#: Codecs a WebM container accepts as a stream copy for video, measured against
#: ffmpeg 9.0. WebM enforces its own codec set at the muxer level ("Only VP8 or
#: VP9 or AV1 video and Vorbis or Opus audio and WebVTT subtitles are supported
#: for WebM"), so a copy outside this mask does not silently degrade -- it fails
#: the cheap attempt outright and the ladder re-encodes.
WEBM_VIDEO_CODECS = frozenset({"vp8", "vp9", "av1"})
#: Codecs a WebM container accepts as a stream copy for audio, measured the
#: same way.
WEBM_AUDIO_CODECS = frozenset({"opus", "vorbis"})

WEBM = Profile(
    label="WebM",
    name="webm",
    description="Video: copies VP8/VP9/AV1 and Opus/Vorbis, re-encodes the rest to VP9/Opus",
    target_suffix=".webm",
    # Measured: WebM's muxer enforces its own codec set and has no faststart
    # equivalent worth declaring, so this stays empty like MKV's.
    container_options=(),
    # Unlike MKV and MOV, deliberately does NOT map "0:t?": WebM does not reject
    # a mapped attachment, it silently discards it at exit 0 (measured), so
    # mapping it would buy nothing -- the "map to force a failure" trick MOV
    # uses does not work here. A source with an attachment still loses it, but
    # only the standing note below can say so, since nothing ever fails on one.
    # Still not "-map 0": that would also select data and timecode streams,
    # which no "v/a/s" map -- WebM's included -- carries at all (measured).
    cheap_attempt=Attempt(
        label="remux",
        options=flags("-map 0:v? -map 0:a? -map 0:s? -c copy -c:s webvtt"),
        notes=("attachments, data and timecode streams are not carried into WebM",),
    ),
    explicit_streams=False,
    # The blind "?" selectors carry every video, audio and subtitle stream
    # WebM's muxer can hold, but never an attachment, data or timecode stream --
    # exactly the standing note's claim, verified once per successful cheap
    # attempt rather than assumed.
    partial_mapping=True,
    rules={
        "video": StreamRule(
            copy_mask=WEBM_VIDEO_CODECS,
            accept_options=flags("-c:v:{n} copy"),
            # VP9 needs "-b:v 0" alongside "-crf" to mean quality-targeted
            # mode; "-crf" alone leaves it in constrained-quality mode instead
            # (measured, spec-video-formats.md's "one open decision").
            fallback_options=flags(
                "-c:v:{n} libvpx-vp9 -crf:v:{n} 32 -b:v:{n} 0 -row-mt 1 -cpu-used 4"
            ),
            fallback_name="vp9",
        ),
        "audio": StreamRule(
            copy_mask=WEBM_AUDIO_CODECS,
            accept_options=flags("-c:a:{n} copy"),
            fallback_options=flags("-c:a:{n} libopus -b:a:{n} 128k"),
            fallback_name="opus",
        ),
        "subtitle": StreamRule(
            copy_mask=TEXT_SUBTITLE_CODECS,
            # A cheap in-kind transcode, not a literal copy: WebM only holds
            # text subtitles as WebVTT.
            accept_options=flags("-c:s:{n} webvtt"),
            drop_reason="bitmap subtitles cannot be stored in WebM",
        ),
        # No "attachment" rule: the cheap attempt maps no attachment at all
        # (unlike MOV, which maps one only to force a failure), so this type
        # never appears in mapped_types and needs no FORCED_FAILURE_TYPES
        # exemption either -- it is simply absent from both sides of the
        # equality, the same way MP4 declares no "attachment" rule. A source
        # that has one still succeeds the cheap attempt, and the success-side
        # verification (jobs.verify_success) names the drop per stream because
        # no rule matches "attachment" -- the standing note above restates it
        # unconditionally alongside that per-stream note.
    },
    last_resort=Attempt(
        label="re-encode",
        options=flags(
            "-map 0:v:0? -map 0:a? "
            "-c:v libvpx-vp9 -crf 32 -b:v 0 -row-mt 1 -cpu-used 4 "
            "-c:a libopus -b:a 128k"
        ),
        notes=("re-encoded to vp9/opus (lossy); subtitles and extra video streams dropped",),
    ),
)

MP3 = Profile(
    label="MP3",
    name="mp3",
    description="Audio: single stream, MP3 (libmp3lame if re-encoded)",
    target_suffix=".mp3",
    container_options=(),
    # Blind by type, not by index: the mp3 muxer -- not this mapping --
    # enforces "at most one audio stream" (measured against ffmpeg 9.0,
    # docs/specs/archive/spec-audio-formats.md), so a second stream fails the cheap
    # attempt outright rather than needing an index-based selector to keep it
    # out; that is what lets stream_limit=1 coexist with a blind "-map 0:a?"
    # below, the muxer-enforced exemption docs/design/degradation-ladder.md
    # names, rather than WAV's index-named one.
    #
    # "-map 0:disp:attached_pic?" (docs/specs/spec-stream-disposition.md): the
    # disposition specifier maps an embedded cover picture and nothing else --
    # measured, it never matches a real video stream, so this cheap attempt
    # still never sees one. "-c copy" replaces "-c:a copy" deliberately: with
    # no codec option covering the picture, ffmpeg would re-encode it to the
    # muxer's default instead of copying it, an undeclared loss the mask would
    # hide; "-c copy" behaves identically to "-c:a copy" for the audio stream
    # since the map now selects only audio and pictures.
    cheap_attempt=Attempt(
        label="remux",
        options=flags("-map 0:a? -map 0:disp:attached_pic? -c copy"),
        # partial_mapping's success-side verification (docs/design/degradation-
        # ladder.md) already names a dropped stream precisely when the ladder
        # actually drops one; this line is the standing note the audio-formats
        # spec's gate chose to keep alongside it -- always true, so it costs
        # nothing to state even for the many files that had nothing to lose.
        # (Now stale for cover art specifically -- issue #78, a dependent of
        # this one, retires it once the verifier's per-stream note is the only
        # place that claim needs to live.)
        notes=("non-audio streams, including cover art, are not carried into MP3",),
    ),
    explicit_streams=False,
    # "-map 0:a?" selects no video, subtitle or attachment stream, so any of
    # those a source carries is left behind without ffmpeg ever complaining.
    partial_mapping=True,
    rules={
        "audio": StreamRule(
            copy_mask=frozenset({"mp3"}),
            # stream_limit=1 means at most one output audio stream ever exists,
            # so the position placeholder StreamRule's docstring describes is
            # left out -- there is only ever "{n} == 0" to substitute.
            accept_options=flags("-c:a copy"),
            fallback_options=flags("-c:a libmp3lame -q:a 2"),
            fallback_name="mp3",
            stream_limit=1,
        ),
        # Accept-anything mask, the same mechanism MKV's attachment rule uses
        # (_AcceptAnyCodec above): the decision resting on this rule is the
        # disposition, not the codec, so enumerating codec names would repeat
        # the phase-4 mistake the MP4 attachment rule corrected. No
        # stream_limit: one "-map 0:disp:attached_pic?" carries *every*
        # picture a source holds (measured), so a limit of 1 would report a
        # carried picture as dropped (Prior decisions, spec-stream-disposition.md).
        "attached_pic": StreamRule(
            copy_mask=_AcceptAnyCodec(),
            accept_options=flags("-c:v:{n} copy"),
        ),
    },
    last_resort=Attempt(
        label="re-encode",
        options=flags("-map 0:a:0 -c:a libmp3lame -q:a 2"),
        # Rescues the one case the selective rung cannot: a mask hit whose
        # -c:a copy the mp3 muxer refuses regardless. Explicit-index, so unlike
        # the selective rung it cannot name a per-stream drop itself -- this is
        # the only place that information about it exists.
        notes=(
            "non-audio streams, and any audio stream beyond the first, are not carried into MP3",
        ),
    ),
)

FLAC = Profile(
    label="FLAC",
    name="flac",
    description="Audio: single stream, lossless FLAC",
    target_suffix=".flac",
    container_options=(),
    # Same blind-by-type shape and the same reason as MP3's above: the flac
    # muxer enforces "at most one audio stream" itself.
    #
    # Same disposition addition as MP3's, and the same "-c copy" reasoning --
    # see its comment (docs/specs/spec-stream-disposition.md).
    cheap_attempt=Attempt(
        label="remux",
        options=flags("-map 0:a? -map 0:disp:attached_pic? -c copy"),
        # Stale for cover art -- see MP3's identical note and its comment.
        notes=("non-audio streams, including cover art, are not carried into FLAC",),
    ),
    explicit_streams=False,
    partial_mapping=True,
    rules={
        "audio": StreamRule(
            copy_mask=frozenset({"flac"}),
            accept_options=flags("-c:a copy"),
            fallback_options=flags("-c:a flac"),
            # No fallback_name: encoding into a container's own lossless codec
            # gives up nothing, the same rule WAV's PCM fallback carries.
            stream_limit=1,
        ),
        # Same accept-anything shape as MP3's -- see its comment.
        "attached_pic": StreamRule(
            copy_mask=_AcceptAnyCodec(),
            accept_options=flags("-c:v:{n} copy"),
        ),
    },
    last_resort=Attempt(
        label="re-encode",
        options=flags("-map 0:a:0 -c:a flac"),
        # Unlike MP3's, this note names no codec loss -- flac is lossless --
        # only the streams -map 0:a:0 cannot reach, the same information MP3's
        # last-resort note carries for the same structural reason.
        notes=(
            "non-audio streams, and any audio stream beyond the first, are not carried into FLAC",
        ),
    ),
)

M4A = Profile(
    label="M4A",
    name="m4a",
    description="Audio: every stream the source has; most players use only the first",
    target_suffix=".m4a",
    container_options=(),
    # ".m4a" auto-selects the "ipod" muxer, whose accept set is narrower than a
    # standard MP4's -- it rejects mp3, opus and flac stream copies -- so the
    # mask below is curated by hand rather than reused from MP4_AUDIO_CODECS
    # (docs/specs/archive/spec-audio-formats.md).
    #
    # Same disposition addition as MP3's cheap attempt, and the same reason
    # "-c:a copy" becomes "-c copy": trap 1 in
    # docs/specs/spec-stream-disposition.md. Measured, this one matters most --
    # the ipod muxer's *default* video encoder is h264, which ipod then
    # rejects, so leaving "-c:a copy" in place would fail every artwork-bearing
    # "--to m4a" at rung 1 rather than silently mis-encoding as mp3/flac would.
    cheap_attempt=Attempt(
        label="remux",
        options=flags("-map 0:a? -map 0:disp:attached_pic? -c copy"),
        # Stale for cover art -- see MP3's identical note and its comment.
        notes=("non-audio streams, including cover art, are not carried into M4A",),
    ),
    explicit_streams=False,
    partial_mapping=True,
    rules={
        "audio": StreamRule(
            copy_mask=frozenset({"aac", "alac"}),
            # No stream_limit: the ipod muxer holds several audio streams, so
            # every one the source has is carried rather than one kept and the
            # rest silently dropped -- unlike mp3/flac, whose muxers enforce
            # exactly one. The position placeholder is required here, unlike
            # mp3/flac's bare form: ffmpeg's unindexed "-c:a" options are not
            # positional -- when several are given, the *last* one wins for
            # every audio output stream, not one per stream in map order
            # (measured against ffmpeg 9.0: a two-stream source with one
            # mask hit and one miss had its accepted stream silently
            # re-encoded anyway). MP4's video/audio rules already carry this
            # placeholder for the same reason.
            accept_options=flags("-c:a:{n} copy"),
            fallback_options=flags("-c:a:{n} aac -b:a:{n} 192k"),
            fallback_name="aac",
        ),
        # Same accept-anything shape as MP3's -- see its comment.
        "attached_pic": StreamRule(
            copy_mask=_AcceptAnyCodec(),
            accept_options=flags("-c:v:{n} copy"),
        ),
    },
    last_resort=Attempt(
        label="re-encode",
        options=flags("-map 0:a:0 -c:a aac -b:a 192k"),
        notes=(
            "non-audio streams, and any audio stream beyond the first, are not carried into M4A",
        ),
    ),
)

OGG = Profile(
    label="OGG",
    name="ogg",
    description="Audio: every stream the source has; most players use only the first",
    target_suffix=".ogg",
    container_options=(),
    # "-c copy" rather than "-c:a copy": the ogg muxer's own video codec is
    # theora, so mapping video here would pass a theora source straight
    # through as a whole video file renamed ".ogg" -- the same defect that
    # rules m4a out. The cheap attempt maps audio only, so the two spellings
    # behave identically; "-c copy" is what the spec pins.
    cheap_attempt=Attempt(
        label="remux",
        options=flags("-map 0:a? -c copy"),
        notes=("non-audio streams, including cover art, are not carried into OGG",),
    ),
    explicit_streams=False,
    partial_mapping=True,
    rules={
        "audio": StreamRule(
            # The ogg muxer accepts vorbis, opus and flac as-is; it rejects
            # mp3 and aac (docs/specs/archive/spec-audio-formats.md).
            copy_mask=frozenset({"vorbis", "opus", "flac"}),
            # No stream_limit: the ogg muxer holds several audio streams. The
            # position placeholder is required for the same reason m4a's
            # audio rule carries one -- see its comment.
            accept_options=flags("-c:a:{n} copy"),
            fallback_options=flags("-c:a:{n} libvorbis -q:a:{n} 5"),
            fallback_name="vorbis",
        ),
    },
    last_resort=Attempt(
        label="re-encode",
        options=flags("-map 0:a:0 -c:a libvorbis -q:a 5"),
        notes=(
            "non-audio streams, and any audio stream beyond the first, are not carried into OGG",
        ),
    ),
)

OPUS = Profile(
    label="OPUS",
    name="opus",
    description="Audio: every stream the source has; most players use only the first",
    target_suffix=".opus",
    container_options=(),
    # "-c copy": on the happy path the muxer, not the copy mask, decides --
    # the opus muxer also accepts a Vorbis stream, so a blind copy can ship a
    # file whose extension lies about its contents. That risk is accepted
    # (Prior decisions, spec-audio-formats.md: "opus copies") because forcing
    # every already-Opus file through libopus would be a real generation loss
    # on the common case to prevent a mislabel reachable only from an Ogg
    # source.
    cheap_attempt=Attempt(
        label="remux",
        options=flags("-map 0:a? -c copy"),
        notes=("non-audio streams, including cover art, are not carried into OPUS",),
    ),
    explicit_streams=False,
    partial_mapping=True,
    rules={
        "audio": StreamRule(
            copy_mask=frozenset({"opus"}),
            # "opus does not copy" describes the cheap attempt alone; the
            # selective rung does, on a mask hit -- an empty accept_options,
            # WAV's precedent, would emit a map with no codec option and
            # produce an undeclared re-encode instead (Prior decisions,
            # spec-audio-formats.md). The spec's Prior decisions row pins this
            # as the bare flags("-c:a copy"); review measured that bare form
            # broken against a real multi-stream, mixed accept/fallback
            # source (see m4a's audio rule comment) and the spec was amended
            # accordingly -- this carries the position placeholder like the
            # other two new profiles rather than the row's original text.
            accept_options=flags("-c:a:{n} copy"),
            # No stream_limit: the opus muxer holds several audio streams, by
            # copy and by encode.
            fallback_options=flags("-c:a:{n} libopus -b:a:{n} 128k"),
            fallback_name="opus",
        ),
    },
    last_resort=Attempt(
        label="re-encode",
        options=flags("-map 0:a:0 -c:a libopus -b:a 128k"),
        notes=(
            "non-audio streams, and any audio stream beyond the first, are not carried into OPUS",
        ),
    ),
)

#: Phase 5 (`docs/specs/archive/spec-image-formats.md`): the image2 muxer -- the one
#: behind PNG, JPEG, TIFF and BMP -- accepts *any* video codec under
#: ``-c copy``, so a stream copy would ship a mislabelled file (measured:
#: ``flat.jpg -c copy out.png`` exits 0 and writes a JPEG named ``.png``).
#: Every profile below forces its encoder in the cheap attempt instead, and the
#: copy mask -- and the copy branch it drives on the rarely-reached selective
#: rung -- exists only for the case a source's video stream already carries the
#: target's own codec.
#:
#: The same muxer also refuses to write more than one frame to one output file
#: ("Cannot write more than one file with the same name"), so a multi-frame
#: source fails both the cheap attempt and the selective rung; only the
#: ``last_resort`` below, which adds ``-frames:v 1``, can turn a video into a
#: still. A source with two video streams (cover art beside the real one) hits
#: the same failure for the same reason, which is what ``stream_limit=1``
#: (muxer-enforced, not mapping-enforced -- the cheap attempt still maps
#: ``0:v?`` blindly) is for.
#:
#: The ``last_resort``'s explicit ``-map 0:v:0`` selects only the first video
#: stream and nothing else, the same shape MP3's and FLAC's index-named
#: last-resort above uses -- so, like theirs, it cannot name a per-stream drop
#: itself and carries a standing note for whatever it structurally cannot
#: reach (docs/design/degradation-ladder.md: "Every rung carries its own
#: notes").
PNG = Profile(
    label="PNG",
    name="png",
    description="Image: force-encoded to PNG, lossless",
    target_suffix=".png",
    container_options=(),
    cheap_attempt=Attempt(label="force-encode", options=flags("-map 0:v? -c:v png")),
    explicit_streams=False,
    partial_mapping=True,
    rules={
        "video": StreamRule(
            copy_mask=frozenset({"png"}),
            accept_options=flags("-c:v copy"),
            fallback_options=flags("-c:v png"),
            # No fallback_name: re-encoding into PNG's own lossless codec
            # gives up nothing worth naming.
            fallback_name=None,
            stream_limit=1,
        ),
    },
    last_resort=Attempt(
        label="single-frame",
        options=flags("-map 0:v:0 -frames:v 1 -c:v png"),
        notes=(
            "only the first frame was kept; PNG cannot hold more than one image",
            "non-video streams, and any video stream beyond the first, are not carried into PNG",
        ),
    ),
)

JPG = Profile(
    label="JPG",
    name="jpg",
    description="Image: force-encoded to JPEG; transparency is not carried",
    target_suffix=".jpg",
    container_options=(),
    cheap_attempt=Attempt(
        label="force-encode",
        options=flags("-map 0:v? -c:v mjpeg -q:v 2"),
        # Standing note, not a fallback-branch one: this cheap attempt always
        # wins for an ordinary single-frame image (it forces the encoder
        # unconditionally), so it is the only rung whose notes are ever
        # actually reported for the overwhelming majority of inputs.
        notes=("transparency is not carried by JPEG; the image was re-encoded",),
    ),
    explicit_streams=False,
    partial_mapping=True,
    rules={
        "video": StreamRule(
            copy_mask=frozenset({"mjpeg"}),
            accept_options=flags("-c:v copy"),
            fallback_options=flags("-c:v mjpeg -q:v 2"),
            fallback_name="mjpeg",
            stream_limit=1,
        ),
    },
    last_resort=Attempt(
        label="single-frame",
        options=flags("-map 0:v:0 -frames:v 1 -c:v mjpeg -q:v 2"),
        # Carries the cheap attempt's own transparency note too: this rung
        # re-encodes just as the cheap attempt does, and the cheap attempt's
        # standing note only actually prints for a source that never reaches
        # here.
        notes=(
            "only the first frame was kept; JPEG cannot hold more than one image",
            "transparency is not carried by JPEG; the image was re-encoded",
            "non-video streams, and any video stream beyond the first, are not carried into JPEG",
        ),
    ),
)

TIFF = Profile(
    label="TIFF",
    name="tiff",
    description="Image: force-encoded to TIFF, lossless",
    target_suffix=".tiff",
    container_options=(),
    cheap_attempt=Attempt(label="force-encode", options=flags("-map 0:v? -c:v tiff")),
    explicit_streams=False,
    partial_mapping=True,
    rules={
        "video": StreamRule(
            copy_mask=frozenset({"tiff"}),
            accept_options=flags("-c:v copy"),
            fallback_options=flags("-c:v tiff"),
            fallback_name=None,
            stream_limit=1,
        ),
    },
    last_resort=Attempt(
        label="single-frame",
        options=flags("-map 0:v:0 -frames:v 1 -c:v tiff"),
        notes=(
            "only the first frame was kept; TIFF cannot hold more than one image",
            "non-video streams, and any video stream beyond the first, are not carried into TIFF",
        ),
    ),
)

BMP = Profile(
    label="BMP",
    name="bmp",
    description="Image: force-encoded to BMP, lossless",
    target_suffix=".bmp",
    container_options=(),
    cheap_attempt=Attempt(label="force-encode", options=flags("-map 0:v? -c:v bmp")),
    explicit_streams=False,
    partial_mapping=True,
    rules={
        "video": StreamRule(
            copy_mask=frozenset({"bmp"}),
            accept_options=flags("-c:v copy"),
            fallback_options=flags("-c:v bmp"),
            fallback_name=None,
            stream_limit=1,
        ),
    },
    last_resort=Attempt(
        label="single-frame",
        options=flags("-map 0:v:0 -frames:v 1 -c:v bmp"),
        notes=(
            "only the first frame was kept; BMP cannot hold more than one image",
            "non-video streams, and any video stream beyond the first, are not carried into BMP",
        ),
    ),
)

#: Phase 5 (`docs/specs/archive/spec-image-formats.md`): the animated-capable trio.
#: ``gif`` and ``webp`` write every frame of a multi-frame source -- an
#: animation, not a still -- so unlike the image2 four above, neither carries a
#: frame limit anywhere. ``avif``'s muxer silently keeps only one frame no
#: matter what is asked of it (measured: dropping ``-still-picture 1`` still
#: yields one frame), so its reduction can only ever be *named*, never avoided,
#: which is why it carries a standing note instead of a `last_resort` shaped
#: around extraction.
#:
#: ``webp``'s muxer self-polices (a non-matching codec copy exits 127, "webp
#: muxer supports only codec webp"), so it keeps a bare ``-c copy`` cheap
#: attempt safely -- it loses neither alpha nor frames, so no standing note's
#: reachability depends on which rung wins. ``gif`` and ``avif`` are different:
#: their drafted copy-based cheap attempt only ever won for a source already in
#: that format, the one input with nothing to lose, so both force their encoder
#: instead -- the cheap attempt then always wins and both standing notes always
#: print. Measured, this costs `gif` only CPU (a GIF source re-encodes through
#: `-c:v gif` pixel-identically) and costs `avif` a real generation loss plus
#: several seconds per already-AVIF file, accepted so its transparency and
#: frame losses are named rather than left silent.
#:
#: All three still declare `stream_limit=1`: none of these muxers holds more
#: than one video *stream* (a second one -- cover art beside an animation --
#: fails the cheap attempt outright), which is orthogonal to how many *frames*
#: the one stream it does hold may carry.
GIF = Profile(
    label="GIF",
    name="gif",
    description="Image: force-encoded to GIF, animated; a photograph is reduced to 256 colours",
    target_suffix=".gif",
    container_options=(),
    cheap_attempt=Attempt(
        label="force-encode",
        options=flags("-map 0:v? -c:v gif"),
        # Standing notes, not fallback-branch ones: this cheap attempt always
        # wins (it forces the encoder unconditionally), so it is the only rung
        # whose notes are ever actually reported for the overwhelming majority
        # of inputs -- the same shape JPG's cheap-attempt note is.
        notes=(
            "transparency is not carried by GIF",
            "colours are reduced to GIF's 256-colour palette",
        ),
    ),
    explicit_streams=False,
    partial_mapping=True,
    rules={
        "video": StreamRule(
            copy_mask=frozenset({"gif"}),
            accept_options=flags("-c:v copy"),
            fallback_options=flags("-c:v gif"),
            # Declared, unlike PNG/TIFF/BMP: GIF is a 256-colour palette format,
            # not a lossless one, so the selective rung's re-encode branch must
            # name the quantisation the same way JPG's "mjpeg" does.
            fallback_name="gif",
            stream_limit=1,
        ),
    },
    last_resort=Attempt(
        label="re-encode",
        options=flags("-map 0:v:0 -c:v gif"),
        notes=(
            # Repeats the cheap attempt's own standing notes: this rung is only
            # reached when that attempt failed, so its notes never printed --
            # the same reasoning JPG's last_resort carries its transparency
            # note for.
            "transparency is not carried by GIF",
            "the image was re-quantised to GIF's 256-colour palette",
            "non-video streams, and any video stream beyond the first, are not carried into GIF",
        ),
    ),
)

#: WebP's muxer self-polices and loses neither alpha nor frames (measured), so
#: it is the one target in this trio that keeps a bare copy-based cheap
#: attempt -- see the block comment above GIF for the full reasoning.
WEBP = Profile(
    label="WEBP",
    name="webp",
    description="Image: copies compatible streams, animated; falls back to WebP re-encode",
    target_suffix=".webp",
    container_options=(),
    cheap_attempt=Attempt(label="remux", options=flags("-map 0:v? -c copy")),
    explicit_streams=False,
    partial_mapping=True,
    rules={
        "video": StreamRule(
            copy_mask=frozenset({"webp"}),
            accept_options=flags("-c:v copy"),
            fallback_options=flags("-c:v libwebp -quality:v 80"),
            # Declared: the fallback is a real, lossy re-encode (quality 80),
            # unlike PNG/TIFF/BMP's lossless one, so it must be named.
            fallback_name="webp",
            stream_limit=1,
        ),
    },
    last_resort=Attempt(
        label="re-encode",
        options=flags("-map 0:v:0 -c:v libwebp -quality:v 80"),
        notes=(
            "the image was re-encoded to WebP (lossy)",
            "non-video streams, and any video stream beyond the first, are not carried into WEBP",
        ),
    ),
)

AVIF = Profile(
    label="AVIF",
    name="avif",
    description="Image: force-encoded to AVIF; a multi-frame source is reduced to a single frame",
    target_suffix=".avif",
    container_options=(),
    cheap_attempt=Attempt(
        label="force-encode",
        options=flags("-map 0:v? -c:v libaom-av1 -crf:v 30 -still-picture 1"),
        # Standing notes: the cheap attempt always wins (forced encoder), so
        # this is the only place AVIF's one silent loss this phase cannot
        # avoid -- the muxer keeps one frame no matter what is asked of it --
        # is ever actually named.
        notes=(
            "transparency is not carried by AVIF",
            "a multi-frame source is reduced to a single frame",
        ),
    ),
    explicit_streams=False,
    partial_mapping=True,
    rules={
        "video": StreamRule(
            copy_mask=frozenset({"av1"}),
            accept_options=flags("-c:v copy"),
            fallback_options=flags("-c:v libaom-av1 -crf:v 30 -still-picture 1"),
            fallback_name="av1",
            stream_limit=1,
        ),
    },
    last_resort=Attempt(
        label="re-encode",
        options=flags("-map 0:v:0 -c:v libaom-av1 -crf 30 -still-picture 1"),
        notes=(
            "transparency is not carried by AVIF",
            "a multi-frame source is reduced to a single frame",
            "non-video streams, and any video stream beyond the first, are not carried into AVIF",
        ),
    ),
)

#: Target name -> profile. Built from each profile's own ``name`` rather than
#: repeating it as a literal key, so the two can never drift apart.
PROFILES: dict[str, Profile] = {
    profile.name: profile
    for profile in (
        MP4,
        WAV,
        MKV,
        MOV,
        MP3,
        FLAC,
        WEBM,
        M4A,
        OGG,
        OPUS,
        PNG,
        JPG,
        TIFF,
        BMP,
        GIF,
        WEBP,
        AVIF,
    )
}

#: The curated set of suffixes discovery walks (`docs/design/source-selection.md`):
#: a file is a candidate only if its suffix is in this set, never discovered from
#: what ffmpeg happens to accept. Phase 2 seeds it with exactly what the old
#: ``video``/``audio`` sub-commands read (``.mkv``, ``.opus``) plus each shipped
#: profile's own target suffix (``.mp4``, ``.wav``) -- the latter is what lets a
#: source that already carries the target suffix take part in selection at all
#: (the self-write and existing-output-skip cases `source-selection.md` and this
#: phase's QA gate both need). Phase 3 (issue #20, `spec-audio-formats.md`) widens
#: it three ways: the audio containers people actually have that were not yet
#: readable as a source, the video containers a "rip the audio" run needs, and the
#: remaining audio target suffixes (``.mp3``, ``.m4a``, ``.flac``, ``.ogg``) so the
#: profiles this milestone still adds already have their own suffix covered when
#: they land -- `.opus` and `.wav` are covered already. Phase 4 (issue #26,
#: `spec-video-formats.md`) widens it once more with the video containers no
#: earlier phase added, ahead of the `mkv`/`webm`/`mov` profiles that milestone
#: still adds. Phase 5 (issue #33, `spec-image-formats.md`) widens it once more
#: with the image containers the seven image profiles that milestone still adds
#: will need, ahead of those profiles landing. None of them re-adds a suffix this
#: set already holds.
SOURCE_SUFFIXES: frozenset[str] = frozenset(
    {
        # phase 2: old sub-commands plus the two shipped profiles' own suffixes
        ".mkv",
        ".mp4",
        ".opus",
        ".wav",
        # phase 3: audio containers people actually have
        ".aac",
        ".m4b",
        ".wma",
        ".aiff",
        ".aif",
        ".ape",
        ".wv",
        ".caf",
        # phase 3: video containers a "rip the audio" run needs
        ".mov",
        ".avi",
        ".webm",
        ".m4v",
        ".wmv",
        ".flv",
        # phase 3: the remaining audio target suffixes, ahead of their profiles
        ".mp3",
        ".m4a",
        ".flac",
        ".ogg",
        # phase 4: video containers no earlier phase added
        ".mpg",
        ".mpeg",
        ".ts",
        ".m2ts",
        ".mts",
        ".vob",
        ".ogv",
        ".3gp",
        # phase 5: image containers ahead of the seven image profiles
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".avif",
        ".gif",
        ".tif",
        ".tiff",
        ".bmp",
        ".ppm",
        ".pgm",
        ".tga",
    }
)


def resolve_target(target: str) -> Profile:
    """Look up *target* in ``PROFILES``, accepting a name or a dotted suffix.

    ``mp4``, ``MP4`` and ``.mp4`` all resolve to the same profile (Prior
    decisions, ``spec-target-driven-cli.md``). An unknown target is a usage
    error, not a conversion failure -- the same shape as ``--jobs`` being out
    of range -- so it is raised as a plain ``ValueError`` for ``cli.py`` to
    turn into its exit-2 ``UsageError``, with a message that lists every
    target actually available rather than just naming the typo.
    """
    name = target.lower().removeprefix(".")
    try:
        return PROFILES[name]
    except KeyError:
        available = ", ".join(sorted(PROFILES))
        raise ValueError(f"unknown target {target!r}; available targets: {available}") from None

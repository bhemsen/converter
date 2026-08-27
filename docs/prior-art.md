# Prior Art

> Descriptive, living document. Indexed BY CONCERN, not by project. Add
> entries whenever new references surface; gaps are fine.
>
> Tag each concern header with the one roadmap phase it feeds: `(Phase N)` for a
> roadmap P-number or `(feature: <slug>)` for a Features-table row (one tag, not
> both) — so `/loopkit:plan` can resolve "prior art for phase N" deterministically.

## Challenge summary

The three challenge questions, answered from the findings below. Scope and
non-goals in `docs/vision.md` derive from these.

**Existence — does something already solve this well enough?** No, but the gap is
narrower than it looks. The landscape splits into GUI tools that can do everything
(HandBrake, Shutter Encoder, FFmpeg Batch AV Converter, fre:ac, FastFlix) and raw
ffmpeg plus a shell script. `HandBrakeCLI` has presets but no recursive directory
batch — batch there means a shell loop. Nothing in between covers a scriptable CLI
that walks a tree, is driven by the target format, and accounts for what it lost.
"Another format converter" would be redundant; this is not, but only because of
the USP below.

**USP.** A CLI converter that turns a whole directory tree into a target format,
sacrificing as little as possible automatically and **naming what it sacrificed**,
and that on a second run only touches the files that are still missing.

Format coverage is not the differentiator — ffmpeg has that. Loss accounting is:
"what broke during conversion" is the question the free tools leave unanswered,
and the reason they half-finish the job. The pattern already exists in this
codebase (`Attempt.notes`, the remux to selective to re-encode ladder); it is
merely nailed to two format pairs.

**Differentiation / non-goals.** Deliberate stops where others continue: no GUI,
no trimming or cutting (LosslessCut), no filter-graph access, no encoder-tuning
surface (FastFlix), no HEIC/SVG support, no EXIF/ICC preservation. The last one is
evidenced, not assumed — see the image-conversion concern.

## Container/codec capability modelling (Phase 1)

### HandBrake/HandBrake

- Path: `preset/preset_template.json`
- License: GPL-2.0
- Verdict: reference-only — the data model is exactly right, the surface area is not
- Date: 2026-08-19
- Notes:
  - ADOPT: the copy-mask plus fallback vocabulary, as data per target format.
    `"FileFormat": "mp4"`, `"AudioCopyMask": ["copy:aac", "copy:ac3", "copy:dts",
    "copy:eac3", "copy:flac", "copy:mp3", "copy:truehd"]`,
    `"AudioEncoderFallback": "ac3"`, `"MetadataPassthru": true`. The `copy:<codec>`
    notation expresses "copy if it is this codec, otherwise encode" in ONE
    vocabulary — which is what `MP4_VIDEO_CODECS` / `MP4_AUDIO_CODECS` in
    `converter/jobs.py` already are, only as Python constants per job instead of
    data per target.
  - AVOID: the preset schema as a whole (roughly 200 fields). HandBrake presets are
    an encoder-tuning surface; that is an explicit non-goal here.

### FFmpeg/FFmpeg (the CLI as a capability source)

- Path: `ffmpeg -formats`, `ffmpeg -muxers`, `ffmpeg -codecs`, `ffmpeg -h muxer=<name>`
- License: LGPL-2.1-or-later / GPL-2.0-or-later
- Verdict: avoid — as a source for the compatibility matrix
- Date: 2026-08-19
- Notes:
  - ADOPT: nothing for the matrix. `-formats` is still useful to verify at runtime
    that a build actually has a muxer enabled before promising a target format.
  - AVOID: deriving container-to-codec compatibility from the CLI. The CLI lists
    what EXISTS (a default ffmpeg 8.x build reports roughly 460 codecs and 370
    formats), never which codec is LEGAL in which muxer — that lives in
    libavformat's C structures and is reachable only through the libraries. An
    auto-discovery design is a trap: the mask must be curated, exactly as
    `MP4_VIDEO_CODECS` is today.

### bhemsen/converter (this codebase)

- Path: `converter/jobs.py`
- License: MIT
- Verdict: reuse — the mechanism stays, its coupling to format pairs does not
- Date: 2026-08-19
- Notes:
  - ADOPT: trial-and-fallback. Attempt the cheap stream copy first; only on a
    non-zero exit spend an ffprobe round-trip and degrade deliberately
    (`mp4_remux` to `_mp4_selective` to `mp4_reencode`). ffprobe never runs on
    the happy path of an *exhaustive* cheap attempt — issue #18 narrowed this
    to admit one probe on the success of a mapping that is partial by
    construction, which is what keeps the loss accounting honest.
    Combined with HandBrake's copy mask this gets both: the mask
    PREDICTS a doomed attempt, trial-and-fallback remains the safety net for what
    the mask gets wrong.
  - AVOID: writing the ladder per format pair. `mp4_retries` and `wav_retries` are
    hand-written per pair, which does not scale to a target-driven matrix.

## Format-driven converter CLI (Phase 2)

### jgm/pandoc

- Path: `src/Text/Pandoc/App.hs`, `--from` / `--to` option handling
- License: GPL-2.0-or-later
- Verdict: reference-only
- Date: 2026-08-19
- Notes:
  - ADOPT: readers plus writers instead of format pairs — N+M implementations
    rather than N*M, mediated by one intermediate representation. The analogue
    here is the ffprobe stream list (reader) plus a target profile (writer). This
    is the direct precedent for choosing a target-format-driven CLI over named
    sub-commands per pair.
  - AVOID: a full AST with filters. Media streams are not document trees; an
    intermediate representation beyond "list of streams plus target profile"
    would be overhead with no payoff.

### ImageMagick/ImageMagick

- Path: `MagickCore/constitute.c` (output format derived from the target filename)
- License: ImageMagick (Apache-2.0-like)
- Verdict: reference-only
- Date: 2026-08-19
- Notes:
  - ADOPT: infer the target format from the output extension. When the target is
    already written down, no flag is needed to repeat it.
  - AVOID: adopting it as an image backend. That would be a second external
    dependency, which the inception ruled out in favour of ffmpeg-only coverage.

### Batch conversion in the field

- Path: paulpacifico/shutter-encoder, eibols/ffmpeg_batch, HandBrake `HandBrakeCLI`
- License: GPL-3.0 (shutter-encoder), GPL-3.0 (ffmpeg_batch), GPL-2.0 (HandBrake)
- Verdict: reference-only
- Date: 2026-08-19
- Notes:
  - ADOPT: bound parallelism by CPU threads, which FFmpeg Batch AV Converter does
    and `converter/batch.py` already does via `default_jobs()`.
  - AVOID: the GUI-first shape all three share. `HandBrakeCLI`'s missing recursive
    batch is precisely the gap this project keeps filling.

## Python wrapper structure around the ffmpeg CLI (Phase 3, Phase 4)

### slhck/ffmpeg-normalize

- Path: `ffmpeg_normalize/_media_file.py`, `_streams.py`, `_cmd_utils.py`, `_errors.py`
- License: MIT
- Verdict: reference-only — independent confirmation of the existing layering
- Date: 2026-08-19
- Notes:
  - ADOPT: the layering, as a sanity check rather than as code. `MediaFile` plus
    `AudioStream`/`VideoStream`/`SubtitleStream` plus a command builder plus
    dedicated exception classes is the same split this codebase arrived at
    independently (`ffmpegtool.Stream`, `build_argv`, `FfmpegMissingError`,
    `ProbeError`). Convergence on the same shape is evidence it is the right one.
  - AVOID: parsing values out of ffmpeg's stderr to drive a second pass. Scraping
    ffmpeg output is brittle across versions and is not needed for conversion.

## Image conversion through ffmpeg (Phase 5)

### ffmpeg image muxers and metadata behaviour

- Path: `libavcodec/pngenc.c`, `libavformat/avifenc.c`, `libavcodec/webpenc.c`
- License: LGPL-2.1-or-later
- Verdict: reference-only
- Date: 2026-08-19
- Notes:
  - ADOPT: pixel conversion is genuinely covered — PNG, JPEG, WebP, AVIF, TIFF,
    BMP and GIF all have working ffmpeg muxers, so images need no second backend.
  - AVOID: promising EXIF/ICC preservation. Conversion tools strip metadata by
    default to keep files small, and PNG cannot carry EXIF at all by construction.
    WebP and AVIF *can* hold EXIF/XMP/ICC, but whether it survives depends on the
    tool, not the format. Document this as a non-goal rather than treating it as a
    bug. HEIC and SVG stay out of scope for the same class of reason: they need
    libheif or a rasteriser, not an ffmpeg muxer.

## Cover art and stream disposition (Phase 6)

### beetbox/beets — the `convert` plugin

- Path: `beetsplug/convert.py`, documented in `docs/plugins/convert.rst`
- License: MIT
- Verdict: reference-only — adopt the stance, not the mechanism
- Date: 2026-08-26
- Notes:
  - ADOPT: artwork is a **first-class, default-on concern** of a conversion
    pipeline, not an incidental stream. beets ships `embed: yes` as the default
    for transcoded items, plus a separate `copy_album_art` for the album-level
    case. The lesson for this project is the stance: a converter that touches
    music has to *decide* about artwork explicitly. Phases 3 and 5 both hit the
    consequence of not deciding — a picture stream that is silently dropped, or
    silently truncated to one frame.
  - AVOID: the mechanism and the surface. beets embeds through a tag library
    (`mediafile`), which here would be a second runtime dependency and is ruled
    out by `docs/vision.md`. Its `album_art_maxwidth` downscaling is an asset
    tuning surface, an explicit non-goal. This project can only do it through
    ffmpeg's own disposition, or not at all.

### ffprobe's `stream_disposition` (measured, not searched)

- Path: `ffprobe -show_entries stream=...:stream_disposition=attached_pic`
- License: LGPL-2.1-or-later / GPL-2.0-or-later
- Verdict: reuse — this is the whole mechanism
- Date: 2026-08-26
- Notes:
  - ADOPT: one probe query returns the disposition alongside the fields
    `probe_streams` already asks for. Measured on ffmpeg 9.0: an MP3 with cover
    art yields `0,mp3,audio,0` and `1,png,video,1`; a plain h264 file yields
    `0,h264,video,0`. So the cost is one extra `-show_entries` clause, one field
    on `Stream`, and one branch in the engine — materially cheaper than the
    "engine change" framing `docs/specs/archive/spec-audio-formats.md` recorded when the
    idea was first deferred.
  - AVOID: inferring artwork from the codec name. `mjpeg` and `png` are the codecs
    of both a cover picture and a real video stream, which is exactly why `m4a`
    hard-fails on one and silently truncates the other (measured in phase 3).
    Disposition is the only honest discriminator.

### bhemsen/converter (this codebase)

- Path: `converter/ffmpegtool.py` (`Stream`, `probe_streams`), `converter/jobs.py`
- License: MIT
- Verdict: reuse — the gap is named, the shape is known
- Date: 2026-08-26
- Notes:
  - ADOPT: the deferral is already documented with its cost, in
    `docs/specs/archive/spec-audio-formats.md`'s "Two roadmap candidates this phase
    deliberately does not take". This phase cashes it in rather than rediscovering
    it.
  - AVOID: re-opening the phase-3 gate decision. Audio profiles currently drop
    every video stream and say so in a standing note; once disposition exists, the
    note narrows rather than disappears — a real video stream under `--to mp3` is
    still dropped, and still has to be named.

## Generation-loss advisories (Phase 7)

### Curated codec data, reused from Phase 1's concern

- Path: `docs/prior-art.md#containercodec-capability-modelling-phase-1`
- License: n/a — a method, not a source
- Verdict: reuse the method
- Date: 2026-08-26
- Notes:
  - ADOPT: a lossy-codec set is the same kind of artifact as a copy mask —
    curated by hand, for the reasons in AVOID below. The Phase 1 concern supplies
    the *shape*, not the reason: its claim is about which codec a muxer legally
    accepts, which is a different question from whether a codec is lossy.
  - AVOID: deriving lossiness from ffmpeg — but **not** for the reason first
    recorded here. ffmpeg does ship the classification (`-codecs`, column `L` for
    lossy and `S` for lossless), and it gets every awkward case right: `alac`,
    `flac`, `wmalossless`, `truehd` and `pcm_s16le` all report `S`. It is still
    not usable as the source of truth: `webp` reports **both**, so the descriptor
    cannot say whether *this* instance was lossy; reading it costs a subprocess
    this project does not otherwise spend; and it answers a different question
    than this tool asks — `gif` reports lossless, while phase 5 measured a
    photograph through `-c:v gif` keeping 182 of 36 485 colours.
  - **The gap this entry recorded is now closed, and one half of it resolved
    differently than expected.** The sparring chose research mode `none`, leaving
    it unchecked whether any comparable converter warns about generation loss, and
    whether a maintained lossy-codec list exists to adopt. Checked during the
    phase's `/loopkit:plan` cycle on 2026-08-27: the *principle* is stated
    everywhere — converting an MP3 to FLAC restores nothing, it stores what is
    left in a new wrapper — but no converter surfaced that acts on it, so the
    differentiation is real. A classification, however, *does* exist — in ffmpeg
    itself — and the reason to curate anyway is the AVOID above rather than its
    absence.

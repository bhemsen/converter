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
    (`mp4_remux` to `_mp4_selective` to `mp4_reencode`). ffprobe never runs on the
    happy path. Combined with HandBrake's copy mask this gets both: the mask
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

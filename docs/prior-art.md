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
    construction, and issue #66 a further one on the written output whenever
    that probe is about to report a loss, which is what keeps the loss
    accounting honest in both directions.
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

## Single-file input (Phase 10)

### Single-file converters already recorded under Phase 2's concern

- Path: `docs/prior-art.md#format-driven-converter-cli-phase-2` (pandoc,
  ImageMagick, `HandBrakeCLI`), plus the ffmpeg CLI itself (`-i in out`)
- License: n/a — a method, not a source
- Verdict: reuse the existing entries; no new research
- Date: 2026-09-28
- Notes:
  - ADOPT: a file is a first-class input. Every reference above takes one file by
    default and treats a directory as the special case (or, for `HandBrakeCLI`,
    not at all); this project inverted that, and this phase closes the gap
    without giving up the directory walk.
  - ADOPT: keep `--to` as the single way to name the target. pandoc names the
    output format by flag, independently of any file name, which is the shape
    this CLI already has.
  - AVOID: ImageMagick's inference of the format from the output *file name*,
    recorded as an ADOPT under Phase 2. For this phase it would make `OUTPUT`
    ambiguous — a not-yet-existing `out.mp4` could be a directory or a file — and
    create a second, possibly contradicting source for the target next to `--to`.
    `OUTPUT` therefore stays a directory.
  - AVOID: several positional files. With `INPUT... OUTPUT` the last positional is
    ambiguous, and Windows does not expand globs in the shell, so the convenience
    would be half-delivered on a first-class target.
  - **Gap, by choice:** the sparring chose research mode `none`. The existence
    question answers itself — raw ffmpeg converts one file, but without the
    ladder, the disposition and alpha handling, or the loss notes, which is the
    USP — so no search was needed to justify the phase. Unchecked: how other
    batch CLIs word a file-vs-directory INPUT in `--help` and errors.
  - Foundation impact: vision — yes: the Scope's *In* list gains single-file input next to the recursive batch; constitution — none; architecture — yes: Key flow 1 and `docs/design/source-selection.md` gain the branch where INPUT is a file

## Machine-readable CLI output (Phase 11)

### restic, cargo, docker events — JSON Lines with a type discriminator

- Path: `restic/internal/ui/backup/json.go`
  (<https://github.com/restic/restic/blob/master/internal/ui/backup/json.go>);
  <https://restic.readthedocs.io/en/stable/075_scripting.html>;
  <https://doc.rust-lang.org/cargo/reference/external-tools.html>;
  <https://docs.docker.com/reference/cli/docker/system/events/>;
  <https://jsonlines.org/>
- License: BSD-2-Clause (restic), MIT/Apache-2.0 (cargo), Apache-2.0 (docker CLI)
- Verdict: reference-only
- Date: 2026-09-28
- Notes:
  - ADOPT: one JSON object per line on stdout, human noise on stderr — restic
    (`message_type`: `status`, `summary`, `error`) and cargo (`reason`:
    `compiler-artifact`, `build-finished`) both do exactly this, with a final
    summary object distinguished by a discriminator field.
  - ADOPT: an open schema — docker documents that its event objects may gain
    fields, which is what lets a consumer tolerate a later addition such as
    phase 14's sidecars.
  - AVOID: leaving versioning implicit by accident. None of the three versions
    its per-line schema in-band; whether this tool should is a decision for
    phase 11's `/plan`, not a precedent to copy.
  - AVOID: `ffprobe -of json`'s single document — it cannot be consumed while a
    batch is still running.
  - Research mode: websearch, 2026-09-28. JSON Lines is explicitly "not yet
    standardized" (jsonlines.org).
  - Foundation impact: vision — yes: Scope *In* gains machine-readable per-file output and a stable exit-code contract; constitution — none; architecture — yes: `batch.Result` becomes a public contract and reporting gets one seam for text and JSON

## Abort-safe writes and child-process termination (Phase 12)

### Windows Job Objects, Node's kill semantics, POSIX process groups

- Path: <https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects>;
  <https://nikhilism.com/post/2017/windows-job-objects-process-tree-management/>;
  <https://nodejs.org/api/child_process.html>;
  <https://man7.org/linux/man-pages/man2/pr_set_pdeathsig.2const.html>;
  <https://docs.python.org/3/library/signal.html>;
  <https://github.com/python/cpython/issues/121649>
- License: n/a — platform documentation and a method
- Verdict: adopt the method (Job Object via `ctypes`, no new dependency)
- Date: 2026-09-28
- Notes:
  - ADOPT: on Windows, a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
    Node's `subprocess.kill()` is a `TerminateProcess` there whatever signal
    name is passed, so the Python child can neither catch it nor clean up, and
    the ffmpeg grandchild survives — only the job, closed by the OS when the
    Python process dies, takes it down.
  - ADOPT: on POSIX, signal handlers run in the main thread only, even while
    worker threads block in `subprocess.run()`; the handler must not shut down
    the executor (cpython#121649 is a deadlock report on exactly that). Track
    each ffmpeg `Popen` in a registry, give it its own session, and terminate
    the registry from the handler. Exit 128+n (130 for SIGINT, 143 for SIGTERM)
    — a shell convention the tool should follow when it exits deliberately.
  - ADOPT: a sweep of stale partial files on the next run — the only cleanup a
    Windows kill leaves room for.
  - AVOID: stopping ffmpeg gracefully (`q` on stdin) — it produces a playable
    truncated file, which is worthless when the partial is deleted anyway.
  - AVOID: trusting `os.replace` to be atomic and unconditional on Windows: it
    maps to `MoveFileEx`, and a scanner or indexer holding the target open makes
    it raise `PermissionError`. Several projects retry a bounded number of times
    on Windows only (cpython#143909 discusses the "atomic" wording). The literal
    python.org text was not fetched — re-read it before quoting.
  - **Measured, not searched (ffmpeg 9.0, 2026-09-28):** `-c copy out.mp4.partial`
    fails with "Unable to choose an output format"; the same with `-f mp4`
    succeeds, as do `-f image2`, `-f apng` and `-f ipod` on `.partial` names.
    `ffmpeg -muxers` lists dedicated muxers for `webm`, `opus`, `avif`, `webp`
    and `gif` — the web research had wrongly folded them into `matroska`, `ogg`
    and `image2`, which is why these names are measured rather than cited.
  - Foundation impact: vision — none; constitution — yes: partial-output removal widens to interrupted runs, with write-then-rename and a Windows Job Object recorded in the tech stack; architecture — yes: `ffmpegtool.run()` becomes a tracked, killable process, profiles declare their muxer, and Key flow 1 gains write-then-rename and a termination flow

## Browser-playable target (Phase 13)

### jellyfin-web's browser device profile

- Path: `src/scripts/browserDeviceProfile.js`
  (<https://github.com/jellyfin/jellyfin-web/blob/master/src/scripts/browserDeviceProfile.js>)
- License: GPL-2.0
- Verdict: reference-only
- Date: 2026-09-28
- Notes:
  - ADOPT: decide copy-or-transcode per stream against a browser profile, and
    gate on profile and bit depth, not the codec family alone — jellyfin-web
    probes `canPlayType` with codec strings such as `avc1.6e0033` (H.264 High
    10) before it direct-plays. Here the equivalent is a copy condition on the
    probed `pix_fmt`.
  - AVOID: feature-testing a live browser. A file written once must play in
    every browser, so the mask is the intersection, fixed at conversion time.

### Browser codec support in MP4 (MDN, caniuse)

- Path: <https://developer.mozilla.org/en-US/docs/Web/Media/Guides/Formats/Video_codecs>;
  <https://developer.mozilla.org/en-US/docs/Web/Media/Guides/Formats/Audio_codecs>;
  <https://caniuse.com/ac3-ec3>; <https://caniuse.com/audiotracks>;
  <https://bitmovin.com/blog/apple-av1-support/>
- License: n/a — documentation
- Verdict: the evidence for the copy mask
- Date: 2026-09-28
- Notes:
  - ADOPT: copy video only as 8-bit 4:2:0 H.264, audio only as AAC or MP3 — the
    two audio codecs every browser decodes in MP4. No browser decodes AC-3 or
    E-AC-3 in `<video>`, HEVC needs a hardware decoder in Chrome and very recent
    Firefox, and AV1 has no Safari fallback below M3 Macs and iPhone 15 Pro.
  - AVOID: copying Opus or FLAC into MP4 for the browser. MDN lists support, but
    Safari's `<video>` path for either is thinly evidenced (medium confidence),
    and a file that plays nowhere is worse than one re-encoded with a note.
  - ADOPT: keep every audio track. Only Safari exposes `audioTracks` by default;
    elsewhere the default track plays — keeping the rest costs nothing a
    browser notices and loses nothing.
  - ADOPT: `-movflags +faststart` — without it a progressive player must fetch
    the index from the end of the file before playback can start.
  - Pi 4: one published data point, libx264 at 8–10 fps for 1080p, preset
    unstated (<https://www.willusher.io/general/2020/11/15/hw-accel-encoding-rpi4/>);
    no per-preset figures exist — phase 13's spec measures them. `h264_v4l2m2m`
    reaches 53–60 fps there, but hardware encoders are out of scope.
  - Research mode: websearch, 2026-09-28.
  - Foundation impact: vision — yes: the target list grows to 18 and the "a new format is data" criterion is shown to hold for `web`; constitution — yes: a probe-first profile becomes a third kind in the ffprobe-on-the-happy-path principle; architecture — yes: the degradation ladder gains a probe-first entry and stream decisions gain a `pix_fmt` copy condition

## Subtitle sidecars for browsers (Phase 14)

### External WebVTT via `<track>`, Jellyfin's subtitle extraction

- Path: <https://developer.mozilla.org/docs/Web/Guide/Audio_and_video_delivery/Adding_captions_and_subtitles_to_HTML5_video>;
  <https://caniuse.com/webvtt>;
  <https://github.com/jellyfin/jellyfin-plugin-subtitleextract>;
  <https://jellyfin.org/docs/general/clients/codec-support/>;
  <https://github.com/WebKit/WebKit/pull/47763>
- License: GPL-3.0 (jellyfin-plugin-subtitleextract); documentation otherwise
- Verdict: reference-only
- Date: 2026-09-28
- Notes:
  - ADOPT: text subtitles as WebVTT files beside the video, loaded through
    `<track>` — universally supported, and what Jellyfin serves browsers instead
    of relying on in-band tracks.
  - AVOID: in-band `mov_text` for a browser target. No source confirms any
    browser exposing it as a `TextTrack` in a plain progressive `<video>`;
    WebKit's tx3g work targets MSE/HLS pipelines. Uncertain rather than ruled
    out — which is enough not to call an in-band track a carried subtitle.
  - AVOID: burning subtitles in — irreversible, and it forces a video re-encode
    on a stream that could otherwise be copied.
  - Research mode: websearch, 2026-09-28.
  - Foundation impact: vision — yes: Scope *In* gains sidecar outputs; constitution — none; architecture — yes: one source may write several paths, so every guard in `source-selection.md`, the JSON record and partial-file handling cover sidecars

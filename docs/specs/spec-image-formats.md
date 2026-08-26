# Spec: image-formats (roadmap phase 5)

> Created: 2026-08-26

Add the seven image target profiles — `png`, `jpg`, `webp`, `avif`, `gif`,
`tiff`, `bmp` — completing the vision's 17 formats. This spec carries no
lifecycle state — acceptance is the spec merged on the default branch with a
milestone and issues, and all progress lives in the GitHub issues and milestone.
A completed spec is moved to `docs/specs/archive/`.

**Depends on milestone #2 (target-driven-cli).** Independent of phases 3 and 4.

## Why this phase is not like the other two coverage phases

Audio and video targets convert a stream into a stream. An image target converts
a *frame*, and every source in the curated suffix set has either one frame or
thousands. That difference is the whole design problem here, and it is what the
open decision below is about — not codec masks, which are the easy part.

## Outcome

- [ ] `converter --to <fmt>` works for `png`, `jpg`, `webp`, `avif`, `gif`,
      `tiff` and `bmp`.
- [ ] `--list-formats` prints one line per registry entry — 17 targets, which is
      `docs/vision.md`'s headline success criterion met in full.
- [ ] **The diff of every PR in this milestone touches only
      `converter/profiles.py`, `README.md` and files under `tests/`.**
- [ ] Every new profile has a test pinning the exact argv it builds, for a
      copyable and for a non-copyable input.
- [ ] A multi-frame source under a single-frame target behaves as the gate
      decides, and says so — never silently.
- [ ] Converting an image with transparency into a target that cannot hold it
      names the loss.

## Scope

### In scope

- Seven new `Profile` entries with their stream rules, copy masks, fallback
  encoders, `cheap_attempt`, `explicit_streams`, `last_resort` and standing
  notes, plus registry entries.
- Extending the curated source-suffix set with image containers: `.png`, `.jpg`,
  `.jpeg`, `.webp`, `.avif`, `.gif`, `.tif`, `.tiff`, `.bmp`, `.ppm`, `.pgm`,
  `.tga`.
- `README.md`'s format list.
- The tests those profiles require.

### Out of scope

- **HEIC, SVG and camera RAW** — `docs/vision.md` names all three as non-goals:
  they need libheif or a rasteriser, not an ffmpeg muxer, and adding one would
  break the single-dependency promise.
- **EXIF/ICC preservation** — an explicit non-goal. ffmpeg strips metadata by
  default and PNG cannot carry EXIF at all (`docs/prior-art.md`).
- Resizing, cropping, rotation, colour management, or any encoder-tuning surface
  beyond the one quality default per lossy format.
- Extracting a frame *sequence* (`out_%04d.png`). One input file maps to one
  output file — `paths.output_for` is built on that, and changing it would be a
  different feature in a different phase.
- **Any engine change.**

## Constraints

- A target format is data, not code.
- One input file, one output file. Every design below is bounded by that.
- `ffprobe` never runs on the happy path.
- Never report success for a conversion that silently dropped something.
- The test suite keeps passing with no ffmpeg installed.

## Prior art

- [Image conversion through ffmpeg (Phase 5)](../prior-art.md#image-conversion-through-ffmpeg-phase-5)
  — the concern tagged for this phase. Its ADOPT is confirmed by measurement: PNG,
  JPEG, WebP, AVIF, TIFF, BMP and GIF all have working ffmpeg muxers, so images
  need no second backend. Its AVOID is the reason EXIF/ICC preservation is out of
  scope rather than a bug.
- [Container/codec capability modelling (Phase 1)](../prior-art.md#containercodec-capability-modelling-phase-1)
  — the copy-mask vocabulary, and the rule that the mask is curated by hand.

## Design

No new design artifact. The ladder and the per-stream branch already cover this
phase; what is new is *which rung does the work*, and that is a decision recorded
below rather than a new diagram.

## Human prerequisites

- none.

## Prior decisions

### The muxer facts these profiles rest on

Measured against ffmpeg 9.0 during planning. A later reader should re-verify.

| Fact | Consequence |
|---|---|
| **A multi-frame source into a single-file image target fails hard**: `-i v.mp4 -map 0:v:0 out.png` exits 127 with "Cannot write more than one file with the same name. Are you missing the -update option or a sequence pattern?" | The single-frame targets do **not** silently produce garbage from a video. They fail into the ladder, which is where the decision below gets to name what it does |
| **Adding `-frames:v 1` makes the same conversion succeed**, writing exactly one frame (verified with `-count_frames`) | The rung that carries `-frames:v 1` is the one that turns a video into an image |
| **GIF is different: it is animated.** A 2-second video into `.gif` exits 0 and writes 20 frames | `gif` must **not** carry `-frames:v 1`, and it is the only image target that converts a video meaningfully |
| **An alpha PNG into JPG exits 0 and silently drops the alpha channel** (`rgba` in, `yuvj444p` out) | A real silent loss, on the happy path, that only a standing note can cover |
| PNG, JPG, WebP, AVIF, TIFF and BMP all encode from a PNG source at exit 0 | Every target in the vision's list has a working muxer; no second backend is needed |
| A single-frame PNG copies into PNG with `-c copy` at exit 0 | The copy path is real for image-to-image where the codec matches |

### Decisions

| Decision | Rationale | Date |
|---|---|---|
| Cheap attempt for every single-frame target: `flags("-map 0:v? -c copy")`, `explicit_streams=False`, **without** `-frames:v 1` | A single-image source converts on the first attempt. A multi-frame source *fails* here, which is exactly what puts it in front of the ladder instead of quietly producing one frame with no explanation — the "turn a quiet loss into a failure the ladder can name" pattern phases 3 and 4 established | 2026-08-26 |
| `gif`'s cheap attempt is `flags("-map 0:v? -c copy")` too, but it carries no frame limit anywhere: a video converts to an animated GIF | Measured: the GIF muxer takes every frame. It is the one image target for which a video source is an ordinary conversion rather than an extraction | 2026-08-26 |
| Every single-frame target declares no audio, subtitle or attachment rule, so those streams are dropped by the selective rung with the engine's per-stream note | An image holds one thing. Nothing here needs a new rule kind | 2026-08-26 |
| Copy masks: `png` -> `{png}`; `jpg` -> `{mjpeg}`; `webp` -> `{webp}`; `avif` -> `{av1}`; `gif` -> `{gif}`; `tiff` -> `{tiff}`; `bmp` -> `{bmp}` | ffprobe reports a still image's `codec_name` as its image codec, so an image-to-same-image conversion is a real stream copy. Everything else re-encodes | 2026-08-26 |
| Fallback encoders: `png` -> `png`; `jpg` -> `mjpeg -q:v:{n} 2`; `webp` -> `libwebp -quality:v:{n} 80`; `avif` -> `libaom-av1 -crf:v:{n} 30 -still-picture 1`; `gif` -> `gif`; `tiff` -> `tiff`; `bmp` -> `bmp` | One quality default per lossy format, chosen at "you would need the original beside it to tell", and pinned by the argv tests. The lossless targets need no parameter | 2026-08-26 |
| `png`, `tiff`, `bmp` and `gif` declare `fallback_name=None` — no note for the encode itself; `jpg`, `webp` and `avif` declare theirs | The rule phase 3 established: encoding into a target's own lossless codec gives up nothing worth naming, encoding into a lossy one does | 2026-08-26 |
| **Standing note on `jpg`**: transparency is not carried into JPEG. Measured as a silent, exit-0 loss on the happy path | The phase-3 gate's mechanism, applied to the one measured silent loss in this phase. Whether `bmp` and `gif` need the same note depends on a measurement the review is asked to make | 2026-08-26 |
| OPEN — what a single-frame target does with a multi-frame source | resolved at the spec-acceptance gate; see the note below | — |

### The one open decision, in full

Measured: `--to png` on a video fails the cheap attempt *and* the selective rung,
because neither carries `-frames:v 1`. What happens next is the `last_resort`,
and what that rung contains is the decision.

1. **Extract the first frame.** `last_resort` is
   `flags("-map 0:v:0 -frames:v 1")` plus the profile's encoder, with a note
   saying a single frame was taken from a multi-frame source. `--to png` over a
   mixed folder then produces a thumbnail per video, exit 0, and a re-run is
   idempotent. It costs three ffmpeg spawns and a probe per video, and it answers
   a question the user did not obviously ask.
2. **Declare no `last_resort`.** A video under `--to png` ends the ladder and is
   reported as `failed`, exit 1. Honest — the tool does not invent an answer — but
   it breaks `docs/vision.md`'s idempotent-re-run criterion for any mixed tree:
   the file produces no output, so every re-run fails again, and the run never
   reaches `0 converted, 0 failed`.

Option 2's cost is the one phase 2 already paid for elsewhere: the `unsupported`
outcome exists precisely because a permanently-failing file poisons re-runs. It
does not apply automatically here — `unsupported` fires when the source carries no
stream of any type the profile has a rule for, and a video *does* match an image
profile's video rule. Making it apply would be an engine change, which this phase
does not take.

## Tracking

- Milestone: image-formats (created at the spec-acceptance gate)
- Issues: created from this spec once it is merged (one per implementable step)

## Verification

Machine checks:

- [ ] Verify passes on the merge commit.
- [ ] For every PR in this milestone, `git diff main...<pr-head> --name-only`
      lists only `converter/profiles.py`, `README.md` and paths under `tests/`.
- [ ] Per new profile, a test pinning the full argv for a copyable input and for
      a non-copyable one — fourteen tests, seven profiles, both cases each.
- [ ] A test that `gif` carries no frame limit while the six single-frame targets
      reach one through the rung the gate chose.
- [ ] A test that no image profile declares an audio, subtitle or attachment
      rule, so those streams are dropped with a note.
- [ ] A test per degradation branch, including `jpg`'s standing note.
- [ ] A test that converting into `png`, `tiff`, `bmp` or `gif` emits no note for
      the encode itself.
- [ ] `--list-formats` prints 17 lines.

Human milestone-QA gate. `$FF` is the absolute ffmpeg path from *This machine*:

```text
New-Item -ItemType Directory -Force in
& $FF -y -f lavfi -i color=c=red:size=320x240:d=1 -frames:v 1 in/flat.png
& $FF -y -f lavfi -i "color=c=red@0.5:size=320x240:d=1,format=rgba" -frames:v 1 in/alpha.png
& $FF -y -f lavfi -i testsrc=size=320x240:rate=10:duration=2 -c:v libx264 in/clip.mp4
```

- [ ] Each of the seven targets converts `flat.png` and the result opens.
- [ ] `--to jpg in out` over `alpha.png` prints the transparency note. Check the
      output's `pix_fmt` with `ffprobe` — the loss is real and silent without it.
- [ ] `--to gif in out` over `clip.mp4` produces an **animated** GIF: count the
      frames with `ffprobe -count_frames`, do not judge by eye.
- [ ] `--to png in out` over `clip.mp4` behaves as the gate decided, and a second
      run over the same tree reports the same thing with exit 0 if the gate chose
      option 1.
- [ ] `--to png in out` over `flat.png` with a different output root stream-copies
      rather than re-encoding.
- [ ] A second run over any converted tree reports `0 converted`, exit 0.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| `--to png` over a video-heavy tree does something surprising | It is the phase's one open decision, put to the gate with both costs measured rather than settled quietly |
| An alpha loss goes unnamed | Measured and covered by `jpg`'s standing note; the review is asked to measure `bmp` and `gif` for the same |
| A copy mask is wrong and an image copy ships something unopenable | The QA gate opens one output per target, and phase 3's lesson applies: on the happy path the muxer is the authority, so the mask matters most on the failure path |
| Someone reads the missing EXIF as a bug | Named as a vision non-goal in Out of scope, with the prior-art entry that evidences it |
| The 17-format claim is asserted rather than checked | `--list-formats` printing 17 lines is a Verification item |

## Decision log

- 2026-08-26: The muxer facts were measured during planning, as in phase 4. The
  decisive one was that a video into a single-file image target *fails* rather
  than silently writing a frame — which is what makes the ladder, and therefore an
  honest note, available at all.
- 2026-08-26: `gif` is deliberately not grouped with the other six. It is the only
  image target that is animated, and treating it as a still would silently discard
  every frame but one.

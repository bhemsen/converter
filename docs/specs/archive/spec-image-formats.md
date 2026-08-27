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
thousands. Worse, the seven targets do not behave alike: three different muxer
families sit behind them, and the differences are not cosmetic.

| Group | Targets | Behaviour that sets it apart |
|---|---|---|
| **image2, permissive** | `png`, `jpg`, `tiff`, `bmp` | The muxer accepts **any** video codec under `-c copy`, so a copy ships a mislabelled file. A multi-frame source fails hard |
| **animated** | `gif`, `webp` | Self-policing muxers, and a video source becomes a genuine animation — every frame is written |
| **still, self-policing** | `avif` | Self-policing, but a multi-frame source is silently reduced to **one** frame at exit 0 |

Everything below follows from that table.

## Outcome

- [ ] `converter --to <fmt>` works for `png`, `jpg`, `webp`, `avif`, `gif`,
      `tiff` and `bmp`.
- [ ] `--list-formats` prints one line per registry entry, including the seven
      image targets.
- [ ] **The diff of every PR in this milestone touches only
      `converter/profiles.py`, `README.md` and files under `tests/`.**
- [ ] `--to png` over a folder of JPEGs produces real PNGs, and `--to jpg` over a
      folder of PNGs produces real JPEGs. The two commonest image conversions
      there are, and a stream copy gets both wrong.
- [ ] A multi-frame source behaves as its target's group requires, and says so —
      never silently.
- [ ] Converting an image with transparency into a target that cannot hold it
      names the loss.

## Scope

### In scope

- Seven new `Profile` entries with their stream rules, copy masks, fallback
  encoders, `cheap_attempt`, `explicit_streams`, `stream_limit`, `last_resort`,
  `container_options` and standing notes, plus registry entries.
- Extending the curated source-suffix set with image containers: `.png`, `.jpg`,
  `.jpeg`, `.webp`, `.avif`, `.gif`, `.tif`, `.tiff`, `.bmp`, `.ppm`, `.pgm`,
  `.tga`.
- `README.md`'s format list.
- The tests those profiles require.

### Out of scope

- **HEIC, SVG and camera RAW** — `docs/vision.md` names all three as non-goals:
  they need libheif or a rasteriser, not an ffmpeg muxer.
- **EXIF/ICC preservation** — an explicit non-goal; PNG cannot carry EXIF at all
  (`docs/prior-art.md`).
- Resizing, cropping, rotation, colour management, or any encoder-tuning surface
  beyond the one quality default per lossy format.
- Extracting a frame *sequence* (`out_%04d.png`). One input file, one output
  file — `paths.output_for` is built on that.
- **Any engine change.**

## Constraints

- A target format is data, not code.
- One input file, one output file.
- `ffprobe` never runs on the happy path of a cheap attempt whose mapping is
  *exhaustive*. A profile whose cheap attempt is partial by construction
  declares `partial_mapping=True` and is probed once on its success, so what
  that mapping could not carry is named (`docs/constitution.md`, narrowed by
  issue #18). Every cheap attempt below maps by type, so every profile in
  this phase is partial and must declare it -- together with exactly a rule
  for each stream type it maps and no rule for any other, per the equality in
  `docs/design/degradation-ladder.md` (issue #40).
- Never report success for a conversion that silently dropped something.
- `{n}` is substituted **only** in `StreamRule` templates. `cheap_attempt` and
  `last_resort` are emitted verbatim, so a `{n}` in either reaches ffmpeg
  literally — every attempt below is written without one.
- The test suite keeps passing with no ffmpeg installed.

## Prior art

- [Image conversion through ffmpeg (Phase 5)](../../prior-art.md#image-conversion-through-ffmpeg-phase-5)
  — the concern tagged for this phase. Its ADOPT is confirmed by measurement: all
  seven formats have working ffmpeg muxers, so images need no second backend. Its
  AVOID is why EXIF/ICC preservation is a non-goal rather than a bug.
- [Container/codec capability modelling (Phase 1)](../../prior-art.md#containercodec-capability-modelling-phase-1)
  — the copy-mask vocabulary, and the rule that the mask is curated by hand.

## Design

No new design artifact. What is new is *which rung does the work*, and that is
recorded as decisions rather than as a new diagram.

## Human prerequisites

- none.

## Prior decisions

### The muxer facts these profiles rest on

Measured against ffmpeg 9.0 during planning and re-measured by the review, exit
codes taken from ffmpeg itself.

| Fact | Consequence |
|---|---|
| **The image2 muxer accepts any video codec under `-c copy`.** `flat.jpg -map 0:v? -c copy out.png` exits 0 and writes a JPEG named `.png`; `alpha.png -> out.jpg` writes a PNG named `.jpg` | `png`, `jpg`, `tiff` and `bmp` must **force their encoder** in the cheap attempt. A copy there mislabels the file on the default path, for the two commonest image conversions there are |
| **`webp`, `avif` and `gif` self-police**: a non-matching codec copy exits 127 ("webp muxer supports only codec webp", "gif muxer supports only codec gif", "Could not find tag for codec png") | Those three can keep `-c copy` safely; the price is one wasted spawn plus one probe per non-matching source |
| **GIF is a 256-colour palette format, not a lossless one**: a photograph through `-c:v gif` keeps 182 of 36 485 distinct colours at exit 0. But a **GIF source** re-encoded through the same template is pixel-identical (PSNR infinite, same byte count, all frames kept) -- it already holds at most 256 colours | `gif` must declare a `fallback_name`, or the quantisation from a photograph is reported nowhere. It also means forcing `gif`'s encoder costs a same-format source nothing but CPU |
| **Forcing `jpg`'s encoder re-encodes an already-JPEG source**: 44 893 B -> 51 865 B (+15.5%), PSNR 53.5 dB, where `-c copy` is byte-identical | The price of not shipping a mislabelled file. `png`, `tiff` and `bmp` re-encode losslessly and pay nothing |
| **A multi-frame source into an image2 target fails hard** at both the cheap attempt and the selective rung: "Cannot write more than one file with the same name" | Only a rung carrying `-frames:v 1` converts a video into a `png`/`jpg`/`tiff`/`bmp` |
| **`gif` and `webp` write every frame**: a 20-frame video becomes a 20-frame GIF and a 20-frame animated WebP, both at exit 0 on the selective rung | `webp` is an *animated* target, not a still one. Neither carries a frame limit |
| **`avif` silently reduces a 20-frame source to one frame at exit 0** — the muxer, not the flag: dropping `-still-picture 1` still yields one frame. With an AV1-in-MP4 source the copy mask hits and this happens on the **cheap attempt** | The one silent multi-frame loss in the phase, and it needs a standing note; no rung can turn it into a failure |
| **Alpha, measured by round-tripping `rgba` (α=127) through each fallback encoder:** kept by `png`, `tiff`, `bmp`, `webp`; **lost by `jpg`, `gif` and `avif`** — `gif` loses even a fully transparent source, `avif` because `libaom-av1` has no alpha pix_fmt | `jpg`, `gif` and `avif` need a transparency standing note. `bmp` does not — the question the earlier draft left open is closed |
| ffprobe reports a still's `codec_name` as `png`, `mjpeg`, `webp`, `tiff`, `bmp`, `gif`, `av1` | The copy masks below are right |
| Option syntax parses in the placeholder-free form the profiles use: `-c:v mjpeg -q:v 2`, `-c:v libwebp -quality:v 80` (not `-compression_level`), `-c:v libaom-av1 -crf:v 30 -still-picture 1`, and bare `-c:v png` / `gif` / `tiff` / `bmp` | The fallback templates below are valid |
| **`libaom-av1` is 17-34x slower than the alternatives**: a 3000x2000 still takes 6.9 s at `-crf 30 -still-picture 1`, against 0.41 s for `libwebp -quality 80` and 0.20 s for `mjpeg -q:v 2` | `--to avif` over a folder of camera JPEGs is a different tool from `--to webp` over the same folder. Priced here rather than discovered |

### Decisions

| Decision | Rationale | Date |
|---|---|---|
| **`png`, `jpg`, `tiff`, `bmp` force their encoder in the cheap attempt**: `flags("-map 0:v? -c:v png")`, `flags("-map 0:v? -c:v mjpeg -q:v 2")`, `flags("-map 0:v? -c:v tiff")`, `flags("-map 0:v? -c:v bmp")`. `explicit_streams=False` | Measured: image2 accepts any codec on copy, so `--to png` over JPEGs would ship JPEGs named `.png`. This is phase 3's carve-out — "where the muxer is looser than the format's identity, the profile does not rely on a copy at all" — and it is the same shape as `opus`. The copy still happens on the selective rung, on a mask hit | 2026-08-26 |
| **`webp` alone keeps `flags("-map 0:v? -c copy")`**, `explicit_streams=False`. `gif` and `avif` force their encoder, per the decision above | `webp`'s muxer rejects a non-matching codec, so a copy cannot mislabel, and `webp` loses neither alpha nor frames -- it has no standing note whose reachability depends on which rung wins. `gif` and `avif` do, which is what makes their case different | 2026-08-26 |
| Copy masks: `png` -> `{png}`; `jpg` -> `{mjpeg}`; `webp` -> `{webp}`; `avif` -> `{av1}`; `gif` -> `{gif}`; `tiff` -> `{tiff}`; `bmp` -> `{bmp}` | Measured against ffprobe's reported codec names | 2026-08-26 |
| Fallback encoders, as full `StreamRule` templates: `png` -> `flags("-c:v png")`; `jpg` -> `flags("-c:v mjpeg -q:v 2")`; `webp` -> `flags("-c:v libwebp -quality:v 80")`; `avif` -> `flags("-c:v libaom-av1 -crf:v 30 -still-picture 1")`; `gif` -> `flags("-c:v gif")`; `tiff` -> `flags("-c:v tiff")`; `bmp` -> `flags("-c:v bmp")` -- all placeholder-free, per the stream-limit row below | One quality default per lossy format, pinned by the argv tests. Written in full rather than as shorthand, because the `-c:v` is not optional | 2026-08-26 |
| Only `png`, `tiff` and `bmp` declare `fallback_name=None`. `gif`, `jpg`, `webp` and `avif` declare theirs | The phase-3 rule -- encoding into a target's own lossless codec gives up nothing worth naming -- covers `png`, `tiff` and `bmp` only. **GIF is not lossless**: it is a 256-colour palette format, and measured, a 1280x720 photograph goes from 36 485 distinct colours to 182 (PSNR 39.4 dB against 47.0 for png and bmp). With `fallback_name=None` that loss would be reported nowhere at all | 2026-08-26 |
| **`accept_options=flags("-c:v copy")` on every image profile's video rule**, placeholder-free like the rest | Follow `opus`'s precedent, **not** WAV's `accept_options=()`. WAV's empty form is safe only because its mask is empty, so its accept branch is unreachable at all; every mask here is non-empty, so the branch is live. Measured, `()` emits a map with no codec option -- `-map 0:0` alone on a JPEG re-encodes it at exit 0 (44 867 B against 44 893 B, PSNR 66 dB) where `-c:v copy` is byte-identical. A silent lossy re-encode on the one path the copy mask exists to protect | 2026-08-26 |
| **`stream_limit=1` on every image profile's video rule**, and -- following the convention `spec-profile-registry.md` recorded -- their templates are written **without** `{n}`: `flags("-c:v png")`, `flags("-c:v mjpeg -q:v 2")` and so on | A rule limited to one stream can only ever produce output stream 0, so it writes the bare specifier and the engine substitutes nothing. That is phase 1's rule, and the argv tests pin whichever form is chosen, so it is worth choosing deliberately. One image, one picture. A source with two video streams — cover art beside a video, an MJPEG-plus-video AVI — would otherwise map both into one output file and fail. `mp3` and `flac` got the same treatment in phase 3 for the same reason | 2026-08-26 |
| No image profile declares an audio, subtitle or attachment rule; `container_options` is `()` for all seven | An image holds one thing, and none of these muxers takes a container flag | 2026-08-26 |
| **Standing notes**, all on a cheap attempt that always wins: `jpg` -- transparency is not carried, and the image was re-encoded; `gif` -- transparency is not carried, and a photograph is reduced to 256 colours; `avif` -- transparency is not carried, and a multi-frame source is reduced to a single frame | All three cheap attempts force their encoder, so all three always win and all three notes always print. The drafted version had `gif` and `avif` copying, which meant their notes printed for exactly the inputs that lose nothing -- the defect the gate's second decision closed | 2026-08-26 |
| `last_resort`: `gif` -> `flags("-map 0:v:0 -c:v gif")`; `webp` -> `flags("-map 0:v:0 -c:v libwebp -quality:v 80")`, noting the image was re-encoded; `avif` -> `flags("-map 0:v:0 -c:v libaom-av1 -crf 30 -still-picture 1")`. The four image2 targets' `last_resort` is what the gate decides | Phase 4's rule: every profile needs one or a ladder that reaches the end lands as `failed`. Written without `{n}`, which is not substituted outside `StreamRule` templates. Each carries the notes its rung earns: `gif` that the image was re-quantised to 256 colours, `avif` that a multi-frame source is reduced to one frame -- a last rung that converts in silence is what `mp4`'s two notes exist to prevent | 2026-08-26 |
| A multi-frame source into `png`, `jpg`, `tiff` or `bmp` is handled by the **`last_resort`**: `flags("-map 0:v:0 -frames:v 1 -c:v png")` and its siblings, with a note that a single frame was taken | Resolved at the gate on 2026-08-26. Keeps the overwhelmingly common case -- an actual image -- converting on the first attempt with no note at all; a video pays three ffmpeg spawns plus a probe for a thumbnail. Failing instead was rejected: the file would produce no output, so every re-run fails again and a mixed tree never reaches `0 converted, 0 failed` | 2026-08-26 |
| **`gif` and `avif` force their encoder** too: `flags("-map 0:v? -c:v gif")` and `flags("-map 0:v? -c:v libaom-av1 -crf:v 30 -still-picture 1")`. Only `webp` keeps `-c copy` | Resolved at the gate on 2026-08-26. The cheap attempt then always wins, so both standing notes always print and the wasted spawn disappears. Measured, `gif` pays nothing for it -- a GIF source re-encodes pixel-identically. `avif` pays a real generation loss plus 7 s per already-AVIF file, accepted so its transparency and frame losses are named rather than requiring a constitution amendment to leave them silent | 2026-08-26 |

### The multi-frame decision, in full (resolved at the gate)

**Scope: four targets, not seven.** `gif` and `webp` convert a video into an
animation, which needs no decision. `avif` reduces it to one frame no matter what
this decision says — whether that reduction is *reported* is the second open
decision's business, not this one's. Only the image2 four — `png`, `jpg`, `tiff`,
`bmp` — reach a rung where this is a choice.

**Resolved at the gate on 2026-08-26: option 1, the `last_resort`.**

Measured: with the encoder forced, an image source converts on the cheap attempt.
A video source fails the cheap attempt *and* the selective rung, because neither
carries `-frames:v 1`. Three answers:

1. **Extract the first frame at the `last_resort`.**
   `flags("-map 0:v:0 -frames:v 1 -c:v png")` and its siblings, with a note saying
   a single frame was taken. The common case — an actual image — converts on the
   first attempt with no note at all. A video costs three ffmpeg spawns plus a
   probe, and gets a thumbnail it did not obviously ask for.
2. **Put `-frames:v 1` in the cheap attempt**, with a standing note that only the
   first frame is kept. One spawn instead of three for a video, and the same
   standing-note mechanism phases 3 and 4 chose elsewhere. The cost is noise: the
   note prints on every single conversion, including the overwhelming majority
   that are ordinary one-frame images with nothing to lose.
3. **Declare no `last_resort`.** A video under `--to png` is reported as `failed`,
   exit 1. The tool invents nothing — but the file produces no output, so every
   re-run fails again and a mixed tree never reaches `0 converted, 0 failed`,
   which `docs/vision.md` requires.

Option 3's cost is the one phase 2 already paid for elsewhere: its `unsupported`
outcome exists precisely because a permanently-failing file poisons re-runs. It
does **not** apply automatically here — `unsupported` fires when the source
carries no stream of any type the profile has a rule for, and a video does match
an image profile's video rule. Making it apply would be a `jobs.py` change, which
this phase does not take.

### The gif/avif decision, in full (resolved at the gate)

**Resolved at the gate on 2026-08-26: option 1, both force their encoder.** The
notes therefore always print, and the "where each note lives" block below applies
in its option-1 form: the standing notes carry transparency for both, the
256-colour quantisation for `gif` and the frame reduction for `avif`, while
`fallback_name` stays declared for the rarely-reached selective rung.

A standing note lives on `cheap_attempt.notes`, and `batch._attempt_conversion`
reports **only the winning attempt's** notes. `gif`'s and `avif`'s drafted cheap
attempt is `-c copy`, which succeeds only when the source is already GIF or AV1 --
the one input that loses nothing. For every other source the copy exits 127, the
selective rung wins, and its per-stream notes are what print. Measured through the
real engine:

- `--to gif` over an alpha PNG loses the transparency at exit 0 **in complete
  silence**.
- `--to avif` over an h264 video loses 19 of 20 frames and says only that the
  video was re-encoded.

So the drafted notes are attached to a path they do not print on. The only lever
this phase has is the cheap attempt:

1. **Force the encoder**, as `png`/`jpg`/`tiff`/`bmp` now do:
   `flags("-map 0:v? -c:v gif")` and
   `flags("-map 0:v? -c:v libaom-av1 -crf:v 30 -still-picture 1")`. The cheap
   attempt then always wins, so both standing notes always print, and the wasted
   spawn plus probe on every non-matching source disappears.

   **The price differs sharply between the two, so this may be answered per
   target.** Measured: re-encoding a GIF source through `-c:v gif` is
   **pixel-identical** (PSNR infinite, same byte count, all 20 frames of an
   animation preserved) -- a GIF already holds at most 256 colours, so the palette
   reproduces them exactly, and option 1 costs `gif` nothing but CPU. Re-encoding
   an AVIF source is genuinely lossy and slow: 7.07 s and PSNR 55.7 dB on a
   3000x2000 still. One caveat that resisted measurement: an animated GIF using
   per-frame local palettes could exceed 256 colours across the whole file, where
   a single global palette would quantise. Both fixtures tried came back lossless.
2. **Keep the copy.** A same-format source is copied perfectly and cheaply. The
   price is that a non-GIF source into `gif` loses transparency, and a video into
   `avif` loses frames, with nothing naming either -- which `docs/constitution.md`
   forbids in as many words, so picking this means amending it as phase 3's
   option 2 would have.

This is the same shape as phase 3's `opus` decision, with one difference worth
weighing: there the cost of copying was a mislabelled file, here it is an unnamed
*loss*, which the constitution addresses directly.

**Where each note lives, per option.** This is not cosmetic: `fallback_name` and a
standing note are reachable on opposite paths.

- **Option 1 (force the encoder).** The cheap attempt always wins, so the standing
  notes are the reporting path and must carry everything: transparency for both,
  the 256-colour quantisation for `gif`, the frame reduction for `avif`.
  `fallback_name` stays declared but fires only on the rarely-reached selective
  rung.
- **Option 2 (keep the copy).** The selective rung usually wins, so `fallback_name`
  carries the re-encode note -- and the transparency and frame notes are
  unreachable, which is the constitution amendment named above.

The Verification and QA items that check these notes are conditioned on this
choice; do not read them as settled before the gate.

## Tracking

- Milestone: [image-formats](https://github.com/bhemsen/converter/milestone/5) (#5)
- Issues: created from this spec once it is merged (one per implementable step)

## Verification

Machine checks:

- [ ] Verify passes on the merge commit.
- [ ] For every PR in this milestone, `git diff main...<pr-head> --name-only`
      lists only `converter/profiles.py`, `README.md` and paths under `tests/`.
- [ ] Per new profile, a test pinning the full argv for a copyable input and for
      a non-copyable one. `png`, `jpg`, `tiff` and `bmp` carry the same exception phase 3
      recorded for `opus`: their cheap attempt never copies, so the copyable case
      exists only on the selective rung. Not WAV's exception, which is about an
      empty mask and points at `accept_options=()` -- the wrong form here.
- [ ] A test that `gif` and `webp` carry no frame limit anywhere, and that the
      image2 four reach one through the rung the gate chose.
- [ ] A test that `png`, `jpg`, `tiff` and `bmp` force `-c:v` in their cheap
      attempt — the check that stops a copy from shipping a mislabelled file.
- [ ] A test that no image profile declares an audio, subtitle or attachment
      rule, so those streams are dropped with a note, and that every one declares
      `stream_limit=1`.
- [ ] A test per standing note, pinning its exact wording **and** that the note
      is on the cheap attempt, which always wins -- the defect the gate's second
      decision closed.
- [ ] A test that converting into `png`, `tiff` or `bmp` emits no note for the
      encode itself. GIF is not in that list -- it is a 256-colour format, not a
      lossless one -- and its quantisation is reported by its standing note.
- [ ] `--list-formats` prints one line per registry entry, including the seven
      image names. The 17-line total is a QA-gate item for whichever of the three
      coverage milestones closes last, not a machine check here — phases 3, 4 and
      5 may run as parallel orchestrators, so this milestone can close while the
      registry holds nine or twelve entries.

Human milestone-QA gate. `$FF` is the absolute ffmpeg path from *This machine*:

```text
New-Item -ItemType Directory -Force in
& $FF -y -f lavfi -i color=c=red:size=320x240:d=1 -frames:v 1 in/flat-png.png
& $FF -y -f lavfi -i color=c=red:size=320x240:d=1 -frames:v 1 in/flat-jpg.jpg
& $FF -y -f lavfi -i "color=c=red@0.5:size=320x240:d=1,format=rgba" -frames:v 1 in/alpha.png
& $FF -y -f lavfi -i testsrc=size=320x240:rate=10:duration=2 -c:v libx264 in/clip.mp4
```

- [ ] Each of the seven targets converts `flat-png.png` and the result opens.
- [ ] `--to png in out` over `flat-jpg.jpg` produces a **real PNG** — `ffprobe` it,
      and check `file` too. A stream copy would produce a JPEG named `.png` at
      exit 0, which is the defect this phase's cheap attempts exist to prevent.
- [ ] `--to jpg in out` over `flat-png.png` produces a real JPEG, same check.
- [ ] `--to jpg in out` over `alpha.png` prints the transparency note, and the
      output's `pix_fmt` shows the alpha is gone. `--to bmp`, `--to png`,
      `--to tiff` and `--to webp` keep it and print no such note. Repeat for
      `--to gif` and `--to avif`, whose standing notes now always print.
- [ ] `--to gif in out` over `clip.mp4` produces an **animated** GIF, and
      `--to webp` an animated WebP: count frames with `ffprobe -count_frames`.
- [ ] `--to avif in out` over `clip.mp4` produces a single frame and says so.
      Confirmed, matching the issue #35 Decision log entry below: the primary
      displayed item (`ffprobe -show_streams`: stream index 0, `nb_frames=1`)
      is the one an AVIF viewer shows; the file's `major_brand` comes back
      `avis` and a second, non-primary stream retains the full 20-frame
      encoded sequence on disk (index 1, `nb_frames=20`) -- already recorded
      as "undersells rather than oversells what the file retains", not a new
      finding.
- [ ] `--to png in out` over `clip.mp4` produces a single frame via the
      `last_resort` and names it; a second run reports the same thing, exit 0.
      Confirmed: `png`'s output genuinely carries a single stream, single frame
      (`ffprobe -count_frames`: `nb_read_frames=1`), unlike `avif`'s two-stream
      container above.
- [ ] `--to gif in out` over a photograph names the colour quantisation, via its standing note.
- [ ] Time `--to avif` over a large still and compare with `--to webp`.
      Measured on *This machine* (not the 3000x2000 photograph the Prior
      decisions table used): a synthetic 1920x1080 still took 6.8 s via `avif`
      against 0.75 s via `webp`, a ~9x gap -- same order of magnitude as the
      table's 17x on a larger image, and the conclusion holds: tolerable for
      one file, not for a folder.
- [ ] A second run over any converted tree reports `0 converted`, exit 0.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| A stream copy ships a mislabelled file | The four image2 targets force their encoder, with a Verification item and a QA check on both directions of the commonest conversion |
| `avif` silently drops frames, and `gif` silently drops transparency and colours | Both forced their encoder at the gate, so their standing notes are on the rung that always wins and the losses are always named |
| `--to avif` over a photo library is unusably slow | Measured and priced in the muxer table; the QA gate confirms it on real photographs |
| An alpha loss goes unnamed | Measured per target: `jpg`, `gif` and `avif` lose it, `png`, `tiff`, `bmp` and `webp` keep it. All three notes print on a cheap attempt that always wins |
| The wasted spawn is mistaken for a bug | It remains only for `webp`, named in its decision row as a deliberate price for a real copy path; forcing the encoder removed it for `gif` and `avif` |
| Someone reads the missing EXIF as a bug | Named as a vision non-goal with the prior-art entry that evidences it |

## Decision log

- 2026-08-26: The muxer facts were measured during planning, as in phase 4, and
  the review falsified three of them. The decisive correction: image2 accepts any
  codec on copy, so the four targets behind it must force their encoder — without
  that, `--to png` over JPEGs and `--to jpg` over PNGs both ship mislabelled files
  at exit 0.
- 2026-08-26: `webp` was moved out of the single-frame group after the review
  measured it writing a 20-frame animation. `gif` was never in it.
- 2026-08-26: `avif`'s silent frame reduction has no failure path to hang a
  per-stream note on, so it is the one loss in this phase that only a standing
  note can report — including on the cheap attempt, for an AV1-in-MP4 source.
- 2026-08-26: Review round 2 found that `gif` and `avif`'s standing notes were
  attached to a path they never print on — their cheap attempt is a copy that only
  wins for a source already in that format, i.e. the one input that loses nothing.
  Promoted to the phase's second open decision rather than settled, because the
  fix costs a re-encode on the same-format case.
- 2026-08-26: Review round 2 measured that GIF keeps 182 of 36 485 colours from a
  photograph. It had been grouped with the lossless targets and would have
  reported that loss nowhere at all.
- 2026-08-26: Review round 3 found `accept_options` undecided and the Verification
  bullet citing WAV's precedent, which is the wrong one — WAV's `()` is safe only
  because its mask is empty, and here it would emit a map with no codec option,
  turning every mask hit into a silent lossy re-encode.
- 2026-08-26: Review round 3 also found that `fallback_name`'s reachability is the
  mirror of the standing notes' — reachable under option 2, unreachable under
  option 1 — so the second open decision now states where each note lives per
  option, and the checks that depend on it say they are conditional.
- 2026-08-26: Review round 4 measured that a GIF source re-encoded through
  `-c:v gif` is pixel-identical, so the second open decision's option 1 costs
  `gif` only CPU while costing `avif` a real generation loss plus seven seconds.
  The two had been bundled under one price sentence that overstated `gif`'s; the
  decision may now be answered per target.
- 2026-08-26: Gate resolved both decisions. The image2 four extract the first
  frame at the `last_resort`, keeping the common single-image case noise-free.
  `gif` and `avif` force their encoder, so every standing note sits on a rung that
  always wins — `gif` pays nothing for it, `avif` pays a generation loss and seven
  seconds per already-AVIF file, accepted rather than leaving its losses silent.
- 2026-08-26: Issue #33 widened `SOURCE_SUFFIXES` with the twelve image
  containers this phase's `In scope` names — `.png`, `.jpg`, `.jpeg`, `.webp`,
  `.avif`, `.gif`, `.tif`, `.tiff`, `.bmp`, `.ppm`, `.pgm`, `.tga` — ahead of the
  seven image profiles this milestone still adds, following the phase-3/phase-4
  precedent of widening the suffix set before its profiles land. None of the
  twelve was already present.
- 2026-08-26: Issue #34 landed the image2 four — `png`, `jpg`, `tiff`, `bmp` —
  exactly as this spec's decisions pin: cheap attempt forces the encoder,
  `accept_options=flags("-c:v copy")`, `stream_limit=1` muxer-enforced (not
  mapping-enforced), `fallback_name=None` for the three lossless targets and
  `"mjpeg"` for `jpg`, and a `last_resort` that extracts the first frame with a
  note. Re-verified against real ffmpeg 9.0: `flat.jpg --to png` produces a
  genuine `codec_name=png` output rather than a mislabelled JPEG, and the
  reverse holds for `flat.png --to jpg`; `alpha.png --to jpg` prints the
  transparency standing note and drops to `pix_fmt=yuvj444p`, while `--to bmp`,
  `--to png` and `--to tiff` keep `pix_fmt` alpha-bearing and print nothing;
  `clip.mp4` (20 frames) into any of the four lands on the `last_resort` and
  writes exactly one frame with the multi-frame note; a second run over an
  already-converted tree reports `0 converted`, exit 0.
- 2026-08-26: PR review on issue #34 found the `last_resort` naming only the
  frame loss: an audio-bearing video into `--to png/jpg/tiff/bmp` dropped its
  audio track (and, for `jpg`, its transparency) in complete silence, because
  `-map 0:v:0` is explicit-index and -- unlike the selective rung -- cannot
  name a per-stream drop itself, the same shape `mp3`'s and `flac`'s
  index-named last resort already carries a standing note for. Fixed by
  extending each `last_resort`'s notes with what the explicit index cannot
  reach, and by repeating `jpg`'s transparency note there too, since a source
  with alpha that also needs the last resort never passes through the cheap
  attempt whose standing note would otherwise have named it. Re-verified
  against real ffmpeg 9.0 with an h264+aac source: the audio-drop note now
  prints where it previously printed nothing.
- 2026-08-26: Issue #35 landed the animated-capable trio -- `gif`, `webp`,
  `avif` -- exactly as this spec's resolved decisions pin: `gif` and `avif`
  force their encoder (`-map 0:v? -c:v gif` /
  `-map 0:v? -c:v libaom-av1 -crf:v 30 -still-picture 1`) so their standing
  notes always print; `webp` alone keeps `-map 0:v? -c copy`; masks
  `{gif}`/`{av1}`/`{webp}`, `accept_options=flags("-c:v copy")`,
  `stream_limit=1` (muxer-enforced, not mapping-enforced -- added to
  `MUXER_ENFORCED_LIMIT_TYPES` alongside the image2 four, since none of these
  three muxers holds more than one video *stream* either), `container_options
  =()`, and `fallback_name` declared for all three (`"gif"`, `"webp"`,
  `"av1"`). Neither `gif` nor `webp` carries a frame limit anywhere. Each
  `last_resort` repeats its cheap attempt's standing notes plus what the
  explicit `-map 0:v:0` index cannot reach, the same shape issue #34's review
  established. Re-verified against real ffmpeg 9.0 with four fixtures (a flat
  still, an alpha still, a 20-frame h264 clip, and a 20-frame GIF source):
  `--to gif` and `--to webp` both write all 20 frames of the video source
  (`ffprobe -count_frames` confirms it), `--to avif` writes a single-frame
  primary item for every source and both standing notes print unconditionally
  as designed. One thing this measurement adds to the muxer-facts table:
  ffmpeg 9's AVIF muxer, given a multi-frame source with `-still-picture 1`,
  writes the primary displayed item as one frame but *also* retains the full
  encoded frame sequence in a second, non-primary stream inside the same file
  (`ffprobe -show_streams` lists it as stream index 1, `nb_frames=20`,
  `DISPOSITION:still_image=0`) -- not exposed as the picture an AVIF viewer
  shows, so the "reduced to a single frame" note still describes what is
  actually displayed accurately, and if anything undersells what the file
  retains on disk rather than overselling it. The `last_resort` argv pinned
  above uses `-crf 30` (no `:v`) rather than the cheap attempt's `-crf:v 30`,
  per this spec's own Decision row -- confirmed non-cosmetic and equally
  valid against real ffmpeg (`-map 0:v:0` already selects the one stream a
  bare `-crf` would apply to). A second run over the converted fixtures
  reports `0 converted, 4 skipped`, exit 0.
- 2026-08-26 (#56): `in/flat.png` and `in/flat.jpg` shared the stem `flat`,
  so a single `--to <fmt>` run over `in/` derived the same output path for
  both -- `flat.jpg -> out/flat.png` collides with `flat.png -> out/flat.png`
  itself under `--to png`, and the equivalent collides under every other
  target -- and the collision refusal (exit 2) fired before any conversion
  ran, the same defect phase 3's audio fixtures had. Renamed to
  `flat-png.png` and `flat-jpg.jpg`; `alpha.png` and `clip.mp4` already had
  distinct stems and needed no change. Ran the whole block as written against
  real ffmpeg 9.0 with `--ffmpeg`/`--ffprobe`: all seven targets converted
  `flat-png.png` and opened; `--to png` over `flat-jpg.jpg` produced a real
  PNG (`ffprobe`: `codec_name=png`) and `--to jpg` over `flat-png.png` a real
  JPEG (`codec_name=mjpeg`); `--to jpg` over `alpha.png` dropped the alpha
  (`pix_fmt=yuvj444p`) while `bmp`/`png`/`tiff`/`webp` kept it
  (`bgra`/`rgba`/`rgba`/`yuva420p`) and printed no transparency note; `--to
  gif`/`--to webp` over `clip.mp4` produced 20-frame animated outputs
  (`ffprobe -count_frames`); `--to avif` over `clip.mp4` matched the issue
  #35 entry above exactly (confirmed there, not a new finding -- the
  Verification item was reworded only to point at that entry instead of
  restating an unqualified "single frame" claim); `--to png` over `clip.mp4`
  produced one frame via the `last_resort`, and a second run reported `0
  converted`, exit 0 for every converted tree.

  The avif-vs-webp timing item's pinned "17x" comes from the Prior decisions
  table's own measurement (3000x2000 still, 6.9 s vs 0.41 s). Re-measured
  here on a different, smaller synthetic still (1920x1080, a generated
  Mandelbrot pattern) since no real photograph was available: 6.8 s via
  `avif` against 0.75 s via `webp`, a ~9x gap. Recorded as its own data point
  rather than overwriting the table's figure -- different resolution and
  image content, same conclusion (`avif` is a different, much slower tool
  for a whole folder).
- 2026-08-26: Issue #36 found that almost every item on its own acceptance
  list was already satisfied -- issue #23's registry-wide structural
  invariants (`--list-formats` line count, the README byte-match) cover the
  registry-level checks, and issues #34/#35 already shipped per-profile argv
  pinning for every one of the seven image targets: `cheap_attempt` and
  `last_resort` are pinned element-for-element for each, which by
  construction already settles any membership question about one flag
  (`copy`, `-still-picture`) inside an already-pinned tuple. The "no
  audio/subtitle/attachment rule, `stream_limit=1`" shape is pinned too. Only
  three of the seven profiles (`jpg`, `gif`, `avif`) carry a standing note;
  the other four are pinned as carrying none.
- 2026-08-26: A first draft added four cross-cutting tests on top of that
  coverage. Two independent reviews, each re-running the author's own
  mutation proofs against the *whole* suite rather than just the new test,
  found three of the four added no protection: mutating `PNG`'s cheap
  attempt back to a copy, or adding/removing `-still-picture` on `GIF`'s or
  `AVIF`'s `last_resort`, already failed an existing per-profile argv-pinning
  test in `tests/test_profiles.py` or `tests/test_argv.py` before the new
  test ever ran. One review also found a docstring's supporting claim --
  that such a mutation "would leave each profile's own argv-pinning test
  technically unexamined" -- to be false against the repo it was making the
  claim about. Those three tests were dropped rather than kept as
  belt-and-braces, since the review's own reproduction showed they added
  no coverage a reader could rely on that the docstrings did not already
  overstate.
- 2026-08-26: The fourth -- no profile's `description` mentions EXIF or ICC
  -- survived, re-parametrized over the whole registry rather than the seven
  image profiles alone: `docs/vision.md`'s non-goal is not image-specific,
  and nothing about the check's cost changes with scope. Deliberately
  scoped to `description` alone, not a rung's notes: a note exists to name a
  *loss* (`Attempt.notes`'s own docstring), so a future "EXIF is not
  carried" note would be the honest disclosure `docs/vision.md`'s
  loss-accounting goal asks for, not the promise this non-goal forbids --
  the first draft's version scanned notes too and would have failed exactly
  that desirable text. Proven to fail against a `description` mutated to
  claim EXIF preservation, and to pass against the real registry, in a
  scratch script outside the repo. Machine coverage still cannot prove a
  pinned argv is accepted by real ffmpeg -- the test suite stubs the
  subprocess boundary by constitution -- so that evidence remains whatever
  issues #34 and #35 already measured against ffmpeg 9.0, recorded above.

- 2026-08-26: Close-out. The final QA gate ran against real ffmpeg 9.0 on
  Windows 11, verifying all 17 target formats end-to-end with ffprobe.
  Verdict: PASS WITH FINDINGS; the findings are filed as issues #66-#73.

- 2026-08-27 (#73): Closed all four QA coverage gaps against real ffmpeg
  9.0-full_build-www.gyan.dev on Windows 11 (this build: no `pgssub`
  encoder, `-encoders` lists only `dvdsub`/`dvbsub` as
  bitmap-subtitle-capable outputs). Three of four branches now have observed
  end-to-end evidence; the fourth is recorded as knowingly unproven per this
  issue's own third acceptance bullet.

  **1. Bitmap-subtitle drop branch -- now proven end-to-end.** Reproduced
  the QA gate's exact fixture-creation blocker first: `ffmpeg -f lavfi -i
  color=... -i sample.srt -map 0:v -map 1:s -c:v mjpeg -c:s dvdsub out.mkv`
  fails with `[sost#0:1/dvdsub @ ...] Subtitle encoding currently only
  possible from text to text or bitmap to bitmap`; `-c:s dvbsub` from the
  same text source fails identically. Confirms the QA gate's blocker was
  about *building a fixture from text*, not about the drop branch itself, and
  that this build cannot encode bitmap subtitles from a text source (and
  has no PGS encoder at all, from any source). Rather than hand-rolling a
  binary PGS/VobSub stream, downloaded a real bitmap-subtitle sample from
  ffmpeg's own public FATE sample host,
  `https://samples.ffmpeg.org/sub/PGS/supsample.mkv` (23 KB, h264 720x480 +
  `hdmv_pgs_subtitle` 1280x720, per `ffprobe`). Renamed to
  `pgsfixture.mkv` and ran `.venv/Scripts/python.exe -m converter --to
  <target> --ffmpeg ... --ffprobe ... pgs_in pgs_out_<target>` for
  `mp4`/`mov`/`webm`. All three fired the drop branch and printed the exact
  `drop_reason` strings from `converter/profiles.py` (lines 146, 386, 470):
  `note    pgsfixture.mkv: subtitle stream 1 (hdmv_pgs_subtitle) dropped:
  bitmap subtitles cannot be stored in MP4` (and `MOV`, `WebM`
  respectively; `webm` additionally re-encoded the video to vp9). Each run
  reported `1 converted, 0 skipped, 0 failed, 0 unsupported (of 1)`.
  `ffprobe` on all three outputs confirms the subtitle stream is genuinely
  absent, only the video stream remains. This matches `README.md`'s own
  quoted example (`note    Show.S01E02.mkv: subtitle stream 2
  (hdmv_pgs_subtitle) dropped: bitmap subtitles cannot be stored in MP4`) in
  shape exactly, differing only in filename and stream index. **Branch
  fired and is correct.**

  **2. `--mirror-to` onto a real second physical drive -- recorded as
  knowingly unproven; no second physical drive exists on this machine.**
  `Get-CimInstance Win32_DiskDrive` lists exactly one physical disk,
  `\\.\PHYSICALDRIVE0` ("PVC10 SK hynix 1024GB"). Its four partitions (an
  EFI system partition, a ~862 MB reserved partition, `C:`, and a
  "DELLSUPPORT" ~1.06 GB recovery partition) are all on that one disk;
  `[System.IO.DriveInfo]::GetDrives()` shows only `C:\` as a ready drive
  letter. There is no second physical drive to attach or test against, and
  none can be created without new hardware -- per this issue's own
  acceptance ("If there is no second physical drive, do NOT park the issue
  -- record it as knowingly unproven"), this is recorded as such rather
  than parked. Note also, per the issue text, that issue #72 is concurrently
  changing `--mirror-to` behaviour behind `subst`/junctions on this same
  machine; that work is untouched here.

  **3. The 10-bit/HDR "reduced to 8-bit" last-resort note -- the note's own
  claim is confirmed true when the rung actually runs, but the rung is not
  reachable through the normal ladder with this ffmpeg build.** This
  build's `libx264` supports high bit depth natively (`ffmpeg -h
  encoder=libx264`: "Supported pixel formats: yuv420p yuvj420p yuv422p
  yuvj422p yuv444p yuvj444p nv12 nv16 nv21 yuv420p10le yuv422p10le
  yuv444p10le nv20le gray gray10le"). Built a genuine 10-bit HDR fixture:
  `ffmpeg -f lavfi -i "testsrc2=...,format=yuv422p10le,setparams=
  color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc" ... -c:v
  prores_ks -profile:v 3 -pix_fmt yuv422p10le -color_primaries bt2020
  -color_trc smpte2084 -colorspace bt2020nc -c:a pcm_s16le
  source_prores_hdr.mov`, verified by `ffprobe`
  (`pix_fmt=yuv422p10le`, `bits_per_raw_sample=10`,
  `color_primaries=bt2020`, `color_transfer=smpte2084`). MP4's muxer
  refuses `prores` outright (`Could not find tag for codec prores in
  stream #0, codec not currently supported in container`), so the cheap
  attempt fails as expected and the engine falls to the selective rung. Ran
  `--to mp4` on this fixture: the batch reported `note ...: video stream 0
  (prores) re-encoded to h264` and `note ...: audio stream 1 (pcm_s16le)
  re-encoded to aac` -- no bit-depth note -- and `ffprobe` on the output
  shows `codec_name=h264`, `pix_fmt=yuv422p10le`, `bits_per_raw_sample=10`,
  `color_primaries=bt2020`, `color_transfer=smpte2084`: the selective
  rung's fallback (`-c:v:{n} libx264 -crf:v:{n} 18`, no forced `-pix_fmt`)
  encoded straight through at the source's own 10-bit 4:2:2 depth and kept
  the HDR tags, because this `libx264` build accepts that pixel format
  directly. The `last_resort` rung -- the only place carrying the
  "reduced to 8-bit" note, per `converter/profiles.py` lines 158, 325, 406
  -- was never reached, because the selective rung already succeeded.
  Reproduced the same pattern for `mov` with a second fixture (10-bit
  `av1`, `yuv420p10le`, bt2020/smpte2084, built via `libaom-av1`, not in
  `MOV_VIDEO_CODECS`): `--to mov` again re-encoded via the selective rung
  only (`note ...: video stream 0 (av1) re-encoded to h264`), and the
  output is `h264 (High 10)`, `pix_fmt=yuv420p10le`, `bits_per_raw_sample=10`,
  HDR tags intact. `mkv`'s video fallback (`-c:v:{n} libx264 -crf:v:{n}
  18`, read from `converter/profiles.py`) is textually identical to
  `mp4`'s and `mov`'s, so the same mechanism is expected to apply there
  too, but this was not independently measured. To isolate whether the
  note's own *claim* is at least true, ran the `mp4` profile's pinned
  `last_resort` argv directly and by hand against the ProRes/HDR fixture:
  `ffmpeg -i source_prores_hdr.mov -map 0:v:0? -map 0:a? -c:v libx264 -crf
  18 -preset medium -pix_fmt yuv420p -c:a aac -b:a 192k -movflags
  +faststart last_resort_test.mp4`. `ffprobe` on that output shows
  `pix_fmt=yuv420p`, `bits_per_raw_sample=8` -- the explicit `-pix_fmt
  yuv420p` really does force the reduction the note describes, whenever
  this rung actually runs. **Branch's own claim verified true by direct
  measurement of its argv; the branch is not reachable through the normal
  ladder with this ffmpeg build and these fixtures, because the selective
  rung's un-pinned `-pix_fmt` lets a high-bit-depth-capable `libx264`
  preserve depth instead of failing.** Also worth recording alongside this
  issue's own "Also worth recording" section: the resulting MP4 (`h264
  (High 4:2:2)`, 10-bit, `yuv422p10le`) decodes cleanly under `ffmpeg -v
  error -i ... -f null -` (exit 0, no stderr) -- the QA gate's own
  "plays" check -- yet High 4:2:2 Profile at 10-bit is a professional/
  broadcast H.264 profile that ordinary consumer software and hardware
  decoders commonly do not support, a third live example of the same
  "remuxed/encoded successfully into a container many players refuse"
  caveat already illustrated by ffv1-in-MP4 (#69) and vorbis-in-`.opus`
  (#68).

  **4. Windows `MAX_PATH` long-path branch -- proven end-to-end, both as a
  direct call and through the full CLI.** Confirmed `HKLM:\SYSTEM\
  CurrentControlSet\Control\FileSystem!LongPathsEnabled` is `0` on this
  machine (long-path support is off, so the classic 260-character limit
  applies). Direct call: built a path 316 characters long under a temp
  directory and called `converter.paths.ensure_directory` on it directly.
  It raised `OSError` reading `[WinError 206] Der Dateiname oder die
  Erweiterung ist zu lang: '...aaaaaaaaaaaaaaaaaaaa'` (Windows stopped
  four segments deep, at the point the accumulating path itself first
  exceeded the limit -- consistent with `pathlib`'s `mkdir(parents=True)`
  creating parents one level at a time) followed on the next line by the
  code's own appended text verbatim: `The path is 316 characters long, and
  Windows rejects paths over 260 characters unless long-path support is
  enabled -- a common cause of this error. Choose a shorter output root, or
  see the README.` End-to-end: ran the real CLI, `.venv/Scripts/
  python.exe -m converter --to mp4 --ffmpeg ... --ffprobe ...
  longpath_cli_in <340-char-deep-output-root>`, over a one-file input
  directory. The batch never got as far as invoking ffmpeg on that run;
  the process printed `error: [WinError 206] ... The path is 340
  characters long, and Windows rejects paths over 260 characters ...` to
  stderr and exited with code 1 -- the bare `OSError` handler in
  `converter/cli.py`'s `main()` (`except (OSError, ValueError) as exc:
  print(f"error: {exc}", ...); return 1`), which is uncaught anywhere
  closer to the individual file, so a single too-deep output path aborts
  the whole run rather than being reported as one failed file among
  others. Both deep trees were removed afterward via `shutil.rmtree` with
  a `\\?\` long-path-prefixed literal (needed since the plain path could
  no longer be addressed once nested past the limit); no subst drive was
  needed since the scratch directory's own path (139 characters) left
  enough of the 260-character budget to reach the threshold without one.
  **Branch fired and is correct**, and the CLI-level side effect
  (whole-run abort rather than per-file failure) is recorded as an
  observation, not a defect -- it was not evaluated against any documented
  contract for per-file isolation at this specific precondition.

  No acceptance item above is ticked without the observed evidence quoted
  next to it. Item 2 is the one gap this round leaves genuinely unproven,
  exactly as its own acceptance bullet anticipates.

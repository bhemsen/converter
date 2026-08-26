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

- [Image conversion through ffmpeg (Phase 5)](../prior-art.md#image-conversion-through-ffmpeg-phase-5)
  — the concern tagged for this phase. Its ADOPT is confirmed by measurement: all
  seven formats have working ffmpeg muxers, so images need no second backend. Its
  AVOID is why EXIF/ICC preservation is a non-goal rather than a bug.
- [Container/codec capability modelling (Phase 1)](../prior-art.md#containercodec-capability-modelling-phase-1)
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
& $FF -y -f lavfi -i color=c=red:size=320x240:d=1 -frames:v 1 in/flat.png
& $FF -y -f lavfi -i color=c=red:size=320x240:d=1 -frames:v 1 in/flat.jpg
& $FF -y -f lavfi -i "color=c=red@0.5:size=320x240:d=1,format=rgba" -frames:v 1 in/alpha.png
& $FF -y -f lavfi -i testsrc=size=320x240:rate=10:duration=2 -c:v libx264 in/clip.mp4
```

- [ ] Each of the seven targets converts `flat.png` and the result opens.
- [ ] `--to png in out` over `flat.jpg` produces a **real PNG** — `ffprobe` it,
      and check `file` too. A stream copy would produce a JPEG named `.png` at
      exit 0, which is the defect this phase's cheap attempts exist to prevent.
- [ ] `--to jpg in out` over `flat.png` produces a real JPEG, same check.
- [ ] `--to jpg in out` over `alpha.png` prints the transparency note, and the
      output's `pix_fmt` shows the alpha is gone. `--to bmp`, `--to png`,
      `--to tiff` and `--to webp` keep it and print no such note. Repeat for
      `--to gif` and `--to avif`, whose standing notes now always print.
- [ ] `--to gif in out` over `clip.mp4` produces an **animated** GIF, and
      `--to webp` an animated WebP: count frames with `ffprobe -count_frames`.
- [ ] `--to avif in out` over `clip.mp4` produces a single frame and says so.
- [ ] `--to png in out` over `clip.mp4` produces a single frame via the
      `last_resort` and names it; a second run reports the same thing, exit 0.
- [ ] `--to gif in out` over a photograph names the colour quantisation, via its standing note.
- [ ] Time `--to avif` over a large still and compare with `--to webp`. The
      measured gap is 17x; confirm it is tolerable on real photographs.
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

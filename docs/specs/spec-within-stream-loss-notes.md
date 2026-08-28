# Spec: within-stream-loss-notes (roadmap phase 8)

> Created: 2026-08-28

Stop telling an opaque image that its transparency was not carried, and name the
stream when it really was — closing the half of issue #67 that its file boundary
could not reach. This spec carries no lifecycle state — acceptance is the spec
merged on the default branch with a milestone and issues, and all progress lives
in the GitHub issues and milestone. A completed spec is moved to
`docs/specs/archive/`.

**This phase is not on the seeded roadmap.** It comes from issue #101, which
#67's PR filed as an explicit unresolved finding rather than dropping it. Its
roadmap row is added in this PR; its Spec and Milestone links are filled at the
acceptance gate like every other phase's.

## The defect

`jpg`, `gif` and `avif` carry static notes on their cheap attempt, true of the
format and fired on every file — so a plain opaque JPEG is told its transparency
was not carried. They name neither a stream index nor a codec.

Retiring them is not the answer, and #67 correctly did not: these are losses
*inside* a stream that is kept, so `_structural_drop` sees nothing and there is
no per-stream note to fall back on. Removing them would be a silent loss.

## What is achievable, and what is not

The probe can answer the transparency question **for some source formats and not
others**, and the honest design says which. Measured:

| Source reports | Verdict | Consequence |
|---|---|---|
| `yuvj420p`, `yuv420p`, `rgb24`, `gbrp`, … | definitely no alpha | note suppressed — **this is the reported defect, fixed** |
| `rgba`, `bgra`, `yuva420p`, … | carries alpha | note fires, naming the stream |
| `pal8` | *may* carry alpha — the name says nothing | note fires: over-reporting is the safe direction |
| any `.gif` source | ffmpeg's gif decoder reports `bgra` **unconditionally**, opaque or not | note fires on every GIF source — unchanged from today, not improved |

The residuals are named rather than hidden. Over-reporting is chosen wherever the
probe is not decisive, because the constitution forbids the other direction.

## Outcome

- [ ] A source whose pixel format definitely carries no alpha emits **no**
      transparency note for `jpg`, `gif` or `avif`. The reported case — an opaque
      `yuvj420p` JPEG — is covered.
- [ ] A source that carries alpha still gets the note, naming the stream index
      and that stream's codec.
- [ ] A source the probe cannot decide (`pal8`, any `.gif`) still gets the note,
      and that residual is documented rather than silently accepted.
- [ ] Whatever this phase does about `avif`'s frame-reduction note leaves a
      statement true for every input, per the gate's decision — and the gate is
      told plainly if that leaves an issue-#101 criterion unmet.
- [ ] `GIF holds at most a 256-colour palette` is untouched — #67 already
      restated it as a format fact.
- [ ] The number of ffprobe **processes** per conversion is unchanged.
- [ ] Every branch ships with a test asserting the note it emits, each proven
      non-vacuous by inverting its condition.

## Scope

### In scope

- `converter/ffmpegtool.py`: a `pix_fmt` field on `Stream` and the matching entry
  in `probe_streams`' existing query; plus, only under the gate's option 1,
  `-count_packets` and a packet-count field.
- `converter/profiles.py`: a curated `ALPHA_FREE_PIX_FMTS` frozenset beside
  `LOSSY_CODECS`, and the per-target declarations that replace the static notes
  on `jpg`, `gif` and `avif`.
- `converter/jobs.py`: the within-stream verdict and its note — plus the fourth
  restatement of the success-side boundary, at `jobs.py:249-251`, which currently
  says the verification is "unchanged, off limits to any codec claim".
- `converter/batch.py`: the hook. The note must be appended **after**
  `_verify_cheap_attempt`'s `if not predicted: return ()` gate, or every alpha
  source falls through to `_confirm_against_output` and gains a second ffprobe.
- `docs/architecture.md` Key flow 1, `docs/design/degradation-ladder.md` and the
  `jobs` docstring: the success-side boundary this phase widens.
- `docs/design/stream-decision.md`: a third carve-out from the three-things rule
  — see the decision on the notes this phase *keeps*.
- `README.md:208-217`, which states the current unconditional behaviour verbatim
  and becomes false. #67's acceptance criterion 3 required the README to describe
  it; leaving it stale regresses a satisfied criterion.
- `docs/roadmap.md`: the phase-8 row.
- The tests for all of it.

### Out of scope

- **The colour-count condition.** Counting distinct colours needs a decode pass.
  #67 already restated GIF's palette note as a format fact, which the issue's own
  acceptance criterion accepts.
- Detecting whether an alpha channel is *used* rather than present. Reading pixel
  values is a decode pass.
- Any note on a target that carries the property: `png`, `tiff`, `bmp` and `webp`
  keep alpha (measured) and gain nothing here.
- Any change to which conversions happen or what argv they build.
- Revisiting phase 7's decision to confine the lossy advisory to `flac`, although
  this phase's widening removes the obstacle that gate cited.

## Constraints

- The ffprobe **process** count per conversion is unchanged; the output-side
  confirmation probe stays conditional on there being a predicted drop (#18, #66).
- Never parse ffmpeg's stderr.
- A target format is data, not code: what an encoder cannot hold is a profile
  declaration, and the alpha-free pixel-format set is curated data in
  `profiles.py` — `converter/jobs.py`'s own docstring forbids it holding a
  format-specific fact.
- Never report success for a conversion that silently dropped something — and,
  its mirror, never announce a loss that did not happen. This phase exists
  because the second half is currently violated; where the two conflict, the
  first wins.
- The test suite keeps passing with no ffmpeg installed.

## Prior art

- [Image conversion through ffmpeg (Phase 5)](../prior-art.md#image-conversion-through-ffmpeg-phase-5)
  — the concern that produced these notes. Its AVOID (never promise EXIF/ICC
  preservation) is the same discipline: state what is true of the file at hand,
  not of the format in general.
- [Container/codec capability modelling (Phase 1)](../prior-art.md#containercodec-capability-modelling-phase-1)
  — the method. `ffmpeg -pix_fmts` lists 267 formats with flags `I/O/H/P/B` and
  **no alpha flag** (measured), so the alpha-free set is curated by hand, exactly
  as the copy masks and `LOSSY_CODECS` are.

## Design

No new design artifact. `docs/design/degradation-ladder.md` and
`docs/design/stream-decision.md` are amended, not added to.

## Human prerequisites

- none.

## Prior decisions

### The measured facts these decisions rest on

Measured against ffmpeg 9.0; the review is asked to falsify.

| Fact | Consequence |
|---|---|
| **`pix_fmt` is free** in the existing `-show_entries` query — no extra process. In `-of json`, which the parser reads, the key is simply **absent** for an audio stream, not `"N/A"` (that is the CSV writer's rendering) | The transparency condition costs nothing. An implementer must test for absence, not for the string `N/A` |
| **`ffmpeg -pix_fmts` has no alpha flag**: 267 formats, flags `I/O/H/P/B` only | The alpha-free set is curated, like every other codec fact here |
| **ffmpeg's gif decoder reports `bgra` for every GIF**, opaque or not — measured on a GIF built from a fully opaque PNG | Every `.gif` source over-reports. `.gif` is a first-class source suffix, so this is a whole format, not an edge case |
| **`pal8` carries no alpha marker but can carry alpha**: a paletted PNG with real transparency reports `pal8`, and into `jpg` the alpha is genuinely destroyed | Excluding it would be a silent loss; including it over-reports on opaque paletted images. Over-reporting is the safe side |
| **An AVIF source reports `gbrp` either way** — but this build cannot write alpha into AVIF at all: `-pix_fmt yuva420p` comes back as `yuv420p` | The theoretical false negative has no reachable input on this build. Recorded, not designed around |
| **The output side cannot be used.** An alpha PNG into GIF yields an output reporting `pix_fmt=bgra` while the channel is opaque (source α `0x7f`, output `0xff`); `jpg` (`yuvj444p`) and `avif` (`gbrp`) do report honestly | The verdict is source-measured ∧ target-declared. It also needs no output probe |
| `png`, `tiff`, `bmp` and `webp` preserve alpha (`rgba`, `rgba`, `bgra`, `yuva420p`, α `0x7f` intact) | Only `jpg`, `gif` and `avif` declare the limitation |
| **`nb_frames` is present for `mp4` and `gif`, absent for `mkv`, `png`, `jpg`** | A hybrid — use `nb_frames` where present — is a real third option for the frame note; see the open decision |
| **`-count_packets` rides the same argv, so the process count is unchanged.** Median of 7: 38.9 MB/1 h → +88 ms; 149.8 MB → +101 ms; **1198 MB → +875 ms**. Roughly 0.7 ms per MB demuxed | The cost is not flat. And `probe_streams` is one function: the failure-side probe and the output-confirmation probe would pay it too, not only the source probe |
| **`-count_frames` is 3x the plain probe** — it decodes | Never an option |
| Today, an alpha PNG into `jpg`/`gif`/`avif` runs **1 ffmpeg + 1 ffprobe**, because `verify_success` returns `()` and `batch._verify_cheap_attempt` short-circuits before the output probe | The hook must sit after that gate, or the process count rises |

### Decisions

| Decision | Rationale | Date |
|---|---|---|
| The verdict is **source-measured ∧ target-declared**, never an output comparison | Measured: the output side reports GIF's alpha as preserved exactly where it was lost. Source-plus-declaration is correct for all three and needs no output probe | 2026-08-28 |
| The condition is **"the source's pixel format is not in the curated alpha-free set"** — over-reporting wherever the probe is not decisive | The constitution forbids the silent-loss direction; `pal8` and every `.gif` source are the cases that forces. The reported defect (`yuvj420p`) is decisive and is fixed | 2026-08-28 |
| `ALPHA_FREE_PIX_FMTS` is a curated module-level frozenset in `converter/profiles.py`, beside `LOSSY_CODECS` | `converter/jobs.py`'s docstring: the engine holds no format-specific fact. The same placement phase 7 recorded for its own curated set | 2026-08-28 |
| **The boundary widens to: a profile whose cheap attempt forces a single declared encoder unconditionally may declare what that encoder cannot hold.** A copy-based cheap attempt gets no such note | The first draft argued "this asserts nothing about the encode" — refuted by `docs/specs/archive/spec-stream-disposition.md`, which already records that AVIF's notes are true of *this profile's forced pipeline*, "not of the AVIF format, which does support alpha and multiple frames elsewhere". Measured, the same holds for GIF: GIF89a has a transparent palette index and ffmpeg's encoder drops it anyway. So for two of three targets the declaration *is* an encoder claim — which is safe only because those profiles always run that encoder. `webp`'s `-c copy` cheap attempt is the case the rule must exclude, and a test pins it | 2026-08-28 |
| The note names the stream index and codec, and is emitted from a new engine entry point called by `batch._verify_cheap_attempt` **after** its `if not predicted` gate. It never enters `confirm_drops` | Measured: returning it from `verify_success` sends every alpha source into the output probe, raising the process count and running `_surplus` arithmetic that is meaningless for a stream that was never a predicted drop | 2026-08-28 |
| `jpg`'s "the image was re-encoded" half stays unconditional | Its cheap attempt forces its encoder for every input | 2026-08-28 |
| **`docs/design/stream-decision.md` gains a third carve-out**: a *format-limit statement* is not a per-stream verdict and is not bound by the three-things rule | The notes this phase keeps — `jpg`'s re-encode half, GIF's palette line, every `last_resort` note, and `AVIF holds a single frame` under option 2 — name neither index nor codec and fall under neither existing carve-out. `spec-stream-disposition.md` records them as an open violation; closing #101 while leaving it unnamed would be the same omission in a new place | 2026-08-28 |
| OPEN — whether `avif`'s frame-reduction note becomes conditional, and at what cost | resolved at the spec-acceptance gate; see the note below | — |

### The one open decision, in full

Transparency rides the existing query for nothing. The frame note does not.

Measured, median of 7, same argv shape `probe_streams` builds:

| Source | plain | with `-count_packets` |
|---|---|---|
| small PNG, 1.9 MB MP3 | — | lost in startup noise |
| 38.9 MB mp4 (1 h, 90 000 packets) | 92 ms | 180 ms |
| 149.8 MB mp4 | 122 ms | 223 ms |
| **1198 MB mp4** | 128 ms | **1003 ms** |

Roughly **0.7 ms per MB demuxed**; a 4 GB rip is about 3 s per file. And
`probe_streams` is a single function, so the flag would be paid by the
failure-side probe and the output-confirmation probe too, not only by the source
probe on success. All 17 profiles declare `partial_mapping=True`, so every
conversion is probed.

1. **Take the cost; make the frame note conditional.** Closes issue #101 fully.
   The price is the table above, on every probe in the system.
2. **Leave the frame note as a format fact** — "AVIF holds a single frame" —
   the way #67 left GIF's palette note. Free. **But it leaves issue #101's
   acceptance criterion 3 unmet**: that criterion reads *"A single-frame source
   into `avif` emits no frame-reduction note; a multi-frame source still does,
   naming the stream"*, unhedged, unlike its palette criterion which explicitly
   allows a restatement. Picking this means #101 stays open on that point, or is
   amended to say so.
3. **The hybrid: use `nb_frames` where the container provides it.** Measured
   present for `mp4` and `gif` — the two multi-frame containers that matter most
   here — and absent for `mkv`, `png`, `jpg`. Free, but only sometimes available,
   so the note would fire for an `.mp4` source and not for an `.mkv` one: a
   silent inconsistency rather than a stated one, which is why it is listed last.

## Tracking

- Milestone: within-stream-loss-notes (created at the spec-acceptance gate)
- Issues: created from this spec once it is merged (one per implementable step)

## Verification

Machine checks:

- [ ] Verify passes on the merge commit.
- [ ] A test that `probe_streams` fills `pix_fmt` from a stubbed **JSON** payload
      where the key is *absent* for an audio stream, and that the
      `-show_entries` argument is pinned verbatim.
- [ ] A test that the ffprobe **process count** per conversion is unchanged, for
      an alpha source into each of the three targets.
- [ ] Per target, a test that an alpha source emits the note naming the stream
      index and codec, and that a `yuvj420p` source emits none — the reported
      defect, pinned.
- [ ] A test that a `pal8` source and a `.gif` source both emit the note, so the
      documented over-reporting is deliberate rather than accidental.
- [ ] A test that `png`, `tiff`, `bmp` and `webp` emit no transparency note for an
      alpha source.
- [ ] A test that the verdict does **not** consult the output's `pix_fmt` — the
      GIF false-negative case an output-comparison implementation would fail.
- [ ] A test that a **copy-based** cheap attempt emits no such note, pinning the
      widened boundary's limit.
- [ ] The two tests that pin the current boundary are narrowed rather than
      deleted: `tests/test_argv.py::test_a_codec_outside_the_copy_mask_produces_no_note`
      and `::test_no_profile_invents_a_loss_for_a_source_it_fully_maps`, the
      latter gaining the image profiles to its parametrisation.
- [ ] Under option 1 only: a single-frame source into `avif` emits no frame note
      and a multi-frame one does, naming the stream.
- [ ] Each branch proven non-vacuous: inverting its condition must fail a test.

Human milestone-QA gate. `$FF` is the absolute ffmpeg path from *This machine*;
distinct stems throughout:

```text
New-Item -ItemType Directory -Force in
& $FF -y -f lavfi -i "color=c=red@0.5:size=200x200:d=1,format=rgba" -frames:v 1 in/alpha-src.png
& $FF -y -f lavfi -i color=c=red:size=200x200:d=1 -frames:v 1 in/opaque-src.jpg
& $FF -y -i in/alpha-src.png -vf "split[a][b];[a]palettegen=reserve_transparent=1[p];[b][p]paletteuse" -frames:v 1 in/pal8-src.png
& $FF -y -i in/opaque-src.jpg -c:v gif in/opaque-gif-src.gif
& $FF -y -f lavfi -i testsrc=size=160x120:rate=10:duration=2 -c:v libx264 in/multi-src.mp4
```

- [ ] `--to jpg in out` over `opaque-src.jpg`: **no** transparency note. This is
      the reported defect; check it first.
- [ ] `--to jpg in out` over `alpha-src.png`: the note fires, naming the stream
      index and `png`.
- [ ] `--to jpg in out` over `pal8-src.png` and `opaque-gif-src.gif`: the note
      fires. Confirm this matches what the spec says it should do — these are the
      documented over-reports, not defects.
- [ ] `--to gif` and `--to avif` over `alpha-src.png` and `opaque-src.jpg`: same
      pattern. `gif` is the one an output-side check would get wrong.
- [ ] `--to png in out` over `alpha-src.png`: no note, and `ffprobe` shows the
      alpha survived.
- [ ] `--to avif in out` over `multi-src.mp4` behaves as the gate decided.
- [ ] Time a conversion of a **large** video (>1 GB) before and after, and record
      the probe cost observed against the table above.
- [ ] A second run over any converted tree reports `0 converted`, exit 0.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| An implementer reaches for the output-side comparison, as `confirm_drops` does | The GIF false negative is a fact row, a decision row and a dedicated test |
| The note is hooked into `verify_success` and the process count rises | Measured today's count as 1 ffmpeg + 1 ffprobe, named the gate it must sit after, and pinned it with a test |
| The widened boundary licenses a note on a copy-based attempt | The boundary is stated as forced-encoder-only, with a test on `webp`'s copy attempt |
| A fifth restatement of the boundary is missed | Four are named in Scope, including `jobs.py:249-251`, which the first draft missed — the same omission `#38`'s follow-up commit exists for |
| Over-reporting on `pal8` and `.gif` is read as a bug | Both are in the Outcome, the fact table and the QA gate as deliberate |
| `-count_packets` costs more on real media than the table suggests | The table now runs to 1.2 GB with a per-MB figure, and the QA gate measures a >1 GB file |

## Decision log

- 2026-08-28: The issue's headline worry — that conditioning these notes needs a
  wider probe budget — is only half true. `pix_fmt` rides the existing query for
  nothing; only the frame count costs anything, and even that stays one process.
- 2026-08-28: The obvious implementation, comparing the output's `pix_fmt` as
  `confirm_drops` compares streams, was measured and rejected: GIF's output
  reports an alpha-capable `bgra` while the channel is opaque.
- 2026-08-28: Review round 1 found the same measurement unread on the *source*
  side — every `.gif` source reports `bgra`, so the note over-reports for a whole
  source format — and that `pal8` hides real alpha. The condition became "not in
  the curated alpha-free set", erring toward reporting, with both residuals
  stated in the Outcome rather than buried.
- 2026-08-28: Review round 1 also refuted the widening's first argument using an
  archived spec in this tree: for `gif` and `avif` the "target cannot hold it"
  half *is* an encoder-behaviour claim, since both formats support alpha
  elsewhere. The boundary is restated as forced-encoder-only, which is what
  actually makes it safe, and a copy-based attempt is excluded by test.

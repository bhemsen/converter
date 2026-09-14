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
| Any 1- or 3-component format: `yuvj420p`, `yuv420p`, `yuv420p10le`, `rgb24`, `nv12`, `gray`, … (184 of them) | no alpha component exists | note suppressed — **this is the reported defect, fixed** |
| `rgba`, `bgra`, `yuva420p`, … | carries alpha | note fires, naming the stream |
| `pal8` | *may* carry alpha — the name says nothing | note fires: over-reporting is the safe direction |
| any `.gif` source | ffmpeg's gif decoder reports `bgra` **unconditionally**, opaque or not | note fires on every GIF source — unchanged from today, not improved |
| `gbrp` from an `.avif` source | ffmpeg reports `gbrp` whether or not the file carried alpha | note suppressed, on decode-side grounds -- see the fact table. Not "definitely no alpha": the format has three components, but the *source file* may have had an alpha aux item ffmpeg never surfaces |

The residuals are named rather than hidden. Over-reporting is chosen wherever the
probe is not decisive, because the constitution forbids the other direction.

## Outcome

- [ ] A source whose pixel format is a member of `ALPHA_FREE_PIX_FMTS` emits
      **no** transparency note for `jpg`, `gif` or `avif`. The reported case — an
      opaque `yuvj420p` JPEG — is covered.
- [ ] A source that carries alpha still gets the note, naming the stream index
      and that stream's codec.
- [ ] A source the probe cannot decide (`pal8`, any `.gif`) still gets the note,
      and that residual is documented rather than silently accepted.
- [ ] The conditional note reaches both rungs that hold a stream list -- the cheap
      attempt and the selective rung. On `last_resort`, which holds none, a
      format-limit statement remains, and the spec says so rather than implying
      the note is conditional everywhere.
- [ ] `avif`'s frame-reduction note reads as a format fact true for every input,
      and no `-count_packets` enters any probe. Issue #101's acceptance criterion
      3 is knowingly left unmet and recorded as such.
- [ ] `GIF holds at most a 256-colour palette` is untouched — #67 already
      restated it as a format fact.
- [ ] The number of ffprobe **processes** per conversion is unchanged.
- [ ] Every branch ships with a test asserting the note it emits, each proven
      non-vacuous by inverting its condition.

## Scope

### In scope

- `converter/ffmpegtool.py`: a `pix_fmt` field on `Stream` and the matching entry
  in `probe_streams`' existing query. No `-count_packets` and no packet-count
  field: the gate declined them.
- `converter/profiles.py`: the generated `ALPHA_FREE_PIX_FMTS` frozenset beside
  `LOSSY_CODECS`, and the per-target declarations that replace the *cheap-attempt*
  static notes on `jpg`, `gif` and `avif`. Their `last_resort` tuples
  (`profiles.py:1040`, `:1176`, `:1252`) keep a format-limit statement -- that rung
  never sees a stream list. Their `description` fields (`:1007`, `:1130`, `:1219`)
  are **deliberately untouched**: `--list-formats` states what a target can hold,
  which is a format fact and belongs there.
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
- Never report success for a conversion that silently dropped something
  (`docs/constitution.md`). Its mirror -- never announce a loss that did not
  happen -- and the precedence between them are **this spec's own rule, not the
  constitution's**: where they conflict, the constitution's half wins, which is why
  every undecidable case here over-reports. Stated rather than smuggled in as a
  quotation.
- The test suite keeps passing with no ffmpeg installed.

## Prior art

- [Image conversion through ffmpeg (Phase 5)](../prior-art.md#image-conversion-through-ffmpeg-phase-5)
  — the concern that produced these notes. Its AVOID (never promise EXIF/ICC
  preservation) is the same discipline: state what is true of the file at hand,
  not of the format in general.
- [Container/codec capability modelling (Phase 1)](../prior-art.md#containercodec-capability-modelling-phase-1)
  — the method, with one difference that must be stated rather than borrowed.
  Unlike a copy mask, this set has an authoritative source: `ffprobe
  -show_pixel_formats` reports `flags.alpha` per format. It is still curated data
  in the same module, for `LOSSY_CODECS`' own reasons -- the happy path spends no
  subprocess on it and the suite must pass with no ffmpeg installed -- but it is
  *generated* from that flag rather than judged. And its *failure mode inverts
  theirs*: `LOSSY_CODECS` records that "a missing codec is a known, disclosable
  gap", where an omission yields silence. An omission here yields a **false note
  on an ordinary file**, the very defect this phase removes.

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
| **`ffprobe -show_pixel_formats -of json` reports a per-format `flags.alpha`** -- the authoritative discriminator. 267 formats: 67 with alpha, 200 without -- of which 16 are hwaccel placeholders, leaving **184** that can actually be a file's reported format. (`ffmpeg -pix_fmts` does *not* expose it, which is the binary the first draft measured and the reason it wrongly concluded no such flag exists) | The set is **generated** from `flags.alpha` and checked in as a literal. It is curated data not because ffmpeg cannot answer, but because the suite must pass with no ffmpeg installed and the happy path spends no subprocess on it |
| **Component census, cross-checked against that flag**: 59 four-component and 7 two-component (`ya8`, `ya16be/le`, `yaf16be/le`, `yaf32be/le`) carry alpha; 165 three-component and 20 one-component do not; 16 zero-component are hwaccel placeholders. Every 1- or 3-component format except `pal8` has `alpha=0`, and every 2- or 4-component format has `alpha=1` -- measured, zero holes in either direction | 184 members. The component rule agrees with the flag exactly today, but it is a *proxy*: the two are independent facts, so the roster is generated from the flag and the rule is only the sanity check |
| **ffmpeg's gif decoder reports `bgra` for every GIF**, opaque or not — measured on a GIF built from a fully opaque PNG | Every `.gif` source over-reports. `.gif` is a first-class source suffix, so this is a whole format, not an edge case |
| **`pal8` carries no alpha marker but can carry alpha**: a paletted PNG with real transparency reports `pal8`, and into `jpg` the alpha is genuinely destroyed | Excluding it would be a silent loss; including it over-reports on opaque paletted images. Over-reporting is the safe side |
| **An AVIF source reports `gbrp` either way.** No AV1 decoder path in this build surfaces an alpha aux item, and the `mov` demuxer that reads AVIF exposes no option for one (measured by review; the encode side agrees -- `-pix_fmt yuva420p` comes back `yuv420p`) | Where an AVIF source did carry alpha, ffmpeg had already dropped it **at decode, before the engine saw the file**. Suppressing the note is then correct rather than a silent loss: this conversion did not take it away. The reachable-input argument the first draft used was encode-side and could not carry a decode-side question |
| **The output side cannot be used.** An alpha PNG into GIF yields an output reporting `pix_fmt=bgra` while the channel is opaque (source α `0x7f`, output `0xff`); `jpg` (`yuvj444p`) and `avif` (`gbrp`) do report honestly | The verdict is source-measured ∧ target-declared. It also needs no output probe |
| `png`, `tiff`, `bmp` and `webp` preserve alpha (`rgba`, `rgba`, `bgra`, `yuva420p`, α `0x7f` intact) | Only `jpg`, `gif` and `avif` declare the limitation |
| **`nb_frames` is present for `mp4` and `gif`, absent for `mkv`, `png`, `jpg`** -- in `-of json` the key is genuinely **omitted**, not `"N/A"`, exactly as with `pix_fmt` | A hybrid — use `nb_frames` where present — is a real third option for the frame note; see the open decision |
| **`-count_packets` rides the same argv, so the process count is unchanged.** Median of 7: 38.9 MB/1 h → +88 ms; 149.8 MB → +101 ms; **1198 MB → +875 ms**. Roughly 0.7 ms per MB demuxed | The cost is not flat. And `probe_streams` is one function: the failure-side probe and the output-confirmation probe would pay it too, not only the source probe |
| **`-count_frames` is 3x the plain probe** — it decodes | Never an option |
| Today, an alpha PNG into `jpg`/`gif`/`avif` runs **1 ffmpeg + 1 ffprobe**, because `verify_success` returns `()` and `batch._verify_cheap_attempt` short-circuits before the output probe | The hook must sit after that gate, or the process count rises |

### Decisions

| Decision | Rationale | Date |
|---|---|---|
| The verdict is **source-measured ∧ target-declared**, never an output comparison | Measured: the output side reports GIF's alpha as preserved exactly where it was lost. Source-plus-declaration is correct for all three and needs no output probe | 2026-08-28 |
| The condition is **"the source's pixel format is not in the curated alpha-free set"** — over-reporting wherever the probe is not decisive | The constitution forbids the silent-loss direction; `pal8` and every `.gif` source are the cases that forces. The reported defect (`yuvj420p`) is decisive and is fixed | 2026-08-28 |
| `ALPHA_FREE_PIX_FMTS` is a module-level frozenset in `converter/profiles.py`, beside `LOSSY_CODECS`, **generated from `ffprobe -show_pixel_formats`' `flags.alpha`** and checked in as a literal: the formats reporting `alpha=0` **and** `hwaccel=0`. That second filter is not cosmetic -- `alpha=0` alone yields 200, of which 16 are hwaccel placeholders (`vaapi`, `cuda`, `d3d11va_vld`, ...) that can never be a source file's reported `pix_fmt`; excluding them gives **184**, which is also exactly what the component cross-check yields. The regeneration command carries both filters, so the command and the number agree | Placement follows `jobs.py`'s docstring -- the engine holds no format-specific fact -- and phase 7's precedent. But the *failure mode inverts* that precedent and must be stated: `LOSSY_CODECS` records "a missing codec is a known, disclosable gap", where an omission yields silence; an omission here yields a **false note on an ordinary file**, the very defect this phase removes. Generating it from the flag rather than hand-listing 184 entries is what keeps that from rotting, and the test pins the roster as a constant so the suite still runs with no ffmpeg | 2026-08-28 |
| **The boundary widens to: a profile whose cheap attempt forces a single declared encoder unconditionally may declare what that encoder cannot hold.** A copy-based cheap attempt gets no such note | The first draft argued "this asserts nothing about the encode" — refuted by `docs/specs/archive/spec-stream-disposition.md`, which already records that AVIF's notes are true of *this profile's forced pipeline*, "not of the AVIF format, which does support alpha and multiple frames elsewhere". Measured, the same holds for GIF: GIF89a has a transparent palette index and ffmpeg's encoder drops it anyway. So for two of three targets the declaration *is* an encoder claim — which is safe only because those profiles always run that encoder. `webp`'s `-c copy` cheap attempt is the case the rule must exclude, and a test pins it | 2026-08-28 |
| **Per rung, because the ladder has three and only two hold a stream list.** **Cheap attempt**: a new engine entry point called by `batch._verify_cheap_attempt` **after** its `if not predicted` gate, never entering `confirm_drops`. **Selective rung**: it is built from the stream list, so it carries the conditional note too -- today it emits only `_reencode_note`, so a transparency loss there is *silent*, a second defect this phase closes. **`last_resort`**: reached only after a failure, so `probed` is already true and no stream list is available; it keeps a static *format-limit statement* under the new third carve-out | Measured: `--to jpg` over any multi-frame source fails both the cheap attempt and the selective rung (`image2: Cannot write more than one file with the same name`, exit 127 for both) and lands on `last_resort`, whose notes are a static tuple. Specifying only the cheap-attempt hook would have left the unconditional note firing on exactly the case the spec calls the one a user notices first. Returning the note from `verify_success` instead would send every alpha source into the output probe, raising the process count | 2026-08-28 |
| `jpg`'s "the image was re-encoded" half stays unconditional | Its cheap attempt forces its encoder for every input | 2026-08-28 |
| **`docs/design/stream-decision.md` gains a third carve-out**: a *format-limit statement* is not a per-stream verdict and is not bound by the three-things rule | The notes this phase keeps — `jpg`'s re-encode half, GIF's palette line, every `last_resort` note, and `AVIF holds a single frame` under option 2 — name neither index nor codec and fall under neither existing carve-out. `spec-stream-disposition.md` records them as an open violation; closing #101 while leaving it unnamed would be the same omission in a new place | 2026-08-28 |
| **`avif`'s frame-reduction note stays a format fact**, reworded so it is true for every input ("AVIF holds a single frame"). No `-count_packets`, no packet-count field | Resolved at the gate on 2026-08-28. Free, and the same resolution #67 chose one issue earlier for GIF's palette note. The measured alternative cost 0.7 ms per MB on *every* probe in the system -- `probe_streams` is one function, so the failure-side and output-confirmation probes pay it too -- for a note only `avif` emits. **This leaves issue #101's acceptance criterion 3 unmet**, knowingly: that criterion is unhedged where its palette sibling is not, so #101 stays open on that point or is amended to record this decision | 2026-08-28 |

### The frame-note decision, in full (resolved at the gate)

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

**Resolved at the gate on 2026-08-28: option 2, the format fact.**

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

- Milestone: [within-stream-loss-notes](https://github.com/bhemsen/converter/milestone/8) (#8)
- Issues: created from this spec once it is merged (one per implementable step)

## Verification

Machine checks:

- [ ] Verify passes on the merge commit.
- [ ] A test that `probe_streams` fills `pix_fmt` from a stubbed **JSON** payload
      where the key is *absent* for an audio stream, and that the
      `-show_entries` argument is pinned verbatim.
- [ ] A test that the ffprobe **process count** per conversion is unchanged, for
      an alpha source into each of the three targets.
- [ ] A test per rung: the conditional note fires from the cheap attempt and from
      the selective rung, and `last_resort` keeps its format-limit statement. The
      selective-rung case is new behaviour -- today that rung emits no transparency
      note at all, so the loss is silent there.
- [ ] The `ALPHA_FREE_PIX_FMTS` roster is pinned as a literal and its regeneration
      command documented; the test must not invoke ffprobe, since the suite runs
      with no ffmpeg installed.
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
- [ ] A test that no probe argv contains `-count_packets`, and that `avif`'s
      frame note is identical for a single-frame and a multi-frame source -- the
      gate chose the format fact, so the two must not diverge.
- [ ] Each branch proven non-vacuous: inverting its condition must fail a test.

Human milestone-QA gate. `$FF` is the absolute ffmpeg path from *This machine*;
distinct stems throughout. Note that `opaque-gif-src.gif` lives in the input
tree, so a `--to gif` run also re-converts it to its own output -- expected, not a
collision:

```text
New-Item -ItemType Directory -Force in
& $FF -y -f lavfi -i "color=c=red@0.5:size=200x200:d=1,format=rgba" -frames:v 1 in/alpha-src.png
& $FF -y -f lavfi -i color=c=red:size=200x200:d=1 -frames:v 1 in/opaque-src.jpg
& $FF -y -i in/alpha-src.png -vf "split[a][b];[a]palettegen=reserve_transparent=1[p];[b][p]paletteuse" -frames:v 1 in/pal8-src.png
& $FF -y -i in/opaque-src.jpg -c:v gif in/opaque-gif-src.gif
& $FF -y -f lavfi -i testsrc=size=160x120:rate=10:duration=2 -c:v libx264 in/multi-src.mp4
& $FF -y -f lavfi -i testsrc=size=160x120:rate=10:duration=1 -frames:v 1 -c:v libx264 -pix_fmt yuv420p10le in/tenbit-still.mkv
& $FF -y -i in/alpha-src.png -i in/opaque-src.jpg -map 0:v -map 1:v -c:v png in/twovid-src.mkv
```

- [ ] `--to jpg in out` over `opaque-src.jpg`: **no** transparency note. This is
      the reported defect; check it first.
- [ ] `--to jpg in out` over `alpha-src.png`: the note fires, naming the stream
      index and `png`.
- [ ] `--to jpg`, `--to gif` and `--to avif` over `pal8-src.png` and
      `opaque-gif-src.gif`: the note fires in all six. These are the documented
      over-reports, not defects.
- [ ] `--to jpg in out` over `tenbit-still.mkv` (`yuv420p10le`, one frame):
      **no** transparency note. Single-frame on purpose -- a multi-frame source
      fails both the cheap attempt and the selective rung and lands on
      `last_resort`, so it would test the static tuple instead of this phase's
      logic. This is the case an incomplete `ALPHA_FREE_PIX_FMTS` regresses.
- [ ] `--to jpg in out` over `twovid-src.mkv`: reaches the **selective** rung (its
      second video stream trips `stream_limit=1`, so the cheap attempt fails but
      the rung succeeds), and the `rgba` first stream produces the transparency
      note. Today that rung emits none and the alpha is destroyed in silence --
      this is the second defect the phase closes, and the only QA line that proves
      it end to end.
- [ ] Each QA line above states the rung it exercises, and `multi-src.mp4` into
      `jpg` is checked explicitly as reaching `last_resort` with its format-limit
      statement intact.
- [ ] `--to gif` and `--to avif` over `alpha-src.png` and `opaque-src.jpg`: same
      pattern. `gif` is the one an output-side check would get wrong.
- [ ] `--to png in out` over `alpha-src.png`: no note, and `ffprobe` shows the
      alpha survived.
- [ ] `--to avif in out` over `multi-src.mp4` and over a single-frame source: the
      frame note reads the same in both, as a format fact.
- [ ] Confirm the probe cost is **unchanged** against a large (>1 GB) video: the
      gate declined `-count_packets`, so the table above is the cost avoided, not
      a cost to verify.
- [ ] A second run over any converted tree reports `0 converted`, exit 0.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| An implementer reaches for the output-side comparison, as `confirm_drops` does | The GIF false negative is a fact row, a decision row and a dedicated test |
| The note is hooked into `verify_success` and the process count rises | Measured today's count as 1 ffmpeg + 1 ffprobe, named the gate it must sit after, and pinned it with a test |
| The widened boundary licenses a note on a copy-based attempt | The boundary is stated as forced-encoder-only, with a test on `webp`'s copy attempt |
| A restatement of the boundary is missed | **Five** carriers are named in Scope and repeated in `docs/roadmap.md`'s foundation-impact line: architecture Key flow 1, the ladder diagram, the `jobs` module docstring, `jobs.py:249-251`, and `stream-decision.md`. The first draft named three and the second four; review round 2 caught the roadmap line still carrying three, which is the copy a future planner reads first. Same omission `#38`'s follow-up commit exists for |
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
- 2026-08-28: Review round 2 found the curation direction right but its precedent
  wrong: an omission from `LOSSY_CODECS` yields silence, an omission from an
  alpha-free set yields a false note on an ordinary file. The set is now derived
  by a stated component rule (184 members) and pinned by a test, and the inverted
  failure mode is written down rather than inherited by analogy.
- 2026-08-28: Review round 2 also caught the roadmap's foundation-impact line
  still naming three carriers of the boundary while Scope named five — falsifying
  this spec's own risks row inside the PR that asserts it. Both now say five.
- 2026-08-28: Review round 3 established the roster's authoritative source, which
  the first two drafts missed by measuring the wrong binary: `ffmpeg -pix_fmts`
  has no alpha flag, but `ffprobe -show_pixel_formats` reports `flags.alpha` per
  format. The set is generated from it and checked in; the component rule is
  demoted to the cross-check it always was — verified zero holes in either
  direction, but a proxy, and the two facts are independent.
- 2026-08-28: Review round 3 also drove the real engine and found the design
  specified for one rung out of three. `--to jpg` over any multi-frame source
  fails both the cheap attempt and the selective rung and lands on `last_resort`,
  whose notes are static — so the unconditional note would have survived on
  exactly the case this spec calls the one a user notices first. The note is now
  specified per rung, and the QA fixture changed to one that actually exercises
  the cheap attempt.
- 2026-08-28: Gate chose the format fact for `avif`'s frame note. The transparency
  half — the reported defect — is fixed regardless; what is declined is
  `-count_packets` on every probe in the system for one target's note. Issue #101's
  acceptance criterion 3 is knowingly left unmet, which is recorded here rather
  than quietly reworded, so #101 stays open on that point or is amended.
- 2026-09-14 (issue #104): Regenerated `ALPHA_FREE_PIX_FMTS` for real against
  the installed ffmpeg 9.0-full_build (`ffprobe -show_pixel_formats -of json`,
  filtered to `flags.alpha == 0 and flags.hwaccel == 0`) rather than trusting
  the spec's own table — it measured **184**, confirming the fact table's
  number exactly, with `pal8` absent and the component cross-check (every
  1-/3-component format except `pal8` reads `alpha=0`, every 2-/4-component
  format reads `alpha=1`) holding with zero exceptions. `Stream.pix_fmt`
  parses absence the same way `codec_name`/`codec_tag` already do --
  `str(raw.get("pix_fmt", ""))` -- so a non-video stream's missing key reads
  as `""`, never the CSV writer's `"N/A"`, with no new branch needed.
- 2026-09-14 (issue #105): Trap 1's hook placement, resolved as the issue's
  own fallback reading rather than its literal one. Read literally ("append
  after the `if not predicted: return ()` gate"), the note would never fire
  for the spec's own headline case -- an alpha PNG into `jpg`, where nothing
  is structurally dropped so `predicted` is empty and the function returns on
  the early path. The real constraint is the *process count*: the note must
  never become part of `predicted`, or it would route an alpha source with
  nothing else wrong into `_confirm_against_output` for a probe it does not
  need. Implemented as the issue's own suggested shape: `within =
  engine.transparency_notes(...)` computed once, unconditionally, then
  returned on *both* paths -- `return within` on the early return, the
  confirmed drops plus `within` on the other (see the 2026-09-14 review-round
  1 entry below for the final argument order). Pinned by
  `tests/test_batch.py::TestTransparencyNote`, including one test
  (`test_alpha_note_survives_the_confirm_against_output_path`) built
  specifically because every other test in that class takes the early-return
  path and so cannot prove the note survives the *other* branch -- caught by
  mutation-testing this hook before handing it to review, as instructed.
- 2026-09-14 (issue #105): Trap 2 established, not assumed. The hazard
  `_lossy_source_notes`'s docstring names is that folding a note into
  `_build_selective`'s own `notes` list can flip
  `if profile.explicit_streams and not notes: return None` for a profile that
  sets `explicit_streams` (`wav` is the case on record). None of `jpg`, `gif`
  or `avif` -- the only profiles this issue's field touches -- sets
  `explicit_streams` (all three are blind, `-map 0:v?`, per
  `docs/design/degradation-ladder.md`'s cheapest-first shape), so the hazard
  cannot manifest for this issue's own targets; pinned by
  `tests/test_profiles.py::TestAlphaUnsupportedField::
  test_none_of_the_three_also_declares_explicit_streams` so a future profile
  cannot combine the two flags unnoticed. The new `jobs.transparency_notes`
  is still kept entirely outside `_build_selective`, appended in `retries`
  exactly where `_lossy_source_notes` already is, rather than relying on
  today's roster to keep it safe: `_build_selective` already decided
  `None`-or-`Attempt` before either note-pass ever runs, so nothing appended
  afterward can resurrect a rung that pass skipped, for any profile, present
  or future -- safe by construction, not by the coincidence that no profile
  happens to combine the two flags today.
- 2026-09-14 (issue #105): `Profile.alpha_unsupported` is the new declared
  field (default `False`); `converter.jobs.transparency_notes` is the new
  engine entry point. The transparency note reads
  `"{kind} stream {index} ({codec}) may carry transparency, which {label}
  cannot hold"`, matching `_drop_note`/`_reencode_note`'s "name index, name
  codec" shape. `avif`'s frame note is reworded to `"AVIF holds a single
  frame"` in both its `cheap_attempt` and its `last_resort` tuple; its
  `description` field is untouched, as scoped. `jpg`'s cheap-attempt standing
  note narrows to `"the image was re-encoded"` and `gif`'s to `"GIF holds at
  most a 256-colour palette"` -- both profiles' `last_resort` tuples keep the
  old combined wording verbatim, since that rung never sees a stream list.
  `tests/test_argv.py::test_a_codec_outside_the_copy_mask_produces_no_note`
  and `::test_no_profile_invents_a_loss_for_a_source_it_fully_maps` are kept,
  not deleted -- the latter's parametrisation now also carries the seven
  image profiles, doubling as proof that `verify_success` itself grew no
  opinion about `pix_fmt`.
- 2026-09-14 (issue #105, review round 1): four defects found by a fresh
  reviewer given the diff and the three traps, all fixed before merge:
  - **A real behavioural bug**, not a documentation one: `jobs.transparency_notes`
    fired even for a stream the selective rung *copies* verbatim on a
    copy-mask hit (`-c:v copy`), which cannot have dropped anything --
    reachable for a real `gif`- or `av1`-coded stream that survives the
    selective rung by copy rather than by fallback encode. A stream copy is
    a *decided* case, not one of the undecidable ones this phase's
    over-reporting rule exists for (`pal8`, `.gif`'s source-side ambiguity),
    so excluding it is not a new over-report exemption, it is removing a
    false one -- the same class of defect commit `760b296` (issue #97) fixed
    for `_lossy_source_notes`'s cover-art case. Fixed by splitting the
    verdict into two entry points sharing one core (`jobs._alpha_notes`):
    `transparency_notes` for the cheap attempt (which forces its encoder
    unconditionally for every `alpha_unsupported` profile, so no copy branch
    exists to exclude) and `jobs._selective_transparency_notes` for the
    selective rung (which excludes a copy-mask hit, mirroring
    `_lossy_source_notes`'s own exclusion). `tests/test_argv.py`'s
    `test_gif_copyable_source_on_the_selective_rung`,
    `test_selective_rung_excludes_a_copied_stream_from_the_note` and
    `test_batch.py`'s `test_selective_rung_excludes_a_copied_stream_end_to_end`
    pin the fix; `test_the_cheap_attempt_entry_point_does_not_exclude_copies`
    pins that the two entry points stay deliberately asymmetric.
  - `jobs.transparency_notes`'s own docstring wrongly restated the literal
    (wrong) Trap-1 reading it was written to avoid -- "after its
    `if not predicted: return ()` gate" -- when the call actually sits
    *before* that gate, computed separately, and the gate itself no longer
    reads `return ()`. Reworded to match `batch.py`'s own accurate wording.
  - `Profile.alpha_unsupported`'s docstring carried a sentence with no
    predicate ("sound only under the same widened boundary a profile whose
    `cheap_attempt` forces..."). Reworded to state the rule plainly, and
    extended to mention the copy exclusion above.
  - The module comment above `JPG` in `profiles.py` (issue #67's "half two"
    finding) is updated, not left stale as first decided: it now says
    plainly that issue #105 closed the transparency third of "half two" for
    the two rungs that ever hold a stream list (naming index and codec,
    conditional on the source), while `last_resort` keeps the old combined
    wording verbatim on all three profiles (it never sees a stream list),
    and the colour-count and frame-count thirds remain exactly as #67 left
    them everywhere -- unconditional, index-less standing notes, recorded as
    an accepted deviation from `stream-decision.md`'s "every note names
    three things" rule rather than a carve-out that document grants yet
    (that amendment is #106's job). The comment sits directly above the
    three profiles this issue rewrites, in a file this issue already edits
    heavily; leaving it to state the opposite of what the code beneath it
    now does was a defect in this issue's own diff, not a restatement
    belonging to #106's five carriers (`README.md`, architecture, the ladder
    diagram, `stream-decision.md`, and the boundary comment above
    `_LOSSY_SOURCE_ADVISORY_TARGETS` -- all still untouched).
  - Two non-blocking findings addressed too: the transparency note's
    position in the returned tuple used to differ between the cheap-attempt
    hook (before any confirmed drop) and the selective rung (after); both now
    put a structural note first and the alpha note last. And `_alpha_notes`
    now skips a kept stream whose `codec_type` is not `"video"` -- unreachable
    for any profile shipped today (only `jpg`/`gif`/`avif` declare
    `alpha_unsupported`, and all three declare a video-only rule set), but
    correct by construction rather than by coincidence of today's roster,
    pinned by `test_a_non_video_stream_kept_under_a_hypothetical_rule_earns_no_note`.
- 2026-09-14 (issue #105, review round 2): the round-1 comment rewrite above
  `JPG` in `profiles.py` replaced four false claims with two new ones of the
  same class, plus left two neighbouring comments stale by the same PR's own
  change -- a fresh reviewer given the diff caught what the previous
  self-review pass missed. All comment-only, no code or test change needed;
  the behaviour, tests and process-count contract were independently
  confirmed correct by mutation-testing every changed branch in isolation.
  - The comment claimed "the transparency line no longer stands in the notes
    tuples below at all" -- false, it still stands in all three `last_resort`
    tuples (the rung that never sees a stream list, deliberately excluded
    from this issue's widening per the Outcome and the entries above).
    Reworded to say the clause is gone from the *cheap attempt's* `notes`
    tuple specifically, and that `last_resort` keeps it on purpose.
  - The comment attributed the colour-count/frame-count residual to "the
    format-limit statement carve-out `docs/design/stream-decision.md`
    names" -- that document names no such carve-out; the term lives only in
    this spec, and the file itself is #106's territory to amend, untouched
    by this issue. Reworded to record the residual as an accepted deviation
    from that document's existing "every note names three things" rule,
    with the amendment left to #106 rather than claimed early. The same
    misattribution in this log's own round-1 entry above is corrected too.
  - Two neighbouring comments -- above JPG's and GIF's `last_resort` --
    described the combined re-encode-plus-transparency wording there as
    simply "the cheap attempt's own standing note[s]" repeated. False as of
    this issue's own change: the cheap attempt's note narrowed to just the
    re-encode half, so `last_resort`'s wording is no longer identical to
    it, only descended from it. Both reworded to say so.
  - Non-blocking: the spec's own round-1 entry above quoted the shipped
    return statement as `(*within, *_confirm_against_output(...))`, the
    order before the note-ordering fix that same round also made -- fixed to
    point at this entry instead of repeating a since-reversed order.

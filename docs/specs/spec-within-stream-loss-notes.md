# Spec: within-stream-loss-notes (roadmap phase 8)

> Created: 2026-08-28

Make the image targets' loss notes fire only when the loss happened, and name
the stream it happened to — closing the half of issue #67 that its file boundary
could not reach. This spec carries no lifecycle state — acceptance is the spec
merged on the default branch with a milestone and issues, and all progress lives
in the GitHub issues and milestone. A completed spec is moved to
`docs/specs/archive/`.

**This phase is not on the seeded roadmap.** It comes from issue #101, which
#67's PR filed as an explicit unresolved finding rather than dropping it. Its
roadmap row is added in this PR alongside the usual spec and milestone links.

## The defect

`jpg`, `gif` and `avif` carry static notes on their cheap attempt:

```
jpg   transparency is not carried by JPEG; the image was re-encoded
gif   transparency is not carried by GIF / GIF holds at most a 256-colour palette
avif  transparency is not carried by AVIF / a multi-frame source is reduced to a single frame
```

They are true statements about the *format*, and they fire on every file. A plain
opaque JPEG is still told its transparency was not carried. And unlike a
per-stream degradation note they name neither a stream index nor a codec, so they
do not satisfy `docs/vision.md`'s third success criterion the way the rest of the
tool's notes do.

Retiring them is not the answer, and #67 correctly did not: these are losses
*inside* a stream that is kept, so `_structural_drop` sees nothing and there is no
per-stream note to fall back on. Removing them would be a silent loss.

## Outcome

- [ ] A source with no transparency converted to `jpg`, `gif` or `avif` emits
      **no** transparency note.
- [ ] A source that genuinely has transparency still gets one, naming the stream
      index and that stream's codec.
- [ ] Whatever this phase does about `avif`'s frame-reduction note leaves a
      statement that is true for every input, per the gate's decision.
- [ ] `GIF holds at most a 256-colour palette` is untouched — #67 already
      restated it as a format fact, which is the form the acceptance criterion
      allows.
- [ ] The number of ffprobe processes per file is unchanged.
- [ ] Every branch ships with a test asserting the note it emits, and each is
      proven non-vacuous.

## Scope

### In scope

- `converter/ffmpegtool.py`: a `pix_fmt` field on `Stream` and the matching
  entry in `probe_streams`' existing `-show_entries` query; plus, only if the
  gate takes option 1, `-count_packets` and a packet-count field.
- `converter/jobs.py`: the within-stream verdict — source carries the property,
  target declares it cannot hold it — and the note it emits.
- `converter/profiles.py`: the per-target declarations that replace the static
  notes on `jpg`, `gif` and `avif`.
- `docs/architecture.md` Key flow 1, `docs/design/degradation-ladder.md` and the
  `jobs` docstring: the success-side verification's boundary, which this phase
  widens from *structural* verdicts to structural **plus stream-property**
  verdicts.
- `docs/roadmap.md`: the phase-8 row, since this phase was not seeded.
- The tests for all of it.

### Out of scope

- **The colour-count condition.** Counting distinct colours needs a decode pass,
  which no probe budget covers. #67 already restated GIF's palette note as a
  format fact, which the issue's own acceptance criterion accepts ("or is stated
  in a form that stays true either way").
- Detecting whether transparency was *used* rather than merely present. A source
  whose alpha channel is entirely opaque still counts as carrying alpha; reading
  pixel values is a decode pass.
- Any note on a target that genuinely carries the property. `png`, `tiff`, `bmp`
  and `webp` keep alpha (measured) and gain nothing here.
- Any change to which conversions happen or what argv they build.
- Revisiting phase 7's decision to confine the lossy-source advisory to `flac`.
  That advisory rides a different verdict; see the open decision's note.

## Constraints

- `ffprobe` runs at most once per file on the source side, and the output-side
  confirmation probe stays conditional on there being a prediction
  (`docs/constitution.md` as narrowed by #18, and issue #66).
- Never parse ffmpeg's stderr.
- A target format is data, not code: what a target cannot hold is a profile
  declaration, never a branch in the engine.
- Never report success for a conversion that silently dropped something — and,
  its mirror, never announce a loss that did not happen. This phase exists
  because the second half is currently violated.
- The test suite keeps passing with no ffmpeg installed.

## Prior art

- [Image conversion through ffmpeg (Phase 5)](../prior-art.md#image-conversion-through-ffmpeg-phase-5)
  — the concern that produced these notes. Its AVOID (never promise EXIF/ICC
  preservation) is the same discipline applied here: state what is true of the
  file at hand, not what is true of the format in general.
- [Container/codec capability modelling (Phase 1)](../prior-art.md#containercodec-capability-modelling-phase-1)
  — the method: what a target can and cannot hold is curated data on the profile,
  not derived at runtime. The alpha declaration is the same kind of artifact as a
  copy mask.

## Design

No new design artifact. `docs/design/degradation-ladder.md` is amended rather
than added to — the success-side verification's boundary is stated there, and
this phase moves it.

## Human prerequisites

- none.

## Prior decisions

### The measured facts these decisions rest on

Measured against ffmpeg 9.0 during planning; the review is asked to falsify.

| Fact | Consequence |
|---|---|
| **`pix_fmt` is free.** Adding it to the existing `-show_entries` query costs no extra process and returns reliably: `rgba` for an alpha PNG, `yuvj420p` for an opaque JPEG, `gbrp` for AV1, `N/A` for an audio stream | The transparency condition costs nothing beyond a field |
| **`nb_frames` is not usable.** Measured `N/A` for `.mkv` and `.png`, `20` for `.mp4` and `.gif` — container-dependent | A frame count cannot come from the metadata query |
| **`-count_packets` is reliable and modest.** Correct on every container tested (20/20/20/1), and it stays *one* process because it goes in the same call. Measured: 4-minute MP3 142 -> 164 ms; 158 MB video 147 -> 293 ms; a small PNG is lost in process-startup noise | If the gate wants the frame condition, this is what it costs — dominated by startup for the common case, ~150 ms on a large video |
| **`-count_frames` is 3x the plain probe** (712 ms vs 227 ms on a small file), because it decodes | Never an option |
| **Comparing the output's `pix_fmt` does not work for `gif`.** An alpha PNG into GIF yields an output reporting `pix_fmt=bgra` — a format *with* alpha — while the actual channel is all-opaque (source alpha 127, output 255). `jpg` (`yuvj444p`) and `avif` (`gbrp`) do report the loss honestly | The verdict must be **source-measured ∧ target-declared**, not an output comparison. That is also why it needs no output probe |
| `png`, `tiff` and `bmp` keep alpha (`rgba`, `rgba`, `bgra` with the value preserved); `webp` keeps it as `yuva420p` | Only `jpg`, `gif` and `avif` need the declaration |

### Decisions

| Decision | Rationale | Date |
|---|---|---|
| The verdict is **source-measured ∧ target-declared**: the source stream carries the property, and the profile declares the target cannot hold it | Measured: an output-side comparison gives a false negative for `gif`, whose output reports an alpha-capable `pix_fmt` while the channel is opaque. Source-plus-declaration is correct for all three, and needs no output probe at all | 2026-08-28 |
| `Stream` gains `pix_fmt`; whether a stream carries alpha is derived from it in the engine, not stored as a second field | One probed fact, one field. The alpha question is a property of the pixel format, and deriving it keeps the value type a record of what ffprobe said rather than of what the engine concluded | 2026-08-28 |
| What a target cannot hold is declared on the **profile**, not inferred | `docs/constitution.md`: a target format is data, not code. It is the same kind of artifact as a copy mask (`docs/prior-art.md`), and it is what makes `gif`'s case expressible at all | 2026-08-28 |
| The note names the stream index and that stream's codec, in the shape `docs/design/stream-decision.md` already requires of a degradation note | These *are* degradation notes — this conversion did lose the alpha — unlike phase 7's advisory, which reports the source's history. No carve-out is needed | 2026-08-28 |
| **The success-side verification widens** from structural verdicts to structural **plus stream-property** verdicts, amended in this PR in all three places that state the boundary | The widening is forced: a conditional note needs the stream list, and the only place a successful cheap attempt has one is the verification. The boundary #18 drew excluded *codec-level* claims because "announcing a re-encode it never performed would swap one dishonest report for another" — this asserts nothing about the encode. It states a measured source property and a declared target limitation, both of which are true independently of what ffmpeg did | 2026-08-28 |
| `jpg`'s "the image was re-encoded" half stays unconditional | `jpg`'s cheap attempt forces its encoder (phase 5), so it is true for every input. Only the transparency half is conditional | 2026-08-28 |
| GIF's palette note is untouched | #67 already restated it from an action claim to a format fact, which is the form the issue's acceptance criterion accepts. Making it conditional needs a colour count, which needs a decode | 2026-08-28 |
| OPEN — whether `avif`'s frame-reduction note becomes conditional, at the cost of `-count_packets` on every probe | resolved at the spec-acceptance gate; see the note below | — |

### The one open decision, in full

Transparency is free: `pix_fmt` rides the existing query. The frame-reduction
note is not — it needs a packet count, and the only reliable way to get one is
`-count_packets` on the same call, which roughly doubles the probe's own cost.

Measured, on this machine:

| Source | plain probe | with `-count_packets` |
|---|---|---|
| small PNG | ~130 ms | ~130 ms (lost in startup noise) |
| 4-minute MP3 | 142 ms | 164 ms |
| 158 MB H.264 video | 147 ms | 293 ms |

The cost lands on **every** conversion, because all 17 profiles declare
`partial_mapping=True` and are therefore probed on success — not only on the
`avif` conversions that would use the result.

1. **Take the cost; make the frame note conditional.** A single-frame source into
   `avif` says nothing; a multi-frame one names the stream and says it was reduced
   to one frame. Fully closes the issue. The price is a probe that costs roughly
   twice as much on large video sources, for a note only `avif` emits.
2. **Leave the frame note as a format fact**, the way #67 left GIF's palette note:
   reworded if necessary so it stays true for a single-frame source — "AVIF holds
   a single frame" rather than "a multi-frame source is reduced". Free, consistent
   with the precedent #67 set one issue earlier, and it leaves `avif` the one
   target whose note is unconditional while `jpg` and `gif` are not.

Note for either choice: this phase's widening of the success-side verification
would also give phase 7's lossy-source advisory somewhere to live for `wav`,
`png`, `tiff` and `bmp` — the four targets that gate declined to cover because
the boundary was closed. Reopening that is deliberately **out of scope** here, but
it is worth knowing the obstacle is being removed.

## Tracking

- Milestone: within-stream-loss-notes (created at the spec-acceptance gate)
- Issues: created from this spec once it is merged (one per implementable step)

## Verification

Machine checks:

- [ ] Verify passes (ruff check, ruff format --check, pytest) on the merge commit.
- [ ] A test that `probe_streams` fills `pix_fmt` from a stubbed payload, and that
      the `-show_entries` argument is pinned verbatim.
- [ ] A test that the ffprobe **process count** per conversion is unchanged.
- [ ] Per target, a test that an alpha-carrying source emits the transparency note
      naming the stream index and codec, and that an opaque source emits none.
      This is the QA finding, pinned.
- [ ] A test that `png`, `tiff`, `bmp` and `webp` emit no transparency note for an
      alpha source, since they carry it.
- [ ] A test that `gif`'s verdict does **not** depend on the output's `pix_fmt` —
      the false-negative case, which an output-comparison implementation would
      fail and this one must not.
- [ ] A test that the success-side verification still refuses codec-level claims,
      with the widened boundary permitting only stream-property verdicts.
- [ ] Under option 1 only: a test that a single-frame source into `avif` emits no
      frame note and a multi-frame one does, naming the stream.
- [ ] Each note branch proven non-vacuous by mutation: inverting the condition
      must fail a test.

Human milestone-QA gate. `$FF` is the absolute ffmpeg path from *This machine*;
every fixture has a distinct stem:

```text
New-Item -ItemType Directory -Force in
& $FF -y -f lavfi -i "color=c=red@0.5:size=200x200:d=1,format=rgba" -frames:v 1 in/alpha-src.png
& $FF -y -f lavfi -i color=c=red:size=200x200:d=1 -frames:v 1 in/opaque-src.jpg
& $FF -y -f lavfi -i testsrc=size=160x120:rate=10:duration=2 -c:v libx264 in/multi-src.mp4
```

- [ ] `--to jpg in out` over `opaque-src.jpg`: **no** transparency note. This is
      the reported defect; check it first.
- [ ] `--to jpg in out` over `alpha-src.png`: the note fires and names the stream
      index and `png`.
- [ ] `--to gif` and `--to avif` over both fixtures: same pattern. `gif` is the
      one whose output would fool an output-side check, so confirm the note is
      right rather than accidentally right.
- [ ] `--to png in out` over `alpha-src.png`: no transparency note, and `ffprobe`
      shows the alpha survived.
- [ ] `--to avif in out` over `multi-src.mp4` behaves as the gate decided.
- [ ] Time a conversion of a large video before and after, and record the probe
      cost actually observed against the table above.
- [ ] A second run over any converted tree reports `0 converted`, exit 0.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| An implementer reaches for the output-side comparison, as `confirm_drops` does | The `gif` false negative is a fact-table row, a decision row and a dedicated test |
| The widened boundary becomes a licence for any success-side claim | The amendment states the new boundary as *stream-property* verdicts, and a test pins that codec-level claims are still refused |
| The probe grows a third process | The process-count test, and the fact that `-count_packets` rides the existing call |
| `-count_packets` costs more than the table suggests on real media | The QA gate measures it on a real large file rather than trusting the fixtures |
| A note fires for a source whose alpha is entirely opaque | Named out of scope with its reason: distinguishing that needs a decode pass. The note stays true — the source did carry an alpha channel |

## Decision log

- 2026-08-28: The issue's headline worry — that conditioning these notes needs a
  wider probe budget — is only half true. `pix_fmt` rides the existing query for
  nothing; only the frame count costs anything, and even that stays one process.
  That split is what turned the phase's open question from "can we afford this at
  all" into "is `avif`'s one note worth `-count_packets`".
- 2026-08-28: The obvious implementation — compare the output's `pix_fmt`, as
  `confirm_drops` compares output streams — was measured and rejected: GIF's
  output reports an alpha-capable `bgra` while the channel is opaque, so it would
  report alpha as preserved exactly where it was lost. Source-measured ∧
  target-declared is correct for all three and needs no output probe.
- 2026-08-28: This phase widens the success-side boundary #18 drew and #66 kept.
  The widening is argued rather than assumed: the verdict asserts nothing about
  what the encoder did, only what the source carried and what the target declares
  it cannot hold.

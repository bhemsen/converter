# Spec: lossy-source-notes (roadmap phase 7)

> Created: 2026-08-27

Say so when a conversion writes an already-lossy source into a lossless target —
the "your 40 MB FLAC came from a 128 kbit/s MP3" advisory. This spec carries no
lifecycle state — acceptance is the spec merged on the default branch with a
milestone and issues, and all progress lives in the GitHub issues and milestone.
A completed spec is moved to `docs/specs/archive/`.

**Depends on milestone #3 (audio-formats), which is complete.** Independent of
milestone #6.

## The one thing this phase is about

Every note the tool prints today answers "what did *this conversion* give up?".
This one answers a different question: "what had the source already given up
before it got here?". The tool takes nothing away — it faithfully stores what it
was handed — and that is exactly why the file is misleading without a word. A
lossless container implies a lossless history, and here there is none.

That difference is not cosmetic. It decides where the note may live, what the
constitution has to say about it, and which of the five lossless targets can
carry it at all.

## Outcome

- [ ] Converting a lossy source into a lossless target says so, naming the source
      codec — for every target the gate's decision covers.
- [ ] The advisory is distinguishable from a degradation note: it reports the
      source's history, not this run's sacrifice, and the constitution says which
      is which.
- [ ] A lossless source into a lossless target says nothing. A lossy source into
      a *lossy* target says nothing either — this phase adds one advisory, not a
      commentary track.
- [ ] The lossy-codec set is curated data with its rationale recorded, not
      derived from ffmpeg.
- [ ] `ffprobe` still runs at most once per file, and no conversion gains a probe
      it did not already make.

## Scope

### In scope

- `converter/profiles.py`: a module-level `LOSSY_CODECS` frozenset, beside the
  copy masks that already live there, and whatever per-rule flag marks a target
  as lossless for this purpose.
- `converter/jobs.py`: emitting the advisory where the gate's decision puts it.
- `docs/constitution.md`: the line distinguishing a degradation note from an
  advisory, which its current notes convention and test gate do not cover.
- The tests, including one asserting the advisory does **not** fire for a
  lossless source or a lossy target.

### Out of scope

- **Lossy-to-lossy generation loss.** Re-encoding an MP3 to an M4A also loses
  something, and every such conversion already carries a re-encode note naming
  both codecs. A second advisory there would be noise on the commonest
  conversion the tool performs.
- Estimating *how much* was lost, or reading a bitrate. The advisory is
  qualitative: the source was lossy. Anything quantitative needs fields
  `probe_streams` does not request.
- Detecting a lossy source that was *already* laundered through a lossless
  container — an MP3 decoded to FLAC by someone else, handed to us as FLAC. That
  is undetectable from a codec name and is a different discipline (spectral
  analysis), squarely outside `docs/vision.md`'s "corruption detection" non-goal.
- Any change to which conversions happen or what argv they build. This phase adds
  a sentence, never a stream decision.

## Constraints

- `ffprobe` runs at most once per file (`docs/constitution.md`, as narrowed by
  issue #18).
- Never parse ffmpeg's stderr. The source codec comes from the probe or not at
  all.
- A target format is data, not code.
- Value types are frozen dataclasses.
- The test suite keeps passing with no ffmpeg installed.

## Prior art

- [Generation-loss advisories (Phase 7)](../prior-art.md#generation-loss-advisories-phase-7)
  — the concern seeded for this phase, whose recorded weakness this cycle closes.
  The seed noted that research mode `none` had been chosen and that nobody had
  checked whether any comparable converter warns at all. Checked now: the
  *principle* is stated everywhere — converting an MP3 to FLAC restores nothing,
  it just stores what is left in a new wrapper — but no converter surfaced that
  warns about it, and no maintained lossy-codec list surfaced to adopt instead of
  curating one. So the differentiation is real and the curation is unavoidable;
  both halves of the seed's uncertainty resolve in favour of building it.
- [Container/codec capability modelling (Phase 1)](../prior-art.md#containercodec-capability-modelling-phase-1)
  — the method: a curated set, hand-maintained, because `ffmpeg -codecs` reports
  what a build contains and never a judgement about it. `LOSSY_CODECS` is the
  same kind of artifact as a copy mask and lives in the same module for the same
  reason.

## Design

No new design artifact. Whether `docs/design/degradation-ladder.md` needs an
amendment depends on the gate's decision — under option 2 it does, since that
file records what the success-side verification may and may not assert.

## Human prerequisites

- none.

## Prior decisions

### The measured facts these decisions rest on

Read off the merged registry and engine, not assumed.

| Fact | Consequence |
|---|---|
| **Five targets are lossless** for this purpose — the rules that declare `fallback_name=None` on their content stream: `flac` (audio), `wav` (audio), `png`, `tiff`, `bmp` (video). The other `None` entries belong to subtitle and attachment rules | The advisory's scope is those five, and the existing "encoding into this gives up nothing" flag already identifies them |
| **Only `flac` reaches a lossy source on the failure side.** Its cheap attempt is `-map 0:a? -c:a copy`, so an MP3 source fails it and lands on the selective rung — measured, `-map 0:0 -c:a flac` with **no notes at all** today | The motivating case is a failure-side rung, where the engine holds the stream list and the source codec, and where a note costs nothing structurally |
| **`wav`, `png`, `tiff` and `bmp` always encode in their cheap attempt** (`-map 0:a:0 -c:a pcm_s16le`, `-map 0:v? -c:v png`, …), so a lossy source *succeeds* at rung 1 | For those four the advisory would have to come from the success-side verification — which issue #18's fix deliberately confined to structural verdicts |
| `jobs._unmapped_notes` states its own boundary: "Codec-level ones are deliberately left out: the cheap attempt has already exited 0, so whatever it did with a stream's codec worked, and announcing a re-encode it never performed would just swap one dishonest report for another" | The boundary's *reason* does not apply here — this advisory announces no re-encode — but the mechanism does. Extending it is a foundation-doc change, not a code detail |
| The copy masks already live as module-level frozensets in `converter/profiles.py` (`MP4_VIDEO_CODECS`, `TEXT_SUBTITLE_CODECS`, …) | A `LOSSY_CODECS` constant beside them needs **no** architecture change. `docs/roadmap.md`'s seeded verdict for this phase — "architecture — yes: a lossy-codec set is cross-cutting data" — is wrong and is corrected here |

### Decisions

| Decision | Rationale | Date |
|---|---|---|
| `LOSSY_CODECS` is a module-level frozenset in `converter/profiles.py`, beside the copy masks | Same kind of artifact, same module, same curation argument (`docs/prior-art.md`). The seeded architecture verdict assumed it needed a new home; the masks show it does not | 2026-08-27 |
| The set is curated by hand and its membership argued in a comment, not derived | `ffmpeg -codecs` reports what a build contains, never a judgement. The awkward cases are the point: `alac`, `flac`, `wmalossless` and `truehd` are lossless despite living beside lossy siblings, and `pcm_*` is lossless by construction | 2026-08-27 |
| A target counts as lossless for the advisory exactly where its content rule declares `fallback_name=None` | That flag already means "encoding into this gives up nothing", which is the same judgement. Introducing a second, parallel marker would let the two disagree | 2026-08-27 |
| **No advisory for a lossy target.** A lossy-to-lossy conversion already carries the engine's re-encode note naming both codecs | One advisory, not a commentary track. The re-encode note is the honest report there, and a second line would fire on the commonest conversion the tool performs | 2026-08-27 |
| The advisory names the source codec and says plainly that the target cannot restore what the source had already discarded | `docs/vision.md` requires a note to name the stream and its codec. The wording is pinned by test, as every note in this project is | 2026-08-27 |
| `docs/constitution.md` gains one line distinguishing a **degradation note** (what this conversion gave up) from an **advisory** (what the source had already given up), authored in this PR | The current notes convention and its test gate — "a new degradation branch ships with a test asserting the note it emits" — assume the former. Without the distinction, the advisory reads as a claim the tool destroyed something | 2026-08-27 |
| OPEN — which of the five lossless targets carry the advisory | resolved at the spec-acceptance gate; see the note below | — |

### The one open decision, in full

The advisory needs the source codec, which the engine holds only where it has a
stream list. That splits the five lossless targets in two:

- **`flac` is free.** Its cheap attempt copies, so a lossy source fails it and
  lands on the selective rung, which already has the stream list and today emits
  no note at all. The motivating case — an MP3 library converted to FLAC — is
  exactly this one.
- **`wav`, `png`, `tiff` and `bmp` are not.** Their cheap attempt always encodes
  and succeeds, so the only place to say anything is the success-side
  verification, which issue #18's fix deliberately restricted to *structural*
  verdicts.

The restriction's stated reason does not apply to this advisory: #18 excluded
codec-level statements because "announcing a re-encode it never performed would
swap one dishonest report for another", and this advisory announces no re-encode.
But the restriction is written down in `docs/constitution.md`,
`docs/design/degradation-ladder.md` and the code's own docstring, so widening it
is a deliberate amendment, not a reading.

1. **`flac` only — the failure-side rung.** Covers the motivating case, needs no
   amendment beyond the degradation-versus-advisory line, and leaves `--to wav`
   over an MP3 silent. Smallest change, and inconsistent in a way a user could
   notice: the same source says something on the way to FLAC and nothing on the
   way to WAV.
2. **All five — widen the success-side verification to permit this one
   codec-level statement.** Consistent, and costs an amendment to
   `degradation-ladder.md` plus the constitution, with the new boundary written
   precisely enough that it does not become a licence for any codec claim on the
   success path. Also adds an advisory to `--to png` from a JPEG, which is
   correct and may be more noise than anyone wants on an image batch.

## Tracking

- Milestone: lossy-source-notes (created at the spec-acceptance gate)
- Issues: created from this spec once it is merged (one per implementable step)

## Verification

Machine checks:

- [ ] Verify passes (ruff check, ruff format --check, pytest) on the merge commit.
- [ ] A test per covered target that a lossy source produces the advisory, with
      its exact wording pinned.
- [ ] A test that a **lossless** source into the same target produces no
      advisory — `flac` from `flac`, `wav` from `wav`.
- [ ] A test that a lossy source into a **lossy** target produces the ordinary
      re-encode note and no advisory.
- [ ] A test that `LOSSY_CODECS` excludes `alac`, `flac`, `wmalossless`,
      `truehd` and the `pcm_*` family — the members a careless list gets wrong.
- [ ] A test that the probe count per file is unchanged.
- [ ] Under option 2 only: a test that the success-side verification still refuses
      every codec-level statement other than this one.

Human milestone-QA gate. `$FF` is the absolute ffmpeg path from *This machine*;
every fixture has a distinct stem:

```text
New-Item -ItemType Directory -Force in
& $FF -y -f lavfi -i sine=duration=2 -c:a libmp3lame -b:a 128k in/lossy-mp3.mp3
& $FF -y -f lavfi -i sine=duration=2 -c:a libopus in/lossy-opus.opus
& $FF -y -f lavfi -i sine=duration=2 -c:a flac in/lossless-flac.flac
& $FF -y -f lavfi -i sine=duration=2 -c:a pcm_s16le in/lossless-wav.wav
& $FF -y -f lavfi -i color=c=red:size=200x200:d=1 -frames:v 1 in/lossy-jpg.jpg
```

- [ ] `--to flac in out` over `lossy-mp3.mp3` prints the advisory naming `mp3`,
      and the output is a playable FLAC. This is the case the phase exists for.
- [ ] The same run over `lossless-flac.flac` prints **no** advisory.
- [ ] `--to wav in out` over `lossy-mp3.mp3` behaves as the gate decided —
      advisory under option 2, silence under option 1.
- [ ] `--to mp3 in out` over `lossy-opus.opus` prints the ordinary re-encode note
      and no advisory: lossy-to-lossy is out of scope by decision.
- [ ] Under option 2: `--to png in out` over `lossy-jpg.jpg` prints the advisory.
      Judge the noise on a real photo folder before accepting.
- [ ] A second run over any converted tree reports `0 converted`, exit 0.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| The advisory reads as "the tool destroyed something" | The constitution gains the degradation-versus-advisory distinction, and the wording is pinned by test |
| Widening the success-side verification becomes a licence for any codec claim | Option 2's amendment has to state the new boundary precisely; the Verification bullet pins that nothing else gets through |
| The lossy set misclassifies a codec | The awkward members are named in a test rather than left to the author's memory |
| The advisory fires on every file of an image batch | Named as option 2's cost, with a QA item asking the human to judge it on real photos before accepting |
| Someone extends this to detect laundered sources | Named out of scope, with the reason: it needs spectral analysis, which `docs/vision.md` already rules out |

## Decision log

- 2026-08-27: The prior-art entry's recorded weakness is closed. The seed noted
  that research mode `none` left it unchecked whether any comparable converter
  warns at all; checked now, the principle is stated everywhere and no tool
  surfaced that acts on it, and no maintained lossy-codec list exists to adopt.
  Both halves resolve in favour of building it and curating the set.
- 2026-08-27: `docs/roadmap.md`'s seeded verdict "architecture — yes: a
  lossy-codec set is cross-cutting data" is wrong and is corrected here. The copy
  masks already live as module-level frozensets in `converter/profiles.py`, so
  the set has a home and the architecture is untouched.
- 2026-08-27: The collision suspected at seeding is real but narrower than it
  looked. It is not "the success path forbids codec statements" in general — the
  motivating case is a *failure*-side rung and entirely free. It is the four
  targets whose cheap attempt always encodes, and that is the gate's decision.

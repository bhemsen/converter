# Spec: lossy-source-notes (roadmap phase 7)

> Created: 2026-08-27

Say so when a conversion writes an already-lossy source into a lossless target —
the "your 40 MB FLAC came from a 128 kbit/s MP3" advisory. This spec carries no
lifecycle state — acceptance is the spec merged on the default branch with a
milestone and issues, and all progress lives in the GitHub issues and milestone.
A completed spec is moved to `docs/specs/archive/`.

**Depends on milestone #3 (audio-formats), which is complete.** Independent of
milestone #6 *in outcome*, but not in text: phase 6 rewrites `flac`'s cheap attempt
to `flags("-map 0:a? -map 0:disp:attached_pic? -c copy")` and adds three
`attached_pic` rules with no fallback. The conclusion survives -- an MP3 still
fails a `-c copy` into the flac muxer and still lands on the selective rung -- but
the lossless criterion below must not match those three rules, which is why it
tests the pair rather than the bare flag.

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

- [ ] Converting a lossy source into a lossless target says so, naming the stream
      index and the source codec -- for every target the gate's decision covers.
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
  copy masks, and the lossless criterion the Decisions table pins
  (`fallback_options is not None and fallback_name is None`) -- not a new flag.
- `converter/jobs.py`: emitting the advisory where the gate's decision puts it --
  **appended after a rung is built, or onto the success-side notes, never inside
  the plan**. `_build_selective` short-circuits on `if profile.explicit_streams
  and not notes`, so an advisory added inside the plan would resurrect a rung that
  is skipped today for `wav`, the one `explicit_streams=True` profile. This phase
  adds a sentence, never a stream decision.
- `docs/constitution.md`: the line distinguishing a degradation note from an
  advisory, which its current notes convention and test gate do not cover. This
  amendment is needed under **both** options.
- `docs/design/stream-decision.md`: the carve-out sentence saying an advisory is
  not bound by the three-things rule the way a degradation note is -- the
  precedent for such a carve-out is already in that file, for the unverified-run
  note.
(The gate chose `flac` only, so `docs/architecture.md` Key flow 1,
`docs/design/degradation-ladder.md` and the engine docstring are **not** touched:
the codec-level restriction they carry stays exactly as it is.)
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
- **The bit-depth truncation `--to wav` already performs.** Measured, a 24-bit
  FLAC becomes 16-bit PCM with no note. That is a genuine unreported loss, but it
  is a *degradation* this conversion performs rather than the source's history,
  so it belongs to a different note and a different phase.

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
  warns about it. That much one search supports, and the differentiation is real.
  The second half is narrower than the seed hoped: ffmpeg **does** classify codecs
  as lossy or lossless (`-codecs`, columns `L` and `S`), so a list does exist --
  it is simply not usable here, for the three reasons the decision row gives.
- [Container/codec capability modelling (Phase 1)](../prior-art.md#containercodec-capability-modelling-phase-1)
  -- the method: a curated set, hand-maintained. Note the phase-1 argument does
  **not** transfer unchanged: its claim is that `-codecs` lists what a build
  contains, "never which codec is LEGAL in which muxer" -- a statement about
  muxers, which is a different question from lossiness. `LOSSY_CODECS` is the same
  *kind* of artifact as a copy mask and lives in the same module, but it is
  curated for its own reasons, given in the decision row.

## Design

No new design artifact, and no amendment to `docs/design/degradation-ladder.md`:
the gate confined the advisory to the failure-side rung, so what that file records
about the success-side verification stays true unchanged. `docs/design/stream-decision.md`
gains only the carve-out sentence for the advisory's note shape.

## Human prerequisites

- none.

## Prior decisions

### The measured facts these decisions rest on

Read off the merged registry and engine, not assumed.

| Fact | Consequence |
|---|---|
| **Nine rules declare `fallback_name=None`, but only five also declare a fallback**: `flac`(audio), `wav`(audio), `png`, `tiff`, `bmp`(video). The other four -- `mp4`/`mov`/`webm` subtitle, `mkv` attachment -- have no fallback at all, so their `None` means "drop", not "re-encode without a note" | The criterion has to be the pair, not the bare flag. Phase 6 adds three more bare-`None` rules (`attached_pic` on `mp3`, `m4a`, `flac`), which the bare test would misread as lossless targets |
| **`--to wav` from a 24-bit FLAC writes 16-bit PCM and says nothing.** Measured: source `sample_fmt=s32`, `bits_per_raw_sample=24`; output `pcm_s16le`, 16 bits; the run reports `converted` with no note | So `fallback_name=None` does **not** mean "gives up nothing" -- it means the profile declared the encode not worth naming. This phase reuses that declaration; the bit-depth truncation is a separate gap, named rather than inherited |
| **Only `flac` reaches a lossy source on the failure side.** Its cheap attempt is `-map 0:a? -c:a copy`, so an MP3 source fails it and lands on the selective rung — measured, `-map 0:0 -c:a flac` with **no notes at all** today | The motivating case is a failure-side rung, where the engine holds the stream list and the source codec, and where a note costs nothing structurally |
| **`wav`, `png`, `tiff` and `bmp` always encode in their cheap attempt** (`-map 0:a:0 -c:a pcm_s16le`, `-map 0:v? -c:v png`, …), so a lossy source *succeeds* at rung 1 | For those four the advisory would have to come from the success-side verification — which issue #18's fix deliberately confined to structural verdicts |
| `jobs._unmapped_notes` states its own boundary: "Codec-level ones are deliberately left out: the cheap attempt has already exited 0, so whatever it did with a stream's codec worked, and announcing a re-encode it never performed would just swap one dishonest report for another" | The boundary's *reason* does not apply here — this advisory announces no re-encode — but the mechanism does. Extending it is a foundation-doc change, not a code detail |
| **Genuinely cross-cutting codec data already lives in `converter/profiles.py` as a module-level frozenset**: `TEXT_SUBTITLE_CODECS` is shared by `mp4`, `mov` and `webm`. (Most masks are inlined per profile; only the four container profiles use module-level constants) | A `LOSSY_CODECS` constant beside it needs **no** architecture change. That shared-across-profiles precedent, not the mere existence of module constants, is what answers the seeded verdict "architecture — yes: a lossy-codec set is cross-cutting data" -- corrected here |

### Decisions

| Decision | Rationale | Date |
|---|---|---|
| `LOSSY_CODECS` is a module-level frozenset in `converter/profiles.py`, beside the copy masks | Same kind of artifact, same module, same curation argument (`docs/prior-art.md`). The seeded architecture verdict assumed it needed a new home; the masks show it does not | 2026-08-27 |
| The set is curated by hand, **although ffmpeg does ship a lossy/lossless flag** (`-codecs`, columns `L` and `S`) | The first draft claimed no such flag exists. It does, and it classifies every "awkward case" correctly -- `alac`, `flac`, `wmalossless`, `truehd`, `pcm_s16le` all report `S`. Three reasons it still cannot be the source of truth here: `webp` reports **both** (`DEVILS`), so the descriptor cannot answer "was *this instance* lossy"; consulting it costs a subprocess this project does not otherwise spend; and it answers a different question than the tool asks -- `gif` reports `S`, lossless, while this project measured in phase 5 that a photograph through `-c:v gif` keeps 182 of 36 485 colours. A set curated against what the tool actually promises is the honest artifact | 2026-08-27 |
| A target counts as lossless for the advisory exactly where a rule declares **`fallback_options is not None and fallback_name is None`** -- it re-encodes, and the profile declared that re-encode not worth naming | The bare `fallback_name is None` test is overloaded: it also matches a rule with no fallback at all, which is a *drop*, and matches nine rules rather than five. Worse, phase 6 gives `mp3`, `m4a` and `flac` an `attached_pic` rule that copies with no fallback declared, so the bare test would start classifying `mp3` and `m4a` as lossless targets the moment #6 merges. The refined test selects exactly `flac`, `wav`, `png`, `tiff`, `bmp` | 2026-08-27 |
| The rationale for reusing that flag is that it is the **profile's own declaration** that the encode needs no note -- not that the encode gives up nothing | Measured, the stronger claim is false for one of the five: `--to wav` from a 24-bit FLAC writes `pcm_s16le` at 16 bits and says nothing. So the flag records a judgement the profile made, and this phase reuses that judgement rather than adding a second marker that could disagree with it. The bit-depth truncation is a real, separate gap -- named in Out of scope, not silently inherited | 2026-08-27 |
| **No advisory for a lossy target.** A lossy-to-lossy conversion already carries the engine's re-encode note naming both codecs | One advisory, not a commentary track. The re-encode note is the honest report there, and a second line would fire on the commonest conversion the tool performs | 2026-08-27 |
| The advisory names the stream index and the source codec, and says plainly that the target cannot restore what the source had already discarded | `docs/vision.md` requires a note to name the stream and its codec. The wording is pinned by test, as every note in this project is | 2026-08-27 |
| `docs/constitution.md` gains one line distinguishing a **degradation note** (what this conversion gave up) from an **advisory** (what the source had already given up), authored in this PR | The current notes convention and its test gate — "a new degradation branch ships with a test asserting the note it emits" — assume the former. Without the distinction, the advisory reads as a claim the tool destroyed something | 2026-08-27 |
| **Only `flac` carries the advisory**, on the failure-side selective rung. `wav`, `png`, `tiff` and `bmp` stay silent | Resolved at the gate on 2026-08-27. It covers the motivating case -- an MP3 library into FLAC -- and costs nothing: that rung already holds the stream list and emits no note today. Widening it would have required a codec-level statement on the success side that issue #18 deliberately excluded, at three foundation restatements plus a test narrowing, and would have added an advisory to every JPEG in an image batch. The inconsistency it leaves -- the same source says something on the way to FLAC and nothing on the way to WAV -- is accepted and recorded rather than hidden | 2026-08-27 |

### The scope decision, in full (resolved at the gate)

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
But the restriction is written down in `docs/architecture.md` Key flow 1,
`docs/design/degradation-ladder.md` and the `jobs._unmapped_notes` docstring --
**not** in `docs/constitution.md`, which carries only the narrowed ffprobe rule and
the notes test gate. Widening it is a deliberate amendment of those three, not a
reading. Getting that list right matters here: issue #38's own follow-up commit
existed because a restatement was missed and a grep disproved the claim that all
of them had moved.

**Resolved at the gate on 2026-08-27: option 1, `flac` only.**

1. **`flac` only -- the failure-side rung.** Covers the motivating case, needs no
   amendment beyond the degradation-versus-advisory line, and leaves `--to wav`
   over an MP3 silent. Smallest change, and inconsistent in a way a user could
   notice: the same source says something on the way to FLAC and nothing on the
   way to WAV.
2. **All five -- widen the success-side verification to permit this one
   codec-level statement.** Consistent, and costs amendments to
   `docs/architecture.md` Key flow 1, `docs/design/degradation-ladder.md` and the
   engine docstring, with the new boundary written precisely enough that it does
   not become a licence for any codec claim on the success path -- plus narrowing
   the test that pins the current boundary
   (the test in `tests/test_argv.py` that pins "a codec outside the copy mask
   produces no note" on the success side). Also adds an advisory to `--to png` from a JPEG, which is
   correct and may be more noise than anyone wants on an image batch.

## Tracking

- Milestone: [lossy-source-notes](https://github.com/bhemsen/converter/milestone/7) (#7)
- Issues: created from this spec once it is merged (one per implementable step)

## Verification

Machine checks:

- [ ] Verify passes (ruff check, ruff format --check, pytest) on the merge commit.
- [ ] A test per covered target that a lossy source produces the advisory, with
      its exact wording pinned.
- [ ] A test that a **lossless** source that is not the target's own codec
      produces no advisory: ALAC into `flac` reaches the selective rung -- measured,
      `1 converted`, no note -- so it actually exercises the guard. `flac` from
      `flac` is kept only as a rung-1 control: it copies and wins at rung 1, so it
      never reaches the rung the advisory would live on and proves nothing about it.
- [ ] A test that a lossy source into a **lossy** target produces the ordinary
      re-encode note and no advisory.
- [ ] A test that `LOSSY_CODECS` excludes `alac`, `flac`, `wmalossless`,
      `truehd` and the `pcm_*` family -- the members a careless list gets wrong.
- [ ] A test pinning that exactly `flac`, `wav`, `png`, `tiff` and `bmp` satisfy
      the lossless criterion across the **whole** registry -- the guard that stops
      phase 6's three new fallback-less rules from being read as lossless targets.
- [ ] A test that the probe count per file is unchanged.
- [ ] A test that the success-side verification still refuses every codec-level
      statement -- unchanged by this phase, and the guard that the advisory did not
      leak onto the success path.

Human milestone-QA gate. `$FF` is the absolute ffmpeg path from *This machine*;
every fixture has a distinct stem:

```text
New-Item -ItemType Directory -Force in
& $FF -y -f lavfi -i sine=duration=2 -c:a libmp3lame -b:a 128k in/lossy-mp3.mp3
& $FF -y -f lavfi -i sine=duration=2 -c:a libopus in/lossy-opus.opus
& $FF -y -f lavfi -i sine=duration=2 -c:a flac in/lossless-flac.flac
& $FF -y -f lavfi -i sine=duration=2 -c:a alac in/lossless-alac.m4a
& $FF -y -f lavfi -i sine=duration=2 -c:a pcm_s16le in/lossless-wav.wav
& $FF -y -f lavfi -i color=c=red:size=200x200:d=1 -frames:v 1 in/lossy-jpg.jpg
```

- [ ] `--to flac in out` over `lossy-mp3.mp3` prints the advisory naming `mp3`,
      and the output is a playable FLAC. This is the case the phase exists for.
- [ ] The same run over `lossless-alac.m4a` prints **no** advisory -- the negative
      that actually reaches the rung. `lossless-flac.flac` is the rung-1 control.
- [ ] `--to wav in out` over `lossy-mp3.mp3` prints **no** advisory. Silent by
      decision, not by oversight -- the accepted inconsistency.
- [ ] `--to mp3 in out` over `lossy-opus.opus` prints the ordinary re-encode note
      and no advisory: lossy-to-lossy is out of scope by decision.
- [ ] `--to png in out` over `lossy-jpg.jpg` prints no advisory either.
- [ ] A second run over any converted tree reports `0 converted`, exit 0.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| The advisory reads as "the tool destroyed something" | The constitution gains the degradation-versus-advisory distinction, and the wording is pinned by test |
| The advisory leaks onto the success path and erodes #18's boundary | The gate confined it to the failure-side rung, and a Verification bullet pins that the success-side verification still refuses every codec-level statement |
| The lossy set misclassifies a codec | The awkward members are named in a test rather than left to the author's memory |
| The same source says something into FLAC and nothing into WAV | Accepted at the gate and recorded, with a QA item asserting the silence is deliberate. Closing it needs the success-side widening the gate declined |
| Someone extends this to detect laundered sources | Named out of scope, with the reason: it needs spectral analysis, which `docs/vision.md` already rules out |
| Under option 1, a lossy source that also fails the *selective* rung wins on `last_resort` and prints no advisory | A declared attempt's notes are fixed data, so the advisory cannot reach it. Named as a known gap rather than discovered: the fix, if it is wanted, is to extend the five lossless targets' `last_resort` note text, which is a profile edit and not an engine one |
| The bit-depth truncation `--to wav` performs stays unreported | Out of scope here and named in the facts table with its measurement, so it is a recorded gap with somewhere to land rather than an assumption this phase quietly inherits |

## Decision log

- 2026-08-27: The prior-art entry's recorded weakness is closed. The seed noted
  that research mode `none` left it unchecked whether any comparable converter
  warns at all; checked now, the principle is stated everywhere and no tool
  surfaced that acts on it, so the differentiation is real. The entry's other half
  — whether a list exists to adopt — resolved the other way; see the entry below
  on ffmpeg's `-codecs` flag.
- 2026-08-27: `docs/roadmap.md`'s seeded verdict "architecture — yes: a
  lossy-codec set is cross-cutting data" is wrong and is corrected here.
  Cross-cutting codec data already lives in `converter/profiles.py` as a
  module-level frozenset: `TEXT_SUBTITLE_CODECS` is shared by `mp4`, `mov` and
  `webm`. (Most masks are inlined per profile -- only the four container profiles
  use module-level constants — so the shared one, not their general shape, is the
  evidence.)
- 2026-08-27: The collision suspected at seeding is real but narrower than it
  looked. It is not "the success path forbids codec statements" in general — the
  motivating case is a *failure*-side rung and entirely free. It is the four
  targets whose cheap attempt always encodes, and that is the gate's decision.
- 2026-08-27: Review round 1 falsified the claim that no flag answers lossiness.
  ffmpeg's `-codecs` classifies every codec the spec had named as an awkward case,
  correctly. The decision to curate survives on better grounds — `webp` reports
  both flags, reading it costs a subprocess, and `gif` reports lossless while this
  project measured it keeping 182 of 36 485 colours — and the prior-art AVOID is
  corrected rather than left asserting something untrue.
- 2026-08-27: Review round 1 also found the lossless criterion overloaded. Bare
  `fallback_name is None` matches nine rules, four of which mean "drop", and phase
  6 adds three more that would make `mp3` and `m4a` read as lossless targets. The
  criterion is now the pair, pinned by a registry-wide test.
- 2026-08-27: And that `--to wav` from a 24-bit FLAC silently writes 16-bit PCM,
  so `fallback_name=None` does not mean "gives up nothing". The phase reuses the
  flag as the profile's own declaration and names the truncation as a separate
  gap rather than inheriting a false premise.
- 2026-08-27: Review round 2 found the round-1 corrections had landed in new prose
  while three older passages still asserted the opposite — the prior-art ADOPT
  bullet, the first decision-log entry, and the roadmap's durable foundation-impact
  row. All three now say what the measurements say. Worth noting as a failure
  mode: correcting a claim is not finished until every restatement of it moves,
  which is the same lesson issue #38's follow-up commit recorded.
- 2026-08-27: Gate chose `flac` only. The advisory stays on the failure-side rung,
  where it is free, and the success-side boundary #18 drew is left intact. The
  accepted cost is an inconsistency a user can notice — the same MP3 says
  something on the way to FLAC and nothing on the way to WAV — which is recorded
  in the decision row and pinned by a QA item rather than left to be discovered.

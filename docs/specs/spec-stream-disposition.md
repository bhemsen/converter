# Spec: stream-disposition (roadmap phase 6)

> Created: 2026-08-26

Teach the engine to tell a cover picture from a real video stream, so the audio
targets whose muxers accept one can carry album art through instead of dropping
it — and retire the standing notes that a partial-mapping verification has since
made redundant. This spec carries no lifecycle state — acceptance is the spec
merged on the default branch with a milestone and issues, and all progress lives
in the GitHub issues and milestone. A completed spec is moved to
`docs/specs/archive/`.

**Depends on milestone #3 (audio-formats), which is complete.** It revisits the
`mp3`, `m4a` and `flac` profiles phase 3 created.

## Why this phase changed shape since it was seeded

`docs/roadmap.md` seeded this phase as "the engine cannot name what it dropped".
That half is already solved: issue #18's fix (`fix(batch): verify a structurally
partial cheap attempt on success`) narrowed the constitution's probe rule and
added `jobs.verify_success`, so a profile that declares `partial_mapping=True`
is probed once on success and names each unmapped stream per stream.

Two consequences this phase must deal with, both measured against the merged
code:

1. **The remaining half is *carrying* artwork, not reporting it.** The engine has
   the stream list on the happy path now; what it lacks is the fact that
   distinguishes a cover picture from a video.
2. **The phase-3 standing notes are now redundant, and this phase makes them
   false.** Measured on `PROFILES["mp3"]` with an MP3-plus-cover-art source, the
   run prints both `non-audio streams, including cover art, are not carried into
   MP3` (the standing note, on every file) and `video stream 1 (png) dropped: not
   supported by MP3` (the verifier, accurate). The phase-3 gate chose the
   standing note *because* per-stream naming was impossible on the happy path —
   that premise is gone, and once artwork is carried the note is not merely noisy
   but wrong.

## Outcome

- [ ] `Stream` carries whether a stream is an attached picture, and
      `probe_streams` fills it — in the same single ffprobe call it already makes.
- [ ] `mp3`, `m4a` and `flac` carry an embedded cover picture through a
      conversion instead of dropping it, for the targets the gate approves.
- [ ] A **real** video stream is still dropped and still named — the whole point
      of the discriminator is that artwork and video stop being the same thing.
- [ ] The standing notes on the six audio profiles are gone, and nothing they
      said is lost: every claim they made is now made per stream by
      `jobs.verify_success`, or is no longer true.
- [ ] No conversion loses a stream without a word, and no note claims a loss that
      did not happen.
- [ ] `ffprobe` still runs at most once per file.

## Scope

### In scope

- `converter/ffmpegtool.py`: an `attached_pic` field on `Stream`, and the
  `stream_disposition=attached_pic` clause in `probe_streams`' existing query.
- `converter/jobs.py`: resolving a stream to its rule by disposition as well as
  type, so an attached picture can have its own rule.
- `converter/profiles.py`: an `attached_pic` rule on the audio profiles the gate
  approves, their cheap attempts mapping video, and the removal of the standing
  notes this phase makes redundant or false.
- The tests for all of it, including the per-target carry-through.

### Out of scope

- Video and image targets. `mkv` already carries attachments by `codec_type`,
  and an image target's whole content is the picture — neither needs a
  disposition.
- Any other ffprobe disposition (`default`, `forced`, `comment`). Only
  `attached_pic` has a decision resting on it; adding the rest would be
  generality with no caller.
- **Writing** a disposition. This phase carries an existing picture through; it
  never marks a stream as artwork that was not already marked.
- Extracting cover art to a separate file, or embedding art from one.
- The `wav` and `mp4` standing-note holes phases 3 and 4 left open — those are
  about a stream type never being mapped at all, which no disposition changes.

## Constraints

- `ffprobe` runs at most once per file, and never on the happy path of an
  exhaustive cheap attempt (`docs/constitution.md`, as narrowed by #18).
- Value types are frozen dataclasses; every parameter and return annotated.
- A target format is data, not code: the per-target decision about artwork is a
  profile entry, not a branch in the engine.
- Never report success for a conversion that silently dropped something.
- The test suite keeps passing with no ffmpeg installed.

## Prior art

- [Cover art and stream disposition (Phase 6)](../prior-art.md#cover-art-and-stream-disposition-phase-6)
  — the concern seeded for this phase. beets' `convert` plugin is the **stance**
  to adopt: artwork is a first-class, default-on concern of a conversion pipeline
  (`embed: yes`), not an incidental stream. Its **mechanism** is the AVOID — it
  embeds through a tag library, which here would be a second runtime dependency.
  The ffprobe entry is the reuse, and its AVOID is the trap this phase exists to
  close: inferring artwork from the codec name, since `mjpeg` and `png` are the
  codecs of both a cover picture and a real video.

## Design

No new design artifact, but `docs/design/stream-decision.md` gains a node: the
question "is this stream an attached picture?" sits before the type lookup. That
edit is authored in this spec's own PR, since the diagram is a foundation-level
contract and the change is one node.

## Human prerequisites

- none.

## Prior decisions

### The measured facts these decisions rest on

Measured against ffmpeg 9.0 during planning; the review is asked to falsify.

| Fact | Consequence |
|---|---|
| One ffprobe query returns the disposition alongside the fields `probe_streams` already asks for: `-show_entries stream=index,codec_type,codec_name:stream_disposition=attached_pic` yields `0,mp3,audio,0` and `1,png,video,1` | No second probe, no new round-trip. The cost is one clause |
| **Artwork survives a mapped copy** into `mp3`, `m4a` and `flac`, disposition intact (`1,png,video,1` out) — with a source whose audio codec the target accepts | The carry-through works; the discriminator is what is missing |
| **A real video behaves differently per target.** `m4a` rejects a real mjpeg (`Could not find tag for codec mjpeg`). `flac` accepts it at exit 0 and discards it. `mp3` rejects h264 (`No mimetype is known for stream 1, cannot write an attached picture`) but **writes a real mjpeg as a single-frame attached picture at exit 0** | The hazard of mapping video blindly is confined to `mp3` with an mjpeg or png *video* source. `m4a` fails into the ladder; `flac`'s discard is named by the verifier |
| `jobs._structural_drop` reaches its verdict from `profile.rules.get(stream.codec_type)` and the stream limit alone, never from the codec | A rule resolved by disposition slots into the same helper, so the success-side verifier keeps working unchanged |
| Every one of the 17 profiles declares `partial_mapping=True` | Every conversion is already probed on success. This phase adds no probe to any run that did not have one |

### Decisions

| Decision | Rationale | Date |
|---|---|---|
| `Stream` gains one boolean field, `attached_pic`, not a general disposition set | Only this disposition has a decision resting on it. A `frozenset[str]` of every disposition would be generality with no caller, and the constitution's value-type rule favours the narrow, named fact | 2026-08-26 |
| An attached picture is resolved to a **`"attached_pic"` key in `profile.rules`**, falling back to `stream.codec_type` when the profile declares none — exactly how phase 4 added the `attachment` rule, and no new `StreamRule` field | Keeps the per-target decision in the profile where the constitution puts it, and keeps `_structural_drop` and `verify_success` working by construction, since both resolve a rule and neither cares how the key was chosen | 2026-08-26 |
| A profile with **no** `attached_pic` rule keeps today's behaviour exactly: the picture falls through to the `video` lookup, finds no rule, and is dropped with the existing note | This phase must not change a target nobody asked it to change. `ogg`, `opus` and `wav` reject a picture outright (measured in phase 3) and gain nothing from a rule | 2026-08-26 |
| The `attached_pic` rule copies unconditionally — an accept-anything mask, like `mkv`'s attachment rule | ffprobe reports the picture's codec (`png`, `mjpeg`) but the decision is the disposition, not the codec. Enumerating codec names would repeat the phase-4 mistake the attachment rule already corrected | 2026-08-26 |
| **The standing notes are removed from all six audio profiles**, not just the three that gain artwork | Measured: the verifier already names every stream those notes describe, per stream and accurately. Keeping them would print a blanket note on every file for a benefit that no longer exists — and for `mp3`, `m4a` and `flac` the note becomes false the moment artwork is carried. Their removal is a behaviour change and is listed in Verification | 2026-08-26 |
| `docs/design/stream-decision.md` gains one node — "is this stream an attached picture?" ahead of the type lookup — authored in this PR | The diagram is where the per-stream branch is settled; leaving it stale would be the drift `docs/design.md` warns about. One node, and the rest of the diagram is unchanged | 2026-08-26 |
| No profile's `partial_mapping` changes | All 17 already declare it true, so the success-side verification this phase depends on is already running everywhere | 2026-08-26 |
| OPEN — which of `mp3`, `m4a`, `flac` map video in their cheap attempt, given the measured per-target hazard | resolved at the spec-acceptance gate; see the note below | — |

### The one open decision, in full

Carrying artwork requires the cheap attempt to map video (`-map 0:a? -map 0:v?
-c copy`); the cheap attempt is blind, so it cannot filter on disposition. The
measured consequence differs per target:

- **`m4a` — no cost.** A real video is rejected by the muxer, so such a source
  fails into the ladder, where the disposition *is* known and the video is
  dropped with a proper note. Pure win.
- **`flac` — no cost.** A real video is silently discarded by the muxer, and the
  success-side verifier names it (`video stream N (mjpeg) dropped: not supported
  by FLAC`) because the stream is not an attached picture and so does not match
  the new rule. Pure win.
- **`mp3` — a real cost.** h264 is rejected, so the common video case is safe.
  But a source whose video stream is **mjpeg or png** is written as a
  single-frame attached picture at exit 0. The user asked to rip audio from an
  MJPEG video and gets an MP3 with a stray cover image, while the verifier
  reports the video stream as *dropped* — approximately true (only one frame
  survived, as art) but not exactly what happened.

Today, with no video mapped, that mp3 case is clean: the video is not mapped, and
the verifier names it accurately. So the gate is trading `mp3` artwork against
`mp3` accuracy on an unusual source. Three answers:

1. **All three map video.** `mp3` gets artwork like the others; an MJPEG-video
   source produces a stray cover and a note that is close but not exact.
   Simplest to explain: "the three targets whose muxers hold a picture, hold it".
2. **`m4a` and `flac` map video; `mp3` does not.** Follows the measurements
   exactly — the two targets that pay nothing gain artwork, and the one that
   pays keeps today's accuracy. The cost is that the commonest music format is
   the one that loses its artwork, which is the reverse of what a user expects.
3. **All three map video, and `mp3` declares an `attached_pic` rule whose drop
   note for a non-picture video says what actually happens** — reduced to a
   single frame rather than dropped. Answer 1 plus one honest note, at the cost
   of a note whose wording is specific to one target's muxer quirk.

## Tracking

- Milestone: stream-disposition (created at the spec-acceptance gate)
- Issues: created from this spec once it is merged (one per implementable step)

## Verification

Machine checks:

- [ ] Verify passes (ruff check, ruff format --check, pytest) on the merge commit.
- [ ] A test that `probe_streams` fills `attached_pic` from a stubbed ffprobe
      payload, true for a picture stream and false for a plain video.
- [ ] A test that the probe still makes exactly **one** ffprobe call per file,
      and that its `-show_entries` argument is pinned verbatim — the clause is
      easy to break and the failure would be silent.
- [ ] A test that a stream with `attached_pic` resolves to the `attached_pic`
      rule when the profile declares one, and to the `video` rule when it does
      not.
- [ ] A test that a profile with no `attached_pic` rule behaves byte-for-byte as
      it does today, for both argv and notes — `ogg`, `opus` and `wav` are the
      guard.
- [ ] Per target that gains artwork, a test pinning the cheap attempt's argv and
      one asserting a picture stream is accepted while a non-picture video stream
      of the same codec is dropped with a note.
- [ ] A test that **no** audio profile carries a standing note any more, and a
      test per removed note that the verifier still names the same loss per
      stream — the removal must lose no statement.
- [ ] `jobs.verify_success` and `jobs.describe_unsupported` keep their current
      behaviour for every profile that gains no rule.

Human milestone-QA gate. `$FF` is the absolute ffmpeg path from *This machine*:

```text
New-Item -ItemType Directory -Force in
& $FF -y -f lavfi -i color=c=blue:size=200x200:d=1 -frames:v 1 cover.png
& $FF -y -f lavfi -i sine=duration=2 -c:a libmp3lame in/plain.mp3
& $FF -y -i in/plain.mp3 -i cover.png -map 0:a -map 1:v -c copy -disposition:v:0 attached_pic in/art.mp3
& $FF -y -f lavfi -i sine=duration=2 -c:a aac in/s.m4a
& $FF -y -i in/s.m4a -i cover.png -map 0:a -map 1:v -c copy -disposition:v:0 attached_pic in/art.m4a
& $FF -y -f lavfi -i sine=duration=2 -c:a flac in/s.flac
& $FF -y -i in/s.flac -i cover.png -map 0:a -map 1:v -c copy -disposition:v:0 attached_pic in/art.flac
& $FF -y -f lavfi -i testsrc=size=160x120:rate=10:duration=2 -f lavfi -i sine=duration=2 -c:v mjpeg -c:a libmp3lame in/mjpegvid.mkv
```

- [ ] For each target the gate approves: converting its `art.*` fixture keeps the
      picture — `ffprobe` the output and confirm the stream is present **and**
      still carries `attached_pic=1`.
- [ ] `in/plain.mp3` (no artwork) converts and prints **no** note at all. This is
      what the standing-note removal buys, and it is the change a user notices
      first.
- [ ] `in/mjpegvid.mkv` under `--to mp3` behaves exactly as the gate's decision
      says, and whatever it prints matches what `ffprobe` finds in the output.
- [ ] `--to ogg` and `--to wav` over `in/art.mp3` behave exactly as they do on
      the previous commit — the targets that gain no rule must be untouched.
- [ ] A second run over any converted tree reports `0 converted`, exit 0.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Removing the standing notes loses a statement the verifier does not make | A test per removed note asserts the verifier still names that loss per stream; the QA gate checks the no-artwork case prints nothing |
| The new rule changes a target nobody asked to change | A profile with no `attached_pic` rule is pinned byte-for-byte against today, with `ogg`, `opus` and `wav` as the guard |
| The `-show_entries` clause is broken later and the field silently reads false | Its argv is pinned verbatim by a test, because a wrong clause fails silently rather than loudly |
| Mapping video reintroduces the phase-3 hazard | Measured per target, and the one target that actually pays is the gate's decision rather than an assumption |
| A second probe creeps in | The one-call test, plus every profile already declaring `partial_mapping=True`, so no run gains a probe it did not have |

## Decision log

- 2026-08-26: The phase was re-scoped before drafting. Its seeded framing —
  "the engine cannot name what it dropped" — was overtaken by issue #18's fix,
  which narrowed the constitution's probe rule and added a success-side verifier.
  What remains is carrying artwork, plus retiring the phase-3 standing notes that
  the verifier made redundant and that carrying artwork would make false.
- 2026-08-26: Measured that the hazard of mapping video is confined to `mp3` with
  an mjpeg or png video source — `m4a` rejects a real video and `flac` discards
  it where the verifier names it. That measurement is what turned a blanket
  question into a per-target one, and it is the phase's open decision.

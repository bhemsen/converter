# Spec: audio-formats (roadmap phase 3)

> Created: 2026-08-25

Add the five remaining audio target profiles — `mp3`, `m4a`, `flac`, `opus`,
`ogg` — to the registry, alongside the `wav` profile that already exists, and
prove that adding a format really does cost nothing but a profile entry and its
test. This spec carries no lifecycle state — acceptance is the spec merged on the
default branch with a milestone and issues, and all progress lives in the GitHub
issues and milestone. A completed spec is moved to `docs/specs/archive/`.

## Outcome

- [ ] `converter --to <fmt>` works for `mp3`, `m4a`, `flac`, `opus` and `ogg`,
      and `wav` still behaves exactly as it does after phase 2.
- [ ] `--list-formats` prints six audio targets.
- [ ] **The diff of this phase touches `converter/profiles.py` and the tests, and
      nothing else.** This is the constitution's "a target format is data, not
      code" claim being cashed in for the first time; a diff in `cli.py`,
      `batch.py`, `paths.py` or `jobs.py` means the profile model is wrong and
      that is the bug to fix, not the diff to accept.
- [ ] Every new profile has a test pinning the exact argv it builds, for a
      copyable and for a non-copyable input.
- [ ] Every degradation branch a new profile introduces has a test asserting the
      note it emits.
- [ ] Whatever a source carries that the target cannot hold is named in a note —
      never dropped in silence.
- [ ] The curated source-suffix set covers the audio formats people actually
      have, so `--to mp3` over a real music tree finds them.

## Scope

### In scope

- Five new `Profile` entries in `converter/profiles.py` with their stream rules,
  copy masks, fallback encoders and container options, plus their registry
  entries.
- Extending the curated source-suffix set with the audio suffixes a source tree
  realistically holds (`.aac`, `.m4b`, `.wma`, `.aiff`, `.alac`, `.ape`, `.wv`
  and the six targets' own suffixes).
- The tests those profiles require, per the constitution's two gates.
- Cover-art handling, per the decision resolved at the acceptance gate.

### Out of scope

- Video and image targets — phases 4 and 5, which depend on the same phase 2 and
  not on this one.
- Any encoder-tuning surface. Bitrates and quality settings are chosen once, as
  defaults, and are not exposed (`docs/vision.md` non-goal).
- Loudness normalisation, resampling, channel remapping, tag editing. A
  conversion is a conversion.
- Changing the engine or the ladder. If a profile needs an engine change, that is
  a finding to escalate, not to absorb quietly — see the Risks table.

## Constraints

- A target format is data, not code (`docs/constitution.md`,
  `docs/architecture.md`): `converter/profiles.py` stays a leaf, and this phase's
  diff proves the rule rather than asserting it.
- No second external dependency, and no second backend — every format here has a
  working ffmpeg muxer or it does not ship (`docs/vision.md` non-goals).
- Never report success for a conversion that silently dropped something.
- Every degraded conversion names the stream index, that stream's codec, and what
  was given up.
- The test suite keeps passing with no ffmpeg installed; the subprocess boundary
  stays stubbed.

## Prior art

- [Python wrapper structure around the ffmpeg CLI (Phase 3, Phase 4)](../prior-art.md#python-wrapper-structure-around-the-ffmpeg-cli-phase-3-phase-4)
  — the concern tagged for this phase. Its ADOPT is confirmation rather than code:
  `ffmpeg-normalize`'s split into per-stream-type handling plus a command builder
  is the shape this codebase already has. Its AVOID is the live one here — never
  scrape ffmpeg's stderr to decide a second pass; a profile that "needs" stderr to
  choose an encoder is a profile modelled wrong.
- [Container/codec capability modelling (Phase 1)](../prior-art.md#containercodec-capability-modelling-phase-1)
  — still governing: HandBrake's copy-mask plus encoder-fallback vocabulary is what
  each new profile is written in, and the ffmpeg-CLI entry is why every mask below
  is curated by hand rather than discovered from `ffmpeg -codecs`.

## Design

No new design artifact. This phase makes no new decision about the ladder or the
per-stream branch — it fills in data for decisions `docs/design/degradation-ladder.md`
and `docs/design/stream-decision.md` already settled. Implement against those two.

## Human prerequisites

- none. No secret, no dependency, no external provisioning. The QA gate needs the
  ffmpeg already installed on this machine, and one real music file per source
  codec, which the gate synthesises.

## Prior decisions

| Decision | Rationale | Date |
|---|---|---|
| Each audio target declares a stream limit of 1 for audio, like WAV | These containers hold one audio stream in any player anyone will use; a second stream is dropped with a note naming it, which is the honest outcome rather than a file that plays unpredictably | 2026-08-25 |
| Copy masks: `mp3` -> `{mp3}`; `m4a` -> `{aac, alac}`; `flac` -> `{flac}`; `opus` -> `{opus}`; `ogg` -> `{vorbis, opus, flac}` | Each is what the muxer accepts as-is, curated by hand per the prior-art AVOID. A copy mask this narrow is the point: a re-encode that the mask predicts is named in a note, and a stream copy that the mask allows costs nothing | 2026-08-25 |
| Fallback encoders and their defaults: `mp3` -> `libmp3lame -q:a 2` (VBR ~190 kbit/s); `m4a` -> `aac -b:a 192k`; `flac` -> `flac` (lossless); `opus` -> `libopus -b:a 128k`; `ogg` -> `libvorbis -q:a 5` (~160 kbit/s) | Quality-based VBR where the encoder has a good one, bitrate where it does not, all at "transparent enough that nobody notices" rather than "smallest". They are defaults, not a surface: `docs/vision.md` rules out an encoder-tuning surface, so these are chosen once and pinned by the argv tests | 2026-08-25 |
| Re-encoding a lossy source into another lossy format emits a note naming both codecs; re-encoding **into** `flac` from a lossy source also emits one, saying the result is lossless but the source was not | Generation loss is exactly the kind of thing the free tools stay silent about (`docs/vision.md`), and a 40 MB FLAC made from a 128 kbit/s MP3 is a result the user should be told about rather than discover | 2026-08-25 |
| Converting into `wav` or `flac` from any source emits **no** note for the encode itself | Decoding to the container's own lossless codec gives up nothing; a note per file would be noise. This is the rule phase 1 already established for WAV's PCM rule | 2026-08-25 |
| A source's video streams that are not cover art are dropped with a note naming the stream and its codec | `--to mp3` pointed at a video file is a legitimate "rip the audio" request; failing it would be unhelpful, and dropping the video without a word is what the constitution forbids | 2026-08-25 |
| OPEN — cover art: which audio targets keep an embedded picture stream, and which drop it with a note | resolved at the spec-acceptance gate; see the note below | — |

### The one open decision, in full

Music files carry cover art as a video stream with the `attached_pic`
disposition — usually `mjpeg` or `png`. It is not metadata, so `docs/vision.md`'s
EXIF/ICC non-goal does not settle it, and nothing in the prior art does either.

Keeping it costs a video rule per profile (`-c:v:{n} copy` plus
`-disposition:v:{n} attached_pic`) and a real risk: ffmpeg's support for attached
pictures differs per muxer, and it is *known* to be awkward for Ogg and Opus,
where the picture goes into a `METADATA_BLOCK_PICTURE` tag rather than a stream.
Dropping it is one line per profile and always works — and loses the album art
off every file someone converts.

The gate picks one of:

1. **Keep cover art where the muxer holds it as a stream (`mp3`, `m4a`, `flac`),
   drop it with a note for `wav`, `opus` and `ogg`.** Honest and per-format, and
   the note tells the user which of their files lost artwork. Costs a QA item
   proving each of the three really does keep it with the installed ffmpeg 9.
2. **Drop cover art everywhere, always with a note.** One rule, no per-muxer
   surprises, no risk of a profile that works on one ffmpeg build and not another.
   Every converted music file loses its artwork, and is told so.

Whichever is picked, the drop is never silent.

## Tracking

The decomposition into steps lives as GitHub issues, not in this file — one
issue per step, grouped under a milestone. This spec owns the design; the issues
own progress.

- Milestone: audio-formats (created at the spec-acceptance gate)
- Issues: created from this spec once it is merged (one per implementable step)

## Verification

Machine checks:

- [ ] Verify passes (ruff check, ruff format --check, pytest) on the merge commit.
- [ ] `git diff <phase-2-merge>..HEAD --stat` for this milestone lists only
      `converter/profiles.py` and files under `tests/`. This is the phase's
      headline outcome and it is checked, not asserted.
- [ ] Per new profile, a test pinning the full argv for a copyable input and for
      a non-copyable one — ten tests, five profiles, both cases each.
- [ ] Per new degradation branch, a test asserting the note: the lossy-to-lossy
      re-encode, the lossy-source-into-flac note, a second audio stream dropped,
      a non-cover-art video stream dropped, and whatever the cover-art decision
      adds.
- [ ] A test that `wav`'s argv is byte-for-byte what it was before this phase.
- [ ] A test that every registry entry has a `name`, a `description`, a target
      suffix that appears in the curated source-suffix set, and at least one
      stream rule — a structural check that catches a half-written profile.
- [ ] A test that converting into `flac` or `wav` emits no note for the encode
      itself.

Human milestone-QA gate — the machine checks stub the subprocess boundary, so
only this proves a real conversion. Synthesise one source per codec first with
the absolute ffmpeg path from *This machine* (`libmp3lame`, `aac`, `flac`,
`libopus`, `libvorbis`, plus one `.mkv` with an audio track):

- [ ] Each of the six targets converts a real source and the result plays.
- [ ] `--to mp3` over a directory holding all six source kinds converts every one
      of them, reports the re-encodes it performed by name, and exits 0.
- [ ] A stream copy really is a copy: `--to opus` from an `.opus` source finishes
      near-instantly and the output is bit-identical in its audio stream.
- [ ] `--to flac` from a 128 kbit/s MP3 prints the generation-loss note.
- [ ] A second run over any converted tree reports `0 converted`, exit 0.
- [ ] Cover art behaves exactly as the gate's decision says, verified per target
      with `ffprobe` rather than by looking at a player.
- [ ] `--to mp3` on a video file rips the audio and names the dropped video
      stream.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| A profile turns out to need an engine change, quietly breaking the phase's headline outcome | The diff check is a Verification item. A profile that cannot be expressed as data is escalated as `needs:planning`, not absorbed by editing `jobs.py` |
| A copy mask is wrong and a stream copy produces a file that does not play | The QA gate plays one output per target, and the copy-vs-re-encode path is the one thing the machine checks cannot prove |
| The fallback defaults age badly, or someone treats them as a tuning surface | They are pinned by the argv tests, so changing one is a visible, argued diff rather than a drive-by |
| Cover art works on this machine's ffmpeg 9 and not on an older build | The QA gate verifies with `ffprobe` per target; the decision note records that muxer support is the risk, so a later bug report has somewhere to land |
| The curated suffix set misses a format people actually have, so `--to mp3` silently finds nothing | The suffix list is enumerated in Scope rather than left to taste, and the QA gate points the tool at a directory holding all six source kinds |

## Decision log

- 2026-08-25: No design artifact for this phase. The ladder and the per-stream
  branch are already drawn; phases 3-5 supply data for them, and a fourth diagram
  restating that would be the drift `docs/design.md` warns about.

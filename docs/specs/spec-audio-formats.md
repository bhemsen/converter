# Spec: audio-formats (roadmap phase 3)

> Created: 2026-08-25

Add the five remaining audio target profiles — `mp3`, `m4a`, `flac`, `opus`,
`ogg` — to the registry, alongside the `wav` profile that already exists, and
prove that adding a format really does cost nothing but a profile entry, its
README line and its test. This spec carries no lifecycle state — acceptance is
the spec merged on the default branch with a milestone and issues, and all
progress lives in the GitHub issues and milestone. A completed spec is moved to
`docs/specs/archive/`.

**Depends on milestone #2 (target-driven-cli), which is planned but not yet
merged.** Everything this phase builds on — the `PROFILES` registry, `name` and
`description` on the profile, the curated source-suffix set, `--to`,
`--list-formats` — is phase-2 code. Do not start against `main` until #2 closes.

## Outcome

- [ ] `converter --to <fmt>` works for `mp3`, `m4a`, `flac`, `opus` and `ogg`,
      and `wav` still behaves exactly as it does after phase 2.
- [ ] `--list-formats` prints seven lines, one per registry entry, including the
      five new audio names.
- [ ] **The diff of every PR in this milestone touches only
      `converter/profiles.py`, `README.md` and files under `tests/`.** This is the
      constitution's "a target format is data, not code" claim being cashed in for
      the first time; a diff in `cli.py`, `batch.py`, `paths.py` or `jobs.py`
      means the profile model is wrong and that is the bug to fix, not the diff to
      accept. `README.md` is in the list because `docs/roadmap.md` gives each
      coverage phase its own format list to maintain.
- [ ] Every new profile has a test pinning the exact argv it builds, for a
      copyable and for a non-copyable input.
- [ ] Every degradation branch a new profile introduces has a test asserting the
      note it emits.
- [ ] The curated source-suffix set covers the audio *and* video containers people
      actually have, so `--to mp3` over a real tree finds them.

## Scope

### In scope

- Five new `Profile` entries in `converter/profiles.py` — including each one's
  `cheap_attempt`, `explicit_streams` and `last_resort`, which the Prior
  decisions fix — plus their registry entries.
- Extending the curated source-suffix set: audio containers
  (`.aac`, `.m4b`, `.wma`, `.aiff`, `.aif`, `.ape`, `.wv`, `.caf`) and the video
  containers a "rip the audio" run needs (`.mp4`, `.mov`, `.avi`, `.webm`,
  `.m4v`, `.wmv`, `.flv`), on top of what phase 2's set already holds.
- `README.md`'s format list.
- The tests those profiles require, per the constitution's two gates.

### Out of scope

- Video and image targets — phases 4 and 5, which depend on the same phase 2 and
  not on this one.
- Any encoder-tuning surface. Bitrates and quality settings are chosen once, as
  defaults, and are not exposed (`docs/vision.md` non-goal).
- Loudness normalisation, resampling, channel remapping, tag editing.
- **Any engine change.** If a profile needs one, that is a finding to escalate as
  `needs:planning`, not to absorb by editing `jobs.py` — the phase's headline
  outcome is precisely that no such diff appears.
- **Keeping cover art as a picture stream.** It is not expressible as data and is
  recorded below as its own roadmap candidate.

## Constraints

- A target format is data, not code (`docs/constitution.md`,
  `docs/architecture.md`): `converter/profiles.py` stays a leaf, and this phase's
  diff proves the rule rather than asserting it.
- `ffprobe` never runs on the happy path. This is what bounds how precise a note
  can be for a conversion the cheap attempt completes — see the open decision.
- No second external dependency, and no second backend.
- Never report success for a conversion that silently dropped something.
- The test suite keeps passing with no ffmpeg installed.

## Prior art

- [Python wrapper structure around the ffmpeg CLI (Phase 3, Phase 4)](../prior-art.md#python-wrapper-structure-around-the-ffmpeg-cli-phase-3-phase-4)
  — the concern tagged for this phase. Its ADOPT is confirmation rather than code:
  `ffmpeg-normalize`'s split into per-stream-type handling plus a command builder
  is the shape this codebase already has. Its AVOID is the live one — never scrape
  ffmpeg's stderr to decide a second pass; a profile that "needs" stderr to choose
  an encoder is a profile modelled wrong.
- [Container/codec capability modelling (Phase 1)](../prior-art.md#containercodec-capability-modelling-phase-1)
  — still governing: HandBrake's copy-mask plus encoder-fallback vocabulary is what
  each new profile is written in, and the ffmpeg-CLI entry is why every mask below
  is curated by hand rather than discovered from `ffmpeg -codecs`.

## Design

No new design artifact. This phase makes no new decision about the ladder or the
per-stream branch — it supplies data for decisions
`docs/design/degradation-ladder.md` and `docs/design/stream-decision.md` already
settled. Implement against those two.

## Human prerequisites

- none. No secret, no dependency, no external provisioning.

## Prior decisions

### The muxer facts these profiles rest on

Verified against the installed ffmpeg 9.0 during planning, not assumed. A later
reader should re-verify rather than trust the table.

| Fact | Consequence |
|---|---|
| `.m4a` auto-selects the **`ipod`** muxer, not `mp4`, and ipod's accept set is *narrower*: `mp3`, `opus` and `flac` stream copies are all rejected | The `m4a` mask is `{aac, alac}` and must **not** reuse `profiles.MP4_AUDIO_CODECS`, which is much wider |
| The `ogg` muxer accepts `vorbis`, `opus` and `flac` as-is; it rejects `mp3` and `aac` | The `ogg` mask is `{vorbis, opus, flac}` |
| The `mp3` muxer enforces "exactly one MP3 audio stream" | `stream_limit=1` there is a muxer constraint, not only a product judgement |
| The `ogg` and `opus` muxers **reject** a picture stream outright (`Unsupported codec id in stream 1`), and the `wav` muxer rejects any video stream | Not "awkward support" — a hard failure, which is why a blind cheap attempt that mapped video would fail for these targets |
| `mp3`, `m4a` (ipod) and `flac` **accept** a picture stream that already carries the `attached_pic` disposition. A **bare** mjpeg is a different case: `m4a` rejects it, `mp3` silently writes it as a single frame | These three cannot map video safely, so they map audio only |
| `m4a` (ipod) copies a **full h264 track** through without complaint: `clip.mkv` under `-map 0:a? -map 0:v? -c copy` exits 0 with `0\|aac 1\|h264` | The decisive reason `m4a` maps no video: the user asked for audio and would get a video file |
| The `opus` muxer accepts a **Vorbis** stream | A blind copy into `.opus` can ship a file whose extension lies about its contents; `opus` forces its encoder instead |
| The `flac` muxer enforces exactly one FLAC audio stream, like `mp3` | `stream_limit=1` is a muxer constraint there too |
| `-q:a 2` (libmp3lame) and `-q:a 5` (libvorbis) are valid | The fallback defaults below are real |

### Decisions

| Decision | Rationale | Date |
|---|---|---|
| **On the happy path the muxer is the authority, not the copy mask.** A stream copy that ffmpeg's muxer accepts ships, whether or not the mask lists that codec; the mask governs the *failure* path, where the engine builds the selective rung | Measured, not assumed: `--to opus` from a Vorbis `.ogg` under a blind `-c:a copy` exits 0 and writes a `.opus` file containing Vorbis. Nothing short of a probe can prevent that, and a probe on the happy path is forbidden. The per-profile cheap attempts below are chosen so that where the muxer is looser than the format's identity, the profile does not rely on a copy at all | 2026-08-25 |
| The `cheap_attempt`, `explicit_streams` and `last_resort` of each of the **five new** profiles are fixed by the table below; `wav` is untouched and keeps phase 2's shape exactly | A blanket rule does not survive contact with the muxers: they differ in whether they enforce the target's codec, whether they hold several audio streams, and whether they reject a picture stream. Each of those differences changes what an honest cheap attempt looks like | 2026-08-25 |
| `stream_limit=1` for `mp3` and `flac` only. `m4a`, `ogg` and `opus` declare **no** audio stream limit | Measured: the `mp3` and `flac` muxers both enforce exactly one audio stream, so the limit is real and a multi-stream source fails into the ladder, which names the stream it drops. `m4a`, `ogg` and `opus` accept several, so declaring a limit would mean mapping one stream and silently discarding the rest — a loss the tool could not name. Carrying every stream the container holds drops nothing at all, which is the better answer | 2026-08-25 |
| `opus` **does not copy**: its cheap attempt forces `libopus`, and carries a standing note saying the audio was re-encoded to Opus | The `opus` muxer accepts a Vorbis stream (measured), and `.opus` is a codec-defined format, so a copy can ship a file whose name lies about its contents. Forcing the encoder is the only way the label stays true without a probe. The standing note is accurate for every input, including an already-Opus source, where it is the generation-loss warning that source deserves | 2026-08-25 |
| `ogg` and `opus` **map video** in their cheap attempt; `mp3`, `m4a` and `flac` do not | Measured: the `ogg` and `opus` muxers reject a picture stream outright, so mapping video makes a cover-art source *fail* into the ladder, which then emits the real per-stream note. That costs one extra ffmpeg spawn for sources that carry artwork and nothing otherwise. The other three accept a picture — and `m4a` will happily copy a full h264 track into a file the user asked for as audio (measured) — so for them mapping video buys a silent wrong result instead of a note | 2026-08-25 |
| Every new profile declares a `last_resort`: the format's fallback encoder over the first audio stream, e.g. `flags("-map 0:a:0 -c:a libmp3lame -q:a 2")` | Not for the FLAC-from-WAV case, which the selective rung already handles. It is for the case the selective rung cannot: the rung may choose `-c:a copy` on a mask hit for a bitstream the muxer then refuses, and only a forced re-encode rescues that file | 2026-08-25 |
| Copy masks: `mp3` -> `{mp3}`; `m4a` -> `{aac, alac}`; `flac` -> `{flac}`; `opus` -> `{opus}`; `ogg` -> `{vorbis, opus, flac}` | Each is what the muxer accepts as-is, per the verified table above and curated by hand per the prior-art AVOID | 2026-08-25 |
| Fallback encoders and their defaults: `mp3` -> `libmp3lame -q:a 2` (VBR ~190 kbit/s); `m4a` -> `aac -b:a 192k`; `flac` -> `flac`; `opus` -> `libopus -b:a 128k`; `ogg` -> `libvorbis -q:a 5` (~160 kbit/s) | Quality-based VBR where the encoder has a good one, bitrate where it does not, all at "transparent enough that nobody notices" rather than "smallest". Defaults, not a surface: pinned by the argv tests, so changing one is an argued diff | 2026-08-25 |
| `flac` and `wav` declare **`fallback_name=None`**, so an encode into them emits no note; the other four declare theirs, so a re-encode emits the engine's existing per-stream note naming the source codec and the target codec | Decoding into a container's own lossless codec gives up nothing. This is the rule phase 1 established for WAV, expressed with the one lever `jobs.py` has | 2026-08-25 |
| **No generation-loss note** (a "your FLAC came from a 128 kbit/s MP3" warning) in this phase | It would need a lossy-codec set plus a new branch in `jobs.py`, and `Stream` carries no such notion — an engine change, which this phase's headline outcome forbids. Recorded below as a roadmap candidate rather than smuggled in | 2026-08-25 |
| No audio profile declares a **video rule**, so any video stream — cover art included — is dropped by the selective rung with the engine's existing "not supported by TARGET" note | Keeping cover art needs the `attached_pic` disposition, which `probe_streams` does not request and `Stream` does not carry, so the engine cannot tell a picture from a real video stream. The muxer table shows what happens if you guess: `m4a` hard-fails on a real MJPEG while succeeding on a picture, and `mp3` silently truncates it to one frame | 2026-08-25 |
| OPEN — what a conversion says when the cheap attempt **succeeds** and cover art is lost along the way | resolved at the spec-acceptance gate; see the note below | — |

### The five new profiles, fixed

`wav` is not in this table: it keeps phase 2's shape unchanged.

| Target | `cheap_attempt` | `explicit_streams` | `stream_limit` (audio) | `last_resort` |
|---|---|---|---|---|
| `mp3` | `-map 0:a? -c:a copy` | False | 1 | `-map 0:a:0 -c:a libmp3lame -q:a 2` |
| `flac` | `-map 0:a? -c:a copy` | False | 1 | `-map 0:a:0 -c:a flac` |
| `m4a` | `-map 0:a? -c:a copy` | False | none | `-map 0:a:0 -c:a aac -b:a 192k` |
| `ogg` | `-map 0:a? -map 0:v? -c copy` | False | none | `-map 0:a:0 -c:a libvorbis -q:a 5` |
| `opus` | `-map 0:a? -map 0:v? -c:a libopus -b:a 128k`, with the standing re-encode note | False | none | `-map 0:a:0 -c:a libopus -b:a 128k` |

`explicit_streams` is `False` throughout: every cheap attempt above selects by
type rather than by index, so the selective rung is never suppressed.

**To be measured before the issues are written**, and recorded here once they
are — the review closes these rather than the implementer discovering them:

- Does the `flac` muxer reject a *real* video stream while accepting a picture?
  If it does, `flac` belongs in the video-mapping group with `ogg` and `opus`,
  and its share of the open decision disappears.
- Does the `opus` muxer accept more than one audio stream? If it enforces one,
  `opus` gains `stream_limit=1` for the same reason `mp3` has it.

### Two roadmap candidates this phase deliberately does not take

Both need an engine change, so neither is a profile entry. Recorded here so they
are not silently lost; seeding them as roadmap phases is `/loopkit:roadmap`'s job.

1. **Stream-disposition awareness** — a `disposition` field on `Stream`, the
   matching `-show_entries` field in `ffmpegtool.py`, and a disposition branch in
   `jobs.py`. It is what keeping cover art actually costs, and it would let
   `mp3`, `m4a` and `flac` carry artwork through.
2. **Source-lossiness awareness** — a lossy-codec set the engine can consult, so a
   re-encode into a lossless target can warn that the source was already lossy.

### The one open decision, in full

`ffprobe` never runs on the happy path (`docs/constitution.md`), so a conversion
the cheap attempt completes has **no stream list** — the engine cannot name what
it dropped, because it does not know.

**This affects three targets, not six.** `ogg` and `opus` map video precisely so
that a cover-art source fails into the ladder, which then names the picture
stream and its codec properly; `wav` rejects video the same way. That leaves
`mp3`, `m4a` and `flac` — the muxers that *accept* a picture — where the cheap
attempt maps audio only, succeeds, and the artwork is gone with nothing to build
a note from. (If the flac measurement above comes back showing it rejects real
video, this narrows again, to `mp3` and `m4a`.)

Every degraded conversion the *ladder* reaches still names the stream index, its
codec and what was given up, exactly as `docs/vision.md` requires. The gap is the
happy path for those targets, and it is structural rather than an oversight. The
gate picks:

1. **A standing note on those profiles' cheap attempts** — a fixed line on the
   `Attempt`, e.g. `non-audio streams, including cover art, are not carried into
   MP3`. Always truthful, never silent, free, and it needs no amendment to any
   foundation doc. The cost is noise: it prints for every file, including the
   majority that had nothing to lose.
2. **Say nothing when the cheap attempt succeeds.** The quieter tool, and a file
   that had cover art loses it without a word. **Picking this requires amending
   `docs/constitution.md` in this PR** — its "never report success for a
   conversion that silently dropped something" is normative and this spec's own
   Constraints repeat it, so the exception has to be written down (scoped to the
   happy path, where the same document forbids the probe that would resolve it)
   rather than approved as a quiet violation. Phases 1 and 2 both set the
   precedent of amending a foundation doc in the spec's own PR.

Option 1 is the safer reading; option 2 is the quieter tool and costs an
amendment. Either way the loss is real and the phase records it.

## Tracking

The decomposition into steps lives as GitHub issues, not in this file — one
issue per step, grouped under a milestone.

- Milestone: audio-formats (created at the spec-acceptance gate)
- Issues: created from this spec once it is merged (one per implementable step)

## Verification

Machine checks:

- [ ] Verify passes (ruff check, ruff format --check, pytest) on the merge commit.
- [ ] For **every PR in this milestone**, `git diff main...<pr-head> --name-only`
      lists only `converter/profiles.py`, `README.md` and paths under `tests/`.
      Per-PR and merge-base-scoped on purpose: phases 3, 4 and 5 may run as
      parallel orchestrators, so a two-dot range against `main` would sweep in
      another milestone's commits.
- [ ] Per new profile, a test pinning the full argv for a copyable input and for
      a non-copyable one — ten tests, five profiles, both cases each.
- [ ] Per new degradation branch, a test asserting the note: a re-encode naming
      both codecs, a second audio stream dropped **for `mp3` and `flac`, whose
      muxers enforce one** (the other three carry every stream, so there is no
      drop to name), a video stream dropped, and whatever the cover-art decision
      adds.
- [ ] A test that converting into `flac` or `wav` emits no note for the encode.
- [ ] A test that `wav`'s argv is byte-for-byte what it was before this phase.
- [ ] A structural test over the whole registry: every entry has a `name`, a
      `description`, a target suffix present in the curated source-suffix set,
      and at least one stream rule — this catches a half-written profile, and it
      keeps working for phases 4 and 5.
- [ ] A test that `--to flac` from a PCM source reaches the **selective** rung
      -- verified against the real engine during review, which returns
      `selective` then `re-encode` for a `pcm_s16le` stream -- rather than
      landing as `failed`.

Human milestone-QA gate — the machine checks stub the subprocess boundary, so
only this proves a real conversion. `$FF` is the absolute ffmpeg path from *This
machine*; PowerShell, one command per line:

```text
New-Item -ItemType Directory -Force in
& $FF -y -f lavfi -i sine=duration=3 -c:a libmp3lame in/tone.mp3
& $FF -y -f lavfi -i sine=duration=3 -c:a aac        in/tone.m4a
& $FF -y -f lavfi -i sine=duration=3 -c:a flac       in/tone.flac
& $FF -y -f lavfi -i sine=duration=3 -c:a libopus    in/tone.opus
& $FF -y -f lavfi -i sine=duration=3 -c:a libvorbis  in/tone.ogg
& $FF -y -f lavfi -i sine=duration=3 -c:a pcm_s16le  in/tone.wav
& $FF -y -f lavfi -i testsrc=size=320x240:rate=10:duration=3 -f lavfi -i sine=duration=3 -c:v libx264 -c:a aac in/clip.mp4
& $FF -y -f lavfi -i color=c=red:size=200x200:d=1 -frames:v 1 in/cover.png
& $FF -y -i in/tone.mp3 -i in/cover.png -map 0:a -map 1:v -c copy -disposition:v:0 attached_pic in/art.mp3
```

- [ ] Each of the six targets converts a real source and the result plays.
- [ ] `--to mp3 in out` converts the seven conversion sources (the six tones and
      `clip.mp4`), names every re-encode it performed, and exits 0. `art.mp3` is a
      conversion source too and is covered by its own item below; `cover.png` is
      not a source at all -- keep it outside `in/`, or expect the image phase to
      claim it later.
- [ ] A stream copy really is a copy: `--to opus` from `tone.opus` finishes
      near-instantly and the audio stream is packet-identical —
      `& $FF -i out/tone.opus -map 0:a -c copy -f md5 -` matches the same command
      on the source. Compare the stream, not the file: a remux re-pages the
      container.
- [ ] `--to flac in out` over `tone.wav` produces a playable FLAC via the
      `last_resort`, not a failure.
- [ ] A second run over any converted tree reports `0 converted`, exit 0.
- [ ] `art.mp3` under `--to mp3`: `ffprobe` the output and confirm the picture
      stream is gone, and that the run says what the gate's decision says it
      says. Repeat for `--to ogg`, where the muxer rejects the picture and the
      ladder is reached instead.
- [ ] `--to mp3` on `clip.mp4` rips the audio and names the dropped video stream.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| A profile turns out to need an engine change, quietly breaking the phase's headline outcome | The per-PR diff check is a Verification item. A profile that cannot be expressed as data is escalated as `needs:planning` |
| A copy mask is wrong and a stream copy produces a file that does not play | The masks are verified against ffmpeg 9 in the table above, and the QA gate plays one output per target |
| The muxer facts are re-derived wrongly by a later reader | They are written down as a table with the consequence beside each, and the QA gate re-exercises them |
| The fallback defaults age badly, or someone treats them as a tuning surface | Pinned by the argv tests, so changing one is a visible, argued diff |
| The two deferred candidates (disposition, lossiness) are forgotten | Named in the spec with what each actually costs, so a roadmap cycle can pick them up |
| The curated suffix set misses a format people actually have | Enumerated in Scope rather than left to taste, and the QA gate points the tool at a directory holding all seven source kinds |

## Decision log

- 2026-08-25: No design artifact for this phase. The ladder and the per-stream
  branch are already drawn; a fourth diagram restating them would be the drift
  `docs/design.md` warns about.
- 2026-08-25: Spec review ran the installed ffmpeg against every proposed mask.
  Three of the planned decisions were wrong: `m4a` uses the `ipod` muxer with a
  narrower accept set than MP4's, `ogg`/`opus` reject a picture stream outright
  rather than handling it awkwardly, and a blind video map into `mp3` silently
  truncates a real video to one frame. The masks and the cheap attempt were
  rewritten around the measured behaviour.
- 2026-08-25: Cover art and generation-loss notes were both dropped from the
  phase once the review showed neither is expressible in the implemented value
  types. They are recorded as roadmap candidates with their real cost — an engine
  change — rather than being smuggled in as "just a profile field".
- 2026-08-25: Spec review built the proposed FLAC profile against the real engine
  and ran it: a PCM stream yields `selective` then `re-encode`, so the selective
  rung is what rescues `--to flac` from a WAV source, not the `last_resort`. The
  `last_resort` is kept for the case the rung cannot cover — a mask hit whose
  bitstream the muxer then refuses — and the Verification item was corrected to
  assert the rung the engine actually reaches.
- 2026-08-25: Spec review measured that a blind `-c:a copy` lets the muxer, not
  the copy mask, decide the happy path — `--to opus` from a Vorbis source shipped
  a `.opus` file containing Vorbis at exit 0. The cheap attempts are now per
  profile, and `opus` forces its encoder rather than copying.

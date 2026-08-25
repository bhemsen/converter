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
| The `ogg` and `opus` muxers **reject** a picture stream outright (`Unsupported codec id in stream 1`), and the `wav` muxer rejects any video stream | Not "awkward support" — a hard failure. It is not enough on its own to justify mapping video, though: see the theora row below for why `ogg` still cannot |
| `mp3`, `m4a` (ipod) and `flac` **accept** a picture stream that already carries the `attached_pic` disposition. A **bare** mjpeg is a different case: `m4a` rejects it, `mp3` silently writes it as a single frame | These three cannot map video safely, so they map audio only |
| `m4a` (ipod) copies a **full h264 track** through without complaint: `clip.mkv` under `-map 0:a? -map 0:v? -c copy` exits 0 with `0\|aac 1\|h264` | The decisive reason `m4a` maps no video: the user asked for audio and would get a video file |
| The `opus` muxer accepts a **Vorbis** stream | A blind copy into `.opus` can ship a file whose extension lies about its contents -- the second open decision below |
| The `flac` muxer enforces exactly one FLAC audio stream, like `mp3` | `stream_limit=1` is a muxer constraint there too |
| The `flac` muxer accepts an `attached_pic` picture but **silently discards a real video stream at exit 0**, warning only on stderr | Worse than a rejection: there is no failure to fall into the ladder, so `flac` maps audio only and stays in the open decision |
| The `ogg` muxer's own video codec is **theora**, so a theora+vorbis source copies straight through: exit 0, output byte-identical in size to the input | `ogg` cannot map video either -- it would hand the user a video file they asked to have as audio, the same defect that rules `m4a` out |
| The `opus` muxer holds **several** audio streams, by copy and by encode | `opus` declares no `stream_limit` |
| `-q:a 2` (libmp3lame) and `-q:a 5` (libvorbis) are valid | The fallback defaults below are real |

### Decisions

| Decision | Rationale | Date |
|---|---|---|
| **On the happy path the muxer is the authority, not the copy mask.** A stream copy that ffmpeg's muxer accepts ships, whether or not the mask lists that codec; the mask governs the *failure* path, where the engine builds the selective rung | Measured, not assumed: `--to opus` from a Vorbis `.ogg` under a blind `-c:a copy` exits 0 and writes a `.opus` file containing Vorbis. Nothing short of a probe can prevent that, and a probe on the happy path is forbidden. The per-profile cheap attempts below are chosen so that where the muxer is looser than the format's identity, the profile does not rely on a copy at all | 2026-08-25 |
| The `cheap_attempt`, `explicit_streams` and `last_resort` of each of the **five new** profiles are fixed by the table below; `wav` is untouched and keeps phase 2's shape exactly | A blanket rule does not survive contact with the muxers: they differ in whether they enforce the target's codec, whether they hold several audio streams, and whether they reject a picture stream. Each of those differences changes what an honest cheap attempt looks like | 2026-08-25 |
| `stream_limit=1` for `mp3` and `flac` only. `m4a`, `ogg` and `opus` declare **no** audio stream limit | Measured: the `mp3` and `flac` muxers both enforce exactly one audio stream, so the limit is real and a multi-stream source fails into the ladder, which names the stream it drops. `m4a`, `ogg` and `opus` accept several, so declaring a limit would mean mapping one stream and silently discarding the rest — a loss the tool could not name. Carrying every stream the container holds drops nothing at all, which is the better answer | 2026-08-25 |
| OPEN — does `opus` copy or always encode? | resolved at the spec-acceptance gate, together with the standing-note decision; see the note below | — |
| **Only `opus` maps video** in its cheap attempt. `mp3`, `m4a`, `flac` and `ogg` map audio only | Mapping video is worth it exactly where it turns a quiet loss into a *failure* the ladder can name. Measured, that is true only for `opus`: its cheap attempt carries no `-c:v`, so ffmpeg cannot select a video encoder and errors out, the ladder runs, and the picture stream is named. Every other target has a measured way to swallow video quietly — `m4a` copies a full h264 track through, `ogg` copies theora through (theora is the ogg muxer's own video codec, so a theora source arrives as a whole video file renamed `.ogg`), `flac` discards real video at exit 0 with only a stderr warning, and `mp3` writes a real video as a single frame. For those four, mapping video buys a silent wrong result instead of a note | 2026-08-25 |
| `opus`'s `accept_options` is `flags("-c:a copy")`: the cheap attempt never copies, but the **selective rung does**, on a mask hit | "`opus` does not copy" is a statement about the cheap attempt alone. Following WAV's `accept_options=()` precedent here would emit a map with no codec option and produce an undeclared re-encode | 2026-08-25 |
| The happy-path muxer-authority row is a problem only for a **codec-defined** target, where the extension names the codec. `.opus`, `.mp3` and `.flac` are codec-defined; `.m4a` and `.ogg` are container-defined, so an `.m4a` holding `ac3` (measured: it copies through, outside the declared mask) is unusual but not a lie | This is the criterion that exempts `m4a` and `ogg` from the treatment `opus` gets, and it stops `{aac, alac}` from being read later as a guarantee | 2026-08-25 |
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
| `ogg` | `-map 0:a? -c copy` | False | none | `-map 0:a:0 -c:a libvorbis -q:a 5` |
| `opus` | per the second open decision | False | none | `-map 0:a:0 -c:a libopus -b:a 128k` |

`explicit_streams` is `False` throughout: every cheap attempt above selects by
type rather than by index, so the selective rung is never suppressed.

Both questions this table originally left open were measured during review and
are now rows in the muxer table above: `flac` does **not** reject real video — it
discards it at exit 0 — so `flac` maps audio only and stays in the open decision;
and `opus` does hold several audio streams, so it declares no `stream_limit`.
Nothing here is left for the implementer to determine.

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

### The second open decision: does `opus` copy?

Decided with the first, because both are the same question — how much may the
happy path lose in exchange for not probing — and because option 1 above already
accepts a standing note as a mechanism.

The `opus` muxer accepts a Vorbis stream (measured), and `.opus` is a
codec-defined format, so a plain copy can ship a file whose extension lies about
its contents. Forcing `libopus` fixes that and costs a re-encode of every source
that was *already* Opus: measured, `tone.opus` grows 18 445 -> 37 356 bytes and
its packets change. That is a real generation loss the tool inflicted, on the
common case, to prevent a mislabel only reachable by pointing `--to opus` at a
`.ogg`/`.oga` file.

1. **`opus` copies** (`-map 0:a? -c copy`). No generation loss, fast, and the
   mask governs the selective rung as everywhere else. A Vorbis source is copied
   into a file called `.opus`, reported as converted — the tool's only mislabel.
2. **`opus` always encodes** (`-map 0:a? -map 0:v? -c:a libopus -b:a 128k`) with a
   standing note saying the audio was re-encoded. The extension never lies, and
   the mapped video is what makes a cover-art source fail into the ladder and get
   a real note — the only target where that works. Every already-Opus file pays a
   transcode.

Picking 1 also removes `opus` from the video-mapping group, so no target maps
video and all five join the first decision's group. Picking 2 keeps `opus` as the
one target whose cover-art loss is named properly.

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
      a non-copyable one. Nine or ten tests depending on the `opus` decision: if
      `opus` always encodes it has no happy-path copyable case, the same exception
      `spec-profile-registry.md` recorded for WAV's empty mask, and its copy is
      reachable only on the selective rung.
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
- [ ] A stream copy really is a copy: `--to mp3` from `tone.mp3` finishes
      near-instantly and the audio stream is packet-identical --
      `& $FF -i out/tone.mp3 -map 0:a -c copy -f md5 -` matches the same command
      on the source. Compare the stream, not the file: a remux re-pages the
      container. Aimed at `mp3` rather than `opus`, since whether `opus` copies at
      all is one of the gate decisions.
- [ ] `--to flac in out` over `tone.wav` produces a playable FLAC via the
      **selective** rung, not a failure -- the same rung the machine check names,
      verified against the real engine.
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
- 2026-08-25: Spec review measured that mapping video into `ogg` passes a theora
  source straight through at exit 0 — a whole video file renamed `.ogg`, the same
  defect that rules `m4a` out. `ogg` no longer maps video, which leaves `opus` as
  the only target where a cover-art loss can be named, and only if the gate has
  it encode rather than copy.
- 2026-08-25: Spec review measured that `flac` does not reject a real video
  stream — it discards it at exit 0 with only a stderr warning, which the
  constitution forbids parsing. Silent discard is worse than rejection, so `flac`
  maps audio only.
- 2026-08-25: The `opus` copy-or-encode question was promoted out of a decision
  row into the gate, next to the standing-note decision. Settling it in a row
  traded a generation loss on the common case for a mislabel on a rare one, and
  presented the loss as a warning the source "deserved" — the tool inflicts it.

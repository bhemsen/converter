# Spec: stream-disposition (roadmap phase 6)

> Created: 2026-08-26

Carry an embedded cover picture through the audio conversions whose muxers hold
one, by mapping **only** attached pictures rather than video in general — and
retire the standing notes that a partial-mapping verification has since made
redundant. This spec carries no lifecycle state — acceptance is the spec merged
on the default branch with a milestone and issues, and all progress lives in the
GitHub issues and milestone. A completed spec is moved to `docs/specs/archive/`.

**Depends on milestone #3 (audio-formats), which is complete.** It revisits the
`mp3`, `m4a` and `flac` profiles phase 3 created.

## Why this phase changed shape twice before it was drafted

`docs/roadmap.md` seeded this phase as "the engine cannot name what it dropped".
That half was already solved by issue #18's fix (`1183a09`), which narrowed the
constitution's probe rule and added `jobs.verify_success`: a profile declaring
`partial_mapping=True` is probed once on success and names each unmapped stream,
per stream. So the remaining work is *carrying* artwork, not reporting it.

The first draft then proposed mapping video blindly (`-map 0:v?`) and using the
disposition to sort it out afterwards. The review falsified that: **the ipod
muxer accepts h264**, so `--to m4a` over an ordinary video would have shipped the
whole video renamed `.m4a` at exit 0 *and* printed a drop that never happened.
Measured, `-map 0:a? -map 0:v? -c copy` on an h264+aac source yields
`0,aac,audio,88` and `1,h264,video,20`.

The fix is not to sort it out afterwards but never to map it: ffmpeg has a
**disposition stream specifier**, and it does exactly what this phase needs.

## Outcome

- [ ] `mp3`, `m4a` and `flac` carry an embedded cover picture through a
      conversion instead of dropping it.
- [ ] A real video stream is **never mapped** into an audio target — not
      dropped-after-mapping, not truncated, not passed through. Measured on
      h264 into `m4a`, the case the first draft got wrong.
- [ ] `Stream` carries whether a stream is an attached picture, and
      `probe_streams` fills it from the same single ffprobe call it already makes.
- [ ] A carried picture is **not** reported as dropped, and a real video stream
      still is.
- [ ] The five audio profiles' cheap-attempt standing notes are gone, and nothing
      they said is lost: every claim is made per stream by `jobs.verify_success`,
      or is no longer true. `last_resort` notes are untouched.
- [ ] `ogg`, `opus` and `wav` are byte-for-byte unchanged in argv, and unchanged
      in notes except for the standing note this phase removes from `ogg` and
      `opus`.
- [ ] `ffprobe` still runs at most once per file.

## Scope

### In scope

- `converter/ffmpegtool.py`: an `attached_pic` field on `Stream`, the
  `stream_disposition=attached_pic` clause in `probe_streams`' existing query,
  and the nested-JSON read that goes with it.
- `converter/jobs.py`: resolving a stream to its rule by disposition as well as
  type, so an attached picture has its own rule.
- `converter/profiles.py`: an `attached_pic` rule on `mp3`, `m4a` and `flac`,
  their cheap attempts gaining `-map 0:disp:attached_pic?`, and the removal of
  the five cheap-attempt standing notes.
- `tests/test_profiles.py`: `MAP_LETTERS` / `mapped_types` learn the disposition
  selector, so the mapped-types-equals-rules invariant keeps holding.
- **`docs/design/stream-decision.md` and `docs/architecture.md` Key flow 2**,
  amended in this PR — the foundation impact `docs/roadmap.md` recorded for this
  phase, which `docs/workflow.md` binds to be authored here.
- The tests for all of it.

### Out of scope

- Video and image targets. `mkv` carries attachments by `codec_type`, and an
  image target's whole content is the picture.
- Any other disposition (`default`, `forced`, `comment`). Only `attached_pic` has
  a decision resting on it.
- **Writing** a disposition. This phase carries an existing picture through; it
  never marks a stream as artwork that was not already marked.
- Extracting cover art to a file, or embedding art from one.
- `ogg`, `opus` and `wav` gaining artwork — measured, all three reject a picture
  outright even with an accepted audio codec.
- The `wav` and `mp4` standing-note holes phases 3 and 4 left open — those are
  about a stream type never being mapped at all.
- `last_resort` notes. They stay: that rung maps `-map 0:a:0` explicitly and is
  never verified (`docs/design/degradation-ladder.md`), so its note is the only
  place that information exists.

## Constraints

- `ffprobe` runs at most once per file, and never on the happy path of an
  exhaustive cheap attempt (`docs/constitution.md`, as narrowed by #18).
- Value types are frozen dataclasses; every parameter and return annotated.
- A target format is data, not code.
- Never report success for a conversion that silently dropped something — and,
  its mirror, never announce a drop that did not happen.
- The test suite keeps passing with no ffmpeg installed.

## Prior art

- [Cover art and stream disposition (Phase 6)](../prior-art.md#cover-art-and-stream-disposition-phase-6)
  — the concern seeded for this phase. beets' `convert` plugin is the **stance**
  to adopt: artwork is a first-class, default-on concern of a conversion pipeline
  (`embed: yes`), not an incidental stream. Its **mechanism** is the AVOID — it
  embeds through a tag library, a second runtime dependency here. The ffprobe
  entry's AVOID is what this phase closes: never infer artwork from the codec
  name, since `mjpeg` and `png` are the codecs of both a cover picture and a real
  video.
- That concern's own AVOID says the standing note "**narrows** rather than
  disappears", and `docs/roadmap.md`'s phase-6 row says the same. **This spec
  overrides both**, on evidence neither had: the verifier added by #18 already
  makes every statement those notes make, per stream and accurately, so a
  narrowed note would still be a blanket line duplicating an exact one. The
  override is named here rather than left as a silent divergence.

## Design

Both foundation edits are authored in this PR, not deferred:

- `docs/design/stream-decision.md` gains one node — "is this stream an attached
  picture, and does the profile declare a rule for one?" — ahead of the type
  lookup.
- `docs/architecture.md` Key flow 2 gains the same clause, since it restates the
  per-stream match in prose.

## Human prerequisites

- none.

## Prior decisions

### The measured facts these decisions rest on

Measured against ffmpeg 9.0; the first draft's table was falsified by review and
this one is rebuilt from what survived plus what the review found.

| Fact | Consequence |
|---|---|
| **ffmpeg has a disposition stream specifier.** `-map 0:disp:attached_pic?` maps embedded pictures and nothing else. Measured: an MP3-with-art source yields `0,mp3,audio,0` + `1,png,video,1`; an **h264** video source yields audio only; an h264+aac source into `m4a` yields audio only | This is the phase's mechanism. The cheap attempt never sees a real video stream, so none of the pass-through hazards below can arise |
| **The ipod muxer accepts h264.** `-map 0:a? -map 0:v? -c copy` on h264+aac into `.m4a` exits 0 and writes `1,h264,video,20` — a whole video renamed `.m4a`, with `verify_success` printing a drop that did not happen | Why the first draft's blind `-map 0:v?` is rejected outright. The same defect `converter/profiles.py`'s OGG comment already records |
| `mp3` writes a real **mjpeg** video as exactly one packet with `attached_pic=1` (source had 20), and rejects **h264** (`No mimetype is known for stream 1`) | The other half of the same hazard: blind mapping is unsafe per target in different ways |
| `flac` accepts a real mjpeg at exit 0 and discards it entirely | The third variant. Three targets, three different wrong answers — hence: map neither, map only pictures |
| **Artwork survives a mapped copy** into `mp3`, `m4a` and `flac` with disposition intact, for **png and mjpeg** — the two artwork codecs that matter | The carry-through works once the mapping is precise |
| One ffprobe query returns the disposition alongside the existing fields, but under `-of json` it is **nested**: `{"index":1,"codec_name":"png","codec_type":"video","disposition":{"attached_pic":1}}` | No second probe, but the parser change is a nested lookup plus a default for a stream reporting no `disposition` object — not "one clause" |
| `ogg`, `opus` and `wav` reject a picture outright even with an accepted audio codec (`Unsupported codec id in stream 1`; `wav muxer does not support any stream of type video`) | Those three gain no rule and no mapping, and stay unchanged |
| `tests/test_profiles.py` binds `set(profile.rules)` to `mapped_types(profile)`, whose `MAP_LETTERS` covers `v/a/s/t/d` only | The invariant is not an obstacle here — it is the reason the design works. See the rules-key decision |

### Decisions

| Decision | Rationale | Date |
|---|---|---|
| The cheap attempt of `mp3`, `m4a` and `flac` gains **`-map 0:disp:attached_pic?`**, never `-map 0:v?` | Measured: it maps pictures and nothing else, on all three targets, including the h264 cases that break a blind map. The `?` keeps a source without artwork exiting 0 | 2026-08-26 |
| `Stream` gains one boolean field, `attached_pic`, not a general disposition set | Only this disposition has a decision resting on it. The field is needed even though ffmpeg does the mapping: the success-side verifier must not report a *carried* picture as dropped, and the selective rung maps by index and so has no specifier to lean on | 2026-08-26 |
| An attached picture resolves to an **`"attached_pic"` key in `profile.rules`**, falling back to `stream.codec_type` when the profile declares none | It lines up with the mapping rather than fighting it: the cheap attempt now maps attached pictures as their own thing, so a rule for them is exactly what the mapped-types-equals-rules invariant demands. `MAP_LETTERS` / `mapped_types` learn `disp:attached_pic -> "attached_pic"`, which is a one-entry extension, not an exemption | 2026-08-26 |
| A profile with **no** `attached_pic` rule keeps today's behaviour exactly: the picture falls through to the `video` lookup, finds no rule, and is dropped with the existing note | This phase must not change a target nobody asked it to change. `ogg`, `opus` and `wav` are the guard | 2026-08-26 |
| The `attached_pic` rule copies unconditionally — accept-anything mask, `accept_options=flags("-c:v copy")` for `mp3` and `flac`, `flags("-c:v:{n} copy")` for `m4a` | The decision is the disposition, not the codec, so enumerating codec names would repeat the phase-4 mistake the attachment rule corrected. The `{n}` split follows the existing per-profile convention: `mp3` and `flac` are stream-limited to one, `m4a` is not | 2026-08-26 |
| The engine counts a carried picture under **`"video"`**, not `"attached_pic"` | ffmpeg counts an attached picture as a video output stream, so `{n}` must stay in step with ffmpeg's own numbering. Irrelevant for the three audio targets, which declare no `video` rule, and a latent bug for any later profile with both | 2026-08-26 |
| `describe_unsupported` stays keyed on `codec_type` deliberately, and is pinned by a test | Its question is "does this source carry any stream type the profile could use", which a disposition does not change. Measured: a standalone `.png` reports `attached_pic=0`, so it stays a genuine `unsupported` | 2026-08-26 |
| **The cheap-attempt standing notes are removed from the five audio profiles that carry one** — `mp3`, `flac`, `m4a`, `ogg`, `opus`. `wav` carries none | Measured: the verifier already names every stream those notes describe, per stream and accurately, so the blanket line is duplication. For `mp3`, `m4a` and `flac` it also becomes false the moment artwork is carried. `ogg` and `opus` gain no artwork, so their removal rests on the duplication argument alone | 2026-08-26 |
| `last_resort` notes are **retained** on every profile | That rung maps `-map 0:a:0` explicitly and is never verified (`docs/design/degradation-ladder.md`: only the cheap attempt's notes are added to), so its note is the only place that information exists. Removing it would lose a statement | 2026-08-26 |
| Genuinely open decisions: **none**. The first draft's open decision — which targets map video, given a per-target hazard — was dissolved by the disposition specifier rather than resolved | Recorded so the gate is a deliberate "the measurement removed the question", not an omission | 2026-08-26 |

## Tracking

- Milestone: stream-disposition (created at the spec-acceptance gate)
- Issues: created from this spec once it is merged (one per implementable step)

## Verification

Machine checks:

- [ ] Verify passes (ruff check, ruff format --check, pytest) on the merge commit.
- [ ] A test that `probe_streams` fills `attached_pic` from a stubbed ffprobe
      **JSON** payload with the nested `disposition` object, true for a picture,
      false for a plain video, and false for a stream carrying no `disposition`
      object at all.
- [ ] A test that the probe still makes exactly **one** ffprobe call per file,
      with its `-show_entries` argument pinned verbatim — a wrong clause fails
      silently rather than loudly.
- [ ] A test that a stream with `attached_pic` resolves to the `attached_pic`
      rule when the profile declares one, and to the `video` rule when it does
      not.
- [ ] A test that `describe_unsupported` is unchanged for every profile,
      including the three that gain a rule.
- [ ] Per target that gains artwork: the cheap attempt's argv pinned, and a test
      that a picture stream is accepted while a **non-picture video stream of the
      same codec** is dropped with a note — the distinction the whole phase is for.
- [ ] A test that `verify_success` does **not** report a carried picture as
      dropped, for each of the three targets.
- [ ] A test that `ogg`, `opus` and `wav` are byte-for-byte unchanged in argv,
      and unchanged in notes apart from the removed standing note.
- [ ] A test that no audio profile carries a **`cheap_attempt`** standing note,
      and a test per removed note that the verifier still names the same loss per
      stream. `last_resort.notes` are asserted unchanged.
- [ ] The `mapped_types` invariant in `tests/test_profiles.py` holds for all 17
      profiles with the disposition selector recognised.

Human milestone-QA gate. `$FF` is the absolute ffmpeg path from *This machine*.
Every fixture has a **distinct stem**, so a single `--to <fmt> in out` run does
not collide (`docs/specs/spec-image-formats.md` and commit `a6b1342` record why):

```text
New-Item -ItemType Directory -Force in
& $FF -y -f lavfi -i color=c=blue:size=200x200:d=1 -frames:v 1 cover.png
& $FF -y -f lavfi -i sine=duration=2 -c:a libmp3lame in/tone-mp3.mp3
& $FF -y -i in/tone-mp3.mp3 -i cover.png -map 0:a -map 1:v -c copy -disposition:v:0 attached_pic in/art-mp3.mp3
& $FF -y -f lavfi -i sine=duration=2 -c:a aac in/tone-m4a.m4a
& $FF -y -i in/tone-m4a.m4a -i cover.png -map 0:a -map 1:v -c copy -disposition:v:0 attached_pic in/art-m4a.m4a
& $FF -y -f lavfi -i sine=duration=2 -c:a flac in/tone-flac.flac
& $FF -y -i in/tone-flac.flac -i cover.png -map 0:a -map 1:v -c copy -disposition:v:0 attached_pic in/art-flac.flac
& $FF -y -f lavfi -i testsrc=size=160x120:rate=10:duration=2 -f lavfi -i sine=duration=2 -c:v libx264 -c:a aac in/vid-h264.mkv
& $FF -y -f lavfi -i testsrc=size=160x120:rate=10:duration=2 -f lavfi -i sine=duration=2 -c:v mjpeg -c:a libmp3lame in/vid-mjpeg.mkv
```

- [ ] `--to mp3 in out`, `--to m4a in out` and `--to flac in out`: each `art-*`
      fixture keeps its picture — `ffprobe` the output and confirm the stream is
      present **and** still carries `attached_pic=1`.
- [ ] **The selective-rung case**, which is the motivating one: `art-flac.flac`
      under `--to mp3` needs an audio re-encode, so the cheap attempt fails and
      the ladder runs. The picture must still arrive with `attached_pic=1`.
- [ ] `vid-h264.mkv` and `vid-mjpeg.mkv` under `--to m4a` and `--to mp3`: the
      output holds **audio only**, and the run names the dropped video stream.
      This is the regression the first draft would have shipped.
- [ ] `tone-mp3.mp3` (no artwork) converts and prints **no** note at all. This is
      what the standing-note removal buys, and the change a user notices first.
- [ ] `--to ogg` and `--to wav` over `art-mp3.mp3` behave exactly as on the
      previous commit apart from the removed standing note.
- [ ] A second run over any converted tree reports `0 converted`, exit 0.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| The disposition specifier is unavailable on an older ffmpeg than this machine's 9.0, and the cheap attempt fails for everyone on it | The review is asked to establish the version floor. If it is above what the project can assume, the fallback is to carry artwork only on the selective rung, which needs no specifier — a smaller win, not a broken one |
| A real video is passed through or truncated into an audio target | The specifier maps only pictures, pinned per target by argv tests and by a QA check on both an h264 and an mjpeg video source |
| Removing the standing notes loses a statement | A test per removed note asserts the verifier still names that loss per stream; `last_resort` notes are explicitly retained and asserted unchanged |
| The `-show_entries` clause or the nested JSON read breaks and the field silently reads false | Both pinned: the argv verbatim, and the parse against a payload with and without a `disposition` object |
| A target that gains no rule changes behaviour | `ogg`, `opus` and `wav` pinned byte-for-byte on argv, and on notes minus the removed standing note |

## Decision log

- 2026-08-26: Re-scoped before drafting. The seeded framing — "the engine cannot
  name what it dropped" — was overtaken by issue #18's fix, which added a
  success-side verifier. What remains is carrying artwork, plus retiring the
  phase-3 standing notes the verifier made redundant.
- 2026-08-26: The first draft proposed mapping video blindly and sorting it out
  with the disposition afterwards. Review falsified it on the measurement that
  mattered most: the ipod muxer accepts h264, so `--to m4a` would have shipped a
  whole video renamed `.m4a` at exit 0 with a false drop note. The first draft
  had measured only mjpeg.
- 2026-08-26: Replaced by `-map 0:disp:attached_pic?`, measured to map pictures
  and nothing else on all three targets. That dissolved the phase's open decision
  rather than answering it — there is no longer a per-target trade to make.
- 2026-08-26: The override of `docs/prior-art.md`'s and `docs/roadmap.md`'s
  "the note narrows rather than disappears" is named in Prior art, with the
  evidence neither had: the verifier makes every statement those notes make.

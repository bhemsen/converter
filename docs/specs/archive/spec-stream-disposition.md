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
      or is no longer true. `last_resort` notes are retained on every profile —
      none is retired or newly added; issue #67 reworded exactly one, `gif`'s,
      from an action claim to a fact claim (the same fix it gave that profile's
      `cheap_attempt` note), which is not a regression against this bullet.
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
- `tests/test_profiles.py`: `MAP_LETTERS` and `mapped_types` learn the disposition
  selector and classify it as **blind**, and `named_index_counts` skips it -- three
  shipped invariants, of which one currently fails against the new shape.
- `docs/constitution.md` and `README.md`: the ffmpeg version floor, per the gate's
  decision, and `docs/roadmap.md`'s "constitution -- none" verdict corrected.
- **`docs/design/stream-decision.md`, `docs/design/degradation-ladder.md` and
  `docs/architecture.md` Key flow 2**, amended in this PR — the foundation impact `docs/roadmap.md` recorded for this
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

- [Cover art and stream disposition (Phase 6)](../../prior-art.md#cover-art-and-stream-disposition-phase-6)
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

Three foundation edits are authored in this PR, not deferred:

- `docs/design/stream-decision.md` gains one node — "is this stream an attached
  picture, and does the profile declare a rule for one?" — ahead of the type
  lookup.
- `docs/architecture.md` Key flow 2 gains the same clause, since it restates the
  per-stream match in prose.
- `docs/design/degradation-ladder.md` gains the third selector kind -- a blind
  selector over a disposition -- because its `stream_limit` reasoning is built on
  a two-way blind-versus-index-named split that no longer covers every case.

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
| **The disposition specifier arrived in ffmpeg 7.1** ("stream specifiers in fftools can now match by stream disposition", `Changelog` under `version 7.1:`, absent from every earlier heading). Ubuntu 24.04 LTS ships 6.1.1 and Debian 12 ships 5.1.9 -- both below it | A new runtime floor the project does not currently state anywhere. `README.md` tells Linux users `sudo apt install ffmpeg`, which lands under the floor on both |
| **Below 7.1 the `?` does not save the invocation.** An unknown disposition specifier makes ffmpeg refuse the option and abort: `Invalid disposition specifier` / `Failed to set value ... for option 'map'` / `Error opening output files`, exit 127 | The cheap attempt fails for *every* file on the three targets, not just artwork-bearing ones. It degrades rather than breaks -- the selective rung maps by index and needs no specifier -- at one failed ffmpeg process plus one probe per file |
| **One `-map 0:disp:attached_pic?` carries *every* picture, not one.** Measured on a two-picture source into all three targets: `1,png,video,1` and `2,mjpeg,video,1` both arrive | The selector is **blind**, not index-named. Declaring `stream_limit=1` on the rule would make `verify_success` report the second picture as dropped while ffmpeg carried it |
| A source with **no** artwork exits 0 on all three targets under the same cheap attempt, carrying audio only | The trailing `?` is load-bearing and works; the majority case is unaffected |
| `tests/test_profiles.py` binds `set(profile.rules)` to `mapped_types(profile)` **and** binds a stream limit to `named_index_counts`, which reads `0:disp:attached_pic?` as index-named | Two of the three invariants hold as-is; the third fails and must be taught the new selector kind. See the rules-key decision |

### Decisions

| Decision | Rationale | Date |
|---|---|---|
| The cheap attempt of `mp3`, `m4a` and `flac` becomes exactly `flags("-map 0:a? -map 0:disp:attached_pic? -c copy")` -- **`-c:a copy` becomes `-c copy`**, which is a second argv change beyond adding the map | Measured: the specifier maps pictures and nothing else on all three targets, including the h264 cases that break a blind map, and the `?` keeps a source without artwork exiting 0. But with `-c:a copy` retained, no codec option covers the picture, so ffmpeg re-encodes it with the muxer's default video encoder -- h264 for ipod, which ipod then rejects, failing every artwork-bearing `--to m4a` at rung 1. `mp3` and `flac` exit 0 and silently re-encode the picture. With `-c copy` all three copy it | 2026-08-26 |
| `Stream` gains one boolean field, `attached_pic`, not a general disposition set | Only this disposition has a decision resting on it. The field is needed even though ffmpeg does the mapping: the success-side verifier must not report a *carried* picture as dropped, and the selective rung maps by index and so has no specifier to lean on | 2026-08-26 |
| An attached picture resolves to an **`"attached_pic"` key in `profile.rules`**, falling back to `stream.codec_type` when the profile declares none | It lines up with the mapping rather than fighting it: the cheap attempt now maps attached pictures as their own thing, so a rule for them is exactly what the mapped-types-equals-rules invariant demands. Two of the three shipped invariants then hold unchanged. The third does not: `named_index_counts` reads `0:disp:attached_pic?` as index-named and would demand `stream_limit=1` -- and measured, one such map carries *every* picture, so that limit would make `verify_success` report a carried picture as dropped. `named_index_counts` must skip the `disp:` form and `mapped_types` must classify it as **blind** | 2026-08-26 |
| The `attached_pic` rule declares **no** `stream_limit` | Measured: a two-picture source arrives whole on all three targets. A limit of 1 would be a false statement about ffmpeg's behaviour and would produce a drop note for a stream that was carried -- the mirror this spec's Constraints forbid | 2026-08-26 |
| `docs/design/degradation-ladder.md`'s blind-versus-index-named dichotomy gains a **third selector kind**: a blind selector over a disposition. Authored in this PR | That file's whole `stream_limit` reasoning is built on the two-way split, so leaving it out would make the shipped invariant and the design contract disagree | 2026-08-26 |
| The engine needs **no change for counting**: `_decide_stream` already writes `counts[stream.codec_type]`, and a picture's `codec_type` is `video` | Verified against the real engine: a two-picture m4a selective rung emits `-c:v:0 copy -c:v:1 copy` and both pictures arrive with `attached_pic=1`. The do-nothing option is also the correct one | 2026-08-26 |
| A profile with **no** `attached_pic` rule keeps today's behaviour exactly: the picture falls through to the `video` lookup, finds no rule, and is dropped with the existing note | This phase must not change a target nobody asked it to change. `ogg`, `opus` and `wav` are the guard | 2026-08-26 |
| The `attached_pic` rule copies unconditionally — accept-anything mask, `accept_options=flags("-c:v:{n} copy")` on all three | The decision is the disposition, not the codec, so enumerating codec names would repeat the phase-4 mistake the attachment rule corrected. The placeholder form is used uniformly because the rule declares no `stream_limit` -- `StreamRule`'s bare-specifier convention is keyed on a limit of 1, which belongs to these profiles' *audio* rule, not this one | 2026-08-26 |
| The engine counts a carried picture under **`"video"`**, not `"attached_pic"` | ffmpeg counts an attached picture as a video output stream, so `{n}` must stay in step with ffmpeg's own numbering. Irrelevant for the three audio targets, which declare no `video` rule, and a latent bug for any later profile with both | 2026-08-26 |
| `describe_unsupported` stays keyed on `codec_type` deliberately, and is pinned by a test | Its question is "does this source carry any stream type the profile could use", which a disposition does not change. Measured: a standalone `.png` reports `attached_pic=0`, so it stays a genuine `unsupported` | 2026-08-26 |
| **The cheap-attempt standing notes are removed from the five audio profiles that carry one** — `mp3`, `flac`, `m4a`, `ogg`, `opus`. `wav` carries none | Measured: the verifier already names every stream those notes describe, per stream and accurately, so the blanket line is duplication. For `mp3`, `m4a` and `flac` it also becomes false the moment artwork is carried. `ogg` and `opus` gain no artwork, so their removal rests on the duplication argument alone | 2026-08-26 |
| `last_resort` notes are **retained** on every profile | That rung maps `-map 0:a:0` explicitly and is never verified (`docs/design/degradation-ladder.md`: only the cheap attempt's notes are added to), so its note is the only place that information exists. Removing it would lose a statement | 2026-08-26 |
| The first draft's open decision -- which targets map video, given a per-target hazard -- was **dissolved** by the disposition specifier rather than resolved | Recorded so the gate is not asked a question the measurement removed | 2026-08-26 |
| **ffmpeg 7.1 is the floor for the fast path, not for correctness.** Older builds stay supported: below 7.1 the cheap attempt of `mp3`, `m4a` and `flac` fails per file and the ladder reaches the same result, artwork included | Resolved at the gate on 2026-08-27. The failure below the floor is a performance cost on three of seventeen targets, not a correctness one, and refusing at startup would stop the fourteen that never touch the specifier on the LTS distributions most Linux users run -- the opposite of the vision's "whatever ffmpeg can read". The wasted rung stays silent, which the ladder already guarantees: only the winning rung's notes are reported | 2026-08-27 |

### The ffmpeg-floor decision, in full (resolved at the gate)

The disposition specifier arrived in **ffmpeg 7.1**. The project states no ffmpeg
floor today -- `docs/constitution.md`'s tech-stack row names the CLI without a
version, and `README.md` says only "keep ffmpeg reasonably current" while telling
Linux users `sudo apt install ffmpeg`, which lands on 6.1.1 under Ubuntu 24.04 LTS
and 5.1.9 under Debian 12.

Measured, below the floor the trailing `?` does not help: ffmpeg refuses the
option and aborts the invocation. So on such a build the cheap attempt of `mp3`,
`m4a` and `flac` fails for **every** file. It degrades rather than breaks -- the
selective rung maps by index, needs no specifier, and carries the artwork just the
same -- but at one failed ffmpeg process plus one ffprobe per file, and every
conversion then reports through the failure-side path.

Whichever the gate picks, `docs/constitution.md` and `README.md` gain the floor
and join this PR's Scope, and `docs/roadmap.md`'s recorded verdict for this phase
("constitution -- none") becomes false and is corrected here. Those three edits are
authored **on this branch after the gate decides and before the merge** -- a
recorded foundation impact belongs to the plan PR (`docs/workflow.md`), not to an
implementation issue.

**Resolved at the gate on 2026-08-27: option 1.** `docs/constitution.md` and
`README.md` carry the floor as of this commit.

1. **Supported with degradation.** Record `ffmpeg >= 7.1` as the floor *for the
   fast path*, and state the cost below it plainly. Nothing breaks anywhere, and
   a user on Debian 12 still gets their artwork -- just one wasted process per
   file on three of the seventeen targets.
2. **Refused up front.** `resolve_tools` already fails fast for a missing binary
   and `ffmpegtool.version()` already exists, so a floor could be enforced at
   startup with an actionable message. But it would refuse *every* target,
   including the fourteen that never use the specifier, on the LTS distribution
   most Linux users are running. That is a large blast radius for a feature three
   targets use.

## Tracking

- Milestone: [stream-disposition](https://github.com/bhemsen/converter/milestone/6) (#6)
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
- [ ] The floor is stated in `docs/constitution.md` and `README.md`, and nowhere
      enforced: no startup check, no version parsing. A test asserting the three
      cheap attempts are unconditional -- the degradation must stay automatic.
- [ ] A test that `ogg`, `opus` and `wav` are byte-for-byte unchanged in argv,
      and unchanged in notes apart from the removed standing note.
- [ ] A test that no audio profile carries a **`cheap_attempt`** standing note,
      and a test per removed note that the verifier still names the same loss per
      stream. `last_resort.notes` are asserted unchanged.
- [ ] All three `tests/test_profiles.py` invariants hold for all 17 profiles with
      the disposition selector recognised -- including the stream-limit one, which
      fails against the new shape until `named_index_counts` skips the `disp:`
      form.
- [ ] A test that a **two-picture** source is carried whole and reported as no
      loss -- the case that decides the rule declares no `stream_limit`.

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
| A user below ffmpeg 7.1 pays a failed process plus a probe per file on three targets | Established: the floor is 7.1, the failure is a full abort rather than a skipped map, and the degradation is automatic rather than a fallback anyone implements. The gate decides whether that is supported or refused, and the floor is recorded in the constitution and the README either way |
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
- 2026-08-26: Review round 2 established the version floor this spec could not
  settle from one machine: the disposition specifier arrived in ffmpeg 7.1, and
  the LTS distributions most Linux users run ship below it. Promoted to the
  phase's one open decision, since it adds a runtime requirement the project has
  never stated and makes `docs/roadmap.md`'s "constitution — none" verdict false.
- 2026-08-26: Review round 2 also measured that one `-map 0:disp:attached_pic?`
  carries every picture, not one — so the rule declares no `stream_limit`, and
  `degradation-ladder.md`'s two-way selector split gains a third kind. Taking the
  failing invariant at face value and declaring `stream_limit=1` would have
  produced a drop note for a stream ffmpeg carried.
- 2026-08-26: And that adding only the map, keeping `-c:a copy`, breaks `m4a`
  outright: with no codec option covering the picture ffmpeg re-encodes it to the
  ipod muxer's default h264, which ipod then rejects. The cheap attempts are
  pinned in full rather than described as "gaining a map".
- 2026-08-27: Gate chose supported-with-degradation. The floor is recorded in the
  constitution and the README and enforced nowhere — below 7.1 the ladder does
  the work at one wasted process per file, which is a performance cost on three
  of seventeen targets rather than a correctness one. This also corrects
  `docs/roadmap.md`'s seeded "constitution — none" verdict for this phase, which
  the version floor made false.
- 2026-08-27: Issue #75 (`converter/ffmpegtool.py`) landed. `Stream` gained
  `attached_pic: bool = False` as its last field, and `probe_streams`'s
  `-show_entries` argument grew the `:stream_disposition=attached_pic` clause,
  still one ffprobe call per file. Verified against real ffprobe 9.0: an
  `art.mp3` fixture (audio + a `disposition:v:0 attached_pic` cover stream)
  reports `disposition: {"attached_pic": 1}` on the picture stream and `0` on
  the audio stream; a plain h264 `.mkv` and a plain `tone.mp3` both report `0`.
  Every payload ffprobe 9.0 actually returned carried the `disposition` object
  regardless of value once the entry was requested, so the "no `disposition`
  object at all" default is a defensive fallback for a payload shape this
  ffprobe version never produced, not one observed here — the parser handles it
  with `raw.get("disposition") or {}` regardless.
- 2026-08-27 (issue #76): `jobs._structural_drop` and `jobs._decide_stream` now
  resolve a stream's rule through one new helper, `jobs._rule_key`, rather than
  reading `profile.rules[stream.codec_type]` directly — it returns
  `"attached_pic"` when the stream carries that disposition *and* the profile
  declares such a rule, and `stream.codec_type` otherwise. `counts` stays keyed
  on `codec_type` throughout (unchanged), so a carried picture still shares its
  position counter with real video streams, matching ffmpeg's own output
  numbering. `describe_unsupported` was left untouched, as decided above.
  `Stream.attached_pic` (issue #75) had not landed on `main` while this issue's
  code and tests were written; the resolution logic and every new test were
  written against its documented shape (a boolean, added last, defaulted
  `False`) and proven correct with a duck-typed stand-in exercising the real,
  unmodified `converter.jobs` code, then re-proven against the real `Stream`
  type once #75 merged.
- 2026-08-27 (issue #77): `mp3`, `m4a` and `flac` gained the carry-through.
  Each cheap attempt is now exactly
  `flags("-map 0:a? -map 0:disp:attached_pic? -c copy")` — pinned in full per
  the Prior decisions row, including the `-c:a copy` → `-c copy` change that
  matters most for `m4a` (trap 1: the ipod muxer's default video encoder is
  h264, which ipod then rejects). Each profile gained an `attached_pic` rule
  reusing `_AcceptAnyCodec` (added for MKV's attachments, issue #38) rather
  than a second accept-anything mechanism: `copy_mask=_AcceptAnyCodec()`,
  `accept_options=flags("-c:v:{n} copy")`, no `stream_limit`. Cheap-attempt
  standing notes are left untouched — their removal is issue #78, which
  depends on this one, so they read as an over-broad statement between the
  two merges rather than a false one this issue is scoped to fix.
  `tests/test_profiles.py`'s `mapped_types` and `named_index_counts` learned
  the `0:disp:<qualifier>?` selector form via a new `DISPOSITION_QUALIFIERS`
  table, resolving it to the blind branch of both invariants per
  `degradation-ladder.md`'s third-selector-kind decision above; all three
  shipped invariants pass over all 17 profiles with the new selector
  recognised. Verified against real ffmpeg 9.0 with distinct-stem fixtures:
  artwork survives `--to mp3`, `--to m4a` and `--to flac`, including the
  selective-rung case (a flac-with-art source into `--to mp3`, which forces an
  audio re-encode); a real h264 and a real mjpeg video stream are both dropped
  with a note on `--to mp3` and `--to m4a` rather than carried; a two-picture
  source is carried whole with no loss note on both the cheap-attempt and
  selective-rung paths; `--to ogg` and `--to wav` over an artwork-bearing
  source are unaffected; a second run over a converted tree reports 0
  converted, exit 0. Every new assertion was proven non-vacuous by mutating a
  profile copy in a scratch script outside the repo (dropping the
  `attached_pic` rule, or giving it `stream_limit=1`) and confirming both the
  scratch check and the shipped `tests/test_profiles.py` invariants fail
  against the mutation.
- 2026-08-27 (issue #78): the cheap-attempt standing note is retired from all
  five audio profiles that carried one -- `mp3`, `flac`, `m4a`, `ogg`, `opus`
  -- leaving `Attempt(label="remux", options=...)` with no `notes` argument at
  all rather than an empty tuple, the same shape a profile that never carried
  one already had. Nothing named by a removed note is now unsaid: for `mp3`,
  `m4a` and `flac`, `jobs.verify_success` already named a real drop (a video,
  subtitle or attachment stream) per stream via `_structural_drop`'s "not
  supported by `<LABEL>`" branch before this issue touched anything, and the
  note's cover-art half had already gone false the moment #77 started
  carrying artwork -- so removing it deletes a statement that was either
  redundant or already wrong, never one still true and unreplaced. `ogg` and
  `opus` gain no `attached_pic` rule (Out of scope), so a cover-art stream
  there resolves to the plain `video` rule same as any other video stream and
  is dropped with the identical per-stream note -- proven by new tests
  (`TestOggJob`/`TestOpusJob::test_cover_art_is_dropped_with_a_note_same_as_any_other_video_stream`)
  rather than assumed. `last_resort` notes on all five profiles are untouched
  and pinned unchanged (`tests/test_profiles.py::TestStandingNoteRetirement`),
  since that rung is never verified and its note is the only place its claim
  exists. `ogg`, `opus` and `wav` argv is byte-for-byte unchanged -- `wav`
  needed no edit at all, since it carried no standing note to begin with.
  Verified against real ffmpeg 9.0 with distinct-stem fixtures: a plain
  matching-codec source into its own target (`tone-mp3.mp3 --to mp3`, and the
  `flac`/`m4a`/`ogg`/`opus` equivalents) converts and prints no note at all --
  the change a user notices first; artwork still survives the cheap-attempt
  and selective-rung paths into `mp3`/`m4a`/`flac` with no false drop; a real
  h264 and a real mjpeg video stream are still dropped with a note into `mp3`
  and `m4a`; an artwork-bearing source into `ogg`, `opus` and `wav` still
  drops the picture with a per-stream note; a second run over a converted tree
  reports 0 converted, exit 0. Every new or changed assertion was proven
  non-vacuous by mutating a profile copy in a scratch script outside the repo
  (restoring the removed standing note, adding an `attached_pic` rule to
  `ogg`, emptying a `last_resort` note) and confirming the same assertion the
  shipped test uses fails against each mutation.
- 2026-08-27 (issue #67): the finding this issue was filed to fix -- the
  cheap-attempt standing note firing even when a source had nothing for the
  target to drop, and naming neither a stream index nor a codec -- is
  resolved differently for the six profiles it covers, depending on what the
  note actually described.

  **`mkv` and `webm` retire theirs outright**, the same resolution #78 gave
  the five audio profiles: `jobs.verify_success`'s `_structural_drop` already
  names any stream of a type the profile declares no rule for, per stream,
  via its "not supported by `<LABEL>`" branch -- `mkv` declares no `data`
  rule and `webm` declares neither `attachment` nor `data`, so an attachment,
  data or timecode stream a partial cheap attempt could not have mapped was
  already named individually before this issue touched anything; the
  standing note was pure duplication, never a statement with no
  replacement. The per-stream prediction itself is pinned by new tests
  (`tests/test_argv.py::TestMkvDegradationNotes`/`TestWebmDegradationNotes`,
  `tests/test_batch.py::TestDropsAreConfirmedAgainstTheOutput`), which use the
  project's usual stubbed subprocess boundary and so prove the *logic*, not
  ffmpeg's own behaviour. That neither `mkv`'s nor `webm`'s real muxer
  regenerates a data or timecode stream from source metadata -- unlike
  `mov`/`mp4` (issue #66) -- is a claim about ffmpeg 9.0 itself, and is
  established the same way issue #66's original finding was: measured by
  hand, recorded in this entry's ffmpeg-9.0 verification paragraph below. A
  `.mov` source carrying a real `tmcd` timecode track converts to both
  containers holding video and audio only, nothing put back -- so no
  `confirm_drops` forgiveness is even in play and the per-stream prediction is
  exact on every file, not merely on average. `mov` needed no change: it
  already carries no standing note, having lost it to issue #66's finding
  that its muxer's own `tmcd` regeneration made the blanket claim measurably
  false.

  **`jpg`, `gif` and `avif` keep theirs, unconditional, by decision rather
  than oversight.** All five notes this issue's QA finding named for these
  profiles -- JPEG's and GIF's transparency loss, GIF's colour palette,
  AVIF's frame reduction -- describe a *within-stream* loss: the video
  stream is still mapped and kept, only something inside it (an alpha
  channel, a colour count, a frame count) is gone. `_structural_drop` only
  ever reasons about whether a stream was mapped at all, so it has no
  opinion on what survived inside one. Review round 2 of this PR flagged an
  earlier version of this entry's own summary sentence here ("neither half
  is fixed here") as false about its own contents -- half one *is* fixed, for
  the one note that needed it. Restated precisely below.

  *Half one -- firing when nothing was lost.* Four of the five notes are
  worded as claims about what *this profile's pipeline always does*
  ("transparency is not carried by JPEG" -- true of JPEG the format; AVIF's
  own notes are true of this profile's forced `-still-picture 1`/no-alpha
  pipeline specifically, not of the AVIF format, which does support alpha and
  multiple frames elsewhere), true of every conversion through that profile
  regardless of what the source held -- not a claim that *this* file's
  transparency was dropped -- so, unlike the retired `mkv`/`webm` notes, they
  do not over-report a specific event that did not happen; they state a
  limit. Review of this PR's first draft found the fifth, GIF's "colours are
  reduced to GIF's 256-colour palette", worded as an *action* rather than a
  fact, and measured that an already-GIF, already-<=256-colour source
  re-encodes pixel-identically (the module comment above `GIF` in
  `converter/profiles.py` already recorded this, unconnected until the
  review) -- so that wording, alone among the five, was a genuine false claim
  for such a file. It is reworded here to "GIF holds at most a 256-colour
  palette", the same fact-not-action shape as its four siblings, closing that
  one real gap; the other four were already accurate as written and needed no
  change.

  *Half two -- naming a stream index and codec.* None of the five names one,
  and this half is **not fixed, only recorded**. A profile's `notes` tuple is
  static data with no access to the source's probed streams at all, so naming
  an index and codec here would need a `pix_fmt` and a frame-count field on
  `Stream` (`converter/ffmpegtool.py`), plus new decision logic in `jobs.py`'s
  engine to compare a kept stream's measured properties against what its
  target actually holds -- both out of this issue's file boundary
  (`converter/jobs.py` was read-only for this work; `converter/ffmpegtool.py`
  was not in scope either), and `converter/profiles.py` is data, not code
  (`docs/constitution.md`), so the comparison logic could not live there even
  if the field existed. Retiring these notes outright rather than leaving them
  as an imprecise-but-true statement would violate `docs/constitution.md`'s
  "never report success for a conversion that silently dropped something" --
  an unmeasured within-stream loss is still a loss the constitution forbids
  leaving unsaid -- so all five stay unconditional standing notes. **Finding,
  not fixed in this issue:** both halves above are recorded for a follow-up
  issue -- conditional firing needs the `pix_fmt`/frame-count probing, and
  per-stream naming needs the engine to consult it -- rather than either being
  attempted piecemeal against the file boundary this issue was scoped to.

  Verified against real ffmpeg 9.0 with distinct-stem fixtures: a source with
  no data or timecode stream into `mkv`/`webm` now prints nothing at all,
  where the retired standing note used to fire unconditionally -- the change
  a user notices first; a source carrying a real `tmcd`-tagged data stream
  (built with `-timecode 00:00:00:00`) into `mkv` prints exactly
  `data stream 2 (unknown) dropped: not supported by MKV`, nothing more, and
  the output genuinely holds no data stream; a font-attachment-bearing MKV
  source into `webm` prints exactly
  `attachment stream 2 (ttf) dropped: not supported by WebM`; the same
  attachment source into `mov` still fails the cheap attempt and is dropped
  with `attachment stream 1 (unknown) dropped: not supported by MOV` at the
  selective rung, unchanged; an alpha-bearing PNG (measured source alpha byte
  `0x7e`) into `jpg`, `gif` and `avif` prints the transparency note and the
  loss is real and measured -- `ffprobe` reports `yuvj444p`/no-alpha `gbrp`
  pixel formats on the `jpg`/`avif` outputs, and the decoded alpha byte comes
  back `0xff` (opaque) on all three, where PNG, TIFF, BMP and WebP round-trip
  the same source at `0xfe`/`0xff` only because they keep an alpha channel at
  all (WebP: `yuva420p`, alpha `0xfe`); a multi-frame GIF source (3 frames,
  measured via `ffprobe -count_frames`) into `avif` prints the frame-reduction
  note and the output genuinely holds 1 frame; a re-run of an already-`.gif`
  source into `gif` still prints the reworded "GIF holds at most a 256-colour
  palette" -- true and unchanged in substance, but no longer a false claim
  that a reduction happened to that specific, already-quantised file; a
  second run over each converted tree reports 0 converted, exit 0. Every new
  or changed assertion was proven non-vacuous by mutating a profile copy in a
  scratch script outside the repo (restoring `mkv`'s and `webm`'s removed
  standing notes, giving each profile a bogus `data` rule that would make
  `verify_success` stop predicting the drop the shipped test pins, and
  restoring GIF's pre-review "colours are reduced to..." wording) and
  confirming the shipped assertion's expected value no longer matches against
  any of the three mutations.

  **Review round 1** (fresh-agent gate) found four comments in
  `converter/profiles.py` left over from before the standing note they
  described was retired -- MKV's `partial_mapping` comment and MOV's
  contrast with MKV still claiming a standing note that no longer exists on
  either side, and two WebM comments still pointing at "the standing note
  below/above" -- all four corrected to describe the code as it now reads. It
  also found the README bullet for MP3/FLAC/M4A overstated ("nothing prints
  for a source that never had one") against `last_resort`'s own unconditional
  note, corrected with the same carve-out `last_resort` has always needed,
  and found GIF's "colours are reduced to GIF's 256-colour palette" was a
  genuine false claim -- not merely an over-broad one -- for an already-GIF
  source, unlike its four unconditional-but-true siblings; reworded to "GIF
  holds at most a 256-colour palette" (`cheap_attempt` and `last_resort`
  both), the fix recorded above. It also asked whether the "second half" of
  the QA finding's own title -- naming no stream index or codec -- was
  addressed for `jpg`/`gif`/`avif`; it was not, and the profile comment and
  this entry now say so explicitly rather than only discussing conditionality.

  **Review round 2** (fresh-agent gate) found the round-1 sweep for stale
  standing-note comments had missed one: `tests/test_profiles.py`'s MOV test
  still said "the standing note MKV still carries" after MKV's own note was
  retired earlier in this same PR -- corrected to describe both profiles'
  current shape. It also found this entry's and `converter/profiles.py`'s own
  "neither half is fixed here" summary sentence contradicted the GIF rewording
  the same PR makes -- corrected above to say precisely which half is fixed
  for which note -- and that calling all five within-stream notes "format
  facts" mischaracterised AVIF's two, which are true of this profile's forced
  pipeline rather than of the AVIF format (which does support alpha and
  multiple frames elsewhere) -- corrected the same way. Non-blocking nits
  also addressed: the muxer-regeneration claim's docstring/spec wording no
  longer credits the (stubbed) test suite with proving something only the
  manual ffmpeg-9.0 record can; `tests/test_batch.py`'s new end-to-end test
  uses each profile's own real copy-mask codecs (vp9/opus for WebM) rather
  than an arbitrary h264/aac stand-in; and AVIF's back-reference to the
  module-level comment now points at the block actually above JPG rather than
  claiming it sits "above GIF".
- 2026-08-27: Close-out QA gate, coverage gap. The sub-ffmpeg-7.1 degradation
  path (Prior decisions row: below 7.1, `-map 0:disp:attached_pic?` aborts the
  cheap attempt with `Invalid disposition specifier`, exit 127, and the ladder
  reaches the same result via the selective rung at one wasted process per
  file) was checked as **text** against the shipped code and confirmed
  unenforced -- the three cheap attempts of `mp3`, `m4a` and `flac` are
  unconditional, matching the Verification bullet's claim -- but was not
  **exercised**: the QA machine has only ffmpeg 9.0 installed. Testing it for
  real needs a 6.x or 5.x binary. Recorded as an unverified coverage gap, not a
  defect.
- 2026-08-27: Close-out QA gate, coverage gap. The `last_resort` rung of the
  five audio profiles (`mp3`, `m4a`, `flac`, `ogg`, `opus`) was not reached
  end-to-end during the gate: reaching it needs both the cheap attempt and the
  selective rung to fail on an audio target, and no realistic fixture produced
  that. Their note text was instead verified by direct registry comparison
  against the pre-milestone commit, not by a real conversion. (`jpg`'s
  `last_resort` note, from the same issue #67 work, *was* exercised
  end-to-end -- the gap is specific to the five audio profiles, not to
  `last_resort` notes in general.)
- 2026-08-27: Close-out. The final QA gate ran against real ffmpeg 9.0 on
  Windows 11, reproducing every behavioural promise of this milestone and of
  milestone 7 (lossy-source-notes) end-to-end. Verdict: PASS WITH FINDINGS, no
  code defect. The one documentation finding -- this spec's Outcome section
  saying `last_resort` notes were "untouched" where "retained" was meant -- is
  fixed above. The two coverage gaps above are recorded rather than mistaken
  for coverage. Issue #101 (the `jpg`/`gif`/`avif` within-stream notes still
  firing unconditionally and naming no stream) remains open by design.

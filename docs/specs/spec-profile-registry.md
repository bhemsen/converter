# Spec: profile-registry (roadmap phase 1)

> Created: 2026-08-25

Turn the two hand-written conversion recipes in `converter/jobs.py` into one
generic, profile-driven engine, and move every format-specific fact into a new
leaf module `converter/profiles.py` — with the ffmpeg argv unchanged and the
notes changed only where today's wording omits a fact the vision requires. This
spec carries no lifecycle state — acceptance is the spec merged on the default
branch with a milestone and issues, and all progress lives in the GitHub issues
and milestone. A completed spec is moved to `docs/specs/archive/`.

## Outcome

- [ ] `converter/profiles.py` exists, imports nothing from `converter`, and holds
      the value types plus exactly two profile entries: MP4 and WAV.
- [ ] `converter/jobs.py` holds no ffmpeg knowledge of a target format — no codec
      name, no container option, no degradation-note wording. The one exception is
      the `JOB_BINDINGS` table described in Prior decisions, which is CLI wiring,
      is marked as such in the module, and disappears in phase 2.
- [ ] `converter/cli.py`, `converter/batch.py` and `converter/paths.py` have an
      empty diff for this phase.
- [ ] Every argv the test suite pins is produced byte-for-byte by the new engine.
      The four changes listed under *Accepted behaviour deltas* are
      the complete set of behaviour differences; anything else is a defect.
- [ ] Both profiles have a test pinning the exact argv they build, for the
      copyable and the non-copyable case each profile actually has
      (`docs/constitution.md`; see Verification for WAV, whose copy mask is empty).
- [ ] `converter --version`, `converter video ...` and `converter audio ...`
      behave exactly as they do on `main`; no user-visible CLI surface changed.
- [ ] `docs/architecture.md`, `docs/design.md` and `docs/roadmap.md` describe the
      shape this phase actually builds — amended in this spec's own PR, not left
      to the implementer.

## Scope

### In scope

- The new leaf module `converter/profiles.py`: the profile and per-stream-rule
  value types, the `Attempt` value type, the `flags()` recipe helper moved into
  it, and the MP4 and WAV profile entries.
- Rewriting the ladder in `converter/jobs.py` as a generic engine over a profile,
  per `docs/design/degradation-ladder.md` and `docs/design/stream-decision.md`.
- Keeping `Job` and `JOBS` in place with an unchanged public shape, so `cli.py`
  and `batch.py` need no diff.
- Porting the safety net onto the new API: `tests/test_argv.py` (the recipe
  tests) and `tests/test_batch.py` (which imports `MKV_TO_MP4` / `OPUS_TO_WAV`
  and pins the `remux` and `selective` rung labels), plus the constitution's
  per-profile argv-pinning tests.
- Removing the `_mp4_selective` row from the tech-debt table in
  `docs/constitution.md` once the function is gone.
- Foundation-doc amendments, already made in this spec's PR:
  `docs/architecture.md` (the profile owns its declared attempts; the last rung
  is optional; an accepted stream may be transcoded in kind; a stream limit is a
  drop reason), `docs/design.md` (a generic engine draws the per-stream branch
  once), `docs/roadmap.md` (what "identical behaviour" means here).

### Out of scope

- Any new target format. Phase 1 re-expresses the two that exist; `mp3`, `mkv`,
  `png` and the rest are phases 3-5.
- Any CLI change — `--to`, `--list-formats` and the reworked prompt are phase 2.
  The `video` / `audio` sub-commands stay exactly as they are here.
- Runtime-editable profiles (a TOML or JSON registry). `docs/architecture.md`
  rules this out: profiles are declarative Python so they keep type checking and
  ruff's view of the code.
- Verifying at runtime that the installed ffmpeg build actually has a muxer
  (`ffmpeg -formats`). Useful later, not needed for two formats that already work.

## Constraints

- `converter/profiles.py` must be a **leaf**: no `converter.*` import at all
  (`docs/architecture.md`). This is what makes "a target format is data, not
  code" structurally enforceable — a module that cannot import anything cannot
  hold logic. It is why `flags()` and `Attempt` have to move rather than be
  imported.
- `jobs.py` may import `profiles` and `ffmpegtool`, and nothing else. The import
  graph stays acyclic.
- `ffprobe` never runs on the happy path of an exhaustive cheap attempt
  (`docs/constitution.md`): the engine probes at most once per file — after an
  attempt has failed, or, for a cheap attempt the profile declares partial by
  construction, once on its success so that what it dropped is named. See the
  2026-08-26 (issue #18) Decision log entry for how that narrowing was reached.
- Maximum 50 lines per function, every parameter and return annotated, a
  docstring on every module and public function (`docs/constitution.md`).
  `_mp4_selective` is 51 lines today and is listed as tech debt to be cleared by
  this phase's replacement.
- ffmpeg options are written through `flags("...")` so a recipe reads like the
  command line you would type (`docs/constitution.md`).
- No `-map 0`: it selects attachments and data streams MP4 cannot hold.
- The test suite must keep passing on a machine with no ffmpeg installed — the
  subprocess boundary stays stubbed at `ffmpegtool.run()`.

## Prior art

- [Container/codec capability modelling (Phase 1)](../prior-art.md#containercodec-capability-modelling-phase-1)
  — the whole concern feeds this phase. HandBrake's `AudioCopyMask` plus
  `AudioEncoderFallback` is the vocabulary the profile value type adopts; the
  ffmpeg-CLI entry is why the copy mask is curated by hand instead of discovered;
  this codebase's own entry is why trial-and-fallback survives the refactor while
  its per-pair ladders do not.
- [Python wrapper structure around the ffmpeg CLI (Phase 3, Phase 4)](../prior-art.md#python-wrapper-structure-around-the-ffmpeg-cli-phase-3-phase-4)
  — secondary: `ffmpeg-normalize`'s split into stream types, a command builder and
  dedicated exceptions independently matches the layering this phase keeps, and
  its AVOID note (never scrape ffmpeg's stderr to drive a second pass) is exactly
  the temptation a fallback ladder creates.

## Design

- `docs/design/degradation-ladder.md` — the order of attempts, where a subprocess
  is spent, when the selective rung is skipped, and where container options land.
- `docs/design/stream-decision.md` — accept / re-encode / drop for one stream,
  what each resulting note must name, and the order options are emitted in.

Both are part of this spec package and are reviewed at the spec-acceptance gate.
Implement against them; the mechanism lives there and is referenced, not repeated,
from this file.

## Human prerequisites

- none. This phase adds no dependency, touches no secret, and needs no external
  provisioning. ffmpeg is only needed for the milestone-QA smoke test, and it is
  already installed on this machine (`docs/workflow.md`, *This machine*).

## Prior decisions

| Decision | Rationale | Date |
|---|---|---|
| A profile is a frozen dataclass holding a display label, the target suffix, container-wide options, a declared cheap attempt, a flag saying whether that cheap attempt selects streams explicitly, an optional declared last-resort attempt, and one rule per stream type | HandBrake's copy-mask + encoder-fallback vocabulary as data per target (`docs/prior-art.md`), expressed in the value-type style the constitution already requires | 2026-08-25 |
| A stream rule holds: the copy mask (a `frozenset` of codec names, possibly empty), the option template emitted for an accepted stream, an optional fallback-encoder option template, the human-readable name of what that encoder produces or `None` when the re-encode gives up nothing worth naming, an optional limit on how many streams of the type the container holds, and the reason a stream is dropped when there is no fallback | Covers every branch the two existing recipes take, including MP4's subtitle case where an accepted stream is transcoded to `mov_text` rather than copied, and WAV's case where nothing is copyable and the PCM conversion is the point of the format rather than a loss | 2026-08-25 |
| WAV's audio rule has an **empty** copy mask, a `pcm_s16le` fallback, and **no** re-encode note; its stream limit is 1. WAV declares no rule for any other stream type | Reproduces today's output exactly: `wav_pcm()` emits no note, and a second audio stream is dropped with one. An empty mask is a legitimate value — a container may accept nothing as-is | 2026-08-25 |
| Positional output specifiers are written into the option template as a literal `{n}` placeholder, e.g. `flags("-c:v:{n} libx264 -crf:v:{n} 18")`, and the engine replaces every `{n}` with the per-type output position | Keeps the `flags("...")` convention — the template still reads like the command line you would type — and avoids the engine guessing which flags take a stream specifier (`-preset` does not) | 2026-08-25 |
| The placeholder is **optional**. A rule whose stream limit is 1 can only ever produce one output stream of its type, so it writes the bare specifier and the engine substitutes nothing. WAV's audio templates are therefore placeholder-free: `flags("-c:a pcm_s16le")` | This is what keeps `tests/test_argv.py`'s `("-map", "0:0", "-c:a", "pcm_s16le")` byte-for-byte rather than turning it into `-c:a:0`. The alternative — a universal placeholder plus a fourth accepted delta — would weaken the safety net to buy uniformity that a limit-1 container cannot use | 2026-08-25 |
| The cheap attempt and the last-resort attempt are **declared per profile as data**, not derived by the engine | `docs/architecture.md`: a new target format must be one profile entry and nothing else. A derived last rung would need MP4's `-pix_fmt yuv420p` and WAV's absence of a video rung to live as branching in `jobs.py`, i.e. format knowledge in the engine. Declaring them also guarantees the two existing argv strings survive byte-for-byte | 2026-08-25 |
| Container-wide options are declared once on the profile, and the engine places them as `docs/design/degradation-ladder.md` specifies; the declared attempts' own data therefore excludes them | Today `+faststart` is the tail of all three MP4 attempts. Declaring it once keeps that argv and stops a profile from repeating the flag | 2026-08-25 |
| The engine-built rung emits its options in the order `docs/design/stream-decision.md` specifies | `tests/test_argv.py` pins exactly that grouping; any other order would be equally valid ffmpeg and a different argv | 2026-08-25 |
| The selective rung is emitted per `docs/design/degradation-ladder.md`; the one datum the engine cannot derive — whether the cheap attempt already selects streams explicitly — is declared by the profile (MP4: no, WAV: yes) | The alternative, comparing the plan against the cheap attempt, would require the engine to parse ffmpeg option syntax, putting CLI knowledge back into `jobs.py`. With the flag, MP4 keeps its rung for `[h264]` and WAV keeps returning no rung for a single audio stream — both existing tests hold | 2026-08-25 |
| The engine-built rung is labelled `"selective"` for every profile; the declared attempts keep their current labels (`remux`, `pcm_s16le`, `re-encode`). WAV's `first-audio-stream` label disappears | `tests/test_batch.py` pins `remux` and `selective`; nothing pins `first-audio-stream`. One label for one engine-built rung is what makes the label meaningful across 17 formats | 2026-08-25 |
| A note's `TARGET` is the profile's **display label** (`MP4`, `WAV`). A stream whose `codec_name` ffprobe leaves empty reads as `unknown`, and so does a stream whose `codec_type` it leaves empty | All three reproduce today's strings in `converter/jobs.py`, which already falls back to `unknown` for both fields | 2026-08-25 |
| `Attempt` moves to `profiles.py` and `jobs.py` imports it; `jobs.py` does **not** re-export it | A profile declares attempts, so the type must sit in the leaf. One import path per type, so a test cannot accidentally pin the wrong one | 2026-08-25 |
| `Job` keeps its public shape (`name`, `description`, `suffixes`, `target_suffix`, `first_attempt`, `retries`) and `JOBS` keeps its keys. The source-pair data behind them — the `JOBS` key (`video`, `audio`), the `Job.name` that `batch.py` prints as the progress-bar description (`mkv-to-mp4`, `opus-to-wav`), the help text, the source suffixes and the target profile — lives in one `JOB_BINDINGS` table in `jobs.py`, explicitly exempted from the no-format-knowledge outcome and marked in the module as phase-2 scaffolding | Delivers the empty diff in `cli.py` and `batch.py`. The data is a *source-pair* binding, not target-format knowledge, so putting it on the profile would contaminate the value type phase 2 consumes by target alone | 2026-08-25 |
| `flags()` moves from `jobs.py` to `profiles.py`; `jobs.py` imports it from there | `profiles.py` writes the recipes and may not import `jobs`; duplicating the function instead would be two definitions of one convention | 2026-08-25 |
| The module-level recipe functions `mp4_remux`, `mp4_retries`, `wav_pcm`, `wav_retries` may disappear | They are internal — nothing outside `jobs.py` and its tests imports them, and the README documents no Python API | 2026-08-25 |
| Every argv assertion in the test suite is preserved verbatim. A note assertion may change only for one of the *Accepted behaviour deltas* below; any other diff to the safety net fails review | The tests are this refactor's safety net; a refactor that silently rewrites its own safety net proves nothing | 2026-08-25 |
| Genuinely open decisions: **none**. Every fork this phase raises is answered in the rows above, resolved from `docs/prior-art.md`, `docs/constitution.md` or `docs/architecture.md` | Recorded so the acceptance gate is a deliberate "nothing was guessed", not an omission | 2026-08-25 |

### Accepted behaviour deltas

These four are the complete set of intended differences from `main`. Each ships
with the test that pins it.

1. **The attachment/unknown-stream note gains the codec.** Today it reads
   `attachment stream 1 dropped: not supported by MP4`, omitting the codec —
   which `docs/vision.md` requires every degradation note to name. It becomes
   `attachment stream 1 (ttf) dropped: not supported by MP4`.
2. **The surplus-audio-stream note is re-worded per stream instead of per file.**
   Today: `2 audio streams present; kept stream 0 only (WAV holds one)`. It
   becomes what `D2` in `docs/design/stream-decision.md` renders for this case —
   `audio stream 1 (opus) dropped: WAV holds 1 audio stream` — which names the
   stream that was actually lost and its codec. The rung's argv is unchanged.
3. **WAV's fallback rung is labelled `selective` instead of `first-audio-stream`.**
   Not visible on a successful conversion — the label only surfaces in the
   per-rung error line `batch.py` builds when every rung failed, so a WAV file
   that fails outright now reports `[selective] ...` where `main` reports
   `[first-audio-stream] ...`.
4. **A WAV source carrying a non-audio stream gains a rung on the failure path.**
   An `.opus` with embedded cover art currently produces no retry at all; it now
   reaches a selective rung that drops the cover-art stream with a note. The rung
   is only ever built after the cheap attempt has already failed, and its argv is
   equivalent to the cheap attempt's, so no successful conversion changes.

## Tracking

The decomposition into steps lives as GitHub issues, not in this file — one
issue per step, grouped under a milestone. This spec owns the design; the issues
own progress. Do not duplicate the step list here.

- Milestone: [profile-registry](https://github.com/bhemsen/converter/milestone/1) (#1)
- Issues: created from this spec once it is merged (one per implementable step)

Each issue references this spec path in its body.

## Verification

Machine checks — Verify is the per-iteration gate (`docs/workflow.md`):

- [ ] Verify passes (ruff check, ruff format --check, pytest) on the merge commit.
- [ ] A test asserting `converter/profiles.py` contains no `from converter` or
      `import converter` statement — the leaf rule, checked rather than trusted.
- [ ] A test pinning the full argv MP4 builds for a copyable input
      (h264 + aac) and for a non-copyable one (vp8 + pcm_s16le).
- [ ] A test pinning the full argv WAV builds for a single-audio source and for a
      two-audio source. WAV has no copyable case to pin — its copy mask is empty
      by construction, so these are the two cases the constitution's rule can
      have here, and the reason is recorded in Prior decisions.
- [ ] A test per degradation branch asserting its note names the stream index,
      that stream's codec, and what was given up: audio re-encoded, video
      re-encoded, bitmap subtitle dropped, attachment dropped, surplus audio
      stream dropped, non-audio stream dropped by WAV, and the last-resort
      attempt's own two notes (lossy re-encode; 10-bit/HDR reduced to 8-bit).
- [ ] A test asserting WAV's PCM conversion emits **no** note — the one re-encode
      that is not a degradation.
- [ ] A test per symptom of issue #18, driving the *cheap-attempt-succeeds* path
      rather than calling `.retries()` directly: the dropped attachment and the
      dropped surplus audio stream are each named on a run that reports
      `converted`, and an exhaustive cheap attempt still spends no probe on
      success.
- [ ] A test per failure-path delta, since the QA gate cannot reach them: the
      engine-built rung is labelled `selective` for WAV too (delta 3), and a WAV
      source carrying a non-audio stream yields exactly one rung that drops it
      with a note (delta 4).
- [ ] `git diff main -- converter/cli.py converter/batch.py converter/paths.py`
      is empty.
- [ ] No function in `converter/jobs.py` or `converter/profiles.py` exceeds 50
      lines, and the `_mp4_selective` row is gone from the tech-debt table in
      `docs/constitution.md`.

Human milestone-QA gate — the machine checks stub the subprocess boundary and so
prove nothing about a real conversion (`docs/workflow.md`). The repository ships
no media fixtures; synthesise them first. `$FF` is the absolute ffmpeg path from
*This machine*; the shell is PowerShell, one command per line, and `ffmpeg` does
not create the directory itself:

```text
New-Item -ItemType Directory -Force in
& $FF -f lavfi -i testsrc=size=320x240:rate=10:duration=2 -f lavfi -i sine=duration=2 -c:v libx264 -c:a aac in/clip.mkv
& $FF -f lavfi -i testsrc=size=320x240:rate=10:duration=2 -c:v vp8 in/lossless.mkv
& $FF -f lavfi -i testsrc=size=320x240:rate=10:duration=2 -c:v libx264 -attach C:\Windows\Fonts\arial.ttf -metadata:s:t mimetype=application/x-truetype-font in/attached.mkv
& $FF -f lavfi -i sine=duration=2 -c:a libopus in/tone.opus
& $FF -f lavfi -i sine=frequency=440:duration=2 -f lavfi -i sine=frequency=880:duration=2 -map 0:a -map 1:a -c:a libopus in/two-tone.opus
```

`lossless.mkv` is the ladder-forcing case: MP4's video copy mask
(`MP4_VIDEO_CODECS` in `converter/profiles.py`) does not include `vp8`, and the
MP4 muxer itself rejects it (confirmed on this machine's ffmpeg 9.0: `Could not
find tag for codec vp8 in stream #0, codec not currently supported in
container`), so the remux fails and the selective rung has to re-encode the
video. `attached.mkv` and
`two-tone.opus` exist to make deltas 1 and 2 observable — the other fixtures
never reach those branches. The WAV job only accepts `.opus` sources, which is
why both audio fixtures use that suffix.

- [ ] `converter video in out` converts `clip.mkv` to a playable `.mp4` and
      reports `converted`, `0 failed`, exit 0.
- [ ] `converter audio in out` converts `tone.opus` to a playable `.wav`.
- [ ] `lossless.mkv` still converts, and prints a note naming the stream index,
      `vp8`, and the re-encode to h264.
- [ ] A second run of each over the same output tree reports `0 converted`,
      `N skipped`, `0 failed`, exit 0.
- [ ] Delta 1: `attached.mkv` converts and its attachment note names the font
      codec (`ttf`), which the same command on `main` omits entirely.
- [ ] Delta 2: `two-tone.opus` converts and names the dropped audio stream and
      its codec, where `main` reports the count instead.
- [ ] Deltas 3 and 4 are **not QA-checkable**, by construction: both only surface
      once an attempt has already failed, which no synthesised fixture triggers
      reliably. They are covered by the machine checks instead. What this gate
      does check is the negative — no successful conversion above differs from
      `main` beyond deltas 1 and 2.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| The generic engine silently changes an argv and the change is only found once a real file converts wrongly | The per-profile argv-pinning tests are written against the strings `main` produces today, before the engine is rewritten; the accepted-deltas list is closed, so any other diff fails review |
| The profile value type is shaped around only two formats and needs breaking changes in phases 3-5 | Accepted deliberately: the roadmap sequences phase 1 before the coverage phases so the model is validated cheaply on audio first. Phases 3-5 may extend the value type; they may not push format knowledge back into `jobs.py` |
| `JOB_BINDINGS` and the `Job` adapter become dead weight after phase 2 | Both are marked in the module as phase-2 scaffolding; phase 2 removes them as part of the breaking change it already ships |
| Note wording drifts and a degradation stops naming what it cost | Every degradation branch ships with a test asserting its note (`docs/constitution.md`), enumerated in Verification above |
| A refactor that also "tidies" `cli.py` or `batch.py` would break the empty-diff outcome | The empty-diff check is a Verification item, so it fails the gate rather than being noticed in review |

## Decision log

- 2026-08-25: Two design diagrams rather than one — `degradation-ladder.md`
  decides the order of attempts, `stream-decision.md` decides one stream's fate.
  `docs/design.md` requires one decision per diagram.
- 2026-08-25: The diagrams use conceptual labels ("the rule's copy mask") and
  brace-free placeholders (`TARGET`, `TARGET_CODEC`, `DROP_REASON`) rather than
  field names or angle brackets — a rename must not rot the artifact, and Mermaid
  renders quoted node text as HTML, so `<target>` would vanish from the rendered
  diagram at the review gate.
- 2026-08-25: Spec review found that comparing the selective plan against the
  cheap attempt is not computable from declared data without parsing ffmpeg
  option syntax. Replaced by a declared flag on the profile; both existing
  suppression behaviours were re-checked against `tests/test_argv.py`.
- 2026-08-25: Closing the equivalence escape hatch in review round 2 introduced a
  contradiction of its own: the universal `{n}` placeholder would have turned
  WAV's pinned `-c:a pcm_s16le` into `-c:a:0`, which the closed delta list forbids.
  Resolved by making the placeholder optional for a rule that can only produce one
  output stream, rather than by admitting a fourth delta — the strict reading of
  "the argv stays identical" is worth more than template uniformity.
- 2026-08-25: Spec review found `docs/architecture.md` describing a ladder this
  phase does not build (a mandatory last rung, copy-only acceptance, two drop
  reasons). Amended here rather than left to drift, since architecture is the
  living doc this phase alters.
- 2026-08-25 (issue #5): `StreamRule.drop_reason` is typed `str | None`, not the
  bare `str` its prose ("the reason a stream is dropped when there is no
  fallback") might suggest, because MP4's video and audio rules always declare a
  fallback encoder — the D3 branch that would read `drop_reason` is unreachable
  for them, and giving it a real value there would read as a lie about what the
  rule does. `None` marks "not applicable"; only MP4's subtitle rule sets it.
- 2026-08-25 (issue #5): WAV's audio rule declares `accept_options=()` rather
  than a placeholder copy template, because its copy mask is empty by
  construction — the accept branch of `stream-decision.md` can never be reached
  for it, so there is no real template to write.
- 2026-08-25 (issue #5): `jobs.py` keeps `MP4_VIDEO_CODECS`, `MP4_AUDIO_CODECS`,
  `TEXT_SUBTITLE_CODECS` and `FASTSTART` as its own module-level constants,
  duplicating the values now also held by `profiles.MP4`'s rules and container
  options. Issue #5's contract is "no ladder rewrite" — only `flags()` and
  `Attempt` move — so `jobs.py`'s recipe functions still reference their own
  copies. The duplication is temporary: issue #6 rewires `jobs.py` onto the
  profile and removes it.
- 2026-08-25 (issue #6): the per-stream decision is drawn as a single helper,
  `_decide_stream`, that returns `(maps, codecs, note)` for one stream and
  mutates a shared `counts` dict rather than the caller threading a returned
  counter back in. A pure "return the incremented count too" shape was
  rejected: `_build_selective`'s loop would then have to unpack and re-store
  `counts[stream.codec_type]` itself, duplicating the bookkeeping
  `_decide_stream` already has all the information to do once.
- 2026-08-25 (issue #6): `JOB_BINDINGS` is keyed by the same strings as `JOBS`
  (`"video"`, `"audio"`) and holds a small frozen `_Binding` (name,
  description, suffixes, profile) rather than a bare tuple, so the phase-2
  removal this table is scaffolding for can delete one dataclass and one dict
  without hunting through positional-tuple indexing elsewhere.
- 2026-08-25 (issue #6): confirmed on this machine's ffmpeg (9.0, gyan.dev
  build) that the milestone-QA `lossless.mkv` fixture's cheap remux attempt
  (`-c copy` into MP4) exits 0 even though the source is `ffv1`, so the ladder
  is not forced by that fixture in practice here — this is unchanged from
  `main` (the cheap-attempt argv is byte-identical), not a regression. The
  ladder logic was verified directly instead: probing the fixture with real
  ffprobe and calling `MKV_TO_MP4.retries()` on the result produces the
  expected selective rung (video re-encoded to h264, noting `ffv1`), and running
  that rung's argv through real ffmpeg succeeds and produces a valid file. The
  same direct check was run for `attached.mkv` (delta 1) and `two-tone.opus`
  (delta 2/3), all matching the design.
- 2026-08-25 (issue #7): several notes already asserted by issue #6's tests
  used substring checks (`"pcm_s16le" in note and "aac" in note`) rather than
  pinning the exact string, which does not satisfy Verification's "names the
  stream index, that stream's codec, and what was given up" for the video- and
  audio-reencode and bitmap-subtitle-drop branches, nor pin the last-resort
  attempt's own two notes. Left the existing (weaker) tests untouched per the
  no-rewrite rule on the safety net and added new tests next to them
  (`TestMp4DegradationNotes` in `tests/test_argv.py`) asserting exact equality
  instead. No engine or profile code changed — this issue is test-only.
- 2026-08-26 (issue #19): the milestone-QA `lossless.mkv` fixture is rebuilt with
  `-c:v vp8` instead of `-c:v ffv1`. On this machine's ffmpeg (9.0, gyan.dev
  build) `ffv1` muxes into MP4 without error, so the fixture no longer forced
  the ladder (found at the phase-1 QA gate; issue #6's own decision-log entry
  above already shows the remux exiting 0 for `ffv1`, but issue #6 read that as
  "unchanged from `main`, not a regression" rather than as a fixture defect).
  `vp8` was chosen over `theora`, `wmv2` and `dnxhd` (all four confirmed to fail
  the MP4 remux, empirically, not by reasoning about the spec) because it needs
  no special resolution or pixel format to encode and is already the non-copyable
  video codec the argv-pinning tests use (Verification: "vp8 + pcm_s16le"), so
  the QA fixture and the unit tests now name the same example. Verified end to
  end through the real CLI, not just ffmpeg directly: `converter video` on a
  `vp8`-in-MKV source converts, exits 0, and prints
  `video stream 0 (vp8) re-encoded to h264`; `ffprobe` on the resulting `.mp4`
  reports the video stream's `codec_name` as `h264`, confirming a genuine
  re-encode rather than a silent remux.
- 2026-08-26 (issue #19): the MP4 video copy mask (`MP4_VIDEO_CODECS`) is left
  unchanged — it does not grow to include codecs a given ffmpeg build happens to
  be willing to mux into MP4 (`ffv1` on this build). `docs/prior-art.md`'s
  FFmpeg-CLI entry already settles this for the whole mask: "deriving
  container-to-codec compatibility from the CLI" is an explicit AVOID, because
  the CLI reports what a build can technically write, never what is legal for a
  standard MP4 player to read — "the mask must be curated, exactly as
  `MP4_VIDEO_CODECS` is today." The Verification section's own QA criterion
  ("converts `clip.mkv` to a **playable** `.mp4`") reinforces the same intent: an
  `ffv1`-in-MP4 file that only ffmpeg itself can decode back out would satisfy
  "ffmpeg exits 0" while failing "playable." Widening the mask to whatever one
  installed binary is willing to mux would also make the copy mask
  machine-dependent, which contradicts the mask being declarative data
  (`docs/architecture.md`). Not a design fork requiring escalation: the prior-art
  AVOID note and the playability criterion already answer it.
- 2026-08-26 (issue #18): the `ffprobe`-never-on-the-happy-path rule is
  **narrowed** rather than kept absolute. `ffprobe` stays off the happy path of a
  cheap attempt whose mapping is *exhaustive*; a cheap attempt that is
  **structurally partial** — one whose mapping can by construction leave source
  streams unmapped (MP4's blind `-map 0:v? -map 0:a? -map 0:s?`, WAV's
  single-index `-map 0:a:0`) — is verified by a probe **on success**, so a silent
  drop is never reported as a plain success. Issue #18 escalated this as a design
  fork because `docs/constitution.md` states both "`ffprobe` never runs on the
  happy path" and "never report success for a conversion that silently dropped
  something", and naming a dropped stream's index and codec is only knowable from
  the source's stream list — parsing ffmpeg's stderr for it being an explicit
  Don't. Rationale for narrowing: the ladder's cost argument is about the common
  case, a copyable source converting without a round-trip. Keeping the rule
  absolute would have forced the two fixture-specific acceptance items
  (`attached.mkv` naming the `ttf` attachment, `two-tone.opus` naming the second
  audio stream and its codec) to be relaxed, trading away the loss-accounting USP
  in `docs/vision.md` to protect a probe on a minority of runs. The four
  restatements the escalation named moved together — `docs/constitution.md`
  (Architecture principles), `docs/architecture.md` (Key flows §1),
  `docs/design.md` (Cost markers), `docs/design/degradation-ladder.md` (the
  diagram gains a success-side probe node) — and review found seven more that a
  grep disproved the completeness of, all amended in the same PR: this spec's
  Constraints, `converter/ffmpegtool.probe_streams`'s docstring,
  `docs/design/source-selection.md`, `docs/prior-art.md`'s ADOPT note, the
  Constraints bullet of each of the three merged coverage specs
  (`spec-audio-formats.md`, `spec-video-formats.md`, `spec-image-formats.md`),
  and `spec-target-driven-cli.md`'s mixed-tree decision. The phase-3 cover-art
  decision, whose premise this narrowing invalidates outright, carries a
  supersession note rather than a re-decision — that choice is phase 3's to
  re-take at its own gate.
- 2026-08-26 (issue #18): "partial by construction" is a **declared field on the
  profile** (`Profile.partial_mapping`), with no default, rather than inferred.
  Inferring it would mean parsing the cheap attempt's option list for `?`
  selectors and stream indices, which is exactly the ffmpeg-syntax knowledge
  `docs/design/degradation-ladder.md` keeps out of the engine — the same
  reasoning that already made `explicit_streams` a declared flag. Omitting the
  default forces every future target profile to state the answer instead of
  inheriting a silent one.
- 2026-08-26 (issue #18): the success-side verification reads only the profile's
  **structural** verdicts — no rule declared for the stream's type (D1), or the
  container already holding as many streams of that type as it can (D2) — and
  never a codec-level one (the D3 no-fallback drop, or a re-encode). Both
  structural verdicts follow from the declared rules alone, independently of what
  the source's codecs turned out to be, so they are exactly the drops a
  structurally partial mapping cannot avoid. A codec-level verdict would be a
  lie on this path: ffmpeg exited 0, so the stream was carried over whatever the
  copy mask says, and reporting a re-encode that never ran would trade one
  dishonest report for another. The shared helper is `_structural_drop` in
  `converter/jobs.py`, used by both `_decide_stream` and `_unmapped_notes` so the
  two readings of D1/D2 cannot drift.
- 2026-08-26 (issue #18): a verification probe that itself fails does not fail the
  conversion — the output is written and valid — but the run is reported with the
  note `could not verify which source streams were kept: <error>` instead of as a
  plain success. Failing an otherwise good conversion because its bookkeeping
  could not be completed would be worse than the silence being fixed; saying
  nothing would re-open it.

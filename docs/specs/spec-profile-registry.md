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
- `ffprobe` never runs on the happy path (`docs/constitution.md`): the engine
  probes at most once per file, and only after an attempt has already failed.
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

- Milestone: profile-registry (created at the spec-acceptance gate)
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
& $FF -f lavfi -i testsrc=size=320x240:rate=10:duration=2 -c:v ffv1 in/lossless.mkv
& $FF -f lavfi -i testsrc=size=320x240:rate=10:duration=2 -c:v libx264 -attach C:\Windows\Fonts\arial.ttf -metadata:s:t mimetype=application/x-truetype-font in/attached.mkv
& $FF -f lavfi -i sine=duration=2 -c:a libopus in/tone.opus
& $FF -f lavfi -i sine=frequency=440:duration=2 -f lavfi -i sine=frequency=880:duration=2 -map 0:a -map 1:a -c:a libopus in/two-tone.opus
```

`lossless.mkv` is the ladder-forcing case: MP4 cannot hold `ffv1`, so the remux
fails and the selective rung has to re-encode the video. `attached.mkv` and
`two-tone.opus` exist to make deltas 1 and 2 observable — the other fixtures
never reach those branches. The WAV job only accepts `.opus` sources, which is
why both audio fixtures use that suffix.

- [ ] `converter video in out` converts `clip.mkv` to a playable `.mp4` and
      reports `converted`, `0 failed`, exit 0.
- [ ] `converter audio in out` converts `tone.opus` to a playable `.wav`.
- [ ] `lossless.mkv` still converts, and prints a note naming the stream index,
      `ffv1`, and the re-encode to h264.
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

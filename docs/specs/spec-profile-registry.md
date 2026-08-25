# Spec: profile-registry (roadmap phase 1)

> Created: 2026-08-25

Turn the two hand-written conversion recipes in `converter/jobs.py` into one
generic, profile-driven engine, and move every format-specific fact into a new
leaf module `converter/profiles.py` — with the observable ffmpeg behaviour of
MKV -> MP4 and Opus -> WAV unchanged. This spec carries no lifecycle state —
acceptance is the spec merged on the default branch with a milestone and issues,
and all progress lives in the GitHub issues and milestone. A completed spec is
moved to `docs/specs/archive/`.

## Outcome

- [ ] `converter/profiles.py` exists, imports nothing from `converter`, and holds
      the value types plus exactly two profile entries: MP4 and WAV.
- [ ] `converter/jobs.py` contains no format-specific constant, codec name or
      note string: it builds the attempt ladder from a profile plus a probed
      stream list, and from nothing else.
- [ ] `converter/cli.py`, `converter/batch.py` and `converter/paths.py` have an
      empty diff for this phase.
- [ ] For every input the test suite covers, the argv reaching ffmpeg and the
      notes reaching the user are the same as before the change, or differ only
      in a way that is ffmpeg-equivalent and listed in the PR body.
- [ ] Both profiles have a test pinning the exact argv they build, for a
      copyable and for a non-copyable input (`docs/constitution.md`).
- [ ] `converter --version`, `converter video ...` and `converter audio ...`
      behave exactly as they do on `main`; no user-visible CLI surface changed.

## Scope

### In scope

- The new leaf module `converter/profiles.py`: the profile and per-stream-rule
  value types, the `flags()` recipe helper moved into it, and the MP4 and WAV
  profile entries.
- Rewriting the ladder in `converter/jobs.py` as a generic engine over a profile,
  per `docs/design/degradation-ladder.md` and `docs/design/stream-decision.md`.
- Keeping `Job` and `JOBS` in place with an unchanged public shape, so `cli.py`
  and `batch.py` need no diff.
- Porting the existing `tests/test_argv.py` recipe tests onto the new API and
  adding the constitution's per-profile argv-pinning tests.

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
  hold logic. It is why `flags()` has to move rather than be imported.
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
  is spent, and the two conditions under which the selective rung is skipped.
- `docs/design/stream-decision.md` — copy / re-encode / drop for one stream, and
  what each resulting note must name.

Both are part of this spec package and are reviewed at the spec-acceptance gate.
Implement against them; do not restate them in an issue.

## Human prerequisites

- none. This phase adds no dependency, touches no secret, and needs no external
  provisioning. ffmpeg is only needed for the milestone-QA smoke test, and it is
  already installed on this machine (`docs/workflow.md`, *This machine*).

## Prior decisions

| Decision | Rationale | Date |
|---|---|---|
| A profile is a frozen dataclass holding a display label, the target suffix, container-wide options, a cheap first attempt, an optional last-resort attempt, and one rule per stream type | HandBrake's copy-mask + encoder-fallback vocabulary as data per target (`docs/prior-art.md`), expressed in the value-type style the constitution already requires | 2026-08-25 |
| A stream rule holds: the copy mask (a `frozenset` of codec names), the option template emitted for an accepted stream, an optional fallback-encoder option template, the human-readable name of what that encoder produces, an optional limit on how many streams of the type the container holds, and the reason a stream is dropped when there is no fallback | Covers every branch the two existing recipes take, including MP4's subtitle case where an accepted stream is not literally copied but transcoded to `mov_text` | 2026-08-25 |
| Positional output specifiers are written into the option template as a literal `{n}` placeholder, e.g. `flags("-c:v:{n} libx264 -crf:v:{n} 18")`, and the engine replaces every `{n}` with the per-type output position | Keeps the `flags("...")` convention — the template still reads like the command line you would type — and avoids the engine guessing which flags take a stream specifier (`-preset` does not) | 2026-08-25 |
| The cheap first attempt and the last-resort attempt are **declared per profile as data**, not derived by the engine | `docs/architecture.md`: a new target format must be one profile entry and nothing else. A derived last rung would need MP4's `-pix_fmt yuv420p` and WAV's absence of a video rung to live as branching in `jobs.py`, i.e. format knowledge in the engine. Declaring them also guarantees the two existing argv strings survive byte-for-byte | 2026-08-25 |
| The selective rung is suppressed when nothing survives the profile's rules, or when its plan keeps the same streams with the same codecs as the first attempt and sacrifices nothing | Reproduces today's `wav_retries([single audio]) == []` without a special case, and stops a profile whose first attempt already maps explicitly from paying for a duplicate ffmpeg run. Drawn in `docs/design/degradation-ladder.md` | 2026-08-25 |
| `Job` keeps its public shape (`name`, `description`, `suffixes`, `target_suffix`, `first_attempt`, `retries`) and `JOBS` keeps its keys; both are built from a profile by a factory in `jobs.py` | Delivers the "empty diff in `cli.py` and `batch.py`" outcome, and leaves phase 2 a natural seam: the CLI will build a `Job` from a profile chosen by `--to` | 2026-08-25 |
| `flags()` moves from `jobs.py` to `profiles.py`; `jobs.py` imports it from there | `profiles.py` writes the recipes and may not import `jobs`; duplicating the function instead would be two definitions of one convention | 2026-08-25 |
| Existing argv assertions in `tests/test_argv.py` are preserved verbatim wherever the new engine produces the same string; an assertion may only change when the new value is ffmpeg-equivalent (e.g. `-c:a` vs `-c:a:0` for a container that holds one audio stream) or when a note is re-worded, and every such change is listed in the PR body with its justification | The tests are this refactor's safety net; a refactor that silently rewrites its own safety net proves nothing. Re-worded notes still have to name the stream index, the stream's codec and what was given up (`docs/vision.md`) | 2026-08-25 |
| The module-level recipe functions `mp4_remux`, `mp4_retries`, `wav_pcm`, `wav_retries` may disappear | They are internal — nothing outside `jobs.py` and its tests imports them, and the README documents no Python API | 2026-08-25 |
| Genuinely open decisions: **none**. Every question this phase raises was settled by `docs/prior-art.md`, `docs/constitution.md` or `docs/architecture.md` | Recorded so the acceptance gate is a deliberate "nothing was guessed", not an omission | 2026-08-25 |

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
- [ ] A test pinning the full argv for MP4 with a copyable input (h264 + aac) and
      with a non-copyable one (vp8 + pcm_s16le), and the same pair for WAV.
- [ ] A test per degradation branch asserting its note names the stream index,
      that stream's codec, and what was given up: audio re-encoded, video
      re-encoded, bitmap subtitle dropped, attachment dropped, surplus audio
      stream dropped.
- [ ] `git diff main -- converter/cli.py converter/batch.py converter/paths.py`
      is empty.
- [ ] No function in `converter/jobs.py` or `converter/profiles.py` exceeds 50
      lines, clearing the `_mp4_selective` tech-debt row in
      `docs/constitution.md`.

Human milestone-QA gate — the machine checks stub the subprocess boundary and so
prove nothing about a real conversion (`docs/workflow.md`). Run with the absolute
ffmpeg paths from *This machine*:

- [ ] `converter video <dir> <out>` converts a real `.mkv` to a playable `.mp4`,
      reporting `1 converted, 0 skipped, 0 failed`.
- [ ] `converter audio <dir> <out>` converts a real `.opus` to a playable `.wav`.
- [ ] A second run over the same output tree reports `0 converted`, `N skipped`,
      `0 failed`, exit 0.
- [ ] A source that forces the ladder down a rung (an MKV carrying a codec MP4
      cannot hold) still converts, and prints a note naming what it gave up.
- [ ] The `docs/constitution.md` tech-debt table has its `_mp4_selective` row
      removed as part of this phase.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| The generic engine silently changes an argv and the change is only found once a real file converts wrongly | The per-profile argv-pinning tests are written against the strings `main` produces today, before the engine is rewritten; any diff has to be argued in the PR body |
| The profile value type is shaped around only two formats and needs breaking changes in phases 3-5 | Accepted deliberately: the roadmap sequences phase 1 before the coverage phases so the model is validated cheaply on audio first. Phases 3-5 may extend the value type; they may not push format knowledge back into `jobs.py` |
| `Job` kept as an adapter becomes dead weight after phase 2 | It is one factory call; phase 2 removes or rewrites it as part of the breaking change it already ships |
| Note wording drifts and a degradation stops naming what it cost | Every degradation branch ships with a test asserting its note (`docs/constitution.md`), listed in Verification above |
| A refactor that also "tidies" `cli.py` or `batch.py` would break the empty-diff outcome | The empty-diff check is a Verification item, so it fails the gate rather than being noticed in review |

## Decision log

- 2026-08-25: Two design diagrams rather than one — `degradation-ladder.md`
  decides the order of attempts, `stream-decision.md` decides one stream's fate.
  `docs/design.md` requires one decision per diagram.
- 2026-08-25: The diagrams deliberately use conceptual labels ("the rule's copy
  mask") rather than field names, so a rename during implementation does not rot
  the design artifact.

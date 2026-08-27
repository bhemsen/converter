# Architecture

> Structural, living document — the most volatile artifact. Update whenever a
> change alters components, boundaries, or flows.

## Component map

Target state. `converter/profiles.py` does not exist yet; Phase 1 creates it.
Everything else exists today.

| Component | Responsibility |
| --------- | -------------- |
| `converter/cli.py` | Argument parsing, target-format selection, the interactive prompt, usage errors, exit codes |
| `converter/profiles.py` | One declarative profile per target format: the copy mask, the fallback encoder and the drop reason per stream type, the container flags, the cheap and last-resort attempts the format declares as data, and whether that cheap attempt's mapping is partial by construction |
| `converter/jobs.py` | The generic conversion engine: turns a profile plus a probed stream list into an ordered ladder of attempts, and into the notes a *successful* partial cheap attempt owes. It owns the *order* of the rungs and how the selective rung is built; the profiles own what each declared rung contains |
| `converter/batch.py` | Bounded parallel execution, the per-file outcome, progress reporting, the aggregate summary and the process exit code |
| `converter/paths.py` | Input discovery, output-path construction, tree mirroring, collision detection, Windows path-length diagnosis |
| `converter/ffmpegtool.py` | Locating ffmpeg and ffprobe, building argv, running without a shell, probing streams |
| `converter/__main__.py` | The `python -m converter` entry point |

## Boundaries

The internal import graph is acyclic today and must stay that way:
`ffmpegtool`, `paths` and `profiles` are leaves, `jobs` depends on `ffmpegtool` +
`profiles`, `batch` depends on `jobs` + `ffmpegtool` + `paths` + `profiles`,
`cli` depends on all of them, `__main__` depends only on `cli`.

- `converter/profiles.py` must be a **leaf**: no internal imports at all. This is
  what makes the constitution's "a target format is data, not code" structurally
  enforceable rather than a matter of taste — a module that cannot import anything
  cannot hold logic. It is also why profiles are declarative Python structures
  rather than a TOML or JSON file: the profiles are not user-editable at runtime
  (encoder tuning is an explicit non-goal), so a data file would buy a parser and
  a schema validator while giving up type checking and ruff's view of the code.
- `jobs.py` may import `profiles` and `ffmpegtool`, and nothing else.
- `batch.py` imports `profiles` only for the type it is handed: it carries a
  profile from `cli.py` to the engine and reads the label for its progress bar,
  and asks `jobs.py` for every attempt. A profile field read for a *conversion*
  decision in `batch.py` is format knowledge in the wrong module.
- Nothing below `cli.py` may import `cli`.
- `paths.py` knows nothing about ffmpeg, and `ffmpegtool.py` knows nothing about
  batches, jobs or profiles. Both are reusable in isolation, and both are tested
  in isolation.
- The subprocess boundary is `ffmpegtool.run()`. It is the single place the test
  suite stubs, which is why the suite passes with no ffmpeg installed.

## Key flows

1. **Happy path.** `cli` resolves the target profile and the output root,
   `paths.find_sources` collects the inputs, `paths.find_collisions` refuses up
   front if two inputs would write to the same output, then `batch.run_batch`
   runs the profile's cheapest attempt per file through the engine in `jobs.py`.
   Every profile shipped or currently specced declares its cheap attempt
   **partial by construction** (`partial_mapping=True`: MP4's blind
   `?`-selectors reach no attachment, WAV's single index reaches no second
   audio stream, and phases 3-5 follow the same shape), so a success spends one
   `ffprobe` round-trip to verify what that mapping could not carry, and every
   source stream it missed becomes a note. The verification reads the
   profile's *structural* verdicts only — whether it declares a rule for the
   stream's type, and how many streams of that type it holds — never a
   codec-level one: the attempt exited 0, so what it did with a codec worked.
   That reading is a *prediction* from the mapping, so a run that is about to
   name a loss spends one further `ffprobe`, on the output this time, and keeps
   only the drops the written file does not in fact contain — MP4 and MOV put a
   `tmcd` timecode track back that no selector mapped (issue #66). A conversion
   that gives nothing up never reaches that second probe.
   A profile whose cheap attempt is *exhaustive* would skip this probe
   entirely, but no shipped or currently specced profile is one — the
   probe-on-success branch is presently the only path a successful conversion
   takes; see the 2026-08-26 (issue #41) entries in
   `docs/specs/archive/spec-profile-registry.md`'s Decision log.
2. **Degradation.** The attempt exits non-zero, so *now* `ffmpegtool.probe_streams`
   describes the file. The engine matches each stream against the profile's copy
   mask: streams the mask accepts pass through unchanged — as a literal `copy`, or
   as the cheap in-kind transcode the rule declares, which is how a text subtitle
   becomes `mov_text` — streams it does not are re-encoded with the profile's
   fallback encoder, and streams are dropped when the container cannot hold that
   stream type at all, when it is already holding as many streams of the type as
   it can, or when the rule declares no fallback. Every sacrifice becomes a note
   on the attempt. The last rung is the full re-encode the profile declares; a
   profile may declare none, and then the rung before it ends the ladder. The
   order of attempts and the per-stream branch are drawn in
   `docs/design/degradation-ladder.md` and `docs/design/stream-decision.md`.
3. **Idempotent re-run.** An output that already exists and no `--overwrite` makes
   the file `skipped` without starting a process, so a second run over a finished
   tree does no work for the files it already converted. A source whose output
   path would be its own input path is `skipped` too — reported rather than passed
   over in silence, and counted, per `docs/design/source-selection.md`.
4. **Failure.** The partially written output is removed, the file is recorded as
   `failed` with ffmpeg's stderr, the batch keeps going for every other file, and
   the process exits 1 at the end.
5. **Unsupported.** Reached only from the failure-side probe of step 2: when the
   source carries no stream of any type the target profile has a rule for at
   all, `jobs.py` reports that as a distinguishable signal instead of climbing
   the rest of the ladder, `batch.py` maps it onto a counted `unsupported`
   outcome, and the partially written output is removed the same way a
   `failed` one is -- but the outcome does not set the exit code, so a re-run
   over a mixed tree reports the same thing rather than failing forever
   (`docs/specs/archive/spec-target-driven-cli.md`).

## Where new code goes

- **A new target format** → one profile entry in `converter/profiles.py` plus its
  test. Nothing else. If the change needs a diff in `cli.py`, `batch.py` or
  `paths.py`, the profile model is wrong and that is the bug to fix.
- **A new CLI flag or prompt question** → `cli.py`.
- **New path semantics** (discovery rules, naming, mirroring) → `paths.py`.
- **A new detail of how ffmpeg is invoked** (a base flag, a probe field, executable
  resolution) → `ffmpegtool.py`.
- **A new degradation *strategy*** — not a new format, but a new *kind* of rung in
  the ladder → the generic engine in `jobs.py`.
- **Concurrency, progress or result aggregation** → `batch.py`.

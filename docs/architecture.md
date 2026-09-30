# Architecture

> Structural, living document — the most volatile artifact. Update whenever a
> change alters components, boundaries, or flows.

## Component map

Target state. `converter/profiles.py` does not exist yet; Phase 1 creates it.
Everything else exists today.

| Component | Responsibility |
| --------- | -------------- |
| `converter/cli.py` | Argument parsing, target-format selection, the interactive prompt, usage errors, exit codes |
| `converter/profiles.py` | One declarative profile per target format: the copy mask, the fallback encoder and the drop reason per stream type, the container flags, the ffmpeg muxer that writes it, the cheap and last-resort attempts the format declares as data, and whether that cheap attempt's mapping is partial by construction |
| `converter/jobs.py` | The generic conversion engine: turns a profile plus a probed stream list into an ordered ladder of attempts, and into the notes a *successful* partial cheap attempt owes. It owns the *order* of the rungs and how the selective rung is built; the profiles own what each declared rung contains |
| `converter/batch.py` | Bounded parallel execution, the per-file outcome, the progress bar, the aggregate summary and the process exit code; hands each result to a caller-supplied callback |
| `converter/report.py` | Rendering results: the human text lines and the `--json` records (JSON Lines), both over `batch.Result` / `batch.Summary` |
| `converter/paths.py` | Input discovery, output-path construction, tree mirroring, collision detection, Windows path-length diagnosis |
| `converter/ffmpegtool.py` | Locating ffmpeg and ffprobe, building argv, running without a shell, probing streams; keeps every running process in a registry it can terminate, bound to a Job Object on Windows |
| `converter/__main__.py` | The `python -m converter` entry point |

## Boundaries

The internal import graph is acyclic today and must stay that way:
`ffmpegtool`, `paths` and `profiles` are leaves, `jobs` depends on `ffmpegtool` +
`profiles`, `batch` depends on `jobs` + `ffmpegtool` + `paths` + `profiles`,
`report` depends on `batch`, `cli` depends on all of them, `__main__` depends
only on `cli`.

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

1. **Happy path.** `cli` resolves the target profile, `paths.input_root` gives
   the input root — `INPUT` itself, or a file's parent as typed — and `cli`
   derives the output root from it. `paths.select_input` then collects the
   inputs: a directory walk through `paths.find_sources`, or the named file alone
   (`docs/design/source-selection.md`). `paths.find_collisions` refuses up front
   if two inputs would write to the same output, then `batch.run_batch`
   runs the profile's cheapest attempt per file through the engine in `jobs.py`
   — or, for a probe-first profile (`web`), for which the engine offers no cheap
   attempt, probes first and starts at the selective rung.
   Every attempt writes to `<output>.partial` (with `-f` naming the profile's
   muxer, since the suffix no longer tells ffmpeg the format); the partial is
   moved into place only after the success-side verification below has run
   against it, so the output path never holds a file whose notes were not
   computed.
   Each result goes to the `on_result` callback `cli` passed in — a `report`
   renderer that writes text lines, or JSON records under `--json`.
   Every profile shipped or currently specced *with a cheap attempt* declares it
   **partial by construction** (`partial_mapping=True`: MP4's blind
   `?`-selectors reach no attachment, WAV's single index reaches no second
   audio stream, and phases 3-5 follow the same shape), so a success spends one
   `ffprobe` round-trip to verify what that mapping could not carry, and every
   source stream it missed becomes a note. The verification reads the
   profile's *structural* verdicts only — whether it declares a rule for the
   stream's type, and how many streams of that type it holds — never a
   codec-level one: the attempt exited 0, so what it did with a codec worked.
   The one licensed exception is a profile whose cheap attempt forces a
   single declared encoder unconditionally, for every input: such a profile
   may also declare what that encoder cannot hold, read from the same source
   probe and naming the surviving stream when it fires — an encoder claim,
   not a codec-level verdict about what this particular attempt did, since
   that attempt has no copy branch it could have taken instead (`jpg`, `gif`
   and `avif`'s `Profile.alpha_unsupported`,
   `converter.jobs.transparency_notes`,
   `docs/specs/archive/spec-within-stream-loss-notes.md`). A copy-based cheap attempt
   (`webp`) earns no such note — that is the boundary's limit.
   That structural reading is a *prediction* from the mapping, so a run that
   is about to name a loss spends one further `ffprobe`, on the output this
   time, and keeps only the drops the written file does not in fact contain
   — MP4 and MOV put a `tmcd` timecode track back that no selector mapped
   (issue #66). A conversion that gives nothing up never reaches that
   second probe.
   A profile whose cheap attempt is *exhaustive* would skip this probe
   entirely, but no shipped or currently specced profile is one — the
   probe-on-success branch is the only path a successful *cheap attempt*
   takes. A probe-first profile (`web`) has no cheap attempt at all and succeeds
   on the selective rung instead; see the 2026-08-26 (issue #41) entries in
   `docs/specs/archive/spec-profile-registry.md`'s Decision log.
2. **Degradation.** The attempt exits non-zero, so *now* `ffmpegtool.probe_streams`
   describes the file. Each stream is first resolved to a rule — by its
   disposition when it is an attached picture and the profile declares a rule for
   one, otherwise by its type — and the engine then matches it against that
   rule's copy mask: streams the mask accepts pass through unchanged — as a
   literal `copy`, or as the cheap in-kind transcode the rule declares, which is
   how a text subtitle becomes `mov_text` — streams it does not are re-encoded
   with the profile's fallback encoder, which may itself carry a
   source-dependent option: a value the rule declares and the engine appends
   only when a further probed source property — independent of whichever one
   routed the stream to this branch — says the fallback would otherwise need
   it (`webm`'s video rule is the only one that declares one today, an
   alpha-carrying pixel format forced when the source's probed `pix_fmt` is not
   already alpha-free — a stream the copy mask accepts never reaches this
   option, since it never reaches the fallback encoder at all,
   `docs/specs/archive/spec-webm-alpha.md`) — and streams are dropped when the
   container cannot hold that stream type at all, when it is already holding as
   many streams of the type as it can, or when the rule declares no fallback.
   Every sacrifice becomes a note on the attempt. The last rung is the full
   re-encode the profile declares; a profile may declare none, and then the
   rung before it ends the ladder. The order of attempts and the per-stream
   branch are drawn in `docs/design/degradation-ladder.md` and
   `docs/design/stream-decision.md`.
3. **Idempotent re-run.** An output that already exists and no `--overwrite` makes
   the file `skipped` without starting a process (a stale `<output>.partial` from
   a killed run is removed first), so a second run over a finished
   tree does no work for the files it already converted. A source whose output
   path would be its own input path is `skipped` too — reported rather than passed
   over in silence, and counted, per `docs/design/source-selection.md`.
4. **Failure.** The `.partial` file is removed — an existing output is left
   untouched even under `--overwrite`, since only the rename replaces it — the
   file is recorded as
   `failed` with ffmpeg's stderr, the batch keeps going for every other file, and
   the process exits 1 at the end.
5. **Unsupported.** Reached only from a probe that precedes an attempt — the
   failure-side probe of step 2, or a probe-first profile's up-front probe: when the
   source carries no stream of any type the target profile has a rule for at
   all, `jobs.py` reports that as a distinguishable signal instead of climbing
   the rest of the ladder, `batch.py` maps it onto a counted `unsupported`
   outcome, and the `.partial` file is removed the same way a
   `failed` one is -- but the outcome does not set the exit code, so a re-run
   over a mixed tree reports the same thing rather than failing forever
   (`docs/specs/archive/spec-target-driven-cli.md`).
6. **Termination.** Ctrl+C / SIGINT, or SIGTERM on POSIX, raises in the main
   thread (`KeyboardInterrupt`, or `ffmpegtool.Terminated` from the SIGTERM
   handler), which calls `ffmpegtool.terminate_all`: the registry closes to new
   spawns and every running process is killed and reaped. Each worker sees the
   shutdown flag after its `run()` returns, deletes its own `.partial` and stops
   without a result; the main thread waits for them, then removes any partial
   still in flight. The run exits 130 or 143 without a summary. A Windows
   `TerminateProcess` cannot be caught: the Job Object kills ffmpeg with the
   converter, and the next run's sweep removes the partial
   (`docs/specs/archive/spec-abort-safe-writes.md`).

## Where new code goes

- **A new target format** → one profile entry in `converter/profiles.py` plus its
  test. Nothing else. If the change needs a diff in `cli.py`, `batch.py` or
  `paths.py`, the profile model is wrong and that is the bug to fix.
- **A new CLI flag or prompt question** → `cli.py`.
- **A new output format or record field** → `report.py`.
- **New path semantics** (discovery rules, naming, mirroring) → `paths.py`.
- **A new detail of how ffmpeg is invoked** (a base flag, a probe field, executable
  resolution) → `ffmpegtool.py`.
- **A new degradation *strategy*** — not a new format, but a new *kind* of rung in
  the ladder → the generic engine in `jobs.py`.
- **Concurrency, progress or result aggregation** → `batch.py`.

# Spec: abort-safe-writes (roadmap phase 12)

> Created: 2026-09-28

Write every output under a temporary name and move it into place only once the
conversion has succeeded and been accounted for; when the run is terminated, stop
the ffmpeg processes it started and leave no half-written file behind. This spec
carries no lifecycle state — acceptance is the spec merged on the default branch
with a milestone and issues, and all progress lives in the GitHub issues and
milestone. A completed spec is moved to `docs/specs/archive/`.

## The gap

- ffmpeg writes straight to the final path with `-y` (`ffmpegtool.build_argv`).
  A conversion that is still running, or was killed, leaves a file at the output
  path that looks finished — and the next run **skips it** as already converted,
  because the skip test is `task.dst.exists()` (`batch._attempt_conversion`).
- `batch._discard_partial_output` removes the output only on a *failed*
  conversion that the process itself observed; a kill never reaches it. With
  `--overwrite`, ffmpeg truncates the previous good output the moment it starts,
  so a failure then leaves neither the old file nor a new one.
- There is no signal handling. On Ctrl+C the batch cancels queued files, but
  "conversions already in flight still finish the file they are on"
  (`batch.run_batch`), and a SIGTERM kills Python while its ffmpeg children run
  on.
- On Windows a parent — *videothek* runs the converter from Node.js — can only
  terminate the child with `TerminateProcess`: Node maps every signal name to it,
  Python cannot catch it, and the ffmpeg grandchild survives
  (`docs/prior-art.md`, *Abort-safe writes*).

## Outcome

- [ ] Every conversion writes to `<output>.partial`, and the final path appears
      only after ffmpeg succeeded **and** the success-side verification (the
      probe of `docs/design/degradation-ladder.md`) ran against the partial file.
- [ ] A failed conversion leaves no `.partial` file; with `--overwrite`, a
      failed conversion leaves the previous output untouched.
- [ ] A stale `<output>.partial` from an earlier, killed run is removed by the
      next run that targets the same output — converted or skipped.
- [ ] SIGTERM (POSIX) and Ctrl+C / SIGINT (all platforms) terminate every running
      ffmpeg, delete every in-flight `.partial`, and exit 143 and 130
      respectively; no ffmpeg process outlives the run.
- [ ] On Windows, when the converter is killed with `TerminateProcess`, its
      ffmpeg processes die with it (a Job Object), and the partial file is
      removed by the next run.
- [ ] Every profile declares its ffmpeg muxer as data, and the argv writing a
      partial names it with `-f`, so ffmpeg writes the same format it chose from
      the extension before.
- [ ] For every one of the 17 targets the output is written by the same muxer
      as before this phase (the one ffmpeg picked from the extension — measured):
      same container, same streams and codecs by `ffprobe`, and byte-identical
      wherever the conversion only copies streams.
- [ ] `docs/constitution.md`, `docs/architecture.md` and `README.md` carry the
      change.

## The muxer table — measured, ffmpeg 9.0, 2026-09-28

The muxer ffmpeg selects from each target suffix, read from `Output #0, <muxer>`:

| Suffix | Muxer | Suffix | Muxer |
|---|---|---|---|
| `.mp4` | `mp4` | `.opus` | `opus` |
| `.mkv` | `matroska` | `.ogg` | `ogg` |
| `.webm` | `webm` | `.png` | `image2` |
| `.mov` | `mov` | `.jpg` | `image2` |
| `.mp3` | `mp3` | `.webp` | `webp` |
| `.m4a` | `ipod` | `.avif` | `avif` |
| `.flac` | `flac` | `.gif` | `gif` |
| `.wav` | `wav` | `.tiff` | `image2` |
|  |  | `.bmp` | `image2` |

Also measured: `-c copy out.mp4.partial` fails with "Unable to choose an output
format"; the same with `-f mp4` exits 0, as do `-f image2`, `-f apng` and
`-f ipod` on `.partial` names.

## Scope

### In scope

- `converter/profiles.py`: a required `Profile.muxer: str` on every profile, the
  values above.
- `converter/ffmpegtool.py`: `build_argv` gains a keyword `output_format: str |
  None = None`, emitted as `-f <muxer>` directly before the output path; `run()`
  becomes a tracked, killable process — a registry of live `Popen` objects, a
  `terminate_all(timeout)` that kills and reaps them, and on Windows a Job Object
  with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` every ffmpeg/ffprobe is assigned to.
- `converter/batch.py`: write to `<dst>.partial`, verify against it, then move it
  into place; remove it on failure; sweep a stale one per task; on interrupt,
  delete every in-flight partial after `terminate_all`.
- `converter/cli.py`: a SIGTERM handler that runs the same termination as Ctrl+C
  and exits 143.
- Tests for every outcome, with the subprocess boundary stubbed.
- `README.md`: the partial-file behaviour, the reserved `.partial` name, exit
  143, and what each platform guarantees on a kill.
- Foundation carriers authored **in this spec PR**: `docs/constitution.md` (the
  partial-output principle, the tech-stack row), `docs/architecture.md`
  (component map, Key flow 1, a termination flow).

### Out of scope

- **SIGKILL of the Python process on POSIX.** Nothing in-process can react to it.
  ffmpeg stays in the converter's process group (see Prior decisions), so a
  caller that kills the group takes ffmpeg down too; the partial is swept by the
  next run. `PR_SET_PDEATHSIG` would need `preexec_fn`, which the Python docs
  call unsafe in a threaded process.
- **Walking the tree for stray `.partial` files.** Only the exact partial path of
  a task in the current run is ever deleted.
- **A graceful ffmpeg stop** (`q` on stdin) — it produces a playable truncated
  file, which is worthless when the partial is deleted anyway.
- **JSON output** — phase 11. This phase adds exit 143 to the README's exit-code
  table; under phase 11's contract a 143 stream is simply one without a summary.

## Constraints

- `docs/constitution.md`: no shell, argv lists only; ≤50 lines per function;
  annotations and docstrings; **no second runtime dependency** — the Job Object
  is reached through `ctypes` from the standard library.
- `docs/architecture.md`: `ffmpegtool` knows nothing about batches, jobs or
  profiles — its process registry holds processes, never output paths; the
  partial paths belong to `batch`. `profiles` stays a leaf.
- The subprocess boundary stays `ffmpegtool.run()`: the suite keeps stubbing it
  there and passes without ffmpeg. The existing `run` stub writes `argv[-1]`,
  which becomes the partial path — the stub keeps working unchanged.
- Windows is first-class: every behaviour has a Windows answer, even where it is
  "the next run cleans up".

## Prior art

- [Abort-safe writes and child-process termination (Phase 12)](../prior-art.md#abort-safe-writes-and-child-process-termination-phase-12)
  — Job Objects with `KILL_ON_JOB_CLOSE` via `ctypes`; Node's `kill()` is an
  uncatchable `TerminateProcess` on Windows; POSIX signal handlers run in the main
  thread only and must not shut down the executor (cpython#121649); 128+n exit
  codes; `os.replace` can raise `PermissionError` on Windows; the measured `-f`
  requirement.

## Human prerequisites

none

## Prior decisions

| Decision | Rationale | Date |
|---|---|---|
| Every profile declares `muxer`, a required field, set to the muxer ffmpeg itself chose from the suffix (table above) | A `.partial` name defeats ffmpeg's extension-based choice (measured). Declaring the *same* muxer keeps every output byte-identical; a required field makes a future format declare it, which keeps "a target format is data" true | 2026-09-28 |
| `-f` is added by `build_argv(..., output_format=...)`, not baked into each profile's attempt options | The attempt options are what `tests/test_argv.py` pins per profile; the output format belongs to the write, not to a rung, and adding it at the one place the output path is placed keeps every existing argv test valid | 2026-09-28 |
| The partial file is renamed into place **after** the success-side verification, which probes the partial | The output path then only ever holds a file whose notes were computed. A kill between ffmpeg's exit and the rename leaves a partial that the next run sweeps and redoes — never a finished-looking file whose losses were never reported | 2026-09-28 |
| With `--overwrite`, the previous output stays in place until the rename replaces it | Today ffmpeg truncates it at start, so a failed `--overwrite` destroys a good file. Writing elsewhere first removes that hazard for free | 2026-09-28 |
| The stale-partial sweep deletes exactly `<dst>.partial` for each task of the current run, at the start of that task — whether it converts or is skipped | The only cleanup a Windows kill allows. Scoping it to paths this run computed means the tool never deletes a file it cannot prove it wrote; `<output>.partial` is documented as reserved | 2026-09-28 |
| ffmpeg stays in the converter's own process group (no `start_new_session`) | A terminal's Ctrl+C and a caller's group-wide kill (`docker stop`, systemd, `kill -- -PGID`) then still reach ffmpeg directly. ffmpeg spawns no children of its own, so killing the `Popen` kills the whole tree; the explicit registry covers a SIGTERM aimed at the Python process alone | 2026-09-28 |
| Termination: the signal handler (main thread) sets the interrupt flag and calls `ffmpegtool.terminate_all`, which kills and reaps every registered process; `batch` then deletes every in-flight partial before the exception propagates | cpython#121649: a handler must not shut the executor down. Reaping before deleting matters on Windows, where a file cannot be removed while the killed process still holds it | 2026-09-28 |
| SIGTERM exits 143, SIGINT keeps 130 | The 128+n convention a Node parent or a shell expects (`docs/prior-art.md`). Windows has no catchable SIGTERM; a `TerminateProcess` exit code is whatever the terminator chose | 2026-09-28 |
| The Job Object is created once per process, lazily, and each spawned ffmpeg/ffprobe is assigned right after `Popen`; any failure to create or assign it is reported once on stderr and the run continues | Best effort: nested jobs work from Windows 8 on, and a missing job only loses the orphan protection, never a conversion. ffmpeg spawns no children, so the window between spawn and assignment cannot leak a grandchild | 2026-09-28 |
| A task interrupted mid-conversion produces no `Result` | As today (`batch._interruptible` raises instead of fabricating one); under phase 11 a stream without a summary is incomplete | 2026-09-28 |
| OPEN — The temporary name: `<name><ext>.partial` (needs `-f`), `<stem>.partial<ext>` (no `-f`, but the next directory walk would collect it as a *source*), or a hidden `.<name><ext>.partial`? | resolved at the spec-acceptance gate | — |
| OPEN — `os.replace` on Windows when the target is held open (scanner, indexer, a player): retry a bounded number of times, or fail at once? | resolved at the spec-acceptance gate | — |

## Tracking

- Milestone: filled at the acceptance gate
- Issues: created from this spec once it is merged (one per implementable step)

Each issue references this spec path in its body.

## Verification

- [ ] Verify passes (`.\.venv\Scripts\python.exe scripts\verify.py`), under 60 s.
- [ ] `tests/test_profiles.py` pins every profile's `muxer` against the table.
- [ ] `tests/test_ffmpegtool.py`: `build_argv` places `-f <muxer>` directly
      before the output path and emits nothing without `output_format`; `run`
      still passes no shell and closes stdin; the registry holds a process only
      while it runs; `terminate_all` kills and reaps every registered process.
- [ ] `tests/test_batch.py`, subprocess stubbed:
  - [ ] a success writes the partial, verifies it, then the final path appears
        and no partial remains;
  - [ ] a failure on every rung leaves neither a partial nor a new output;
  - [ ] `--overwrite` with a failing conversion leaves the old output's bytes
        unchanged;
  - [ ] a stale partial beside a missing output is removed and the file
        converts; one beside an existing output is removed and the file is
        skipped;
  - [ ] an interrupt with conversions in flight calls `terminate_all` and
        leaves no partial.
- [ ] `tests/test_cli.py`: SIGTERM (POSIX only, skipped on Windows) exits 143 and
      leaves no partial; Ctrl+C still exits 130.
- [ ] `tests/test_argv.py` passes unchanged.
- [ ] Tests for whichever way each OPEN row is resolved.
- [ ] **QA smoke test with real ffmpeg** (paths from `docs/workflow.md`):
  - [ ] all 17 targets convert; compared with the same conversions run on
        `v3.1.0`, each output has the same `format_name` and the same streams and
        codecs by `ffprobe`, and a pure remux (`--to mkv` of an h264/aac `.mp4`)
        is byte-identical — re-encodes are not compared byte for byte, because
        multi-threaded encoders need not be deterministic;
  - [ ] a long re-encode killed by Ctrl+C: exit 130, no `.partial`, no ffmpeg
        left in Task Manager;
  - [ ] the same run killed from Node.js with `child.kill()` on Windows: no
        ffmpeg left running; the next run removes the partial and converts;
  - [ ] on Linux (WSL or CI runner), `kill -TERM` on the converter: exit 143, no
        partial, no ffmpeg left;
  - [ ] `--overwrite` over a good output with a source that fails: the old
        output survives.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| A declared muxer differs from what the extension chose, silently changing output | The table is measured, pinned by a test, and the QA run compares every target's `format_name` and streams against `v3.1.0` |
| `image2` on a `.partial` name treats it as a pattern or needs `-update 1` | Measured: `-f image2` on `out.png.partial` exits 0 with one image; the QA run covers every image target |
| Replacing `subprocess.run` with `Popen` loses its timeout/cleanup semantics | `run()` keeps its signature and `CommandResult`; `communicate()` plus `kill()` on timeout mirrors `subprocess.run`'s own implementation |
| The Job Object code is Windows-only and untested on Linux CI | The Windows CI matrix runs it; a test asserts the assignment is attempted and that a failure only warns |
| Signal handling differs between platforms and flakes in CI | The SIGTERM test runs on POSIX only; the termination logic itself is tested through `terminate_all` with fake processes on both |

## Decision log

- 2026-09-28: Planned from the roadmap seed of the same day (PR #136). The
  muxer table was measured for this spec. The seed's open questions on the
  SIGTERM code and partial handling are settled above; the temporary name and the
  Windows rename retry stay open for the gate.

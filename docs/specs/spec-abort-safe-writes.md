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
- `converter/paths.py`: `partial_for(dst)`.
- `converter/ffmpegtool.py`: `build_argv` gains a keyword `output_format: str |
  None = None`, emitted as `-f <muxer>` directly before the output path; `run()`
  becomes a tracked, killable process — a registry of live `Popen` objects, a
  shutdown flag, `terminate_all(timeout)`, `terminated()`, the `Terminated`
  exception, and a function that binds the current process to a Job Object with
  `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` on Windows.
- `converter/batch.py`: write to `<dst>.partial`, verify against it, then move it
  into place; remove it on failure; sweep a stale one per task; on interrupt,
  delete every in-flight partial after `terminate_all`.
- `converter/cli.py`: the SIGTERM handler, the 143 mapping, and binding the
  process to the Job Object on Windows.
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

**Overlap with phase 11.** Both phases touch `batch.run_batch` (phase 11 adds
`on_result`; this phase changes its wait loop and interrupt path), `cli.main`'s
interrupt branch, and the README's exit-code table. They are independent in
design; whichever merges second rebases onto the other. A killed attempt never
reaches `on_result`.

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
| The stale-partial sweep deletes exactly `<dst>.partial` for each batch task, at the start of that task — whether it converts or is skipped as already existing; not for self-write skips (decided in `cli`, and their output is their source) and never under `--dry-run`. A sweep that cannot delete (a locked file on Windows) is ignored; ffmpeg's own failure to open the path then reports it | The only cleanup a Windows kill allows, scoped to paths this run computed. `<output>.partial` is **reserved**: two converter runs over the same tree at once are unsupported, since one run's sweep would delete the other's live partial | 2026-09-28 |
| The partial path is built by a new `paths.partial_for(dst) -> Path` (`dst` plus `.partial`), and any path-length diagnosis for an output is made on the partial path, the longer of the two | `docs/architecture.md`: output-path construction belongs to `paths`; `.partial` adds 8 characters, which is what can cross Windows' `MAX_PATH` first | 2026-09-28 |
| ffmpeg stays in the converter's own process group (no `start_new_session`) — a deliberate departure from the prior-art note ("give it its own session") and the phase-12 roadmap impact line, which this PR amends | A terminal's Ctrl+C and a caller's group-wide kill (`docker stop`, systemd, `kill -- -PGID`) then still reach ffmpeg directly. ffmpeg spawns no children of its own, so killing the `Popen` kills the whole tree; the registry covers a SIGTERM aimed at the Python process alone. The research's reason for a new session — killing a whole group — does not apply to a child with no children | 2026-09-28 |
| **Signals.** `cli.main` installs, for the convert command only, a SIGTERM handler that does nothing but `raise ffmpegtool.Terminated()`; SIGINT keeps Python's default `KeyboardInterrupt`. `Terminated` subclasses `BaseException`, so `convert_one`'s `except Exception` never swallows it. `cli.main` maps `KeyboardInterrupt` to 130 and `Terminated` to 143 | The handler runs in the main thread and must not take locks or shut down the executor (cpython#121649); raising is the only way out of a wait that PEP 475 would otherwise resume. Keeping SIGINT on its default path leaves today's 130 behaviour intact | 2026-09-28 |
| **Termination state.** `ffmpegtool` owns one process-wide shutdown flag. `terminate_all(timeout=10)` sets it, kills every registered process and reaps each for up to `timeout` seconds. Once the flag is set, `run()` refuses to spawn and raises `Terminated`; a process spawned concurrently is killed on registration. The registry lock is a plain `Lock`, never touched from the handler | Closes the race the review found: without a closed registry, a worker whose ffmpeg was killed would treat the kill as an ordinary failure, probe, and start the next rung *after* `terminate_all` had run | 2026-09-28 |
| **Workers after a kill.** A worker checks `ffmpegtool.terminated()` after every `run()` — before it probes, starts the next rung, verifies or renames. When set, it deletes **its own** partial and raises `Terminated`/`KeyboardInterrupt` instead of returning a `Result`. The main thread, after `terminate_all`, waits for the in-flight futures (bounded by the same timeout) and only then removes any partial still listed in `batch`'s in-flight set | Each partial has exactly one owner at any moment, so the main thread's clean-up cannot race a worker's rename; a killed attempt never becomes a `failed` Result, and so never reaches phase 11's `on_result` | 2026-09-28 |
| The main loop waits with `concurrent.futures.wait(..., timeout=0.5, return_when=FIRST_COMPLETED)` in a loop rather than blocking in `as_completed` | Whether a blocking lock wait in the main thread is interruptible by Ctrl+C on Windows under Python 3.11-3.13 is unverified; a short poll makes the signal's delivery independent of it | 2026-09-28 |
| SIGTERM exits 143, SIGINT keeps 130 | The 128+n convention a Node parent or a shell expects (`docs/prior-art.md`). Windows has no catchable SIGTERM; a `TerminateProcess` exit code is whatever the terminator chose | 2026-09-28 |
| On Windows, `cli.main` assigns **the converter's own process** to a Job Object with `KILL_ON_JOB_CLOSE` once, at the start of the convert command, before any spawn; every ffmpeg/ffprobe it starts inherits the membership. Failure to create or assign is reported once on stderr and the run continues | Assigning the parent removes the spawn-then-assign window entirely and needs no lazy, thread-safe creation. Nested jobs work from Windows 8 on; a missing job only loses the orphan protection, never a conversion. When the converter dies, the OS closes the job handle and kills what is left | 2026-09-28 |
| A task interrupted mid-conversion produces no `Result` — including one whose ffmpeg was killed, which today would surface as `failed` | Under phase 11 a stream without a summary is incomplete; a killed attempt is not a conversion failure | 2026-09-28 |
| The temporary name is `<name><ext>.partial` (`clip.mp4.partial`) | Resolved at the spec-acceptance gate, 2026-09-28: `.partial` is no source suffix, so the next directory walk never collects it (`clip.partial.mp4` would be, and would need an exclusion rule in `paths`); it is visibly unfinished in any file browser, where a hidden `.clip.mp4.partial` would hide a kill's leftovers from the user on POSIX and not even hide it on Windows. The cost is the declared muxer, measured above | 2026-09-28 |
| On Windows only, and only on `PermissionError`, the rename is retried up to 5 times with exponential backoff starting at 0.1 s (0.1, 0.2, 0.4, 0.8, 1.6 s — about 3 s in all); after the last failure the file is `failed` with the lock as its reason, the partial is deleted, and an existing output is left untouched. POSIX renames once | Resolved at the spec-acceptance gate, 2026-09-28: a scanner or indexer briefly holding the target is routine on Windows, and failing a finished conversion over it would be the worse outcome; the bound keeps a genuinely locked target (a player holding it open) from stalling the run. The pattern several projects use (`docs/prior-art.md`) | 2026-09-28 |

### Implementation notes from the acceptance review

- **The Job Object handle lives as long as the process.** The converter is itself
  in the job, so closing the handle kills it: keep it in a module-level reference,
  never `CloseHandle` it, never let a wrapper's finaliser close it. `tests/test_cli.py`
  calls `cli.main` repeatedly inside pytest, so the tests stub the binding.
- **The shutdown flag is one-way per process.** Tests reset it through a fixture;
  production never resets it.
- **Check the flag again directly before `os.replace`.** A worker can pass the
  post-`run()` check and then reach the rename while the main thread is already
  shutting down. Re-checking immediately before the rename (and deleting the
  partial instead) keeps "the output path only holds a file whose notes were
  reported"; results of futures that still complete during the bounded wait are
  reported through `on_result` / the text renderer rather than dropped.
- **Spawn and register in one critical section**, so a SIGTERM landing between
  `Popen` and registration cannot leave an unregistered process.

## Tracking

- Milestone: [abort-safe-writes](https://github.com/bhemsen/converter/milestone/12)
- Issues: created from this spec once it is merged (one per implementable step)

Each issue references this spec path in its body.

## Verification

- [ ] Verify passes (`.\.venv\Scripts\python.exe scripts\verify.py`), under 60 s.
- [ ] `tests/test_profiles.py` pins every profile's `muxer` against the table.
- [ ] `tests/test_ffmpegtool.py`: `build_argv` places `-f <muxer>` directly
      before the output path and emits nothing without `output_format`; `run`
      still passes no shell and closes stdin; the registry holds a process only
      while it runs; `terminate_all` kills and reaps every registered process;
      `paths.partial_for` appends `.partial`; on Windows, a failed Job Object
      binding only warns.
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
        leaves no partial;
  - [ ] a worker whose `run()` returns after `terminate_all` neither probes nor
        starts another rung nor renames, deletes its partial, and yields no
        `Result`;
  - [ ] after `terminate_all`, `run()` raises `Terminated` without spawning;
  - [ ] a killed success-side probe does not rename the partial;
  - [ ] the sweep skips self-write skips and `--dry-run`, and ignores a partial
        it cannot delete.
- [ ] `tests/test_cli.py`: SIGTERM (POSIX only, skipped on Windows) exits 143 and
      leaves no partial; Ctrl+C still exits 130.
- [ ] `tests/test_argv.py`'s attempt-option pins pass unchanged; its
      `TestRunIsShellFree` (which stubs `subprocess.run`) moves to
      `tests/test_ffmpegtool.py` against `Popen`, and the `test_batch.py` tests
      that assert the output probe targets `task.dst` now expect the partial.
- [ ] Tests pin the rename retry: on a stubbed `PermissionError`, Windows retries
      with the stated backoff (sleep stubbed) and ends `failed` with the partial
      removed and the old output intact; POSIX does not retry; a success on the
      third try converts.
- [ ] **QA smoke test with real ffmpeg** (paths from `docs/workflow.md`):
  - [ ] all 17 targets convert; compared with the same conversions run on
        `v3.1.0`, each output has the same `format_name` and the same streams and
        codecs by `ffprobe`, and a pure remux into MP4 (`--to mp4` of an
        h264/aac `.mkv`) is byte-identical — not Matroska, whose muxer writes a
        random SegmentUID (measured: two identical `-c copy` runs into `.mkv`
        differ), and not re-encodes, because multi-threaded encoders need not be
        deterministic;
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
| A killed attempt is mistaken for a failure and climbs the ladder | The closed registry plus the worker's post-`run()` check, each pinned by a test |
| Signal handling differs between platforms and flakes in CI | The SIGTERM test runs on POSIX only; the termination logic itself is tested through `terminate_all` with fake processes on both |

## Decision log

- 2026-09-28: Planned from the roadmap seed of the same day (PR #136). The
  muxer table was measured for this spec. The seed's open questions on the
  SIGTERM code and partial handling are settled above; the temporary name and the
  Windows rename retry stay open for the gate.
- 2026-09-28: Acceptance review (REQUEST_CHANGES) addressed: the termination
  race (a killed attempt climbing the ladder, or a killed verification probe
  still renaming) is closed by a shutdown flag in `ffmpegtool`, a registry that
  refuses spawns, and a post-`run()` check in every worker that owns its own
  partial; the SIGTERM handler only raises `Terminated`, mapped to 143; the main
  loop polls instead of blocking; the Job Object binds the converter itself; the
  byte-identity QA check moves from Matroska (random SegmentUID, measured) to an
  MP4 remux; `paths.partial_for`, the sweep's limits, the reserved name and the
  overlap with phase 11 are stated.
- 2026-09-28: Spec-acceptance gate: the temporary name is `<name><ext>.partial`,
  and the Windows rename retries 5 times with exponential backoff from 0.1 s
  before failing. Human prerequisites: none. Accepted.
- 2026-09-29 (issue #143): adding the required `muxer` field breaks three
  hand-built `Profile(...)` test doubles outside `tests/test_profiles.py`
  (`tests/test_argv.py`, `tests/test_batch.py`, `tests/test_batch_containment.py`)
  with a `TypeError` at collection, since none of them own a real target
  format's muxer. Issue #143 scopes the change to `converter/profiles.py` and
  `tests/test_profiles.py` alone, but also requires every existing test to
  stay green; those fixtures are not the profile registry the scope line
  protects; each was given `muxer="mp4"`, an arbitrary but valid value, since
  none of the three tests it feeds inspects the field. No production file
  (`converter/ffmpegtool.py`, `converter/batch.py`, `converter/cli.py`,
  `converter/paths.py`) was touched.
- 2026-09-29 (issue #146, acceptance review round 1): "any path-length
  diagnosis for an output is made on the partial path" needed no new code.
  `paths.ensure_directory` is the only length diagnosis in the tree, and it
  runs on `task.dst.parent` in `batch._stage_output_directories` -- identical
  to `partial_for(task.dst).parent`, since `.partial` is appended to the
  file name, never the directory, so the requirement already held before
  this issue touched anything. The two places a *file*-level length failure
  can surface -- ffmpeg's own stderr (the argv it receives names the
  partial, never `task.dst`) and a failed rename (`Path.replace`'s own
  `OSError` names the partial as its source) -- both already read the
  partial for the same reason, without a dedicated diagnosis wrapper. The
  same review found two related gaps in `batch.py`, fixed in the same
  round: `_climb_ladder`'s own probe can be killed and silently surfaces as
  an ordinary `ProbeError` rather than `Terminated`, so a check was added
  right after it returns; and `Terminated` raised directly by a *new*
  `ffmpegtool.run` spawn attempted after the shutdown flag is already set
  bypasses every explicit check, so `_attempt_conversion` now wraps its
  whole attempt in `except BaseException: delete the partial; raise` as a
  second line of defence.

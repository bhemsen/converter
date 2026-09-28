# Spec: json-output (roadmap phase 11)

> Created: 2026-09-28

`--json` turns a conversion run into a machine-readable stream — one JSON object
per file as JSON Lines on stdout, then one summary object — and the exit codes
become a documented, stable contract. This spec carries no lifecycle state —
acceptance is the spec merged on the default branch with a milestone and issues,
and all progress lives in the GitHub issues and milestone. A completed spec is
moved to `docs/specs/archive/`.

## The gap

The tool's secondary users are defined by "the exit code and parsable output"
(`docs/vision.md`, *Target users*), yet every line it prints is prose. A caller
such as *videothek* — a browser player that runs the converter per file, argv, no
shell — has to scrape `note    a.mkv: …`, `FAILED  a.mkv: …` and
`1 converted, 0 skipped, …`, none of which is a promise. Today:

- `batch._report` writes notes to **stdout** and `FAILED` lines to **stderr**,
  interleaved with the progress bar through `tqdm.write`
  (`converter/batch.py`, `_report`).
- `cli._run_tasks` prints `Using ffmpeg version …` to **stdout** unless `-q`.
- Skips decided before the batch starts (a self-write) are printed by
  `cli._announce_skips`, a second path the batch never sees.
- The summary is `Summary.describe()`, a sentence.
- `batch.Result` holds everything a record needs — task, outcome, attempt label,
  notes, error — but is internal.

## Outcome

- [ ] `converter --to FORMAT --json INPUT [OUTPUT]` writes to stdout **only** JSON
      Lines: one `file` record per file, emitted as that file finishes, then one
      `summary` record — every line a complete JSON object, flushed as written.
- [ ] Every file the run reports on appears exactly once as a `file` record —
      pre-batch skips (self-write), staging failures, and ladder results alike.
- [ ] Under `--json` nothing else reaches stdout: no progress bar, no
      `Using ffmpeg …`, no `note`/`FAILED` prose.
- [ ] The records carry the fields and values in *The record contract* below,
      and a test pins each record type's exact key set.
- [ ] `--json --dry-run` emits one `planned` record per task and a summary.
- [ ] Output without `--json` is byte-identical to today.
- [ ] `README.md` documents the record contract and the exit codes 0/1/2/130 as a
      stable contract, including that 0 covers `skipped` and `unsupported`.
- [ ] `docs/vision.md`, `docs/architecture.md` carry the change (see Scope).

## The record contract

One JSON object per line, terminated by a single `\n` **on every platform**,
written with `json.dumps(..., ensure_ascii=True)` so every line is pure ASCII —
see Prior decisions for why. The bytes go to `sys.stdout.buffer`, not through the
text layer, because on Windows the text layer turns `\n` into `\r\n` (measured,
Python 3.13, piped stdout). The discriminator field is named in the OPEN row below; this
section writes it as `type` as a placeholder.

**`file`** — one per file the run reports on:

| Key | Type | Meaning |
|---|---|---|
| `type` | `"file"` | discriminator |
| `source` | string | the source path, absolute (`Path.absolute()`, not resolved) |
| `output` | string | the output path it maps to, absolute, whether or not it was written |
| `outcome` | `"converted"` \| `"skipped"` \| `"failed"` \| `"unsupported"` | `batch.Outcome`'s value |
| `attempt` | string \| null | the rung that produced the file (`remux`, `selective`, …); `null` unless `converted` |
| `notes` | array of strings | every note and advisory, in the order the text mode prints them; `[]` when none |
| `error` | string \| null | the failure reason — ffmpeg's joined stderr, or the exception text for a staging or unexpected failure; `null` unless `failed` |

**`planned`** — `--dry-run` only, one per task that would convert: `type`,
`source`, `output`. Pre-batch skips still appear as `file` records with
`outcome: "skipped"`. A planned task whose output already exists is still
`planned`: the existing-output check runs inside the batch, which a dry run never
starts — exactly as the text mode lists it today.

**`summary`** — exactly one, last:

| Key | Type | Meaning |
|---|---|---|
| `type` | `"summary"` | discriminator |
| `converted`, `skipped`, `failed`, `unsupported`, `total` | integer | `batch.Summary`'s counts |
| `planned` | integer | `--dry-run`: the number of `planned` records; `0` otherwise. Computed by the renderer, **not** a `batch.Summary` field — adding it there would change `describe()` and the text output |
| `exit_code` | integer | the code the process is about to exit with |
| `dry_run` | boolean | whether this was `--dry-run` |

In a dry run `converted`, `failed` and `unsupported` are `0`, `skipped` counts the
pre-batch skips, and `total` is `planned + skipped`. A run that finds no
candidates writes only a summary with every count `0`, exit 0; the "no
convertible files found" hint stays on stderr.

**An incomplete stream.** Every exit that writes a summary is `0` or `1` from a
finished run. A stream **without** a `summary` — exit 130, or an exit 1 from an
unexpected error that aborted the run — is incomplete: the `file` records already
written stand, and a consumer must discard a trailing line that is not
`\n`-terminated, since an interrupt can cut one mid-write.

The schema is **open**: a consumer must ignore keys it does not know, so a later
phase (phase 14's sidecars) can add a key without breaking it. Removing or
renaming a key, or changing a value's meaning, is a breaking change.

## Exit codes — the contract `README.md` states

| Code | Meaning |
|---|---|
| 0 | nothing failed — `converted`, `skipped` and `unsupported` all count as success |
| 1 | at least one file `failed`, or an unexpected `OSError`/`ValueError` aborted the run (then without a summary) |
| 2 | usage error, a refusal before any conversion (collision, overwrite hazard, a file-name `OUTPUT`), or ffmpeg not found — stdout is empty |
| 130 | interrupted (Ctrl+C / SIGINT) — no summary |

Phase 12 decides the code for SIGTERM; this phase documents only what exists.

## Scope

### In scope

- `converter/cli.py`: the `--json` flag, suppressing the bar and moving
  `Using ffmpeg …` to stderr under `--json`, routing pre-batch skips and
  `--dry-run` through the renderer, and writing the summary.
- `converter/batch.py`: one seam — `run_batch` gains a keyword-only
  `on_result: Callable[[Result], None] | None = None` and calls it once per
  result instead of calling `_report`; `None` means no per-file output. `batch`
  never imports `report` (that would be a cycle); `cli` always passes a renderer.
- A new module `converter/report.py`: the text renderer (today's `_report`
  lines) and the JSON renderer (record building and writing), both pure over
  `Result` / `Summary` plus an output stream.
- Tests: `tests/test_report.py` for the record builders (key sets, nulls,
  absolute paths, ASCII escaping), `tests/test_cli.py` for the end-to-end stream
  with the subprocess stubbed, `tests/test_batch.py` for the callback seam.
- `README.md`: `--json` in the options table, a *Machine-readable output*
  section with the record contract, and the exit-code table.
- Foundation carriers authored **in this spec PR**: `docs/vision.md` (Scope
  *In*), `docs/architecture.md` (component map, import graph, Key flow 1).

### Out of scope

- **JSON for `--list-formats` and `converter mirror`.** Neither converts a file.
  Their behaviour stays exactly as today: `--json --list-formats` prints the prose
  list at exit 0 (the list flag is routed before parsing), and
  `converter mirror --json` is an argparse usage error, exit 2. Adding JSON to
  either later is additive.
- **Progress within a file** — out of scope for the whole videothek idea.
- **SIGTERM, exit 143, partial-file cleanup on a kill** — phase 12.
- **A JSON record for usage errors and refusals.** See Prior decisions.

## Constraints

- `docs/constitution.md`: no shell; ≤50 lines per function; annotations and
  docstrings; comments explain why; one broken file never aborts the batch.
- `docs/architecture.md`: the import graph stays acyclic; `report` may import
  `batch` (for `Result`, `Summary`, `Outcome`) and nothing below it imports
  `report` or `cli`.
- `converter/cli.py` and the new `converter/report.py` name no target format in a
  string literal (the `ast` test).
- Runtime dependencies stay `tqdm` only — `json` is the standard library.
- Verify stays green and under 60 s; the suite stays ffmpeg-free.

## Prior art

- [Machine-readable CLI output (Phase 11)](../prior-art.md#machine-readable-cli-output-phase-11)
  — restic (`message_type`) and cargo (`reason`) emit one object per line on
  stdout with a discriminator and a final summary object; docker documents an
  open schema; none versions its per-line schema in-band.

## Human prerequisites

none

## Prior decisions

| Decision | Rationale | Date |
|---|---|---|
| JSON Lines on stdout, one object per line, flushed per record, written as each file finishes | The prior-art precedent (restic, cargo); a consumer can act on a file before the batch ends, which a single document (`ffprobe -of json`) cannot offer | 2026-09-28 |
| Records are emitted in completion order, not submission order | The batch already reports in `as_completed` order; a consumer keys on `source`, not position | 2026-09-28 |
| `ensure_ascii=True` — every line is pure ASCII | Windows is first-class: a *piped* stdout on Windows — the child-process case — is encoded with the ANSI code page (`cp1252` here, strict errors) unless UTF-8 mode is on (`PYTHONUTF8=1`, default from Python 3.15 per PEP 686), so a non-ASCII file name would raise `UnicodeEncodeError`. `\uXXXX` escapes are valid JSON under any code page and either mode. A POSIX file name that is not valid UTF-8 reaches Python as lone surrogates and is escaped as `\udcXX`, which `JSON.parse` accepts — but a JS consumer cannot turn it back into the original bytes, so such a path is reported, not openable, from JavaScript | 2026-09-28 |
| Lines are written as bytes to `sys.stdout.buffer` with `\n`, flushing after each | Measured: through the text layer a piped stdout on Windows ends lines in `\r\n`. Writing bytes makes the framing identical on every platform; the text layer is flushed first so nothing written earlier is reordered | 2026-09-28 |
| `source` and `output` are absolute via `Path.absolute()`, never `resolve()` | The consumer needs a path independent of the converter's working directory; resolving would rewrite a `subst`/junction path the user chose, contradicting issue #72's as-typed rule | 2026-09-28 |
| `attempt` is `null` unless `converted`; `error` is `null` unless `failed`; `notes` is always an array | One shape per key; a consumer never has to tell `""` from absent | 2026-09-28 |
| `unsupported` records carry the engine's discriminator in `notes`, exactly as the text mode prints it | `batch.Result` already stores it there; a separate key would duplicate it | 2026-09-28 |
| Pre-batch skips (self-write) and staging failures are `file` records like any other | `docs/constitution.md`: "Never report success for a conversion that silently dropped something" — and `_announce_skips` exists so a file the user pointed at and did not get is not passed over; that second print path must not become a JSON-less one | 2026-09-28 |
| Under `--json`, pre-batch skip records are held back and written only once the run is past tool resolution — just before the batch's first record, or straight away when there are no tasks (the path that never resolves tools) | Otherwise a self-write followed by a missing ffmpeg would write `file` records and then exit 2, breaking "exit 2 leaves stdout empty". Text mode keeps printing them where it does today | 2026-09-28 |
| Under `--json`, stdout carries records only; `Using ffmpeg …` moves to stderr (still suppressed by `-q`), and no per-file prose is printed anywhere | "No progress bar and no `Using ffmpeg …` on stdout" was the seed's requirement; the record already carries every note and error, so repeating them on stderr would be noise a consumer has to filter | 2026-09-28 |
| `--json` implies no progress bar, whatever `-q` says | The bar writes to stderr, but a bar that nobody sees is wasted redraws and pollutes a parent's captured stderr log | 2026-09-28 |
| Usage errors and refusals (exit 2) write **no** JSON; stdout stays empty and the reason goes to stderr as today | They happen before any file is reported, and the exit code alone tells a caller the run did nothing. A JSON error record would need a third record type for a case a per-file caller never hits — collisions and hazards need several sources. Additive later if a consumer asks | 2026-09-28 |
| On interrupt (130) or an aborting exit 1, no summary record is written | The run did not finish; a consumer treats a stream without a `summary` as incomplete, which is simpler to state than a summary with a "partial" flag. The `file` records already written stand; a trailing unterminated line is discarded | 2026-09-28 |
| `--json --dry-run` emits `planned` records plus a summary with `dry_run: true` | Keeps `--dry-run` usable from a script; `planned` is its own type because a dry run has no outcome yet | 2026-09-28 |
| The renderers live in a new `converter/report.py`, and `run_batch` takes an optional `on_result` callback | Two output formats over the same `Result` belong in one module rather than in `cli.py` (already ~600 lines) or `batch.py` (whose job is running, not formatting). The text renderer calls the `tqdm.write` **classmethod**, which keeps the bar's cursor handling without needing the bar instance and works with a disabled bar. Existing `tests/test_batch.py` tests that assert `_report`'s lines through `run_batch` move to `tests/test_report.py` with the same expectations | 2026-09-28 |
| The format-literal `ast` check extends to `converter/report.py` | Not required by the vision's no-diff list, but a renderer is exactly where a format name could creep in; the parametrised test covers it for free | 2026-09-28 |
| The foundation carriers are edited in this spec PR | Recorded by `/loopkit:roadmap` for ratification at this gate; phases 6 and 10 are the precedent | 2026-09-28 |
| OPEN — The discriminator's name: `type`, restic's `message_type`, or cargo's `reason`? | resolved at the spec-acceptance gate | — |
| OPEN — Does the schema carry a version in-band — on every record, on the summary only, or not at all? | resolved at the spec-acceptance gate | — |

## Tracking

- Milestone: filled at the acceptance gate
- Issues: created from this spec once it is merged (one per implementable step)

Each issue references this spec path in its body.

## Verification

- [ ] Verify passes (`.\.venv\Scripts\python.exe scripts\verify.py`), under 60 s.
- [ ] `tests/test_report.py` pins, per record type, the exact key set; `null` for
      `attempt`/`error` where specified; `notes: []` when empty; absolute paths;
      a non-ASCII and a lone-surrogate file name escaped to a pure-ASCII line
      that `json.loads` round-trips.
- [ ] `tests/test_cli.py`, subprocess stubbed:
  - [ ] a mixed batch (converted, skipped, failed, unsupported, a self-write)
        yields exactly one `file` record per file and one final `summary` whose
        counts and `exit_code` match the process exit code;
  - [ ] every stdout line parses with `json.loads`; nothing else is on stdout;
  - [ ] `Using ffmpeg …` is on stderr under `--json`, absent with `-q`;
  - [ ] `--json --dry-run` yields `planned` records and `dry_run: true`;
  - [ ] a usage error, a collision refusal, and a self-write plus a missing
        ffmpeg under `--json` all leave stdout empty and exit 2;
  - [ ] a run with no candidates writes one zero `summary`, exit 0;
  - [ ] every line ends in exactly `\n` (bytes captured from `stdout.buffer`),
        on Windows as on Linux;
  - [ ] a single-file `INPUT` works under `--json`;
  - [ ] `--json --dry-run` counts: `planned`, `skipped` = pre-batch skips,
        `total = planned + skipped`;
  - [ ] without `--json`, the existing CLI output tests pass unchanged.
- [ ] `tests/test_batch.py` pins that `run_batch` hands every result to
      `on_result` exactly once, including staging failures, and prints nothing
      per file when `on_result` is `None`.
- [ ] The `ast` format-literal test covers `converter/report.py`.
- [ ] Tests for whichever way each OPEN row is resolved.
- [ ] `git diff main -- converter/jobs.py converter/profiles.py converter/paths.py
      converter/ffmpegtool.py` is empty over the phase.
- [ ] **QA smoke test with real ffmpeg** (paths from `docs/workflow.md`):
  - [ ] `--json --to mp4 <dir> <out>` over a tree with a remuxable file, a
        re-encoded one, an unreadable `.mkv` and an audio-only file: stdout is
        pure JSON Lines, each line `json.loads`-able, the summary last, exit 1;
  - [ ] a re-run reports every file `skipped`, exit 0;
  - [ ] Ctrl+C mid-batch: exit 130, no `summary` line;
  - [ ] a Node.js one-liner (`child_process.spawn` with an argv array, no
        shell) reads the stream line by line and parses every record — the
        videothek shape — including a file named `Übung.mkv`, whose `source`
        comes back intact; this is the piped case where the encoding risk lives.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| A stray `print` reaches stdout under `--json` and breaks a consumer's parser | The end-to-end test parses every stdout line; the text renderer is never installed under `--json` |
| Moving `_report` into `report.py` changes text-mode output | The existing text-mode tests keep their expectations unchanged (the `_report` ones move to `tests/test_report.py`) and must pass |
| Records written from worker threads interleave mid-line | Records are written only from the main thread, in the `as_completed` loop, like `_report` today |
| Windows stdout encoding mangles paths | `ensure_ascii=True`, plus the QA check with a non-ASCII name through the Node spawn pipe |

## Decision log

- 2026-09-28: Planned from the roadmap seed of the same day (PR #136). The seed's
  two open questions — the discriminator's name and in-band versioning — stay
  open for the gate; every other fork is settled above from the codebase, the
  constitution and the Phase 11 prior-art concern.
- 2026-09-28: Acceptance review (REQUEST_CHANGES) addressed: `on_result` is an
  optional callback so `batch` never imports `report`; lines are written as bytes
  so they end in `\n` on Windows too (measured `\r\n` through the text layer);
  pre-batch skip records wait until tools resolve so exit 2 leaves stdout empty;
  dry-run and empty-run summaries, the incomplete-stream rule, the `error` field's
  scope, `--list-formats`/`mirror` behaviour and the `ast` check are now stated.

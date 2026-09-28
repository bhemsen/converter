# Spec: single-file-input (roadmap phase 10)

> Created: 2026-09-28

Let `INPUT` name one file instead of a directory, so a single conversion gets the
degradation ladder, the disposition and alpha handling and the loss notes rather
than sending the user back to raw ffmpeg. This spec carries no lifecycle state —
acceptance is the spec merged on the default branch with a milestone and issues,
and all progress lives in the GitHub issues and milestone. A completed spec is
moved to `docs/specs/archive/`.

## The gap

`INPUT` must be a directory today. `converter --to mp3 song.flac out` reaches
`paths.find_sources`, which raises `NotADirectoryError`, and `cli._selected_pairs`
turns that into `error: input directory does not exist: song.flac`, exit 2 — a
message that is also wrong, since the path exists. The only workaround is a
directory holding nothing but that one file, or raw ffmpeg, which converts the
file but names nothing it gave up.

## The one model this spec follows

**A file `INPUT` behaves exactly like its parent directory, non-recursively, with
that one file as the only candidate — and the suffix set not consulted.**

Every decision below falls out of that sentence, which is why the existing
machinery needs almost no change: the input root becomes `INPUT`'s parent *as
typed*, `paths.output_for` maps the file to `<output root>/<stem><target
suffix>`, `--mirror-to` re-roots that parent, and the self-write, collision,
overwrite-hazard and existing-output rules of `docs/design/source-selection.md`
apply unchanged to a batch of one. The only two departures from "its parent
directory" are the ones the sparring decided: the suffix set is bypassed, and
`OUTPUT` may be omitted.

## Outcome

- [ ] `converter --to FORMAT FILE OUTPUT` converts that one file into
      `OUTPUT/<stem><target suffix>`, through the same ladder and with the same
      notes a directory run would give it.
- [ ] `converter --to FORMAT FILE` with neither `OUTPUT` nor `--mirror-to` writes
      the result beside the source.
- [ ] `converter --to FORMAT FILE --mirror-to ROOT` writes it where a directory
      run over `FILE`'s parent would have — the parent re-rooted onto `ROOT` *as
      typed*, per issue #72's rule.
- [ ] A file named explicitly is converted whatever its suffix; one ffmpeg
      cannot read ends `FAILED` with its reason, exit 1 — never a usage error and
      never a silent drop.
- [ ] A file whose output would be itself (`a.mp4 --to mp4`, no `OUTPUT`) is a
      counted `skipped` with the existing self-write note, exit 0; a second run
      over an already-converted file reports `0 converted`, `1 skipped`, exit 0.
- [ ] A path that does not exist is a usage error naming it as "input", not as
      "input directory", exit 2.
- [ ] Every directory invocation keeps its exact current behaviour, `OUTPUT`
      still required for a directory unless `--mirror-to` is given.
- [ ] The interactive prompt offers the file case — see Prior decisions (OPEN).
- [ ] `--help`, `README.md`, `docs/vision.md`, `docs/architecture.md` and
      `docs/design/source-selection.md` describe `INPUT` as a file or a directory.

## Scope

### In scope

- `converter/cli.py`: the file branch of source selection and output-root
  resolution, the not-found message, the `INPUT` / `OUTPUT` help text, and the
  interactive prompt.
- Tests in `tests/test_cli.py` for every outcome above.
- `README.md`: the usage block, the options table and one example.
- Foundation and design carriers, **authored in this spec PR** so they are
  ratified at the acceptance gate: `docs/vision.md` (Scope *In*),
  `docs/architecture.md` Key flow 1, and `docs/design/source-selection.md` (the
  entry node and one rule).

### Out of scope

- **Several files as `INPUT`.** Decided in the sparring: it would need `-o` in
  place of the positional `OUTPUT` — a second CLI break — and Windows does not
  expand globs in the shell (`docs/prior-art.md`, *Single-file input*).
- **`OUTPUT` as a file name** (`converter --to mp4 a.mkv b.mp4`). `OUTPUT` stays a
  directory; `--to` stays the only way to name the target.
- **An omitted `OUTPUT` for a directory `INPUT`.** That would make in-place tree
  conversion the default — a behaviour change nobody asked for, and a different
  question from this phase's.
- **Any change to `converter/paths.py`, `converter/batch.py`, `converter/jobs.py`
  or `converter/profiles.py`.** The model above needs none; a PR that reaches
  into one of them has left the model and must say why.

## Constraints

- `docs/constitution.md`: no shell, paths only through `cli_path()` /
  `build_argv()` (untouched here), ≤50 lines per function, full annotations, one
  broken input never aborts the batch.
- `docs/architecture.md`: `paths.py` stays pure and knows nothing of the CLI;
  nothing below `cli.py` imports `cli`.
- `converter/cli.py` names no target format in a string literal — a test walks
  the module with `ast` and fails otherwise. The new help text and messages must
  keep to that.
- Selection still spends no subprocess: whether a file is a file is an `os.stat`,
  so `--dry-run` and every refusal keep working without ffmpeg installed.
- Verify stays green and under 60 s; the suite stays ffmpeg-free.

## Prior art

- [Single-file input (Phase 10)](../prior-art.md#single-file-input-phase-10) —
  the sparring's decisions and their precedents: a file is a first-class input
  everywhere else (pandoc, ImageMagick, `HandBrakeCLI`, ffmpeg itself); `--to`
  stays the single naming of the target; ImageMagick's output-name inference and
  several positional files are the two recorded AVOIDs.
- [Format-driven converter CLI (Phase 2)](../prior-art.md#format-driven-converter-cli-phase-2)
  — the entries the Phase 10 concern reuses by reference.

## Human prerequisites

none

## Prior decisions

| Decision | Rationale | Date |
|---|---|---|
| `INPUT` is exactly one file or one directory | Sparring, 2026-09-28: several files force `-o` (a CLI break) and meet unexpanded globs on Windows | 2026-09-28 |
| A file `INPUT` is modelled as its parent directory, non-recursive, with the file as the only candidate | Reuses `output_for`, `mirror_to_drive` and every guard of `source-selection.md` unchanged — one model to test instead of a second pipeline | 2026-09-28 |
| The input root for a file is `INPUT`'s parent **as typed** (`Path(INPUT).parent`), never resolved | Issue #72: `--mirror-to` re-roots the path as typed so a `subst`/junction input mirrors onto the shallow tree the user sees; the guards resolve independently, so this costs no safety | 2026-09-28 |
| A file `INPUT` bypasses `SOURCE_SUFFIXES` | Sparring: the user named the file, so ffprobe — not an extension list — decides whether it is readable. An unreadable file fails like any other conversion (`FAILED`, exit 1), which the batch already reports with ffmpeg's reason | 2026-09-28 |
| `OUTPUT` stays a directory; for a file it is optional and defaults to the input root (the source's own directory) | Sparring. Omitting it for a *directory* stays a usage error — see Out of scope | 2026-09-28 |
| `OUTPUT` and `--mirror-to` together stay a usage error, for a file as for a directory | Existing rule in `_resolve_output_root`; the model gives no reason to relax it | 2026-09-28 |
| `-r` is accepted and has no effect on a file | A file has no sub-directories; `cp -r file dst` and `rsync -r file dst` accept it the same way, and a script that passes `-r` uniformly over mixed paths must not break. No note: nothing was given up | 2026-09-28 |
| The strict-descendant output exclusion (`OWN`) does not apply to a file | It exists so a *walk* does not rediscover its own output. A named file is never walked to; excluding it would drop the one thing the user asked for | 2026-09-28 |
| A missing path is `error: input does not exist: <path>`, exit 2, checked in `cli.py` before selection | The old text says "input directory", which is wrong for a file. Checking in `cli.py` keeps `paths.find_sources`'s contract (a directory walk) untouched | 2026-09-28 |
| A path that exists but is neither a file nor a directory is treated as a directory and fails as today | No realistic media input takes that shape; a dedicated branch would be untestable ceremony | 2026-09-28 |
| `--dry-run`, the summary line, `--jobs` and the progress bar are unchanged for a file | A batch of one already prints `src -> dst` and `1 file(s) would be converted.` correctly; no wording is wrong, so none changes | 2026-09-28 |
| The "no convertible files found" hint never fires for a file | A file `INPUT` always yields exactly one pair, because the suffix set is bypassed | 2026-09-28 |
| The foundation and design carriers are edited in this spec PR, not in an implementation issue | `/loopkit:roadmap` recorded the impact for ratification at this gate; phase 6's spec PR is the precedent for editing `architecture.md` and a design diagram before the code | 2026-09-28 |
| OPEN — Does the interactive prompt become file-aware (skip the sub-directory question, allow an empty output for a file), or only accept a file under a reworded question? | resolved at the spec-acceptance gate | — |
| OPEN — Is an `OUTPUT` that *looks like a file name* refused when `INPUT` is a file? | resolved at the spec-acceptance gate | — |

### Why the two OPEN rows are genuinely open

- **Prompt.** Today an empty answer to "Output directory" means "mirror onto
  another drive instead", and "Include sub-directories?" defaults to yes. Both
  keep working for a file — `-r` is harmless, and the mirror question is still
  valid — so a reworded "Input file or directory" question is *enough* to reach
  the feature. A file-aware prompt is friendlier (no pointless question; an empty
  output answer lands beside the source, matching the CLI) but makes the prompt
  check the filesystem before dispatch, which it does not do today. Neither the
  constitution nor precedent chooses.
- **An `OUTPUT` that looks like a file name.** `OUTPUT` is a directory, so
  `converter --to mp4 a.mkv b.mp4` — the ImageMagick reflex, recorded as an AVOID
  in `docs/prior-art.md` — would create a *directory* `b.mp4\` and write
  `b.mp4\a.mp4`. That is not destructive and is reported, but it is surprising.
  A guard would refuse, exit 2, when `INPUT` is a file and `OUTPUT` is an
  existing non-directory, or does not exist and ends in the target's suffix. It
  adds a usage error with its own test, and it is the one place the model above
  would gain a rule its directory counterpart lacks.

## Tracking

- Milestone: filled at the acceptance gate
- Issues: created from this spec once it is merged (one per implementable step)

Each issue references this spec path in its body.

## Verification

- [ ] Verify passes (`.\.venv\Scripts\python.exe scripts\verify.py`), under 60 s.
- [ ] Tests pin, for a file `INPUT` with the subprocess stubbed:
  - [ ] with `OUTPUT`: one task, `OUTPUT/<stem><target suffix>`;
  - [ ] without `OUTPUT`: one task, the output beside the source;
  - [ ] with `--mirror-to`: the parent re-rooted *as typed* — the same output a
        directory run over the parent would produce;
  - [ ] a suffix outside `SOURCE_SUFFIXES` still yields a task;
  - [ ] `a.mp4 --to mp4` without `OUTPUT`: `skipped` with the self-write note,
        exit 0, and no tool resolution attempted;
  - [ ] an existing output without `--overwrite`: `skipped`, exit 0;
  - [ ] `-r` changes nothing;
  - [ ] a file inside a directory that would be a nested output root is still
        converted (`OWN` does not apply);
  - [ ] `OUTPUT` together with `--mirror-to`: usage error, exit 2;
  - [ ] a missing path: `input does not exist`, exit 2;
  - [ ] `--dry-run` prints the one pair and `1 file(s) would be converted.`
- [ ] Every existing `tests/test_cli.py` test passes unchanged, except where it
      pins the old "input directory does not exist" text for a missing path.
- [ ] Tests for whichever way each OPEN row is resolved.
- [ ] `git diff main -- converter/paths.py converter/batch.py converter/jobs.py
      converter/profiles.py` is empty over the phase.
- [ ] **QA smoke test with real ffmpeg** (the only end-to-end evidence; paths from
      `docs/workflow.md`, *This machine*), on copies of fixture files:
  - [ ] `--to mp3 song.flac` writes `song.mp3` beside it; exit 0.
  - [ ] `--to mp4 clip.mkv OUT` writes `OUT\clip.mp4` with the notes a directory
        run over the same file prints.
  - [ ] `--to mp4 clip.mkv --mirror-to <tmp root>` lands under the re-rooted
        parent.
  - [ ] A readable file with an unregistered suffix (a WAV renamed `.dat`)
        converts; a `.txt` fails with ffmpeg's reason, exit 1.
  - [ ] `--to mp4 clip.mp4` reports `skipped`, exit 0; re-running the first
        command reports `0 converted`, exit 0.
  - [ ] A missing path exits 2 with `input does not exist`.
  - [ ] The interactive prompt, driven once with a file, produces a working run.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| A relative `INPUT` like `song.flac` has parent `.`, and `output_for`'s `relative_to` or `mirror_to_drive` mishandles it | Pinned by a test with a bare relative file name, with and without `--mirror-to`; the directory counterpart (`--to mp4 . OUT`) already takes the same path |
| The file branch grows into a second pipeline beside the directory one | The model sentence plus the empty-diff check on `paths`, `batch`, `jobs` and `profiles` |
| A function in `cli.py` crosses 50 lines when the branch is added | Put the file-vs-directory decision in one small helper that both `_selected_pairs` and `_resolve_output_root` call |
| The ffmpeg-free suite hides a real-ffmpeg problem with a file outside the suffix set | QA smoke test covers both the readable and the unreadable case |

## Decision log

- 2026-09-28: Planned from the roadmap seed of the same day (PR #124). The seed's
  four open questions are settled here: `-r` is a no-op, `--mirror-to` re-roots
  the parent as typed, a self-write is the existing counted skip (confirmed
  against `cli._partition_self_writes` — no new code), and `--dry-run` needs no
  new wording. The prompt question stays open for the gate.

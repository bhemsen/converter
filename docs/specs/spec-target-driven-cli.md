# Spec: target-driven-cli (roadmap phase 2)

> Created: 2026-08-25

Replace the `video` and `audio` sub-commands with `converter --to <format>`,
driven by the profile registry phase 1 built — plus `--list-formats`, a prompt
that offers the registry instead of two hard-wired pairs, and a README that
documents what the tool now is. This is the project's breaking change. This spec
carries no lifecycle state — acceptance is the spec merged on the default branch
with a milestone and issues, and all progress lives in the GitHub issues and
milestone. A completed spec is moved to `docs/specs/archive/`.

## Outcome

- [ ] `converter --to <format> INPUT [OUTPUT]` converts every source under
      `INPUT` into `<format>`, mirroring the tree, with the flags the old
      sub-commands had (`-r`, `-j`, `--overwrite`, `--dry-run`, `-q`,
      `--mirror-to`, `--ffmpeg`, `--ffprobe`) unchanged in name and meaning.
- [ ] `converter video ...` and `converter audio ...` are **gone** — the parser
      rejects them with a usage error naming the replacement.
- [ ] `converter --list-formats` prints every target the registry holds and the
      suffix each writes, and exits 0 without touching the filesystem.
- [ ] The interactive prompt (bare `converter`) offers the registry's targets and
      the `mirror` command, built from the registry rather than a literal list.
- [ ] `converter mirror ...` still works exactly as it does today.
- [ ] Adding a target format still produces no diff in `cli.py`, `batch.py` or
      `paths.py` — the check phases 3-5 will actually run.
- [ ] `README.md` documents the `--to` CLI, carries a migration note from the old
      sub-commands, and names `main` as the pull-request target.
- [ ] Both README tech-debt rows are gone from `docs/constitution.md`: the
      `develop` row, and the `convert_command` over-50-lines row.
- [ ] No version bump and no changelog entry land in this phase.

## Scope

### In scope

- `converter/cli.py`: the parser shape, `--to`, `--list-formats`, the reworked
  prompt, the `mirror` routing, and splitting `convert_command` under 50 lines.
- `converter/profiles.py`: looking a profile up by target name, and the curated
  set of source suffixes discovery uses.
- `converter/batch.py`: taking a profile where it takes a `Job` today, and
  deleting `Job` / `JOBS` / `JOB_BINDINGS` with the sub-commands they served.
- `README.md`, and the two tech-debt rows in `docs/constitution.md`.
- Source selection per `docs/design/source-selection.md`.

### Out of scope

- New target formats. Phase 2 ships the two profiles that exist; `--list-formats`
  will print two lines until phase 3.
- The conversion ladder itself. Phase 1 owns it; nothing in this phase touches
  `jobs.py` beyond removing the `Job` scaffolding.
- The version bump to 3.0.0, the changelog and the release. `docs/release.md`
  makes that `/loopkit:ship`'s job, computed from the `refactor!` commit this
  phase lands — a version bumped here would be bumped twice.
- A deprecation shim that keeps `video` / `audio` working. `docs/release.md`
  already plans this phase as the breaking change with a migration note.

## Constraints

- A target format is data, not code: this phase must leave `cli.py` free of any
  format name, so phases 3-5 can add one by touching only `profiles.py`
  (`docs/constitution.md`, `docs/architecture.md`).
- Maximum 50 lines per function — `convert_command` is 54 today and is listed as
  tech debt this phase clears.
- `paths.py` knows nothing about ffmpeg or profiles; discovery keeps taking a
  suffix set as an argument rather than reaching into the registry.
- Selection finishes before `resolve_tools` runs, so `--dry-run` and a collision
  refusal keep working on a machine with no ffmpeg installed.
- Windows is a first-class target: `--mirror-to E:` behaviour is unchanged.

## Prior art

- [Format-driven converter CLI (Phase 2)](../prior-art.md#format-driven-converter-cli-phase-2)
  — the concern that feeds this phase. pandoc's readers-plus-writers is the direct
  precedent for `--to` over per-pair sub-commands: N+M implementations instead of
  N*M, with the ffprobe stream list as the reader and the target profile as the
  writer. ImageMagick's ADOPT (infer the target from the output extension) is the
  reason `--to` accepts `.mp4` as readily as `mp4`. The batch-conversion entry's
  AVOID (the GUI-first shape) is what keeps the interactive prompt a thin argv
  builder rather than a second code path.

## Design

- `docs/design/source-selection.md` — which files under the input root become
  tasks, which are refused up front, and which are never candidates.
- The ladder is unchanged: `docs/design/degradation-ladder.md` and
  `docs/design/stream-decision.md` still describe what happens per file.

## Human prerequisites

- none. No secret, no dependency, no external provisioning.

## Prior decisions

| Decision | Rationale | Date |
|---|---|---|
| `--to` accepts a format name or a suffix, case-insensitively: `mp4`, `MP4` and `.mp4` all select the MP4 profile | ImageMagick's precedent is that the target is already written down as an extension (`docs/prior-art.md`); refusing the dotted form would be pedantry, and normalising is three lines in the registry lookup | 2026-08-25 |
| An unknown target is a usage error (exit 2) whose message lists the available targets | The same shape as the existing `--jobs must be 1 or more`; a wrong format name is a typo, not a conversion failure | 2026-08-25 |
| Discovery uses a curated **source-suffix set** declared in `converter/profiles.py`, and files whose suffix equals the target's own suffix are never candidates | Drawn in `docs/design/source-selection.md`. The suffix set is curated for the same reason the copy mask is; the same-suffix exclusion is what stops an output path from being its own input | 2026-08-25 |
| `mirror` stays a sub-command. `main()` routes on the first token: a leading `mirror` goes to the mirror parser, anything else to the convert parser | argparse cannot hold both a positional `INPUT` on the top-level parser and a sub-command, since it would read `INPUT` as a command name. Two parsers behind one routing line is honest and testable; the alternative — turning `mirror` into a flag — would break a working command for no reason | 2026-08-25 |
| `Job`, `JOBS` and `JOB_BINDINGS` are deleted. `batch.run_batch` takes the profile, and the progress bar's description comes from the profile's label | They exist only to keep phase 1's diff out of `cli.py` and `batch.py`; phase 2 is the breaking change that was always going to remove them. The constitution's no-diff rule is about *adding a format*, which this is not | 2026-08-25 |
| No version bump, no `CHANGELOG.md` entry, no tag in this phase | `docs/release.md` computes the version from the conventional commits in the range and has the human curate the changelog at the `/loopkit:ship` preview. A bump here would be recomputed and could disagree with the tag | 2026-08-25 |
| The commit that removes the sub-commands is subject-marked `refactor!`, and the PR body carries the migration line `converter video IN OUT` -> `converter --to mp4 IN OUT`, `converter audio IN OUT` -> `converter --to wav IN OUT` | `docs/release.md` derives the major bump from the `!` marker and requires a migration note in the breaking release's changelog entry; the text has to exist somewhere for `/ship` to curate | 2026-08-25 |
| `--list-formats` prints one line per target — the name, the suffix it writes, and the profile's one-line description — sorted by name, and exits before any path or tool resolution | It is the discoverability half of `--to`: a user who guessed a format name wrong needs the list without owning a valid input directory | 2026-08-25 |
| The interactive prompt asks for the target format by name, offering the registry's list, and otherwise keeps today's questions and its argv-building shape | The prompt is not a second code path (`converter/cli.py`); keeping it an argv builder is what makes it testable against the same parser | 2026-08-25 |
| OPEN — does this phase also ship a `--from <suffix>` source filter? | resolved at the spec-acceptance gate | — |

## Tracking

The decomposition into steps lives as GitHub issues, not in this file — one
issue per step, grouped under a milestone. This spec owns the design; the issues
own progress.

- Milestone: target-driven-cli (created at the spec-acceptance gate)
- Issues: created from this spec once it is merged (one per implementable step)

## Verification

Machine checks:

- [ ] Verify passes (ruff check, ruff format --check, pytest) on the merge commit.
- [ ] A test that `converter video ...` and `converter audio ...` exit 2 with a
      message naming `--to`.
- [ ] A test per selection rule in `docs/design/source-selection.md`: a
      non-media file is not a candidate, a file already in the target format is
      not a candidate, a collision exits 2 before any conversion, an existing
      output is `skipped`, and `--dry-run` works with no ffmpeg resolvable.
- [ ] A test that `--to MP4`, `--to mp4` and `--to .mp4` select the same profile,
      and that an unknown target exits 2 listing the available ones.
- [ ] A test that `--list-formats` prints a line per registry entry and exits 0
      without resolving tools or touching the filesystem.
- [ ] A test driving `prompt_for_argv` through the real parser, so the prompt and
      the flags cannot drift apart.
- [ ] A test that `converter mirror ...` is unaffected.
- [ ] No function in `converter/cli.py` exceeds 50 lines, and both README-related
      tech-debt rows are gone from `docs/constitution.md`.
- [ ] `grep` finds no format name (`mp4`, `wav`, `mkv`, `opus`) in
      `converter/cli.py`, `converter/batch.py` or `converter/paths.py`.

Human milestone-QA gate — with the absolute ffmpeg paths from *This machine*,
reusing the fixtures the phase-1 gate synthesises:

- [ ] `converter --to mp4 in out` converts the MKV fixtures and reports a
      summary; a second run reports `0 converted`, exit 0.
- [ ] `converter --to wav in out` converts `tone.opus` and leaves the `.mkv`
      files alone.
- [ ] Pointing `--to mp4` at a directory that already contains `.mp4` files
      converts the others and does not touch or destroy the existing ones.
- [ ] `converter --list-formats` and bare `converter` (the prompt) both behave as
      described, on a machine path where ffmpeg is not on PATH.
- [ ] `converter video in out` fails with a message that tells the user what to
      run instead.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| `--to mp4` pointed at a large mixed tree silently tries to convert far more files than the old sub-commands did | The curated source-suffix set bounds it, `--dry-run` lists the tasks before any work, and the same-suffix exclusion keeps the target's own files out |
| A source whose output path equals its input path corrupts the file under `--overwrite` | Excluded at selection, with a test per `docs/design/source-selection.md` |
| Removing the sub-commands breaks someone's script silently | The parser names the replacement in its error, and the `refactor!` commit plus migration line drive the release note |
| The prompt drifts from the flags it builds | The prompt test parses its output with the real parser, as today |
| Phases 3-5 discover that `cli.py` still needs a diff per format | The `grep`-for-format-names check in Verification fails the gate rather than surfacing in phase 3 |

## Decision log

- 2026-08-25: `docs/design/source-selection.md` added as the phase's design
  artifact. The CLI has no UI surface, but `--to` creates a selection decision
  that every coverage phase re-opens by adding suffixes, which is exactly the
  recurring-decision criterion `docs/design.md` names.

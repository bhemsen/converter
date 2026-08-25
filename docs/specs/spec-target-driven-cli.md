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
- [ ] `converter video ...` and `converter audio ...` exit 2 with a message that
      says the sub-commands are gone, shows the `--to` shape, and points at
      `--list-formats` — without naming a format (see the Prior decision).
- [ ] `converter --list-formats` prints every target the registry holds and exits
      0 without resolving tools or touching the filesystem.
- [ ] The interactive prompt (bare `converter`) offers the registry's targets and
      the `mirror` command, built from the registry rather than a literal list.
- [ ] `converter mirror ...` and `converter --version` still work exactly as they
      do today, and `converter --help` still leads a reader to both.
- [ ] Adding a target format still produces no diff in `cli.py`, `batch.py` or
      `paths.py` — the check phases 3-5 will actually run.
- [ ] A source the target cannot produce at all resolves to the outcome decided
      at the acceptance gate, and a mixed tree does not fail the run for it —
      so a re-run over it still reports `0 converted, 0 failed`, exit 0.
- [ ] `README.md` documents the `--to` CLI, carries the migration note, names
      `main` as the pull-request target, and no longer tells a reader to add a
      `Job` to `converter/jobs.py`.
- [ ] Both remaining tech-debt rows are gone from `docs/constitution.md`: the
      README `develop` row, and the `convert_command` over-50-lines row.
- [ ] No version bump, no changelog entry and no tag land in this phase.

## Scope

### In scope

- `converter/cli.py`: the parser split, the `main()` routing, `--to`,
  `--list-formats`, the reworked prompt, and splitting `convert_command` under
  50 lines.
- `converter/profiles.py`: a `PROFILES` mapping (target name -> profile) — the
  registry itself, which the merged module does not yet have — plus a `name` and
  a one-line `description` on the profile value type, lookup by that name, and
  the curated source-suffix set.
- `converter/batch.py`: taking a profile where it takes a `Job` today, the
  progress-bar description, and mapping the engine's signal onto the outcome the
  gate decides for a source the target cannot produce — mapping only, never
  deciding.
- `converter/paths.py`: the three new selection predicates — self-write,
  output-tree exclusion and the overwrite hazard — live here beside
  `find_collisions`, as pure path logic with no ffmpeg or profile knowledge, and
  the output-tree exclusion means `find_sources` grows a way to skip a subtree.
  `cli.py` calls them; it does not reimplement them, which is also what keeps
  `convert_command` under 50 lines. Their tests go to `tests/test_paths.py`.
- `converter/jobs.py`: exposing the engine entry points `batch.py` now calls
  directly, and reporting the "no rule matches any present stream" signal the
  unsupported outcome rests on. No change to the ladder itself.
- Deleting `Job`, `JOBS` and `JOB_BINDINGS` with the sub-commands they served.
- **The test migration this forces**, which is a substantial part of the work:
  `tests/test_batch.py` imports `MKV_TO_MP4` / `OPUS_TO_WAV` across 17 call
  sites, and `tests/test_cli.py`'s parser, output-root, convert-command,
  exit-code and prompt classes are written entirely against `video` / `audio`.
  `tests/test_paths.py` gains the cases for the three new predicates.
- `README.md`, the two tech-debt rows in `docs/constitution.md`, and the
  `docs/architecture.md` amendment already made in this spec's PR (the
  `batch` -> `profiles` edge, and `batch` calling the engine directly).
- Source selection per `docs/design/source-selection.md`.

### Out of scope

- New target formats. Phase 2 ships the two profiles that exist; `--list-formats`
  prints two lines until phase 3.
- The conversion ladder. Phase 1 owns it; this phase only exposes its entry
  points and removes the `Job` scaffolding around them.
- The version bump to 3.0.0, the changelog and the release. `docs/release.md`
  makes that `/loopkit:ship`'s job, computed from the `refactor!` commit this
  phase lands — a version bumped here would be bumped twice.
- A deprecation shim that keeps `video` / `audio` *working*. They are recognised
  only to produce a useful error.
- Rewriting `converter/paths.py`'s docstrings, which use `.mkv` and `.mp4` as
  illustrations. They are examples in prose, not format knowledge in code; see
  the Verification check that draws the line.

## Constraints

- A target format is data, not code: this phase must leave `cli.py` and
  `batch.py` free of any format name, so phases 3-5 add one by touching only
  `profiles.py` (`docs/constitution.md`, `docs/architecture.md`).
- Maximum 50 lines per function — `convert_command` is 54 today and is listed as
  tech debt this phase clears.
- `paths.py` knows nothing about ffmpeg or profiles; discovery keeps taking a
  suffix set as an argument rather than reaching into the registry.
- Selection finishes before `resolve_tools` runs, so `--dry-run`,
  `--list-formats` and a collision refusal keep working with no ffmpeg installed.
- Windows is a first-class target: `--mirror-to E:` behaviour is unchanged, and
  path comparison stays case-folded.

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
| Source selection follows `docs/design/source-selection.md` | The mechanism lives in the diagram; repeating it here would let the two drift (`docs/design.md`) | 2026-08-25 |
| There are **two parsers**: a convert parser (positional `INPUT`, optional `OUTPUT`, required `--to`) and the existing mirror parser. `main()` routes on the raw argv before parsing: a leading `mirror` goes to the mirror parser; a leading `video` or `audio` prints the migration line and returns 2; `--list-formats` anywhere prints the list and returns 0; anything else goes to the convert parser | The subparsers action is itself a positional, so with `INPUT` on the top-level parser argparse binds the first token to `INPUT` and reads the *next* one as the command name — the two shapes genuinely cannot coexist. Routing before parsing is also what makes `--list-formats` reachable at all, since a required `--to` and a required `INPUT` would otherwise reject it | 2026-08-25 |
| `build_parser()` returns the **convert** parser; the mirror parser comes from a second builder, and both are exported | Every existing parser test calls `build_parser()`, and the convert path is the one the prompt round-trips through. Two builders keep each parser's `--help` honest about its own arguments | 2026-08-25 |
| `--version` stays an `action="version"` optional on the convert parser | argparse runs a `version` action during parsing and exits before it checks required arguments, so `converter --version` keeps working with `--to` required. Pinned by the existing test rather than assumed | 2026-08-25 |
| The convert parser's `--help` epilog names `converter mirror --help` and `--list-formats` | With `mirror` off the sub-parser list it would otherwise vanish from `--help`, which would be a discoverability regression nobody decided on | 2026-08-25 |
| The profile value type gains a `name` (the `--to` token) and a one-line `description`. This **extends phase 1's value type**, whose field list did not include either | `--list-formats` and the prompt both need a human-readable line per target, and the text that serves that today lives in `JOB_BINDINGS`, which this phase deletes. Recorded as a visible change to phase 1's shape rather than a silent one | 2026-08-25 |
| `Job`, `JOBS` and `JOB_BINDINGS` are deleted. `batch.run_batch` takes the profile, calls the engine through the entry points `jobs.first_attempt(profile)` and `jobs.retries(profile, streams)`, and takes the progress-bar description from the profile's label — so the bar reads `MP4` where it read `mkv-to-mp4` | They exist only to keep phase 1's diff out of `cli.py` and `batch.py`; phase 2 is the breaking change that was always going to remove them. The constitution's no-diff rule is about *adding a format*, which this is not. Naming the entry points here stops the implementer from inventing a third shape | 2026-08-25 |
| The entry-point names above are **phase 2's to establish**: if phase 1's engine issue lands with different ones, phase 2 adopts those rather than renaming them. The wrapper around `profile.cheap_attempt` is not redundant — it is where `container_options` are placed per `docs/design/degradation-ladder.md`, and `batch.py` reading the field directly would be exactly the format knowledge the new architecture bullet forbids | The merged `Profile` stores `cheap_attempt` as a plain `Attempt` field rather than a callable, so the wrapper looks removable until you notice what it does | 2026-08-25 |
| `docs/architecture.md`'s Boundaries gains the `batch` -> `profiles` edge, amended in this PR | `run_batch(profile, ...)` needs the type for its annotation, so the edge is real. Phase 1 set the precedent of amending architecture in the spec's own PR rather than letting it drift | 2026-08-25 |
| A run that finds no candidates prints the ordinary summary line on stdout and a one-line hint on stderr, and exits 0 — it no longer prints `No .mkv files found` | The suffix set is now dozens of entries, so interpolating it is unreadable, and an error-channel message for an empty directory reads like a failure. `docs/vision.md` requires a re-run over a finished tree to *report* `0 converted, 0 failed`, which needs the summary to be printed | 2026-08-25 |
| No version bump, no `CHANGELOG.md` entry, no tag in this phase | `docs/release.md` computes the version from the conventional commits in the range and has the human curate the changelog at the `/loopkit:ship` preview. A bump here would be recomputed and could disagree with the tag | 2026-08-25 |
| The commit that removes the sub-commands is subject-marked `refactor!`, and the PR body carries the migration lines `converter video IN OUT` -> `converter --to mp4 IN OUT` and `converter audio IN OUT` -> `converter --to wav IN OUT` | `docs/release.md` derives the major bump from the `!` marker and requires a migration note in the breaking release's changelog entry; the text has to exist for `/ship` to curate | 2026-08-25 |
| `--list-formats` prints one line per target — the name, the suffix it writes, and the description — sorted by name | It is the discoverability half of `--to`: a user who guessed a format name wrong needs the list without owning a valid input directory | 2026-08-25 |
| The prompt lists the registry's targets numbered in the same sorted order `--list-formats` uses, with `mirror` as the last entry and the first target as the default. It also accepts a format name typed instead of a number | Keeps today's shape (a numbered menu with a default) while the list grows; typing the name is the escape hatch once 17 entries make counting silly. The prompt stays an argv builder, so the parser remains the single code path | 2026-08-25 |
| The legacy-token message is **generic**: it says the sub-commands are gone, shows `converter --to <format> IN OUT`, and points at `--list-formats`. The concrete `video` -> `--to mp4` and `audio` -> `--to wav` mapping lives in the README and in the PR body, not in `cli.py` | Naming `mp4` in `cli.py` would be the one string that defeats the `ast` check this phase installs to keep format names out of the CLI — and that check is what phases 3-5 rely on. A user who has just been told about `--list-formats` is one command from the answer | 2026-08-25 |
| Routing runs on `raw` **after** the bare-invocation prompt has filled it, so a prompt that returns a `mirror` argv reaches the mirror parser. The `if not hasattr(args, "handler")` fallback in `main()` is removed — with explicit routing both parsers always set one | The prompt is an argv builder, so its output must travel the same path a typed argv does; that is the property the round-trip test exists to protect | 2026-08-25 |
| OPEN — the `unsupported` outcome alone, or together with a `--from <suffix>` filter | resolved at the spec-acceptance gate; see the note below | — |

### The one open decision, in full

Selection cannot know whether a source *can* produce the target: that needs a
probe, and a probe on the happy path is forbidden. So under `--to wav`, a
video-only `.mkv` is selected, its attempt fails, the probe finds no audio, the
selective rung has no streams to map, WAV declares no last-resort rung — and the
file lands as `failed`, exit 1. Pointing `--to wav` at any mixed tree therefore
fails the run today, and keeps failing on every re-run, which is the one thing
`docs/vision.md`'s idempotent-re-run criterion forbids.

That criterion is why the phase needs an **`unsupported` outcome** either way: a
file that cannot produce the target produces no output, so a re-run re-attempts
it forever unless the run stops calling it a failure. Its discriminator is taken
from the probe, never from ffmpeg's stderr (`docs/constitution.md`): the source
carries no stream of any type the profile declares a rule for. A file that *does*
carry usable streams and still fails is a genuine `failed` — the distinction
matters, or a corrupt file would be quietly relabelled.

**The discriminator lives in `jobs.py`, not `batch.py`.** It reads the profile's
rules against the probed streams, which is a conversion decision, and the
architecture bullet this PR adds forbids `batch.py` from making one. The engine
reports it as a distinguishable signal; `batch.py` maps that signal onto the
outcome and counts it, and does nothing else with it.

Note what the outcome does **not** buy: an unsupported file still costs one ffmpeg
attempt and one ffprobe on every run, because nothing short of a probe can tell.
The re-run reports honestly and exits 0, but it is not free — worth knowing before
picking, on a large mixed tree.

The gate therefore picks between two answers, not three:

1. **The `unsupported` outcome alone.** Costs a new outcome in `batch.py` and a
   column in every summary line. A mixed tree converts what it can and reports
   the rest by name.
2. **The `unsupported` outcome plus a `--from <suffix>` filter**, so a user who
   knows their tree can narrow it up front and never see the unsupported lines.
   More surface, more tests, and a flag phases 3-5 must keep working.

   Picking this must not reopen planning, so its semantics are settled here: the
   flag is **repeatable** (`--from mkv --from avi`) and not comma-separated,
   matching how argparse expresses a list without a second parsing rule; it
   accepts the same dotted and cased forms `--to` does, normalised the same way;
   it **intersects** the curated source-suffix set rather than replacing it, so a
   typo cannot widen discovery to files ffmpeg was never going to read; and a
   suffix outside that set is a usage error (exit 2) naming it, not an empty run
   that looks like success.

A `--from` filter *alone* was considered and dropped: it leaves the default
invocation failing on a mixed tree, which contradicts this spec's own Outcome and
the vision criterion above.

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
      non-media file is not a candidate, a source whose output path is its own
      input path is a counted `skipped`, a source with the target's suffix but a
      different output root **is** converted, a collision exits 2 before any
      conversion, an existing output is `skipped`, and `--dry-run` works with no
      ffmpeg resolvable.
- [ ] A test pair for `a.mkv` and `a.mp4` in one directory, converting to `mp4`
      in place: **with** `--overwrite` it exits 2 naming both files, because
      reporting `a.mp4` as skipped and then overwriting it would destroy a file
      the run said it kept; **without** `--overwrite` it reports
      `0 converted, 2 skipped` and exits 0, because nothing is at risk and an
      in-place re-run must stay idempotent.
- [ ] A test for a nested output root (`-r IN IN\converted`): run it twice, and
      the second run reports `0 converted`. Without the output-tree exclusion this
      grows a `converted\converted\...` generation per run, forever.
- [ ] A test for an **ancestor** output root (`-r IN\Sub IN`): the files convert,
      and a second run reports `0 converted`. A rule written as "lies under the
      output root" without the strict-descendant clause excludes every candidate
      here and reports a successful run that did nothing.
- [ ] A `--mirror-to` variant of the `--overwrite` refusal test, so the hazard
      guard is pinned on paths that differ as given and agree once resolved — the
      one-directory test cannot tell the two comparisons apart.
- [ ] A test that the self-write guard still fires under `--mirror-to`, where the
      output root is derived from a resolved input path and the source paths are
      not — the case a compare-as-given check would miss, and that an absolute
      `tmp_path` in a test would hide.
- [ ] A test that `--to MP4`, `--to mp4` and `--to .mp4` select the same profile,
      and that an unknown target exits 2 listing the available ones.
- [ ] A test that `--list-formats` prints a line per registry entry and exits 0
      without resolving tools, and that it works with `--to` and `INPUT` absent.
- [ ] A test that `converter --version` still exits 0 with `--to` required.
- [ ] A test driving `prompt_for_argv`'s output through the same routing function
      a typed argv takes — not through one parser, since a prompted `mirror` argv
      the convert parser cannot parse is exactly what this protects — plus one
      for a typed format name.
- [ ] A test that `converter mirror ...` is unaffected, and one that a run with
      no candidates prints the summary and exits 0.
- [ ] A test that walks `converter/cli.py` and `converter/batch.py` with `ast`
      and asserts no string literal other than a docstring contains a format name
      or suffix from the registry. A plain `grep` cannot do this: `paths.py`
      illustrates its rules with `.mkv` in prose, and a case-sensitive grep would
      miss `.MKV` — the check has to look at code, not text.

Checked in review, not by a machine — ruff's `select` carries no `PL` rules, so
nothing measures function length:

- [ ] No function in `converter/cli.py` exceeds 50 lines, and the
      `convert_command` tech-debt row is gone from `docs/constitution.md`.
- [ ] `README.md`: the `--to` CLI, the migration note, `main` as the PR target,
      a `converter/profiles.py` row in the layout table, and no surviving
      instruction to add a `Job` to `converter/jobs.py`.

Human milestone-QA gate — with the absolute ffmpeg paths from *This machine*,
reusing the fixtures the phase-1 gate synthesises:

- [ ] `converter --to mp4 in out` converts the MKV fixtures and reports a
      summary; a second run reports `0 converted`, `N skipped`, exit 0.
- [ ] `converter --to wav in out` over the same mixed directory behaves as the
      gate's open decision resolved it — and does not exit 1 for the video-only
      sources if the resolution says it should not.
- [ ] Pointing `--to mp4` at a directory that already contains `.mp4` files,
      **without** `--overwrite`, converts the others and leaves the existing ones
      untouched; with `OUTPUT` equal to `INPUT` the `.mp4` files are reported as
      skipped rather than silently passed over.
- [ ] `converter --list-formats` and bare `converter` both behave as described
      from a directory where ffmpeg is not on PATH.
- [ ] `converter video in out` fails with a message that tells the user what to
      run instead.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| `--to X` pointed at a large mixed tree tries to convert far more files than the old sub-commands did | The curated source-suffix set bounds it, `--dry-run` lists the tasks before any work, and the gate's open decision settles what a source the target cannot hold reports |
| A source whose output path equals its input path is read and written at once, or is overwritten by a sibling under `--overwrite` | Reported as a counted skip, and the sibling case refuses the run up front -- both per `docs/design/source-selection.md`, with a test for each and for the harmless no-`--overwrite` counterpart |
| A nested output root makes every run convert one more generation of its own output | Files under the output root are not candidates, pinned by a run-it-twice test |
| Removing the sub-commands breaks someone's script silently | `main()` recognises both legacy tokens and points at `--to` plus `--list-formats` -- generically, since naming a format in `cli.py` would defeat this phase's own format-name check; the concrete mapping lives in the README, and the `refactor!` commit plus migration lines drive the release note |
| The prompt drifts from the flags it builds | The prompt test dispatches its output through the same routing function a typed argv takes, so a prompted `mirror` argv is covered too |
| Phases 3-5 discover that `cli.py` still needs a diff per format | The `ast`-based format-name check fails the gate rather than surfacing in phase 3 |
| The test migration is large enough to be rushed | It is named in Scope and gets its own issue, rather than riding along in the parser issue |

## Decision log

- 2026-08-25: `docs/design/source-selection.md` added as the phase's design
  artifact — the batch-item flow `docs/design.md` names as its secondary
  decision, extended one step upstream to selection.
- 2026-08-25: Spec review found the same-suffix exclusion wrong whenever the
  output root differs from the input root: `In\a.mp4` -> `Out\a.mp4` is a
  legitimate remux, and excluding it would leave the output tree quietly
  incomplete. Replaced by a path-identity guard that reports rather than drops.
- 2026-08-25: Spec review found `--list-formats` unreachable under this spec's
  own parser decision, and the legacy sub-commands unable to produce the error
  the Outcome promised. Both are now explicit routing steps in `main()`.
- 2026-08-25: Spec review found that a source the target cannot produce at all
  fails the whole run, which no decision covered. Promoted to the phase's one
  open decision, with `--from` folded into it as one of three answers.
- 2026-08-25: Review round 2 found that reporting a self-writing source as
  skipped and then letting another source overwrite it in the same run is a
  file named as kept and then deleted. Self-writing sources now take part in the
  collision check, which runs first and refuses the run.
- 2026-08-25: Review round 2 found that a `--from` filter alone cannot satisfy
  the idempotent-re-run criterion on a mixed tree, so it was demoted from an
  answer to an optional addition, and the `unsupported` outcome became the part
  the phase needs either way.
- 2026-08-25: Review round 3 found that routing self-writes through the ordinary
  collision check over-corrected: an in-place re-run would exit 2 on the second
  run of a command that worked on the first. The refusal now fires only under
  `--overwrite`, where the destruction is real.
- 2026-08-25: Review round 3 found that a nested output root never converges —
  each run converts the previous run's output one level deeper. Files under the
  output root are now excluded from discovery.

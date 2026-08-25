# Constitution

> Normative and binding. Every principle must be verifiable and specific.
> Keep to ~1 page; this file is permanently loaded via CLAUDE.md. No status
> marker — foundation docs carry none.

## Tech stack

| Area | Choice | Rationale |
| ---- | ------ | --------- |
| Language | Python >= 3.11 | `StrEnum` and modern typing without `from __future__`; 3.11 is the floor CI proves |
| Media engine | the ffmpeg / ffprobe CLI, called with argv lists | Wrapper libraries are dead or broken; the reasoning is recorded in `converter/ffmpegtool.py` |
| Runtime dependencies | `tqdm>=4.66.3`, nothing else | Progress bar only; the floor is the fix for CVE-2024-34062 |
| Build backend | hatchling | PEP 517, no `setup.py` |
| Lint and format | ruff, explicit rule set, line length 100 | One tool for both; `select` is explicit so an upgrade cannot silently change the rule set |
| Tests | pytest >= 8, with the subprocess call stubbed | The suite must pass on a machine without ffmpeg installed |
| CI | GitHub Actions, Linux and Windows across Python 3.11-3.14, actions pinned to commit SHAs | Windows path behaviour is not optional; a tag can be moved, a SHA cannot |

## Architecture principles

- No shell, ever. Every external invocation is an argv list; `shell=True` must not
  appear anywhere in the tree.
- No path is ever interpolated into a command string. Paths reach ffmpeg only
  through `cli_path()` and `build_argv()`.
- Value types are frozen dataclasses.
- Maximum 50 lines per function.
- Every function parameter and every return value carries a type annotation.
- Every module has a module docstring.
- `ffprobe` never runs on the happy path — only after a conversion attempt has
  actually failed.
- A target format is data, not code: adding one must produce no diff in
  `cli.py`, `batch.py` or `paths.py`.
- One broken input file must not abort the batch.
- A partially written output file is removed when its conversion fails.

## Conventions

- Comments explain the *why*, never the *what*. A comment that restates the code
  is a review finding.
- A docstring on every module and every public function.
- English in code, comments, docs and commit messages.
- Conventional-commit subjects; `!` marks a breaking change.
- ffmpeg options are written through `flags("...")`, so a recipe reads like the
  command line you would type.
- Windows is a first-class target, not an afterthought.

## Quality gates

- `ruff check` clean.
- `ruff format --check` clean.
- `pytest` green.
- The CI matrix green on both Linux and Windows before a merge.
- A new degradation branch ships with a test asserting the note it emits.
- A new target format ships with a test pinning the argv it builds, for a
  copyable and for a non-copyable input.

## Don'ts

- No `shell=True`, and no command assembled as a string.
- No ffmpeg wrapper library — not `ffmpeg-python`, not `pydub`, not the unrelated
  `ffmpeg` package on PyPI.
- No second external binary dependency.
- Never parse ffmpeg's stderr to drive logic.
- No second runtime dependency without a recorded rationale.
- No unpinned GitHub Action.
- No `-map 0`: it also selects attachments and data streams that MP4 cannot hold.
- Never report success for a conversion that silently dropped something.

## Tech debt (brownfield only)

| Deviation | Where | Plan |
| --------- | ----- | ---- |
| `convert_command` is 54 lines, over the 50-line limit | `converter/cli.py` | Phase 2 rewrites it target-format-driven; split it there |
| Ruff `D` (pydocstyle) rules are not enabled, so the docstring convention rests on review | `pyproject.toml` | Enable pydocstyle once the noise is acceptable |
| The README names `develop` as the pull-request target | `README.md` | The base branch is `main`; correct it with the next docs change |

# converter

Batch media conversion built directly on the ffmpeg command-line program.

## Always in context

@docs/vision.md
@docs/constitution.md

## On demand (NOT auto-loaded)

Read these when the task needs them; they are deliberately kept out of the
permanent context for token budget.

- `docs/architecture.md` — components, boundaries, key flows, where new code goes.
  Read before adding or moving anything.
- `docs/roadmap.md` — the sequenced queue of phases and what each one covers.
- `docs/prior-art.md` — references indexed by concern, with per-entry ADOPT/AVOID
  notes. Tagged by the roadmap phase each concern feeds.
- `docs/workflow.md` — the operational contract: branch model, board, commands,
  gates, loop behaviour.
- `docs/design.md` — the design contract (`kind: concept`): Mermaid diagrams for
  the degradation ladder, and the rules they follow.
- `docs/release.md` — versioning, tag format, changelog, publish target.

## Commands on this machine

Neither the Python toolchain nor ffmpeg is on the PATH that tooling shells
inherit, so bare names fail. Full detail in `docs/workflow.md`; the short version:

- Verify (lint + format + tests): `.\.venv\Scripts\python.exe scripts\verify.py`
- ffmpeg / ffprobe: `C:\Users\bhemsen\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe`
  and `ffprobe.exe` in the same directory.
- Never call bare `python`: it resolves to the Windows Store stub, which is not an
  interpreter. To create a venv use
  `C:\Users\bhemsen\AppData\Local\Programs\Python\Python313\python.exe`.

The test suite stubs the subprocess boundary, so a green Verify proves nothing
about whether a conversion actually works. That evidence comes only from the QA
gate's ffmpeg smoke test.

## Autonomy

Within the loopkit skills the following are explicitly granted and override any
stricter global user rules: autonomous commits, pushes, PR creation and merges,
dependency installs, and `.env` edits. Hard limits live in
`.claude/settings.json` as deny rules — they apply in every mode, including
`bypassPermissions`, and deny always wins.

# Compact Instructions

Preserve the active milestone target and the unblocked issue frontier — both are
re-derivable from GitHub, so keep the identifiers rather than the details: the
milestone number and title, the issue numbers currently unblocked, and any issue
labelled `blocked:human` or `needs:planning` with the one-line reason. Keep
decisions made in-session that are not yet written to a doc or an issue. Drop
tool output, file listings, and reasoning that has already produced a committed
artifact.

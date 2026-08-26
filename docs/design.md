---
# concept — no UI, but a visualisation clarifies recurring decisions.
# The token blocks (color / type / spacing / radii / shadow) are pruned on
# purpose: this project renders no interface, so there is nothing to tokenise.
kind: "concept"
---

# Design contract

> Design contract for the loopkit skills (`/loopkit:design`, `/loopkit:plan`,
> `/loopkit:implement`) — the single source for this project's design medium,
> rules, and handoff. Filled during inception for a design-surface project — one
> that renders a UI, or where a visualisation would materially clarify recurring
> decisions; the skills read it instead of hardcoding any tool. The sibling of
> `docs/workflow.md`. A project with neither surface records `none` and has no
> `docs/design.md`.

## Overview

This project has no user interface: it is a CLI that prints lines and a progress
bar. It qualifies as a design-surface project on the second criterion only —
there is one decision shape that recurs across most of the roadmap, and it is far
easier to agree on as a picture than as prose.

That decision is the **degradation ladder**: given a source file's streams and a
target profile, what gets stream-copied, what gets re-encoded, what gets dropped,
and in which order attempts are tried. Phase 1 builds the generic engine for it,
and phases 3, 4 and 5 each re-make that decision for a new family of target
formats. A diagram makes the branch points explicit, so a spec can point at the
picture instead of re-describing the flow in words that drift apart between
phases.

The diagrams carry no visual character beyond legibility: they exist to settle a
control-flow question, not to look like anything.

## Design tool

- Tool / MCP: **none — Mermaid written by hand**. The medium is plain text in the
  repository, so there is no editor to authenticate against and no export step.
  No secondary tool.
- The tool is the **editor, never the source of truth.** The durable design
  state is the committed files in this repo (see Durable form), not anything
  living only inside the tool.
- Auth: in-session / subscription only — no headless run, no API key, no
  scheduler (constitution).

## Where designs live

- Source / working designs: the Mermaid source itself. Because the medium is
  text, the working copy and the durable artifact are the same file — there is no
  separate editing surface that could drift out of sync.
- Committed tokens: not applicable (`kind: concept` — no UI, no tokens).
- Committed assets: `docs/design/` — one `.md` file per diagram, holding a
  fenced ```mermaid block plus the prose that explains what the diagram decides.

## Diagram medium

- Medium: **Mermaid**, in a fenced ```mermaid block inside a Markdown file.
  Chosen because GitHub renders it natively in the PR diff — so the diagram is
  reviewable at the spec-acceptance gate without an export, and it diffs line by
  line, which an SVG or a PNG does not.
- Where diagrams live: `docs/design/<slug>.md`, referenced from the spec of the
  phase that needs it. Never an external editor's link.
- Decisions it clarifies: the degradation ladder — the order of conversion
  attempts, and the per-stream copy / re-encode / drop branch for a given target
  profile. Secondary: the state flow of a single batch item (pending, skipped,
  converted, failed) when a phase changes it.

Note for whoever writes these: Verify's format check covers Markdown since ruff
0.16, so a Python snippet inside a diagram file has to be formatted like real
code. Mermaid blocks themselves are untouched.

## Durable form

The durable design form is **a file committed to this repo** — a tokens file,
an exported image, or a screenshot — referenced from the spec or the issue. An
external-tool URL (a Figma / v0 / Paper share link) is NOT a valid durable form:
the tool is the editor, the committed file is the state (constitution:
GitHub-only durable state). When `/loopkit:design` finishes, the design exists
as a committed file at the location above, not as a link.

For this project that file is `docs/design/<slug>.md` with its Mermaid block.

## Review path

- Reviewer: the in-session Agent reviewer that reviews the spec package. There is
  no separate design critique step — a control-flow diagram is judged by whether
  it matches the spec's Verification section, which is the same reviewer's job.
- The design is reviewed **AT the spec-acceptance gate** as part of the spec
  package — never a separate stop after planning (constitution: exactly two
  human gates). Reference, do not restate.

## Handoff format

- Format the implementer consumes: the committed Markdown file, referenced by
  repo path from the phase's spec. The Mermaid source is read as text; nothing
  needs rendering to implement against it.
- `/loopkit:implement` consumes the committed artifact referenced from the
  design-surface issue; it never reaches into the design tool.

## Diagram conventions

Instead of UI components, these are the rules a diagram in this project follows.

- **Attempt ladder** — one node per rung, ordered top to bottom cheapest-first.
  Every edge that leaves a rung is labelled with the condition that takes it
  (`exit 0`, `exit != 0`), so no branch is implicit.
- **Per-stream decision** — every stream ends on exactly one of three outcomes:
  accept, re-encode, drop. "Accept" rather than "copy" because a stream the target
  accepts may still be transcoded in kind (a text subtitle becoming `mov_text`).
  Each drop edge is labelled with the reason the container cannot hold the
  stream. Draw one decision chain per stream type (video, audio,
  subtitle, other) while the code branches per type; draw the chain once,
  type-agnostically, once the code is driven by per-type data rather than per-type
  branches — a diagram that repeats an identical chain four times hides that the
  engine is generic. A diagram that takes the generic form says so in its header.
- **Cost markers** — any node that spends a subprocess call says so
  (`ffprobe`, `ffmpeg`). The point of the ladder is that ffprobe stays off the
  happy path of an *exhaustive* cheap attempt, and that the one exception — a
  cheap attempt the profile declares partial by construction, which is probed
  once even on success so its silent drops get named — is visible as its own
  node on the success side. A diagram that hides where processes start defeats
  both halves of that.

## Do's and Don'ts

**Do**

- Keep one decision per diagram; a second question means a second file.
- Label every edge with its condition, including the failure edges.
- Mark the nodes that cost a subprocess call.
- Reference the diagram from the spec by repo path, so it travels with the spec
  package into the acceptance review.

**Don't**

- Commit an image where Mermaid would do — it stops diffing and stops rendering
  in the review.
- Treat a share link as the design; commit the file.
- Restate the diagram's content in the spec's prose — reference it instead, or
  the two will drift.
- Add a third human gate — design is reviewed at spec-acceptance.

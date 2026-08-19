# Vision

> Normative. What and why only — no implementation detail. Keep to ~1 page;
> this file is permanently loaded via CLAUDE.md. No status marker — foundation
> docs carry none.

## Problem

The converter does two conversions, both one-way, both hard-wired. A third one
costs Python: write a `Job`, hand-maintain its fallback ladder, register it in
`JOBS`. Anyone who needs a different format ends up back at raw ffmpeg or at the
free tools that half-finish the job — and those stay silent about *what* they
sacrificed along the way.

## Why now

The refactoring pulled discovery, parallelism, collision checking and error
handling out of the recipes and covered them with 141 tests. A new format now
costs a recipe instead of a copy of the pipeline. That window is widest before
more sub-commands accumulate in the old shape: every additional format pair makes
the change more expensive.

## Target users

Primary: people with local media collections who want a directory tree turned
into one target format without driving ffmpeg themselves. Secondary: script and
pipeline users, for whom the exit code and parsable output are what matter.

## Goal

`converter --to <format>` takes whatever ffmpeg can read and writes one target
format, driven by a declarative profile per target that knows which codecs it may
stream-copy, what it re-encodes to otherwise, and what it cannot hold at all.
Whatever is lost gets named rather than hidden.

## USP / differentiation

Loss accounting plus idempotent resumption, in a scriptable CLI — not format
coverage, which ffmpeg already has. The evidence, the alternatives and the
per-entry ADOPT/AVOID harvest live in `docs/prior-art.md`; see its challenge
summary for why this is not redundant next to HandBrake, Shutter Encoder or a
shell loop around ffmpeg.

## Success criteria

- `converter --to X` works for at least 17 target formats: `mp4 mkv webm mov`,
  `mp3 m4a flac wav opus ogg`, `png jpg webp avif gif tiff bmp`.
- Adding a target format changes only its profile entry and its test — no diff in
  `cli.py`, `batch.py` or `paths.py`. Checkable against the diff of the most
  recently added format.
- Every degraded conversion names the stream index, that stream's codec, and what
  was given up. Checkable: each degradation branch has a test asserting the note.
- A second run over an already-converted tree reports 0 converted, 0 failed,
  exit 0.
- Every target profile has a test pinning the exact argv built for a copyable and
  for a non-copyable input.
- Verify stays under 60 s in CI.

## Scope

### In

- Target-format-driven conversion across audio, video and image formats.
- Declarative target profiles: copy mask plus fallback encoder per stream type.
- Recursive batch over a directory tree, mirroring its structure.
- Loss accounting per file.
- Skipping existing outputs, and refusing colliding output paths up front.
- Bounded parallelism, progress reporting, non-zero exit when anything failed.
- An interactive prompt for people who do not want to pass flags.

### Out

- A graphical interface.
- Trimming, cutting or concatenating.
- Filter-graph access.
- An encoder-tuning surface beyond sensible defaults.
- Network or streaming sources.

## Non-goals

- **HEIC, SVG, camera RAW** — these need libheif or a rasteriser, not an ffmpeg
  muxer, and would break the single-dependency promise.
- **EXIF/ICC preservation** — ffmpeg strips metadata by default, and PNG cannot
  carry EXIF at all by construction; promising it would be a lie.
- **Document conversion (pdf, docx, md)** — a different problem with a different
  tool (pandoc); adopting it would turn an ffmpeg wrapper into a conversion
  platform.
- **A second backend** — one external dependency is the promise made to the user;
  two doubles what has to be installed before anything works.
- **Corruption detection** — ffmpeg reports success for whatever it salvaged from
  a truncated source, so a trustworthy check would be a project of its own.

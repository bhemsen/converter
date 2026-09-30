# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [3.2.0] - 2026-09-30

The converter becomes a dependable child process: a machine-readable output
contract, writes that a kill cannot leave half-finished, and a target every
browser plays.

### Added

- **`--json`: one JSON record per file, then a summary.** JSON Lines on stdout —
  `file` records with `source`, `output` (both absolute), `outcome`, `attempt`,
  `notes` and `error`, and one closing `summary` with the counts and the exit
  code. Every record carries `type` and `schema` (`1`). Lines are pure ASCII and
  end in `\n` on every platform; nothing else reaches stdout. A stream without a
  `summary` is incomplete. `--json --dry-run` emits `planned` records.
- **Exit codes are a documented contract**: `0` (nothing failed — `skipped` and
  `unsupported` included), `1`, `2` (under `--json`, stdout stays empty), `130`,
  and new **`143` for SIGTERM**.
- **`--to web`: an MP4 every current browser plays.** It probes first instead
  of remuxing blindly, copies only 8-bit 4:2:0 H.264 and AAC/MP3, and re-encodes
  everything else to H.264 `yuv420p` (`-preset veryfast`) and AAC — naming each
  re-encode, including one caused by a 10-bit or 4:2:2 pixel format. All audio
  tracks and MJPEG/PNG cover art are kept; subtitles are dropped with a note.
  It shares the `.mp4` suffix with `--to mp4`, so write it to its own output
  directory. `--to mp4` is unchanged.

### Changed

- **Every output is written as `<output>.partial` and renamed only when
  complete.** A killed run no longer leaves a finished-looking output that the
  next run would skip; a stale `.partial` is removed by the next run that
  targets the same output. The `.partial` name is reserved, and two runs over
  the same tree at once are unsupported.
- **`--overwrite` keeps the previous output until the new one is complete**, so
  a failed overwrite no longer destroys a good file.
- **Termination stops ffmpeg.** Ctrl+C and, on POSIX, SIGTERM terminate every
  running ffmpeg and delete its partial file. On Windows, where a parent can only
  `TerminateProcess` the converter, a Job Object takes ffmpeg down with it.
- The note for a file whose output would be itself now reads "the output path
  is this file itself; not converted in place".

### Fixed

- An interrupt that landed while tasks were still being submitted skipped the
  termination path and left ffmpeg running (#159).

## [3.1.0] - 2026-09-28

A single file can now be converted on its own, with the same degradation ladder
and loss notes a directory run gives it, and `--to webm` keeps an alpha channel
instead of failing on it.

### Added

- **`INPUT` may name a single file.** `converter --to FORMAT FILE [OUTPUT]`
  converts that one file exactly as a non-recursive run over its directory
  would, so a one-off conversion no longer means falling back to raw ffmpeg and
  losing the notes on what was given up. `OUTPUT` is optional for a file — the
  result lands beside the source — and `--mirror-to` re-roots the file's
  directory as typed. A file you name is converted whatever its extension:
  ffmpeg, not the extension list, decides whether it is readable, and one it
  cannot read fails with ffmpeg's reason, exit 1.
- **An `OUTPUT` that looks like a file name is refused for a file `INPUT`.**
  `converter --to mp4 a.mkv b.mp4` exits 2 with `OUTPUT must be a directory; the
  output file name comes from INPUT and --to` instead of quietly creating a
  directory named `b.mp4`. A directory `INPUT` behaves exactly as before.
- **The interactive prompt accepts a file.** Given one, it skips the
  sub-directory question, and an empty output answer means the file's own
  directory.

### Changed

- A path that does not exist is now reported as `error: input does not exist`
  rather than `input directory does not exist`, since it may name either.

### Fixed

- **`--to webm` no longer fails on a source carrying an alpha channel, and no
  longer silently discards one.** An RGBA, 16-bit RGBA or grey+alpha PNG now
  converts to WebM with its alpha channel intact instead of failing outright;
  a source deeper than 8 bits per channel keeps its alpha but has its depth
  reduced to 8 bits, and that reduction is named. Every `.gif` source now
  converts too — previously all of them failed, transparent or fully opaque,
  because ffmpeg's own GIF decoder reports every GIF as carrying an alpha
  channel regardless of whether it does. A **transparent** paletted PNG,
  which already converted but silently lost its transparency, now keeps it —
  the cost is that an **opaque** paletted source, which already converted
  too, now does so at 4:2:0 chroma subsampling instead of 4:4:4, because the
  pixel format cannot tell the two apart.

## [3.0.0] - 2026-09-15

The target-format release. `converter --to <format>` replaces the two hard-wired
sub-commands, and seventeen target formats are driven by declarative profiles
instead of Python. Whatever a conversion gives up is named rather than hidden.

### Changed

- **BREAKING: `converter --to <format>` replaces the `video` and `audio`
  sub-commands.** One flag now selects any target format, so the tool is no
  longer two one-way conversions.

  Migration:

  | Before | Now |
  | ------ | --- |
  | `converter video IN OUT` | `converter --to mp4 IN OUT` |
  | `converter audio IN OUT` | `converter --to wav IN OUT` |

  Run `converter --list-formats` for the full set. Scripts calling the old
  sub-commands fail with a usage error rather than converting anything, so the
  break is loud rather than silent.

- A target format is now **data, not code**. Each target is one profile entry
  declaring which codecs it may stream-copy, what it re-encodes to otherwise,
  and what it cannot hold at all. Adding a format touches its profile entry and
  its test — not the CLI, the batch runner or the path logic.

- Degradation notes name the **stream index and that stream's codec**, so a
  report says which stream lost what rather than making a statement about the
  format in general.

### Added

- **Seventeen target formats.** Video: `mp4`, `mkv`, `webm`, `mov`. Audio:
  `mp3`, `m4a`, `flac`, `wav`, `opus`, `ogg`. Image: `png`, `jpg`, `webp`,
  `avif`, `gif`, `tiff`, `bmp`.
- `--list-formats`, which prints each target and what it can hold.
- **Loss accounting.** A conversion that drops a stream, re-encodes one, or
  cannot carry a property says so per file, naming the stream.
- **Success-side verification.** A cheap attempt whose mapping can leave source
  streams unmapped is checked after it succeeds, so a silent drop is reported
  instead of passing as a plain success. What the mapping is predicted to give
  up is confirmed against the file that was actually written before it is
  printed — a muxer may put back what no `-map` selected.
- **Cover art is carried into `mp3`, `m4a` and `flac`** instead of being
  dropped, by telling an attached picture apart from a real video stream.
- **Lossy-source advisory.** Converting an already-lossy source into `flac`
  says that the target cannot restore what the source had discarded — an
  advisory about the source's history, not a claim that this run destroyed
  anything.
- **Conditional transparency notes.** `jpg`, `gif` and `avif` state a
  transparency loss only when the source could actually carry alpha, measured
  from its pixel format. An opaque JPEG is no longer told its transparency was
  not carried.
- An `unsupported` outcome, distinct from a failure, for a source the target
  cannot hold at all.

### Fixed

- `Ctrl+C` stops queued conversions instead of draining the rest of the batch.
- `--mirror-to` mirrors onto the typed input path rather than its resolved one,
  so a relative input no longer produces an unexpected output tree.
- An output path too long for the filesystem fails that one file instead of the
  whole batch.
- The `flac` advisory no longer fires for cover art the rung only copies
  byte-for-byte — nothing was discarded there.
- `--jobs` is no longer documented as capped by CPU count; it is not.

### Known limitations

- **`--to webm` failed for a source carrying an alpha channel — fixed, not yet
  released** (see *Unreleased* above). Measured with ffmpeg 9.0: an RGBA PNG
  was refused by `libvpx-vp9` with *"Pixel format 'gbrap' is not widely
  supported"*, on every rung of the ladder. This understated the defect: every
  `.gif` source failed the same way, opaque ones included, because ffmpeg's
  GIF decoder reports every GIF as carrying an alpha channel (`bgra`)
  regardless of whether it actually does. The failure was reported and the
  batch continued with a non-zero exit — nothing was silently corrupted — but
  the file did not convert.
- **`--to opus` can hand you a `.opus` file that is actually Vorbis**, because
  the Ogg muxer accepts either. The README documents when this happens.
- **Metadata is not preserved.** ffmpeg strips it by default, and PNG cannot
  carry EXIF at all, so the tool does not promise what it cannot deliver.

## [2.0.0] - 2026-08-19

Backfilled at the 3.0.0 release; this version carries no git tag. Recorded so
the history starts somewhere honest rather than at 3.0.0.

### Changed

- **BREAKING:** the four standalone scripts were replaced by a packaged
  `converter` CLI with `video` and `audio` sub-commands, installable with
  `pip install -e .`.

[3.2.0]: https://github.com/bhemsen/converter/releases/tag/v3.2.0
[3.1.0]: https://github.com/bhemsen/converter/releases/tag/v3.1.0
[3.0.0]: https://github.com/bhemsen/converter/releases/tag/v3.0.0

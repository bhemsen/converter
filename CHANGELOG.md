# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **`--to webm` no longer fails on a source carrying an alpha channel, and no
  longer silently discards one.** An RGBA, 16-bit RGBA, grey+alpha or paletted
  PNG now converts to WebM with its alpha channel intact instead of failing
  outright; a source deeper than 8 bits per channel keeps its alpha but has its
  depth reduced to 8 bits, and that reduction is named. Every `.gif` source now
  converts too — previously all of them failed, transparent or fully opaque,
  because ffmpeg's own GIF decoder reports every GIF as carrying an alpha
  channel regardless of whether it does. A transparent paletted PNG, which
  previously converted "successfully" while silently losing its transparency,
  now keeps it.

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

[3.0.0]: https://github.com/bhemsen/converter/releases/tag/v3.0.0

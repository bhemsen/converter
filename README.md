# converter

Batch media conversion that just works, built for people who got tired of free
converter tools that half-finish the job.

It is a thin, honest wrapper around [ffmpeg](https://ffmpeg.org/): it builds the
command line, runs a bounded number of conversions in parallel, tells you what it
changed, and exits non-zero if anything failed.

## Available target formats

The tool is driven by a target format rather than by one sub-command per
format pair. Run `converter --list-formats` to print exactly what your
installed version supports; today that is:

```
Target formats:
  avif  .avif  Image: force-encoded to AVIF; a multi-frame source is reduced to a single frame
  bmp   .bmp  Image: force-encoded to BMP, lossless
  flac  .flac  Audio: single stream, lossless FLAC
  gif   .gif  Image: force-encoded to GIF, animated; a photograph is reduced to 256 colours
  jpg   .jpg  Image: force-encoded to JPEG; transparency is not carried
  m4a   .m4a  Audio: every stream the source has; most players use only the first
  mkv   .mkv  Video: copies almost every codec as-is, keeps font attachments
  mov   .mov  Video: copies compatible streams, re-encodes the rest to h264/aac; no attachments
  mp3   .mp3  Audio: single stream, MP3 (libmp3lame if re-encoded)
  mp4   .mp4  Video: copies compatible streams, re-encodes the rest to h264/aac
  ogg   .ogg  Audio: every stream the source has; most players use only the first
  opus  .opus  Audio: every stream the source has; most players use only the first
  png   .png  Image: force-encoded to PNG, lossless
  tiff  .tiff  Image: force-encoded to TIFF, lossless
  wav   .wav  Audio: single stream, uncompressed 16-bit PCM
  web   .mp4  Video for web browsers: copies 8-bit h264 and aac/mp3, re-encodes the rest to h264/aac
  webm  .webm  Video: copies VP8/VP9/AV1 and Opus/Vorbis, re-encodes the rest to VP9/Opus
  webp  .webp  Image: copies compatible streams, animated; falls back to WebP re-encode
```

`m4a`, `ogg` and `opus` carry every audio stream the source has — nothing is
dropped, but most players only offer the first, so a source with several audio
tracks is not obviously "converted in full" just by looking at what plays.

More target formats can be added — see [Contributing](#contributing).

## Requirements

* **Python 3.11 or newer**
* **ffmpeg** (and `ffprobe`, which ships with it) on your `PATH`
  * Windows: `winget install Gyan.FFmpeg`
  * macOS: `brew install ffmpeg`
  * Linux: `sudo apt install ffmpeg`
  * Others: [ffmpeg.org/download.html](https://ffmpeg.org/download.html)

Keep ffmpeg reasonably current. It is the component that parses untrusted media
files, so it is where media-parsing security fixes land.

**ffmpeg 7.1 or newer is worth having, but is not required.** Converting to
`mp3`, `m4a` or `flac` uses a stream selector that arrived in 7.1 to carry
embedded cover art across. On an older build — Ubuntu 24.04 ships 6.1.1, Debian
12 ships 5.1.9 — those three conversions cost one extra ffmpeg call per file and
then produce the same result, artwork included. Every other target is unaffected.

## Install

```sh
git clone https://github.com/bhemsen/converter.git
cd converter
python -m pip install -e .
```

That gives you a `converter` command. If you would rather not install anything,
`python -m converter` works the same way from the repository root once
`python -m pip install -r requirements.txt` has run.

## Usage

```sh
converter --to FORMAT INPUT [OUTPUT]         # INPUT: a file or a directory; e.g. --to mp4, --to wav
converter mirror INPUT_ROOT OUTPUT_ROOT      # re-create a directory tree elsewhere
converter --list-formats                     # print the target formats above
```

`OUTPUT` is required for a directory `INPUT`, but optional for a file: omitted,
the result lands beside the source.

Run `converter` with no arguments for an interactive prompt that asks the same
questions and then runs the same code — it adapts to a file `INPUT` too,
skipping the sub-directory question and taking an empty output answer as the
file's own directory — or `converter --help` for the full option list
(`converter mirror --help` for the mirror sub-command's own).

> **Coming from an older version?** The `video` and `audio` sub-commands are
> gone; a target format replaces them:
>
> * `converter video IN OUT` → `converter --to mp4 IN OUT`
> * `converter audio IN OUT` → `converter --to wav IN OUT`
>
> Running the old sub-command now prints a pointer to `--to` and
> `--list-formats`, and exits with status 2.

### Options

| Option | Effect |
| --- | --- |
| `--to FORMAT` | target format to convert everything to (required); a name or a dotted suffix, e.g. `mp4` or `.mp4` — see `--list-formats` |
| `--list-formats` | list the target formats available and exit |
| `-r`, `--recursive` | also convert files in sub-directories, keeping the tree in the output |
| `--mirror-to ROOT` | derive the output directory by re-rooting `INPUT` onto `ROOT`, e.g. `E:` — use instead of `OUTPUT` |
| `-j N`, `--jobs N` | conversions to run in parallel, not capped (default: 4, or fewer if the machine has fewer CPUs) |
| `--overwrite` | replace existing output files instead of skipping them |
| `--dry-run` | print what would be converted and stop |
| `-q`, `--quiet` | hide the progress bar |
| `--json` | emit newline-delimited JSON on stdout instead of prose (implies no progress bar) — see [Machine-readable output](#machine-readable-output) |
| `--ffmpeg`, `--ffprobe` | use a specific executable instead of searching `PATH` |

> **A file as `INPUT`.** A named file is converted whatever its suffix — it
> bypasses the curated suffix list used for a directory walk, since ffmpeg
> decides whether it is readable; a file ffmpeg cannot read still ends
> `FAILED` with its reason, exit 1, never a usage error. `OUTPUT` stays a
> directory: an existing non-directory `OUTPUT`, or a missing one whose
> suffix already matches the target format, is refused up front (`error:
> OUTPUT must be a directory; the output file name comes from INPUT and
> --to`, exit 2).

> **`--mirror-to` and `subst`/junction/symlinked inputs.** `--mirror-to` re-roots
> `INPUT` onto `ROOT` using the path you typed, not the physical path it
> resolves to. So `subst Q: <fixtures>` followed by
> `converter --to mp4 -r Q:\ --mirror-to R:` writes to `R:\Season1\...`, mirroring
> the shallow tree under `Q:\` — **not** `R:\Users\...\<physical path>\Season1\...`,
> the whole physical path `Q:` happens to resolve to. The same holds for a
> directory junction, an NTFS symlink standing in for `INPUT`, or a relative
> `INPUT` (mirrored from the path as given, not resolved against the current
> working directory first). This only changes the *shape* of the mirrored tree,
> never its safety: a self-write (`INPUT` and `--mirror-to` resolving to the
> same file) is still reported as a skipped file at exit 0, and an `--overwrite`
> hazard that would destroy one of the run's own inputs is still refused at
> exit 2 — both checks resolve the input and the derived output path to their
> physical location at comparison time, so mirroring a virtual drive back onto
> the real directory behind it is still caught exactly as if no
> `subst`/junction/symlink were involved.

### Examples

```sh
# Everything under D:\Rips, mirrored onto E: with the same folder structure
converter --to mp4 D:\Rips --mirror-to E: --recursive

# Check first, convert second
converter --to mp4 D:\Rips E:\Done --recursive --dry-run
converter --to mp4 D:\Rips E:\Done --recursive

# Six at a time, replacing what is already there
converter --to mp4 D:\Rips E:\Done -r -j 6 --overwrite

# Rip audio out to WAV instead
converter --to wav D:\Rips E:\Audio --recursive

# Convert a single file; with no OUTPUT, song.mp3 lands next to song.flac
converter --to mp3 D:\Rips\song.flac
```

Existing outputs are **skipped** by default, so re-running after an interruption
only does the remaining work.

| Exit code | Meaning |
| --- | --- |
| `0` | nothing failed — `skipped` and `unsupported` files count as success too |
| `1` | at least one file failed, or an unexpected error aborted the run |
| `2` | a usage error, a refusal (e.g. a collision or overwrite hazard), or a missing ffmpeg |
| `130` | interrupted (Ctrl+C / SIGINT) |
| `143` | terminated (`SIGTERM`, POSIX only) |

> **Under `--json`, exit 2 always leaves stdout empty.** A usage error, a
> refusal, or a missing ffmpeg happens before any file is reported, so nothing
> reaches stdout — the exit code alone says the run did nothing; the reason is
> on stderr as always. Exit 130, exit 143, and an aborting exit 1 all end the
> run without writing the final `summary` record — see
> [Machine-readable output](#machine-readable-output) for what a consumer does
> with a stream that ends that way.

> **Every output is written safely.** A conversion writes to `<output>.partial`
> and is renamed into place only after ffmpeg has succeeded and, where the loss
> report needs it, the partial has been probed for what it kept — this is loss
> accounting, not a corruption check (ffmpeg is not asked to verify the file it
> just wrote). A failed or interrupted conversion leaves no `.partial` file
> behind. The `.partial` name is reserved for the run using it — running two
> converters over the same output tree at once is unsupported, since one run's
> clean-up would delete the other's file mid-write. A `.partial` left over from
> an earlier run that got killed is removed the next time a non-`--dry-run` run
> targets that same output, whether the file then converts or is skipped as
> already there.
> `--overwrite` does not touch the existing output until the replacement is
> complete, so a failed `--overwrite` (a bad source, an interruption) leaves the
> old file exactly as it was.

> **What a kill leaves behind.** Ctrl+C, and on POSIX `SIGTERM`, stop every
> ffmpeg process the run has started and delete every `.partial` file still
> being written, then exit `130` or `143` respectively; a conversion already
> renamed into place by the time the kill lands is unaffected either way. On
> Windows, a parent that can only reach for `TerminateProcess` — Node's
> `child.kill()`, for example — gives the converter no chance to react to it at
> all; instead every ffmpeg/ffprobe child is bound, at startup, to the same
> Windows Job Object as the converter itself (a failure to bind only prints a
> warning and the run proceeds unprotected), so killing the converter normally
> kills them with it, and the next run removes whatever `.partial` file was
> left. A POSIX `SIGKILL` is the one case nothing in the process can react to:
> ffmpeg keeps running until it finishes unless the whole process group is
> killed with it, and either way the next run removes the `.partial` file it
> finds.

## Machine-readable output

`--json` replaces every printed line with newline-delimited JSON on stdout: one
`file` record per file as it finishes (completion order, not the order you
passed them), then one `summary` record last. Nothing else reaches stdout — no
progress bar, no `Using ffmpeg …` banner (it moves to stderr, still hidden by
`-q`), no `note`/`FAILED` prose.

Each line is one complete, pure-ASCII JSON object terminated by a single `\n`
byte — never `\r\n`, on Windows either, because the bytes go straight to the
stdout buffer instead of through the text layer. A non-ASCII path (or, on
POSIX, a file name that reached Python as lone surrogates) is escaped to
`\uXXXX`, so every line parses under any locale or code page. Every record's
first two keys, in order, are `type` (the discriminator) and `schema` (the
integer schema version, `1` today).

Example — captured from one real run (`--to png` over a directory holding a
video and an audio-only file), paths shortened:

```json
{"type": "file", "schema": 1, "source": "D:\\Rips\\audio_only.mp3", "output": "E:\\Done\\audio_only.png", "outcome": "unsupported", "attempt": null, "notes": ["audio stream 0 (mp3) dropped: not supported by PNG"], "error": null}
{"type": "file", "schema": 1, "source": "D:\\Rips\\clip1.mp4", "output": "E:\\Done\\clip1.png", "outcome": "converted", "attempt": "single-frame", "notes": ["only the first frame was kept; PNG cannot hold more than one image", "non-video streams, and any video stream beyond the first, are not carried into PNG"], "error": null}
{"type": "summary", "schema": 1, "converted": 1, "skipped": 0, "failed": 0, "unsupported": 1, "total": 2, "planned": 0, "exit_code": 0, "dry_run": false}
```

### Record types

**`file`** — one per file the run reports on, including a pre-batch skip (a
self-write) and a staging failure: nothing that was pointed at is left off the
stream.

| Key | Type | Meaning |
| --- | --- | --- |
| `source` | string | the source path, absolute (`Path.absolute()`, never `resolve()`) |
| `output` | string | the output path it maps to, absolute, whether or not it was written |
| `outcome` | string | `"converted"`, `"skipped"`, `"failed"`, or `"unsupported"` |
| `attempt` | string \| `null` | the rung that produced the file (`remux`, `selective`, …); `null` unless `outcome` is `"converted"` |
| `notes` | array of strings | every note and advisory, in the order the text mode prints them; `[]` when there are none |
| `error` | string \| `null` | the failure reason; `null` unless `outcome` is `"failed"` |

**`planned`** — `--dry-run` only, one per task that would convert: `type`,
`schema`, `source`, `output`. A pre-batch skip still appears as a `file` record
with `outcome: "skipped"`, dry run or not.

**`summary`** — exactly one, last:

| Key | Type | Meaning |
| --- | --- | --- |
| `converted`, `skipped`, `failed`, `unsupported`, `total` | integer | the same counts the text summary sentence uses |
| `planned` | integer | number of `planned` records emitted; `0` outside `--dry-run` |
| `exit_code` | integer | the code the process is about to exit with |
| `dry_run` | boolean | whether this was `--dry-run` |

### An incomplete stream

A stream **without** a `summary` line is incomplete: exit 130, exit 143, and an
aborting exit 1 (an unexpected error, not a per-file failure) all stop the run
before one is written. The `file` records already written still stand — but an
interrupt can also cut the very last line mid-write, so a consumer should
discard a trailing line that is not `\n`-terminated rather than fail to parse
it.

### The schema is open

A consumer must ignore keys it does not recognise — a later version can add a
key, or a new record type, without breaking anything reading today's stream.
Removing or renaming a key, or changing what a value means, is a breaking
change and raises `schema` past `1`.

## How a conversion works

Every target format is a declarative profile (`converter/profiles.py`): a copy
mask that says which codecs it may stream-copy, a fallback encoder for
everything else, and what it cannot hold at all. The engine in
`converter/jobs.py` turns one profile into the same three-step ladder for
every format:

1. **Cheap attempt first.** For MP4 that is a remux: video, audio and text
   subtitles are stream-copied (`-c copy`, subtitles to `mov_text`). Nothing is
   re-encoded, so there is no quality loss and it runs at disk speed. For WAV
   it is a decode of the first audio stream straight to PCM — WAV cannot hold
   anything else as-is. Either way, because the mapping can, by construction,
   leave source streams unmapped (MKV attachments and data streams for MP4, a
   second audio stream for WAV), a successful cheap attempt still spends one
   `ffprobe` call to name each stream it left behind, rather than reporting a
   plain success.
2. **If the cheap attempt fails, look at the file instead.** `ffprobe` reports
   the streams, and each one is handled individually against the profile's
   copy mask: compatible streams are still copied, incompatible ones are
   re-encoded with the profile's fallback encoder, and streams the target
   cannot hold at all (bitmap subtitles into MP4, a second audio stream into
   WAV) are dropped.
3. **As a last resort, re-encode.** MP4 declares one: one video and all audio
   streams re-encoded to h264/aac. WAV has nothing left to fall back to beyond
   step 2, so its ladder ends there.

Anything sacrificed along the way is printed, for example:

```
note    Show.S01E01.mkv: video stream 0 (theora) re-encoded to h264
note    Show.S01E02.mkv: subtitle stream 2 (hdmv_pgs_subtitle) dropped: bitmap subtitles cannot be stored in MP4
```

### Notes and limitations

* **Some exotic codecs remux "successfully" but play badly.** ffmpeg will happily
  put Vorbis or VP9 into an MP4 container, so step 1 succeeds and nothing is
  re-encoded — but many players and TVs will not touch those streams. If a
  converted file refuses to play, that is the likely reason.
* **WAV, MP3 and FLAC each hold one audio stream.** For a source with several
  audio streams, the first one is converted and the rest are dropped. For MP3
  and FLAC that limit is the container's own muxer, not a choice this tool
  makes.
* **MP3, FLAC and M4A carry embedded cover art, but nothing else non-audio.**
  A picture stream survives a straight copy untouched, byte for byte. Any
  other video, subtitle or attachment stream a straight copy leaves out is
  reported only when one was actually present to drop; nothing prints for a
  source that never had one. The one place that is not true is each format's
  re-encode rung, reached only when a matching codec's copy is refused
  outright: its note names what that rung structurally cannot carry
  regardless of whether this particular source had any to give up, the same
  as it always has.
* **MKV, MOV and WebM name a dropped attachment, data or timecode stream
  individually, by index and codec, rather than with a blanket warning.** MKV
  keeps font attachments and drops data or timecode streams; MOV rejects a
  mapped attachment outright, so its loss surfaces through the same rung a
  genuinely incompatible codec would, and its muxer regenerates a `tmcd`
  timecode track from source metadata on its own, so that one is not
  reported as dropped even though nothing mapped it; WebM silently discards
  an attachment, data or timecode stream at exit 0. None of the three prints
  anything for a source that carries none of these.
* **JPG, GIF and AVIF name a transparency loss only when the source could
  actually carry one.** Step 1 or step 2 checks the source's own pixel
  format: an ordinary opaque image gets no transparency note at all, and one
  that could carry alpha gets a note naming its stream index and codec. Two
  cases still warn every time, on purpose: a paletted source (`pal8`) can
  hide real transparency the palette format itself does not flag, and every
  `.gif` source decodes as if it had an alpha channel whether or not it did —
  in both cases the tool would rather warn about a loss that might not have
  happened than stay silent about one that did. An already-AVIF source is
  the one case handled the other way: ffmpeg reports the same pixel format
  whether or not the file carried alpha, so the tool cannot tell and stays
  silent here — the one place it under-reports rather than over-reports.
  GIF's 256-colour palette limit and AVIF's single-frame limit are unrelated
  to this and still fire on every conversion regardless of the source: each
  states what this tool's GIF or AVIF pipeline always does — ffmpeg's GIF
  encoder quantises to a single 256-entry palette, and its AVIF muxer keeps
  one frame no matter what is asked of it — not what those formats can hold
  elsewhere, which is more. Counting colours or frames would cost a decode
  or an extra probe this tool does not spend. Step 3, reached only once the
  faster paths have failed, never gets to look at the source's streams at
  all, so it restates every one of these limits as fixed text instead.
* **`--to opus` can hand you a `.opus` file that is actually Vorbis.** A
  Vorbis source (typically a `.ogg`/`.oga` file) is stream-copied into the
  `.opus` container without transcoding — genuinely lossless, but `.opus` is a
  codec-defined format (RFC 7845), so strict players may reject the result.
  This is a deliberate trade: forcing a re-encode instead would cost every
  already-Opus source a generation loss just to guard against a mislabel that
  only a Vorbis source can trigger. Point a Vorbis source at `--to ogg`
  instead for a lossless copy that keeps its real codec.
* **Windows path length.** Mirroring a deep source tree onto a sub-directory can
  push paths past Windows' 260-character limit; the error message says so when it
  happens. Either pick a shorter output root or
  [enable long-path support](https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation).
* Corrupt inputs are not detected as such. ffmpeg salvages what it can and
  reports success, so a truncated source can yield a truncated result.

## Development

```sh
python -m pip install -e ".[dev]"
ruff check .          # lint
ruff format .         # format
pytest                # tests
```

The tests do not need ffmpeg installed: they cover the command lines that get
built and the decisions around them, and stub out the subprocess call itself.
CI runs lint, format check and tests on Linux and Windows across Python
3.11–3.14.

### Layout

| File | Purpose |
| --- | --- |
| `converter/cli.py` | argument parsing, target-format selection, the interactive prompt |
| `converter/profiles.py` | one declarative profile per target format: copy mask, fallback encoder, container flags |
| `converter/jobs.py` | the generic conversion engine that turns a profile into a fallback ladder |
| `converter/batch.py` | bounded parallel execution, progress, result aggregation |
| `converter/paths.py` | input discovery and output-path construction |
| `converter/ffmpegtool.py` | building and running ffmpeg/ffprobe commands |

To add a target format, add a profile entry to `converter/profiles.py` and its
test. Everything else — discovery, parallelism, progress, error handling — is
shared, and stays untouched: `cli.py`, `batch.py` and `paths.py` see no diff.

## Contributing

Feel free to clone or fork this project and add whatever target format or
feature you need. Just open a branch and create a pull request against `main`,
and assign it to me.

### Commit messages

A short description is enough. Please keep it professional, and say *why* rather
than only *what*.

### Code

Use whatever structure or style you prefer, but please be as declarative as
possible and leave comments so others can follow your thinking. `ruff check` and
`pytest` should pass before you open the pull request.

### Help each other

Do not be afraid to contribute. It does not matter what skill level you have.
There is no room for shaming here.

## Legal notice

I am not responsible for what you do with this software. Please only use it on
files you legally own.

## License

[MIT](LICENSE)

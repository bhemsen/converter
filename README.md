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
  bmp   .bmp  Image: force-encoded to BMP, lossless
  flac  .flac  Audio: single stream, lossless FLAC
  jpg   .jpg  Image: force-encoded to JPEG; transparency is not carried
  mkv   .mkv  Video: copies almost every codec as-is, keeps font attachments
  mp3   .mp3  Audio: single stream, MP3 (libmp3lame if re-encoded)
  mp4   .mp4  Video: copies compatible streams, re-encodes the rest to h264/aac
  png   .png  Image: force-encoded to PNG, lossless
  tiff  .tiff  Image: force-encoded to TIFF, lossless
  wav   .wav  Audio: single stream, uncompressed 16-bit PCM
```

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
converter --to FORMAT INPUT_DIR OUTPUT_DIR   # e.g. --to mp4, --to wav
converter mirror INPUT_ROOT OUTPUT_ROOT      # re-create a directory tree elsewhere
converter --list-formats                     # print the target formats above
```

Run `converter` with no arguments for an interactive prompt that asks the same
questions and then runs the same code, or `converter --help` for the full
option list (`converter mirror --help` for the mirror sub-command's own).

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
| `--mirror-to ROOT` | derive the output directory by re-rooting `INPUT_DIR` onto `ROOT`, e.g. `E:` — use instead of `OUTPUT_DIR` |
| `-j N`, `--jobs N` | conversions to run in parallel (default: 4, capped by CPU count) |
| `--overwrite` | replace existing output files instead of skipping them |
| `--dry-run` | print what would be converted and stop |
| `-q`, `--quiet` | hide the progress bar |
| `--ffmpeg`, `--ffprobe` | use a specific executable instead of searching `PATH` |

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
```

Existing outputs are **skipped** by default, so re-running after an interruption
only does the remaining work. Exit status is `0` when nothing failed, `1` when at
least one file failed, and `2` for a usage error or a missing ffmpeg.

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
* **MP3 and FLAC never carry video.** Any non-audio stream — including
  embedded cover art — is left out. A straight copy says so even when the
  source had nothing to lose; when the audio itself has to be re-encoded, the
  dropped stream is still named, just without the extra line.
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

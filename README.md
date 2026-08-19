# converter

Batch media conversion that just works, built for people who got tired of free
converter tools that half-finish the job.

It is a thin, honest wrapper around [ffmpeg](https://ffmpeg.org/): it builds the
command line, runs a bounded number of conversions in parallel, tells you what it
changed, and exits non-zero if anything failed.

## Available conversions

* `.mkv` → `.mp4` (stream copy where possible, so usually lossless and near-instant)
* `.opus` → `.wav` (uncompressed 16-bit PCM)

More can be added in `converter/jobs.py` — see [Contributing](#contributing).

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
converter video INPUT_DIR OUTPUT_DIR      # .mkv -> .mp4
converter audio INPUT_DIR OUTPUT_DIR      # .opus -> .wav
converter mirror INPUT_ROOT OUTPUT_ROOT   # re-create a directory tree elsewhere
```

Run `converter` with no arguments for an interactive prompt, or
`converter video --help` for the full option list.

### Options

| Option | Effect |
| --- | --- |
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
converter video D:\Rips --mirror-to E: --recursive

# Check first, convert second
converter video D:\Rips E:\Done --recursive --dry-run
converter video D:\Rips E:\Done --recursive

# Six at a time, replacing what is already there
converter video D:\Rips E:\Done -r -j 6 --overwrite
```

Existing outputs are **skipped** by default, so re-running after an interruption
only does the remaining work. Exit status is `0` when nothing failed, `1` when at
least one file failed, and `2` for a usage error or a missing ffmpeg.

## How the video conversion works

1. **Remux first.** Video, audio and text subtitles are stream-copied into MP4
   (`-c copy`, subtitles to `mov_text`). Nothing is re-encoded, so there is no
   quality loss and it runs at disk speed. MKV attachments (such as fonts for ASS
   subtitles) and data streams are dropped, because MP4 cannot hold them.
2. **If that fails, look at the file.** `ffprobe` reports the streams, and each
   one is handled individually: compatible streams are still copied, incompatible
   audio or video is re-encoded, and bitmap subtitles (PGS, VobSub) are dropped.
3. **As a last resort, re-encode.** One video and all audio streams to
   h264/aac.

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
* **WAV holds one audio stream.** For `.opus` files with several audio streams,
  the first one is converted and the rest are dropped.
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
| `converter/cli.py` | argument parsing, sub-commands, interactive prompt |
| `converter/jobs.py` | the conversion recipes and their fallback ladders |
| `converter/batch.py` | bounded parallel execution, progress, result aggregation |
| `converter/paths.py` | input discovery and output-path construction |
| `converter/ffmpegtool.py` | building and running ffmpeg/ffprobe commands |

To add a conversion, add a `Job` in `converter/jobs.py` and register it in
`JOBS`. Everything else — discovery, parallelism, progress, error handling — is
shared.

## Contributing

Feel free to clone or fork this project and add whatever file-type conversion or
feature you need. Just open a branch and create a pull request against `develop`,
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

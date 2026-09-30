# Spec: web-target (roadmap phase 13)

> Created: 2026-09-30

`converter --to web` writes an MP4 that a plain HTML5 `<video>` plays in every
current browser: it copies only what every browser decodes and re-encodes the
rest, and it decides that from a probe *before* the first attempt instead of
trusting a blind remux. This spec carries no lifecycle state — acceptance is the
spec merged on the default branch with a milestone and issues, and all progress
lives in the GitHub issues and milestone. A completed spec is moved to
`docs/specs/archive/`.

## The gap

`--to mp4` answers "can MP4 hold this?", not "can a browser play this?". Its
cheap attempt is a blind `-c copy` remux (`profiles.MP4`, `jobs.first_attempt`),
and the copy mask only matters on the selective rung, which runs **only after the
remux failed**. MP4 legally holds HEVC, AC-3, E-AC-3, MPEG-4 Part 2, MPEG-2 and
10-bit H.264, so the remux succeeds, the run reports `converted`, and the file
shows a black picture or plays silently in Chrome or Firefox (`README.md`,
*How a conversion works*; `docs/prior-art.md`, *Browser-playable target*).
*videothek*, a browser player, needs a target where "converted" means "plays".

## Outcome

- [ ] `converter --to web` exists, listed by `--list-formats` and the prompt,
      writing `<stem>.mp4` through the `mp4` muxer with `+faststart`.
- [ ] A source whose every video stream is 8-bit 4:2:0 H.264 (`yuv420p` or
      `yuvj420p`) and whose every audio stream is AAC or MP3 is copied, not
      re-encoded — on the first and only attempt.
- [ ] Any other video stream is re-encoded to H.264 `yuv420p`, any other audio
      stream to AAC, each with a note naming the stream index, its codec and —
      where the codec itself was copyable but its pixel format was not — that
      pixel format.
- [ ] Every audio stream is kept.
- [ ] Every subtitle stream is dropped with a note (phase 14 turns text
      subtitles into sidecars); cover art in MJPEG or PNG is kept, anything else
      dropped with a note.
- [ ] A `web` conversion spends exactly one `ffprobe`, before its first
      attempt, and none after a success.
- [ ] Every existing target's argv, notes and probe count are unchanged.
- [ ] The engine capability (probe-first, the pixel-format copy condition) lands
      in its own change; the change that adds `web` touches only
      `converter/profiles.py` and its tests — the vision's "a new format is data"
      criterion, checked against that diff.
- [ ] `docs/vision.md`, `docs/constitution.md`, `docs/architecture.md`,
      `docs/design/degradation-ladder.md`, `docs/design/stream-decision.md` and
      `README.md` carry the change.

## Scope

### In scope

- **Engine capability** (`converter/profiles.py` dataclasses, `converter/jobs.py`,
  `converter/batch.py`):
  - `Profile.probe_first: bool = False`. A probe-first profile declares
    `cheap_attempt=None`; `jobs.first_attempt` returns `None` for it, and
    `batch` — which only sees that the engine offers no first attempt — probes
    first and climbs `jobs.retries` directly. `Profile.cheap_attempt` becomes
    `Attempt | None`; a test over `PROFILES` pins "`cheap_attempt is None` exactly
    when `probe_first`".
  - `StreamRule.copy_pix_fmts: frozenset[str] | None = None`. When set, a stream
    counts as copyable only if its codec is in `copy_mask` **and** its probed
    `pix_fmt` is in `copy_pix_fmts`; an unknown `pix_fmt` is not copyable. One
    helper in `jobs.py` decides "copyable" for every place that asks today
    (`_decide_stream` and the three note builders that test `copy_mask`).
  - A re-encode caused by the pixel-format condition gets its own note:
    `video stream <i> (<codec>, <pix_fmt>) re-encoded to h264: browsers only play
    8-bit 4:2:0 video`.
- **The `web` profile** (`converter/profiles.py` entry + tests only), in the
  change after the capability.
- The self-write note (`cli._partition_self_writes`) is reworded so it no longer
  claims there is nothing to convert — see Prior decisions.
- `README.md`: `web` in the format list and a short section on what it copies,
  what it re-encodes, and why it differs from `mp4`.
- Foundation and design carriers, **authored in this spec PR**: `docs/vision.md`,
  `docs/constitution.md`, `docs/architecture.md`,
  `docs/design/degradation-ladder.md`, `docs/design/stream-decision.md`.

### Out of scope

- **WebVTT sidecars** — phase 14. Here every subtitle is dropped with a note.
- **Converting `.mp4` sources in place.** `--to web` over `.mp4` sources with no
  separate `OUTPUT` maps each file onto itself, which `source-selection.md`
  makes a counted self-write skip. Replacing a source in place is a different
  safety question; a caller writes to a separate output directory.
- **Hardware encoders** (`h264_v4l2m2m` on the Pi) and **per-call tuning flags** —
  the vision rules out an encoder-tuning surface.
- **Changing `--to mp4`** — it keeps its remux-first behaviour and its copy mask.

## Constraints

- `docs/constitution.md`: no shell; ≤50 lines per function; annotations and
  docstrings; ffmpeg options through `flags("...")`; no `-map 0`; a new target
  ships with a test pinning its argv for a copyable and a non-copyable input; a
  new degradation branch ships with a test asserting its note.
- `docs/architecture.md`: `profiles` stays a leaf; `batch` reads no profile field
  for a conversion decision — it asks `jobs` (hence `first_attempt` returning
  `None`, not `batch` reading `probe_first`).
- The muxer and partial-file handling from phase 12 apply unchanged.
- Verify green and under 60 s; the suite stays ffmpeg-free.

## Prior art

- [Browser-playable target (Phase 13)](../prior-art.md#browser-playable-target-phase-13)
  — jellyfin-web gates direct play on profile and bit depth, not codec family;
  MDN/caniuse evidence for the copy mask (AAC and MP3 everywhere; no AC-3/E-AC-3
  in any browser; HEVC hardware-gated; AV1 without a Safari fallback; Opus/FLAC in
  MP4 thinly evidenced for Safari); every audio track kept; `+faststart`; the one
  Pi 4 data point.

## Measured for this spec — ffmpeg 9.0, 2026-09-30

- Per-stream options work as the engine emits them: a 10-bit HEVC + AC-3 source
  through `-c:v:0 libx264 -crf:v:0 20 -preset:v:0 veryfast -pix_fmt:v:0 yuv420p
  -c:a:0 aac -b:a:0 192k -f mp4` came out `h264, High, yuv420p` + `aac, LC`.
- Relative x264 speed, 10 s of 1080p30, 4 threads (the Pi 4 has 4 cores), on this
  Windows machine:

  | Preset | Time | vs `medium` | Size |
  |---|---|---|---|
  | `medium` | 2.15 s | ×1.0 | 10.4 MB |
  | `fast` | 1.88 s | ×1.1 | 10.4 MB |
  | `veryfast` | 1.14 s | ×1.9 | 9.3 MB |
  | `superfast` | 1.02 s | ×2.1 | 16.9 MB |
  | `ultrafast` | 0.71 s | ×3.0 | 22.4 MB |

  Synthetic content; the ratios, not the absolute times, are what transfers.
  Against the one published Pi 4 figure (libx264 1080p at 8–10 fps, preset
  unstated, likely `medium`), `veryfast` would land near 15–19 fps and
  `ultrafast` near 25–30 fps — **estimates**, to be confirmed on the Pi.

## Human prerequisites

- [ ] Access to the Raspberry Pi 4 *videothek* runs on, with ffmpeg installed, to
      run the preset benchmark at the QA gate (see Verification). Needed for QA,
      not for implementation.

## Prior decisions

| Decision | Rationale | Date |
|---|---|---|
| Copy mask: video `h264` only with `pix_fmt` in {`yuv420p`, `yuvj420p`}; audio `aac`, `mp3` | Sparring on the research's evidence, 2026-09-28 (`docs/prior-art.md`). The pixel format is what separates a playable H.264 from High 10 / 4:2:2, which is the check jellyfin-web makes through `canPlayType` | 2026-09-30 |
| Probe-first: the profile declares `probe_first=True` and `cheap_attempt=None`; `jobs.first_attempt` returns `None`; `batch` then probes and climbs `jobs.retries` | A remux is exactly what lets unplayable codecs through; skipping it costs nothing, because the probe count stays one per file — the same count MP4's `partial_mapping` already spends after a successful remux. `batch` asks the engine rather than reading the flag, per `docs/architecture.md`'s boundary | 2026-09-30 |
| `web` sets `partial_mapping=False` and `explicit_streams=True` | Its first attempt is built stream by stream from the probe, so nothing is unmapped by construction and the selective rung's notes are already accurate; no success-side probe runs | 2026-09-30 |
| An unknown `pix_fmt` is not copyable | The safe side: a stream the probe could not describe is re-encoded, never copied on a guess | 2026-09-30 |
| One `jobs` helper decides "copyable" everywhere `copy_mask` is tested today | Four call sites testing the mask alone would silently disagree with `_decide_stream` once a rule restricts pixel formats | 2026-09-30 |
| Video fallback: `-c:v:{n} libx264 -crf:v:{n} 18 -preset:v:{n} <PRESET> -pix_fmt:v:{n} yuv420p`; audio fallback `-c:a:{n} aac -b:a:{n} 192k` | CRF 18 and AAC 192k match `mp4`, so `web` introduces no quality decision beyond the preset; `-pix_fmt` per stream, the form measured above | 2026-09-30 |
| Last resort: `-map 0:v:0? -map 0:a? -c:v libx264 -crf 18 -preset <PRESET> -pix_fmt yuv420p -c:a aac -b:a 192k`, with notes naming what it gives up | Mirrors `mp4`'s last resort with the same preset | 2026-09-30 |
| Every audio stream is kept | Sparring: only Safari lets a user switch, elsewhere the default track plays; keeping the rest loses nothing a browser notices | 2026-09-30 |
| Subtitles: one `subtitle` rule with an empty copy mask, no fallback, and the drop reason "subtitles are not shown by a browser from inside an MP4" | No browser renders in-band `mov_text` in a plain `<video>` (`docs/prior-art.md`); carrying it would look like a kept subtitle. Phase 14 adds sidecars | 2026-09-30 |
| Cover art: an `attached_pic` rule copying `mjpeg` and `png`, dropping anything else with a note | Without it, an MJPEG cover would match the video rule and be re-encoded into a second H.264 stream. MP4 holds both formats; a browser ignores the picture, so keeping it costs nothing | 2026-09-30 |
| `web` writes `.mp4` with muxer `mp4` and `+faststart`; `resolve_target` finds it by name only, so `.mp4` keeps resolving to `mp4` | `resolve_target` strips a leading dot and looks up the *name*; there is no suffix index to collide with | 2026-09-30 |
| The self-write note becomes "the output path is this file itself; not converted in place" | Today's "nothing to convert" is false for `--to web` over an HEVC `.mp4`, which does need converting. The new wording is true for every target, so the change stays target-agnostic | 2026-09-30 |
| The capability and the `web` profile land as separate issues, the profile last | Makes the vision's criterion checkable: the profile's own diff touches only `profiles.py` and tests | 2026-09-30 |
| The foundation and design carriers are edited in this spec PR | Recorded by `/loopkit:roadmap`; phases 6, 10, 11 and 12 are the precedent | 2026-09-30 |
| OPEN — Which x264 preset does `web` declare: `veryfast`, `ultrafast`, or `medium` like `mp4`? And is the Pi 4 benchmark a precondition for fixing it, or a QA confirmation? | resolved at the spec-acceptance gate | — |

## Tracking

- Milestone: filled at the acceptance gate
- Issues: created from this spec once it is merged (one per implementable step)

Each issue references this spec path in its body.

## Verification

- [ ] Verify passes (`.\.venv\Scripts\python.exe scripts\verify.py`), under 60 s.
- [ ] `tests/test_argv.py` pins `web`'s argv for: a copyable source (h264
      `yuv420p` + aac → all copy); a non-copyable one (hevc + ac3 → libx264 +
      aac); an h264 `yuv420p10le` source (→ re-encode, with the pixel-format
      note); a source with two audio streams (both kept); a source with a text
      and a bitmap subtitle (both dropped with the note); an MJPEG cover (copied).
- [ ] `tests/test_argv.py` / `tests/test_batch.py`: a `web` conversion calls
      `probe_streams` exactly once, before the first `run()`, and not after a
      success; a probe failure is `failed` with the probe error; a source with
      no video or audio is `unsupported`.
- [ ] `tests/test_profiles.py`: `cheap_attempt is None` exactly when
      `probe_first`; `web`'s copy masks, `copy_pix_fmts`, muxer, suffix and
      `partial_mapping=False`.
- [ ] Every existing profile's argv and notes tests pass unchanged; the MP4 remux
      path still spends its one probe after success.
- [ ] `git diff` of the issue that adds `web` touches only
      `converter/profiles.py` and tests.
- [ ] **QA smoke test with real ffmpeg** (paths from `docs/workflow.md`):
  - [ ] h264 8-bit + aac `.mkv` → `.mp4` copied (no re-encode note), `+faststart`
        (moov before mdat), one ffprobe per file;
  - [ ] HEVC 10-bit + AC-3 + a text subtitle + a second audio track → h264
        `yuv420p` + aac + aac, the subtitle dropped with its note, each re-encode
        named;
  - [ ] h264 `yuv420p10le` → re-encoded with the pixel-format note;
  - [ ] each output plays in Chrome, Firefox and Edge from a local HTML page with
        `<video src=…>` (Safari/iOS if a device is at hand);
  - [ ] `--to mp4` on the same sources behaves exactly as before;
  - [ ] **on the Pi 4:** the chosen preset's fps on a 1080p source, recorded in the
        Decision log.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Making `cheap_attempt` optional breaks code that assumes it | A test pins the `probe_first` ↔ `None` pairing; `jobs.first_attempt` is the only reader and returns `None` explicitly |
| The pixel-format check diverges between `_decide_stream` and the note builders | One helper, used by all four sites, with a test per site |
| `yuvj420p` (full range) copied into MP4 plays with wrong levels in some browser | It is H.264 8-bit 4:2:0; the sparring accepted it; the QA playback check covers a `yuvj420p` source |
| The preset is too slow on the Pi | Measured at QA on the Pi itself; the gate decides whether the number is a precondition |

## Decision log

- 2026-09-30: Planned from the roadmap seed of 2026-09-28 (PR #136). Measured the
  per-stream re-encode options and relative preset speeds for this spec. The
  preset is the one genuinely open decision.

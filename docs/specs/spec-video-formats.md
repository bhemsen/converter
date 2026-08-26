# Spec: video-formats (roadmap phase 4)

> Created: 2026-08-26

Add the three remaining video target profiles — `mkv`, `webm`, `mov` — alongside
the `mp4` profile that already exists. This spec carries no lifecycle state —
acceptance is the spec merged on the default branch with a milestone and issues,
and all progress lives in the GitHub issues and milestone. A completed spec is
moved to `docs/specs/archive/`.

**Depends on milestone #2 (target-driven-cli).** Independent of milestones #3 and
#5, which is why phases 3, 4 and 5 can run as parallel orchestrators
(`docs/workflow.md`).

## Outcome

- [ ] `converter --to <fmt>` works for `mkv`, `webm` and `mov`, and `mp4` still
      behaves exactly as it does after phase 2.
- [ ] `--list-formats` prints one line per registry entry, including the three
      new video names.
- [ ] **The diff of every PR in this milestone touches only
      `converter/profiles.py`, `README.md` and files under `tests/`** — the same
      check phase 3 runs, for the same reason.
- [ ] Every new profile has a test pinning the exact argv it builds, for a
      copyable and for a non-copyable input.
- [ ] Every degradation branch a new profile introduces has a test asserting the
      note it emits.
- [ ] An MKV converted to MKV keeps its font attachments, so ASS subtitles still
      render — the one case in this phase where a target can hold everything its
      source had.

## Scope

### In scope

- Three new `Profile` entries in `converter/profiles.py` with their stream rules,
  copy masks, fallback encoders, container options and registry entries.
- Extending the curated source-suffix set with video containers phase 3 did not
  already add (`.mkv`, `.webm`, `.mpg`, `.mpeg`, `.ts`, `.m2ts`, `.vob`, `.ogv`,
  `.3gp`, `.mts`).
- An **attachment** stream rule, which no profile has needed before.
- `README.md`'s format list.
- The tests those profiles require, per the constitution's two gates.

### Out of scope

- Image targets — phase 5, independent of this one.
- Any encoder-tuning surface: no CRF, preset, resolution or bitrate flags
  (`docs/vision.md` non-goal). The defaults below are chosen once and pinned.
- Two-pass encoding, hardware encoders, HDR tone-mapping.
- **Any engine change.** A profile that cannot be expressed as data is escalated
  as `needs:planning`, not absorbed by editing `jobs.py`.
- Closing `mp4`'s standing-note hole — see the decision on that below.

## Constraints

- A target format is data, not code (`docs/constitution.md`,
  `docs/architecture.md`).
- No `-map 0`: it selects data streams and, for containers that cannot hold them,
  turns a remuxable file into a failure. Every cheap attempt selects by type.
- `ffprobe` never runs on the happy path.
- Never report success for a conversion that silently dropped something.
- The test suite keeps passing with no ffmpeg installed.

## Prior art

- [Container/codec capability modelling (Phase 1)](../prior-art.md#containercodec-capability-modelling-phase-1)
  — HandBrake's copy-mask plus encoder-fallback vocabulary, and the ffmpeg-CLI
  entry's AVOID: the mask is curated by hand, because `ffmpeg -codecs` lists what a
  build contains and never what a muxer will accept. Every mask below was measured
  instead of derived.
- [Python wrapper structure around the ffmpeg CLI (Phase 3, Phase 4)](../prior-art.md#python-wrapper-structure-around-the-ffmpeg-cli-phase-3-phase-4)
  — tagged for this phase too. Its AVOID is the live one: WebM's rejection message
  is informative and tempting, and parsing it to pick an encoder is exactly what
  the constitution forbids. The copy mask has to carry that knowledge instead.

## Design

No new design artifact. This phase supplies data for decisions
`docs/design/degradation-ladder.md` and `docs/design/stream-decision.md` already
settled.

## Human prerequisites

- none.

## Prior decisions

### The muxer facts these profiles rest on

Measured against the installed ffmpeg 9.0 during planning, with the exit code
taken from ffmpeg itself rather than from a pipeline. A later reader should
re-verify rather than trust the table.

| Fact | Consequence |
|---|---|
| **WebM enforces its own codec set**: "Only VP8 or VP9 or AV1 video and Vorbis or Opus audio and WebVTT subtitles are supported for WebM." An h264+aac source copy fails outright | `webm` is self-policing: a source it cannot hold *fails* into the ladder rather than being silently mangled. Its masks are exactly that list |
| **MKV accepts everything tried**, including vp9 and opus from a WebM source | The `mkv` masks are broad, and `mkv` is the one target in this phase that rarely re-encodes |
| **MKV holds attachments, and `-map 0:t?` carries them through** (`0,h264 1,subrip 2,ttf` in, same out). Without `-map 0:t?` the attachment is gone at exit 0 | `mkv` maps attachments; the others cannot, and lose them silently — the standing-note decision below |
| **MOV rejects an attachment** (`Could not find tag for codec ttf`) and **rejects a subrip copy**, but accepts `-c:s mov_text` | `mov`'s subtitle rule transcodes in kind to `mov_text`, exactly as `mp4`'s does; no attachment rule |
| **MOV rejects vp9** (`vp9 only supported in MP4`) while **MP4 accepts vp9** | The `mov` video mask is narrower than `mp4`'s — they are not interchangeable, despite sharing a muxer family |
| **WebM rejects a subrip copy** but accepts `-c:s webvtt` | `webm`'s subtitle rule transcodes in kind to `webvtt` |

### Decisions

| Decision | Rationale | Date |
|---|---|---|
| Cheap attempts: `mkv` -> `flags("-map 0:v? -map 0:a? -map 0:s? -map 0:t? -c copy")`; `webm` -> `flags("-map 0:v? -map 0:a? -map 0:s? -c copy")`; `mov` -> `flags("-map 0:v? -map 0:a? -map 0:s? -c copy -c:s mov_text")`. All three `explicit_streams=False` | Each maps exactly what its muxer can hold, measured. `mkv` is the only one that can take `-map 0:t?`, and mapping it is what keeps a font attachment — and therefore ASS subtitle rendering — alive. `mov` needs `-c:s mov_text` in the cheap attempt for the same reason `mp4` does: a subrip copy is rejected | 2026-08-26 |
| Copy masks — video: `mkv` broad (h264, hevc, av1, vp8, vp9, mpeg4, mpeg2video, theora, prores, ffv1, mjpeg); `webm` `{vp8, vp9, av1}`; `mov` `{h264, hevc, prores, mpeg4, mpeg2video, mjpeg}` — **not** `mp4`'s, which includes vp9 | Measured. The `mov`/`mp4` difference is the one a reader is most likely to get wrong by copying the neighbouring entry | 2026-08-26 |
| Copy masks — audio: `mkv` broad (aac, mp3, ac3, eac3, dts, truehd, flac, opus, vorbis, alac, pcm_s16le); `webm` `{opus, vorbis}`; `mov` `{aac, alac, mp3, ac3, eac3}` | Measured against each muxer | 2026-08-26 |
| Subtitle rules: `mkv` accepts text subtitles as a literal copy; `webm` transcodes in kind to `webvtt`; `mov` to `mov_text`. Bitmap subtitles are dropped with a note for `webm` and `mov`, and copied by `mkv` | The accept-but-transcode branch `docs/design/stream-decision.md` already models, three more times | 2026-08-26 |
| `mkv` declares an **attachment** rule that copies; `webm` and `mov` declare none, so an attachment is dropped by the selective rung with the engine's "not supported by TARGET" note | This is the first stream type beyond video/audio/subtitle any profile has ruled on. Nothing in the engine special-cases it — a rule keyed on the probed `codec_type` is all it takes | 2026-08-26 |
| Fallback encoders: `mkv` -> `libx264 -crf:v:{n} 18` / `aac -b:a:{n} 192k`; `mov` -> the same; `webm` -> **`libvpx-vp9`** for video and `libopus -b:a:{n} 128k` for audio | h264/aac for the two permissive containers matches `mp4`'s existing choice, so one reader learns one pair. WebM has no such option: its codec set is the constraint | 2026-08-26 |
| **`mp4` keeps its standing-note hole; the three new profiles carry one where they drop a whole stream type.** `webm` and `mov` say attachments are not carried; `mkv` says nothing, because it drops nothing | Follows the precedent the phase-3 gate set for `wav`: a new profile gets the note, an existing one is not retro-fitted, because that would edit an argv/note assertion phase 1 pinned as its refactor's safety net. `mp4`'s hole is named here so a later phase can close both at once | 2026-08-26 |
| OPEN — WebM's video fallback default | resolved at the spec-acceptance gate; see the note below | — |

### The one open decision, in full

`libvpx-vp9` at its defaults is **slow** — minutes per minute of video on a
desktop CPU, against seconds for `libx264`. `--to webm` over a holiday-video
folder is where this is felt, and `docs/vision.md` rules out an encoder-tuning
surface, so whatever is chosen here is what every user gets, with no flag to
escape it.

The measured facts do not settle this; it is a product judgement about who
`--to webm` is for. The gate picks:

1. **`libvpx-vp9` with speed options** — `-row-mt 1 -cpu-used 4` or similar.
   Still VP9, still widely playable, several times faster than the default, at
   some quality cost that nobody without a reference file would notice. The
   options are pinned by the argv test, so the choice stays visible.
2. **`libvpx-vp9` at its defaults.** Best quality per byte, and honest to the
   format. A batch conversion may take hours, and the progress bar is the only
   thing telling the user it is still alive.
3. **`libvpx` (VP8)** — much faster and universally supported, at a real size and
   quality penalty against VP9. The conservative choice if `--to webm` is mostly
   about compatibility rather than archiving.

## Tracking

- Milestone: video-formats (created at the spec-acceptance gate)
- Issues: created from this spec once it is merged (one per implementable step)

## Verification

Machine checks:

- [ ] Verify passes on the merge commit.
- [ ] For every PR in this milestone, `git diff main...<pr-head> --name-only`
      lists only `converter/profiles.py`, `README.md` and paths under `tests/`.
- [ ] Per new profile, a test pinning the full argv for a copyable input and for
      a non-copyable one — six tests, three profiles, both cases each.
- [ ] A test that `mkv`'s cheap attempt maps `0:t?` and the others do not.
- [ ] A test that `mov`'s video mask excludes `vp9` while `mp4`'s includes it —
      the one difference a copy-paste between the two entries would erase.
- [ ] A test per degradation branch: video re-encoded, audio re-encoded, a bitmap
      subtitle dropped by `webm` and by `mov`, an attachment dropped by `webm` and
      by `mov`, a text subtitle transcoded to `webvtt` and to `mov_text`.
- [ ] A test that `mp4`'s argv and notes are byte-for-byte what they were before
      this phase.
- [ ] The registry structural test from phase 3 still passes with the new entries.

Human milestone-QA gate. `$FF` is the absolute ffmpeg path from *This machine*;
PowerShell, one command per line:

```text
New-Item -ItemType Directory -Force in
& $FF -y -f lavfi -i testsrc=size=320x240:rate=10:duration=3 -f lavfi -i sine=duration=3 -c:v libx264 -c:a aac in/h264.mkv
& $FF -y -f lavfi -i testsrc=size=320x240:rate=10:duration=3 -f lavfi -i sine=duration=3 -c:v libvpx-vp9 -b:v 200k -c:a libopus in/vp9.webm
& $FF -y -f lavfi -i testsrc=size=320x240:rate=10:duration=3 -c:v ffv1 in/lossless.mkv
& $FF -y -i in/h264.mkv -attach C:\Windows\Fonts\arial.ttf -metadata:s:t mimetype=application/x-truetype-font -c copy in/attached.mkv
```

- [ ] Each of the four targets converts a real source and the result plays.
- [ ] `--to mkv in out` over `attached.mkv` keeps the font attachment — check with
      `ffprobe`, not by eye. This is the phase's headline behaviour.
- [ ] `--to webm in out` over `h264.mkv` re-encodes video and audio, names both,
      and produces a file that plays in a browser.
- [ ] `--to webm in out` over `vp9.webm` stream-copies: near-instant, and the
      video stream is packet-identical
      (`& $FF -i out/vp9.webm -map 0:v -c copy -f md5 -` matches the source).
- [ ] `--to mov in out` over `vp9.webm` re-encodes the video rather than failing —
      the measured `mov` rejection of vp9, reached through the ladder.
- [ ] `--to mp4 in out` behaves exactly as it did before this phase.
- [ ] A second run over any converted tree reports `0 converted`, exit 0.
- [ ] Time the `--to webm` run over a 30-second source and record it, so the
      gate's fallback-encoder decision can be judged against a real number.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| `mov`'s mask is written by copying `mp4`'s, silently admitting vp9 | Its own Verification item, because this is the likeliest mistake in the phase |
| `--to webm` is so slow that the tool looks hung | The gate decides the fallback with a measured time in front of it, and the QA gate records one |
| The attachment rule turns out to need an engine change | Measured first: a rule keyed on `codec_type` is all the engine already does. If it is not, escalate as `needs:planning` rather than editing `jobs.py` |
| A source with a data or timecode stream fails a remux | No cheap attempt uses `-map 0`; every one selects by type, so an unmapped type cannot fail the copy |
| `mkv`'s broad masks let a stream through that the muxer then refuses | The `last_resort` re-encode is the safety net, and the ladder reaches it |

## Decision log

- 2026-08-26: The muxer facts were measured during planning rather than left for
  the review to find, after phase 3 needed five rounds largely because its first
  draft guessed at them. The table above is the result; the review's job is to
  falsify it, not to derive it.
- 2026-08-26: `mp4`'s standing-note hole is left open deliberately, following the
  phase-3 gate's `wav` precedent — retro-fitting a note to an existing profile
  edits an assertion phase 1 pinned as its safety net, and the two holes are
  better closed together in one later phase than piecemeal.

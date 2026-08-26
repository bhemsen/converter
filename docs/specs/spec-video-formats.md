# Spec: video-formats (roadmap phase 4)

> Created: 2026-08-26

Add the three remaining video target profiles — `mkv`, `webm`, `mov` — alongside
the `mp4` profile that already exists. This spec carries no lifecycle state —
acceptance is the spec merged on the default branch with a milestone and issues,
and all progress lives in the GitHub issues and milestone. A completed spec is
moved to `docs/specs/archive/`.

**Depends on milestone #2 (target-driven-cli).** Independent of phase 3's and
phase 5's milestones, which is why the three coverage phases can run as parallel
orchestrators (`docs/workflow.md`).

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
      render — the one case in this phase where a target holds everything a
      typical source had.
- [ ] Nothing a cheap attempt cannot carry is lost without a word: each new
      profile's standing note enumerates the stream types it does not map.

## Scope

### In scope

- Three new `Profile` entries in `converter/profiles.py` with their stream rules,
  copy masks, fallback encoders, container options, `cheap_attempt`,
  `explicit_streams`, `last_resort` and standing notes, plus registry entries.
- Extending the curated source-suffix set with the containers no earlier phase
  added: `.mpg`, `.mpeg`, `.ts`, `.m2ts`, `.mts`, `.vob`, `.ogv`, `.3gp`.
  (`.mkv` comes from phase 2; `.mp4`, `.mov`, `.avi`, `.webm`, `.m4v`, `.wmv`
  and `.flv` come from phase 3.)
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
- No `-map 0`: it selects data streams, and for a container that cannot hold them
  it turns a remuxable file into a failure. Measured: `-map 0 -c copy` of a
  timecode-bearing MOV into MKV exits 127 with "Only audio, video, and subtitles
  are supported for Matroska". Every cheap attempt selects by type.
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
  — tagged for this phase too. Its AVOID: never parse values out of ffmpeg's stderr
  to drive a second pass. Relevant here because WebM's rejection message names the
  codecs it wants, which is exactly the tempting string to scrape; the copy mask
  has to carry that knowledge instead.

## Design

No new design artifact. This phase supplies data for decisions
`docs/design/degradation-ladder.md` and `docs/design/stream-decision.md` already
settled.

## Human prerequisites

- none.

## Prior decisions

### The muxer facts these profiles rest on

Measured against ffmpeg 9.0 during planning and re-measured by the
spec-acceptance review, with exit codes taken from ffmpeg itself rather than from
the end of a pipeline. A later reader should re-verify rather than trust the
table.

| Fact | Consequence |
|---|---|
| **WebM enforces its own codec set**: "Only VP8 or VP9 or AV1 video and Vorbis or Opus audio and WebVTT subtitles are supported for WebM." An h264+aac copy fails outright | `webm` is self-policing for codecs: a source it cannot hold *fails* into the ladder rather than being silently mangled |
| **MKV accepts every codec tried** — all 11 video and all 11 audio codecs in the masks below, vp9 and opus from a WebM source included | `mkv` is the one target in this phase that rarely re-encodes |
| **MKV holds attachments and `-map 0:t?` carries them** (`0,h264 1,subrip 2,ttf` in, same out). Without `-map 0:t?` the attachment is gone at exit 0; with it, a source that has none still exits 0 | `mkv` maps attachments unconditionally |
| **MOV *rejects* a mapped attachment** ("Could not find tag for codec ttf") | Mapping `0:t?` makes MOV **fail loudly** on an attachment-bearing source, so the ladder runs and names the loss. This is the phase-3 "turn a quiet loss into a failure the ladder can name" pattern, and it works here |
| **WebM does *not* reject a mapped attachment — it silently discards it** at exit 0 | The same trick does not work for `webm`; only a standing note can cover it |
| **Neither MKV nor a `v/a/s/t` map carries data or timecode streams**: a timecode-bearing MOV through `-map 0:v? -map 0:a? -map 0:s? -map 0:t? -c copy` exits 0 with the data stream gone | Every profile in this phase loses data/timecode silently, `mkv` included. The standing notes have to say so |
| **MOV rejects a subrip copy but accepts `-c:s mov_text`**; **WebM rejects a subrip copy but accepts `-c:s webvtt`** (and `ass` converts into both) | Both need the in-kind transcode in their cheap attempt, as `mp4` already does |
| **MOV rejects `vp9`, `av1` and `vp8`** ("vp9 only supported in MP4", "av1 only supported in MP4 and AVIF", "VP8 muxing is currently not supported") while **MP4 accepts vp9 and av1** | The `mov` video mask is narrower than `mp4`'s in *two* codecs, not one. Striking only vp9 from a copied `MP4_VIDEO_CODECS` still leaves a bug |
| **MOV also copies `ffv1`, `theora`, `dts` and `pcm_s16le`** (tags `dtsc`, `sowt`) | Those belong in the `mov` masks; leaving them out would force a lossless stream through `libx264`/`aac` on the failure path for no reason |
| **ffprobe reports an attachment's `codec_name` from its MIME type**: `application/x-truetype-font` -> `ttf`, `application/vnd.ms-opentype` -> `otf`, but **`font/ttf` and `font/otf` -> `unknown`** | An attachment copy mask enumerating font codec names is wrong by construction. `mkv`'s attachment rule accepts unconditionally |
| `-movflags +faststart` is accepted by MOV and harmlessly ignored by MKV and WebM | `mov` takes it, matching `mp4`; the other two declare no container options |

### Decisions

| Decision | Rationale | Date |
|---|---|---|
| Cheap attempts, all with `explicit_streams=False`: `mkv` -> `flags("-map 0:v? -map 0:a? -map 0:s? -map 0:t? -c copy")`; `mov` -> `flags("-map 0:v? -map 0:a? -map 0:s? -map 0:t? -c copy -c:s mov_text")`; `webm` -> `flags("-map 0:v? -map 0:a? -map 0:s? -c copy -c:s webvtt")` | Each maps what its muxer can hold, measured. `mov` maps `0:t?` **deliberately**: it makes an attachment-bearing source fail into the ladder, which then names the loss per stream — better than a blanket note. `webm` does not, because it silently discards instead of failing, so mapping would buy nothing. Both `mov` and `webm` carry their in-kind subtitle transcode in the cheap attempt, so a subtitled source converts on the first attempt instead of paying a probe and a second run | 2026-08-26 |
| Video masks: `mkv` = `{h264, hevc, av1, vp8, vp9, mpeg4, mpeg2video, theora, prores, ffv1, mjpeg}`; `webm` = `{vp8, vp9, av1}`; `mov` = `{h264, hevc, prores, mpeg4, mpeg2video, mjpeg, ffv1, theora}` — **not** `mp4`'s, which holds `vp9` and `av1` | Measured. The `mov`/`mp4` difference is two codecs, not one, and is the likeliest copy-paste mistake in the phase | 2026-08-26 |
| Audio masks: `mkv` = `{aac, mp3, ac3, eac3, dts, truehd, flac, opus, vorbis, alac, pcm_s16le}`; `webm` = `{opus, vorbis}`; `mov` = `{aac, alac, mp3, ac3, eac3, dts, pcm_s16le}` | Measured against each muxer | 2026-08-26 |
| Subtitle rules: `mkv` accepts text **and bitmap** subtitles as a literal copy, mask `{subrip, ass, ssa, mov_text, webvtt, text, hdmv_pgs_subtitle, dvd_subtitle, dvb_subtitle}`; `webm` transcodes text subtitles in kind to `webvtt`; `mov` to `mov_text`. `webm` and `mov` drop bitmap subtitles with a note | Matroska is the only container here that holds bitmap subtitles; the other two reuse the accept-but-transcode branch `docs/design/stream-decision.md` already models | 2026-08-26 |
| `mkv` declares an **attachment** rule that copies **unconditionally** — an empty-meaning "accept anything" mask, not a list of font codec names | Measured: ffprobe derives the codec name from the MIME type, so `font/ttf` reads as `unknown`. A rule enumerating `{ttf, otf}` would drop a modern font attachment with the note "attachment stream 1 (unknown) dropped: not supported by MKV" — false, and it fails `stream-decision.md`'s requirement that a note name the stream's codec | 2026-08-26 |
| `webm` declares no attachment rule; `mov` declares none either, and relies on its cheap attempt failing instead | `webm` cannot fail on one, so its standing note covers it. `mov` fails, so the ladder's selective rung drops it with a real per-stream note | 2026-08-26 |
| **Standing notes**, on each new profile's `cheap_attempt.notes`: `mkv` — "data and timecode streams are not carried into MKV"; `mov` — the same for MOV; `webm` — "attachments, data and timecode streams are not carried into WebM" | Measured: all three lose data/timecode at exit 0, and `webm` loses attachments the same way. `batch.py` reports only the winning attempt's notes, so a note on the cheap attempt is exactly what a successful conversion prints. This is the phase-3 gate's mechanism, applied to what this phase actually drops | 2026-08-26 |
| Fallback encoders: `mkv` and `mov` -> `libx264 -crf:v:{n} 18` and `aac -b:a:{n} 192k`; `webm` -> `libopus -b:a:{n} 128k` for audio, and the video encoder the gate picks | h264/aac for the two permissive containers matches `mp4`'s existing choice, so a reader learns one pair. WebM's codec set is the constraint, and its video encoder is the phase's one open decision | 2026-08-26 |
| `last_resort`: `mkv` and `mov` -> `flags("-map 0:v:0? -map 0:a? -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -c:a aac -b:a 192k")` with `mp4`'s two notes; `webm` -> the same shape with the gate's video encoder and `libopus -b:a 128k`, noting subtitles and extra video streams are dropped | Every profile needs one, or a ladder that reaches the end lands as `failed` — and the Risks table's safety-net claim would be fiction. Reusing `mp4`'s shape keeps the three readable side by side | 2026-08-26 |
| Container options: `mov` -> `FASTSTART`; `mkv` and `webm` -> none | Measured: `+faststart` is accepted by MOV and ignored by the other two, so declaring it there matches `mp4` and declaring it elsewhere would be noise | 2026-08-26 |
| **`mp4` keeps its standing-note hole**; the three new profiles get one | Follows the precedent the phase-3 gate set for `wav`: a new profile gets the note, an existing one is not retro-fitted, because that edits an assertion phase 1 pinned as its refactor's safety net. `mp4`'s hole is named here so a later phase can close both at once | 2026-08-26 |
| OPEN — WebM's video fallback encoder and its quality parameter | resolved at the spec-acceptance gate; see the note below | — |

### The one open decision, in full

`--to webm` has no flag to escape its encoder (`docs/vision.md` rules out an
encoder-tuning surface), so whatever is chosen here is what every user gets.
Measured during review: 30 s of `testsrc2` at 1280x720@30 on this machine.

| Option | Wall time | Output size |
|---|---|---|
| `libx264 -crf 18` — the `mkv`/`mov` fallback, for scale | 3.6 s | 17.2 MB |
| 1: `libvpx-vp9 -crf 32 -b:v 0 -row-mt 1 -cpu-used 4` | 21.7 s | 12.8 MB |
| 2: `libvpx-vp9 -crf 32 -b:v 0` at default speed | 104.3 s | 12.3 MB |
| 3: `libvpx` (VP8) at defaults | 11.3 s | 1.2 MB |

1. **VP9 with speed options.** Six times slower than h264 and about a fifth
   smaller. The quality cost against option 2 is invisible without a reference
   file, and the options are pinned by the argv test so the choice stays visible.
2. **VP9 at default speed.** Best quality per byte, ~3.5x realtime — a folder of
   holiday videos becomes an overnight job, with only the progress bar to say it
   is alive.
3. **VP8.** Fast and universally playable, but note what the measurement actually
   shows: `libvpx` at defaults uses a fixed low target bitrate rather than a
   quality target, so the 1.2 MB is a different rate-control regime, not codec
   efficiency. It would need its own quality parameter to be comparable at all.

Unlike the audio fallbacks, VP9 needs `-crf` *and* `-b:v 0` to mean
"quality-targeted"; `-crf` alone leaves VP9 in constrained-quality mode. (For
x264, measured, `-crf 18` and `-crf 18 -b:v 0` are byte-identical, so `mp4`'s
existing entry needs no companion.)

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
- [ ] A test that `mkv`'s and `mov`'s cheap attempts map `0:t?` and `webm`'s does
      not.
- [ ] A test that `mov`'s video mask excludes **both** `vp9` and `av1` while
      `mp4`'s includes both — the two-codec difference a copy-paste erases.
- [ ] A test that `mkv`'s attachment rule accepts a stream whose `codec_name` is
      `unknown`, since that is what ffprobe reports for a `font/ttf` attachment.
- [ ] A test per degradation branch: video re-encoded, audio re-encoded, a bitmap
      subtitle dropped by `webm` and by `mov`, an attachment dropped by `mov` via
      the ladder, a text subtitle transcoded to `webvtt` and to `mov_text`.
- [ ] A test per standing note, asserting its exact wording on the profile's
      `cheap_attempt.notes` — the mechanism that covers what the ladder never
      sees.
- [ ] A test that each new profile declares a `last_resort`.
- [ ] A test that `mp4`'s argv and notes are byte-for-byte what they were before
      this phase.

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
- [ ] `--to mov in out` over `attached.mkv` *fails the cheap attempt*, reaches the
      ladder, and names the dropped attachment. The one place a drop is reported
      per stream rather than by a standing note.
- [ ] `--to webm in out` over `attached.mkv` succeeds and prints WebM's standing
      note, since nothing failed and there was no ladder to name it.
- [ ] `--to webm in out` over `h264.mkv` re-encodes video and audio, names both,
      and produces a file that plays in a browser.
- [ ] `--to webm in out` over `vp9.webm` stream-copies: near-instant, and the
      video stream is packet-identical
      (`& $FF -i out/vp9.webm -map 0:v -c copy -f md5 -` matches the source).
- [ ] `--to mov in out` over `vp9.webm` re-encodes the video rather than failing.
- [ ] `--to mp4 in out` behaves exactly as it did before this phase.
- [ ] A second run over any converted tree reports `0 converted`, exit 0.
- [ ] Time the `--to webm` run over a 30-second source and record it, so the
      gate's fallback choice can be checked against a real number on real content.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| `mov`'s mask is written by copying `mp4`'s, admitting vp9 or av1 | Its own Verification item naming both codecs, because this is the likeliest mistake in the phase |
| `--to webm` is so slow that the tool looks hung | The gate decides with measured wall times in front of it, and the QA gate records one on real content |
| Data or timecode streams are lost without a word | Every new profile's standing note says so, with a test pinning the wording |
| The attachment rule turns out to need an engine change | Measured through the real engine during review: a rule keyed on `codec_type == "attachment"` works, and `-c:t:0 copy` is valid ffmpeg. If that changes, escalate as `needs:planning` |
| A source with a data stream fails a remux | No cheap attempt uses `-map 0`; every one selects by type, so an unmapped type cannot fail the copy |
| `mkv`'s broad masks let a stream through that the muxer then refuses | The declared `last_resort` is the safety net, and the ladder reaches it |

## Decision log

- 2026-08-26: The muxer facts were measured during planning rather than left for
  the review to find, after phase 3 needed five rounds largely because its first
  draft guessed. The review's job was to falsify the table; most rows survived,
  and the ones that did not are folded in above.
- 2026-08-26: Review measured that `mov` *rejects* a mapped attachment while
  `webm` silently discards one. So `mov` maps `0:t?` to force the failure that
  lets the ladder name the loss, and `webm` cannot — the asymmetry decides which
  target gets a real note and which gets a standing one.
- 2026-08-26: Review measured that no profile in this phase carries data or
  timecode streams, `mkv` included, so the original "mkv drops nothing" claim was
  wrong and all three profiles need a standing note.
- 2026-08-26: `mp4`'s standing-note hole is left open deliberately, following the
  phase-3 gate's `wav` precedent — the two holes are better closed together in
  one later phase than piecemeal.

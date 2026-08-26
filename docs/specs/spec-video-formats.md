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
- `ffprobe` never runs on the happy path of a cheap attempt whose mapping is
  *exhaustive*. A profile whose cheap attempt is partial by construction
  declares `partial_mapping=True` and is probed once on its success, so what
  that mapping could not carry is named (`docs/constitution.md`, narrowed by
  issue #18). Every cheap attempt in the table below selects by type or by
  index, so every profile in this phase is partial and must declare it --
  together with exactly a rule for each stream type it maps and no rule for
  any other, per the equality in `docs/design/degradation-ladder.md` (issue
  #40, narrowing #39). `mkv` and `mov` both map `-map 0:t?`, and the two
  resolve oppositely: `mkv`'s muxer holds an attachment, so it carries fonts
  on the success side and the profile owes an `attachment` rule, or the fonts
  it keeps get reported as dropped. `mov`'s muxer rejects any mapped
  attachment outright, so mapping it there only ever forces the cheap attempt
  to fail into the ladder when the source has one -- the type never reaches
  the success side, so `mov` needs no `attachment` rule to keep the
  verification honest, and the equality exempts it on both sides rather than
  admitting a rule-less mapped type as a special case.
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
| **WebM does *not* reject a mapped attachment — it silently discards it** at exit 0 | The same trick does not work for `webm`; a standing note covers it, alongside the same per-stream success-side note MP4's own attachment gap already relies on (issue #29) |
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
| Subtitle rules: `mkv` accepts text **and bitmap** subtitles as a literal copy, mask `{subrip, ass, ssa, webvtt, text, hdmv_pgs_subtitle, dvd_subtitle, dvb_subtitle}` — **not** `mov_text`, which Matroska rejects as a copy and which `mkv` instead re-encodes to `subrip` (`fallback_options=flags("-c:s:{n} srt")`, `fallback_name="subrip"`); `webm` transcodes text subtitles in kind to `webvtt`; `mov` to `mov_text`. `webm` and `mov` drop bitmap subtitles with a note | Matroska is the only container here that holds bitmap subtitles; the other two reuse the accept-but-transcode branch `docs/design/stream-decision.md` already models. `mov_text`'s exclusion from `mkv`'s mask is measured, not a typo: `-c:s copy` of a mov_text stream into Matroska exits 127 ("Subtitle codec mov_text ... is not supported"), while `-c:s srt` on the same input exits 0 | 2026-08-26 |
| `mkv` declares an **attachment** rule that copies **unconditionally** — an empty-meaning "accept anything" mask, not a list of font codec names | Measured: ffprobe derives the codec name from the MIME type, so `font/ttf` reads as `unknown`. A rule enumerating `{ttf, otf}` would drop a modern font attachment with the note "attachment stream 1 (unknown) dropped: not supported by MKV" — false, and it fails `stream-decision.md`'s requirement that a note name the stream's codec | 2026-08-26 |
| `webm` declares no attachment rule; `mov` declares none either, and relies on its cheap attempt failing instead | `webm` cannot fail on one, so its standing note covers it -- and, since it declares no `attachment` rule, so does the success-side verification's own per-stream note (issue #29). `mov` fails instead, so the ladder's selective rung drops it with a real per-stream note | 2026-08-26 |
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

- Milestone: [video-formats](https://github.com/bhemsen/converter/milestone/4) (#4)
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
- 2026-08-26 (issue #39): The cheap-attempt invariant in
  `docs/design/degradation-ladder.md` ("a rule for every stream type its cheap
  attempt maps") was too broad: `mov` maps `attachment` via `-map 0:t?`
  deliberately to force a failure into the ladder, never to carry one on the
  success side, so a mov-shaped profile has no `attachment` rule and would
  fail that reading. Resolved by narrowing the invariant to the types the
  cheap attempt can *successfully carry* -- a type mapped only to force a
  failure never reaches the success-side check -- rather than by adding a
  drop-only `attachment` `StreamRule` to `mov`. Both docs now name `mov`
  alongside `mkv` as the pair that distinguishes the two readings, and
  `tests/test_profiles.py` proves the narrowed form with a mov-shaped profile
  in its test corpus.
- 2026-08-26 (issue #40): #39 narrowed only one direction of the invariant --
  a rule for a type the cheap attempt does not map (modulo the force-failure
  exemption) was still admitted, and `degradation-ladder.md` even endorsed it
  ("a limit belongs to a type ... or does not map at all"). That is issue
  #18's bug class reintroduced: a hypothetical audio-only cheap attempt
  carrying a `video` rule for cover art -- the motivating case this issue was
  filed against -- would pass both existing checks and silently drop the
  artwork, because `_structural_drop` (`converter/jobs.py`) finds the rule,
  sees no stream-limit trip, and treats the stream as accepted. No shipped or
  planned profile is actually shaped that way -- phase 3's
  `spec-audio-formats.md` resolved the opposite, that no audio profile
  declares a video rule at all -- but the contract had to forbid the shape
  outright rather than rely on every future profile avoiding it by
  discipline. Resolved by stating the invariant as the equality its
  justification already relied on, `set(profile.rules) ==
  set(mapped_types(profile))` modulo #39's exemption, and striking the "or
  does not map at all" clause -- a `stream_limit` on a type absent from the
  mapping cannot arise once the equality holds, so nothing was left for that
  clause to permit. `tests/test_profiles.py` adds the mirrored assertion
  (`set(profile.rules) <= set(mapped_types(profile))`) and an index-count
  check for `stream_limit`; `mapped_types` itself now asserts every `-map`
  selector it sees is one it recognises, so a form it cannot read
  (`-map 0:0`, `-map -0:s`) fails loudly instead of being skipped and passing
  every check vacuously.

  Review surfaced a second, real collision while checking this: phase 3's
  `mp3` and `flac` map audio *blindly* (`-map 0:a?`) yet declare
  `stream_limit=1`, because their muxers reject a second audio stream outright
  (measured) -- exactly the shape the plain "no `stream_limit` on a blindly
  mapped type" rule would reject once those profiles are implemented. Not a
  gap the equality introduced, but one this PR's own tightening would have
  shipped as newly-false documentation against an already-merged spec.
  Resolved the same way as the force-failure exemption: `degradation-ladder.md` now
  states a `stream_limit` on a blindly-mapped type is legitimate exactly when
  the container's own muxer enforces that limit and rejects a surplus
  outright, and `tests/test_profiles.py` adds an `mp3`-shaped profile
  (`MP3_SHAPED`/`MUXER_ENFORCED_LIMIT_TYPES`) proving it the way `MOV_SHAPED`
  proves the force-failure exemption.

  No shipped profile was affected -- MP4 and WAV both already satisfy the
  equality -- so this closes a hole in the contract before phases 3-5 write
  target profiles against it, not a live bug.

- 2026-08-26 (issue #26): Widened `SOURCE_SUFFIXES` with the video containers
  this phase's Scope names -- `.mpg`, `.mpeg`, `.ts`, `.m2ts`, `.mts`, `.vob`,
  `.ogv`, `.3gp` -- ahead of the `mkv`/`webm`/`mov` profiles this milestone
  still adds, the same ahead-of-the-profile shape phase 3 used for the
  remaining audio target suffixes. `.mkv` (phase 2) and `.mp4`/`.mov`/`.avi`/
  `.webm`/`.m4v`/`.wmv`/`.flv` (phase 3) were already present and are not
  repeated. No profile, engine, or CLI change -- data only, per this issue's
  scope; the three new `Profile` entries remain a separate issue in this
  milestone.

- 2026-08-26 (issue #27): Added the `mkv` `Profile`. Re-measuring the muxer
  facts against ffmpeg 9.0 while implementing found the Prior decisions'
  subtitle-mask row wrong on one codec: it listed `mov_text` as literal-copy
  material alongside the other eight text/bitmap codecs, but `-c:s copy` of a
  mov_text stream into Matroska exits 127 ("Subtitle codec mov_text ... is not
  supported"), while `-c:s srt` on the same input exits 0. Corrected in place
  above rather than left to drift from the shipped profile: `mkv`'s subtitle
  mask excludes `mov_text`, and the rule falls back to `-c:s:{n} srt`
  (`fallback_name="subrip"`) for it instead. Confirmed end-to-end against real
  ffmpeg 9.0 through the CLI: a mov_text-subtitled MP4 source fails `mkv`'s
  cheap attempt (the blanket `-c copy` cannot copy the subtitle), reaches the
  selective rung, and converts with the note "subtitle stream 2 (mov_text)
  re-encoded to subrip" -- exactly the branch `TestProfileArgvPinning` cannot
  reach, since a copyable and a non-copyable video/audio pinning pair does not
  exercise a subtitle fallback.

  The attachment rule (`_AcceptAnyCodec`, `converter/profiles.py`) is
  implemented as a `frozenset` subclass overriding `__contains__` to always
  return `True`, rather than as an engine change: this spec's own Risks table
  anticipated this ("a rule keyed on `codec_type == "attachment"` works, and
  `-c:t:0 copy` is valid ffmpeg"), and
  both were confirmed against real ffmpeg -- a `font/ttf` attachment
  (`codec_name` reported as `unknown`, measured) round-trips through
  `-map 0:t? -c copy` and through the selective rung's `-c:t:0 copy` alike.
  `jobs.py` needed no change, keeping the PR's diff to `converter/profiles.py`,
  `README.md`, `docs/specs/spec-video-formats.md` and `tests/`.

  `mkv`'s cheap attempt maps `video`, `audio`, `subtitle` and `attachment`, and
  the profile declares exactly those four rules, so it satisfies
  `set(profile.rules) == set(mapped_types(profile))` directly -- unlike `mov`,
  it needs neither the `FORCED_FAILURE_TYPES` nor the
  `MUXER_ENFORCED_LIMIT_TYPES` exemption from `docs/design/degradation-ladder.md`
  (issues #39/#40); `tests/test_profiles.py` adds `MKV` to `SHIPPED` with an
  empty entry in both exemption dicts, so the existing parametrized invariant
  tests check it machine-side rather than by review.

- 2026-08-26 (issue #28): Added the `mov` `Profile` -- THE motivating case for
  the `FORCED_FAILURE_TYPES` exemption issue #39 wrote (`docs/design/
  degradation-ladder.md`): its cheap attempt maps `attachment` via `-map 0:t?`
  deliberately, but declares no `attachment` rule, because MOV's muxer rejects
  any mapped attachment outright. Re-measured against real ffmpeg 9.0 while
  implementing, every muxer fact in the Prior decisions table above held
  exactly as written: the video mask excludes vp9, av1 *and* vp8 while
  including ffv1 and theora; the audio mask includes dts and pcm_s16le; a
  mov_text-transcoded subtitle round-trips on the cheap attempt itself; and an
  attachment-bearing source fails the cheap attempt (`-map 0:t?` plus `-c
  copy` on a font stream MOV cannot mux) and lands on the selective rung,
  which drops it with a real per-stream note -- confirmed end-to-end through
  the CLI against a font-attached MKV source, ffprobing the MOV output to
  confirm the attachment stream is gone rather than checking by eye. No spec
  correction was needed this time, unlike issue #27's `mkv` mov_text finding.

  The stand-in fixture `MOV_SHAPED` (`tests/test_profiles.py`) is retired now
  that the real `mov` profile proves the force-failure exemption directly --
  `MOV` joins `SHIPPED` and `INVARIANT_CASES`, with
  `FORCED_FAILURE_TYPES[MOV.name] == frozenset({"attachment"})` and an empty
  `MUXER_ENFORCED_LIMIT_TYPES` entry -- the same retirement shape PR #53 used
  for `MP3_SHAPED` once `MP3` and `FLAC` shipped. `jobs.py` needed no change:
  the missing `attachment` rule already routes through `_structural_drop`'s
  existing "no rule for this type" branch, so the per-stream drop note falls
  out of the engine that shipped for `mp4`'s attachment case rather than
  needing new logic, keeping the PR's diff to `converter/profiles.py`,
  `README.md`, `docs/specs/spec-video-formats.md` and `tests/`.

- 2026-08-26 (issue #29): Added the `webm` `Profile`, the last of this phase's
  three. Re-measured every muxer fact against real ffmpeg 9.0 while
  implementing; all held as written above, including that WebM enforces its
  own codec set at the muxer level and that a mapped attachment is silently
  discarded rather than rejected. `webm`'s cheap attempt maps no attachment at
  all (`-map 0:v? -map 0:a? -map 0:s? -c copy -c:s webvtt`), so unlike `mov`
  it needs neither the `FORCED_FAILURE_TYPES` nor the
  `MUXER_ENFORCED_LIMIT_TYPES` exemption -- the type is simply absent from
  both `mapped_types(WEBM)` and `WEBM.rules`, satisfying the equality
  directly. `tests/test_profiles.py` adds `WEBM` to `SHIPPED` with an empty
  entry in both exemption dicts.

  The video fallback is pinned to the spec's "one open decision" Option 1
  (`libvpx-vp9 -crf:v:{n} 32 -b:v:{n} 0 -row-mt 1 -cpu-used 4`), including
  `-b:v:{n} 0` alongside `-crf`: the Prior decisions table above states VP9
  needs both together to mean quality-targeted mode, `-crf` alone leaves it in
  constrained-quality mode (measured). Issue #29's own acceptance checklist
  abbreviated this line without `-b:v:{n} 0`; the spec is what owns the exact
  pinned argv per this issue's brief, so the fuller, measured form here is what
  shipped, confirmed against real ffmpeg 9.0 through the CLI (a copyable
  vp9/opus source stream-copied, packet-identical by `-f md5`, and a
  non-copyable h264/aac source re-encoded to vp9/opus and played back
  correctly).

  One clarification to the Prior decisions table's framing, found while
  measuring the attachment case end-to-end: "webm declares no attachment
  rule ... its standing note covers it" reads as if the standing note were
  the *only* mechanism naming the loss. In fact, because `webm`'s cheap
  attempt is `partial_mapping=True` and declares no `attachment` rule, a
  successful cheap attempt over an attachment-bearing source also gets a real
  per-stream note from `jobs.verify_success`'s success-side verification --
  the exact mechanism `mp4` already relies on for its own attachment gap
  (`test_mp4_names_the_attachment_its_selectors_cannot_reach`,
  `tests/test_argv.py`). Confirmed against real ffmpeg 9.0: converting a
  font-attached, h264/aac MKV to WebM through the CLI reported both
  `"attachments, data and timecode streams are not carried into WebM"` (the
  standing note) and `"attachment stream 2 (ttf) dropped: not supported by
  WebM"` (the per-stream note) on the same run. This is not new behaviour
  introduced by this profile -- `mkv` and `mov` get the identical doubling for
  a data/timecode stream, since neither declares a `data` rule either -- so no
  argv, mask or mechanism needed correcting, only this note to keep the prose
  from reading as more exclusive than the shipped mechanism actually is.

  A source WebM cannot hold at all (no video, audio or subtitle stream --
  only an attachment or a data stream) proved impractical to construct with
  ffmpeg's own muxers during the real-ffmpeg smoke test: an attachment-only
  Matroska output ("Output file is empty, nothing was encoded") and a
  data-only one ("Output file does not contain any stream") both failed at
  ffmpeg's own tool boundary, before reaching this project's code at all.
  `describe_unsupported`'s handling of that shape is unchanged, pre-existing
  engine logic already proven generically (`TestUnsupportedDiscriminator`,
  `tests/test_argv.py`) and now pinned for `webm` specifically too
  (`test_a_source_webm_cannot_hold_at_all_is_unsupported`), using the same
  attachment-only stream shape the real fixture would have produced had
  ffmpeg been willing to write one.

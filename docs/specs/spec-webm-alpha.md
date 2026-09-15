# Spec: webm-alpha (roadmap phase 9)

> Created: 2026-09-15

Stop `--to webm` failing outright on a source that carries an alpha channel, and
carry the channel through instead of destroying it. This spec carries no
lifecycle state — acceptance is the spec merged on the default branch with a
milestone and issues, and all progress lives in the GitHub issues and milestone.
A completed spec is moved to `docs/specs/archive/`.

**This phase is not on the seeded roadmap.** It comes from issue #114, which
v3.0.0's pre-release smoke test filed and which that release shipped as a
documented *Known limitation* rather than silently. Its roadmap row is added in
this PR; its Spec and Milestone links are filled at the acceptance gate like
every other phase's. The same route phase 8 took from issue #101.

## The defect

An RGBA source into `webm` fails on **every rung** of the ladder — in ladder
order `remux` -> `selective` -> `re-encode`. Measured, ffmpeg 9.0, on a 200×200
RGBA PNG:

```
[remux]     [webm] Only VP8 or VP9 or AV1 video and Vorbis or Opus audio
            and WebVTT subtitles are supported for WebM.
[selective] [libvpx-vp9] Pixel format 'gbrap' is not widely supported.
            Use -strict experimental to use it anyway, or use 'yuva420p'
            pixel format instead.                        -> exit -22
[re-encode] (same)                                       -> exit -22
```

The file is reported `FAILED` and the batch exits non-zero. Nothing is corrupted
and the rest of the batch still converts — the failure is loud, which is why
v3.0.0 shipped over it — but a reasonable conversion simply does not happen.

`png` is not in `WEBM_VIDEO_CODECS` (`vp8`, `vp9`, `av1`), so the stream must be
re-encoded, and `webm`'s video fallback names no `-pix_fmt`, so ffmpeg selects
`gbrap` from the RGBA source and libvpx refuses it without `-strict experimental`.

## What measurement established — including one trap

**WebM alpha is achievable, and cheaply.** `-pix_fmt yuva420p` is all libvpx-vp9
needs; the alpha rides a Matroska `BlockAdditional` block, exactly as WebM
specifies.

| Attempt on the RGBA source (α = 127) | Result |
|---|---|
| As shipped, no `-pix_fmt` | exit **-22**, no output — the defect |
| **`-pix_fmt yuva420p`** | exit 0, `alpha_mode=1`, `BlockAdditional` present, **alpha round-trips at 127** |
| `-pix_fmt gbrap` + `-strict experimental` | exit 0, **alpha round-trips at 127** |
| `-pix_fmt yuva420p10le` | refused **without** `-strict experimental`, exit -22 — the same "not widely supported" message; **accepted with it** |
| VP8 (`-c:v libvpx`) + `yuva420p` | fails on the default `auto_alt_ref`; with `-auto-alt-ref 0`, exit 0 and `alpha_mode=1` |
| AV1 (`libaom-av1`) + `yuva420p` | alpha dropped — `libaom-av1` declares no `yuva*` pixel format |

`-strict experimental` must be an **output** option; given as an input option the
encoder still exits -22.

**The defect is wider than "an alpha source" — but not as wide as roster
membership.** What decides it is the format ffmpeg's negotiation lands the
*encoder* on, which is not the same question as whether the source's reported
`pix_fmt` is in `ALPHA_FREE_PIX_FMTS`. Measured against `webm`'s exact video
fallback argv, and end to end through the CLI:

| Source | Reported `pix_fmt` | Encoder negotiates | `--to webm` today |
|---|---|---|---|
| RGBA PNG | `rgba` | `gbrap` | **fails**, exit -22 |
| **Any `.gif`, opaque included** | `bgra` — ffmpeg's gif decoder reports it unconditionally (phase 8 measured the same) | `gbrap` | **fails**, exit -22 |
| 16-bit RGBA PNG | `rgba64be` | `gbrap12le` | **fails**, exit -22 |
| Grey+alpha PNG | `ya8` | `gbrap` | **fails**, exit -22 |
| **Paletted PNG, transparent or not** | `pal8` | **`gbrp`** — libvpx accepts it unconditionally | **succeeds**, exit 0 |

`.gif` is in `SOURCE_SUFFIXES`, so `--to webm` currently fails for **every GIF
source in a tree**, transparent or not. v3.0.0's *Known limitations* entry
therefore understates the defect and is corrected by this phase.

**`pal8` is the interesting one, and it is not a failure at all.** It converts
today — and a *transparent* paletted PNG loses its transparency while being
reported as a plain success. Measured: source corner pixel `A=0`, output `A=255`
decoded with an explicit libvpx decoder, with only a `re-encoded to vp9` note
that says nothing about the channel. That is a live breach of the constitution's
"never report success for a conversion that silently dropped something",
reachable from an ordinary paletted PNG, and nothing in the tree covers it —
`webm` declares no `alpha_unsupported`, so phase 8's note cannot reach it.

So `pal8` belongs in this phase's scope for a **better** reason than the first
draft's: the override turns a silent loss into a correct conversion. But it also
carries a cost the gate must weigh, because `pix_fmt` alone cannot tell a
transparent paletted image from an opaque one — the ambiguity phase 8 already
recorded for `pal8`. See decision 3, resolved at the gate.

> **The trap, recorded because this spec's first draft fell into it and the
> acceptance review caught it.** `ffprobe` and `ffmpeg` default to the **native**
> `vp9`/`vp8` decoders, which have no alpha support: they report `pix_fmt=yuv420p`
> for a file that demonstrably carries alpha. Reading that as "the encoder dropped
> the channel" inverts the whole conclusion. **Every alpha check in this phase —
> test fixture, QA line, or ad-hoc measurement — must decode with an explicit
> `-c:v libvpx-vp9` / `-c:v libvpx`, or assert on `alpha_mode` /
> `BlockAdditional` instead of on the output's `pix_fmt`.** This is precisely the
> class `docs/prior-art.md`'s FFmpeg entry warns about: the CLI reports what a
> component *does*, never what the format permits.

Two consequences follow, and they are the shape of the whole phase:

- **The fix preserves, it does not destroy.** Issue #114's option 3
  (declare `webm` alpha-incapable and name the loss) is wrong on the facts, and
  its option 1 (force `yuva420p` unconditionally) is wrong on the 10-bit case
  below. Its option 2 — choose the pixel format from the probed source — is
  correct, and no transparency note is needed for the case it fixes.
- **The override must be conditional.** Measured: a `yuv420p10le` source survives
  as 10-bit through today's fallback, and an unconditional `-pix_fmt yuv420p`
  *or* `yuva420p` would truncate it to 8-bit. An opaque `rgb48be` source likewise
  reaches `gbrp12le` today with no flag at all. Forcing one pixel format on every
  conversion would trade a loud failure for a silent truncation.

## Outcome

- [ ] An RGBA source into `webm` **converts at exit 0 with its alpha channel
      intact** — verified by decoding with an explicit libvpx decoder, not by
      reading the output's reported `pix_fmt`.
- [ ] A source whose `pix_fmt` **is a member of `ALPHA_FREE_PIX_FMTS`** is
      byte-for-byte unaffected: same argv, same output, no note.
- [ ] Every GIF source converts to `webm`. Today none does — an opaque GIF
      reports `bgra` and fails like a transparent one.
- [ ] A **transparent paletted** source keeps its transparency. Today it converts
      and loses it in silence — the phase's second defect, and the only one that
      is a live constitution breach rather than a failure.
- [ ] An **opaque paletted** source still converts, now at 4:2:0 instead of
      `gbrp`, and **the reduction is named by the existing re-encode note**
      ("re-encoded to vp9"), the same note every other fallback in this
      registry already carries — not by the new depth note (#117), which
      fires for bit depth only and does not fire for `pal8`, an 8-bit format
      (Decision log, 2026-09-15). Accepted at the gate as the cost of firing
      the *override* for every `pal8`, since `pix_fmt` cannot tell a
      transparent palette from an opaque one.
- [ ] A **>8-bit alpha** source keeps its alpha at 8-bit, and **the depth
      truncation is named** by a dedicated note that covers depth only
      (Decision log, 2026-09-15) — never chroma, which the opaque-paletted
      bullet above already covers by the existing re-encode note.
- [ ] A **10-bit** source into `webm` still produces 10-bit output
      (`yuv420p10le` in, `yuv420p10le` out), and an opaque high-depth source
      still reaches `gbrp12le`.
- [ ] A source already in a WebM codec that the cheap attempt **copies** is
      untouched, alpha included.
- [ ] Every rung that can re-encode carries the fix — the selective rung **and**
      `last_resort`, which fails identically today when reached. The
      `last_resort` half is **defensive**: with the selective rung fixed, no
      constructible source reaches it (see Prior decisions), so it is pinned by
      argv test only and carries no QA line that would have to pass.
- [ ] `CHANGELOG.md`'s v3.0.0 *Known limitations* entry for this defect records
      which release fixed it.
- [ ] Every branch ships with a test asserting the argv or note it produces, each
      proven non-vacuous by inverting its condition.

## Scope

### In scope

- `converter/profiles.py`: `webm`'s video rule and its `last_resort`, plus the
  declared pixel-format scalar (decision 2) and the value `last_resort` reads.
- `converter/jobs.py`: the mechanism that appends `-pix_fmt:v:{n}` from that
  declaration when the stream takes the fallback branch and its `pix_fmt` is not
  alpha-free, for both rungs.
- The **degradation note** for what the forced `yuva420p` reduces — **bit depth
  only** (Decision log, 2026-09-15, resolving this spec's own contradiction).
  Chroma resolution is never named by it: every fallback in this registry
  subsamples and none says so specifically, so the existing re-encode note
  already carries that half, consistently with the other sixteen profiles.
  This is the phase's only new note machinery.
- `docs/design/stream-decision.md` and `docs/design/degradation-ladder.md`: the
  node and the rung description for a source-dependent option.
- `docs/architecture.md` Key flow 2, whose per-stream match is where the new
  source-dependent branch sits — named here because the roadmap's foundation-impact
  line claims an architecture carrier and must point at one.
- `CHANGELOG.md`: the v3.0.0 *Known limitations* entry.
- `docs/roadmap.md`: the phase-9 row.
- The tests for all of it.

### Out of scope

- **Alpha for `mp4`, `mkv` and `mov`.** Their *cheap attempt* carries a `png`
  stream through — measured: exit 0, output `png`/`rgba`, alpha byte 127 intact
  — but this is the blind `-c copy` map plus a muxer that accepts a PNG track,
  **not** a copy-mask hit: `png` is in none of `MP4_VIDEO_CODECS`,
  `MKV_VIDEO_CODECS` or `MOV_VIDEO_CODECS`. So a `png` stream that reaches their
  **selective** rung is re-encoded by the h264 fallback and loses its alpha with
  no note, since none of the three declares `alpha_unsupported`. That is a real
  and separate defect; it is named here rather than fixed, because it is a
  different profile, a different encoder and a different decision. **File it as
  its own issue at this spec's acceptance.**
- **A second backend** or a differently-built libvpx (`docs/constitution.md`).
- **Alpha for any other target.** `png`, `tiff`, `bmp` and `webp` preserve it;
  `jpg`, `gif` and `avif` declare and name the loss (phase 8).
- **Auditing bit-depth handling across the other sixteen profiles.** This phase
  must not *introduce* a truncation, and decision 1 settles the one it could
  introduce; the general audit is its own concern.
- Changing which conversions happen for a source with no alpha.

## Constraints

- **Never report success for a conversion that silently dropped something**
  (`docs/constitution.md`). This is what forbids an unconditional override — see
  the 10-bit row — and what made decision 1 a decision rather than a
  detail.
- A target format is data, not code: adding a target must still produce no diff
  in `cli.py`, `batch.py` or `paths.py`, and `jobs.py`'s own docstring forbids
  the engine holding a format-specific fact — **including a literal pixel-format
  name**. Any mechanism that hard-codes `yuva420p` in `converter/jobs.py`
  violates the same rule that rules out special-casing `webm` there.
- The ffprobe **process count per conversion must not rise.** `Stream.pix_fmt` is
  already on the source probe (#104), so the fact this phase needs is in hand.
- Never parse ffmpeg's stderr to drive logic. The `gbrap` refusal is a fact
  recorded here, not something the engine may detect at runtime.
- No filter-graph access (`docs/vision.md`'s Out list): the pixel format is set
  through `-pix_fmt`, never a `format=` filter.
- `-pix_fmt` must be written in the **per-stream** form on the selective rung
  (`-pix_fmt:v:{n}`, the way that rung's other options already carry `{n}` through
  `_substitute_position`) and in the global form on `last_resort`, which names no
  index. A bare `-pix_fmt` on the selective rung would apply to every video output
  stream.
- The test suite keeps passing with no ffmpeg installed — so the *encoder*
  behaviour above is pinned as argv, and the round-trip evidence lives at the QA
  gate.

## Prior art

- [Container/codec capability modelling (Phase 1)](../prior-art.md#containercodec-capability-modelling-phase-1)
  — the method for declaring what a target can hold. This phase adds a capability
  that is **encoder-bound and pixel-format-bound** rather than container-bound,
  which the copy-mask model does not itself express.
- [FFmpeg/FFmpeg (the CLI as a capability source)](../prior-art.md#ffmpegffmpeg-the-cli-as-a-capability-source)
  — its warning that the CLI reports what exists rather than what is legal is
  exactly the trap recorded above, in its decoder-versus-encoder form. Cited as
  the class of error, not as a matrix source.
- [Image conversion through ffmpeg (Phase 5)](../prior-art.md#image-conversion-through-ffmpeg-phase-5)
  — its AVOID (never promise what the tool cannot deliver) now cuts the other
  way: the tool *can* deliver this, so declaring the loss would be the dishonesty.

## Human prerequisites

- none.

## Prior decisions

| Decision | Rationale | Date |
|---|---|---|
| Alpha is **preserved**, not dropped-and-named | Measured: `-pix_fmt yuva420p` round-trips α=127 with `alpha_mode=1` and a `BlockAdditional` block. Issue #114's ranking of the options was built on a decoder artefact | 2026-09-15 |
| Every alpha verification decodes with an **explicit libvpx decoder** | The native `vp9`/`vp8` decoders report `yuv420p` for a file that carries alpha. An output-`pix_fmt` check would silently "confirm" a false negative | 2026-09-15 |
| The verdict is **source-measured**, reusing `Stream.pix_fmt` against `ALPHA_FREE_PIX_FMTS` | Already probed (#104), no new process. The output side is unusable here for the decoder reason above, which is a second reason on top of phase 8's | 2026-09-15 |
| The override is **conditional on the source carrying alpha**, never unconditional | Measured: `yuv420p10le` survives today and any blanket `-pix_fmt` truncates it; an opaque `rgb48be` reaches `gbrp12le` with no flag | 2026-09-15 |
| `webm` does **not** declare `alpha_unsupported`, and emits no transparency note for the fixed case | It can hold alpha. Phase 8's forced-encoder boundary is therefore untouched by this phase — the first draft's open decision about widening it disappeared with the corrected facts | 2026-09-15 |
| Both re-encoding rungs are fixed, but `last_resort`'s half is **defensive** | Its argv fails identically on a `gbrap` source — reproduced at exit -22 — so leaving it inconsistent would be a trap for the next reader. But `webm`'s video rule declares **no `stream_limit`** (measured: `WEBM.rules["video"].stream_limit is None`; the only `stream_limit=1` rules in the tree are `wav`/`mp3`/`flac` and the image profiles), and with the selective rung fixed a two-video-stream source **succeeds there** — measured: `-pix_fmt:v:0 yuva420p` gives exit 0 and `vp9/yuva420p` + `vp9/gbrp`. `batch._attempt_conversion` returns on the first success, so `last_resort` is not reachable for any source this phase can construct. An earlier draft claimed a `stream_limit` that does not exist and gave it a QA line that could not pass | 2026-09-15 |
| **A >8-bit alpha source gets `yuva420p`**: alpha kept, depth truncated to 8-bit, and the truncation **named** | Resolved at the gate, 2026-09-15. The alternative keeps both but needs `-strict experimental`, whose output ffmpeg itself calls "not widely supported" — shipping files some players cannot read is a worse cost than a depth reduction, and naming a loss is what this tool is for. The note is new machinery; see the coupling row below | 2026-09-15 |
| **The pixel format is a declared scalar on the rule**; `converter/jobs.py` appends `-pix_fmt:v:{n}` when the stream takes the **fallback** branch *and* its `pix_fmt` is not in `ALPHA_FREE_PIX_FMTS` | Resolved at the gate, 2026-09-15. House style: every profile-declares-a-fact case in the tree is a scalar the engine reads (`partial_mapping`, `explicit_streams`, `alpha_unsupported`, `stream_limit`, `fallback_name`, `drop_reason`). A second options tuple would be the first of its kind. The engine contributes the flag, never the value, so `jobs.py` holds no format-specific fact | 2026-09-15 |
| **The override fires for every `pal8`** | Resolved at the gate, 2026-09-15. It fixes a measured silent transparency loss — a live breach of "never report success for a conversion that silently dropped something" — and `pix_fmt` cannot tell a transparent palette from an opaque one, so the undecidable case errs toward the non-silent direction, exactly as phase 8 chose for `pal8`. The accepted cost is that opaque paletted sources move from `gbrp` (4:4:4) to 4:2:0 | 2026-09-15 |
| **The new note covers bit depth only, never chroma** — corrected from an earlier "one note covers both losses" row that contradicted this spec's own Verification section | Resolved by the orchestrator at dispatch, 2026-09-15 (issue #117's body), on consistency grounds: every fallback in this registry subsamples and none names it specifically, so folding chroma into a new note only for the alpha case would be inconsistent with the other sixteen profiles. The opaque-paletted source's real cost (`gbrp` 4:4:4 -> 4:2:0) is carried by the existing re-encode note instead, exactly like every other fallback. See the Decision log entry below for the contradiction this replaces | 2026-09-15 |

### The three decisions, as resolved at the gate

Recorded with the options that were on the table, so a later reader sees what was
weighed rather than only what was picked.

**1. The >8-bit alpha source.** Now measured, on a fixture built by *converting*
a known-alpha PNG (`-pix_fmt rgba64be`) rather than synthesising one — the
drafting attempt used `color=...,format=rgba64be`, which yields an **opaque**
file, the same class of trap this spec records above. Verified source alpha
`0x7F7C`:

| Pixel format | Without `-strict experimental` | With it | Alpha back |
|---|---|---|---|
| `yuva420p` (8-bit) | **exit 0** | — | `0x7F00` — the low byte is gone |
| `yuva420p10le` | exit -22 | exit 0 | `0x7F80` |
| `gbrap10le` | exit -22 | exit 0 | `0x7F5F` |
| `gbrap12le` | exit -22 | exit 0 | `0x7F77` |
| `yuva444p12le` | exit -22 | exit 0 | `0x7F90` |

So all four >8-bit paths keep sub-byte alpha precision (the spread is ordinary
lossy-encode rounding around `0x7F7C`), and all four need the experimental flag.

- **A — always `yuva420p`.** Simplest and never experimental. A >8-bit alpha
  source keeps its alpha and loses depth — measured, `0x7F7C` -> `0x7F00` — which
  is a real degradation and so needs a note. There is no depth-note machinery
  today; phase 7 recorded `--to wav`'s bit-depth truncation as an open gap of the
  same kind, so this option either builds one or ships a silent truncation the
  constitution forbids.
- **B — `-strict experimental` plus a >8-bit alpha format when the source is
  >8-bit alpha.** Measured feasible, and cheaper than the first draft implied:
  `yuva420p10le` is a **one-token change** from `yuva420p`, so a `gbrap*` format
  is not required. Costs shipping an experimental flag by default, on output that
  is by ffmpeg's own words "not widely supported" — a playability risk the user
  never asked for.
- **C — treat a >8-bit alpha source as the alpha-free path**: keep the depth,
  drop the alpha, and name it. **This is the most expensive option, not the
  cheapest** — an earlier draft had this backwards. Phase 8's note reaches
  nothing unless the profile declares `alpha_unsupported`
  (`converter/jobs.py`: `if not profile.alpha_unsupported: return ()`), and that
  field's own docstring forbids exactly this profile from declaring it: a
  copy-based cheap attempt "asserts nothing about any encoder's behaviour, so it
  must never declare it". `tests/test_profiles.py` pins the declaring set to
  `{jpg, gif, avif}`. So option C means either violating a documented boundary
  and changing a pinned test, or building new note machinery — while discarding a
  channel in the one case the phase exists to protect.

**2. How the conditional pixel format reaches the argv.** Note that the
constitution narrows this more than the first draft allowed: a literal
`yuva420p` written into `converter/jobs.py` is a format-specific fact in the
engine, which `jobs.py`'s docstring forbids — the same rule that rules out
special-casing `webm` there. So the value must come from the profile either way.

- **A — a declared alternative option tuple** on the rule, used when the source
  carries alpha. Fully declarative; costs a second tuple that repeats the first
  plus one flag.
- **B — a declared pixel-format value** on the rule (e.g. an
  `alpha_pix_fmt` field), which `jobs.py` appends as `-pix_fmt:v:{n}` when the
  stream **takes the fallback branch** *and* its `pix_fmt` is not in
  `ALPHA_FREE_PIX_FMTS`. Both conditions are required: without the first, a
  vp9-alpha source that hits the copy mask would get a pixel-format flag beside
  `-c:v:0 copy`. One small declaration, no duplicated tuple; the engine
  contributes the flag but never the value.
- **C — a declared map** from alpha format to replacement. More general than any
  present need; listed to be dismissed unless the gate wants the generality.

**House style points at B**, and the gate should know it: every
profile-declares-a-fact case in the tree is a scalar the engine reads —
`partial_mapping`, `explicit_streams`, `alpha_unsupported`, `stream_limit`,
`fallback_name`, `drop_reason`. A second parallel options tuple (option A) has no
precedent anywhere in `converter/profiles.py`. Nothing *forces* B, so the
decision is genuinely open, but A would be the first of its kind.

**Whichever of A, B or C is chosen, it must also say where `last_resort` gets its
value.** All three are phrased "on the rule", but `last_resort` is an `Attempt`
on the `Profile`, not on a `StreamRule`, and is not built from rules at all — so
either the engine cross-references the `video` rule from a rung that has none, or
the profile declares a second value on `last_resort` itself. Settle it in the
same breath rather than leaving it to the implementer.

**3. Does the override fire for `pal8`?** This is about the override's
*condition*, not its mechanism, which is why it is its own decision. `pal8`
converts today and `pix_fmt` cannot say whether the palette carries a transparent
entry — the ambiguity phase 8 recorded when it chose to over-report for `pal8`.
Measured both ways:

- **Fire for every `pal8`.** A transparent paletted source keeps its
  transparency, which today it loses in silence. The cost is that an *opaque*
  paletted source moves from `gbrp` (4:4:4) to `yuva420p` (4:2:0) — this phase
  would introduce chroma subsampling into a conversion that works fine, for every
  paletted image in a tree. Consistent with phase 8's over-report-when-undecidable
  precedent, and with the constitution's preference for the non-silent direction.
- **Never fire for `pal8`.** No conversion that works today changes. The cost is
  leaving the silent transparency loss in place — a known constitution breach the
  phase measured and chose not to fix.
- **Fire, and keep 4:4:4** by declaring an alpha format that does not subsample
  (`yuva444p` and friends need `-strict experimental`, per decision 1's table).
  Keeps both properties; inherits decision 1's experimental-flag cost.

**Resolved: fire for every `pal8`** — the first option. The silent-loss rule
outranks a quality regression that is itself nameable, and the reduction note
above covers it.

With the combination resolved, `docs/design/stream-decision.md` gains the node that
describes a source-dependent option and `docs/design/degradation-ladder.md`
follows.

## Tracking

- Milestone: created at the spec-acceptance gate
- Issues: created from this spec once it is merged (one per implementable step)

## Verification

Machine checks (the suite stubs the subprocess boundary, so these pin **argv**,
never encoder behaviour):

- [ ] Verify passes on the merge commit.
- [ ] A test pinning the argv `webm`'s **selective rung** builds for an
      alpha-carrying source and for an alpha-free one: the two differ only by the
      pixel-format flag, the flag carries the per-stream `:v:{n}` form, and the
      alpha-free case is byte-for-byte what ships today.
- [ ] The same pair for **`last_resort`**, in its global (index-less) form. This
      is the whole of that rung's coverage — it is defensive and has no QA line,
      per the Prior-decisions row.
- [ ] A test that a `yuv420p10le` source's argv carries **no** pixel-format
      override on either rung.
- [ ] A test that a source whose codec is in `WEBM_VIDEO_CODECS` takes the copy
      branch, so no pixel-format flag is added.
- [ ] A test that a `bgra` source (every `.gif`) **and** a `pal8` source both get
      the override — the first fails today, the second does not, and both are
      meant to change.
- [ ] A test that the other sixteen profiles' argv is unchanged by this phase,
      for both an alpha and an alpha-free source.
- [ ] A test that the ffprobe process count per conversion is unchanged.
- [ ] A test that the reduction note fires for a **>8-bit alpha** source (depth
      only — corrected from an earlier draft of this line, which wrongly
      expected the same note for an opaque paletted source too; that source's
      chroma loss is carried by the existing re-encode note instead, Decision
      log 2026-09-15) and **not** for an ordinary 8-bit RGBA source or a
      `pal8` source, neither of which loses depth.
- [ ] Each branch proven non-vacuous: inverting its condition must fail a test.

Human milestone-QA gate. `$FF`/`$FP` are the absolute paths from *This machine*.
**Every alpha assertion below decodes with an explicit `-c:v libvpx-vp9`** — the
default decoder reports `yuv420p` for an alpha WebM and would confirm a false
negative.

```text
New-Item -ItemType Directory -Force in
& $FF -y -f lavfi -i "color=c=red@0.5:size=200x200:d=1,format=rgba" -frames:v 1 in/alpha-src.png
& $FF -y -f lavfi -i color=c=blue:size=200x200:d=1 -frames:v 1 in/opaque-src.jpg
& $FF -y -f lavfi -i testsrc=size=160x120:rate=10:duration=1 -c:v libx264 -pix_fmt yuv420p10le in/tenbit-src.mkv
& $FF -y -i in/alpha-src.png -c:v libvpx-vp9 -pix_fmt yuva420p in/vp9-alpha-src.webm
& $FF -y -i in/opaque-src.jpg -c:v gif in/opaque-gif-src.gif
& $FF -y -i in/alpha-src.png -pix_fmt rgba64be in/alpha16-src.png
& $FF -y -i in/alpha-src.png -vf "split[a][b];[a]palettegen=reserve_transparent=1[p];[b][p]paletteuse" -frames:v 1 in/pal-alpha-src.png
& $FF -y -i in/opaque-src.jpg -vf "split[a][b];[a]palettegen[p];[b][p]paletteuse" -frames:v 1 in/pal-opaque-src.png
```

Build `alpha16-src.png` by **converting** a known-alpha file, as above.
`color=...,format=rgba64be` yields an opaque file — verify its alpha before
trusting it (`0x7F7C`, not `0xFFFF`).

- [ ] **`--to webm` over `alpha-src.png` (selective rung)**: converts at exit 0.
      Decode the output with
      `& $FF -c:v libvpx-vp9 -i <out> -frames:v 1 -pix_fmt rgba -f rawvideo px.raw`
      and read the bytes from the file, confirming the centre pixel's alpha is
      ~127 and not 255. PowerShell mangles binary on stdout, so never pipe
      rawvideo to `-`. This is the reported defect; check it first.
- [ ] **`--to webm` over `opaque-src.jpg` (selective rung)**: converts, no
      transparency note, and the argv carries no pixel-format flag.
- [ ] **`--to webm` over `tenbit-src.mkv` (selective rung)**: the output still
      reports `yuv420p10le`. This is the regression an unconditional override
      causes.
- [ ] **`--to webm` over `vp9-alpha-src.webm` (cheap attempt, copy)**: the stream
      is copied; decode with the explicit libvpx decoder and confirm the alpha is
      still ~127. Note that `ffprobe` will report `yuv420p` for both input and
      output here — that is the decoder, not a loss.
- [ ] **`--to webm` over `opaque-gif-src.gif` (selective rung)**: converts at
      exit 0. It fails today at exit -22 even though it is fully opaque, because
      ffmpeg's gif decoder reports `bgra` for every GIF — so this line proves the
      phase fixes every GIF source, not only transparent ones.
- [ ] **`--to webm` over `pal-alpha-src.png` (selective rung)**: whatever open
      decision 3 settled. If the override fires, the corner pixel's alpha comes
      back **0**, not 255 — today it converts at exit 0 and comes back 255, which
      is the silent loss this phase found. This is the only QA line where the
      phase turns a reported success into a correct one.
- [ ] **`--to webm` over `pal-opaque-src.png` (selective rung)**: whatever open
      decision 3 settled, checked deliberately — it converts today via `gbrp`, so
      a firing override changes a working conversion to 4:2:0.
- [ ] **`--to webm` over `alpha16-src.png` (selective rung)**: whatever open
      decision 1 settled, checked on the fixture above — alpha preserved at full
      depth (option B), or preserved at 8-bit **with the degradation named**
      (option A).
- [ ] No QA line exercises `last_resort`, by design: with the selective rung
      fixed, no constructible source reaches it (Prior decisions). Its argv fix
      is covered by machine check alone.
- [ ] `CHANGELOG.md`'s v3.0.0 *Known limitations* entry has been updated.
- [ ] A second run over any converted tree reports `0 converted`, exit 0.
- [ ] The v3.0.0 smoke matrix still passes: all seventeen targets, no new failure.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| An implementer checks alpha with `ffprobe` or a default-decoder round-trip and concludes it was dropped | The trap is a call-out block, a Prior-decisions row, a Constraint, and an instruction on every QA line that touches alpha. It is the error this spec's own first draft made |
| The override is applied unconditionally and truncates 10-bit or high-depth sources | Its own Outcome bullet, two machine checks on the argv, and a QA line with a `yuv420p10le` fixture |
| A literal `yuva420p` is written into `converter/jobs.py` | Named as a constitution violation in Constraints and inside open decision 2, which is what narrowed that decision's options |
| `last_resort` is left inconsistent with the selective rung | Its own Outcome bullet and its own argv machine check. Deliberately **no** QA line: the rung is unreachable once the selective rung is fixed, and an earlier draft's QA line invoked a `stream_limit` that does not exist |
| The override's condition is inferred from roster membership rather than measured | The fact table states what the *encoder* negotiates per source, because `pal8` is outside the roster and yet succeeds today — the inference an earlier draft made and review round 3 refuted |
| The `mp4`/`mkv`/`mov` selective-rung alpha loss is assumed to be covered here | Scoped out explicitly, with the mechanism stated and an instruction to file it as its own issue at acceptance |
| A >8-bit alpha fixture is assumed rather than verified | The drafting attempt's fixture was opaque and is recorded as such, with the QA line requiring the fixture's alpha be confirmed before use |

## Decision log

- 2026-09-15: The first draft concluded that no encoder in this build writes WebM
  alpha, and planned drop-and-name on that basis. **The acceptance review refuted
  it by measurement** and the finding was re-verified independently before the
  rewrite: `-pix_fmt yuva420p` yields `alpha_mode=1`, a `BlockAdditional` block,
  and α=127 back through an explicit libvpx decoder. The error was reading the
  *native decoder's* missing alpha support as the *encoder's* — the exact class
  `docs/prior-art.md`'s FFmpeg entry warns about. Recorded rather than quietly
  rewritten, because the trap is a standing hazard for anyone re-measuring this
  phase.
- 2026-09-15: With the facts corrected, the first draft's open decision about
  widening phase 8's forced-encoder boundary **disappeared**: `webm` preserves
  alpha, so it declares no `alpha_unsupported` and the boundary is untouched. A
  decision presented as open turned out not to exist once the premise was right.
- 2026-09-15: The claim that `mp4`/`mkv`/`mov` "hold `png` in their copy masks"
  was wrong — `png` is in none of them. The behaviour is right (their blind
  `-c copy` cheap attempt plus a muxer that accepts a PNG track) but the
  mechanism was not, and the corrected mechanism exposes a separate defect on
  their selective rung, now scoped out by name.
- 2026-09-15: The 10-bit finding survived the rewrite unchanged and is what makes
  the override conditional rather than blanket. An opaque `rgb48be` source
  reaching `gbrp12le` today was added beside it.
- 2026-09-15: Review round 2 found two more statements the codebase contradicts,
  the same class as round 1's. The `last_resort` QA line invoked a
  `stream_limit` that `webm`'s video rule does not declare, and the fixture it
  named **succeeds on the selective rung** once the fix is applied — so the rung
  is not reachable for any constructible source and the line could never have
  passed. That half of the fix is now stated as defensive, pinned by argv test
  and given no QA line. And open decision 1's option C was described as the
  cheapest when it is the most expensive: phase 8's note is gated on
  `alpha_unsupported`, whose docstring forbids a copy-based cheap attempt from
  declaring it and whose declaring set is pinned by test to `{jpg, gif, avif}`.
  A cost stated backwards can produce the wrong choice at the gate.
- 2026-09-15: Review round 2 also established that the defect is **wider than an
  alpha source**. The condition is the reported `pix_fmt`, so every `.gif`
  source fails today — measured end to end on a fully opaque GIF, which the gif
  decoder reports as `bgra`. That makes the phase materially more valuable than
  its issue claimed and means v3.0.0's *Known limitations* wording understates
  the defect.
- 2026-09-15: Review round 3 refuted the generalisation that entry rested on.
  "Outside `ALPHA_FREE_PIX_FMTS`, therefore it fails" is an inference, not a
  measurement, and it is false for `pal8`: ffmpeg negotiates `gbrp` there, which
  libvpx accepts, so a paletted source **converts today**. The governing
  condition is what the encoder is landed on, not roster membership — the third
  round in a row that a confident statement about the tree turned out to be one
  step of reasoning past the evidence.
- 2026-09-15: That refutation surfaced a second defect worth more than the wrong
  row. A **transparent** paletted source converts at exit 0 and loses its
  transparency in silence — measured, corner pixel `A=0` in, `A=255` out through
  an explicit libvpx decoder, with only a `re-encoded to vp9` note. It is a live
  breach of "never report success for a conversion that silently dropped
  something", reachable from an ordinary PNG, and phase 8's note cannot reach it
  because `webm` declares no `alpha_unsupported`. `pal8` stays in scope for that
  reason instead, and the trade it forces — an opaque paletted source moving from
  `gbrp` to a subsampled format — became open decision 3 rather than a side
  effect of the condition picked for decision 2.
- 2026-09-15: Open decision 1 was measured rather than deferred to the
  implementer, on a fixture built by converting a known-alpha PNG. The drafting
  attempt had synthesised one with `color=...,format=rgba64be` and got an opaque
  file — the same decoder-versus-reality trap in a new place, caught by checking
  the fixture instead of trusting it.
- 2026-09-15 (issue #116): Resolved the one choice open decision 2 left to the
  implementer — how `webm`'s `last_resort` reaches the alpha pixel format
  declared on the `video` rule. **Chosen: the engine cross-references the
  `video` rule from `last_resort`** — `video_rule = profile.rules.get("video");
  value = video_rule.alpha_pix_fmt if video_rule else None` — rather than the
  `Profile` declaring a second value there. `jobs.retries` already receives
  the whole `profile` when it builds `last_resort` (`converter/jobs.py`), so
  reading the same rule's field costs no new declaration and keeps the value
  single-sourced; a second field on `Attempt` or `Profile` would restate the
  literal `"yuva420p"` a second time with nothing to keep the two in sync if
  either ever changed — the same "no duplicated tuple" reasoning decision 2
  itself used to prefer a scalar over a second options tuple. Both the dict
  lookup *and* the attribute access on its result must be guarded: five
  profiles declare a `last_resort` and no `"video"` rule at all (`mp3`,
  `flac`, `m4a`, `ogg`, `opus`), so `rules["video"].alpha_pix_fmt` raises
  `KeyError` on all five and `rules.get("video").alpha_pix_fmt` raises
  `AttributeError` on the same five — an earlier revision of this entry made
  exactly that second mistake while believing it had fixed the first. Issue
  #116 adds no engine code for the cross-reference itself (that is #117's
  mechanism, per this spec's own scope split); it adds only
  `StreamRule.alpha_pix_fmt`, the value declared on `webm`'s video rule, and a
  comment on `WEBM.last_resort` recording this choice for #117 to implement
  against.
- 2026-09-15 (issue #117): The Prior-decisions row "One note covers both
  losses the forced `yuva420p` causes" contradicted this spec's own
  Verification section. That row said the note covers depth *and* chroma,
  reasoning that both are "the same shape" (this conversion reduced the
  stream so its alpha could be carried); but the Verification section already
  required the note **not** to fire for an 8-bit RGBA source, "which gives up
  neither" — and an 8-bit RGBA source is 4:4:4 while the forced `yuva420p` is
  4:2:0, so it *does* give up chroma. The two statements cannot both hold.
  **Resolved by the orchestrator at dispatch, on consistency grounds**: the
  note covers **bit depth only**. Chroma subsampling is left to the existing
  re-encode note, because every fallback in this registry subsamples its
  output and none of them names that specifically — carving out a dedicated
  chroma note only for the alpha case would make `webm` inconsistent with the
  other sixteen profiles for no offsetting benefit. The Prior-decisions row,
  the two Outcome bullets (the opaque-paletted one and the >8-bit-alpha one),
  the Scope bullet naming the note, and the Verification bullet pinning its
  firing conditions were all corrected in the same pass so the spec no longer
  contradicts itself.
- 2026-09-15 (issue #117): Investigated whether the depth note is exposed to
  the rung-resurrection trap `converter.jobs._lossy_source_notes`'s docstring
  documents — folding a note into `_build_selective`'s own `notes` list can
  flip `if profile.explicit_streams and not notes: return None` and
  resurrect a rung the ladder deliberately never builds (`wav` is the case on
  record). **Finding: the trap does not apply to any profile shipped today**
  — `StreamRule.alpha_pix_fmt` is declared only on `webm`'s video rule, and
  `webm` sets `explicit_streams=False`, so `_build_selective`'s short-circuit
  can never trigger for it regardless of the depth note's presence. But
  nothing stops a future profile from declaring both `alpha_pix_fmt` and
  `explicit_streams=True` at once, at which point folding the note into the
  per-stream plan would silently resurrect that profile's selective rung the
  same way an in-line lossy-source note would have for `wav`. **Decision:
  compute the depth note as its own pass (`_alpha_depth_notes`), appended in
  `retries()` exactly like `_lossy_source_notes` and
  `_selective_transparency_notes`**, so the invariant holds by construction
  for any future profile rather than by coincidence of today's roster — the
  same reasoning `_selective_transparency_notes`'s own docstring already
  applies to its sibling note.

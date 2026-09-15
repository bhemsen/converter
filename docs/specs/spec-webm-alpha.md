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
| `-pix_fmt yuva420p10le` | **refused**, exit -22 — the same "not widely supported" message |
| VP8 (`-c:v libvpx`) + `yuva420p` | fails on the default `auto_alt_ref`; with `-auto-alt-ref 0`, exit 0 and `alpha_mode=1` |
| AV1 (`libaom-av1`) + `yuva420p` | alpha dropped — `libaom-av1` declares no `yuva*` pixel format |

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
- [ ] A source whose pixel format carries **no** alpha is byte-for-byte
      unaffected: same argv, same output, no note.
- [ ] A **10-bit** source into `webm` still produces 10-bit output
      (`yuv420p10le` in, `yuv420p10le` out), and an opaque high-depth source
      still reaches `gbrp12le`.
- [ ] A source already in a WebM codec that the cheap attempt **copies** is
      untouched, alpha included.
- [ ] Every rung that can re-encode carries the fix — the selective rung **and**
      `last_resort`, which fails identically today.
- [ ] Whatever the gate decides for a **>8-bit alpha** source is implemented and
      named: either it keeps both, or what it gives up is reported.
- [ ] `CHANGELOG.md`'s v3.0.0 *Known limitations* entry for this defect records
      which release fixed it.
- [ ] Every branch ships with a test asserting the argv or note it produces, each
      proven non-vacuous by inverting its condition.

## Scope

### In scope

- `converter/profiles.py`: `webm`'s video rule and its `last_resort`, plus
  whatever declaration open decision 2 settles on.
- `converter/jobs.py`: the mechanism that makes an attempt's pixel format depend
  on the probed source, for both rungs.
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
  must not *introduce* a truncation, and open decision 1 settles the one it could
  introduce; the general audit is its own concern.
- Changing which conversions happen for a source with no alpha.

## Constraints

- **Never report success for a conversion that silently dropped something**
  (`docs/constitution.md`). This is what forbids an unconditional override — see
  the 10-bit row — and what makes open decision 1 a decision rather than a
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
| Both re-encoding rungs are fixed | `last_resort` fails identically to the selective rung on a `gbrap` source — reproduced at exit -22. Fixing one rung would leave the defect reachable | 2026-09-15 |
| **OPEN — what happens to a >8-bit alpha source?** `yuva420p10le` is refused, so the non-experimental path can keep alpha *or* depth, not both. | resolved at the spec-acceptance gate | — |
| **OPEN — how does the conditional pixel format reach the argv?** Every attempt's options are a static tuple today, varied only by `_substitute_position`'s stream index. | resolved at the spec-acceptance gate | — |

### The two open decisions, in full

**1. The >8-bit alpha source.** Measured: `yuva420p10le` is refused without
`-strict experimental`; `gbrap` *with* it round-trips alpha at 8-bit. What a
>8-bit alpha source costs on the experimental path is **not yet measured** — the
first attempt used a fixture that turned out to be opaque, so the implementing
issue must measure it rather than inherit a guess.

- **A — always `yuva420p`.** Simplest and never experimental. A >8-bit alpha
  source keeps its alpha and loses depth, which is a real degradation and so
  needs a note — and there is no depth-note machinery today (phase 7 recorded
  `--to wav`'s bit-depth truncation as an open gap of the same kind).
- **B — `-strict experimental` with a `gbrap*` format when the source is
  >8-bit alpha.** Keeps both, if measurement confirms it. Costs shipping an
  experimental flag by default, and the output is by ffmpeg's own words "not
  widely supported" — a playability risk the user never asked for.
- **C — treat a >8-bit alpha source as the alpha-free path**: keep the depth,
  drop the alpha, and name it with phase 8's existing note. Consistent with the
  machinery already in the tree, at the cost of discarding a channel in the one
  case the phase exists to protect.

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
  source's `pix_fmt` is not in `ALPHA_FREE_PIX_FMTS`. One small declaration, no
  duplicated tuple; the engine contributes the flag but never the value.
- **C — a declared map** from alpha format to replacement. More general than any
  present need; listed to be dismissed unless the gate wants the generality.

Whichever pair is chosen, `docs/design/stream-decision.md` gains the node that
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
- [ ] The same pair for **`last_resort`**, in its global (index-less) form.
- [ ] A test that a `yuv420p10le` source's argv carries **no** pixel-format
      override on either rung.
- [ ] A test that a source whose codec is in `WEBM_VIDEO_CODECS` takes the copy
      branch, so no pixel-format flag is added.
- [ ] A test that the other sixteen profiles' argv is unchanged by this phase,
      for both an alpha and an alpha-free source.
- [ ] A test that the ffprobe process count per conversion is unchanged.
- [ ] Whatever open decision 1 settles: a test for the >8-bit alpha branch,
      including the note if that option emits one.
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
& $FF -y -i in/alpha-src.png -i in/opaque-src.jpg -map 0:v -map 1:v -c:v png in/twovid-src.mkv
```

- [ ] **`--to webm` over `alpha-src.png` (selective rung)**: converts at exit 0.
      Decode the output with `& $FF -c:v libvpx-vp9 -i <out> -pix_fmt rgba -f rawvideo -`
      and confirm the centre pixel's alpha is ~127, not 255. This is the reported
      defect; check it first.
- [ ] **`--to webm` over `opaque-src.jpg` (selective rung)**: converts, no
      transparency note, and the argv carries no pixel-format flag.
- [ ] **`--to webm` over `tenbit-src.mkv` (selective rung)**: the output still
      reports `yuv420p10le`. This is the regression an unconditional override
      causes.
- [ ] **`--to webm` over `vp9-alpha-src.webm` (cheap attempt, copy)**: the stream
      is copied; decode with the explicit libvpx decoder and confirm the alpha is
      still ~127. Note that `ffprobe` will report `yuv420p` for both input and
      output here — that is the decoder, not a loss.
- [ ] **`--to webm` over `twovid-src.mkv` (`last_resort`)**: its second video
      stream and the `stream_limit` force the ladder down to `last_resort`;
      confirm it converts and the alpha of the first stream survives.
- [ ] Whatever open decision 1 settles, exercised on a >8-bit alpha fixture built
      at implementation time (the one used while drafting turned out to be
      opaque — build it and verify its alpha before trusting it).
- [ ] `CHANGELOG.md`'s v3.0.0 *Known limitations* entry has been updated.
- [ ] A second run over any converted tree reports `0 converted`, exit 0.
- [ ] The v3.0.0 smoke matrix still passes: all seventeen targets, no new failure.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| An implementer checks alpha with `ffprobe` or a default-decoder round-trip and concludes it was dropped | The trap is a call-out block, a Prior-decisions row, a Constraint, and an instruction on every QA line that touches alpha. It is the error this spec's own first draft made |
| The override is applied unconditionally and truncates 10-bit or high-depth sources | Its own Outcome bullet, two machine checks on the argv, and a QA line with a `yuv420p10le` fixture |
| A literal `yuva420p` is written into `converter/jobs.py` | Named as a constitution violation in Constraints and inside open decision 2, which is what narrowed that decision's options |
| `last_resort` is left unfixed because only the selective rung was reproduced | Its own Outcome bullet, its own machine check, and a QA line with a fixture that reaches it |
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

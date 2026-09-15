# Spec: webm-alpha (roadmap phase 9)

> Created: 2026-09-15

Stop `--to webm` failing outright on a source that carries an alpha channel, and
name the loss instead of hiding it. This spec carries no lifecycle state —
acceptance is the spec merged on the default branch with a milestone and issues,
and all progress lives in the GitHub issues and milestone. A completed spec is
moved to `docs/specs/archive/`.

**This phase is not on the seeded roadmap.** It comes from issue #114, which
v3.0.0's pre-release smoke test filed and which that release shipped as a
documented *Known limitation* rather than silently. Its roadmap row is added in
this PR; its Spec and Milestone links are filled at the acceptance gate like
every other phase's. The same route phase 8 took from issue #101.

## The defect

An RGBA source into `webm` fails on **every rung** of the ladder. Measured,
ffmpeg 9.0, on a 200×200 RGBA PNG:

```
[selective] [libvpx-vp9] Pixel format 'gbrap' is not widely supported.
            Use -strict experimental to use it anyway, or use 'yuva420p'
            pixel format instead.  -> exit -22
[re-encode] (same)                  -> exit -22
[remux]     [webm] Only VP8 or VP9 or AV1 video and Vorbis or Opus audio
            and WebVTT subtitles are supported for WebM.
```

Result: the file is reported `FAILED` and the batch exits non-zero. Nothing is
corrupted and the rest of the batch still converts — the failure is loud, which
is why v3.0.0 shipped over it — but a reasonable conversion simply does not
happen.

It is **`webm`-specific by construction**, not a general alpha gap. `png` is not
in `WEBM_VIDEO_CODECS` (`vp8`, `vp9`, `av1`), so the stream must be re-encoded,
and `webm`'s video fallback names no `-pix_fmt`, so ffmpeg selects `gbrap` from
the RGBA source and libvpx refuses it. `mp4`, `mkv` and `mov` hold `png` in their
copy masks, **stream-copy it**, and preserve the alpha intact.

## What is achievable, and what is not

The obvious reading of the ffmpeg hint — "use `yuva420p` instead" — does not
survive measurement. **Alpha cannot be carried into WebM by this build at all.**

| Attempt on the RGBA source | Result |
|---|---|
| As shipped, no `-pix_fmt` | exit **-22**, no output — the defect |
| `-pix_fmt yuva420p` | exit 0, output reports **`yuv420p`** — the request is accepted and the alpha is dropped **silently** |
| `-strict experimental` | exit 0, output reports `gbrp`; round-tripped alpha measures **255** where the source was **127** — dropped silently |
| `-c:v libvpx` (VP8) with `yuva420p` | fails outright |
| `-c:v libaom-av1` with `yuva420p` | exit 0, output `yuv420p` — alpha dropped |

So every path that produces a file produces one without alpha. WebM *the format*
can carry alpha (VP8/VP9 store it in a secondary block), but no encoder in this
ffmpeg build writes it. The honest outcome is therefore **drop the alpha and say
so**, never "preserve it".

This is the same shape as phase 8's `gif` and `avif` conclusion, and the note
machinery that phase built — `Profile.alpha_unsupported`, `ALPHA_FREE_PIX_FMTS`,
`jobs._alpha_notes` — is what should name it. What does *not* transfer is where
the declaration may sit; see the open decisions.

## Outcome

- [ ] An RGBA source into `webm` **converts** instead of failing, and the
      conversion names the transparency loss, with the stream index and that
      stream's codec.
- [ ] A source whose pixel format carries **no** alpha is byte-for-byte
      unaffected: same argv, same output, no note.
- [ ] A **10-bit** source into `webm` still produces 10-bit output. Measured
      today: `yuv420p10le` in, `yuv420p10le` out — an unconditional
      `-pix_fmt yuv420p` would silently truncate it to 8-bit, trading this
      phase's defect for a quieter one.
- [ ] A source already in a WebM codec (`vp8`/`vp9`/`av1`) that the cheap
      attempt **copies** gets no transparency note — a copy drops nothing.
- [ ] `webm`'s `last_resort` carries a static format-limit statement about
      transparency, under `stream-decision.md`'s third carve-out.
- [ ] `CHANGELOG.md`'s v3.0.0 *Known limitations* entry for this defect is
      updated to say which release fixed it.
- [ ] Every branch ships with a test asserting the note it emits, each proven
      non-vacuous by inverting its condition.

## Scope

### In scope

- `converter/profiles.py`: `webm`'s video rule and `last_resort`, plus whatever
  declaration the open decisions settle on.
- `converter/jobs.py`: the mechanism that makes the fallback's pixel format
  depend on the source, and the entry point that emits the note for it.
- `docs/design/stream-decision.md` and `docs/design/degradation-ladder.md`: the
  boundary phase 8 stated as forced-encoder-only, which this phase must either
  widen or work within — whichever the open decisions settle.
- `CHANGELOG.md`: the v3.0.0 *Known limitations* entry.
- `docs/roadmap.md`: the phase-9 row.
- The tests for all of it.

### Out of scope

- **Preserving alpha into WebM.** Measured impossible with this build's
  encoders; promising it would be the lie `docs/vision.md` forbids.
- **A second backend** (a VP9 build with alpha support, or libwebp) — the
  single-dependency promise (`docs/constitution.md`).
- **Alpha for any other target.** `mp4`, `mkv` and `mov` copy a `png` stream
  and keep the channel; `png`, `tiff`, `bmp` and `webp` preserve it; `jpg`,
  `gif` and `avif` already declare and name the loss (phase 8).
- **The bit-depth question in general.** This phase must not *introduce* a
  truncation; auditing existing ones across every profile is its own concern.
- Changing which conversions happen for a source with no alpha.

## Constraints

- **Never report success for a conversion that silently dropped something**
  (`docs/constitution.md`). This is what rules out every "just make it encode"
  fix on its own: `-pix_fmt yuva420p` and `-strict experimental` both produce a
  file and both lose the alpha without a word.
- A target format is data, not code: what an encoder cannot hold is a profile
  declaration, and adding a target must still produce no diff in `cli.py`,
  `batch.py` or `paths.py`.
- The ffprobe **process count per conversion must not rise.** `Stream.pix_fmt`
  is already on the source probe (#104), so the fact this phase needs is already
  in hand — no new probe, and no `-count_packets`.
- Never parse ffmpeg's stderr to drive logic. The `gbrap` refusal is a measured
  fact recorded here, not something the engine may detect at runtime.
- No filter-graph access (`docs/vision.md`'s Out list) — the pixel format is set
  through `-pix_fmt`, not a `format=` filter.
- The test suite keeps passing with no ffmpeg installed.

## Prior art

- [Container/codec capability modelling (Phase 1)](../prior-art.md#containercodec-capability-modelling-phase-1)
  — the method for declaring what a target can hold. This phase adds a
  capability that is **encoder-bound rather than container-bound**, which is the
  distinction the copy-mask model does not itself express.
- [FFmpeg/FFmpeg (the CLI as a capability source)](../prior-art.md#ffmpegffmpeg-the-cli-as-a-capability-source)
  — the ADOPT here is the discipline this spec followed: the capability was read
  off the binary by measuring it, not inferred from what the format supports on
  paper. WebM-the-format carries alpha; this build's encoders do not.
- [Image conversion through ffmpeg (Phase 5)](../prior-art.md#image-conversion-through-ffmpeg-phase-5)
  — its AVOID (never promise what the tool cannot deliver) is why the outcome is
  "drop it and name it" rather than "preserve it".

## Human prerequisites

- none.

## Prior decisions

| Decision | Rationale | Date |
|---|---|---|
| Alpha is **dropped and named**, never preserved, for `webm` | Measured: no encoder in this ffmpeg build writes alpha into WebM. `yuva420p` is accepted and yields `yuv420p`; `-strict experimental` yields `gbrp` with alpha measured at 255 against a source 127; VP8 fails outright; AV1 yields `yuv420p` | 2026-09-15 |
| The verdict is **source-measured**, reusing `Stream.pix_fmt` against `ALPHA_FREE_PIX_FMTS` | The fact is already probed (#104) and costs no new process. The output side is unusable for the same reason phase 8 recorded — a written file's `pix_fmt` does not tell you what the channel held | 2026-09-15 |
| The pixel-format override is **conditional on the source carrying alpha**, never unconditional | Measured: a `yuv420p10le` source survives as 10-bit today and would be truncated to 8-bit by a blanket `-pix_fmt yuv420p`. Trading a loud failure for a silent truncation fails the constitution's own rule | 2026-09-15 |
| A **copied** stream gets no note | `jobs._alpha_notes`' `exclude_copies` already draws this line for the selective rung, and issue #97 drew it for the lossy advisory. A literal copy discards nothing | 2026-09-15 |
| `last_resort` keeps a **static** format-limit statement | That rung runs only after a failure and never holds a stream list — settled by phase 8's third carve-out in `stream-decision.md`, not re-opened here | 2026-09-15 |
| **OPEN — where does the declaration live?** `Profile.alpha_unsupported`'s documented precondition is a cheap attempt that *forces a single declared encoder unconditionally*; `webm`'s cheap attempt is `-c copy`, so it does not qualify, and phase 8's boundary explicitly excludes a copy-based attempt (`webp` is its pinned example). Either the declaration moves to the rule that actually owns the encoder, or the profile-level field's contract widens. | resolved at the spec-acceptance gate | — |
| **OPEN — how does the conditional pixel format reach the argv?** Today every attempt's options are a static tuple on the profile, varied only by `_substitute_position`'s stream index. A pixel format chosen from a probed source property is a new kind of variation. | resolved at the spec-acceptance gate | — |

### The two open decisions, in full

They are coupled: the second is only reachable once the first says who owns the
declaration. Both are recorded as options rather than guessed.

**1. Where the declaration lives.**

- **A — a new per-rule field** (e.g. `StreamRule.fallback_drops_alpha`). The
  declaration sits on the rule that owns the fallback encoder, which is exactly
  what cannot hold alpha. It composes with a copy-based cheap attempt by
  construction — a copy never reaches the fallback — so phase 8's boundary needs
  no widening at all. Cost: a second field expressing a near-identical idea to
  `Profile.alpha_unsupported`, and a decision about whether `jpg`/`gif`/`avif`
  migrate to it or the two coexist.
- **B — widen `Profile.alpha_unsupported`'s contract** so it also covers a
  profile whose cheap attempt may copy, by making the cheap-attempt entry point
  exclude copy-mask hits the way the selective rung already does. Cost: one
  field, but it changes behaviour for the three profiles that already declare it
  and rewrites the boundary phase 8 spent a whole issue (#106) stating in five
  places. Whether any of `jpg`/`gif`/`avif` actually changes behaviour needs
  measuring before this is chosen — an `mjpeg` source into `jpg` is the case to
  check, and its `yuvj420p` may make it moot.
- **C — declare nothing; special-case `webm` in the engine.** Rejected in
  advance by `docs/constitution.md` ("a target format is data, not code") and by
  `jobs.py`'s own docstring forbidding a format-specific fact in the engine.
  Listed so the gate sees it was considered, not to be chosen.

**2. How the conditional pixel format reaches the argv.**

- **A — a declared alternative option tuple** on the rule, used when the source
  carries alpha (e.g. alongside `fallback_options`). Keeps argv fully declarative
  — the profile still states every option it can produce — at the cost of a
  second tuple that repeats the first plus one flag.
- **B — an engine-injected `-pix_fmt`**, appended by `jobs.py` when the
  declaration says the fallback cannot hold alpha and the source's `pix_fmt` is
  not in `ALPHA_FREE_PIX_FMTS`. One declaration, no duplicated tuple, but the
  engine now contributes an option the profile never wrote, which is a genuine
  departure from "a recipe reads like the command line you would type".
- **C — pick the replacement format from a declared map** (alpha format ->
  alpha-free counterpart). More general than the problem; no second target needs
  it today. Listed to be dismissed unless the gate wants the generality.

Whichever pair is chosen, `docs/design/stream-decision.md` gains the node or the
carve-out that describes it, and `docs/design/degradation-ladder.md` follows.

## Tracking

- Milestone: created at the spec-acceptance gate
- Issues: created from this spec once it is merged (one per implementable step)

## Verification

Machine checks:

- [ ] Verify passes on the merge commit.
- [ ] A test pinning the argv `webm`'s video fallback builds for an
      **alpha-carrying** source and for an **alpha-free** one — the two must
      differ only by the pixel-format flag, and the alpha-free case must be
      byte-for-byte what ships today.
- [ ] A test that a `yuv420p10le` source's argv carries **no** pixel-format
      override, pinning that the 10-bit path is untouched.
- [ ] A test that the transparency note fires for an alpha source into `webm`,
      naming the stream index and that stream's codec.
- [ ] A test that a `vp9` source the cheap attempt copies emits **no**
      transparency note, even when its `pix_fmt` carries alpha.
- [ ] A test that `webm`'s `last_resort` notes carry the static format-limit
      statement.
- [ ] A test that the ffprobe **process count** per conversion is unchanged for
      an alpha source into `webm`.
- [ ] Whichever declaration the gate picks, a test that the other sixteen
      profiles' argv is unchanged by this phase.
- [ ] Each branch proven non-vacuous: inverting its condition must fail a test.

Human milestone-QA gate. `$FF` is the absolute ffmpeg path from *This machine*:

```text
New-Item -ItemType Directory -Force in
& $FF -y -f lavfi -i "color=c=red@0.5:size=200x200:d=1,format=rgba" -frames:v 1 in/alpha-src.png
& $FF -y -f lavfi -i color=c=blue:size=200x200:d=1 -frames:v 1 in/opaque-src.jpg
& $FF -y -f lavfi -i testsrc=size=160x120:rate=10:duration=1 -c:v libx264 -pix_fmt yuv420p10le in/tenbit-src.mkv
& $FF -y -f lavfi -i testsrc=size=160x120:rate=10:duration=1 -c:v libvpx-vp9 in/vp9-src.webm
```

- [ ] `--to webm in out` over `alpha-src.png`: **converts** at exit 0, and the
      transparency note fires naming the stream index and `png`. This is the
      reported defect; check it first.
- [ ] `--to webm in out` over `opaque-src.jpg`: converts, and emits **no**
      transparency note.
- [ ] `--to webm in out` over `tenbit-src.mkv`: the output still reports
      `yuv420p10le`. This is the regression an unconditional override causes.
- [ ] `--to webm in out` over `vp9-src.webm`: the cheap attempt copies it, and
      no transparency note appears.
- [ ] `ffprobe` the alpha source's output and confirm it reports an alpha-free
      pixel format — the note is telling the truth, not guessing.
- [ ] A second run over any converted tree reports `0 converted`, exit 0.
- [ ] The whole v3.0.0 smoke matrix still passes: all seventeen targets, no new
      failure.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| An implementer reads ffmpeg's own hint and forces `yuva420p`, believing alpha is preserved | The measurement is a fact-table row: `yuva420p` yields `yuv420p`. A QA line probes the output's pixel format |
| The override is applied unconditionally and truncates 10-bit sources | Its own Outcome bullet, a machine check on the argv, and a QA line with a `yuv420p10le` fixture |
| Phase 8's forced-encoder boundary is widened by accident rather than by decision | It is open decision 1, with the copy-based exclusion (`webp`) named as the case that made it a boundary at all |
| A note fires for a stream the cheap attempt copied | `exclude_copies` already exists; a QA line and a machine check use a `vp9` source |
| The engine gains a format-specific fact | Open decision 1 option C is named and pre-rejected against `jobs.py`'s docstring |

## Decision log

- 2026-09-15: The issue offered three options, two of which measurement removed.
  "Force `yuva420p`" produces `yuv420p` — a silent drop, not a fix. "Choose the
  pixel format from the source to preserve alpha" cannot preserve anything,
  because no encoder in this build writes WebM alpha. What is left is the third
  option, drop-and-name — which the issue ranked last for giving up a capability
  the format has. The format has it; this build cannot reach it.
- 2026-09-15: The `mp4`/`mkv`/`mov` comparison was measured rather than assumed.
  They do not handle alpha better — they stream-copy the `png` stream into the
  container (`rgba` out, alpha byte 127 intact), so the question never arises.
  That is what makes this defect `webm`-only rather than the visible corner of a
  general gap.
- 2026-09-15: The 10-bit case was found while checking what an unconditional
  `-pix_fmt yuv420p` would cost. It would have replaced a loud failure with a
  silent truncation, which is the trade the constitution forbids — so the
  conditional shape is a constraint, not a preference.

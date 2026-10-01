# converter — Roadmap

> Living document: the sequenced queue of phases. The hand-off to `/plan`, which
> picks the next phase, creates its spec + issues, and links them back here.
> No status markers — progress lives in the GitHub issues and milestones each
> phase links to. Specs (created by `/plan`) carry no lifecycle state either;
> a spec is "accepted" once merged on the default branch with a milestone and
> issues.

## Phase overview

| Phase | Name | Spec | Milestone |
|---|---|---|---|
| 1 | profile-registry | [spec-profile-registry.md](specs/archive/spec-profile-registry.md) | [#1](https://github.com/bhemsen/converter/milestone/1) |
| 2 | target-driven-cli | [spec-target-driven-cli.md](specs/archive/spec-target-driven-cli.md) | [#2](https://github.com/bhemsen/converter/milestone/2) |
| 3 | audio-formats | [spec-audio-formats.md](specs/archive/spec-audio-formats.md) | [#3](https://github.com/bhemsen/converter/milestone/3) |
| 4 | video-formats | [spec-video-formats.md](specs/archive/spec-video-formats.md) | [#4](https://github.com/bhemsen/converter/milestone/4) |
| 5 | image-formats | [spec-image-formats.md](specs/archive/spec-image-formats.md) | [#5](https://github.com/bhemsen/converter/milestone/5) |
| 6 | stream-disposition | [spec-stream-disposition.md](specs/archive/spec-stream-disposition.md) | [#6](https://github.com/bhemsen/converter/milestone/6) |
| 7 | lossy-source-notes | [spec-lossy-source-notes.md](specs/archive/spec-lossy-source-notes.md) | [#7](https://github.com/bhemsen/converter/milestone/7) |
| 8 | within-stream-loss-notes | [spec-within-stream-loss-notes.md](specs/archive/spec-within-stream-loss-notes.md) | [#8](https://github.com/bhemsen/converter/milestone/8) |
| 9 | webm-alpha | [spec-webm-alpha.md](specs/archive/spec-webm-alpha.md) | [#9](https://github.com/bhemsen/converter/milestone/9) |
| 10 | single-file-input | [spec-single-file-input.md](specs/archive/spec-single-file-input.md) | [#10](https://github.com/bhemsen/converter/milestone/10) |
| 11 | json-output | [spec-json-output.md](specs/archive/spec-json-output.md) | [#11](https://github.com/bhemsen/converter/milestone/11) |
| 12 | abort-safe-writes | [spec-abort-safe-writes.md](specs/archive/spec-abort-safe-writes.md) | [#12](https://github.com/bhemsen/converter/milestone/12) |
| 13 | web-target | [spec-web-target.md](specs/archive/spec-web-target.md) | [#13](https://github.com/bhemsen/converter/milestone/13) |
| 14 | subtitle-sidecars | [spec-subtitle-sidecars.md](specs/spec-subtitle-sidecars.md) | [#14](https://github.com/bhemsen/converter/milestone/14) |

A phase gets a Spec link once `/plan` drafts it, and a Milestone link once the
spec is merged. The milestone (open/closed + issue progress) is where status
lives.

Foundation impact, recorded at seeding and authored in that phase's `/plan` spec
PR. What never happens here is the foundation-doc *edit*; the verdict itself is
corrected in place when planning measures it wrong, as phases 6 and 7 both
record -- phase 6 corrected a verdict's reason, phase 7 flipped one:

- Phase 6 — Foundation impact: vision — none; constitution — **yes** (corrected at planning: the disposition selector arrived in ffmpeg 7.1, which the tech-stack row now records as the floor for the fast path); architecture — yes: Key flow 2's per-stream match gains a disposition branch, `docs/design/stream-decision.md` gains the node that distinguishes a picture from a video stream, and `docs/design/degradation-ladder.md` gains a third selector kind.
- Phase 7 — Foundation impact: vision — none; constitution — yes: the notes convention and its test gate assume a note describes what *this* conversion gave up, and an advisory about loss the source already carried is a second kind that has to be defined; architecture — **none** (corrected at planning: cross-cutting codec data already lives in `converter/profiles.py` as a module-level frozenset — `TEXT_SUBTITLE_CODECS` is shared by `mp4`, `mov` and `webm` — so a lossy-codec set beside it needs no architectural change).
- Phase 8 — Foundation impact: vision — none; constitution — none; architecture — yes: Key flow 1's success-side verification widens from structural verdicts to structural plus stream-property ones. **Five carriers, all named in the spec's Scope**: `docs/architecture.md` Key flow 1, `docs/design/degradation-ladder.md`, the `jobs` module docstring, the comment above `converter/jobs.py`'s `_LOSSY_SOURCE_ADVISORY_TARGETS` (line numbers go stale as the file grows, so locate it by content), and `docs/design/stream-decision.md`, which additionally gains a third carve-out from the three-things rule.
- Phase 9 — Foundation impact: vision — none; constitution — none; architecture — yes: the engine gains an attempt option that depends on a probed *source* property rather than only on the stream index. **Three carriers, all named in the spec's Scope**: `docs/architecture.md` Key flow 2, whose per-stream match is where the branch sits, `docs/design/stream-decision.md`, which gains the node describing it, and `docs/design/degradation-ladder.md`, which follows. Phase 8's forced-encoder boundary is **not** touched — the first draft thought it might be, on a premise the acceptance review refuted: `webm` preserves alpha, so it declares no `alpha_unsupported` and the boundary is untouched.
- Phase 10 — Foundation impact: vision — yes: the Scope's *In* list names only a recursive batch over a directory tree, so a single named file needs its own entry there; constitution — none: no principle assumes a directory, and "one broken input file must not abort the batch" holds trivially for a batch of one; architecture — yes: Key flow 1 starts at `paths.find_sources` walking a root, and `docs/design/source-selection.md`'s first node is "file under the input root" — both gain the branch where INPUT is itself a file, which bypasses the suffix set and derives its output directory differently.
- Phase 11 — Foundation impact: vision — yes: Scope *In* names progress reporting and a non-zero exit but no machine-readable output, although the secondary users are defined by "the exit code and parsable output"; the JSON Lines stream and the exit-code contract need their own entry; constitution — none: no principle constrains the output format, and the stderr rule ("never parse ffmpeg's stderr") is about input, not output; architecture — yes: `batch.Result` becomes a public contract rather than an internal value, and reporting (`batch._report`, the summary line in `cli`) needs one seam both the text and the JSON renderer go through.
- Phase 12 — Foundation impact: vision — none; constitution — yes: "A partially written output file is removed when its conversion fails" must widen to *fails or is interrupted*, with outputs written under a temporary name and renamed only on success, and the Windows half rests on a Job Object reached through `ctypes` — no new dependency, but a platform mechanism the tech-stack table should record; architecture — yes: `ffmpegtool.run()` becomes a tracked, killable process (a registry and a shutdown flag; the converter's own process group on POSIX — corrected at planning, a new session would stop group-wide kills reaching ffmpeg; a Job Object on Windows), every profile gains an explicit muxer because a `.partial` name defeats ffmpeg's extension-based muxer choice (measured, ffmpeg 9.0), and Key flow 1 gains the write-then-rename step and a termination flow.
- Phase 13 — Foundation impact: vision — yes: the success criterion's target list grows from 17 to 18, and the "no diff in `cli.py`, `batch.py` or `paths.py`" criterion must be shown to hold for `web` — the probe-first ladder is an engine change in `jobs.py`, which that criterion does not name, so the profile itself stays data; constitution — yes: the principle that `ffprobe` never runs on the happy path of an exhaustive cheap attempt gains a third kind, a *probe-first* profile that skips the blind remux and builds its first attempt from the probe and the copy mask — still one probe per file, the same count `partial_mapping` already spends for MP4; architecture — yes: `docs/design/degradation-ladder.md` gains the probe-first entry, `docs/design/stream-decision.md` gains a copy condition on `pix_fmt` beside the codec mask, and Key flow 1 names the probe-first branch.
- Phase 14 — Foundation impact: vision — yes: Scope *In* gains "a conversion may write sidecar files next to its output", which today's one-source-one-output model does not allow; constitution — none: the sidecar is declared as profile data, so "a target format is data" holds; architecture — yes: `paths.output_for` yields one primary output plus sidecars, and the collision, self-write, overwrite-hazard and existing-output guards of `docs/design/source-selection.md` must cover every path a source writes, not just the primary one; the JSON record from phase 11 and the `.partial` handling from phase 12 must cover sidecars too.

## What each phase covers

1. **profile-registry** — Create `converter/profiles.py` as a leaf module and turn
   the ladder in `converter/jobs.py` into a generic engine driven by a profile.
   MKV-to-MP4 and Opus-to-WAV are *re-expressed* as profiles: the ffmpeg argv
   stays identical, and a note changes only where it gains a fact today's wording
   omits — each such change argued in the PR. The existing 141 tests are the
   safety net. No CLI change.
2. **target-driven-cli** — `converter --to <format>` replaces the `video` and
   `audio` sub-commands, plus `--list-formats` and a reworked interactive prompt.
   Corrects the README, including the stale `develop` pull-request target. This is
   the breaking change, so it lands as 3.0.0.
3. **audio-formats** — Profiles for `mp3`, `m4a`, `flac`, `wav`, `opus`, `ogg`.
4. **video-formats** — Profiles for `mp4`, `mkv`, `webm`, `mov`.
5. **image-formats** — Profiles for `png`, `jpg`, `webp`, `avif`, `gif`, `tiff`,
   `bmp`.
6. **stream-disposition** — Teach the engine to tell a cover picture from a real
   video stream: a `disposition` field on `Stream`, the matching `-show_entries`
   clause in `ffmpegtool.py`, and the branch that uses it. Then `mp3`, `m4a` and
   `flac` carry artwork through instead of dropping it, and their standing note
   narrows to the case that is still a real loss. Measured cost: one probe field,
   one dataclass field, one branch — materially less than the "engine change"
   framing under which phase 3 deferred it.
7. **lossy-source-notes** — A curated set of lossy codecs, so converting an
   already-lossy source into a lossless target says so: the "40 MB FLAC from a
   128 kbit/s MP3" advisory. Deferred out of phase 3 because `Stream` carries no
   such notion and that phase was deliberately data-only.
8. **within-stream-loss-notes** — Make the image targets' loss notes fire only
   when the loss happened, and name the stream it happened to. Today `jpg`, `gif`
   and `avif` state a format fact on every file, so an opaque JPEG is told its
   transparency was not carried. Filed by #67's own PR as issue #101 rather than
   dropped, and planned directly rather than seeded.
9. **webm-alpha** — Stop `--to webm` failing outright on a source that carries an
   alpha channel, and carry the channel through. Measured: `-pix_fmt yuva420p` is
   all libvpx-vp9 needs — `alpha_mode=1`, the alpha on a Matroska
   `BlockAdditional` block, α round-tripping intact. The override must be
   conditional on the probed source, because a blanket `-pix_fmt` would silently
   truncate a 10-bit source that survives today. The standing hazard the phase
   records: ffmpeg's *native* vp9/vp8 decoders have no alpha support and report
   `yuv420p` for a file that carries it, so every check must decode with an
   explicit libvpx decoder. Filed by v3.0.0's pre-release smoke test as issue
   #114 and shipped as a documented limitation rather than held back.
10. **single-file-input** — Let `INPUT` name one file instead of a directory, so
    a single conversion gets the ladder and the loss notes rather than sending
    the user back to raw ffmpeg. Decided in the sparring: exactly one file (not
    several — that would need `-o` in place of the positional `OUTPUT`, a second
    CLI break); `OUTPUT` stays a directory and becomes optional for a file, the
    result landing beside the source when it is omitted; `--to` stays the only
    way to name the format (no ImageMagick-style inference from an output file
    name); and a file named explicitly bypasses the source-suffix set, because
    the user chose it and ffprobe, not an extension list, decides whether it is
    readable — an unreadable one fails as any other conversion does, exit
    non-zero. Left open for `/plan`: what `-r` and `--mirror-to` mean for a file
    (ignore, re-root its parent, or refuse), a file whose output would be itself
    (`a.mp4 --to mp4` with no `OUTPUT` — the existing self-write guard should
    already refuse it, to be confirmed), the `--dry-run` wording, and whether the
    interactive prompt offers the file case at all.
11. **json-output** — `--json`: one JSON object per file as JSON Lines on
    stdout — `source`, absolute `output`, `outcome` (`converted` / `skipped` /
    `failed` / `unsupported`), the `attempt` that produced it, `notes[]`,
    `error` — plus one closing summary object, a discriminator field telling the
    two apart. No progress bar and no `Using ffmpeg …` on stdout under `--json`.
    The exit codes 0/1/2/130 become a documented, stable contract in the README,
    including that 0 covers `skipped` and `unsupported`. Seeded 2026-09-28 from
    the *videothek* idea — a browser player that runs the converter as a child
    process, per file, argv, no shell. Left open for `/plan`: the discriminator's
    name and whether the schema carries a version in-band (restic and cargo do
    not; the sparring flagged that as a gap to decide, not to copy).
12. **abort-safe-writes** — Write every output under a temporary name and rename
    it into place only on success; on SIGTERM/SIGINT (POSIX) terminate the running
    ffmpeg processes and delete their partial files; on Windows, where a parent's
    kill is an uncatchable `TerminateProcess` that leaves ffmpeg orphaned, bind
    each ffmpeg to a Job Object with `KILL_ON_JOB_CLOSE` and remove stale partial
    files on the next run. Decided in the sparring: both platforms, Windows
    through the Job Object plus that sweep. Measured, ffmpeg 9.0: a `.partial`
    suffix makes ffmpeg fail with "Unable to choose an output format", and an
    explicit `-f` fixes it — so every profile declares its muxer as data. Left
    open for `/plan`: the temporary name (a suffix after the extension needs
    `-f`; one before it, `x.partial.mp4`, would be rediscovered as a *source* by
    the next directory walk), the bounded retry `os.replace` needs on Windows when
    a scanner holds the target, and the exit code for SIGTERM (143 by the 128+n
    convention).
13. **web-target** — `--to web`: an MP4 a plain HTML5 `<video>` plays in every
    current browser. A new engine mode, *probe first*: the profile skips the
    blind `-c copy` remux and builds its first attempt from the probe and the
    copy mask, because a remux is exactly what lets HEVC, AC-3, E-AC-3, MPEG-4
    Part 2 and MPEG-2 through untouched while the run reports success. Copy mask,
    decided in the sparring on the research's evidence: video `h264` only when
    8-bit `yuv420p`/`yuvj420p` (a copy condition on `Stream.pix_fmt`, which
    exists since phase 8), audio `aac` and `mp3`; everything else re-encodes to
    libx264 `-pix_fmt yuv420p` and aac. VP9, AV1, Opus and FLAC are re-encoded
    deliberately: AV1 has no Safari fallback below Apple's newest hardware, and
    Opus/FLAC-in-MP4 in Safari's `<video>` is thinly evidenced. All audio tracks
    are kept — browsers play the default one, Safari can switch, nothing is lost.
    `+faststart` as for `mp4`. Text subtitles are **dropped with a note** in this
    phase; phase 14 turns them into sidecars. The encoder preset is profile data,
    not a flag (the vision excludes an encoder-tuning surface), and its value is
    **measured on a Raspberry Pi 4** in the spec — the only published data point
    is libx264 at 8–10 fps for 1080p, below real time, with no per-preset
    breakdown. `--to mp4` keeps its behaviour.
14. **subtitle-sidecars** — `--to web` writes each text subtitle stream as a
    WebVTT file beside the MP4 (`<stem>.<lang>.vtt`, a stable suffix for
    streams without a language), because no browser renders in-band `mov_text`
    in a plain `<video>`; image subtitles stay dropped with a note. The first
    phase where one source produces several outputs, so the skip, collision,
    self-write and overwrite guards, the JSON record and the partial-file
    handling all have to cover every path a source writes. Left open for `/plan`:
    the naming for two streams that share a language, and whether an existing
    MP4 with a missing sidecar counts as done.

## Sequencing rationale

Phase 1 precedes phase 2 because a target-format-driven CLI has nothing to drive
without the registry underneath it. Phase 2 precedes 3-5 so the breaking change
lands exactly once: after the coverage phases, every format added beforehand would
have to be migrated. Within 3-5, audio comes first because audio profiles are the
simplest (mostly a single stream type), which validates the profile model cheaply
before the harder video cases.

Phases 3, 4 and 5 depend only on phase 2, not on each other, so their milestones
can run as parallel orchestrators. That independence is recorded as the
`Depends on milestone:` line in each milestone description.

Phases 6 and 7 both follow phase 3: each revisits audio profiles that phase 3
creates, and neither is worth planning before those exist. They are independent
of each other and of phases 4 and 5. Both were deferred out of phase 3 by name,
with their costs recorded in `docs/specs/archive/spec-audio-formats.md` rather than left
to be rediscovered — and phase 6's cost turned out to be smaller than that
deferral assumed.

Phase 8 follows phase 5, whose image profiles it corrects. It is the first phase
not seeded through `/loopkit:roadmap`: the PR that half-closed it filed the
remainder as issue #101 rather than dropping it, and it was planned directly.

Phase 9 follows phase 4, whose `webm` profile it corrects, and depends on phase 8
for the data rather than the format: `Stream.pix_fmt` and `ALPHA_FREE_PIX_FMTS`
arrived there and are exactly the source-side fact this phase needs, so it
reuses them instead of building its own. It does **not** reuse phase 8's
transparency note — `webm` preserves alpha, so it declares no
`alpha_unsupported` and emits no such note. It is the second phase planned
directly from an issue rather than seeded — the route phase 8 established, here
starting from a release's own smoke test rather than from a PR's unresolved
finding.

Phase 10 depends only on phase 2, whose target-driven CLI it extends; it touches
no profile, so it is independent of every coverage and loss-note phase. It is a
CLI-surface change rather than a format one, which is why it is exempt from the
vision's "no diff in `cli.py`, `batch.py` or `paths.py`" criterion — that rule
governs adding a *target format*, and this phase adds none. It is additive: every
existing directory invocation keeps its meaning, so it needs no major version.

Phases 11-14 come from one idea, seeded together on 2026-09-28: the converter as
a dependable child process for *videothek*, a browser player. The idea named
three gaps in the order web target, JSON output, abort safety; the phases run in
the opposite order, because each later one uses the earlier ones. Phase 11 and
phase 12 are independent of each other and can run as parallel orchestrators.
Phase 13 depends on 12 — its re-encodes are exactly the long-running writes a
kill is most likely to interrupt — and phase 14 depends on 11, 12 and 13, since
its sidecars must appear in the JSON record, be written abort-safely, and exist
only for the `web` target. Splitting the sidecars out of phase 13 keeps that
phase's profile checkable against the vision's "a new format is data" criterion:
the probe-first mode is an engine change in `jobs.py`, but one output per source
still holds until phase 14 deliberately widens it.

There is deliberately no separate release or documentation phase. README changes
belong to the phase that makes them necessary — phase 2 breaks the CLI, so phase 2
fixes the README, and each coverage phase maintains its own format list. The
release itself runs through `/loopkit:ship` against `docs/release.md`.

## North star

Every format ffmpeg can write becomes one profile entry — and every loss on the
way there gets named.

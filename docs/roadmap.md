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
| 8 | within-stream-loss-notes | — | — |

A phase gets a Spec link once `/plan` drafts it, and a Milestone link once the
spec is merged. The milestone (open/closed + issue progress) is where status
lives.

Foundation impact, recorded at seeding and authored in that phase's `/plan` spec
PR. What never happens here is the foundation-doc *edit*; the verdict itself is
corrected in place when planning measures it wrong, as phases 6 and 7 both
record -- phase 6 corrected a verdict's reason, phase 7 flipped one:

- Phase 6 — Foundation impact: vision — none; constitution — **yes** (corrected at planning: the disposition selector arrived in ffmpeg 7.1, which the tech-stack row now records as the floor for the fast path); architecture — yes: Key flow 2's per-stream match gains a disposition branch, `docs/design/stream-decision.md` gains the node that distinguishes a picture from a video stream, and `docs/design/degradation-ladder.md` gains a third selector kind.
- Phase 7 — Foundation impact: vision — none; constitution — yes: the notes convention and its test gate assume a note describes what *this* conversion gave up, and an advisory about loss the source already carried is a second kind that has to be defined; architecture — **none** (corrected at planning: cross-cutting codec data already lives in `converter/profiles.py` as a module-level frozenset — `TEXT_SUBTITLE_CODECS` is shared by `mp4`, `mov` and `webm` — so a lossy-codec set beside it needs no architectural change).
- Phase 8 — Foundation impact: vision — none; constitution — none; architecture — yes: Key flow 1's success-side verification widens from structural verdicts to structural plus stream-property ones, restated in `docs/design/degradation-ladder.md` and the `jobs` docstring.

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

There is deliberately no separate release or documentation phase. README changes
belong to the phase that makes them necessary — phase 2 breaks the CLI, so phase 2
fixes the README, and each coverage phase maintains its own format list. The
release itself runs through `/loopkit:ship` against `docs/release.md`.

## North star

Every format ffmpeg can write becomes one profile entry — and every loss on the
way there gets named.

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
| 1 | profile-registry | — | — |
| 2 | target-driven-cli | — | — |
| 3 | audio-formats | — | — |
| 4 | video-formats | — | — |
| 5 | image-formats | — | — |

A phase gets a Spec link once `/plan` drafts it, and a Milestone link once the
spec is merged. The milestone (open/closed + issue progress) is where status
lives.

## What each phase covers

1. **profile-registry** — Create `converter/profiles.py` as a leaf module and turn
   the ladder in `converter/jobs.py` into a generic engine driven by a profile.
   MKV-to-MP4 and Opus-to-WAV are *re-expressed* as profiles with identical
   behaviour; the existing 141 tests are the safety net. No CLI change.
2. **target-driven-cli** — `converter --to <format>` replaces the `video` and
   `audio` sub-commands, plus `--list-formats` and a reworked interactive prompt.
   Corrects the README, including the stale `develop` pull-request target. This is
   the breaking change, so it lands as 3.0.0.
3. **audio-formats** — Profiles for `mp3`, `m4a`, `flac`, `wav`, `opus`, `ogg`.
4. **video-formats** — Profiles for `mp4`, `mkv`, `webm`, `mov`.
5. **image-formats** — Profiles for `png`, `jpg`, `webp`, `avif`, `gif`, `tiff`,
   `bmp`.

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

There is deliberately no separate release or documentation phase. README changes
belong to the phase that makes them necessary — phase 2 breaks the CLI, so phase 2
fixes the README, and each coverage phase maintains its own format list. The
release itself runs through `/loopkit:ship` against `docs/release.md`.

## North star

Every format ffmpeg can write becomes one profile entry — and every loss on the
way there gets named.

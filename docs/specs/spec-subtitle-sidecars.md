# Spec: subtitle-sidecars (roadmap phase 14)

> Created: 2026-10-01

`converter --to web` writes every text subtitle stream of a source as a WebVTT
file beside the MP4, so a browser can load it through `<track>`; image
subtitles stay dropped with a note. It is the first phase where one source
writes more than one path, so the guards, the `.partial` handling and the JSON
record are widened to cover every path a source writes. This spec carries no
lifecycle state — acceptance is the spec merged on the default branch with a
milestone and issues, and all progress lives in the GitHub issues and
milestone. A completed spec is moved to `docs/specs/archive/`.

## The gap

`--to web` (phase 13) drops every subtitle stream with the note "subtitles are
not shown by a browser from inside an MP4" (`profiles.WEB`'s `subtitle` rule).
That is honest, but for *videothek* it means a film with English and German
subtitles plays with none. No browser exposes an in-band `mov_text` track as a
`TextTrack` in a plain progressive `<video>`; a WebVTT file loaded through
`<track>` works everywhere (`docs/prior-art.md`, *Subtitle sidecars for
browsers*). Today's model is one source, one output path — `paths.output_for`,
`batch.Task.dst`, one `.partial`, one `output` key in the JSON record — so a
second file per source has nowhere to go.

## Outcome

- [ ] `converter --to web` writes each text subtitle stream (a codec in
      `TEXT_SUBTITLE_CODECS`) of a source as `<stem>.<lang>.vtt` beside
      `<stem>.mp4`, where `<lang>` is the stream's normalised language tag or
      `und`; a second stream that normalises to the same language follows the
      duplicate-naming rule fixed in *Prior decisions*.
- [ ] An image subtitle stream (PGS, DVD, DVB) is dropped with a note naming
      its index, its codec and the reason; a text subtitle stream that became a
      sidecar earns no drop note.
- [ ] A sidecar that gives up styling earns a note naming the stream index, its
      codec and what was lost, per the styling-note rule fixed in *Prior
      decisions*.
- [ ] Every sidecar is written under `<sidecar>.partial` and renamed into place
      only after the MP4 conversion succeeded and was verified; every sidecar is
      renamed **before** the MP4, so an MP4 at its final path implies its run
      finished the sidecar step.
- [ ] A failed sidecar step costs no MP4: the file is still `converted`, every
      sidecar it could not write is named in a note, and its partials are gone.
- [ ] A sidecar path that already exists is never replaced without
      `--overwrite`; it is left alone and named in a note.
- [ ] An interrupted run leaves no sidecar `.partial` behind; a stale one from
      a killed run is removed by the next run that targets the same MP4, skipped
      or not.
- [ ] No sidecar path can equal another source's MP4, another source's
      sidecar, or any selected source's input path — by construction of the
      name, pinned by tests — so the collision, self-write and overwrite-hazard
      guards stay correct without knowing sidecar names up front.
- [ ] A second run over a converted tree reports 0 converted, 0 failed, exit 0
      — per the re-run rule fixed in *Prior decisions*.
- [ ] Under `--json`, a `file` record carries a `sidecars` key: `null` unless
      the outcome is `converted`, otherwise an array of
      `{"path", "stream", "language"}` objects for the sidecars actually
      written, in source-stream order. `schema` stays `1`.
- [ ] A `web` conversion spends no probe it did not spend before: the language
      tag rides phase 13's one up-front `ffprobe`. The sidecar step is one
      additional `ffmpeg` process per source with at least one text subtitle,
      and none for a source without.
- [ ] Every other target's argv, notes, probe count and JSON record (apart from
      the new `sidecars: null`/`[]` key) are unchanged.
- [ ] `docs/vision.md`, `docs/architecture.md`, `docs/design/source-selection.md`,
      `docs/design/degradation-ladder.md`, `docs/design/stream-decision.md` and
      `README.md` carry the change.

## Scope

### In scope

- **Probe** (`converter/ffmpegtool.py`): `Stream.language: str = ""`, filled
  from `stream_tags=language` added to the existing single `-show_entries`
  query (one query, one process — the same free ride `pix_fmt` took in phase
  8). Absent tag → `""`.
- **Multi-output argv** (`converter/ffmpegtool.py`): a builder for one input and
  several outputs, each with its own options, `-f` muxer and path, every path
  through `cli_path()`; `BASE_FLAGS` and `-y` as in `build_argv`, whose own
  signature and output stay unchanged.
- **Sidecar naming and sweeping** (`converter/paths.py`, pure where it can be):
  - `sidecar_language(tag) -> str`: lower-cased tag if it matches
    `[a-z]{2,3}(-[a-z0-9]{1,8})*` after lower-casing, otherwise `und`.
  - `sidecar_paths(dst, languages, suffix) -> list[Path]`: one path per
    language in order, `dst` with its suffix replaced by
    `.<lang><dup><suffix>`, where `<dup>` implements the duplicate rule.
  - `stale_sidecar_partials(dst, suffix) -> list[Path]`: the files in
    `dst.parent` whose name, case-folded, matches the sidecar grammar for
    `dst`'s stem with `.partial` appended — the one filesystem read here.
- **Profile data** (`converter/profiles.py`): a frozen `Sidecar` dataclass
  (accepted codecs, per-stream options with `{n}`-free form, muxer, suffix, the
  codecs whose styling is not carried plus the note reason) and
  `StreamRule.sidecar: Sidecar | None = None`. `WEB`'s `subtitle` rule declares
  `Sidecar(codecs=TEXT_SUBTITLE_CODECS, options=flags("-c:s webvtt"),
  muxer="webvtt", suffix=".vtt", ...)`; its `drop_reason` becomes the bitmap
  reason; its `last_resort` note no longer claims text subtitles are dropped.
- **Engine** (`converter/jobs.py`): a stream whose rule rejects it in-band
  (no copy-mask hit, no fallback) but whose `sidecar` accepts its codec is not
  mapped into the primary output and earns no drop note; `jobs.plan_sidecars
  (profile, streams)` returns the ordered sidecar streams with their options and
  styling notes, `()` for a profile without a sidecar rule.
- **Batch** (`converter/batch.py`): the sidecar step, its partials, its renames,
  its clean-up on every exit path and the existing-sidecar rule; `Result`
  gains `sidecars: tuple[WrittenSidecar, ...] = ()`.
- **Report** (`converter/report.py`): the `sidecars` key on the `file` record.
- **Registry invariants** (`tests/test_profiles.py`): a `sidecar` is declared
  only on a probe-first profile; its suffix is in no `SOURCE_SUFFIXES` and is
  no profile's `target_suffix`.
- **Docs**: the foundation carriers (authored in this spec PR, below) and
  `README.md` (`--to web`, *Machine-readable output*), the latter in the
  implementing issue.

### Out of scope

- Sidecars for any target other than `web`. The mechanism is profile data, so a
  later target can declare one; none is planned.
- OCR of image subtitles — a second dependency (`docs/vision.md`, Non-goals).
- Language-code mapping (`eng` → `en`). The tag is kept as the container wrote
  it; a table of ISO 639-2 → 639-1 codes would be curated data with no
  consumer that needs it — `<track srclang>` is the player's concern.
- Disposition flags (`forced`, `hearing_impaired`, `default`) in the file name
  or the JSON record. Additive later; not needed to load a track.
- Sidecars under `--dry-run`. Selection spends no probe, so a dry run cannot
  know a source's subtitle streams; `planned` records stay unchanged.
- Backfilling sidecars beside an MP4 converted by v3.2.0 other than through the
  re-run rule fixed in *Prior decisions*.
- Burning subtitles into the picture (`docs/prior-art.md`: AVOID).

## Constraints

- `docs/constitution.md` holds unchanged: argv lists only; paths only through
  `cli_path()`/the argv builders; every output under `<output>.partial`; one
  probe per `web` file plus the confirming one only when a structural drop is
  predicted; no stderr parsing to drive logic; functions ≤ 50 lines.
- `docs/architecture.md` boundaries: `paths` stays a leaf that knows nothing
  about ffmpeg or profiles (the suffix is a parameter); `jobs` imports only
  `profiles` and `ffmpegtool`, so naming — which needs `paths` — happens in
  `batch`; `batch` asks the engine for the sidecar plan and never reads a
  profile field to decide a conversion.
- This phase changes no target's format choice and adds no target, so the
  vision's "no diff in `cli.py`, `batch.py` or `paths.py`" criterion — which
  governs *adding a target format* — does not apply, as for phases 10-12.
  `cli.py` needs **no** diff: the guards hold by construction.
- The constitution's ladder and probe principles are untouched: the sidecar
  step runs after the ladder, from the stream list phase 13's up-front probe
  already holds.

## Prior art

- [Subtitle sidecars for browsers (Phase 14)](../prior-art.md#subtitle-sidecars-for-browsers-phase-14)
  — WebVTT beside the video through `<track>` (ADOPT); in-band `mov_text` for a
  browser and burned-in subtitles (AVOID). Jellyfin extracts subtitles in a run
  of its own, separate from the transcode — the precedent for the separate
  sidecar step.
- [Machine-readable CLI output (Phase 11)](../prior-art.md#machine-readable-cli-output-phase-11)
  — the open schema that lets the `file` record gain `sidecars` without raising
  `schema`.
- [Abort-safe writes and child-process termination (Phase 12)](../prior-art.md#abort-safe-writes-and-child-process-termination-phase-12)
  — the `.partial`-then-rename discipline the sidecars inherit.

## Human prerequisites

- none — ffmpeg 9.0 with the `webvtt` encoder and muxer is installed (measured
  below); the QA fixtures are generated with `lavfi` like phase 13's.

## Measurements (ffmpeg 9.0, this machine, 2026-10-01)

Source: an MKV with H.264, AAC, two SubRip streams tagged `eng`, one ASS stream
without a language tag.

- `ffprobe -show_entries stream=...:stream_tags=language -of json` reports
  `"tags":{"language":"eng"}` for the tagged streams and `"tags":{}` for the
  untagged one; an MP4 reports `"und"` for an untagged track.
- One ffmpeg process with three outputs —
  `-map 0:2 -c:s webvtt -f webvtt a.eng.vtt.partial -map 0:3 ... a.eng.2.vtt.partial
  -map 0:4 ... a.und.vtt.partial` — exits 0 and writes all three.
- SubRip `<i>` survives; SubRip `<font color="red">` is **dropped** (text kept).
  ASS `{\pos(..)\c&H..&}` is **dropped** (text kept). `mov_text` → WebVTT keeps
  `<i>`.

## Prior decisions

| Decision | Rationale | Date |
|---|---|---|
| **A separate sidecar step**, not extra outputs on a ladder rung: once a rung has produced the MP4 partial and its verification ran, `batch` runs **one** ffmpeg process with one output per planned sidecar (multi-output argv), reading the source again | The ladder, its argv pins and its verification stay untouched. A subtitle the WebVTT encoder rejects would otherwise fail the rung and push the video down to the last resort — a subtitle costing a re-encode. Jellyfin extracts in its own run (`docs/prior-art.md`). The cost is one more read of the source, small beside the re-encodes `web` already does and only paid when a text subtitle exists | 2026-10-01 |
| The sidecar step runs **whichever rung won** the MP4, last resort included, from the stream list of phase 13's up-front probe | Sidecars come from the source, not from the MP4; the last resort is reached only after that probe, so the streams are known. The last resort's fixed note is reworded to "...; bitmap subtitles, cover art and extra video streams dropped" so it no longer claims text subtitles are lost | 2026-10-01 |
| A sidecar may be declared only on a **probe-first** profile (registry test) | On a cheap-attempt profile a successful first attempt has no stream list, and planning sidecars would add a probe the constitution does not allow | 2026-10-01 |
| A sidecar step that exits non-zero: the file stays `converted`; **every** sidecar planned for that run is dropped with one note each — `subtitle stream <i> (<codec>) not written as a sidecar: <reason>`, where `<reason>` is the last non-empty stderr line or `exit code <n>` — and every sidecar partial is removed | The MP4 is good; failing it would throw away work over an auxiliary file. Naming each stream keeps the drop from being silent. Quoting stderr in a note is display, not logic | 2026-10-01 |
| **Rename order**: every sidecar first (each through `_rename_with_retry`), the MP4 last. A sidecar whose rename fails is dropped with a note and its partial removed; the run continues. If the MP4's rename then fails, the result is `failed` as today **and** every sidecar this run renamed into place is removed again | An MP4 at its final path is the skip signal; renaming it last makes "MP4 exists" imply "its sidecar step finished". Removing the sidecars on an MP4 failure keeps a failed source from leaving outputs a re-run would then meet as "already exists" | 2026-10-01 |
| **An existing sidecar path is never replaced without `--overwrite`**: that sidecar is not written, and the note reads `subtitle stream <i> (<codec>) not written: <name> already exists; pass --overwrite to replace it`. With `--overwrite` it is replaced like the MP4 | `docs/design/source-selection.md`'s EXISTS rule, extended to every path a source writes. An in-place run (`--to web IN IN`) puts sidecars beside the source, where a user's own downloaded `movie.eng.vtt` may already sit | 2026-10-01 |
| **Guards by construction, no diff in `cli.py`**: a sidecar's name is the MP4's name with `.mp4` replaced by `.<lang>[.<k>]<suffix>`, `<lang>` never purely numeric, `<k>` always purely numeric, neither containing `.`; the suffix is in no source-suffix set and is no target suffix | Selection has no probe (`source-selection.md`), so sidecar names cannot be known there. With this grammar, for two distinct MP4 names in one directory the dot-separated components cannot line up (a lang where the other has a number, or a different component count), so sidecars never collide with each other, never with an MP4 (`.vtt` ≠ `.mp4`), and never with a walked source (`.vtt` is no source suffix) or a named single-file source (a sidecar always has one more component than that source's stem). Case-folding preserves the argument (lang is lower-cased; MP4 names are already collision-checked case-folded). Pinned by a `paths` test over adversarial stems (`ep1` / `ep1.eng` / `ep1.eng.2` / `ep1.und`) and by the registry invariants | 2026-10-01 |
| Language normalisation: lower-case the tag; keep it if it matches `[a-z]{2,3}(-[a-z0-9]{1,8})*`, otherwise `und`. An absent tag is `und` | `und` is ISO 639-2's "undetermined", and what ffmpeg itself writes into MP4 for an untagged track (measured). The pattern admits ISO 639-1/-2 codes and BCP 47 subtags while guaranteeing no dot, no separator and never a purely numeric component — what the grammar above relies on. No `eng` → `en` mapping (out of scope) | 2026-10-01 |
| Stale sidecar partials are swept by **grammar**: at the start of every task (before the skip check, beside today's primary-partial sweep) and in the main thread's stuck-future clean-up, `paths.stale_sidecar_partials(dst, suffix)` lists matching `*.partial` files and each is removed best-effort; `batch` gets the suffix from the engine (`jobs.sidecar_suffix(profile)`, `None` → no sweep), never from the profile field | Sidecar names need the probe, which a skipped task never spends and the main thread never sees; the grammar makes the match exact for one MP4 name, so two concurrent tasks in one directory never sweep each other's partials. Satisfies the constitution's "a stale one is removed by the next run that targets the same output" | 2026-10-01 |
| Termination: after the sidecar process returns, `_raise_if_terminated` removes the MP4 partial **and** every sidecar partial of the run before raising; the outer `except BaseException` net in `_attempt_conversion` does the same | Same ownership rule as phase 12: each partial has one owner at a time | 2026-10-01 |
| A sidecar's argv: `-map 0:<index> <options> -f <muxer> <sidecar>.partial` per sidecar, all in one process; options `-c:s webvtt`, muxer `webvtt` | Measured above; `-f` is required because `.partial` defeats suffix-based muxer choice (phase 12). No `-vn`/`-an` needed: explicit `-map` selects nothing else | 2026-10-01 |
| Which streams: `codec_type == "subtitle"` and codec in `TEXT_SUBTITLE_CODECS` (`subrip`, `srt`, `ass`, `ssa`, `mov_text`, `webvtt`, `text`); every other subtitle codec takes the rule's D3 drop with reason "bitmap subtitles cannot be written as WebVTT" | Reuses the curated set MP4 and WebM already use for "is this text"; the reason replaces "subtitles are not shown by a browser from inside an MP4", which is no longer true of the streams that still reach it | 2026-10-01 |
| A source carrying only subtitle streams still ends `failed` under `web`, with no sidecar step | No rung writes an MP4, so there is nothing to put a sidecar beside; phase 13 recorded the `failed` outcome for this shape. Not special-cased | 2026-10-01 |
| JSON: the `file` record gains `sidecars` as its **last** key: `null` unless `converted`; otherwise an array (empty when none were written) of `{"path": <absolute, via Path.absolute()>, "stream": <source stream index>, "language": <normalised lang>}` in source-stream order, listing only sidecars actually written. `schema` stays `1`; `planned` and `summary` records are unchanged | The record contract is open and additive changes keep the schema (`docs/specs/archive/spec-json-output.md`). `null` for non-converted outcomes follows `attempt`'s convention: a skipped file's sidecars are unknown, and `[]` would wrongly assert there are none. Last position keeps every existing key's order | 2026-10-01 |
| Text mode prints no line for a written sidecar | A `note` line reports what was given up; a sidecar gives nothing up. Notes for styling loss, an existing path or a failed step are printed as usual | 2026-10-01 |
| `batch.Result` gains `sidecars: tuple[WrittenSidecar, ...] = ()`, `WrittenSidecar` a frozen dataclass `(path: Path, stream: int, language: str)` in `batch.py` | Value types are frozen dataclasses (`docs/constitution.md`); the default keeps every existing construction site unchanged | 2026-10-01 |
| OPEN — **naming of a second stream that normalises to the same language** (and to `und`) | resolved at the spec-acceptance gate | — |
| OPEN — **does an existing MP4 whose sidecar is missing count as done?** | resolved at the spec-acceptance gate | — |
| OPEN — **which text codecs earn a styling note** (ASS/SSA always lose positioning and colour; SubRip and `mov_text` lose `<font color>` when present, measured) | resolved at the spec-acceptance gate | — |

## Foundation impact (authored in this spec PR)

- `docs/vision.md` — Scope *In* gains "Text subtitles written as sidecar files
  next to a browser target's output". The roadmap's verdict holds.
- `docs/constitution.md` — none. Verified: no principle assumes one path per
  source; the `.partial` principle already reads "every output"; the probe
  principle is untouched (the language tag rides the existing query).
- `docs/architecture.md` — component map (`profiles` sidecar declaration,
  `paths` sidecar naming, `report` `sidecars` key); Key flow 1 gains the sidecar
  step and the rename order; Key flow 3 states that sidecars do not take part in
  the skip decision; Key flow 6 names the sidecar partials.
- `docs/design/source-selection.md` — a rule stating that the guards cover
  sidecars by construction of their name, and that an existing sidecar is
  handled per sidecar, after the ladder, not by selection.
- `docs/design/degradation-ladder.md` — the `OK` path of a sidecar-declaring
  profile passes through the sidecar step before the rename.
- `docs/design/stream-decision.md` — a `SIDECAR` outcome on the `ENC → no`
  edge; "Three outcomes, never a fourth" becomes four.

## Tracking

- Milestone: subtitle-sidecars (linked from `docs/roadmap.md`)
- Issues: created from this spec once it is merged (one per implementable step)

## Verification

- [ ] Verify passes: `.\.venv\Scripts\python.exe scripts\verify.py`, under 60 s.
- [ ] `ffmpegtool`: a stubbed probe payload with and without `tags.language`
      yields `Stream.language` `"eng"` / `""`; the probe argv pin includes
      `stream_tags=language`; the multi-output builder pins its argv for two
      outputs, dash-leading paths included.
- [ ] `paths`: `sidecar_language` for `eng`, `EN`, `pt-BR`, `""`, `"12"`,
      `"en.x"`, `"english"`; `sidecar_paths` for one, two and three same-language
      streams and mixed languages; the adversarial-stem test showing no
      sidecar of one MP4 name equals any sidecar or MP4 of another, case-folded;
      `stale_sidecar_partials` matches its own grammar and **not** `ep1.eng`'s
      partials when asked for `ep1`.
- [ ] `profiles`/`jobs`: the argv pin for a `web` source with H.264, AAC, two
      `eng` SubRip, one untagged ASS and one PGS stream — the PGS dropped with
      the bitmap note, no SubRip/ASS in the primary argv, no drop note for
      them; `plan_sidecars` returns the three text streams in order with the
      styling notes the gate fixed; registry invariants green; every other
      profile's argv pins unchanged.
- [ ] `batch` (stubbed `run`): sidecars renamed before the MP4; a failing
      sidecar step → `converted` + one note per planned sidecar + no partials;
      an existing sidecar without `--overwrite` → not written + its note, with
      `--overwrite` → replaced; an MP4 rename failure removes the sidecars
      this run renamed; termination during the sidecar step leaves no partial;
      a stale sidecar partial is swept for a skipped task; no sidecar process
      for a source without text subtitles; probe count unchanged.
- [ ] `report`: `sidecars` is `null` for skipped/failed/unsupported, `[]` for a
      converted file without sidecars, populated and last otherwise.
- [ ] QA smoke (real ffmpeg 9.0, `--ffmpeg`/`--ffprobe` absolute):
  - [ ] An MKV with H.264, AAC, two `eng` SubRip, one untagged ASS, one PGS →
        `--to web --json`: an MP4 plus three `.vtt` files named per the gate's
        duplicate rule, each a valid WebVTT that a browser `<track>` loads; the
        record lists all three; notes name the PGS drop and the styling
        losses.
  - [ ] An HEVC 10-bit source with a SubRip stream (re-encode path) → the MP4
        is re-encoded and the sidecar still written.
  - [ ] `--to web IN IN` beside a user's own `<stem>.eng.vtt` → that file is
        untouched and named in a note; with `--overwrite` it is replaced.
  - [ ] A second run → 0 converted, 0 failed, exit 0, no stray `.partial`.
  - [ ] Ctrl+C during a long run → no `.vtt.partial` remains.
  - [ ] `--to mp4` on the same MKV → output and notes unchanged from v3.2.0.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| A second read of the source on a slow disk (a Pi 4 with a USB HDD) | Only sources with a text subtitle pay it; demux-only reading is I/O-bound and far below a `libx264` re-encode of the same file. Measured at the QA gate on the Pi if it matters |
| A container whose language tag is free text (`English`) | Normalised to `und` — never a broken name; the stream index in the JSON record still identifies it |
| A Windows `TerminateProcess` kill between the sidecar renames and the MP4 rename leaves finished sidecars without an MP4 | The next run converts the MP4 and meets the sidecars as existing: kept, named in a note, content identical. Documented, not engineered away |
| Grammar sweep deleting a user's file | It only matches names ending in `<suffix>.partial` with the exact stem — a name the converter alone produces |
| The sidecar step's ffmpeg is not a ladder rung, so a future change could forget its termination check | The termination test for the sidecar step pins it |

## Decision log

- 2026-10-01: Separate sidecar step over extra outputs on the rung — a broken
  subtitle must never cost the video a re-encode; Jellyfin precedent.
- 2026-10-01: Guards by name grammar instead of probing during selection —
  selection stays probe-free (`docs/design/source-selection.md`) and `cli.py`
  needs no diff.
- 2026-10-01: Measured on ffmpeg 9.0 that one process writes several WebVTT
  `.partial` outputs with `-f webvtt`, and that SubRip colour and ASS
  positioning/colour do not survive.

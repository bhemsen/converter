# Degradation ladder

> Design artifact (`docs/design.md`, `kind: concept`). One decision per diagram;
> the per-stream branch is a separate file, `stream-decision.md`. Referenced from
> the spec of every phase that changes the ladder — reference it, never restate it.

## The decision this settles

In which order the engine tries to produce one output file, where a subprocess is
spent, and which conditions move it down a rung. The point of the ladder is that
`ffprobe` stays off the happy path of an *exhaustive* cheap attempt
(`docs/constitution.md`), so every node that costs a process call is marked —
including the one node on the success side, which only a cheap attempt the
profile declares *partial by construction* ever reaches.

```mermaid
flowchart TD
    A["Attempt 1 — the profile's cheap attempt<br/>(ffmpeg)"]
    V["verify what that mapping could carry<br/>(ffprobe — the only probe on the success side)"]
    P["describe the source's streams<br/>(ffprobe — the only probe on the failure side)"]
    PLAN["build the selective plan<br/>(no subprocess — see stream-decision.md)"]
    SEL["Attempt 2 — selective<br/>(ffmpeg)"]
    FIN["Attempt 3 — the profile's last-resort attempt<br/>(ffmpeg; a profile may declare none)"]
    OK["converted — the winning attempt's notes are reported"]
    BAD["failed — partial output removed, ffmpeg's stderr kept per rung"]

    A -->|"exit 0, and the profile declares the mapping exhaustive"| OK
    A -->|"exit 0, and the profile declares the mapping partial"| V
    V -->|"stream list — plus a note per source stream<br/>the mapping could not carry"| OK
    V -->|"probe failed — plus a note that the run is unverified,<br/>so it is not a plain success"| OK
    A -->|"exit != 0"| P
    P -->|"probe failed"| BAD
    P -->|"stream list"| PLAN
    PLAN -->|"no stream survives the profile's rules"| FIN
    PLAN -->|"the cheap attempt already selects streams explicitly<br/>and the plan gives up nothing"| FIN
    PLAN -->|"otherwise"| SEL
    SEL -->|"exit 0"| OK
    SEL -->|"exit != 0"| FIN
    FIN -->|"exit 0"| OK
    FIN -->|"exit != 0, or no last-resort attempt declared"| BAD
```

## Rules the diagram encodes

- **At most one probe per file, and none for an exhaustive cheap attempt.** The
  failure-side `ffprobe` node sits behind the first non-zero exit and is reached
  at most once; every later rung reuses the same stream list. The success-side
  node is reached only when the profile declares its cheap attempt *partial by
  construction*. The two are mutually exclusive — a file takes one path or the
  other — so no file is ever probed twice.
- **A partial cheap attempt's success is verified, not assumed.** A mapping is
  partial by construction when it can leave source streams unmapped whatever the
  source turns out to contain: MP4's `-map 0:v? -map 0:a? -map 0:s?` selects no
  attachment and no data stream, WAV's `-map 0:a:0` selects no second audio
  stream. The profile declares this as data, exactly as it declares whether the
  attempt is stream-explicit — the engine never parses an option list to find
  out. The verification consults only the *structural* verdicts of
  `stream-decision.md` — is there a rule for this stream's type, and is the
  container already holding as many of that type as it can — never a codec-level
  one: ffmpeg exited 0, so whatever the attempt did with a codec worked, and
  naming a re-encode that never ran would trade one dishonest report for another.
- **What a partial profile owes in exchange.** Reading the declared rules instead
  of the option list is sound only while the rules and the mapping agree, so a
  profile that sets `partial_mapping` must satisfy both halves of this. A new
  profile that cannot is the bug — not the verification.
  1. **A rule for every stream type its cheap attempt maps.** Otherwise the
     verification announces a drop that never happened. A profile that carries
     attachments with `-map 0:t?` has to declare an `attachment` rule, or every
     font it faithfully copied is reported as lost.
  2. **No `stream_limit` on a type its cheap attempt selects blindly.** A blind
     `-map 0:a?` maps *every* audio stream, so a limit the mapping does not
     enforce would have the verification report surplus streams the output does
     contain. A limit belongs to a type the cheap attempt names by index (WAV's
     `-map 0:a:0`) or does not map at all.

  The two shipped profiles satisfy both by construction — MP4's selectors match
  its three rules exactly and it declares no limit, WAV names one audio index and
  limits audio to 1 — and `tests/test_profiles.py` checks the pair per profile
  rather than leaving it to review.
- **Cheapest first.** Rung 1 is whatever the profile declares as its cheap attempt:
  a *blind* stream copy for a container that can hold the source codecs
  (`-map 0:v? -map 0:a? ...`), or a *stream-explicit* selection where it cannot
  (`-map 0:a:0 ...`). Which of the two it is, the profile declares — the engine
  never parses an option list to find out.
- **The selective rung is skipped when it would add nothing.** Two conditions do
  that. Nothing survives the profile's rules, so there is no command to build. Or
  the profile's cheap attempt is stream-explicit *and* the plan gives up nothing
  worth naming — then the rung would be a second, equivalent ffmpeg run. A profile
  whose cheap attempt is blind always gets the rung: the explicit per-stream
  mapping is exactly what can rescue a file the blind copy could not.
- **The last rung is optional.** A container that can always be reached by a full
  re-encode declares one; a container with nothing further to give up (WAV) does
  not, and a failure at the rung before it is then the end of the ladder.
- **Every rung carries its own notes.** The notes of the attempt that actually
  succeeded are what the batch reports — the discarded rungs' notes are not. Only
  the cheap attempt's notes are ever added to, and only by the verification node
  above it; a later rung was built from the stream list itself, so its notes are
  already complete and it is never verified a second time.
- **Container-wide options are appended by the engine, once, at the end of every
  attempt.** The profile declares them in one place instead of repeating them in
  each attempt it declares.

# TRACE_ACTIVITY_CONTRACT.md — What the shim must fabricate for trace/console

> ## ⚠ READ BEFORE CHANGING ANYTHING
> **This spec may be out of date, and may be MISSING decisions that were made
> but never written down.** A spec can tell you what to **build**. It NEVER, on
> its own, authorises **undoing** something that already works.
>
> If the code does something this document doesn't mention, that is most likely
> a real decision — check `git log -S "<the thing>"` first, then **ASK JEREMY**.
> **Never delete working behaviour without his explicit go-ahead.** (Removing
> genuinely dead code is fine.)
>
> Standing decisions that outrank this document: **[HARD_RULES.md](HARD_RULES.md)**

**Status:** Draft 2 — ALL §1-§5 TO-VERIFY items resolved 2026-07-19 (verification
pass; every claim now cited). Originally Draft 1 2026-07-10, mining `reference/webCoRE-hubitat-patches-extracted/`
(the ady624 Hubitat fork, "Last update July 5, 2026 for Hubitat" — confirmed correct fork
per `SESSION_BRIEF_HUBITAT_MINING.md` Step 0).
**Scope:** the DATA CONTRACT the dashboard's piston view consumes for its trace/console —
not how Hubitat executes pistons. What the shim must eventually fabricate (real HA data
where possible), and what compiled PyScript must eventually emit, for the trace/console to
light up. No shim code changes in this session (research-only per the brief).
**Tagging:** `VERIFIED-HE-GROOVY` (this Hubitat fork, file:line) / `VERIFIED-JS` (dashboard
consumer) / `TO VERIFY` / `ASSUMED`.

---

## 1. `intf/dashboard/piston/activity` response shape

**VERIFIED-HE-GROOVY** — `webcore-piston.groovy:1190-1214`, `Map activity(lastLogTimestamp)`:

```
{
  "name":       <piston name — sNM>,
  "state":      <state blob — sST, see §3>,
  "logs":       [ <log entry, see §2>, ... ],   // only entries AFTER lastLogTimestamp
  "trace":      <trace blob — sTRC, see §4>,
  "localVars":  <piston-local variables map — sLOCALV, from state's "vars">,
  "memory":     <memory usage — sMEMORY>,
  "lastExecuted": <epoch ms — sLEXEC>,
  "nextSchedule": <epoch ms — sNSCH>,
  "schedules":  [ <list> — sSCHS ],
  "systemVars": <system vars cache — sSYSVARS, from "cachePersist">
}
```

Note the doc comment at the source: `// not reporting global or system variable changes` next
to `localVars` — global/system variable CHANGES are deliberately excluded from per-activity-
poll payloads; only piston-LOCAL variable state is included here. (Globals are fetched via
`load`'s `instance.globalVars`, not via `activity`.)

`lastLogTimestamp` semantics — **VERIFIED-HE-GROOVY :1196-1204, RESOLVED:** the `t`
field lives on RUN-HEADER entries, not message entries. Every execution seeds its log
buffer with `[[t: <runStartTime>]]` (:2567, re-seeded :2608), then pushes `{o,p,m,c}`
message entries after it. Pagination is therefore per-RUN: `activity()` finds the header
whose `t` == lastLogTimestamp and returns `logs[0..idx-1]` — everything BEFORE the match
in a newest-first list, i.e. all runs newer than the client's last-seen run.
`lastLogTimestamp=0` returns the whole buffer (idx=size); non-zero with no match returns
`[]`. The shim replicates this by stamping one `{t}` header per compiled-piston
execution — the shim owns the timestamp, nothing to copy from Hubitat internals.

## 2. Log entry shape

**VERIFIED-HE-GROOVY** — `webcore-piston.groovy:13288`, the log-push call site:

```
{
  "o": <elapsed time since piston start — elapseT(timestamp)>,
  "p": <padded prefix string — indentation/level marker for nested log display>,
  "m": <message string, truncated to 1024 chars with "...[TRUNCATED]" suffix if longer,
        CRLF-normalized to \r, split into multiple entries on \r if untruncated>,
  "c": <mcmd — the log command/category, e.g. error/warn/info/debug/trace level markers>
}
```

Entries are capped per-piston at a configurable limit (`sMLOGS`, minimum 50) — oldest
entries silently stop accumulating once the cap is hit for that execution's log buffer, not
a rolling window (`webcore-piston.groovy:13282-13291`).

**RESOLVED (see §1):** `t` never appears on message entries — it is the per-run header
entry's key. Two entry shapes total: `{t}` (run header) and `{o,p,m,c}` (message).

## 3. Piston state blob (`state` / `sST`)

**VERIFIED-HE-GROOVY :1219-1237 (`curPState()`, the parent-served per-piston meta):**
`{a: active, c: category, t: lastExecuted, m: modified, b: bin, n: nextSchedule,
z: description, s: <state map minus its 'old' key>, heCached}` — the meta shape the shim
already fabricates for the piston list, plus `s`. The `s`/`sST` blob is a pass-through
map (the piston-state display setState writes); the runtime keeps current+previous
internally and strips `old` before serving — the shim serves current-only. PistonCore
source: the compiled piston's persisted `pyscript.pistoncore_<id>_state` entity
(setState already writes it today).

## 4. Trace storage (`trace` / `sTRC`)

**VERIFIED-HE-GROOVY — write sites found and traced:**
- Init per run (:2611): `trace = {t: <run timestamp>, points: {}}`
- Total duration added at run end (:3531): `trace.d = <elapsed ms>`
- Per-node writes via `tracePoint(r9, oId, duration, value)` (:13388-13394):
  `points[<oId>] = {o: <ms offset from run start, minus duration>, d: <duration ms>,
  v: <evaluated value>}` — **keyed by the node's `$` id** (oId is the statement/
  condition id; ids confirmed stable per PISTON_JSON_REFERENCE §8).
Full contract: `{t, d, points: {"<$id>": {o, d, v}, ...}}` — this is what paints the
dashboard's per-statement trace overlay (evaluation dots/timings on the piston code).
A compiled PyScript piston can emit exactly this: stamp t at wake, collect
(id, offset, duration, value) per executed statement, hand the blob to the shim.

## 5. Cross-check against the dashboard consumer

**VERIFIED-JS — piston.module.js:164-181, the activity poll handler consumes:**
`state, logs, trace, localVars, memory, lastExecuted, nextSchedule, schedules, name,
globalVars, systemVars` — a 1:1 match with §1's keys plus `globalVars`/`systemVars`,
which are OPTIONAL (guarded ifs; the Hubitat backend does not send globalVars in
activity and the dashboard tolerates absence). Log delivery detail (:167): new logs are
**prepended** (`concat($scope.logs)`) — confirms newest-first ordering end to end.
Minimum viable contract for a live status page: `state, logs, lastExecuted,
nextSchedule` — everything else can arrive incrementally.

## 6. Feasibility for compiled PyScript (facts only, no design decisions)

- `logs`: straightforward — PyScript can emit `{o, p, m, c}`-shaped entries to a ring buffer
  the shim reads. The `t` field's exact source is the one open unknown (§1/§2); without it,
  the shim can substitute a wall-clock timestamp at write time rather than replicating
  whatever Hubitat's original transformation does — behaviorally equivalent for pagination
  purposes as long as the shim, not PyScript, owns writing `t`.
- `state`/`trace`: cannot assess feasibility until their write sites are traced (§3/§4 TO
  VERIFY) — deferred to a follow-up session.
- `localVars`/`systemVars`/`schedules`/`lastExecuted`/`nextSchedule`/`memory`: all facts a
  compiled automation's own execution context could report if the compiler/runtime chooses
  to track them; no blocker identified this session.
- **Bottom line (updated 2026-07-19): every shape is verified — the implementation
  session can be brief-driven on cheap tokens.** PistonCore data sources per key:
  `state` from the persisted `pyscript.pistoncore_<id>_state` entity (setState writes it
  today); `lastExecuted`/`logs` from a per-piston shim-readable log the PyScript band's
  existing log.info breadcrumbs graduate into (`{t}` header + `{o,p,m,c}` entries, shim
  owns `t`); YAML-band `lastExecuted` from the automation entity's `last_triggered`;
  `nextSchedule` from HA's next trigger time where derivable (timers), else 0;
  `trace.points` from a tracePoint-equivalent helper the piston template already has
  hooks for (stmt ids ride the kwargs today); `memory` cosmetic, serve "unknown".

## 7. Summary for Jeremy (plain language)

- Fully nailed down as of 2026-07-19: EVERYTHING. The activity response, both log entry
  shapes (run header + message), the per-run pagination trick, the piston-state blob, the
  full trace format (per-statement `{o,d,v}` keyed by the same `$` ids the compiler
  already stamps on triggers), and exactly which keys the dashboard reads. The status
  screen's live half (Quick Facts + logs + trace overlay) can now be built against
  verified shapes with zero guessing — and it does NOT need a top-tier model session.
- Nothing here contradicts anything already shipped (milestones 1-3). No shim bugs found in
  this pass — this was purely additive research.
- `openWebSocket` (a separate open item, §B3 below): confirmed dead — the self-hosted
  Hubitat backend has **zero** websocket code. It's cloud-only (`api-us-*.webcore.co:9297`,
  the commercial webcore.co relay), so the dashboard already has to tolerate it being
  absent for any self-hosted install. Nothing to build.

## 8. YAML-band live feedback (IDEA — Jeremy, 2026-07-26; NOT BUILT, NOT DESIGNED)

**The gap this addresses.** Everything above (§4, §6) assumes per-statement trace is a
PyScript-band capability: the compiled piston reports its own execution. The YAML band gets
exactly ONE key out of that — `lastExecuted`, read from the automation entity's
`last_triggered` (§6). So a YAML-compiled piston's status/view page in the dashboard is
effectively DEAD while open: no logs, no trace overlay, no sign it did anything. Since YAML
is the default target (YAML-first is a day-one rule; PyScript is the valve), the majority of
pistons land on the blind path.

**Jeremy's idea.** While a piston is open on the dashboard's status/view page, the shim
watches Home Assistant's OWN live record of that automation and turns it into the log/
activity entries the dashboard already knows how to render (§1, §2). Not a reimplementation
of the webCoRE engine's trace — an APPROXIMATION assembled from what HA already stores, so
the open page shows real signal ("triggered at …", "condition met", "turned on X") instead
of nothing.

**Candidate sources — TO VERIFY, none confirmed this session:**

| Source | What it could give | Notes |
|---|---|---|
| **HA automation traces** | Per-run detail: which trigger fired, condition results, which actions ran, timings, changed variables | Richest by far. Believed reachable over the websocket connection the shim already opens (`trace/list` / `trace/get`). **TO VERIFY:** exact payload shape, retention/limits, whether script-kind output traces the same way. |
| **Logbook** | Coarse "automation triggered" + resulting device state changes | REST, simple, low fidelity. Useful fallback if traces don't pan out. |
| **`last_triggered`** | Timestamp only | Already used for `lastExecuted` (§6). No per-run detail. |

**The open question that decides the ceiling (TO VERIFY).** HA's trace entries identify
steps by their position/path in the emitted automation. The compiler already stamps piston
statement (`$`) ids on triggers, and §4's `trace.points` is keyed by exactly those ids. IF
emitted YAML steps can be mapped back to the statement ids that produced them, this stops
being a coarse feed and becomes a real per-statement trace overlay for the YAML band —
the same surface §4 assumes only PyScript can paint. If they can't be mapped, it degrades
to the coarse log feed, which is still a large improvement over a dead page.

**Explicitly NOT decided:** whether this polls or pushes, how often, whether it runs only
while a piston page is open, retention, or what happens for a piston compiled to several
automations (TCP scoping, COMPILER_SPEC §2.5). No design work has been done — this section
exists so the idea isn't lost, per the authority chain (an idea captured is not a spec'd
decision).

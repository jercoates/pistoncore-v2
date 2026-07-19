# TRACE_ACTIVITY_CONTRACT.md — What the shim must fabricate for trace/console

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

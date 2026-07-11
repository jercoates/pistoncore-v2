# TRACE_ACTIVITY_CONTRACT.md — What the shim must fabricate for trace/console

**Status:** Draft 1 — research session, 2026-07-10, mining `reference/webCoRE-hubitat-patches-extracted/`
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

`lastLogTimestamp` semantics (`webcore-piston.groovy:1196-1199`): if the client passes a
valid timestamp, the function finds the log entry with a matching `t` and returns only logs
AFTER it (or all logs if no match/first call with `lastLogTimestamp=0`). **TO VERIFY**: the
log-push site found (§2) does not set a `t` field on the entry — likely added by a
transformation step between execution-time logging and the cached `activity` map this
function reads (`getCachedMaps('activity')`); not traced further this session.

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

**TO VERIFY:** the `t` (absolute timestamp) field `activity()`'s pagination logic depends on
(§1) — not present at the push site; likely populated when the log buffer is written into
the cached `activity` map. Needs a further trace before the shim can replicate log
pagination correctly.

## 3. Piston state blob (`state` / `sST`)

Referenced but not fully traced this session (`mMs(t0,sST)` in `activity()`,
`curPState()`'s `s: st` with `st.remove(sOLD)` — a stale/previous-value key gets stripped
before serving). **TO VERIFY**: full key set of this map. `curPState()`'s removal of an
"old" key suggests the live runtime state tracks both current AND previous values
internally, and only current is served.

## 4. Trace storage (`trace` / `sTRC`)

Referenced (`mMs(mst,sTRC)` at both `activity()` and `piston.get()`) but not traced to its
write site this session. **TO VERIFY**: exact per-node record shape, whether keyed by the
`$` node id (PISTON_JSON_REFERENCE.md §8 — confirmed this session that `$` ids are stable,
assigned only to nodes missing one, never renumbered — see PISTON_JSON_REFERENCE.md §8
update), and what per-node fields it carries (last-evaluated value, timing, hit count,
etc.). Needs a dedicated follow-up trace of wherever `sTRC` gets written during piston
execution (not reached in this session's time budget).

## 5. Cross-check against the dashboard consumer

Not completed this session (piston.module.js's activity-polling/trace-rendering code was
not re-read against these specific fields this pass — prior sessions already read
`piston.module.js:234-290`'s `init()` for the adjacent `piston/get` fields, see
SHIM_API_SPEC.md §4.5). **TO VERIFY** next: which of §1's response keys the dashboard's
activity poller actually reads vs. ignores, to scope the minimum viable contract.

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
- **Bottom line:** logs are ready to design now; state/trace need one more focused
  extraction pass (their write sites, not just their read/serve sites) before the compiler
  can commit to a trace strategy.

## 7. Summary for Jeremy (plain language)

- Fully nailed down: what `piston/activity` returns overall, and the shape of one log line
  (indentation, message, truncation-at-1024-chars, category). Good enough to build the logs
  half of a status page against real data shapes, not guesses.
- Not yet nailed down: the exact "state" and "trace" blobs — I found where they're *read*
  from but not where they get *written* during execution, which is the half that actually
  matters for designing what compiled PyScript needs to emit. That's real, scoped follow-up
  work, not a blocker discovered in what's already built.
- Nothing here contradicts anything already shipped (milestones 1-3). No shim bugs found in
  this pass — this was purely additive research.
- `openWebSocket` (a separate open item, §B3 below): confirmed dead — the self-hosted
  Hubitat backend has **zero** websocket code. It's cloud-only (`api-us-*.webcore.co:9297`,
  the commercial webcore.co relay), so the dashboard already has to tolerate it being
  absent for any self-hosted install. Nothing to build.

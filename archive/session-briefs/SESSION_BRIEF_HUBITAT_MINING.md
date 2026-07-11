# SESSION BRIEF — Mine the Hubitat webCoRE sources (research session)

## Session type: RESEARCH ONLY
This session reads reference code and updates spec documents. **No shim code changes** —
if you find a bug this research exposes, note it in the summary and stop; fixing it is a
separate session with its own plan stop. New-file approval is pre-granted for exactly one
file: `TRACE_ACTIVITY_CONTRACT.md` (repo root, alongside the other specs). Any other new
file: name it and wait for approval per CLAUDE.md.

## Step 0 — Verify inputs
Confirm these exist in `reference/` (Jeremy downloaded them from
github.com/imnotbob/webCoRE, branch `hubitat-patches`):
- the Hubitat main app groovy (webcore.groovy from the fork)
- the Hubitat piston/engine groovy (webCoRE-piston.groovy or similar)
If either is missing, or the file headers don't identify as the imnotbob Hubitat fork,
STOP and tell Jeremy which file is missing/wrong before doing anything else.
The mainline SmartThings app (`webcore_source_reference.groovy`) is already present —
use it for cross-platform comparison, and keep platform attribution straight in every
finding: tag `VERIFIED-HE-GROOVY` (Hubitat fork) vs `VERIFIED-GROOVY` (mainline), always
with file + line refs.

## Extraction targets

### A. The trace/activity contract → new doc TRACE_ACTIVITY_CONTRACT.md
The goal is the DATA CONTRACT the dashboard's piston view consumes — not how Hubitat
executes pistons. We need what the shim must eventually fabricate (and what compiled
PyScript must eventually emit) for the trace/console to light up.
1. `activity()` in the piston groovy: the exact response object of
   `intf/dashboard/piston/activity`. Every key, with types and meaning (logs, trace,
   state, timing, globalVars merge — whatever is actually there).
2. Log entry shape: find the internal logging functions; document one entry's fields
   (timestamp, level, message, anything else).
3. Trace storage: search for trace writes keyed by node `$` ids — per-statement /
   per-condition evaluation records, timing values, whatever the trace view renders.
4. Cross-check against the dashboard consumer: piston.module.js's activity handler and
   trace rendering — confirm which served keys the dashboard actually reads (that's the
   minimum viable contract; note keys it ignores).
5. End the doc with a short feasibility section: given this contract, what would compiled
   PyScript need to emit per statement for trace to work? Facts only, no design decisions.

### B. Resolve existing TO VERIFY items — update the specs in place
Mark each finding with its tag + line ref, and flip the item from TO VERIFY to VERIFIED
(or document that the Hubitat fork differs). Do not silently rewrite decided content.
1. **PISTON_JSON_REFERENCE.md §8:** `$` id assignment — find where setup/save stamps ids
   onto nodes (rule, starting value, renumber-or-preserve behavior). Also §10.5: whether
   the engine strips the editor's `exp` caches.
2. **SHIM_API_SPEC.md §5.2:** piston `meta` keys (the per-piston state blob in the
   instance payload — active/paused, last run, next run, etc.). Also §4.6 pause/resume
   response keys, §4.7 set.end "saved" extra keys, §4.3 refresh/getDashboardData shape
   on Hubitat, §4.9 backup envelope.
3. **SHIM_API_SPEC.md §2 / open item:** `openWebSocket` — what the Hubitat backend serves
   for the dashboard's websocket live-update channel; is it optional (dashboard degrades
   without it)? Recommendation: stub vs ignore.
4. **DEVICE_PAYLOAD_SPEC.md open items 3:** device serialization on Hubitat —
   `c[].p` element type (names vs types), and the device-level `o` map (custom command
   labels) the dashboard reads at piston.module.js:2664.
5. **DEVICE_PAYLOAD_SPEC.md Stage 3 amendment support:** confirm the Hubitat app
   serializes `getSupportedAttributes()` straight off the driver — i.e., driver-reported
   attributes appear in `a` whether or not the vocab db knows them (this is the
   pass-through-lane justification; Jeremy's cameras' smartDetectType is the motivating
   case).
6. **PISTON_JSON_REFERENCE.md §10.2:** in the db construction, which field marks a
   comparison as trigger-type vs condition-type (check both platforms).
7. **hashId:** confirm the Hubitat fork uses the same `:md5("core."+id):` formula.

## Output rules
- Findings go INTO the existing spec docs at the marked TO VERIFY spots (plus the one new
  contract doc). Keep the VERIFIED/ASSUMED/DECISION tagging convention.
- Where Hubitat and mainline differ, record BOTH with platform tags — the shim follows
  Hubitat (the dashboard runs in 'he' mode).
- Quote reference code sparingly (a line or a signature), reference by file:line
  otherwise.
- End with a plain-language summary for Jeremy in behavior terms: what got resolved, what
  the Hubitat fork does differently, whether trace-on-HA looks feasible, and what (if
  anything) this research says the shim currently does wrong — as notes, not fixes.

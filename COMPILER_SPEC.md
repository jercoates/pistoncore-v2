# COMPILER_SPEC.md — PistonCore v2 Compiler

**Status:** Draft 1 (skeleton + decisions, 2026-07-13). Sections marked [FILL] are
structure-complete but content-light; each names its source doc so ANY session (or model)
can fill it without re-research. Sections marked DECIDED carry Jeremy's settled call: do not silently drift from them or
"improve" them mid-session — but they are NOT immune to evidence. If implementation,
testing, or research contradicts a DECIDED item, STOP, present the evidence to Jeremy,
and he re-decides. (Precedent: packages-vs-includes was reversed by one research pass.)
Decided ≠ frozen; it means changing it requires Jeremy, not that it can't change.
**Authority:** Subordinate to PISTON_JSON_REFERENCE.md (input format is law) and the
webCoRE sources. Consumes research from: WEBCORE_HA_BEHAVIOR_MAP.md,
HA_YAML_COMPILER_RESEARCH.md, PYSCRIPT_COMPILER_RESEARCH.md, HA_LIMITATIONS.md.
Decisions inherited from COMPILER_DECISIONS_HOLDING.md (§A–§H) and
COMPILER_DECISIONS_DEPLOY.md — restated here; on conflict, this doc wins once accepted.
**Tagging:** VERIFIED (source+date) / ASSUMED / TO VERIFY / DECISION (who, when).

---

## 1. Mission and non-negotiable policy (DECIDED — from holding doc §A)

The compiler turns saved webCoRE piston JSON into things Home Assistant executes natively.
It replicates the **intent** of the piston, not webCoRE's architecture. There is no engine.

- **Read-only compiler.** Never mutates piston JSON, vocab, or translation files. Ever.
- **Errors go to the debug page** (piston + statement `$` id + plain-English reason).
  Never mutation, never partial/placeholder output, never TODO comments in deployed YAML
  (considered and REJECTED — a deployed automation that silently skips an action is worse
  than a visible compile failure).
- **Jinja2 everywhere:** all emission goes through editable template files + JSON maps in
  the customize volume. No hardcoded YAML/Python strings in compiler code. This is the
  breaking-change insurance (Recompile All, §10).
- **One canonical variable-substitution function.** All text interpolation flows through it.
- **YAML-native is the primary target; PyScript is the routed exception** (§5) plus an
  optional user preference ("prefer PyScript for fidelity", settings).

## 2. Input contract [pointer section — content lives elsewhere]

- Format: PISTON_JSON_REFERENCE.md (certified against editor source + live captures).
- Trigger identification: node-level `ct` ("t"/"c") and `s` (subscription) fields when
  present (engine-saved pistons); DERIVED from the comparisons vocab buckets
  (`comparisons.triggers{}` vs `.conditions{}`) when absent (imported/AI-authored pistons).
  Vocab is authority on disagreement. [VERIFIED — capture 2026-07-12 + HE groovy]
  **UPDATE 2026-07-17: the SHIM now stamps `ct`/`s` at save** (`storage.
  classify_conditions()`, replicating the engine's verified classification+promotion rule
  — the editor itself never writes them, proven by a hand-authored round-trip). So
  shim-saved pistons ALWAYS carry them; the derive-from-vocab fallback remains only for
  raw pastes that bypass a save. Same stamping feeds `piston/get`'s `subscriptions`
  counts (Quick Facts / no-subscriptions banner now engine-equivalent).
- Scope: the 84-piston corpus (`test-pistons/`) defines v1 requirements: statement types
  {if, action, each, while, repeat, do, group}, 22 comparisons, ~70 commands, 12 system
  vars (PISTON_JSON_REFERENCE §8b). Types outside the corpus (for, switch, on, break,
  exit) are spec'd but lower priority; `break` and `on` force PyScript anyway (§5).

## 2.5 Semantic model — how a piston means

Source: `reference/webCoRE-hubitat-patches-extracted/webCoRE-hubitat-patches/smartapps/
ady624/webcore-piston.src/webcore-piston.groovy` (the real engine, 14,566 lines, terse/
abbreviated naming — traced by following descriptive comments to their functions, not by
guessing function names). This section documents how webCoRE actually executes, because
intent = what the user learned to expect from that execution. It is the baseline everything
in §3 compiles against.

**Status: all 6 points VERIFIED with line citations below, 2026-07-15 (point 2's
implicit-subscription rule verified; its mixed-if-block claim is reasoned/
architecturally-implied, not independently re-traced at the per-node level — flagged
inline; point 6 scoped per the brief's own note, not the whole expression language).
§2.5 is complete. §3.0 (corpus-mined intent-pattern catalog) is the remaining piece before
this pipeline stage is done — separate pass, not started.**

1. **The event loop (VERIFIED).** Every event — device state change, timer fire, manual
   test, resume/pause/clear-cache commands — funnels through one dispatcher,
   `handleEvents()` (line 2849), reached via `commonHandle()` (2751) for non-device events
   and directly for device events. Events are **serialized per piston** via a semaphore
   (`lockOrQueueSemaphore`, 2884) — a piston processes one event at a time; concurrent
   events queue, they do not run in parallel. If the piston is paused (`!isAct`) or killed
   (`!isEnbl`), execution aborts before touching the statement tree (2923-2934) — pause
   stops all processing, not just scheduling. For a normal (non-resumed-schedule) event,
   `executeEvent()` (3298) calls `executeStatements(r9, piston.s)` (3472) exactly once —
   this is the literal "evaluates top-to-bottom in ONE pass" — which is a plain sequential
   `for` loop over the statement array (3852), calling `executeStatement` on each in order
   and **short-circuiting** (stopping the whole pass) the moment one returns false (3859-
   3863). Resumed scheduled tasks (delayed waits, repeats, device timers) do NOT re-run
   from the top — `currun(r9)`/`chgRun()` (3880-3885) and a fast-forward flag (`ffTo`) skip
   forward through the tree without executing branches until reaching the matching
   statement id, then resume normal execution from there (3922-3924, `pushStk`/`popStk`
   3893-3910 track exact tree position for this).

2. **Implicit subscription promotion (VERIFIED).** `subscribeAll()` (line 8741) builds the
   subscription set per condition node. The precise rule (9278/9296):
   `cndtn[sS] = subscribeMethod != "never" AND (ct=="t" OR subscribeMethod=="always" OR
   !hasTriggers)`. So a condition subscribes (drives event wake-up) if it's explicitly
   trigger-classified (`ct=="t"`), OR its own subscribe-method override says "always", OR —
   the implicit rule — **the piston has NO trigger-classified conditions anywhere at all**
   (`!hasTriggers`), in which case EVERY condition gets promoted to subscribe. The engine's
   own debug string names this outright: `'no triggers, promoting conditions'` (9242).
   Confirms the brief's triggerless-piston claim exactly. Independent bonus find at 9277:
   `isSkipA = a in [lastActivity, status, roomId, roomName]` — these four attributes are
   hardcoded as never generating subscribable events at all, in the real engine itself —
   cross-confirms this session's separate finding (from the HA side) that Hubitat's
   room/last-activity metadata isn't a normal subscribable device attribute.
   **Mixed if-block "trigger AND condition currently holds" — REASONED, not independently
   re-verified at the per-node level.** Architecturally implied by points 1+3 combined
   (subscriptions from trigger-classified nodes determine WHEN the piston wakes;
   `evaluateCondition` then reads live/cached state for EVERY node in the group uniformly,
   trigger-classified or not, combined via the group's and/or/xor — no special-casing found
   between trigger and condition nodes at evaluation time). Have NOT independently traced
   whether a trigger-classified condition, when evaluated, additionally requires itself to
   be the specific device that just changed (vs. any condition just reading current state)
   — worth a targeted follow-up if this distinction ever matters for a specific compile
   case, but not blocking: the architecture as traced is sufficient to compile against.

3. **Truth-change semantics (VERIFIED).** Condition results are cached per condition-group
   (keyed by a collection id) across evaluation runs. On each evaluation: `oldResult` = the
   previously cached boolean for this exact condition group; `a = (oldResult != res)`;
   `r9[sCNDTNSTC]` ("condition state changed") `= a` (line 7460-7468, `evaluateConditions`
   region) — **this is a genuine edge detector** (fires only on a flip), not a level check
   re-evaluated as "true." The piston-level counterpart (`sPSTNSTC`, "piston state
   changed") is set elsewhere (5599) — not yet traced to its own precise rule. Both flags
   feed **TEP** (Task Execution Policy, a per-statement `tep` field: blank = always execute;
   `"c"` = only if condition state changed; `"p"` = only if piston state changed; `"b"` =
   either) — `executeStatement()` (3921-3954) checks TEP before running a statement's body
   at all, skipping it silently (returns true, does not stop the pass) when the policy's
   condition isn't met. This is the exact mechanism `ts`/`fs`-triggered actions and
   if-block re-execution gating are built on.

4. **TCP (Task Cancellation Policy) — VERIFIED, complete.** The full `tcp` value set, from
   an authoritative code comment (line 4605): `""` (blank) or `"c"` = cancel on CONDITION
   state change (**the default**), `"p"` = cancel on PISTON state change, `"b"` = cancel on
   EITHER, `"n"` = NEVER cancel. Mechanism: `svCS()` (4604) attaches the current
   condition-stack context to a scheduled task only when tcp is `b`/`c` (`ListBC`, line
   1536) — that task then gets cancelled specifically by `cancelConditionSchedules()` when
   THAT condition's cached truth value flips (point 3's edge detector, line 7469-7470).
   `svPS()` (4611) attaches a piston-state-change flag only when tcp is `b`/`p` (`ListBP`,
   1537). **Cancellation is scoped to the specific condition/statement that owns the
   scheduled task, never global-per-piston** — there is no single "cancel everything in
   this piston" switch; each condition group is its own independent cancel-on-retrigger
   unit.
   **`mode: restart` verdict (evidence-based, resolves SPEC_ADDENDA_GEMINI.md item 1 as a
   PARTIAL match, not a clean one):** HA's `mode: restart` cancels the ENTIRE automation
   run on any new trigger — that's closest to webCoRE's tcp default (`c`) or `b`, but ONLY
   when a compiled automation contains exactly one independent condition-scoped TCP unit.
   A piston with multiple independent timed branches bundled into one automation would have
   `mode: restart` over-cancel (killing unrelated branches' pending tasks that webCoRE's own
   per-condition scoping would have left alone) — confirms the addenda's own caution
   verbatim, now with a concrete mechanism behind it: **one-automation-per-condition-group
   is what would make `mode: restart` exact; bundling condition groups into one automation
   is what breaks it.** tcp=`"n"` (never cancel) and tcp=`"p"` (piston-only) have no
   `mode: restart` equivalent at all — those need explicit `task.unique`-style handling
   (PyScript) or a mode other than `restart`.

5. **Async flag, loop/schedule constructs, exit — VERIFIED (line 3973-4280 region, the
   `executeStatement` switch).**
   - **Async (`a` field, line 3973):** a statement runs async if its own `a` field equals
     `1`, OR its statement type is unconditionally async regardless of the field
     (`are_async = [EVERY, ON]`, line ~3917). Both EVERY and ON are always-async
     constructs; other types are async only when explicitly flagged.
   - **`if`/`while` share the same evaluation code** (literal case-fallthrough, `case sIF:
     isIf=true; case sWHILE:` — no break between them, line 3994-3996): both evaluate the
     same condition-check; `if` runs it once, `while` re-runs it in a loop
     (`while(repeat){switch(stateType){...}}`) until the condition evaluates false.
   - **`if`'s truth value becomes the piston's automatic state** (line 4001-4004): the
     FIRST top-level if-statement's result is written to `r9.st.autonew` (unless overridden
     by an "MPS" option) — this is where "piston state" (the `p` value in TEP/TCP) actually
     comes from by default; it isn't an abstract flag, it's literally the first if-block's
     outcome.
   - **`every` (line 4059-4088) only runs its body on its OWN scheduled timer event**
     (`ownEvent` = a TIME event whose schedule id matches this exact statement), but
     **unconditionally re-registers its timer every run regardless of whether it fired**
     (`scheduleTimer(...)`, always called). **`every` always terminates the piston run
     immediately after its block, whether the timer fired or not** (`r9.term=true`,
     "Exiting piston at end of Every timer block") — nothing after an `every` statement in
     the same statement list ever executes in that run. Compiler consequence: `every`
     cannot be treated as "just another statement in sequence" — it's a hard stop.
   - **`repeat` (line 4089-4099) runs its body ONCE per invocation, not as a synchronous
     loop** — it executes its statements once, then evaluates its condition to decide
     whether to schedule ANOTHER future invocation (ties into `qrunRepeat`/`svCS`,
     §2.5 point 4's TCP mechanism — each repeat cycle is its own scheduled re-entry,
     cancelable like any other scheduled task). Compiling `repeat` as a tight in-process
     loop would be wrong; it's closer to a self-rescheduling delayed action.
   - **`on` (line 4100-4133) matches a specific event, not a truth value** — checks whether
     the CURRENT triggering event matches one of its declared event conditions (device+
     attribute name, virtual device, or custom `x`-event), by identity, not by evaluating
     current state. Genuinely different semantics from `if`/`while`'s condition evaluation.
   - **`each`/`for` share code** (same fallthrough pattern, line 4134-4136). `each`
     evaluates its device-list operand ONCE at loop entry to build the iteration set
     (`devices`, sized `dsiz`) — iteration order is whatever that one evaluation returns,
     not re-evaluated per iteration. `for` uses explicit start/end/step values instead of a
     device list.
   - **`exit` (line 4264-4272)** evaluates its operand, calls `vcmd_setState()` to set the
     PISTON's own final state to that value, then sets `r9.term=true` — same termination
     mechanism `every` uses. This is the real mechanism behind "exit with value" (the
     HA_LIMITATIONS gap: HA's `stop:` has no equivalent "return a value" concept).
   - **`break` (line 4276-4279)** targets the nearest enclosing loop construct
     (`loops = [WHILE, REPEAT, FOR, EACH]`) via a request flag (`isBrk`), not exit/every's
     termination flag — confirms `break` is loop-scoped, not piston-scoped.
   - Incidental finding kept from the first pass: `resumeP()` (1874, comment at 1911-1913)
     always re-fires `resumeHandler` on piston start/resume specifically so `every`/timer
     schedules re-register even for pistons that don't subscribe to the resume event —
     `every` blocks schedule unconditionally on resume, independent of the piston's own
     subscription set.

6. **Expression evaluation, coercion, `$device`/system-var timing — VERIFIED, scoped per
   the brief (enough for the corpus's 12 system vars + observed expressions, not the whole
   language).** `evaluateExpression()` (line 10497) is the central evaluator. Two findings:
   - **Coercion is strongly-typed dispatch, not loose values (line 10510-10559).** Every
     evaluated expression gets switched on its declared type (`INT`/`LONG`/`DEC`/`TIME`/
     `DATE`/`BOOL`/`STR`/`NUMBER`/`DURATION`/`VARIABLE`/`DEV`/etc.) and run through a
     type-specific cast function (`cast`/`bcast`/`scast`/`dcast`) before being returned —
     the result is ALWAYS coerced to match the operand's declared type, never left as a
     loose dynamic value. **Compiler consequence: this is a real semantic gap against
     Jinja2/HA, which has no equivalent forced-cast-per-type step** — a naive
     string-interpolation translation would silently behave differently (e.g. comparing a
     numeric-looking string as a string vs. webCoRE's guaranteed numeric coercion). The
     compiler's canonical variable-substitution function (§1) needs to replicate this
     cast-by-declared-type behavior, not just interpolate raw values.
   - **`$device`/`$index` are scoped/contextual, not fixed per run.** `$index`
     (`sDLLRINDX`) gets set via `stSysVarVal()` inside the `each`/`for` loop body itself
     (line 4163) — updated per iteration, not once at piston start. `$device`
     (`sDLLRDEVICE`) is similarly contextual — and critically, when a piston resumes from
     an async wait/schedule, its saved stack context restores the ORIGINAL `$index`/
     `$device`/`$devices` values from when the wait began (line 3335-3339,
     `tMap[sSTACK]` → `sysV[sDLLRINDX]`/`sysV[sDLLRDEVICE]`/`sysV[sDLLRDEVS]`) — so a
     delayed action inside an `each` loop correctly still knows which device it was
     working on when it resumes, potentially much later. Compiler consequence: any
     PyScript-routed construct using `$device`/`$index` across a `task.wait_until()` needs
     to capture and restore that same context explicitly (closures/locals persist this
     naturally in PyScript, but it's worth stating as a requirement, not an accident).
   - The 12-system-var-specific expression grammar and full operator-precedence parsing
     (`simplifyExpression()`, referenced ~10501, single-pass leftmost-highest-priority
     comment at 10738) were not traced further — out of scope per the brief's own note;
     revisit only if a specific corpus expression's exact evaluation order is in question.

## 3. The pipeline

```
piston JSON ──► (0) ANALYZE ──► (1) RESOLVE ──► (2) ROUTE ──► (3) EMIT ──► (4) DEPLOY ──► (5) LIFECYCLE
```

### 3.0 ANALYZE — intent-pattern catalog (STARTER, from real corpus examples)

**Status: representative pass, not exhaustive.** Built from a structural scan across all
84 corpus pistons (statement-type/command/flag frequency — see distribution below) plus
close reading of genuinely representative files, not a full manual read of all 84. Per the
brief's own framing this is fine ("patterns are a fidelity/readability optimization, not a
gate" — unclassifiable structures always fall back to statement-by-statement compilation,
§3.3). Treat this as a strong starting catalog to extend, not a closed set.

**Corpus-wide structural facts (from the scan, worth knowing before reading the patterns):**
top-level statements are almost entirely `if` (189 of 198 top-level statements across 84
pistons) with a handful of bare `action`; nested constructs are dominated by `if`/`action`/
`condition`/expression trees. `wait` appears in 33/84 pistons (39%) — the single most common
"interesting" construct. `each` appears in 8/84, `repeat` in 4/84, `while` in 1/84.
**`every`, `on`, `exit`, and piston-level `restrictions` (`r`) appear in ZERO of the 84
corpus pistons** — real gaps in this corpus's coverage, not evidence those constructs don't
matter; they still need the hand-built captures §7 open item 3 already calls for. Most
common task commands (piston-count basis): `on`/`off` (device control), `setVolume`+
`playText` (the Speak-with-volume pattern, §B1 of the holding doc), `setVariable`, `wait`,
`deviceNotification`/`sendNotification`/`sendPushNotification`, `cancelTasks`.

**Patterns identified (each: JSON signature → intent → target HA construct):**

1. **Trigger-gated action.** Signature: one `if` with a single `ct:"t"` condition (or a
   trigger + simple guard conditions), one `then` branch with 1-2 device-command tasks, no
   `wait`. Intent: "when X happens (and Y currently holds), do Z." Target: HA `trigger:` +
   `condition:` + `action:` directly, no `choose`/`if` needed — the simplest possible
   automation shape. Example: `test-pistons/04_Back_Yard_Light_GPT.json` statement `$1`
   (switch changes_to off → turn light off, reset two local flags).

2. **Compound-guard trigger action.** Signature: `if` whose condition group mixes a
   trigger (`ct:"t"`) with several `ct:"c"` guard conditions (device state, another
   device's attribute, a local variable) combined `and`/`or`, sometimes nesting a `group`
   for an inner `or`. Intent: "only actually do this when the trigger fires AND the world
   is in the right shape" — guards prevent the action from firing on every raw trigger.
   Target: HA `condition:` list (or a `choose` branch) gating the same `action:` block;
   nested `or` groups map to a `condition: or` block. Example: same file, statement `$8`
   (illuminance<100 AND light-off AND (person-detected OR motion-active) → light on).

3. **Physical-vs-programmatic flag (local-variable interaction tracking) — DECIDED, Jeremy
   2026-07-15.** Signature: a local boolean variable (e.g. `"programatic"`) is set
   `true`/`false` around the piston's own device commands, and a SEPARATE `if` watches for
   the SAME device's trigger firing while that flag reads `false` — distinguishing a user's
   manual interaction from the piston's own automated one. Intent: "did a person just do
   this, or did I?" **Decision: replicate the local-variable pattern verbatim — do NOT
   translate to HA's context system (`context_id`/`parent_id`).** Considered and rejected:
   routing through HA context tracking, because it has the identical reliability problem in
   practice — it depends on the specific integration/driver correctly propagating context
   through to the device's real report back to HA, which is unreliable for the same
   underlying reason physical/programmatic detection is already unreliable per-device in
   Hubitat (Jeremy, confirmed from direct experience: "found it a little buggy in Hubitat
   depending on the device"; he has already used this exact local-variable mechanism
   directly in real HA automations himself, independent of webCoRE). The local-variable
   approach is application-level bookkeeping the piston fully controls, so it sidesteps
   trusting either platform's device-level physical/digital reporting entirely — the more
   portable, more reliable choice, and it follows the standing intent rule (replicate what
   the piston actually does, don't "improve" it into a platform-native mechanism that
   behaves differently). Example: `test-pistons/04_Back_Yard_Light_GPT.json` statement
   `$20`.

4. **Timed follow-up with re-check reset.** The pattern the brief named up front, confirmed
   real in the corpus. Signature: `if` (trigger: condition clears / motion inactive) `and`
   guard flag → `wait <N minutes>` → nested `if` RE-CHECKING the same conditions (plus
   guards) still hold → device action + flag reset. TCP (`tcp:"c"`, the default, §2.5 point
   4) auto-cancels the pending wait if the watched condition retriggers before the wait
   elapses; the nested re-check after the wait is a second, explicit guard against state
   having drifted during the wait (belt-and-suspenders on top of TCP, not a replacement for
   it). Target: HA `delay:`/`wait_for_trigger:` with the re-check as a `condition:` right
   after the wait, inside the same automation (TCP's auto-cancel maps to `mode: restart` —
   see §2.5 point 4's scoping caveat) OR PyScript `task.wait_until()` + re-check when
   composed with other routed features. Example: same file, statement `$25` → nested `$32`.

5. **Explicit cancel-on-retrigger.** Signature: a standalone `if` whose only task is
   `cancelTasks`, triggered by the same condition(s) that would otherwise auto-cancel via
   TCP. Intent: belt-and-suspenders — redundant with automatic TCP cancellation in the
   simple case, but becomes NON-redundant when it needs to cancel a DIFFERENT statement's
   pending tasks than TCP's own per-condition-group scoping would reach. Target: an
   explicit `service: automation.trigger`-adjacent cancel action is unlikely to be needed
   if TCP scoping (§2.5 point 4) is correctly replicated per-condition-group; TO VERIFY
   whether any corpus instance of this pattern cancels tasks OUTSIDE its own condition
   group (would force an explicit cross-branch cancel mechanism). Example: same file,
   statement `$42`.

6. **Group-aggregate sensor condition (no explicit loop).** Signature: a `p` operand's `d`
   array names a multi-member device-type variable (e.g. "Gas_Detectors" grouping several
   real sensors) with `g:"any"` (trigger side) or `g:"all"` (condition side) — testing "did
   ANY sensor in the group detect X" / "are ALL sensors in the group clear" without an
   `each` statement at all. Intent: fan-in aggregation across a device group. Target: HA
   `trigger: state, entity_id: [...]` naturally fans in for the "any" case; the "all clear"
   condition needs an explicit `condition: template` or repeated `condition: state` AND-ed
   together, since HA has no native "all of these entities read X" shorthand. Example:
   `test-pistons/29_Gas_Detector_2.json` statements `$1`-`$4` (naturalGas any-detected /
   all-clear pair).

7. **Edge announcement (notify/speak-on-trigger) — corpus-frequency evidence only, not yet
   read closely.** 25/84 pistons use `playText`, 17/84 use `deviceNotification` (plus
   `sendNotification`/`sendPushNotification` in a handful more) — a real, common pattern
   (trigger → speak or push a message), matching the already-documented Speak/Notify
   action specs (holding doc §B/§C). Not given a close-reading citation this pass — TO DO:
   pick one real example and confirm it's a simple trigger-gated variant of pattern 1
   rather than something structurally distinct.

**Not yet clustered from this pass:** `each`-loop-over-devices as an explicit statement
(8/84 pistons have one, none read closely yet), `repeat` usage (4/84), the "guard-only
piston" pattern the brief suggested (restrictions + no trigger) — **this pattern may not
exist in this corpus at all**, since 0/84 pistons use restrictions. Confirm that absence
before assuming the pattern needs compiler support at v1.

### 3.1 RESOLVE — devices, variables, values
- Device refs in `d` arrays are: hashed id | local device-variable name | `@global` name |
  `$device` (inside `each`). Resolution order: literal hash → piston `v[]` definition →
  globals store → loop binding. [VERIFIED — capture]
- Hash → member entities via the shim's resolution map (DEVICE_PAYLOAD_SPEC §8:
  registry_device_id, members, attr_bindings, cmd_bindings). Rebuildable cache.
- **Per-device multi-mapping (DECISION, Jeremy 2026-07-12):** each member entity is
  matched against the vocab entry's `ha` array by domain/device_class/features; array
  order is the tiebreaker when several match one entity (order is MEANINGFUL — never
  re-sort the arrays).
- **Command fan-out with grouping (DECISION):** one webCoRE command over mixed devices
  emits one HA service call per winning mapping, each carrying the combined entity list
  of the devices that resolved to it.
- **Failure rules (DECIDED — COMPILER_DECISIONS_DEPLOY §2):** unavailable = pass through
  (HA skips offline entities in actions); unresolvable = compile error (a trigger on a
  nonexistent entity_id silently never fires); multi-device statements skip+flag bad
  members; single-device statements with an unresolvable sole device error+pause+flag.
- **Globals: read from the globals store (shim-side JSON, `used_by`-tracked); global
  VALUES inline per C-TYPES translation (holding doc §C-TYPES, transcribed here — VERIFIED
  against wiki.webcore.co + the ady624 groovy source).** Device globals resolve like local
  device vars (hashed device IDs, resolved through the shim's hash↔entity_id map, §H1 —
  never an HA "device variable" helper, because HA has none). Scalar globals map to HA
  input helpers **by BEHAVIOR, never by name** — webCoRE's and HA's type names do not
  reliably match:
  | webCoRE type (what value it holds) | HA storage | Name-mismatch trap |
  |---|---|---|
  | integer | `input_number` | HA has ONE numeric helper, no separate integer/decimal — use mode/min/max/step to constrain |
  | decimal/float | `input_number` | Same single helper as integer — webCoRE's two numeric types collapse to one |
  | string/text | `input_text` | — |
  | boolean | `input_boolean` | **HA values are `on`/`off`, NOT `true`/`false`** — do not map by the word "boolean" and assume Python-style booleans |
  | datetime/date/time (3 separate webCoRE types) | `input_datetime` | ONE HA helper with `has_date`/`has_time` flags covers all three |
  | device (list of device IDs) | not an input helper at all | stored as hashed device ID arrays, same shape as local device vars, resolved via §H1 |
  webCoRE's ~7 value types collapse to 4 HA input helpers + the device-picker path.
  Globals carry an `@` prefix; superglobals (`@@`) are cross-*instance*, and since
  PistonCore collapses the broker to a single local HA instance, superglobals have no v1
  role (noted for future scope, not a v1 gap).

### 3.2 ROUTE — YAML or PyScript
- **`routing_table.json`: a list of webCoRE-JSON signatures that FORCE PyScript; YAML is
  default (DECISION). Re-key of holding doc §E's rows to real v2 field names — VERIFIED
  against PISTON_JSON_REFERENCE.md §2.2's statement-type table:**
  | v1 §E field (old) | Real v2 field/signature | PyScript mechanism |
  |---|---|---|
  | `type: "on_event"` | statement `t:"on"` (fields: `c`, `s`, `o` forced `"or"`) | `task.wait_until(event_trigger=...)` |
  | `type: "break"` | statement `t:"break"` (no other fields) | Python `break` |
  | `type: "cancel_pending_tasks"` | **NOT a statement type at all — it's a task command, `k[].c == "cancelTasks"`** (confirmed real, corpus statements `$19`/`$46` in `04_Back_Yard_Light_GPT.json`) — the v1 doc's framing was wrong, this is a command inside an `action` statement's task list, not a control-flow statement | `task.unique()` |
  | `condition_operator: "xor"` | group node `o:"xor"` (VERIFIED, PISTON_JSON_REFERENCE §3: `{"t":"group", "o":"and"|"or"|"xor"|..., ...}`) | `sum([...]) == 1` |
  | `operator: "followed_by"` | NOT a separate operator value — signaled by presence of `wd` (within-duration operand) + `wt` (option string, only `"l"` observed so far) on a condition/group node (VERIFIED, PISTON_JSON_REFERENCE §3) | Chained `task.wait_until()` with shared deadline |
  | `case_traversal_policy: "fallthrough"` | statement `t:"switch"`'s `ctp` field (VERIFIED field name, PISTON_JSON_REFERENCE §2.2 — exact value set NOT yet enumerated, TO VERIFY against piston.module.html dialogs same as tcp/tep) | Python `if/elif` without early exit |
  | `interval_unit: "n"/"y"`, `only_on_dom`, `only_on_months`, `only_on_wom` | statement `t:"every"` carries `lo`/`lo2`/`lo3`/`s` per PISTON_JSON_REFERENCE §2.2, but **how interval-unit/dom/month/wom actually pack into those operands is NOT yet captured** — `every` has ZERO occurrences in the 84-piston corpus (§3.0), so this re-key is unverified against real data; needs a hand-built capture (already flagged, §7 open item 3) before the routing table can trust it | `@time_trigger("cron(...)")` / runtime check for `only_on_wom` |
  Corpus note: `cancelTasks` and `stays_*`/`was_*` operators DO appear in real pistons
  (§3.0) — this routing WILL fire in practice, it's not a theoretical edge case.
- **`stays_*`/`was_*` native-vs-PyScript boundary (VERIFIED — the boundary is the
  continuous-vs-point-in-time distinction, not "simple vs composed" positioning):**
  - **Native `for:` handles the CONTINUOUS-duration semantics** — "stayed X for N" /
    "changes to X and stays for N" both mean "has been true without interruption for the
    whole duration," which is exactly what HA's `for:` parameter on `state`/
    `numeric_state` triggers AND conditions already means (behavior map §2.1/§2.2). This
    covers `stays_less_than`/`stays_greater_than`/`stays_greater_than_or_equal_to`/
    `stays_any_of` (all real corpus operators, §3.3's coverage table) directly, as a
    single native trigger/condition — no PyScript needed for the simple case.
  - **The real boundary is `was X in the last N`, a DIFFERENT semantic** ("was that value
    at ANY point during the window," not "has been that value continuously") — behavior
    map §2.1 states this explicitly has no native HA equivalent, template condition
    required. This is where PyScript's `.old` (single prior value) or `state_hold`
    genuinely diverge from native `for:`, because HA's `for:` cannot express "was true at
    some point, possibly not now."
  - **Composition still matters, but as a second, separate reason to route to PyScript,
    not the primary boundary:** combining a `stays`/`was` condition with other conditions
    inside a `followed_by` chain or an XOR group forces PyScript anyway per those
    constructs' own routing rows above — `stays`/`was` itself isn't what forces the
    route in that case.
  - **HA_LIMITATIONS §2 caveats that apply regardless of which path is chosen:** `for:`
    duration has edge cases when the entity goes unknown/unavailable mid-wait (HA may not
    evaluate the duration correctly); a 2026.7 PR changed numeric_state error-reporting
    behavior for this case — re-test before assuming either the old silent-failure or the
    new error-surfaced behavior without checking a real HA 2026.7+ instance.
- User preference "prefer PyScript" flips the default for whole pistons (settings).
- The routing scan runs in the shim's save flow, after reassembly.

### 3.3 EMIT — the two bands
**YAML band (primary):**
- **Classic primitives are the DEFAULT emission; a purpose-specific template band exists
  as the FALLBACK (DECIDED, Jeremy 2026-07-18: "default to primitive but add all — I want
  a fallback in the templates in case they retire the primitives").** Evidence for the
  default: purpose-specific YAML keys were renamed breaking in 2026.7 itself, while
  classic primitives carry an explicit stability promise [VERIFIED —
  HA_YAML_COMPILER_RESEARCH §0/§3]. The fallback is a TEMPLATE-BAND concern, not a
  compiler-code concern: `templates/compiler/yaml/classic/` is the active band;
  a `.../purpose/` band gets authored when needed (or preemptively); switching bands is a
  data/settings change + Recompile All — zero compiler edits. This is the same insurance
  pattern as the PyScript band versioning.
- Modern key schema (`triggers:`/`conditions:`/`actions:`, `trigger:` type key) per
  HA_YAML_COMPILER_RESEARCH §1. **Emission baseline VERIFIED:** modern key schema ONLY —
  `triggers:` list (`- trigger: <type>`), `conditions:` list (`- condition: <type>`),
  `actions:` list (`- action: <domain.service>`, never `service:`). Never emit legacy
  `platform:`/`service:`/singular `trigger:` forms. Inner triggers (inside
  `wait_for_trigger:`) use the same `trigger:` type-key form as top-level.
- Structure per piston: one automation (+ script when reuse/complexity demands) [FILL:
  the automation/script split rule — source: v1 compiler reference + behavior map §1].
- Trigger extraction: all `ct:"t"` nodes → `triggers:` OR-list; full parent condition
  tree → `conditions:`/`choose:`.
- **`if`/`ei`/`e` → HA choose/if mapping (VERIFIED — behavior map §1.1 + YAML research §2
  row "if/then/else"):** a piston `if` node with NO `ei` array compiles to HA's `if:`/
  `then:`/`else:` action directly (`e` becomes `else:`, when present). A piston `if` WITH
  one or more `ei` entries (an elseif chain) compiles to `choose:` instead — each `ei`
  entry becomes one `conditions:`/`sequence:` pair in order, the original `if`'s own
  condition is the FIRST `choose` branch, and `e` (if present) becomes `default:`. Reason
  for the split: HA's `if:` action has no native elseif — chaining it would require
  nesting `if` inside `else`, which does not preserve the flat elseif-chain shape a
  `choose` block does natively. **XOR groups have no native HA equivalent** (behavior map
  §3) — must route to a template condition (`{{ (cond1|int) + (cond2|int) == 1 }}`) or
  force PyScript.
- **Comparison table — VERIFIED coverage checked against the REAL corpus's operator set,
  not just transcribed.** The corpus uses exactly 22 distinct `co` (comparison operator)
  values (confirmed by direct extraction from all 84 files, matching PISTON_JSON_REFERENCE
  §2's stated count). Cross-referencing that real set against WEBCORE_HA_BEHAVIOR_MAP.md
  §2.1/§2.2's mapping table:
  - **Directly covered, ready to use:** `is`, `changes_to`, `is_between`, `is_not`,
    `is_less_than`, `is_less_than_or_equal_to`, `is_greater_than`,
    `is_greater_than_or_equal_to`, `is_any_of`, `changes`, `is_not_between`, `was` — all
    have an exact named row in the table.
  - **Same semantic family, exact row name differs — needs a quick re-key, not new
    research:** `changes_away_from` (table has "changes from"), `changes_to_any_of` (table
    has "changes to" + "is any of" as separate rows — this corpus operator combines both),
    `stays_less_than`/`stays_greater_than`/`stays_greater_than_or_equal_to` (table has
    "stays above"/"stays below" as the trigger-side family; the corpus's `stays_*` naming
    needs mapping onto that family precisely), `was_greater_than_or_equal_to`,
    `stays_any_of` (table covers "was"/"stayed" generically, not this specific combination
    by name).
  - **The three special triggers the behavior map skipped — RESEARCHED 2026-07-15 from
    real corpus captures** (they were never lost from the vocab — all three live in
    `comparisons.triggers`; the behavior-map research pass walked the state-comparison
    categories and missed these because they aren't state comparisons at all):
    - **`happens_daily_at` (33 uses — the daily schedule trigger).** Shape: `lo` = virtual
      device `time` (`{t:"v","v":"time"}`), `ro` = either a time CONSTANT in minutes-since-
      midnight (`480` = 8:00 AM, `1215` = 8:15 PM — §4's documented time encoding) or a
      system variable (`{t:"x","x":"$sunrise"}`). Mapping: constant → `trigger: time,
      at: "HH:MM:SS"` (native, clean); `$sunrise`/`$sunset` → `trigger: sun,
      event: sunrise|sunset` (+ `offset:` when the operand is an offset expression);
      any other variable/expression time → `trigger: time` accepts an `input_datetime`
      entity id natively, else PyScript `@time_trigger`. All observed corpus uses are the
      first two forms.
    - **`gets` (19 uses — the momentary-event trigger, vocab bucket `g:"m"`).** Shape:
      `lo` = device attribute `pushed` (scene controller / button device), `ro` = the
      button NUMBER (Hubitat button devices emit `pushed=<n>` events). Semantics: fires on
      EVENT ARRIVAL, even when the value repeats (two presses of button 1 in a row both
      fire) — this is exactly the event-entity repeat-fire problem already flagged in
      HA_LIMITATIONS §3: a plain `to:` state trigger will MISS repeat presses. Mapping:
      Hubitat-bridged buttons surface in HA as `event` entities whose state is the
      last-event timestamp (changes on EVERY event) → `trigger: state` on the event entity
      with no `to:`, plus a condition on the event's attribute for the button number.
      [ASSUMED — needs the dev-HA button test already on §6's list before trusting.]
    - **`executes` (4 uses — virtual-device event trigger, vocab bucket `g:"v"`).** All
      corpus uses: `lo` = virtual device `alarmSystemAlert`, `ro` = `"intrusion"` /
      `"intrusion-delay"` — i.e. "HSM fired an intrusion alert." Mapping: HSM → HA
      `alarm_control_panel` (HA_LIMITATIONS §10); the alert firing → `trigger: state,
      to: "triggered"` on the alarm entity. OPEN detail: HA's alarm entity state doesn't
      distinguish alert TYPES (intrusion vs intrusion-delay) — whether PistonCore's
      alarm virtual-device mapping can expose that granularity is a shim design question
      (TO DECIDE at the alarm virtual-device implementation, not a comparison-table
      issue). `executes` is broader in webCoRE (pistons/rules execute too — `on`-statement
      territory) but 4/4 corpus uses are the HSM-alert form.
- Hard template rules (DECIDED, v1 postmortem — HA_LIMITATIONS §9): ALWAYS quote state
  values; EVERY wait emits `timeout:` + `continue_on_timeout:`; parallel branches carry
  sequence-level `continue_on_error`.
- `ts`/`fs` condition task lists compile (easy to miss). **Restrictions (`r`, VERIFIED —
  behavior map §4):** a `condition:` action placed before the restricted statements in the
  sequence — like piston restrictions, HA inline conditions don't subscribe to events, they
  only test state at evaluation time, so this is a faithful mapping with no PyScript
  detour needed. Piston-level `r` → a condition at the very top of the automation's
  `actions:` (global gate); statement-level `r` → a condition inline at that point in the
  sequence (local gate). Note: 0/84 corpus pistons actually use restrictions (§3.0) — this
  mapping is unexercised by the corpus, verify it against a hand-built test piston before
  treating it as corpus-confirmed, not just doc-confirmed.
- Header comment on every file: generated-by, piston id/name, template-set version,
  do-not-edit.
**PyScript band (exception path) — VERIFIED, PYSCRIPT_COMPILER_RESEARCH.md is
comprehensive and ready to consume directly (per-doc citations already carry section refs
to the actual PyScript 2.0.1 manual, not re-verified here — see that doc for sourcing):**
- **File layout (corrected — was wrong in an earlier assumption):**
  `/config/pyscript/scripts/pistoncore/<piston_id>.py` — NOT `pyscript/pistoncore/`, which
  PyScript's autoloader never sees at all (`scripts/**` is the only sanctioned recursive
  subdirectory). One piston = one file, its own isolated global context
  (`scripts.pistoncore.<piston_id>`) and own per-function log path — piston isolation and
  per-piston debug-log level control both come for free.
- **Tier-1 verbatim primitive table (the per-construct snippet list the brief asked for —
  full table lives in PYSCRIPT_COMPILER_RESEARCH §3, restated here as the operative
  mapping):**
  | webCoRE construct | PyScript primitive |
  |---|---|
  | trigger `changes to X` (edge) | `@state_trigger("e == 'X'", state_hold_false=0)` |
  | trigger `stays X for N` | `state_hold=N` |
  | `was` (prior value) | `.old` (`e.old == 'A' and e == 'B'` for changes-from-to) |
  | trigger `changes` (any) | `@state_trigger("domain.entity")` plain-name form |
  | restriction "only when X" | `@state_active("expr")` |
  | restriction "only between T1-T2" (incl. overnight wrap) | `@time_active("range(start, end)")` |
  | restriction "NOT between" | `@time_active("not range(...)")` |
  | "at sunrise/sunset ± offset" | `@time_trigger("once(sunrise + 30m)")` — near-verbatim to webCoRE's own phrasing |
  | "every N units between X and Y" | `@time_trigger("period(start, interval, end)")` |
  | monthly/yearly/dom/month restriction | `@time_trigger("cron(...)")` |
  | wait N (duration) | `task.sleep(N)` — never `time.sleep` (blocks the loop) |
  | wait until condition/time, with timeout | `task.wait_until(state_trigger=..., time_trigger=..., timeout=...)` — `"none"` return = the time spec was entirely in the past, compiler must branch on it instead of hanging |
  | `on_event`/`followed_by` | `task.wait_until(event_trigger=[...])` — has a real fidelity gap, see caveats below |
  | external execute URL | `@webhook_trigger("<id>")` (not v1-required) |
- **Execution modes, all four reproducible:** `parallel` = default (every trigger spawns an
  independent task, zero code); `restart` = `@task_unique("pistoncore_<id>")`; `single` =
  same decorator with `kill_me=True`; `queued` = an `asyncio.Lock` held for the function
  body (the one Tier-2/composed case, needs a small template not a bare decorator).
  **Default mode still OPEN** — webCoRE itself serializes per-piston execution
  (queued-ish), HA automations default to `single`; must be decided once, applies
  identically to the YAML target's `mode:` so both targets agree. Not decided in this pass.
- **Redeploy safety, verbatim by accident:** `task.unique("pistoncore_<piston_id>")` in the
  file preamble (unconditional, every load) kills any in-flight old-version execution on
  redeploy — this is exactly webCoRE's own behavior when you save a piston mid-run.
- **Pause mechanism:** rename the file to `#<piston_id>.py` (PyScript's documented
  loader-skip convention) — chosen so both targets have symmetric pause behavior
  (`automation.turn_off` on YAML). Does not preserve mid-run state on either target.
- **Piston state / exit-with-value:** `state.persist("pyscript.pistoncore_<id>_state", ...)`
  gives a real, restart-surviving piston-state entity, readable by other pistons on either
  target — a real, concrete answer for the PyScript half of the open "exit value" question
  (§2.5 point 5). The YAML target still has no equivalent (would need a helper entity) —
  that half stays open.
- **Value coercion (locked template rule):** numeric comparisons NEVER use bare `int()`/
  `float()` casts — always the forgiving helpers (`as_float(default=None)` etc.) with an
  explicit None-check, so an unavailable/unknown entity becomes a defined false + breadcrumb
  log instead of an exception. Ties directly to §2.5 point 6's finding that webCoRE forces a
  cast-to-declared-type on every expression — this is the PyScript-side implementation of
  that same discipline, just guarded against HA's stringly-typed state values specifically.
- **Never-emit list:** generators/`yield`/dunder methods, `async def` (PyScript's `async`
  doesn't behave like real Python async — always plain `def`), `exit()` (can crash all of
  HA), `time.sleep()`, blocking file I/O, bare `hass`, shadowing `state`/`task`/`log`/
  `event`/`service`/`pyscript` as local variable names, imports outside a pinned minimal
  set (exact allowlist still TO VERIFY from PyScript source).
- **Real fidelity gap, not yet mitigated:** `task.wait_until` only monitors WHILE it's
  actively waiting — an event landing between two chained waits is missed. Affects
  `followed_by` and any `on_event` placed mid-sequence. webCoRE's own subscriptions were
  persistent, so this is a genuine (if narrow) behavioral gap against the source system —
  recorded as a compiler warning code to emit (`FOLLOWED_BY_EVENT_GAP`), not yet built.
- Same template/data discipline as YAML band — one construct, one Jinja2 snippet template,
  no emitted-code strings in compiler Python source (this is the actual breaking-change
  insurance Recompile All depends on).

### 3.4 DEPLOY (DECIDED — COMPILER_DECISIONS_DEPLOY §2.5–§5)
- **Write transport — TWO modes (COMPILER_DECISIONS_DEPLOY §2.5), the thing that makes
  every write below actually reach HA.** PistonCore's container has no inherent access to
  HA's `/config`. Mode A = **Samba/SMB** (HA in a VM/HAOS/separate box — network write,
  creds on Settings). Mode B = **shared volume / local path** (HA as a co-located Docker
  container — bind-mounted config dir, plain local writes). Selected on the Settings page
  (`write_mode`), abstracted behind one `deploy_writer` interface so the compiler never
  knows which is active. Control path (reload) stays on the HA API regardless.
- Labeled includes, NOT packages: `automation pistoncore: !include_dir_merge_list
  pistoncore/automations/` (+ scripts). Packages rejected (UI-duplicate bug, filename
  uniqueness).
- Naming: `<slug>_<shortid>.yaml`; id authoritative, old file removed on rename.
- Reload: `automation.reload` + `script.reload`; TO VERIFY whether first-time file
  additions under include_dir need `reload_all` (dev-HA test).
- First-run wizard owns the configuration.yaml consent edit (backup, show diff, explicit
  yes, refuse-if-nonstandard) + pyscript block + PyScript-optional notice + default mode.

### 3.5 LIFECYCLE (DECIDED — COMPILER_DECISIONS_DEPLOY §1, §8)
- Compile on every successful save. Failed compile leaves the previous artifact RUNNING;
  banner on the stock status page (link → debug page) + front-door flag.
- Piston active/paused mirrors one-way PistonCore → HA (`initial_state`/enable);
  new pistons land paused (webCoRE build-0 behavior) — mirrored, not invented.
- Device-global edits: targeted patch of deployed artifacts via `used_by`, never full
  recompile (holding doc §H); piston JSON untouched (verified — names in JSON).
- Recompile All: settings button + stale-template front-door banner; artifacts record
  template-set version.

## 4. Execution modes
First-run prompt sets the default; settings changes it; webCoRE piston settings honored
per-piston where they express an equivalent.

**ALL FOUR policy value sets now VERIFIED from the dialog templates (piston.module.html
:337-365, read 2026-07-15) — no longer TO VERIFY:**
| field | option values (default marked *) | meaning |
|---|---|---|
| `tcp` taskCancellationPolicy | `""`* / `c` / `p` / `b` | Never* / on condition state / on piston state / on either. **⚠ CONFLICT to resolve on dev HA:** the dialog labels `""` as "Never" (:357) and `c` as the greyed default; but the groovy engine's own comment (`gTCP`, :4601 `?: sC`) treats ABSENT tcp as `c`, and the status-badge logic (:499) shows badge "N"(never) for tcp NOT in c/p/b. So `""` present-on-wire = Never, but tcp KEY ABSENT = defaults to `c`. The compiler must distinguish absent-key from empty-string-value (the dashboard-next wire map's "absent ≠ empty" rule, PISTON_JSON_WIRE_MAP §2, matters here). |
| `tep` taskExecutionPolicy | `""`* / `c` / `p` / `b` | Always* / only on condition state change / on piston state / on either (:361). |
| `tsp` taskSchedulingPolicy | `""`* / `a` | Override* / Allow multiple (:365). "Override" = a new scheduled task replaces the pending one of the same statement; "Allow multiple" = they coexist. (Semantics inferred from the two labels; confirm against engine scheduling code when the scheduler is implemented.) |
| `ctp` caseTraversalPolicy (switch only) | `i`* / `e` | Safe* (break after first match) / Fall-through (continue to next case) — `e` forces PyScript (§3.2). |

**TCP** (repeated from §2.5 point 4 for the routing consequence):
`""`/`"c"` (cancel-on-condition-change, default), `"p"` (cancel-on-piston-change), `"b"`
(either), and Never (key absent behaves as `c`; explicit `""`-on-wire = Never per the
dialog — see conflict note above). `mode: restart` is a real but PARTIAL match — exact only when a
compiled automation contains exactly one independent condition-scoped TCP unit; bundling
multiple condition groups into one automation breaks it (§2.5 point 4 has the full
reasoning). Routing consequence: **the ANALYZE/ROUTE stages need a rule that keeps each
independent TCP-scoped condition group as its own automation** (or otherwise isolates it)
when tcp is `c`/`b`/`default`, rather than assuming one-automation-per-piston always works.
tcp=`"n"` and tcp=`"p"` still have no `mode: restart` equivalent — TO VERIFY: does `"p"`
map to a piston-wide (not condition-wide) `mode: restart`-per-automation-if-one-piston-one-
automation-holds, or does it need PyScript's `task.unique`/`state.persist`?
All four value sets are tabled above. Disposition for the non-native ones (tep, tsp, and
non-default tcp/ctp) per §5's governing rule: IMPLEMENT via the PyScript route, never
defer — corpus frequency sets test priority only. Remaining unknowns are RUNTIME
SEMANTICS (exactly what tsp "Override" cancels, the tcp absent-vs-empty resolution), to be
mined from the engine's scheduling code when that piece is built — not the value sets
themselves, which are now closed.

## 5. What does not compile

**GOVERNING RULE (DECISION, Jeremy 2026-07-15 — supersedes every earlier "defer"/"cut"
in this spec): MAKE WHATEVER CAN WORK, WORK.** PyScript exists in this architecture
precisely so hard things still work. A compile error is reserved for the VERIFIABLY
impossible only, and the spec must record the verified reason — specifically why even
PyScript cannot do it. Corpus absence is NEVER a reason to defer or cut: the 84-piston
corpus is Jeremy's test/debug set and the regression priority order, NOT the feature
ceiling ("I'm only testing and debugging my pistons through the compiler — I am not
purposely leaving shit out").

- Omitted-from-db features never reach pistons (reproduce-cleanly test; `ha:"n/a"` markers
  drive Stage-3/getDb filtering) — this is picker-side scope, decided separately.
- Pistons using routed-but-PyScript features when PyScript is absent: compile error with
  the E3 notice ("statement $N requires PyScript") + install link. Never silent. (This is
  environmental — the feature works, the runtime is missing — not a feature cut.)
- **Behavior-map §6 reconciliation (2026-07-15, REVISED same day under the governing
  rule).** WEBCORE_HA_BEHAVIOR_MAP.md §6 listed 11 items as "cannot be mapped" — stale;
  reconciled disposition:
  | §6 item | Real disposition |
  |---|---|
  | Followed-by condition group | **PyScript-ROUTED** (chained `task.wait_until`, §3.2) — with the recorded FOLLOWED_BY_EVENT_GAP caveat (§3.3) |
  | `on` event nested trigger | **PyScript-ROUTED** (`task.wait_until(event_trigger=...)`, §3.2) |
  | XOR logical operator | **PyScript-ROUTED** (`sum([...]) == 1`, §3.2) or template condition on the YAML band (§3.3) |
  | Switch fall-through | **PyScript-ROUTED** (`if/elif` without early exit, §3.2) |
  | Piston state / exit with value | **IMPLEMENT BOTH BANDS** — PyScript via `state.persist` (holding doc §E5); YAML via writing the piston-state helper entity (`input_text`, C-TYPES pattern) before `stop:`. No drop-with-warning option. |
  | IFTTT virtual device | **STAYS — natively reproducible** (`rest_command` webhook, Session-73 research, HA_LIMITATIONS §10) |
  | LIFX cloud virtual device | **STAYS — natively reproducible** (native `lifx.*` actions, HA_LIMITATIONS §10) |
  | Physical vs programmatic operand filter (`p:"p"`/`p:"s"`) | **IMPLEMENT — PyScript route, context-based.** HA state events carry a `context` (who/what caused the change): a change caused by a service call from an automation/script carries a parent context; a device-originated report does not. PyScript trigger functions receive the event `context` — so `p:"s"` (programmatic) ≈ "context has a parent," `p:"p"` (physical) ≈ "no parent and no automation origin." TO VERIFY on dev HA: exact context fidelity per integration (Hubitat-bridged devices especially), and the residual approximation vs. Hubitat's own flaky per-device support (Jeremy's direct experience: unreliable there too — parity with an imperfect source, not regression from a perfect one). 7 real corpus occurrences — this WILL fire. Only if dev-HA verification proves the context signal genuinely unusable does this become an error, with that verified evidence recorded here. |
  | Task Execution Policy (`tep`) | **IMPLEMENT — PyScript route.** Persist the per-condition-group truth cache (§2.5 point 3's own mechanism) in the piston's `state.persist` entity attributes; gate statement bodies on the c/p/b flags exactly as `executeStatement` does (engine lines 3921-3954). Native YAML has no equivalent → non-default `tep` is a routing-table row (forces PyScript), same as XOR. Corpus's 0 uses = lowest test priority, nothing more. |
  | `tsp` (task scheduling policy) | **IMPLEMENT — same path as tep**: enumerate the value set from piston.module.html dialogs, mine the engine for semantics, implement on the PyScript band; route non-default values there. TO VERIFY (semantics not yet mined), never "defer." |
  | AskAlexa / EchoSistant virtual devices | **MOOT — not in the served vocab at all** (verified 2026-07-15: no askAlexa/echoSistant entries in webcore_vocab.json commands, virtualCommands, or virtualDevices). They cannot appear in any piston authored against this shim; imported ancient pistons referencing them fail device/command resolution generically. Not a cut — there is nothing to cut. |
  | Contacts / SMS (`sendSMSNotification`, `sendNotificationToContacts` — both ARE in the served vocab, verified 2026-07-15) | **IMPLEMENT — Notify band.** Both are notification fan-outs; HA's notify platforms include SMS-capable targets (Twilio, SMS gateways, carrier email-gateways) and person-targeted notify services. Compile through the C1/C2 stable-target-reference mechanism: the piston stores the intent, deploy-time config maps it to the user's configured notify target(s). If the user has no SMS-capable notify service configured, that's a deploy-time resolution error naming the missing target (environmental, same class as PyScript-absent) — not a feature cut. |
  Net result under the governing rule: **ZERO cuts from the behavior-map list.** Two items
  are moot (absent from the vocab), everything else is implemented, routed, or an
  environmental/resolution error with the specific missing dependency named.

**The complete verified can't-do list (HA_LIMITATIONS §10.2 — exactly two, matching
Jeremy's recollection), re-examined 2026-07-15 under the governing rule:**
1. **Mid-run piston pause/resume** — webCoRE pause preserved mid-run state and resumed
   from the paused point. VERIFIED impossible on both bands: HA automations and PyScript
   tasks cannot be suspended and resumed mid-statement — in-flight tasks are killed, not
   frozen (PYSCRIPT_COMPILER_RESEARCH restart/reload semantics; `automation.turn_off`
   stops runs). Future-trigger pause (what PistonCore's pause does) is the implementable
   part and IS implemented.
2. **Piston tiles** (setTile family) — not a capability gap: the tile display surface is
   deliberately absent from PistonCore by Jeremy's own design (no tile layouts, ever).
   Out by decision, recorded as such.
   **Partial upgrade:** `setPistonState` was bundled with pause/resume in §10.2 but is NOT
   impossible — it writes the piston's state string, which is exactly what the
   piston-state entity (E5's `state.persist` / helper mechanism) holds. IMPLEMENT it
   through that entity on both bands.

## 6. Regression & acceptance
- Compile-all-84 (`test-pistons/`) is the regression suite and the progress bar; work
  order: single-feature test pistons → mid-size → the three ~80-node alarm pistons.
- **Golden fixtures (STARTED 2026-07-15, `test-pistons/fixtures/`):** hand-written
  expected outputs for real corpus pistons, one per band — Jeremy reviews these
  BEHAVIORALLY ("is this what that piston should do?"), and they become the acceptance
  set before any compiler code exists. **BOTH APPROVED (Jeremy, 2026-07-16: "both of the
  descriptions match my intent") — including 04's two flagged review points (@task_unique
  as the TCP approximation; cancelTasks as structural no-op + breadcrumb). These two are
  now binding acceptance targets.**
  - `12_Cave_motion_V2.expected.yaml` — native band. Exercises patterns #1/#4/#6; makes
    concrete: one-automation-per-top-level-if (TCP scoping), the TCP-default compilation
    idiom (mode: restart + auxiliary cancel-triggers + `condition: trigger` id-gate),
    ≤-comparison as a fail-closed template condition, multi-entity trigger lists.
  - `04_Back_Yard_Light_GPT.expected.py` — PyScript band (routed by `cancelTasks`).
    Exercises patterns #1-#5; makes concrete: locals-as-persisted-pyscript-entities,
    the one-function/OR'd-decorators/one-pass-body anatomy, `.old` for changes_away_from,
    forgiving numeric helpers, and TWO explicit REVIEW POINTS — (a) @task_unique as the
    TCP approximation (kills in-flight runs on ANY subscribed event, not only on the
    owning condition's flip — exact for this piston, over-broad in general), and
    (b) `cancelTasks` compiling to a structural no-op + breadcrumb under that model.
  - NOT yet covered by fixtures: patterns #6 aggregation-`all` (Gas Detector's all-clear),
    #7 speak/notify (blocked on the Notify band, §7 item 6), `each`/`repeat`/`while`
    loops, and everything absent from the corpus (`every`/`on`/`exit`/restrictions —
    needs the §7-item-3 hand-built captures first). Extend one fixture per pattern as
    each EMIT template gets written.
- Dev-HA test list (port from research docs): reload-new-file behavior; restart kills
  in-flight waits (PyScript §12); `state_hold_false=0` chatty-sensor; event-entity repeat
  under classic state trigger; presence semantics vs Jeremy's zones (2026.7 changes).

## 7. Open items
1. Jeremy: confirm classic-primitives-only (§3.3) → flip to DECIDED.
2. ~~Behavior-map §6 reconciliation pass~~ — DONE 2026-07-15, see §5 table.
3. Five uncaptured statement types → hand-built captures (editor session).
4. Engine-mining leftovers: exact TCP per-statement semantics, `a` async flag, mixed
   trigger evaluation order, `every` scheduling internals, expression evaluator coercion
   (webcore-piston.groovy; needed for §3.3 fills and §4).
5. Port-backs listed in both research docs' §5 (Code errand).
6. Notify band: blocked on C2b translation file + phone on test HA (design exists —
   NOTIFY_ACTION_SPEC + C1/C2/C2b).

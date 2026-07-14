# PistonCore — HA Limitations & Gotchas Reference

**Status:** Living document — add to this whenever a new HA limitation is discovered.
**Last Updated:** July 2026 (PyScript research session — verified PyScript 2.0.0/2.0.1 release notes and current docs against a third-party AI summary; corrected two false claims (auto-reload DOES exist; scripts DO persist across restart), added Section 6 "PyScript Runtime Constraints" covering the 2.0 decorator subsystem rewrite (re-test flag), hard rules for compiler-emitted code (no generators/yield/special class methods; never touch `hass` — built-ins only), restart semantics for in-flight tasks, and the no-trace-UI debug implication (compiler must emit log breadcrumbs). Prior: July 2026 research session — re-verified full PyScript routing table and Section 1 loop-control table against live HA 2026.7 docs; no changes required, all prior routing decisions confirmed still correct. Current stable is **2026.7** (released July 1, 2026 — purpose-specific triggers/conditions graduated from Labs to default, Matter backend rewritten in TypeScript (matter.js), Activity/Logbook rebuilt as timeline; none of this affects PistonCore's core scripting/routing decisions). Added two re-test flags to Section 2 from 2026.7 changelog. PyScript confirmed still at 2.0.1 — no release since last research. Prior: June 2026 — PyScript routing table expanded: XOR, followed_by, switch fallthrough, monthly/yearly scheduling all confirmed PyScript-capable and routed there, not cut. Prior: Session 73 — live-researched WebCoRE non-device command set against current HA docs; added Section 10.)

This document captures Home Assistant limitations that affect PistonCore design and
implementation. It exists because the gap between Hubitat/WebCoRE and HA is significant
and keeps being rediscovered from different angles.

For decisions already made in response to these limitations, see
COMPILER_DECISIONS_HOLDING.md (and the v2 compiler spec when it exists).
For the piston JSON these limitations apply to, see PISTON_JSON_REFERENCE.md.
(v1 pointers to DESIGN.md / COMPILER_SPEC.md / WIZARD_SPEC.md are retired with v1.)

---

## Version Review Log

| Reviewed against | Date | Findings |
|---|---|---|
| HA 2026.4 (current stable) | May 2026 | Variable scoping fixed in 2025.3. `continue_on_error` added to UI editor in 2026.3. `break`/`on_event`/`cancel_pending_tasks` still PyScript-only. No other limitations resolved. |
| HA 2026.6 (current stable) | June 2026 (Session 73) | Stable is now **2026.6** (prior log said 2026.4 — stale). Re-verified loop control against live 2026.6 script-syntax docs: HA's native `stop` action only ends the current sequence block / current repeat iteration / current choose — it is **not** a true WebCoRE `break` (exit loop, continue after it). So `break` stays PyScript **for now**. Live-researched the WebCoRE non-device (location/emulated) command set for reproducibility — results recorded in new Section 10. NOTE: this is the line as of 2026.6 — HA gains native capability over time, so Section 10 must be re-reviewed periodically, not treated as permanent. |
| PyScript 2.0.1 + HA 2026.6 | June 2026 (Research session) | Full PyScript routing table researched and verified. XOR, followed_by, switch fall-through, monthly/yearly scheduling all confirmed PyScript-capable — moved from "unknown/cut" to routed-to-PyScript. Full routing table now in Section 6. User notification requirement established. `on_event` timeout fields added to JSON schema. `every` restriction fields (`only_on_hours`, `only_on_minutes`, `only_on_wom`) added to JSON schema. |
| PyScript 2.0.0/2.0.1 release notes + docs | July 2026 (PyScript research session) | Fact-checked a third-party AI (Grok) summary of PyScript capabilities against the actual release notes and current readthedocs. **Confirmed:** 2.0.1 (May 7, 2026) is latest; 2.0.0 (May 2, 2026) supports HASS 2026.5+ and is backward compatible; `task.wait_until()`, `@task_unique`/`task.unique()`, cron `@time_trigger`, and no-HA-trace-UI all check out — Section 6 routing table unaffected. **Grok claims REJECTED:** "no auto-reload" (false — watchdog auto-reload exists, fixed in 1.6.1, watchdog moved to own thread in 1.6.0; the documented reload limitation applies only to `legacy_decorators` mode) and "doesn't survive addon restart" (confused — pyscript is a custom integration, not an addon; script files in `/config/pyscript` persist; only *in-flight tasks* die on restart). **New findings recorded in Section 6:** 2.0.0 decorator subsystem rewrite (re-test flag on compiler-emitted decorators), language limitations (no generators/`yield`/special class methods), `hass_is_global` defaults false (compiler must use built-ins only — locked rule), pyscript per-function logging paths as the debug substitute for missing traces. |
| HA 2026.7 (current stable) | July 2026 (Research session) | Stable is now **2026.7** (released July 1, 2026 — prior log said 2026.6, stale). Re-verified `stop:` action against live 2026.7.2 script-syntax docs: still only ends current sequence block / current repeat iteration / current choose — confirms `break` stays PyScript, no change. PyScript confirmed still at 2.0.1 (no release since June) — full Section 6 routing table re-verified accurate, no items move off PyScript. `choose` fall-through behavior unchanged (still exits on first match). Headline 2026.7 changes (purpose-specific triggers/conditions graduating from Labs to default, Matter backend rewrite to matter.js, Activity/Logbook timeline rebuild) are UI/UX and integration-layer — do not affect PistonCore's compiler routing decisions. Two changelog items flagged for re-test in Section 2: numeric_state trigger error reporting (PR #175093) and sun condition event-time handling (PR #175240) — neither confirmed to resolve the existing edge cases, just flagged as changed underlying behavior worth testing against. |

---

## 1. Runtime Execution Limitations

### Native Scripts Are Weak Compared to Hubitat

Hubitat/WebCoRE had a full scripting runtime. HA native scripts are declarative YAML
with significant restrictions:

| Feature | Hubitat/WebCoRE | HA Native Script | PyScript | Handled by |
|---|---|---|---|---|
| break out of loop | Yes | No | Yes — real Python break | PyScript only — routing mechanism (UNVERIFIED in code) |
| on_event inside running script | Yes | No | Yes — `task.wait_until()` | PyScript only — routing mechanism (UNVERIFIED in code) |
| cancel async tasks | Yes | No | Yes — `task.unique()` | PyScript only — routing mechanism (UNVERIFIED in code) |
| Variable scoping across loops | Clean | Fixed (HA 2025.3+) | N/A | Was unreliable; now correct — see note below |
| Context tracking ($currentEventDevice) | Yes | No | Yes | PyScript only |
| Physical vs programmatic interaction | Yes | No | PyScript only | Wizard prompts conversion — deferred, needs sandbox validation |
| XOR logic in conditions | Yes | No — template only | Yes — Python expression | PyScript only — `condition_operator: "xor"` forces PyScript (verified June 2026) |
| Followed-by sequential events | Yes | No | Yes — chained `task.wait_until()` | PyScript only — `operator: "followed_by"` on condition group forces PyScript (verified June 2026) |
| Switch fall-through | Yes | No — `choose` always exits first match | Yes — real Python if/elif | PyScript only — `case_traversal_policy: "fallthrough"` forces PyScript (verified June 2026) |
| Monthly/yearly scheduling | Yes | No — `time_pattern` has no dom/month fields | Yes — cron syntax | PyScript only for `interval_unit: "n"/"y"` or non-empty `only_on_dom`/`only_on_wom`/`only_on_months` (verified June 2026) |
| Exit with value (piston state) | Yes | No — `stop:` drops value | Partial — can write to helper entity | Design decision required at the v2 compiler spec |

> **PyScript routing re-verified June 2026 (HA 2026.6 + PyScript 2.0.1):** The features
> now confirmed PyScript-capable (and the conditions that force routing) are documented in
> PISTON_FORMAT_MERGED.md "PyScript-Only Statement Types and Features" section. The list is
> larger than previously documented — XOR, followed_by, switch fall-through, and monthly/
> yearly scheduling now confirmed as PyScript-capable and routed there (not cut).
>
> **The routing must go through a template, not hardcoded logic.** HA gains native capability
> over time. The routing template is the single place to update when HA catches up. Native is
> always preferred over PyScript when HA supports it cleanly.
>
> **`target-boundary.json` mechanism:** referenced in specs as the routing file. Its existence
> in the backend was NOT confirmed from code — a coding session must verify whether it exists
> or the boundary is hardcoded, and extend/create it to cover the full routing table above.
> Do not treat it as confirmed.
**Variable scoping fix (HA 2025.3):** The long-standing bug where variables set inside a loop or parallel sequence body didn't update the outer scope was fixed in HA 2025.3 (PR #138883). The `wait` and `response_variable` scoping bugs were also fixed. General variable mutation across nested sequence blocks now works correctly. The `repeat` variable (available inside loop body as `repeat.index`, `repeat.first`, `repeat.last`) is still intentionally local to the loop — that hasn't changed. If PistonCore targets HA 2025.3+ (which it does — minimum is 2023.1), the old compiler warning about variable scoping can be downgraded or removed for most patterns. **Exception:** string accumulation across loop iterations using `variables:` still has subtle scope behavior that should be tested — the PyScript fallback for `loop_string_accumulation` remains correct.

### Long-Running Pistons

HA scripts have implicit resource limits and timeouts that Hubitat did not have.
Very long waits or complex loops may behave unexpectedly.
**Status:** Not yet handled. Flag as known risk. Test with real long-running pistons
before v1 release.

---

## 2. State and History Limitations

### was/stays Timing Edge Cases

The `was` / `stays` distinction is critical and has real edge cases:

- `wait_for_trigger` at a specific time — if the piston reaches this step AFTER the
  target time has already passed today, it waits until tomorrow. Compiler always
  emits a warning for this. (was WIZARD_SPEC.md; the was/stays semantics now live with the comparison docs in the v2 compiler spec.)
- Negative sunrise/sunset offsets that cross midnight (e.g., "$sunrise - 2 hours"
  when sunrise is at 6am = 4am, but what if piston runs at 11pm?). **Test specifically.**
- `for:` duration on state triggers has edge cases with unknown/unavailable states.
  HA may not evaluate the duration correctly if the entity goes unavailable mid-wait.
- **`for:` does NOT survive a HA restart or automation reload** (VERIFIED — HA docs,
  ported from HA_YAML_COMPILER_RESEARCH.md §2, 2026-07): the timer resets when HA restarts
  or automations reload, same as webCoRE pistons resetting on restart — this is an
  equivalent limitation on both systems, not a regression introduced by compiling to HA.
  Worth stating explicitly in user-facing help text so a `stays`/`was` piston's behavior
  around a restart doesn't look like a compiler bug.

### Numeric State Trigger Edge Cases

`above:` and `below:` on numeric_state triggers have nuanced behavior:
- Entity in unknown/unavailable state — trigger may not fire as expected
- Rapid state changes — trigger may miss transitions
- **Test with real sensors before shipping numeric trigger compilation.**

> **⚠ Re-test flag (HA 2026.7):** PR #175093 ("Report errors in numerical entity
> triggers") changed how numeric_state triggers surface errors — previously silent
> failures (e.g. unknown/unavailable entity) may now be reported instead of failing
> silently. This is a behavior change to verify, not a confirmed fix — it could mean
> PistonCore's compiler/deploy flow can now catch and surface something it couldn't
> before, or it could just mean HA's own log gets noisier. **Test against a real
> HA 2026.7+ instance before assuming either way.**

> **⚠ Re-test flag (HA 2026.7):** PR #175240 ("Use event time for sun is_up and
> is_set conditions") changed sun *condition* timing precision. This is a condition-level
> change, not the sunrise/sunset trigger-offset math the negative-offset edge case above
> is about — likely not directly relevant, but flagged since it touches sun timing.
> Do not treat as resolving the negative-offset edge case without testing.

---

## 3. Device and Entity Limitations

### Entity ID Changes Break Deployed Pistons

If a user renames a device in HA, the entity ID may change. This breaks any piston
that references that entity_id — the compiled YAML or PyScript will reference an entity
that no longer exists.

**Current status (logic_version 2):** Entity IDs are stored directly on condition,
action, and for_each nodes. There is no device_map. The scheduled entity validation
(the v2 deploy design (was DESIGN.md §9.2)) checks all deployed pistons every 30 minutes against the live
HA entity registry. If any entity_id is not present in the registry, the piston is
flagged `entity_missing: true` in the piston index and ⚠ appears on the piston list.

**Important:** A device that is offline, unavailable, or has a dead battery is NOT
missing — it still exists in the registry. The flag only fires when the entity_id is
completely absent from HA (renamed, deleted, or integration removed).

The fix flow: user opens the piston in the editor. The node with the missing entity
shows an inline warning. User clicks the node — wizard opens pre-filled with the
current role label. User picks a replacement device from the live HA picker. New
entity_ids are written to the node on commit. Save and redeploy.

### Multi-Entity Compilation — Confirmed Native Support

**HA natively accepts entity_id as an array in both triggers and action targets.**
PistonCore does not need to expand multi-entity groups into multiple blocks.

- **Triggers:** `entity_id: [list]` — one trigger block fires when any entity matches
- **Actions:** `target.entity_id: [list]` — one action block applies to all entities simultaneously
- **Conditions:** No native multi-entity support — PistonCore uses Jinja2 `any()`/`all()`/`none()` templates

For PyScript, service calls accept `entity_id=["e1", "e2"]` as a Python list — same behavior.
Triggers in PyScript use one `@state_trigger` string per entity (separate string arguments
to the decorator, which PyScript OR's together) — this IS expansion, but it's the only
option since `@state_trigger` takes string expressions not entity lists.

**Verified against official HA docs (May 2026). Locked decision.**

### ⚠ Presence/Zone Semantics Changed in HA 2026.7 (ported from HA_YAML_COMPILER_RESEARCH.md §4)

All three [Verified — HA 2026.7 release notes, backward-incompatible changes]:
1. **Zone person-counts:** zone entity state and the `persons` attribute are now
   calculated from each person entity's new `in_zones` attribute — a person can count in
   MULTIPLE zones simultaneously (e.g. `home` AND `near_home`). A piston comparing zone
   occupancy counts can see different numbers than it did pre-2026.7.
2. **Device tracker zone resolution:** position-aware device trackers now report the
   SMALLEST zone they're in, not the zone whose center is closest. A presence piston keyed
   on zone-name state can flip behavior where zones overlap.
3. **Person coordinates:** person entities no longer report home-zone lat/long when their
   location comes from a presence scanner associated with home — any piston reading person
   coordinates must use `in_zones` instead.

**Compiler consequence:** presence/zone compilation is not fidelity-clean until re-tested
against a real HA 2026.7 instance with Jeremy's actual zones. Do not declare presence
pistons done without that test.

### Event Entities May Miss Repeated Identical Events on the Classic (YAML) Path

[Verified — HA 2026.7 release notes] Automating around an event entity with a plain
`state` trigger "may discover it doesn't fire the second time the same event happens" —
event entities can report the same state value on consecutive distinct events (e.g. two
button presses in a row), and a state trigger only fires on a value CHANGE. This is a real
edge for button/scene-controller devices — a webCoRE "button pushed" piston compiled to a
plain state trigger can miss repeat presses.

**Interim mitigation:** trigger on the event entity's state change including same-state
timestamps (`to: null`-style forms). [Assumed — needs a dev-HA test with a real button
event entity to confirm this fires reliably on repeated identical events; not yet tested.]
Purpose-specific event triggers would solve this natively, but PistonCore's compiler
deliberately doesn't emit those (COMPILER_SPEC.md §3.3, classic-primitives-only decision)
— this is the one concrete case where that decision has a real, known cost, not just a
theoretical one. Revisit if this limitation turns out to affect real users often.

### Entity vs Device Model

HA's entity model means one physical device can have 10-20 entities.
PistonCore groups at the device level in the picker (done in ha_client.py).
But capability data comes from entities. If a device has multiple entities
for the same capability, the wizard must pick the right one.
**Currently handled by domain caps map — verify with real multi-entity devices.**

---

## 4. Deployment and Reload Limitations

### HA Reload Is Not Instant and Can Fail Silently

After `automation.reload` / `script.reload`:
- HA sometimes takes several seconds to reload
- HA can fail silently — reload returns 200 but automation is broken
- If the YAML is invalid, the old version stays active (good) but HA may not
  return a clear error

**Current status:** Deploy flow catches reload failures and shows error to user.
Old version stays active. UX must clearly communicate when old version is still
running. Test failure scenarios explicitly.

### continue_on_error — Now Available in the UI Editor (HA 2026.3)

`continue_on_error` on script actions was YAML-only until HA 2026.3, which added it
to the visual automation editor. This has no impact on PistonCore's YAML output —
PistonCore has always emitted it via the compiler. The change simply means users
who hand-edit their compiled files now have UI support for this field.

The compiler-level gap (Section 9 — `continue_on_error` not emitted at the parallel
sequence level) is separate and remains outstanding.

### File Permissions in Addon

Writing to `/config/automations/pistoncore/` and `/config/pyscript/scripts/pistoncore/`
(corrected path — `pyscript/pistoncore/` is NOT autoloaded at all, PyScript's loader only
recurses `pyscript/scripts/**`; PYSCRIPT_COMPILER_RESEARCH.md §0.1/§2, 2026-07)
requires correct addon permissions in config.json (addon manifest).
Easy to get wrong during addon packaging.
**Must be tested end-to-end in real HA addon environment before release.**

---

## 5. Performance Limitations

### Flat JSON File Storage at Scale

Current storage is one JSON file per piston. With 100+ pistons:
- Piston list page load will be slow (reads all files)
- Background compile on every save will feel sluggish

**Current status:** Acceptable for v1. Add indexing/caching before public release
if user testing shows lag. A simple index file (id → name, status, last_run) would
fix the list page without a database.

### WebSocket Payload Size

Large pistons with many statements will produce large WebSocket payloads.
Not a concern for v1 scale but worth noting for future.

---

## 6. PyScript Specific Limitations

### PyScript Is a Community Project

PyScript for HA (the HACS integration, not the web framework) is well-maintained
but is not an official HA project. If it stops being maintained, Docker users
(for whom PyScript is permanent) would be impacted.

**Mitigation:** Docker native runtime option is planned (see DESIGN.md Section 3.1).
Route the compiler's output target logic to accommodate this from the start.

### PyScript Routing — Full Verified Feature Table

The following features are confirmed PyScript-capable as of June 2026 (PyScript 2.0.1,
HA 2026.6). **Field names below are v1 placeholders — COMPILER_SPEC.md §3.2 has the
VERIFIED re-key to real v2 piston JSON field names (statement `t` values, `o`/`wd`/`wt`
group fields, `ctp`, etc.), including the finding that `cancel_pending_tasks` is actually
a task command (`k[].c == "cancelTasks"`), not a statement type. Treat §3.2 as
authoritative for field names; this table's PyScript-mechanism column still holds.**

| Feature | v1 JSON field (placeholder — see COMPILER_SPEC.md §3.2 for the real field) | PyScript mechanism |
|---|---|---|
| `on_event` statement | `type: "on_event"` | `task.wait_until()` with optional timeout |
| `break` statement | `type: "break"` | Python `break` |
| `cancel_pending_tasks` statement | `type: "cancel_pending_tasks"` | `task.unique()` |
| XOR conditions | `condition_operator: "xor"` on any statement | Python expression `sum([...]) == 1` |
| Followed-by sequential events | `operator: "followed_by"` on condition group | Chained `task.wait_until()` with shared deadline |
| Switch fall-through | `case_traversal_policy: "fallthrough"` | Python `if/elif` without early exit |
| Monthly scheduling | `interval_unit: "n"` | `@time_trigger("cron(0 H D * *)")` |
| Yearly scheduling | `interval_unit: "y"` | `@time_trigger("cron(0 H D M *)")` |
| Day-of-month restriction | Non-empty `only_on_dom` on `every` | cron `dom` field |
| Month restriction | Non-empty `only_on_months` on `every` | cron `mon` field |
| Week-of-month restriction | Non-empty `only_on_wom` on `every` | Runtime check in function body (no cron equivalent) |

**User notification requirement:** When any piston compiles to PyScript, the debug/compile
screen must display a prominent notice: "This piston uses features that require PyScript.
It will be deployed as a PyScript file, not a native HA automation. PyScript must be
installed via HACS." This is not optional — users who haven't installed PyScript will
have silently non-functional pistons without it.

### Deploy Lifecycle Facts (VERIFIED — PYSCRIPT_COMPILER_RESEARCH.md §2, ported 2026-07)

- **Reload is per-file granular.** PyScript auto-reloads changed files, and only changed
  files (plus dependents) reload — deploying piston A never touches running piston B. The
  deploy flow still calls `pyscript.reload` explicitly with
  `global_ctx="scripts.pistoncore.<piston_id>"` for a deterministic, per-piston,
  error-surfaced reload.
- **Redeploy kills in-flight old-version execution, by design.** Reload does NOT stop a
  currently-running triggered function on its own — a mid-`wait` piston from the OLD code
  keeps running unless something explicitly kills it. The fix: `task.unique
  ("pistoncore_<piston_id>")` in the file preamble (outside any function, so it runs on
  every load/reload) terminates any running task that already claimed that name. This
  means redeploying a piston kills its in-flight old-version run — which happens to be
  exactly webCoRE's own behavior when you save a piston mid-run. Verbatim fidelity, by
  accident of how PyScript's task-uniqueness mechanism works.
- **Pause = rename the file to `#<piston_id>.py`.** A filename starting with `#` is
  skipped by PyScript's loader, and renaming triggers an automatic reload — this is the
  documented enable/disable mechanism. Chosen so both compile targets have symmetric pause
  behavior (`automation.turn_off` on the YAML target). Neither target preserves mid-run
  state across a pause — the existing cut of webCoRE's mid-run pause/resume (§10.2) stands
  for the PyScript target too.
- **Each piston gets its own isolated global context and its own log path**
  (`scripts.pistoncore.<piston_id>` / `custom_components.pyscript.scripts.pistoncore.
  <piston_id>.<function_name>`) — pistons cannot see each other's globals (isolation for
  free), and per-piston, per-function log level is controllable at runtime via the
  `logger.set_level` service with no HA restart needed. This is the PyScript-side answer
  to webCoRE's per-piston logging levels (None/Minimal/Medium/Full).

### PyScript Runtime Constraints (verified against 2.0.1 release notes + docs, July 2026)

These are constraints on the PyScript *runtime itself* — separate from the routing table
above, which is about which piston features force PyScript. Everything below applies to
every piston that compiles to PyScript. Verified/Assumed tags per the standard convention.

#### 2.0 Decorator Subsystem Rewrite — ⚠ Re-test Flag

**[Verified — 2.0.0 release notes, May 2, 2026]** PyScript 2.0.0 replaced the monolithic
decorator implementation with a new modular decorator manager, organized by decorator type
(state, event, timing, service, mqtt, webhook, task). The new implementation is the default.
A `legacy_decorators: true` config option exists as a temporary escape hatch for regressions,
and the legacy code will be removed in a future version. The project states there are no
intentional breaking changes; 2.0.1 (May 7, 2026) fixed `@webhook_trigger` regressions and
improved error messages for exceptions in triggered functions.

**Compiler rules:**
- Target the **new** decorator subsystem only. Never assume, require, or document
  `legacy_decorators: true` — it is scheduled for removal.
- **⚠ Re-test flag:** every decorator the compiler emits (`@state_trigger`,
  `@time_trigger`, `@event_trigger`, `@task_unique`, `@service`) sits directly on top of a
  fresh rewrite. Before v1 release, run each compiler-emitted decorator pattern against a
  real PyScript 2.0.1+ install on the test HA. A decorator rewrite is exactly where
  regressions in *generated* code surface — the project's own tests cover hand-written
  patterns, not necessarily the shapes a compiler emits. Same treatment as the two
  HA 2026.7 re-test flags in Section 2.

#### Language Limitations — Constructs the Compiler Must Never Emit

**[Verified — 2.0.1 docs, overview/language limitations]** PyScript supports almost all
Python language features **except generators, `yield`, and defining special class methods**
(dunder methods). Modern PyScript does support `try/except`, `with`, classes, dataclasses,
enums, f-strings, comprehensions — the old "no try/except" limitation is long gone (do not
trust stale forum posts on this).

**Compiler rule (locked):** the PyScript code generator must never emit generators,
`yield`, or special class method definitions. Straight-line functions, loops, conditionals,
and pyscript built-ins only. Written down so a future coding session doesn't "optimize"
piston compilation into a generator pattern and produce code that silently fails to parse.

#### `hass` Global Access — Built-ins Only (locked rule)

**[Verified — 2.0.1 docs, configuration]** `hass_is_global` is an optional config parameter
**defaulting to false**. Compiler-generated code must therefore never reference `hass`
directly. Use only pyscript built-ins: `state.get()`/`state.set()`/state variables,
service calls as Python functions, `task.*`, `event.fire()`, `log.*`. If generated code
needed `hass`, every PistonCore user would need a non-default pyscript configuration —
a guaranteed support-ticket generator and a silent-failure mode for users who skip a
setup step. There is no known piston feature that requires `hass` access; if one is ever
found, that feature gets a design decision, not a config requirement.

#### Deployment, Reload, and Restart Semantics

**[Verified — release notes 1.6.0/1.6.1 + docs]** PyScript has watchdog-based
**auto-reload**: files written to `<config>/pyscript` are picked up automatically on
change (auto-reload was fixed in 1.6.1 after breaking in 1.6.0; the watchdog runs in its
own thread as of 1.6.0). The documented reload limitation applies only to
`legacy_decorators` mode, which PistonCore never uses. Third-party claims that pyscript
"requires manual reload" are **false** as of current versions.

**Compiler/deploy rule:** the deploy pipeline should still call the `pyscript.reload`
service explicitly after writing files — not because auto-reload doesn't work, but because
an explicit reload is deterministic: deploy knows *when* the new code is live and can
surface reload errors in the same request/response cycle, matching how the YAML path
handles `automation.reload` (Section 4). Do not depend on watchdog timing in the deploy
flow; treat auto-reload as a nice-to-have for users hand-editing files.

**[Verified]** Script files persist across HA restarts like any other config file —
pyscript is a HACS custom integration, not an addon; there is no "re-deployment after
restart" problem. **[Assumed — needs test on dev HA]** *In-flight tasks* do not survive
restart: a piston mid-`task.wait_until()` (an `on_event` wait, a `followed_by` chain, a
long timer) dies on HA restart and does not resume. This matches Hubitat behavior (a
webCoRE piston mid-wait dies on hub reboot), so it is not a fidelity regression — but it
should be stated in user-facing help for `on_event`/wait-heavy pistons, and confirmed by
a real restart test before the help text claims it definitively.

#### No HA Trace UI — Debug Output Is the Compiler's Job

**[Verified — docs, logging reference]** PyScript executions do not appear in HA's
automation trace UI. Logging goes through HA's Logger component with per-script and
per-function log paths of the form `custom_components.pyscript.file.SCRIPTNAME.FUNCNAME`,
adjustable at runtime via `logger.set_level`.

**Implication for the v2 UI split:** PistonCore owns compile/debug output. YAML-routed
pistons get HA traces for free; PyScript-routed pistons get **only what the compiler
writes in**. The PyScript code generator must emit `log.info()` breadcrumbs at trigger
fire, condition evaluation results, and each action execution, so the PistonCore debug
console has real data to show. The per-function logging path structure means each piston's
log stream is cleanly filterable by its generated function name — the compiler should emit
one top-level function per piston with a deterministic name to exploit this. (Ties into
the Section 6 user notification requirement: the PyScript notice should also mention that
debug detail for these pistons comes from PistonCore's console, not HA's trace viewer.)

#### Version Compatibility Direction

**[Verified — 2.0.0 release notes]** 2.0.0 states support for HASS 2026.5+ with backward
compatibility for earlier HA versions. There has been **no pyscript release since HA
2026.7 shipped** (July 1, 2026) — so any HA 2026.7 internal changes affecting pyscript
are untested by the project itself. No known issues, but if a PyScript-routed piston
misbehaves on 2026.7+, "pyscript hasn't released against this HA version yet" is a valid
first suspect. Re-check the pyscript release page on each HA monthly release, same cadence
as the rest of this document.

### PyScript Context Tracking Feasibility

Physical vs programmatic interaction detection (`context.id`, `context.parent_id`)
needs sandbox validation before the "Which Interaction" wizard step is built.
**Status:** Explicitly deferred. Do not build until validated.

---

## 7. User Experience Gotchas

### Live Fire Test Danger

Test button always executes real actions. No dry-run mode.
Users WILL accidentally trigger real devices during building — lights will flash,
locks will click, speakers will speak.
The confirmation dialog ("Live Fire ⚠ — this will execute real actions") is
mandatory and must be prominent. Consider a global "Test Mode" toggle for v2
that logs instead of fires.

### Automation Mode Behavior Differs From Hubitat

HA automation modes (single/restart/queued/parallel) map to WebCoRE concepts
but behave differently in edge cases. Users migrating from Hubitat may be surprised.
**Document the differences in user-facing help text for the mode picker.**

---

## 8. Things Already Correctly Handled

These limitations were discovered and designed around. Listed here so they are
not re-litigated:

- **PyScript routing** — Full verified feature table now in Section 6. Routing mechanism (`target-boundary.json`) referenced in specs but UNVERIFIED in backend code — confirm or create at the v2 compiler spec (v2 note: the scan lives in the shim save flow per COMPILER_DECISIONS_HOLDING §E). ⚠
- **Binary sensors always report on/off** → Friendly label system in wizard,
  compiled_value always "on"/"off" ✅
- **Entity IDs are compile-time** → entity_ids baked at wizard commit time, static in JSON ✅
- **Loop variable scoping** — Fixed natively in HA 2025.3 (PR #138883). Variables updated inside loop/parallel bodies now correctly propagate to outer scope. The `repeat` loop variable (`repeat.index` etc.) is still intentionally local. Compiler warning for general variable scoping can be removed; the `loop_string_accumulation` PyScript fallback remains correct. ✅ (native fix)
- **Entity IDs never shown to user** → Device picker + role label abstraction ✅
- **HA churn on YAML syntax** → Versioned Jinja2 template system ✅
- **Minimum HA version** → 2023.1 floor documented and checked on connect ✅. Note: variable scoping fix requires HA 2025.3+. PistonCore should consider raising the minimum to 2025.3 before v1 release to avoid the scoping bug for users on older installs.
- **`trigger:` vs `platform:` inside wait_for_trigger** → Compiler always uses
  `trigger:` key inside `wait_for_trigger` blocks. `platform:` is legacy syntax that
  causes silent reload errors in modern HA. ✅
- **Multi-entity triggers and actions** → HA natively accepts entity_id arrays.
  Native YAML: pass array directly. PyScript actions: pass Python list. No expansion needed. ✅

---

## 9. Still Needs a Solution

These are known gaps without a defined solution yet:

- **State value quoting not enforced at compiler level** — `_compile_single_condition` passes `compiled_value` to templates without normalization. HA silently parses unquoted `on`/`off` as booleans, causing state checks to never match. Spec says handled — code does not enforce it. Fix required in S1-7. (Moved from Section 8 — was incorrectly listed as handled.)
- **`wait_for_trigger` timeout not emitted** — Compiler passes `stmt_id` and `at_time` to the wait_until template but does not emit `timeout:` or `continue_on_timeout:`. Pistons will hang forever if the time is missed. Spec says handled — code does not emit it. Fix required in S1-7. (Moved from Section 8 — was incorrectly listed as handled.)
- **Parallel branch `continue_on_error` at the SEQUENCE level (v2 compiler REQUIREMENT):** per-action only is not enough — one offline device kills the whole parallel block. The v1 compiler failed this; bake into the v2 parallel template.
- Entity ID changes flagged by scheduled validation (the v2 deploy design (was DESIGN.md §9.2)) — UX needs work
- Long-running piston timeouts — not yet handled
- Global variable helper race conditions on simultaneous deploy — not yet handled
- Sunrise/sunset negative offset edge cases — needs explicit testing
- Numeric trigger unknown state behavior — needs explicit testing
- HA reload failure UX — partial, needs more robustness
- **Hubitat room assignment (`roomId`/`roomName`) not reachable via HA** — real webCoRE
  shows these because it runs inside Hubitat with direct device-object access; HA's
  Hubitat integration doesn't bridge Hubitat's room concept to any entity/state (confirmed
  2026-07-12: HA Developer Tools > States shows an empty Area column and no room_id/
  room_name entity for a fully-enabled device that DOES expose other custom attributes,
  e.g. `smartDetectType`, fine via Stage 3.2's fallback). Would need HA's own Area registry
  as a substitute data source (different API, not currently part of the device pipeline) —
  not pursued yet, Jeremy: "not hunting it down for now."

### ⚠️ Validation Required — Missing Single-Device Entity Behavior

**Must test before implementing the single-device hard flag in the (future) v2 deploy spec (was DESIGN.md §15.6).**

Unknown: what does HA actually do when an automation references a missing entity?

Questions to answer with real testing:
1. Does HA error on reload and disable the automation, or does it load the automation and error only at runtime?
2. Does HA behave differently for a missing trigger entity vs a missing condition entity vs a missing action target entity?
3. Does the behavior differ between native YAML automations and PyScript files?
4. Is the error surfaced clearly enough to catch in PistonCore's reload error handler, or does it fail silently?

**How to test:** Create a simple test automation in HA that references a known entity. Remove the entity (or rename it so it no longer exists). Reload automations. Observe what HA does — check the HA log, check whether the automation is marked as disabled, check what error (if any) is returned by the reload call.

Results go here and inform the implementation of the hard flag logic in PistonCore. Do not implement the single-device missing deploy block until this is validated.

---

## 10. Non-Device Command Reproducibility (WebCoRE location/emulated → HA)

**Scope:** This section is ONLY about WebCoRE's **non-device** commands — the "location" and
"emulated" groups of the with-block "Do…" picker. **Device commands are out of scope here:**
anything that is a real HA entity is pulled natively into the device picker as an entity and
never appears on any cut list. The question here is only: for a non-device WebCoRE command,
can HA cleanly reproduce the *result*? If yes → it STAYS in the wizard. If there is no clean
HA reproduction → it is CUT from the wizard and listed below.

**This is the line as of HA 2026.6 (June 2026) — NOT forever.** HA gains native capability
over time (e.g. variable scoping went native in 2025.3; `continue_on_error` hit the UI in
2026.3). Re-review periodically. A command cut today returns to the wizard if HA later gains
a clean way to reproduce it. **Rule:** if HA has a *built-in* for it, use HA's built-in
(do not reach for optional add-ons when a native path exists); only if there is no built-in
and no other clean path does it go on the cut list.

### 10.1 REPRODUCIBLE — stays in the wizard

> **What "Verified" means per row:** "...docs 2026.6" = the current HA doc was read this
> session confirming the action exists. "Existing path" = PistonCore already compiles this
> (verified in code, not necessarily re-checked against the newest HA doc). Neither means the
> WebCoRE→HA mapping was tested end-to-end for identical behavior — see §10.4.

| WebCoRE command | HA reproduction | Verified |
|---|---|---|
| Wait / Wait for time / Wait for date & time / Wait randomly | Native `delay`, `wait_for_trigger`, `wait_template` | Existing PistonCore path (`_saveLocationCmd`); script-syntax docs 2026.6 |
| Set variable | Native `variables:` action | Script-syntax docs 2026.6 (variable scoping fixed 2025.3) |
| Log to console | Native `logbook.log` / `system_log.write` | Existing path |
| Execute piston / call_piston | `script.turn_on` / `automation.trigger` on the compiled target | Existing path |
| Set location mode | Native `input_select` helper: `input_select.select_option` sets a named mode state; state-change is a usable trigger. (No HA *built-in* "location mode" — you create the helper — but the result is fully reproduced.) | input_select docs, June 2026 |
| Make a web request | Native **`rest_command`** (GET/POST/PUT/DELETE, templated URL/payload/headers/auth, response via `response_variable`) — reproduces WebCoRE web request incl. JSON response handling | rest_command docs, June 2026 |
| Read from file / Write to file | Native **File integration** (enabled by default): `file.read_file` (→ `response_variable`) and the file notify entity for writes. Caveat: paths must be in `allowlist_external_dirs` | File integration docs, June 2026 |
| HSM status (Set Hubitat Safety Monitor) | HA ships a **built-in `alarm_control_panel`** with arm_home/arm_away/arm_night/disarm/triggered states + arm/disarm actions. Use HA's built-in alarm entity. (NOTE: WebCoRE *custom* HSM monitoring rules don't map 1:1 — only the arm/disarm/status maps cleanly; custom-rule fidelity needs per-piston validation) | alarm_control_panel docs, June 2026 |
| Capture attributes to store / Restore attributes from store | Native `scene.create` with `snapshot_entities` (capture) + `scene.turn_on` (restore) — saves current entity states and restores them | scene docs, June 2026 |
| Send an IFTTT Maker event | Reproducible as a webhook fire via native `rest_command` to the target URL. RENAMED in the picker to "Webhook" (principle 6) — IFTTT is a specific service; the real action is firing a webhook | rest_command docs, June 2026 |
| LIFX – Breathe / Pulse / Set State / Activate scene / Toggle | Native LIFX integration effect actions: `lifx.effect_pulse` (with mode: breathe/blink/ping/strobe/solid — old `lifx_effect_breathe` folded into this), `lifx.effect_colorloop`, `lifx.effect_move`, `lifx.set_state`, `effect_stop`; scenes/themes via `select.select_option`. Toggle/basic = ordinary `light` entity. | LIFX integration docs, June 2026 |

### 10.2 CUT — no clean HA reproduction as of 2026.6 (Hubitat/WebCoRE-platform artifacts)

These are constructs of the Hubitat/WebCoRE platform itself, not automation actions HA has
an equivalent for. Cut from the wizard; logged here.

| WebCoRE command | Why no clean HA reproduction |
|---|---|
| Piston tiles (set tile, tile colors/footer/text/title/mouseover, clear tile) | WebCoRE-dashboard-specific UI construct; HA has no piston-tile concept. (HIGH confidence — pure WebCoRE UI.) |
| Set piston state / Pause piston / Resume piston | Operate on the WebCoRE engine's own run state; no HA analog to a "piston" runtime to pause/resume. `automation.turn_off`/`turn_on` disables future triggers but cannot pause a mid-run execution — WebCoRE pause/resume preserved mid-run state, resuming from the paused point. These are fundamentally different behaviors. (ASSUMED — reasoning from HA automation behavior, not verified by end-to-end test. HIGH confidence the distinction is real.) |

### 10.3 EMULATED group — not v1 (unchanged)

WebCoRE "emulated" commands (WebCoRE synthesizing a command for a device that lacks it
natively) are flagged NOT-v1 in WITH_BLOCK_TASK_FRAMEWORK.md §5.2. Most don't map cleanly to
HA. Not researched per-command here; the group renders for fidelity but isn't implemented.

### 10.4 Confidence + completeness note

**Research COMPLETE for the non-device command set as of 2026.6 (Session 73)** — every
non-device command resolved to a definitive stays/cut, so the wizard can be loaded from this
without "verify later" gaps. The 10.1 entries are confirmed against current HA docs (sources
dated June 2026). The only cuts (10.2) are piston tiles and piston engine state — pure
WebCoRE/Hubitat-platform constructs with no HA analog (HIGH confidence). There are no
remaining MED/unresolved items.

**Caveat on what "reproducible" means:** §10.1 means *HA has an action that should reproduce
the result*, confirmed to exist — it is NOT end-to-end behavior-tested. Known example:
`scene.create`/`snapshot_entities` has a documented quirk where an entity unavailable at
snapshot time breaks restore. Real-HA testing per mapping is still wise before v1; "exists
and is the right action" is not "proven byte-identical to WebCoRE."

**Not permanent:** this is the line as of 2026.6 — re-review on major HA releases.

---

*Add to this document whenever a new HA limitation is discovered — from AI review,
community feedback, or real testing. This saves re-research time.*

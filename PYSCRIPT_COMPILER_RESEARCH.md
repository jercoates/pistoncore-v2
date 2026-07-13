# PistonCore — PyScript Compiler Research (codegen layer)

**Status:** Research holding doc — feeds the v2 compiler spec's PyScript codegen sections.
**Version:** 1.0 (July 2026 — researched against the full PyScript 2.0.1 reference manual,
hacs-pyscript.readthedocs.io, plus 2.0.0/2.0.1/1.7.0/1.6.x release notes)
**Position in authority chain:** research input, NOT authority. Routing decisions live in
COMPILER_DECISIONS_HOLDING.md §E. Runtime constraints live in HA_LIMITATIONS.md §6. This doc
covers the layer below routing: **what the emitted PyScript code looks like and why**.
**Tagging convention (every claim carries a verified-by source):**
- **[Verified — ref §<section>]** = read directly in the PyScript 2.0.1 reference manual
  (hacs-pyscript.readthedocs.io/en/latest/reference.html), 2026-07-12. `§<section>` names the
  manual section (e.g. §@state_trigger, §Persistent State, §Language Limitations).
- **[Verified — rel <version>]** = read in that version's GitHub release notes
  (github.com/custom-components/pyscript/releases), 2026-07-12.
- **[Assumed]** = reasoned, needs a test on dev HA before it can be tagged Verified.
- **[Decision]** = PistonCore choice, not a PyScript fact — cite the doc where it locks.

---

## 0. The headline findings (read this first)

1. **⚠ CORRECTION to an existing path assumption:** `/config/pyscript/pistoncore/*.py` would
   **NOT be autoloaded** by PyScript. [Verified — ref §Configuration, autoload list] PyScript
   only autoloads: top-level
   `pyscript/*.py`, `pyscript/scripts/**/*.py` (recursive), and `pyscript/apps/` (only with a
   config entry). An arbitrary subdirectory like `pyscript/pistoncore/` is invisible to the
   loader. HA_LIMITATIONS.md §4 (File Permissions in Addon) currently names
   `/config/pyscript/pistoncore/` — that path must change to
   **`/config/pyscript/scripts/pistoncore/`**. Port this correction to HA_LIMITATIONS.md.

2. **PyScript has documented primitives that ARE the webCoRE semantics, nearly verbatim** —
   `stays` = `state_hold`, edge-triggered `changes to` = `state_hold_false=0`, `was` =
   `.old`, piston restrictions = `@state_active`/`@time_active`, `sunrise + 30m` offset
   syntax is literally PyScript's native time spec. Section 3 is the full mapping. The
   compiler should compose these primitives instead of hand-rolling the semantics in
   generated Python — less emitted code, and the fidelity burden shifts onto PyScript's
   own tested implementation.

3. **All four HA execution modes are reproducible in PyScript** (Section 6) — including
   webCoRE-style restart semantics via `task.unique`, which also solves the
   kill-old-instance-on-redeploy problem via a documented file-preamble mechanism.

4. **`state.persist` gives PyScript pistons real persistent piston state** (survives HA
   restart, `pyscript.*` domain only) — a candidate resolution for the §E5 `exit` value
   open decision and for webCoRE "piston state" generally. (Section 7.)

---

## 1. Template architecture — versioned emission, zero hardcoded code strings

**[Decision — extends the locked "versioned Jinja2 template system" decision from the YAML
path]** PyScript code generation goes through the same Jinja2 template system as YAML
compilation. Rationale proven twice this year already: the ESPHome 2026.3→2026.6 config break,
and PyScript's own 2.0.0 decorator subsystem rewrite (May 2026). When PyScript changes,
**only template files change** — the compiler's Python source never contains emitted-code
strings.

Layout (mirrors the YAML template versioning):

```
templates/
  yaml/<ha_version_band>/...        # existing
  pyscript/2.x/                     # this doc targets the 2.x band
    file_header.py.j2               # imports, preamble task.unique, state.persist calls
    trigger_state.py.j2             # @state_trigger block
    trigger_time.py.j2              # @time_trigger block
    trigger_event.py.j2             # @event_trigger block
    active_state.py.j2              # @state_active from piston restrictions
    active_time.py.j2               # @time_active from piston restrictions
    exec_mode.py.j2                 # @task_unique / lock scaffold per Section 6
    func_signature.py.j2            # kwargs → system-variable bindings per Section 5
    condition_eval.py.j2            # per-condition evaluation w/ value-coercion guards
    action_call.py.j2               # service call
    wait_duration.py.j2             # task.sleep
    wait_until.py.j2                # task.wait_until (state/time/timeout forms)
    on_event.py.j2                  # task.wait_until event form
    log_breadcrumb.py.j2            # debug-console breadcrumbs (HA_LIMITATIONS §6)
    service_registration.py.j2      # @service execute entry point per Section 8
```

Rules:
- **Version band, not exact version.** Templates target "PyScript 2.x". A `pyscript/3.x/`
  directory is created only when a breaking release lands. The deploy flow records which
  PyScript version was present at deploy time (readable from the integration's manifest via
  the HA API — [Assumed] exact endpoint, verify in a coding session) so a version-mismatch
  warning can be surfaced later.
- **One construct = one snippet template.** Matches §G's per-statement sketches one-to-one,
  so §G graduates from sketch to spec by pointing each statement type at its template file.
- **No emitted line originates in compiler .py source.** Same data-driven rule as the
  routing table (§E1) and the vocab file. This is what makes "PyScript changed again"
  a template-edit, not a code session.

---

## 2. Deployment layout, global contexts, and lifecycle

All claims in this section [Verified — ref §Configuration, §Global Context, §Reloading
Scripts] unless tagged otherwise.

**File layout:** one piston = one file at `/config/pyscript/scripts/pistoncore/<piston_id>.py`.
- `scripts/**` autoloads recursively — this is the ONLY sanctioned subdirectory layout for
  PistonCore's purposes (`apps/` requires a per-app yaml config entry; top-level is user turf).
- Each file gets its **own isolated global context**, named `scripts.pistoncore.<piston_id>`.
  Pistons cannot see each other's globals — piston isolation for free.
- Each piston gets its **own log path**:
  `custom_components.pyscript.scripts.pistoncore.<piston_id>.<function_name>` — per-piston,
  per-function log level control at runtime via the `logger.set_level` service, **no HA
  restart needed**. PistonCore's debug console can turn a single piston's logging to `debug`
  on demand and back off after. This is the PyScript-side answer to webCoRE's per-piston
  logging levels (None/Minimal/Medium/Full).

**Reload on deploy:** PyScript auto-reloads changed files, and reload is **per-file
granular** — only changed files (plus dependents) reload, so deploying piston A never
touches running piston B. The deploy flow still calls `pyscript.reload` explicitly with
`global_ctx="scripts.pistoncore.<piston_id>"` for a deterministic, per-piston,
error-surfaced reload (HA_LIMITATIONS §6 rule, now with the exact mechanism).

**Kill the old instance on redeploy:** reload does NOT stop a currently-running triggered
function — a mid-`wait` piston from the *old* code keeps running. The documented fix:
`task.unique("pistoncore_<piston_id>")` **in the file preamble** (outside any function),
which executes on every load/reload and terminates any running task that claimed that name.
The compiler emits this in `file_header.py.j2` unconditionally. This means: redeploying a
piston kills its in-flight old-version execution — which is exactly webCoRE's behavior when
you save a piston mid-run. Verbatim fidelity by accident.

**Pause / disable a PyScript piston:** [Verified — ref §Configuration, `#` filename rule] a
filename starting with `#` is skipped by
the loader, and renaming triggers an automatic reload — the documented enable/disable
mechanism ("commenting" the filename). So piston pause for the PyScript target = rename to
`#<piston_id>.py` (+ preamble task.unique consideration: the rename-reload deletes the
context and its triggers). This is future-trigger pause, equivalent to `automation.turn_off`
on the YAML target — it does NOT preserve mid-run state, so the §10.2 cut of webCoRE's
mid-run pause/resume stands. [Decision] use file-rename as the PyScript pause mechanism so
both targets have symmetric pause behavior.

**task.unique names are per-global-context.** [Verified — ref §Task unique] Uniqueness names in one piston's
file don't collide with another piston's — piston-scoped `cancel_pending_tasks` is automatic.
Consequence: task.unique can NEVER cancel across pistons. If a webCoRE piston semantic ever
needs cross-piston cancel, task.unique is not the tool (would need event.fire + a listener).
Flag if it ever comes up; no known webCoRE feature needs it.

---

## 3. Tier-1 VERBATIM mappings — webCoRE semantic → documented PyScript primitive

This is the core "use as much verbatim as we can" table. **Every row is
[Verified — ref §<the decorator/function named in the PyScript primitive column>]** — e.g.
the `stays` row is verified by ref §@state_trigger (state_hold), the restrictions rows by
ref §@state_active / §@time_active, the wait rows by ref §Task sleep / §Task waiting, the
webhook row by ref §@webhook_trigger. Where the "Why it's verbatim" cell quotes wording,
that wording is from the named section. The compiler should emit the primitive, not
re-implement the
semantic in generated Python.

| webCoRE semantic | PyScript primitive | Why it's verbatim |
|---|---|---|
| trigger: `changes to X` (edge) | `@state_trigger("e == 'X'", state_hold_false=0)` | Docs: `state_hold_false` makes the trigger **edge-triggered** ("triggers on a False to True transition") — expression must go false before it can fire again. That is precisely webCoRE's changes-to: fires on the transition, not on every re-report of the same value. |
| trigger: `stays X for N` | `state_hold=N` | Docs: delays the trigger N seconds; "if the state trigger expression changes back to False during that time, the trigger is canceled and a wait for a new trigger begins." That sentence IS webCoRE's `stays` definition. |
| condition operand: `was` (prior value) | `.old` in trigger expr: `e.old == 'A' and e == 'B'` | Docs: prior value available as `domain.name.old`, incl. `domain.name.old.attr` for attributes. Direct `changes from A to B`. |
| trigger: `changes` (any change) | `@state_trigger("domain.entity")` plain-name form | Docs: plain name = trigger on any value change (also fires on create/delete with old/new = None — see Section 9 guard). |
| attribute triggers | `domain.entity.attr` / `domain.entity.*` forms | Native, incl. any-attribute wildcard. |
| piston restrictions: "only when <condition>" | `@state_active("expr")` | Docs: evaluated on ANY trigger; if false, trigger ignored. It even evaluates against the trigger-time value (not the possibly-already-changed current value) — better-than-naive fidelity, matches webCoRE evaluating against the event that woke it. One per function; combine restrictions with and/or inside the expr. |
| piston restrictions: "only between <time1> and <time2>" | `@time_active("range(start, end)")` | Docs: range with end < start wraps past midnight ("sunset − 20min, sunrise + 15min" is the doc's own example) — webCoRE's overnight between-times handled natively. |
| restrictions: "NOT between" | `@time_active("not range(...)")` | Documented `not` prefix; multiple positive args OR, negative args AND. |
| trigger: "at sunrise/sunset ± offset" | `@time_trigger("once(sunrise + 30m)")` | The offset grammar (`sunrise + 30m`, `sunday sunset - 1.5 hour`, s/m/h/d/w units, float allowed) is PyScript's native datetime spec. WebCoRE's phrasing compiles almost character-for-character. Also `noon`/`midnight`. |
| trigger: "every N <units> between X and Y" | `@time_trigger("period(start, interval, end)")` | Native periodic form with optional end. |
| monthly / yearly / dom / month restrictions | `@time_trigger("cron(...)")` | Already in routing table §E2; croniter grammar incl. `*/5`, ranges, lists, optional 6th seconds field. |
| "once per year on <date>" (birthday-style) | `once(mm/dd hh:mm)` — year omitted = annually | Documented partial-date semantics. |
| debounce / min time between runs | `@time_active(hold_off=N)` | Docs: "rate-limiting trigger events or debouncing a noisy sensor." 2.0.0 added `hold_off=None` support. |
| wait N (duration) | `task.sleep(N)` | Float-capable; never `time.sleep` (blocks the loop — logged warning). |
| wait until condition / wait for time, w/ timeout | `task.wait_until(state_trigger=..., time_trigger=..., timeout=...)` | Same trigger grammar as the decorators; returns dict with `trigger_type` = `"state"/"time"/"event"/"timeout"/"none"`. `"none"` = time spec is entirely in the past — maps onto the §2 (HA_LIMITATIONS) wait-for-passed-time edge: the compiler branches on it instead of hanging. |
| on_event / followed_by | `task.wait_until(event_trigger=["type", "expr"])` | Per routing table; event-data filter expr supported. See Section 10 caveat (missed-event race). |
| external piston execution URL | `@webhook_trigger("<id>")` at `hass_url/api/webhook/<id>` | webCoRE's per-piston external URL, verbatim concept. POST/PUT (configurable), payload dict handed to the function, `local_only` flag. Not v1-required; recorded because it's a free fidelity win later. Note: a webhook_id is exclusive to either an HA automation or PyScript, not both. |
| $args-style parameter passing on execute | `@service` keyword params / `event.fire(..., **kwargs)` | Section 8. |

**[Decision] Tier structure for the codegen spec:**
- **Tier 1 (table above):** documented primitive = the semantic. Always preferred.
- **Tier 2 (composed):** small compositions of Tier-1 pieces — followed_by chains
  (sequential `task.wait_until` with a shared deadline), XOR (`sum([...]) == 1`), switch
  fall-through (if/elif without early exit), `only_on_wom` runtime check (§E6). Already in
  the routing table; the templates in Section 1 are where they live.
- **Tier 3 (emulated with a recorded caveat):** anything where fidelity is approximate —
  each gets a CompilerWarning code and an entry in Section 10.

---

## 4. Anatomy of a compiled PyScript piston

[Decision — assembly order for the templates; every element below is individually Verified
against ref §Function Trigger Decorators (multi-decorator + OR'd args), ref §@task_unique,
and ref §@service.]

```python
# ── file_header.py.j2 ──────────────────────────────────────────
# PistonCore compiled piston — <piston name> (<piston_id>)
# Generated <timestamp> — template band pyscript/2.x — DO NOT EDIT
from datetime import datetime, timedelta

task.unique("pistoncore_<piston_id>")          # kill in-flight old version on redeploy
state.persist("pyscript.pistoncore_<piston_id>_state",
              default_value="idle")            # only if piston uses piston-state (Sec. 7)

# ── trigger_*.py.j2 + active_*.py.j2 + exec_mode.py.j2 ────────
@state_trigger("binary_sensor.front_door == 'open'", state_hold_false=0)
@state_active("input_select.pistoncore_location_mode == 'Home'")   # restrictions
@time_active("range(sunset - 30m, sunrise)")                       # restrictions
@task_unique("pistoncore_<piston_id>")          # execution mode (Section 6)
def piston_<piston_id>(trigger_type=None, var_name=None, value=None,
                       old_value=None, **kwargs):
    # ── func_signature.py.j2 binds webCoRE system variables (Section 5)
    log.info(f"[<piston_id>] triggered: {var_name} {old_value}→{value}")   # breadcrumb
    ...condition_eval / action_call / wait_* blocks...

# ── service_registration.py.j2 (Section 8) ────────────────────
@service("pyscript.pistoncore_<piston_id>_execute")
def piston_<piston_id>_execute(**kwargs):
    """PistonCore: execute piston '<piston name>'."""
    piston_<piston_id>(trigger_type="service", **kwargs)
```

Notes on why this shape:
- **One top-level trigger function per piston, deterministic name** — gives the stable
  per-function log path (Section 2) the debug console filters on.
- Multiple webCoRE triggers on one piston = multiple decorators on the one function
  ([Verified — ref §Function Trigger Decorators] a function accepts any number/mix of
  trigger decorators; multiple
  `@state_trigger` string args are OR'd). `trigger_type` + `var_name` tell the body which
  fired — no dispatcher function needed.
- The decorators have no effect when the function is called directly from Python
  ([Verified — ref §Function Trigger Decorators]) — which is exactly why the `@service`
  wrapper can invoke the same body for
  Test/execute without fighting the triggers.

---

## 5. webCoRE system variables → trigger kwargs (verbatim data plumbing)

[Verified — ref §@state_trigger (trigger kwargs), §@time_trigger (trigger_time),
§@event_trigger (native-typed event data)] When a trigger fires, PyScript passes keyword
args to the function. These map
directly onto webCoRE's event system variables:

| webCoRE system variable | PyScript source |
|---|---|
| `$currentEventDevice` | `var_name` kwarg (the entity whose change caused the trigger) |
| `$currentEventValue` | `value` kwarg |
| `$previousEventValue` | `old_value` kwarg |
| `$currentEventAttribute` | derivable from `var_name` when it's a `domain.entity.attr` form |
| `$currentEventDate` (time triggers) | `trigger_time` kwarg (exact datetime of the spec that fired; `"startup"`/`"shutdown"` for those) |
| trigger source discrimination | `trigger_type` kwarg (`"state"/"time"/"event"/"service"`) |
| event data (on_event) | event params passed as kwargs, native types preserved (event data is NOT string-coerced, unlike state) |

Also [Verified — ref §@state_trigger (kwargs param)]: the decorators accept a `kwargs={...}`
dict of **extra** parameters passed
through to the function — the compiler can stamp each trigger decorator with
`kwargs={"stmt_id": "<webcore statement id>"}` so breadcrumb logs identify *which piston
statement's trigger* fired, tying the debug console back to the dashboard's piston view.
(Caution: [Verified — ref §@state_trigger] extra kwargs raise an exception if the function
signature lacks a
matching keyword — the emitted signature always ends in `**kwargs` to make this safe.)

Edge to encode in `func_signature.py.j2`: [Verified — ref §@state_trigger
(state_check_now)] on a `state_check_now` immediate fire,
only `trigger_type` is passed (no `var_name`/`value`) — all bindings default to `None`, and
$currentEventDevice-dependent expressions must tolerate None. Same for `.old` being None on
first-ever set.

---

## 6. Execution modes — full parity table

WebCoRE piston "executes in" semantics / HA automation `mode:` — all four reproducible:

| HA mode (webCoRE analog) | PyScript mechanism | Status |
|---|---|---|
| `parallel` | Default — every trigger spawns an independent task ([Verified — ref §Tasks are Asynchronous]) | Verbatim, zero code |
| `restart` (webCoRE default-ish: new event supersedes) | `@task_unique("pistoncore_<id>")` — new instance kills the running one ([Verified — ref §Task unique]) | Verbatim, one decorator |
| `single` (skip if running) | `@task_unique("pistoncore_<id>", kill_me=True)` — NEW instance dies if one is already running ([Verified — ref §Task unique, kill_me]) | Verbatim, one decorator |
| `queued` | `asyncio.Lock` held for the function body — docs explicitly name `asyncio.Lock` as the serialization tool ([Verified — ref §Tasks are Asynchronous]) | Composed (Tier 2), small template |

[Decision needed — carry to §D/§E]: what does the piston JSON's execution-mode field (or
absence) map to by default? Standing rule says "what webCoRE does": webCoRE serializes
piston executions per-piston via its semaphore (queued-ish, with a wait cap), which argues
`queued` as default. HA automations default to `single`. Do not silently pick — one line in
the compiler spec, decided once. Whatever is chosen applies identically to the YAML target's
`mode:` so both targets agree.

---

## 7. Piston state and persistence — `state.persist`

[Verified — ref §Persistent State + §state.persist] `state.persist(entity_id,
default_value=None, default_attributes=None)` makes a
`pyscript.*`-domain entity survive HA restarts (value + attributes). Must be called at load
time — i.e., in the file preamble, which re-runs on every parse. Writing is plain assignment
(`pyscript.pistoncore_<id>_state = "..."`) or `state.set()` with attributes.

What this buys:
- **webCoRE "piston state" / exit-with-value (§E5 open decision):** the PyScript target can
  write the exit value to `pyscript.pistoncore_<piston_id>_state` — restart-proof, visible
  in Developer Tools, readable by other pistons on either target (it's a normal entity).
  This is a concrete candidate to close §E5 for the PyScript path; the YAML path would use
  the same entity written via `python_script`-free means (`input_text` helper or the
  pyscript entity set from YAML is NOT possible — [Verified — ref §state.persist,
  pyscript-domain restriction] only pyscript can persist `pyscript.*` entities, so the YAML
  target would still need a helper. §E5 stays open for
  the native target; PyScript half is solved).
- **followed_by / sequence progress** across restarts if ever wanted ([Assumed] design
  choice — in-flight tasks still die on restart per HA_LIMITATIONS §6, but persisted
  progress state could let a restarted piston know a sequence was mid-flight).
- Attributes on the state entity can carry structured data (attributes keep native types,
  [Verified — ref §State variables functions, state.set note]) — e.g., `last_run`, `last_trigger_device`, run counters for the piston list UI.

[Decision] Namespace: everything under `pyscript.pistoncore_<piston_id>_*`. Never touch
`pyscript.*` names PistonCore didn't create.

---

## 8. Cross-piston execution, the Test button, and external calls

[Verified — ref §@service] `@service("DOMAIN.SERVICE")` registers the function as a real HA
service;
docstring becomes the service description (yaml-form docstring gives full field selectors in
Dev Tools); called with keyword params, `trigger_type="service"`; `supports_response`
available if a piston should ever return data to a caller.

The compiler registers `pyscript.pistoncore_<piston_id>_execute` per piston (Section 4).
That single mechanism gives:
- **webCoRE "Execute piston" (call_piston)** — either target calls the service: YAML target
  emits a service call action; PyScript target calls `service.call(...)` or just the
  function name. Cross-target piston calls work with no special casing (§G call_piston
  sketch gets its concrete PyScript-side answer).
- **The Test / Live-Fire button** for PyScript pistons — PistonCore's backend fires the
  service via the HA API, identical plumbing to triggering a YAML script. No file-touching,
  no fake state changes.
- **$args:** service call keyword params flow into `**kwargs` → bind to webCoRE `$args`.
  [Verified — ref §@event_trigger + §@service] event/service params keep native types.

[Verified — ref §Service Calls, service.has_service] Also available if ever needed:
`service.has_service(domain, name)` — the
compiled piston (or the deploy validator) can check a notify target still exists before
calling (ties to §C1 stable-target-reference resolution at compile time; a runtime
existence check is a possible belt-and-suspenders, [Decision] whether to emit it).

---

## 9. Value coercion and unavailable-entity guards (condition_eval template rules)

All claims [Verified — ref §State Variables] except where a release note is cited:

- **State values are always strings.** Raw `int(sensor.x)` throws on `unknown`/
  `unavailable`. The forgiving helpers shipped in 1.7.0 [Verified — rel 1.7.0, "StateVal
  conversion helpers"] and are documented on every state value [Verified — ref §State
  Variables]:
  `as_float(default=None)`, `as_int(default=None)`, `as_bool(default=None)`,
  `as_round(...)`, `as_datetime(default=None)`, plus `is_unknown()`, `is_unavailable()`,
  `has_value()`.
- **[Decision — locked rule for condition_eval.py.j2]:** numeric comparisons are ALWAYS
  emitted through the forgiving helpers, never bare casts:
  `sensor.temp.as_float()` with an explicit None-check branch, or
  `(v := sensor.temp.as_float(default=None)) is not None and v > 50`.
  This directly de-fangs the HA_LIMITATIONS §2 numeric unknown/unavailable edge on the
  PyScript target — the failure mode becomes a defined false + breadcrumb log instead of an
  exception or silent weirdness. (Trigger *expressions* are safer already: [Verified — ref
  §@state_trigger, undefined-state note] inside
  `@state_trigger` strings, undefined states/attrs/`.old` evaluate to None instead of
  throwing — but explicit `int()`/`float()` casts inside the expression still throw on
  non-numeric strings, so trigger expressions with numeric compares should ALSO be emitted
  with a None/has_value guard or string-compare form.)
- **Any-change triggers fire on entity create and delete** (`old_value is None` /
  `value is None` respectively) — condition_eval and breadcrumbs must tolerate both.
- **Timestamps for free:** virtual attributes `last_changed` / `last_updated` /
  `last_reported` (UTC) on every entity — these are webCoRE's `$device.lastActivity`-style
  operands; no extra plumbing. (Take precedence over same-named real attributes;
  `state.getattr()` reaches a shadowed real attribute.)
- **Service-name collision trap:** [Verified — ref §State Variables, service-priority note]
  service names take priority over state
  variable names on the rare collision — `state.get("name")` is the unambiguous accessor.
  [Decision] condition_eval emits `state.get("domain.entity")` (string-name form) rather
  than bare identifiers everywhere — dodges the collision class entirely and is
  string-templating-friendly since entity_ids arrive as JSON data anyway.

---

## 10. Fidelity caveats and never-emit rules

**Never-emit list (extends HA_LIMITATIONS §6 language-limitations rule):**
| Construct | Why | Verified by |
|---|---|---|
| generators / `yield` / dunder methods | unsupported (existing rule) | ref §Language Limitations |
| `async def` on pyscript functions | documented to NOT behave like real async — call executes instead of returning a coroutine. `async`/`await` keywords are optional and unnecessary; emit plain `def` | ref §Language Limitations |
| `exit()` | documented to potentially **crash all of Home Assistant** | ref §Language Limitations, citing pyscript issue #811 |
| `time.sleep()` | blocks the event loop (pyscript logs a warning and substitutes) — always `task.sleep()` | ref §Task sleep; rel 1.5.0 (warning added) |
| `open`/`read`/`write`/blocking I/O | not supported in pyscript / blocks the loop; file ops route through HA services (File integration per HA_LIMITATIONS §10.1), never Python I/O | ref §Avoiding Event Loop I/O |
| `print()` for real output | it's just `log.debug` alias; emit explicit `log.*` | ref §Logging |
| bare `hass` | existing rule (hass_is_global defaults false) | ref §Configuration + §Access to Hass |
| assignments to the names `state`, `task`, `log`, `event`, `service`, `pyscript` | assigning these shadows the entire built-in namespace under that prefix — generated local variables must never use these names (template lint rule) | ref §Functions, shadowing note |
| imports outside a fixed minimal set | default import allowlist is restricted; `allow_all_imports` must never be required. [Assumed] `datetime` is safe (used throughout official docs/examples); the exact default allowlist should be read from pyscript source (`ALLOWED_IMPORTS`) in a coding session and pinned in the compiler spec. Until then: emit imports only for `datetime`, and prefer built-ins over imports everywhere | ref §Importing (restriction Verified; safe-set Assumed) |

**Fidelity caveats (Tier 3 register — each gets a CompilerWarning code):**
- **`task.wait_until` event race** — [Verified — ref §Task waiting, decorator-vs-wait_until
  comparison] documented at length: wait_until only
  monitors while it's waiting; events landing between chained waits are missed. Affects
  `followed_by` and any `on_event` placed mid-sequence. WebCoRE's own subscriptions were
  persistent, so this is a genuine (small) fidelity gap → `CompilerWarning:
  FOLLOWED_BY_EVENT_GAP`. Mitigations exist (persistent decorator + flag variable) but cost
  complexity; record, don't build yet.
- **DST semantics choice** — [Verified — ref §@time_trigger, DST paragraph] `cron()` =
  wall-clock across DST (6pm stays 6pm);
  `period()` = fixed duration (drifts an hour across DST). WebCoRE time-of-day scheduling is
  wall-clock → [Decision] daily/weekly "at time" compiles to `once()`/`cron()` forms, never
  `period()` spanning days. `period()` is reserved for interval semantics ("every 15
  minutes") where fixed duration is the intent.
- **`state_hold` argument snapshot** — [Verified — ref §@state_trigger, state_hold notes]
  after a `stays` fires, the function
  receives the variable values from the *initial* trigger, and `@state_active`/`@time_active`
  are evaluated post-hold against that initial value. [Assumed] this matches webCoRE's
  stays evaluation closely enough; verify against webCoRE source behavior if a discrepancy
  is ever reported.
- **Same-value writes don't re-trigger** — [Verified — ref §@state_trigger, same-value
  note] HA emits no state-change event when an
  entity is set to its current value+attributes, so `changes` won't fire on a same-value
  report. Matches HA-wide behavior (YAML target identical); note in help text for users
  expecting Hubitat's every-report events.
- **In-flight tasks die on HA restart** — already recorded (HA_LIMITATIONS §6, [Assumed],
  restart-test pending).

---

## 11. Items to port to other docs

1. **HA_LIMITATIONS.md §4:** deploy path correction —
   `/config/pyscript/pistoncore/` → `/config/pyscript/scripts/pistoncore/` (Section 0.1
   here). Also worth adding the §2 lifecycle facts (per-file reload granularity, preamble
   task.unique redeploy-kill, `#`-rename pause) to §6 there.
2. **COMPILER_DECISIONS_HOLDING.md §E5:** PyScript half of exit-value has a concrete
   mechanism (`state.persist`, Section 7). Native-target half still open.
3. **COMPILER_DECISIONS_HOLDING.md §D (open):** execution-mode default decision
   (Section 6), and whether Test-button = registered `@service` call becomes the locked
   Test mechanism for the PyScript target (Section 8).
4. **§G sketches:** each statement sketch should gain a `template:` pointer per Section 1's
   inventory when §G graduates into the v2 compiler spec.

## 12. Open items / next research

- Read pyscript's `ALLOWED_IMPORTS` from source; pin the compiler's permitted import set.
- Verify the HA API surface for reading the installed pyscript version at deploy time.
- Dev-HA tests: restart-kills-in-flight-wait ([Assumed] → Verified), `state_hold_false=0`
  edge behavior against a chatty sensor, `task.wait_until` returning `"none"` on a past
  time spec, `@service` registration visible in Dev Tools with the yaml docstring.
- Decorator re-test pass against 2.0.1+ per the HA_LIMITATIONS §6 re-test flag — the
  Section 4 anatomy is the exact set of shapes to test.

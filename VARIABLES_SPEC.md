# PistonCore v2 — Variables Specification

**Status:** PARTIAL — scope, typing, persistence, and storage specified.
Casting rules, system variables, and list runtime semantics BLOCKED pending
`webcore-piston.groovy`.

## Sources

| Source | Version | Role |
|---|---|---|
| `app.js` (dashboard) | v0.3.114.20220203 | Wire format, design-time evaluation |
| `webcore.groovy` (parent app) | v0.3.114.20220203 | Global variable storage & lifecycle |
| `piston.module.html` (dashboard) | v0.3.114.20220203 | Authoritative type lists, persistence semantics |
| `webcore-piston.groovy` | — | **NOT YET SUPPLIED** — casting, system vars, list runtime |

Every claim is marked `Verified — <source, line>`, `Assumed — needs test`, or
`Decision — PistonCore choice`.

---

## Variable classes — scope of this document

webCoRE exposes several distinct classes of variable. They differ in who owns
them, whether they are writable, and — critically — how each must compile to
Home Assistant. **Sections 1–11 below cover Class A only.** The other classes
are specified here and enumerated by the verification tasks in §12.

| Class | Examples | Writable | PistonCore compilation target |
|---|---|---|---|
| **A. User-declared** | any name from the variable dialog | yes | Helper entity, or YAML `variables:` (§5) |
| **B. Event context** | `$currentEventDevice`, `$currentEventValue`, `$currentEventAttribute` | no | HA trigger data (`trigger.*`) in templates |
| **C. Time & date** | `$now`, `$time`, `$hour`, `$sunrise`, `$sunset` | no | HA template functions; `sun` integration |
| **D. Location & hub** | `$locationMode`, `$shmStatus` | no | PistonCore `input_select`; designated `alarm_control_panel` |
| **E. Loop & iteration** | `$index`, `$device` inside `for`/`each` | no | HA `repeat.index` / `repeat.item` |
| **F. Piston arguments** | `$args` | no | Variables passed at call site by `call_piston` |
| **G. Web request results** | `$response`, `$httpStatusCode` | no | HA `response_variable` from the action call |
| **H. Random** | `$random`, `$randomColor` | no | HA templates |
| **I. Piston metadata** | version, piston name/id | no | Compile-time constants |

**Decision — PistonCore choice.** **Only Class A ever becomes a helper entity.**
Every other class compiles to a template expression, trigger context, call-site
variable, or compile-time constant. Creating a helper for any of them would be
wrong: they are engine-provided and read-only, so a helper could drift from the
real value and would appear in the user's entity list as state PistonCore
invented.

**Decision — PistonCore choice.** Classes B–I are read-only. A piston attempting
to assign to one fails at compile, naming the variable. Reference in the spec:
this is the same fail-loud principle as §7.2.

**Open — needs source.** The complete membership of each class, and whether the
class boundaries above match the engine's own internal grouping, is resolved by
**VAR-V-02**. The examples above are illustrative, not exhaustive, and must not
be treated as a complete list. The classes themselves are a PistonCore
organizing decision; webCoRE may not group them this way internally.

**Open — decision needed.** Classes B, E, F, and G are *context-scoped* — they
have meaning only inside a particular trigger, loop, call, or action, and are
undefined outside it. A piston reading `$index` outside a loop, or
`$currentEventDevice` in a piston with no device trigger, is legal in webCoRE
but has no HA equivalent. Whether PistonCore rejects these at compile or emits a
null-safe template is resolved by **VAR-V-12** and **VAR-V-13**.

---

## 1. Storage model (Class A)

**Decision — PistonCore choice.** Persistent variable state lives in native HA
helper entities, one helper per variable. Rationale: native-where-possible; a
user can inspect and debug variable state in Developer Tools without knowing
anything about PistonCore internals. Rejected alternative was a single
PistonCore-owned JSON blob, which makes PistonCore opaque inside HA and forces
PyScript for read-modify-write on ordinary pistons.

**Decision — PistonCore choice.** Helper entity IDs use normal readable HA
naming. The friendly-names-only rule governs the PistonCore dashboard, not HA
object names.

**Decision — PistonCore choice.** PyScript routing is a per-piston execution
decision, not a per-variable storage decision. Helpers remain the storage layer
on both paths.

**Not every variable needs a helper.** See §5 — only persistent variables do.

---

## 2. Scope (Class A)

| Prefix | Scope | Storage |
|---|---|---|
| (none) | Piston-local | Per-piston helper, or run-scoped (§5) |
| `@` | Instance-global | Shared helper, flat namespace |
| `@@` | Hub-global, broadcast across webCoRE instances | Shared helper + HA event |

**Verified — webcore.groovy v0.3.114.20220203, lines 1504, 1525, read 2026-08-03.** The `variable/set` endpoint
branches on presence of a piston id: absent → global (parent app state);
present → `piston.setLocalVariable(name, value.v)`.

**Verified — webcore.groovy v0.3.114.20220203, lines 891, 2183, read 2026-08-03.** `@@` variables are broadcast via
`sendLocationEvent` with name `'@@' + handle()`, and webCoRE subscribes to that
same event. `@` and `@@` differ in blast radius, not scope depth.

**Decision — PistonCore choice.** With a single PistonCore instance, `@` and
`@@` collapse to one namespace. `@@` writes additionally fire an HA event so
external listeners can subscribe, preserving the broadcast contract.

**Verified — webcore.groovy v0.3.114.20220203, lines 1818–1820, read 2026-08-03.** The global namespace is flat and
returned sorted by key. No nesting, no per-piston prefixing.

**Open — needs source.** `validateGlobalVariableName()` gates global creation
(piston.module.html, `dialog-edit-global-variable` footer). The rules live in
`piston.module.js`, not yet supplied.

---

## 3. Piston JSON shape

**Verified — piston.module.html v0.3.114.20220203, `variables` template, lines 466–476, read 2026-08-03.**

| Key | Meaning |
|---|---|
| `n` | Variable name |
| `t` | Data type (§4) |
| `v` | Initial value operand — absent/empty means persistent (§5) |
| `a` | Assignment type: `s` = constant, `d`/absent = dynamic (§6) |
| `z` | Description / comment |

Operand `t` codes observed in the editor templates: `c` value, `d` device,
`e` expression, `p`, `s`, `u`, `v` variable, `x`. **Assumed — needs test:** the
full code table requires `piston.module.js`.

---

## 4. Data types (Class A)

**Verified — piston.module.html v0.3.114.20220203, `dialog-edit-variable`, lines 2221–2243, read 2026-08-03.**
Locals offer:

*Basic:* `dynamic`, `string`, `boolean`, `integer`, `decimal`, `long`,
`datetime`, `date`, `time`, `device`

*Lists:* `dynamic[]`, `string[]`, `boolean[]`, `integer[]`, `decimal[]`,
`long[]`, `datetime[]`, `date[]`, `time[]`

**There is no `device[]`.** Device is the one basic type with no list form.
**There is no `enum` type** — earlier drafts of this spec invented it.

**Verified — piston.module.html v0.3.114.20220203, `dialog-edit-global-variable`, lines 2310–2319, read 2026-08-03.**
Globals offer a *reduced* set: `dynamic`, `string`, `boolean`, `integer`,
`decimal`, `datetime`, `date`, `time`, `device`. **No `long`, and no list types
at all.** Globals cannot be lists.

### HA mapping

**Decision — PistonCore choice.** Mapping below is PistonCore's, constrained by
the HA facts cited in §7.

| webCoRE type | HA helper | Notes |
|---|---|---|
| boolean | `input_boolean` | Clean 1:1 |
| integer | `input_number` (step 1) | `counter` deliberately unused — see §7.4 |
| long | `input_number` | Float-backed; precision risk — see §7.3 |
| decimal | `input_number` | |
| string | `input_text` | Entity-state cap — see §7.2 |
| time | `input_datetime` (`has_time`) | Offset trap — see §7.1 |
| date | `input_datetime` (`has_date`) | |
| datetime | `input_datetime` (both) | |
| device | — | Compile-time resolution; never reaches HA (§8) |
| dynamic | `input_text` + type tag | Forces PyScript unless type is unambiguous |
| `<type>[]` | `input_text` (JSON) | No native list helper; entity-state cap applies |

**Verified — HA `input_datetime` docs, https://www.home-assistant.io/integrations/`input_datetime/`, read 2026-08-03.**
`has_date` and `has_time` are independent booleans, giving all three variants.

## 5. Persistence — initial value determines lifetime

**Verified — piston.module.html v0.3.114.20220203, `dialog-edit-variable`, initial-value note, read 2026-08-03.**
Assigning an initial value instructs the piston to re-initialize the variable to
that value **on every run**. The variable may change during a run, but reverts on
the next one. To persist data between runs, the initial value is left empty.

This yields two distinct classes:

| Class | Condition | PistonCore treatment |
|---|---|---|
| **Run-scoped** | Initial value present | YAML `variables:` block — **no helper** |
| **Persistent** | Initial value absent | Helper entity |

**Decision — PistonCore choice.** Compile run-scoped variables to native YAML
`variables:`. They need no entity, which removes them from the sprawl budget
entirely and keeps the common case fully native.

**Verified — piston.module.html v0.3.114.20220203, line 2249, read 2026-08-03.** The initial-value form group is
hidden when the data type ends with `]`. List variables cannot take an initial
value, and are therefore **always persistent**.

---

## 6. Assignment type

**Verified — piston.module.html v0.3.114.20220203, `dialog-edit-variable`, assignment select, read 2026-08-03.**
Two values: `d` Dynamic (default), `s` Constant — value is static and cannot be
changed.

**Decision — PistonCore choice.** Constants compile to literals inlined at each
reference. No helper, no runtime state, no YAML variable.

**Verified — piston.module.html v0.3.114.20220203, line 2253, read 2026-08-03.** The assignment selector is hidden
for device-typed operands (`data.t == 'd'`), so device variables have no constant
form.

---

## 7. Known traps

### 7.1 `time` is not epoch milliseconds

**Verified — app.js v0.3.114.20220203, lines 1461–1468, read 2026-08-03.** `date` and `datetime` serialize as plain
epoch milliseconds. `time` serializes as
`d.getTime() - d.getTimezoneOffset() * 60000` — offset-shifted.

Treating all three identically when mapping to `input_datetime` produces times
wrong by the local UTC offset, and wrong differently across DST boundaries.

### 7.2 The 255-character ceiling is platform-wide, not `input_text`-specific

**Verified — HA `input_text` docs, https://www.home-assistant.io/integrations/`input_text/`, read 2026-08-03.** The
documentation states that 255 is the maximum number of characters allowed in an
**entity state**. The cap is not a property of `input_text`; it binds every
entity's state.

**Consequence.** There is no alternative helper to switch to. This binds strings,
serialized lists, and type-tagged dynamics alike. PyScript does not route around
it — the cap is on the entity, not the writer.

**Decision — PistonCore choice.** Fail loudly at compile time, naming the
variable and the limit. Do not truncate, do not silently shard. Consistent with
the unknown-vocabulary-throws principle: failures surface during compile, which
is already part of the workflow.

**Assumed — needs test.** A frontend defect permitting text helpers above 255
via the UI is reported (home-assistant/frontend issue 24549, home-assistant/core
issue 140054, read 2026-08-03). Treat as a bug, not a supported path. Do not
build on it.

Record in `HA_LIMITATIONS.md` with a re-test flag.

### 7.3 `input_number` is float-typed and requires bounds

**Verified — HA `input_number` docs, https://www.home-assistant.io/integrations/`input_number/`, read 2026-08-03.**
`min` and `max` are **required** float parameters. `initial` and `step` are also
floats; the smallest permitted `step` is 0.001.

Two consequences PistonCore must handle:

**Decision — PistonCore choice.** webCoRE numbers are unbounded, but every
`input_number` requires explicit `min`/`max`. PistonCore uses
`min: -999999999999`, `max: 999999999999` for all numeric variables. This sits
well inside the range where integers remain exactly representable in a 64-bit
float, so no silent rounding occurs. Bounds are not surfaced in the PistonCore
UI — webCoRE has no such concept and exposing one would be a fidelity break.
A value exceeding these bounds fails at compile time, naming the variable.

**Assumed — needs test.** Float backing means large `long` values lose
exactness. Determine the practical threshold and whether to fail at compile or
route affected pistons to PyScript.

### 7.4 `counter` cannot start negative

**Verified — HA `counter` docs, https://www.home-assistant.io/integrations/`counter/`, read 2026-08-03.** `initial` is
documented as 0 or a positive integer. `minimum` and `maximum` are optional.
`restore` defaults to true.

**Decision — PistonCore choice.** PistonCore does **not** use `counter`. All
webCoRE numeric types map to `input_number` without exception. Using `counter`
would require a per-variable eligibility rule (non-negative, increment-only),
and conditional mapping rules are the category most prone to being hardcoded
into the compiler rather than driven by the vocabulary tables. A single
unconditional mapping is worth more than `counter`'s nicer display.

### 7.5 Helper `initial` corroborates but does not implement §5

**Verified — HA `input_text` and `input_number` docs, https://www.home-assistant.io/integrations/, read 2026-08-03.**
Setting a valid `initial` makes the helper start with that value; omitting it
makes the helper restore the state it held before Home Assistant stopped.

This is the same rule as webCoRE's initial-value semantics (§5), but the trigger
differs: HA's `initial` applies at **Home Assistant restart**, webCoRE's applies
at **every piston run**. Helper `initial` therefore corroborates the model but
cannot implement it. Run-scoped variables still compile to YAML `variables:`.

---

## 8. Device variables

**Decision — PistonCore choice.** Device variables resolve at compile time. The
compiler expands them into the entity list at each reference point; the variable
never becomes HA state and never reaches a helper. The 255-character cap does not
apply.

Resolution reads variables and never mutates them. Device variables store
friendly names and are never rewritten to entity IDs.

**Verified — piston.module.html v0.3.114.20220203, line 2243 / 2310, read 2026-08-03.** Device has no list form in
either dialog, so compile-time expansion never has to handle a device collection
declared as a list type.

### 8.1 Global device variables go stale — dependency tracking required

**Two homes, one name.** Global variables split by type:
non-device globals become helper entities in HA, referenced by the compiled
automations from outside them. Device globals are expanded inline into the
automation at compile and the variable itself exists only in PistonCore's store
— it never becomes an HA entity at all.

**Verified — dashboard UI screenshot, 2026-08-03.** Global device variables in
real use hold large device lists (observed: `@Door_Contacts_Exterior` with 14
devices, `@Alert_Lights` with 4). Device-typed globals are a primary usage
pattern, not an edge case.

**The problem.** webCoRE resolves device variables at **runtime**, so a global
device variable is always current — there is no compiled artifact to go stale.
PistonCore resolves them at **compile time** (§8), which introduces a staleness
class webCoRE does not have:

> A global device variable is edited from the dashboard, outside any piston.
> Every already-compiled piston referencing it still holds the device list as it
> was at compile time. The piston continues to run, silently, against the old
> list. No error is raised. The failure surfaces only as a device that stopped
> participating in an automation.

This is the worst failure shape: silent, delayed, and indistinguishable from a
device problem.

**Decision — PistonCore choice.** Compile-time resolution is retained, but the
compiler must maintain a **dependency map** from each global device variable to
every piston that references it. On any change to a global device variable —
add, remove, rename, delete — all dependent pistons are recompiled and
redeployed automatically.

**Decision — PistonCore choice.** Deleting a global device variable that has
dependents fails, naming the dependent pistons. webCoRE permits the delete and
lets the pistons break at runtime; PistonCore's compile step makes the
dependency knowable in advance, so it should be enforced.

**Open — decision needed.** Whether recompilation is automatic and silent, or
surfaces a confirmation listing affected pistons. Silent is closer to webCoRE's
behavior, where the change simply takes effect. A confirmation is safer but has
no webCoRE analogue.

**Open — needs source.** Whether webCoRE permits a *local* device variable to
reference a global one, which would create a second-order dependency. Resolved
by **VAR-V-06**.

---

**Open — decision needed.** A piston assigning *into* a device variable at
runtime (e.g. storing `$currentEventDevice`) cannot be resolved at compile time.
Either reject at compile with a clear message, or route the piston to PyScript.
Must be an explicit decision, not a discovered gap.

---

## 9. Value format

**Verified — webcore.groovy v0.3.114.20220203, lines 1513, 1516, read 2026-08-03.** Globals are stored as
`name → [t: <type>, v: <value>]`. The type tag is part of the storage format, not
merely the wire format.

**Verified — app.js v0.3.114.20220203, lines 1456–1476, read 2026-08-03.** The dashboard sends the same `{t, v}`
shape, base64-encoded via `utoa` (`btoa(unescape(encodeURIComponent(str)))`,
app.js line 2398 — UTF-8 safe). Transport is JSONP.

**Verified — webcore.groovy v0.3.114.20220203, line 1525, read 2026-08-03.** Locals are set with `value.v` only. No
type is transmitted; it is resolved from the piston's declaration.

**Verified — piston.module.html v0.3.114.20220203, `dialog-edit-local-variable`, lines 2282–2300, read 2026-08-03.**
The local-variable dialog edits value only — no type selector. Corroborates the
above: local type is fixed at declaration.

---

## 10. Rename semantics

**Verified — webcore.groovy v0.3.114.20220203, lines 1509–1517, read 2026-08-03.** When the incoming name differs
from the stored name, the old key is removed and a new entry written. Nothing
keyed to the old name survives.

**Decision — PistonCore choice.** Match this. On rename, delete the old helper
and create a new one. Orphaning on rename is webCoRE's actual behavior, so this
is fidelity rather than compromise.

**Verified — webcore.groovy v0.3.114.20220203, line 1524, read 2026-08-03.** The change event fires only on
create/update, never on delete.

**Verified — webcore.groovy v0.3.114.20220203, lines 1520 vs 1819, read 2026-08-03.** The setter writes
`atomicState.vars`; `listAvailableVariables()` reads `state.vars`. Source-side
quirk; PistonCore should use one consistent store.

---

## 11. Design-time expression evaluation

**Verified — app.js v0.3.114.20220203, lines 1488–1503, read 2026-08-03.** `dataService.evaluateExpression` posts to
`intf/dashboard/piston/evaluate` with `id`, base64 `expression`, `dataType`, and
optional base64 `variables`. On error with variables supplied, it retries once
without them.

**Verified — webcore.groovy v0.3.114.20220203, line 1557, read 2026-08-03.** The parent app delegates to
`piston.proxyEvaluateExpression(getRunTimeData(), expression, params.dataType)`.

> **Implication for PistonCore — likely gap.** The dashboard never evaluates
> expressions locally. The shim must provide a **design-time** expression
> evaluator running live while the user types in the wizard, distinct from the
> compile-time path.

**Action:** diff the 20 `intf/dashboard/` endpoints referenced in `app.js`
against what the shim currently implements.

---

## 12. Verification tasks (for Claude Code)

Each task below is self-contained and executable against the local source trees:
webCoRE, Hubitat Groovy, and Home Assistant core. Run **one task per session**.

### Standing rules for every task

1. **Read the full file before drawing any conclusion.** Do not conclude from a
   grep hit alone. Grep to locate; read to understand.
2. **webCoRE source is the highest authority.** Where source and this spec
   disagree, the source wins and this spec is wrong.
3. **Make no edits.** Not to source, not to PistonCore, not to this spec. Report
   only. Edits are a separate, separately-approved task.
4. **Cite file and line for every claim.** `<filename> line NNN`. A claim without
   a citation is not an answer.
5. **Report unknowns as unknown.** If the source does not answer the question,
   say so. Do not infer, do not fill gaps from general knowledge of Groovy, HA,
   or other automation systems.
6. **Report in this format**, one block per finding:

   ```
   VAR-V-<task>-<n>
   CLAIM:    <what the spec currently says, or "no current claim">
   FINDING:  <what the source actually says>
   CITATION: <file> line <NNN>
   VERDICT:  CONFIRMS | CONTRADICTS | INCOMPLETE | NOT-FOUND
   ```

---

### VAR-V-01 — Casting rules

**File:** `webcore-piston.groovy`

Locate the casting function (likely `cast()`) and every call site. Report:

- The complete list of type names it accepts, exactly as spelled in source.
- The conversion behavior for each source-type → target-type pair it handles.
- Behavior on an impossible cast: exception, null, zero, empty string, or
  silent passthrough.
- How `dynamic` is resolved — at assignment, at read, or per-operation.
- Whether `long` and `integer` are distinct in casting or collapse.

Cross-check against §4 of this spec, which lists the types offered by the
editor UI. **Flag any type the engine handles that the UI does not offer, and
any type the UI offers that the engine does not handle.**

---

### VAR-V-02 — System variable inventory (all of Classes B–I)

**File:** `webcore-piston.groovy`

This is the largest and highest-priority task. The class table at the top of this
spec is a PistonCore organizing guess; this task replaces it with fact.

Locate the system variable table (variables prefixed `$`). Report the **complete**
list — do not stop at the ones named in this spec, which are illustrative only.
For each variable report: exact name, data type, whether writable, what it
returns, and whether it is context-scoped (meaningful only inside a trigger,
loop, call, or web request).

Report as a JSON object keyed by variable name, suitable for saving beside
`webcore_vocab.json`. Do not write the file — output it in the response.

**Then answer three questions:**

1. Does the engine group these internally? If so, report its grouping — that is
   more authoritative than the A–I classes in this spec.
2. Which are Hubitat/SmartThings-specific with no Home Assistant equivalent?
3. Are any of them **writable**? This spec assumes Classes B–I are read-only.
   Any writable system variable contradicts that and must be flagged.

---

### VAR-V-03 — Local variable declaration and typing

**File:** `webcore-piston.groovy`

Locate `setLocalVariable` and the local variable read path. Report:

- Where a local's declared type is stored and how it is looked up.
- What happens when a value of the wrong type is assigned.
- Whether the declared type can change at runtime.
- Whether an undeclared variable can be written to, and if so what type it gets.

**Spec claim under test (§9):** locals are set by value only, with type resolved
from the piston's declaration.

---

### VAR-V-04 — Persistence and initial values

**File:** `webcore-piston.groovy`

**Spec claim under test (§5):** a variable with an initial value is
re-initialized on every piston run; a variable without one persists between runs.

Locate the piston run initialization path. Report exactly which variables are
reset at the start of a run and under what condition. Report whether the rule
differs for list-typed variables, which the editor does not allow initial values
for.

---

### VAR-V-05 — List runtime semantics

**File:** `webcore-piston.groovy`

Report:

- How list variables are stored and serialized.
- Read behavior for an index beyond the end of the list.
- Write behavior for an index beyond the end — error, or extend the list.
- Whether indices are 0-based or 1-based.
- The `*CLEAR` index behavior (see changelog v0.3.111.20210130).
- Whether there is any maximum list length.

---

### VAR-V-06 — Device variables at runtime

**File:** `webcore-piston.groovy`

**Open question this resolves (§8):** can a piston assign a device *into* a
device variable at runtime — for example storing `$currentEventDevice`?

Report whether the engine permits it, what is stored (device object, id, or
name), and how a later read resolves it. If the engine permits it, report
whether the editor UI exposes any way to construct such an assignment.

**Additionally, for §8.1 (global device variable staleness):**

This is a **timing** question, not a whether question. The device global lives in
PistonCore's own store, so PistonCore always knows when it changes; dependency
tracking is within its control. What the source determines is *when*
recompilation must happen to match webCoRE's observable behavior.

- Report what happens to a piston when a global device variable it references is
  edited: does the change take effect on the very next run, or only after the
  piston is re-saved? **If immediate, PistonCore must recompile dependents on
  edit. If re-save is required, PistonCore may defer.**
- Confirm whether webCoRE resolves device variables on every read or caches the
  resolution at piston save.
- Report whether a local device variable can be assigned from a global device
  variable, creating a second-order dependency.
- Report whether webCoRE blocks deleting a global variable that pistons
  reference, or permits it.

---

### VAR-V-07 — Global variable naming rules

**File:** `piston.module.js`

Locate `validateGlobalVariableName()`. Report the complete validation rules:
permitted characters, length limits, required prefixes (`@`, `@@`), reserved
names, and case sensitivity.

Also report the full operand `t` code table (§3 lists `c`, `d`, `e`, `p`, `s`,
`u`, `v`, `x` as observed but unconfirmed).

---

### VAR-V-08 — Expression evaluation semantics

**File:** `webcore-piston.groovy`

Locate `proxyEvaluateExpression` and the expression evaluator it calls. Report:

- Operator precedence.
- Type coercion rules in comparisons between mismatched types.
- Behavior on division by zero, null operands, and malformed expressions.
- Whether evaluation differs between design-time (dashboard preview) and
  runtime (piston execution).

**This task may be large.** If the evaluator exceeds what one session can cover
properly, report precedence and coercion only, and state clearly what was not
covered.

---

### VAR-V-12 — Event context variables (Class B)

**File:** `webcore-piston.groovy`

Report how event context variables (`$currentEventDevice`, `$currentEventValue`,
`$currentEventAttribute`, and any others found by VAR-V-02) are populated, and:

- What they return in a piston whose trigger is not a device event — time
  trigger, manual execution, or piston call.
- What they return inside a nested block far from the trigger.
- Whether previous-value variants exist and how far back they reach.

**Open question this resolves:** whether PistonCore rejects out-of-context reads
at compile or emits a null-safe template.

---

### VAR-V-13 — Loop, argument, and web-response variables (Classes E, F, G)

**File:** `webcore-piston.groovy`

Three related context-scoped groups. Report for each:

- **Loop (`$index`, `$device`):** 0- or 1-based; behavior in nested loops —
  shadowed, or is there an outer accessor; value after the loop ends.
- **Arguments (`$args`):** how a calling piston passes them, the structure
  received, behavior when the caller passes none or passes extras, and whether
  they are typed.
- **Web response (`$response`, `$httpStatusCode`):** when populated, lifetime
  after the request, and behavior on request failure or timeout.

---

### VAR-V-14 — Location and hub variables (Class D)

**Files:** `webcore-piston.groovy`, Hubitat Groovy source

Report the source of `$locationMode`, `$shmStatus`, and any others found by
VAR-V-02. For each: exact values it can take, and whether the value is a display
string or an internal id.

**Spec cross-check:** existing PistonCore decisions map location mode to
`input_select.pistoncore_location_mode` (Day/Evening/Night/Away) and HSM to a
designated `alarm_control_panel`. Report whether the real value sets match those
mappings, and flag any value with no HA equivalent.

---

### VAR-V-09 — HA entity state length limit

**Files:** Home Assistant core

**Spec claim under test (§7.2):** entity state is capped at 255 characters
platform-wide, not merely in `input_text`.

Locate where the limit is enforced in core (search for the constant, likely in
the state machine / `core.py`). Report the exact constant, its value, where it
is enforced, and what happens on overflow — exception, truncation, or state set
to `unknown`. Report the HA version of the tree inspected.

---

### VAR-V-10 — HA input_number schema

**Files:** Home Assistant core, `components/input_number/`

**Spec claims under test (§7.3):** `min` and `max` are required; values are
float-backed; smallest step is 0.001.

Report the actual config schema from source, the Python type used for storage,
and what happens when a set value falls outside `min`/`max` — clamp, reject, or
raise. Report the HA version of the tree inspected.

---

### VAR-V-11 — HA helper restore semantics

**Files:** Home Assistant core, `components/input_text/`, `input_number/`,
`input_datetime/`, `input_boolean/`

**Spec claim under test (§7.5):** setting `initial` disables state restore;
omitting it restores the prior state.

Report the restore logic from source for each helper, and confirm whether the
behavior is identical across all four. Report the HA version inspected.

---

## 13. Still unresolved

Resolved by the tasks in §12. Listed here for tracking:

Writing these from inference is precisely the guessing that has produced drift.
Each maps to a verification task above.

- **Casting rules** — `cast()` semantics, coercion between types, invalid-cast
  behavior. Especially `dynamic` resolution and `long` vs `integer`.
- **System variables (`$`)** — the authoritative table: `$now`, `$time`,
  `$currentEventDevice`, `$currentEventValue`, `$index`, `$random`, and the rest.
  Belongs in a JSON file beside `webcore_vocab.json`, not in compiler code.
- **List runtime semantics** — indexing, out-of-range behavior, and the `*CLEAR`
  index reset. **Verified — webcore.groovy v0.3.114.20220203, changelog entry
  v0.3.111.20210130, read 2026-08-03** that `*CLEAR` exists; its semantics are not.
- **Lifecycle** — behavior on HA restart, piston re-import, piston pause.
- **Expression evaluation semantics** — operator precedence, coercion in
  comparisons. Likely warrants its own document.

Also outstanding: `piston.module.js` for `validateGlobalVariableName()` rules and
the full operand `t` code table.

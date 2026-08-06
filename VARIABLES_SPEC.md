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
| `webcore-piston.groovy` | — | **SUPPLIED** (2026-08-03) at `reference/webCoRE-hubitat-patches-extracted/.../webcore-piston.src/`. VAR-V-01/03/04/05 are runnable. VAR-V-02 is DONE — see `webcore_vocab.json` `systemVariables` |

Every claim is marked `Verified — <source, line>`, `Assumed — needs test`, or
`Decision — PistonCore choice`.

---

## Reconciliation with COMPILER_SPEC.md

This document is scoped to variables. `COMPILER_SPEC.md` §3.1 RESOLVE already
covers part of the same ground. Where they overlap, the following applies.

**COMPILER_SPEC wins:**

- **Device variables** — specified there in full (§3.1, §H1). Out of scope here.
- **Superglobals (`@@`)** — §3.1 states they have no v1 role, since PistonCore
  collapses to a single local HA instance. That supersedes any `@@` handling
  described in §2 of this document. Deferred, not specified.
- **Map by behavior, never by name** — §3.1's principle. Adopted here.

**This document corrects COMPILER_SPEC §3.1:**

| §3.1 states | Verified position | Source |
|---|---|---|
| "~7 value types" | 10 basic + 9 list types | §4, verified against source and UI |
| `long` absent from the helper table | `long` is a distinct declared type | §4; COMPILER_SPEC §2.5 itself lists `LONG` in cast dispatch |
| List types absent entirely | 9 list types exist; lists cannot take an initial value and therefore always persist | §4, §5 |
| `min`/`max` used "to constrain" | `min`/`max` are **required** — an `input_number` cannot be created without both | §7.3 |

**This document adds, with no COMPILER_SPEC coverage:**

initial-value persistence semantics (§5), the 255-character entity-state cap
(§7.2), list variables, media and image handling (§10b, §10d), system variables
embedded in string expressions and their formatting (§10c), and sanitized output
(§10e).

**COMPILER_SPEC partially answers this document's open items.** §2.5 item 6
locates `evaluateExpression()` at `webcore-piston.groovy` line 10497 and reports
that coercion is strongly-typed dispatch — every expression is cast to its
declared type via `cast`/`bcast`/`scast`/`dcast` before return, with no loose
dynamic values. It flags this as a real semantic gap against Jinja2, which has no
forced-cast-per-type step. **VAR-V-01 and VAR-V-08 should start from that finding
rather than from scratch.**

---

## Variable classes — scope of this document

webCoRE exposes several distinct classes of variable. They differ in who owns
them, whether they are writable, and — critically — how each must compile to
Home Assistant. **Sections 1–11 below cover Class A only.** The other classes
are specified here and enumerated by the verification tasks in §11.

| Class | Examples | Writable | PistonCore compilation target |
|---|---|---|---|
| **A. User-declared** | any name from the variable dialog | yes | Helper entity, or YAML `variables:` (§5). **Device-typed variables are out of scope** — see note below. |
| **B. Event context** | `$currentEventDevice`, `$currentEventValue`, `$currentEventAttribute` | no | HA trigger data (`trigger.*`) in templates |
| **C. Time & date** | `$now`, `$time`, `$hour`, `$sunrise`, `$sunset` | no | HA template functions; `sun` integration |
| **D. Location & hub** | `$locationMode`, `$shmStatus` | no | PistonCore `input_select`; designated `alarm_control_panel` |
| **E. Loop & iteration** | `$index`, `$device` inside `for`/`each` | no | HA `repeat.index` / `repeat.item` |
| **F. Piston arguments** | `$args` | no | Variables passed at call site by `call_piston` |
| **G. Web request results** | `$response`, `$httpStatusCode` | no | HA `response_variable` from the action call |
| **H. Random** | `$random`, `$randomColor` | no | HA templates |
| **I. Piston metadata** | version, piston name/id | no | Compile-time constants |

**Out of scope — device-typed variables.** Device variables, local and global,
are specified in full elsewhere in the PistonCore specs. This document does not
restate, extend, or reinterpret those rules. Where a device variable interacts
with something specified here, defer to the device variable spec.

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
| boolean | `input_boolean` | **Not 1:1.** HA states are `on`/`off`, never `true`/`false`. Map by behavior, not type name. (COMPILER_SPEC §3.1) |
| integer | `input_number` (step 1) | `counter` deliberately unused — see §7.4 |
| long | `input_number` | Float-backed; precision risk — see §7.3 |
| decimal | `input_number` | |
| string | `input_text` | Entity-state cap — see §7.2 |
| time | `input_datetime` (`has_time`) | Offset trap — see §7.1 |
| date | `input_datetime` (`has_date`) | |
| datetime | `input_datetime` (both) | |
| device | — | **Out of scope.** Covered by the device variable spec. |
| dynamic | `input_text` + type tag | Forces PyScript unless type is unambiguous |
| `<type>[]` | `input_text` (JSON) | No native list helper; entity-state cap applies |

**Verified — HA `input_datetime` docs, https://www.home-assistant.io/integrations/`input_datetime/`, read 2026-08-03.**
`has_date` and `has_time` are independent booleans, giving all three variants.

## 4a. IMPLEMENTATION STATUS (PistonCore, 2026-08-03)

**Built and verified.** Both bands read the declared type. The decision is
`resolve.typed_value()` — ONE function — and each band formats the result its
own way (`true` in YAML/Jinja, `True` in Python). Sharing the decision but not
the formatting is deliberate: the last time a band borrowed the other's
formatter it emitted a Jinja template into a PyScript module.

Only CONSTANTS are cast. An expression is left alone, because casting a value
the compiler cannot see would be guessing.

**The hazard this closed:** every value used to be written as text, and the
string `"false"` is TRUTHY in both Jinja and Python. A boolean left as text
silently inverts `if <var>`.

## 4b. PERSISTENCE NEEDS A STRICTER TEST THAN §5 (PistonCore, 2026-08-03)

§5's rule — initial value present means run-scoped — is correct for webCoRE,
which runs a piston as ONE program. **PistonCore compiles each top-level
statement into a SEPARATE HA automation**, and an HA `variables:` block lives
for one run of one automation. So the test PistonCore must apply is:

> Does any READ of this variable happen outside the statement that WROTE it?

If yes it needs a helper entity, **regardless of whether it has an initial
value**. `Motion_Triggered` in `Video Hall Motion Light` has an initial value
(so §5 calls it run-scoped) yet is set in statement 1 and read in statement 9 —
two different automations. Measured across the 84-piston corpus: 23 variables
in 13 pistons, and every motion-light piston needs two.

This is the manual-override pattern (Jeremy, 2026-08-03): set a flag when the
light is switched on by hand, check it back on a later trigger to skip the
timer. Before this it silently never matched.

PyScript-band pistons need no helpers — that band keeps piston variables in its
own persisted state, so cross-statement reads already work there.

## 4c. HELPER CREATION — VERIFIED MECHANISM (2026-08-03)

**The REST config API does NOT create helpers.** `/api/config/input_boolean/
config/<id>` returns **404**; that path exists for automations, scripts and
scenes only. (Jeremy called this before the test: *"i doubt it autocreats i had
to do it when i made the yaml by hand."*)

**What works:** write a YAML file, then call `<domain>.reload`. All four helper
domains expose one. Proven end to end against a live HA — file written, reload
called, entities appeared, no restart.

**A PACKAGES folder, not `!include` lines.** A package MERGES with the user's
configuration. Four bare `input_boolean:`-style includes would collide with an
install that already defines its own helpers, and a duplicate key stops HA
starting — a failure that lands at their next restart, not at our compile.

The shape lives in `templates/compiler/yaml/classic/helpers_package.yaml.j2`,
not in Python, because helper domain names and required fields are HA's moving
target.

**Lifecycle.** The package is rebuilt from every piston's recorded helper set on
each deploy, so a variable that no longer needs a helper — or a piston that has
been deleted — simply stops contributing rows and the entity disappears on the
next reload. Reconciling beats bookkeeping: there is no orphan list to drift.

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

## 8. Value format

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

## 9. Rename semantics

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

## 10. Design-time expression evaluation

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

## 10a. Two type systems — attribute types vs variable types

**Verified — webcore.groovy v0.3.114.20220203, capability/attribute table
(lines ~2470–2560), read 2026-08-03.** webCoRE uses **two distinct type
systems**:

- **Variable types (10)** — what the user can declare (§4).
- **Attribute and parameter types (~35)** — what devices expose and what
  commands accept. Extracted from source: `decimal`, `string`, `enum`,
  `integer`, `duration`, `level`, `boolean`, `color`, `dynamic`, `datetime`,
  `lifxSelector`, `hue`, `uri`, `thermostatSetpoint`, `text`, `attributes`,
  `url`, `saturation`, `piston`, `colorTemperature`, `object`, `variables`,
  `infraredLevel`, `time`, `variable`, `thermostatMode`, `thermostatFanMode`,
  `switch`, `routine`, `phone`, `number`, `mode`, `lifxScene`, `email`,
  `contacts`, `consumable`, `alarmSystemStatus`, `vector3`, `image`,
  `hexcolor`, `date`.

**The unspecified problem.** When a piston stores a device attribute into a
variable, a ~35-type space must collapse into a 10-type space. Several
attribute types have **no variable type to land in**: `image`, `object`,
`vector3`, `attributes`, `variables`.

**Decision — PistonCore choice.** A claim that all pistons compile is not
credible until this collapse is specified. Any attribute type with no variable
target must either have an explicit mapping rule or fail loudly at compile,
naming the attribute and type. Silent coercion to `string` is prohibited — it
converts a type error into a runtime data corruption.

---

## 10b. Media types — images and audio

### Images

**Verified — HA core `components/image/__init__.py`, read 2026-08-03.**
`ENTITY_IMAGE_URL = "/api/image_proxy/{0}?token={1}"` with
`TOKEN_CHANGE_INTERVAL = timedelta(minutes=5)`. A `snapshot` service exists,
taking `ATTR_FILENAME`.

**Verified — HA developer docs, image entity, read 2026-08-03.** Image entity
state is driven by `image_last_updated`; the bytes are fetched separately and
are never in the entity state.

**Verified — user piston "doorbell pushed albert", dashboard screenshot,
2026-08-03.** webCoRE itself stores a captured image as a **filename in a plain
`string` variable**:
`string DoorBell_Camera_Image = 'Doorbell_Pro_-motion_...-motion.jpg';`

**Decision — PistonCore choice.** A webCoRE `image` attribute compiles to a
**file path**, produced by the snapshot service, stored in a `string` variable.
This now matches webCoRE's own representation rather than being an inference.

**Decision — PistonCore choice.** PistonCore must **never** store an
`/api/image_proxy/` or `/api/camera_proxy/` URL in a variable. The token rotates
every 5 minutes, so a stored URL silently dies. A piston capturing an image and
notifying later would send a dead link with no error raised. This is a
prohibition, not a preference.

**Open — decision needed.** Snapshot filenames must be unique per capture, or
successive captures overwrite each other. Naming scheme and cleanup policy are
unspecified. webCoRE has no analogue — it holds the image in its own storage.

### Audio

**Verified — HA `media_source` docs, read 2026-08-03.**
`media_player.play_media` takes `media_content_id` — a `media-source://` URI, a
`/local/` path, or an https URL — plus `media_content_type`.

**Verified — HA TTS docs, read 2026-08-03.** `tts.speak` speaks a message on a
media player through a TTS entity.

**Decision — PistonCore choice.** webCoRE speech commands (`playText`, `speak`,
and variants) compile to `tts.speak`. The message is a plain string and fits
normal variable handling.

**Decision — PistonCore choice.** webCoRE `playTrack` compiles to
`media_player.play_media`. `media_content_type` is **required by HA and has no
webCoRE equivalent** — webCoRE's track parameter is a bare URI. The compiler
infers the type from the file extension via a data-driven extension→type table,
and fails loudly when the extension is absent or unknown.

**Both media classes are reference-only.** No audio or image bytes ever enter an
entity state or a variable. This is consistent with §7.2 — the 255-character
entity state cap makes by-value media impossible regardless.

---

## 10c. System variables inside string expressions

**Verified — user piston "Dishwasher", dashboard screenshot, 2026-08-03.**
Observed source line:

```
Send device notification "{"[emoji] Dishwasher [emoji] "$monthName" "$day" - "$time" Dishwasher has finished."}";
```

This is **not a string literal.** It is a concatenation expression in which
quote characters toggle between literal text and expression context, with three
Class C system variables spliced inline.

**Implication.** §§ B–I of the class table describe how system variables are
*read*. This shows they are also *embedded*, which is a different compilation
target: the containing string becomes a Jinja template, not a value. Any
compiler path that treats system variables only as standalone reads will
mis-handle this, and this construction is common in notification text.

### Formatting is not free

`$monthName`, `$day`, and `$time` return **formatted, localized** values.
webCoRE derives format and locale from hub settings. HA has no equivalent
defaults, so each one compiles to an explicit `strftime` format the compiler
must choose.

**Decision — PistonCore choice.** Format strings live in a data-driven system
variable table, never inline in the compiler or templates. Each entry pairs the
webCoRE variable with its HA template expression and format string.

**Open — needs source.** The exact format webCoRE produces for each — 12- vs
24-hour for `$time`, zero-padding for `$day`, locale for `$monthName`, and
whether hub timezone or locale settings alter them. Resolved by **VAR-V-16**.
Choosing differently than webCoRE silently changes every notification's text.

### Encoding

**Verified — user piston, 2026-08-03.** Emoji appear in notification strings.
UTF-8 must survive parse, compile, YAML emission, and service call. Consistent
with app.js `utoa` being UTF-8 safe (§8); the compiler must not narrow this.

### The same concept compiles two ways

The observed piston uses time as a **condition** (`Time is between 9:00:00 AM
and 9:00:00 PM`) and as a **value** (`$time` inside the message) in the same
piston. These are unrelated compilation targets: a condition, versus a template
expression. The system variable table must not assume one shape.

---

## 10d. Media lifecycle and platform-dependent content

Observed in real pistons. Each is a variable-adjacent gap with no clean HA
equivalent.

### `clearImages()` — no HA analogue

**Verified — user piston "doorbell pushed albert", 2026-08-03.** The piston calls
`Take a picture;` and later `clearImages();` on the same camera device.

webCoRE owns an image store with an explicit lifecycle command to empty it. HA's
snapshot service writes files and nothing reclaims them.

**Open — decision needed.** A doorbell piston firing several times daily
accumulates files indefinitely. Options: compile `clearImages()` to a file
deletion (requires filesystem access from an automation, which HA restricts),
adopt a fixed-slot filename scheme so each capture overwrites the last, or
document the gap and let files accumulate. Fixed-slot overwriting is the most
native, but changes semantics — webCoRE retains multiple images until cleared.

### Image attachment to notifications

**Verified — user piston, 2026-08-03.** Email notification body embeds the image
filename via a `File:` parameter alongside the message text.

**Open — needs source.** How webCoRE's `File:` parameter resolves the filename to
image data, and whether HA notify platforms accept an equivalent attachment
path. Resolved by **VAR-V-17**.

### Device-specific numeric media

**Verified — user piston, 2026-08-03.** `Play Sound 12;` on a chime device — a
numeric sound index interpreted by device firmware.

**Open — decision needed.** HA has no "sound N" concept; the equivalent depends
entirely on the device integration. Likely an escape-hatch case under the hybrid
vocabulary approach rather than a translatable command.

---

## 10e. Sanitized output must substitute device names

**Verified — user piston screenshots, 2026-08-03.** webCoRE's dashboard offers a
sanitized export. In sanitized output, device names are replaced with generic
substitutions derived from device type plus an index — observed: `Switch 12`,
`Unknown Device 15`, `Unknown Device 11`. Compare the unsanitized rendering of a
different piston, which shows real names (`Back Door`, `Front Door`).

**Correction.** An earlier draft of this spec read those placeholders as
unresolvable device references. They are not — the devices resolve normally; only
the *rendering* is redacted.

**Requirement for PistonCore.** Sanitize is a dashboard feature that operates on
piston data and substitutes **device names specifically**. Because PistonCore
serves the stock webCoRE dashboard, the sanitize control exists in the UI and
must work. It touches device variables directly: the substitution replaces the
friendly names that device variables hold.

**Open — needs source.** Where sanitization is performed — client-side in
`piston.module.js`, or server-side via a dashboard endpoint — and the exact
substitution rule that produces names like `Switch 12`. If server-side, the shim
must implement it. Resolved by **VAR-V-18**.

---

## 11. Verification tasks (for Claude Code)

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

**Spec claim under test (§8):** locals are set by value only, with type resolved
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

### VAR-V-15 — Attribute type to variable type collapse

**Files:** `webcore-piston.groovy`, `webcore.groovy`

**Spec claim under test (§10a):** webCoRE has ~35 attribute/parameter types but
only 10 variable types, and the collapse between them is unspecified.

Report:

- The complete attribute/parameter type list from the capability table, and the
  complete variable type list, as two explicit sets.
- For each attribute type with no matching variable type, what the engine
  actually does when that value is assigned to a variable: coerce, error, or
  store as-is untyped.
- Specifically for `image`: what is stored, and what the value looks like — data
  URI, URL, byte array, or object reference. The dashboard's
  `dialog-captured-image` template binds an `<img src>` to `capturedImage`, so
  determine the form that value takes.
- For `object`, `vector3`, `attributes`, and `variables`: what these represent
  and whether a piston can meaningfully assign them to a variable at all.

**This task determines whether "all pistons compile" is true.** If any attribute
type has no variable target and the engine silently coerces, PistonCore must
decide explicitly rather than inherit the coercion.

---

### VAR-V-16 — String expression grammar and system variable formatting

**Files:** `webcore-piston.groovy`, `piston.module.js`

**Spec claim under test (§10c):** system variables are embedded inside string
concatenation expressions, where quotes toggle literal/expression context.

Report:

- The **grammar** of a webCoRE string expression: how quote characters delimit
  literal versus expression segments, how nesting and escaping work, and how a
  literal quote character is represented.
- How this is stored in piston JSON — as one string, or a parsed operand tree.
  PistonCore must consume whatever webCoRE emits (piston JSON is law).
- For **every** date/time system variable found by VAR-V-02, the exact output
  format, with a concrete example value. Specifically `$monthName`, `$day`,
  `$time`, `$dayOfWeek`, `$hour`, `$minute`, `$meridian`.
- Whether format depends on hub locale, hub timezone, or a webCoRE setting, and
  what the fallback is when unset.
- Whether numeric variables embedded in strings are zero-padded, and whether
  decimals get a fixed precision.

Output the format findings as a JSON table mapping each system variable to its
observed output format, suitable for the data-driven table required by §10c.

---

### VAR-V-17 — Image storage lifecycle and attachment

**Files:** `webcore-piston.groovy`, `webcore.groovy`

**Context (§10b, §10d):** webCoRE stores captured images as filename strings and
provides `clearImages()`.

Report:

- Where captured images are physically stored, and the filename scheme —
  specifically whether names are unique per capture or reused.
- What `clearImages()` deletes: all images for a device, all for a piston, or
  all globally.
- Whether images expire or are capped in count or size.
- How the `File:` notification parameter resolves a filename to image data, and
  what the receiving notification handler is given — path, bytes, or URL.
- Whether the image filename variable is written by the engine automatically on
  `take`, or must the piston assign it.

**Then, against HA:** report whether any notify platform accepts a local file
path for attachment, and what permissions or `allowlist_external_dirs` config it
requires.

---

### VAR-V-18 — Sanitized output substitution

**Files:** `piston.module.js`, `app.js`, `webcore.groovy`

**Context (§10e):** the dashboard's sanitized export replaces device names with
generic placeholders such as `Switch 12` and `Unknown Device 15`.

Report:

- Whether sanitization happens client-side or via a dashboard endpoint. If it
  calls an endpoint, name it — the PistonCore shim must serve it.
- The exact substitution rule: what produces the type prefix (`Switch`,
  `Unknown Device`) and what the trailing number indexes.
- What else is redacted besides device names — piston name, author, location,
  variable values, import codes.
- Whether the sanitized form is display-only or also used for piston sharing and
  backup.

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

## 12. Still unresolved

Resolved by the tasks in §11. Listed here for tracking:

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

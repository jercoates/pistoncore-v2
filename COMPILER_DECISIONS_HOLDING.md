# PistonCore — Compiler Decisions Holding Doc

**Version:** 2.0 (July 2026 — adapted for the pistoncore-v2 pivot: the piston JSON is now stock webCoRE format authored by the vendored webCoRE dashboard; the v1 wizard and v1 nested-tree JSON are retired. All v1-JSON field names below are historical and re-key against PISTON_JSON_REFERENCE.md (webCoRE format) when it exists. v1.3 added C-TYPES; v1.2 added Section G sketches; v1.1 added Section E PyScript routing, verified vs PyScript 2.0.1 + HA 2026.6)
**Status:** Holding doc — not a spec; expected to drift and adapt as problems and
solutions are found. Captures compiler-relevant decisions (originally from
SPEAK_ACTION_SPEC.md, NOTIFY_ACTION_SPEC.md, and v1 sessions) so they survive into the
v2 compiler spec work. When the v2 compiler spec is written, fold these in and retire
this file. The two action specs live in the v1 repo — carry them into pistoncore-v2
before the compiler sessions.
**Authority:** The two action specs are authoritative for their own action types. This doc
is a faithful POINTER + extraction, not a replacement — if anything here disagrees with
SPEAK_ACTION_SPEC.md or NOTIFY_ACTION_SPEC.md, those win. Extract verbatim-faithful from
them at the v2 compiler spec, not from this summary.

---

## Why this file exists

The v1 compiler specs (COMPILER_SPEC.md / PYSCRIPT_COMPILER_SPEC.md) are retired with the
v1 JSON. The v2 compiler consumes stock webCoRE piston JSON (PISTON_JSON_REFERENCE.md,
pending) and its spec does not exist yet. Until it does, this file holds the compiler
decisions already paid for in v1 that remain true in v2.

The governing rule for everything below (Jeremy, Session 73; restated for v2): **what the
user sees in the editor is the contract — and in v2 the editor is the stock webCoRE
dashboard, so the piston JSON as webCoRE emits it is law; PistonCore adapts to it, never
the reverse.** The decisions worth preserving are the *behavioral* ones (what HA must end
up doing) and the *policy* ones (read-only compiler, debug-page errors, Jinja2-everywhere).
v1 field names appearing below are NOT contracts — they re-key against
PISTON_JSON_REFERENCE.md (webCoRE format) at coding time.

---

## A. Cross-cutting compiler policy (applies to BOTH Speak and Notify, likely all actions)

1. **Compiler is read-only.** It reads the JSON and NEVER writes, reshapes, or mutates it.
   The editor/wizard authors the JSON; it is the source of truth; the compiler is
   input-only. (This is the rule whose violation has bitten the project before.)
2. **Errors go to the debug page, never to mutation.** On any incompatibility (device can't
   speak, no TTS engine, notify target unresolvable, kind unrecognized), the compiler does
   NOT edit the JSON and does NOT silently drop the task — it writes a clear, specific
   debug-page error naming the offending device/engine/target and why. Source stays
   untouched regardless of compile outcome.
3. **All HA YAML values go through Jinja2.** Standing project rule, no exceptions.
4. **One canonical variable→Jinja substitution function.** The variable-token → Jinja
   substitution MUST reuse the single canonical substitution function used elsewhere in the
   compiler. Do NOT introduce a second variable-substitution path for Speak or Notify.
5. **Compile-time live-HA lookups inform the OUTPUT only, never the source JSON.** The
   compiler may pull live HA at compile time (engine selection, device compatibility,
   target resolution) to make its hidden translation correct, but those lookups only shape
   what it emits.
6. **Entity resolution happens at COMPILE via the hash ↔ entity_id map.** (Rewritten for
   v2 — the v1 name+capability/`role_tokens` model is retired with the wizard.) Stock
   webCoRE piston JSON stores **hashed device IDs** (`:` + md5("core." + entity_id) + `:`,
   VERIFIED from webcore.groovy). Because the hash is a deterministic function of the
   entity_id, resolution is a pure lookup through the bidirectional map maintained by the
   shim (DEVICE_PAYLOAD_SPEC.md Stage 6):
   - **Happy path:** hash → entity_id → live HA entity at compile time.
   - **Offline device:** the hash still resolves — the map entry persists regardless of the
     entity's availability, so a temporarily-dark device keeps its identity and the piston
     compiles whole. The v1 prior-YAML-grep fallback is no longer needed for identity; it
     existed only because friendly names could not durably resolve.
   - **No silent drop, no placeholder, no partial output.** A hash with no map entry
     (foreign piston import referencing a device this install has never seen) is a real
     unresolvable error → A2 debug-page error naming the hash and any name hints available.
   - Editor side: the stock dashboard keeps device IDs in the JSON regardless of live
     availability — nothing prunes an offline device except explicit user removal. The v1
     edit-side token-persistence rule is satisfied by webCoRE's own behavior for free.

---

## B. SPEAK / TTS — behavioral decisions the compiler must honor

Authoritative source: SPEAK_ACTION_SPEC.md. Pulled here: the decisions, not the field names.

### B1. Volume is a SEPARATE sibling step, not an inline Speak parameter (LOAD-BEARING, behavioral)

In the editor and in execution, Set Volume is its own task ordered *before* the Speak task
inside the same with-block — exactly as WebCoRE shows it (`Set Volume to 70;` then
`Speak text "{Message}";`). Volume is NOT a field on the Speak task.

**Why this is load-bearing and not cosmetic:** Jeremy's actual Sonos type does not honor an
inline Speak volume the way Hubitat did. Emitting volume as a real `media_player.volume_set`
step is what makes the volume actually change on his hardware. The compiler emits, in order,
per with-block containing a speak task:
1. `media_player.volume_set` (if a Set Volume task is present) against the block's resolved
   output entities — **with the 0–100 (WebCoRE/UI scale) → 0.0–1.0 (HA) conversion done HERE,
   in the compiler, never in the stored JSON** (see also GAP-S72-3).
2. `tts.speak`.

This ordering (volume THEN speak) is preserved on the PyScript target too.

### B2. Engine resolved at COMPILE time from a global; never stored on the node

No TTS engine appears in the piston (matches WebCoRE — `Speak text` carries no engine). The
engine is environment config, resolved at compile time from a global "default TTS engine"
setting (a `tts.*` entity discovered from HA states). The node is engine-agnostic.

`tts.speak` has two distinct fields the compiler must not conflate:
- `target.entity_id` = the engine (a `tts.*` entity, from the global).
- `data.media_player_entity_id` = the output device(s) (the with-block's resolved entities).
The engine is never a media_player; the media_player is never the target.

### B3. `cache: true` emitted by default

The compiler emits `data.cache: true` on `tts.speak` by default. This is the HA-side
equivalent of the offline clip caching Jeremy relies on under Hubitat — HA synthesizes the
audio once and persists it, so a local engine (Piper) doesn't re-synthesize every fire and
announcements have no live cloud dependency. Whether `cache` later becomes a user toggle is
a UI decision; default-on is the contract.

### B4. SSML — passthrough, never opted-in or stripped

The message is passed verbatim. The compiler does NOT inject `options.text_type: ssml` and
does NOT strip SSML. SSML rendering is entirely a property of the resolved engine (Piper has
no SSML support at all; SSML-capable engines need an explicit opt-in that lives in global
engine config, not the node). Rate/cadence (the original `<prosody rate>` intent) is an
engine concern (Piper `length_scale` at the voice/Wyoming level), never a node concern. This
keeps Speak engine-agnostic and fully local-capable.

### B5. Feasibility confirmed (Session 73)

Message-from-live-data → native HA Script `variables:` block with Jinja2 interpolation,
spoken by Piper, cached, played on Sonos — zero cloud dependency, no PyScript required for
the variable mechanic. Recorded so it isn't re-litigated.

### B6. Backend plumbing Speak needs (carried from SPEAK spec §6)

(v1 file/line references retired; requirements carried into the v2 shim.) Both come from
the same HA state fetch the shim already performs for DEVICE_PAYLOAD_SPEC.md:
- `attributes.supported_features` (PLAY_MEDIA bit) must survive into whatever author-time
  gate decides which media_players are speakable — in v2 that gate is the capability set
  the device payload advertises (a speakable player gets the speech-capable capability;
  one that can't, doesn't).
- `tts.*` entities must be enumerated (they are not devices — exclude from the device
  payload) to feed the global "default TTS engine" setting the compiler reads (B2).

---

## C. NOTIFY / PUSH — behavioral + structural decisions the compiler must honor

Authoritative source: NOTIFY_ACTION_SPEC.md. Pulled here: the decisions, not the field names.

### C1. The node stores a STABLE TARGET REFERENCE, never a hard-coded HA service string (LOAD-BEARING)

This is the entire churn-insurance policy and it's a compiler concern. HA notify is
mid-transition (legacy per-target `notify.mobile_app_*` services today; `notify.send_message`
with entity targets emerging in 2026.5+ but not yet covering rich companion-app payloads).
So the stored piston must NOT contain a resolved HA service call. It stores a stable target
reference; the compiler resolves that reference to whatever HA currently wants **via a Jinja2
template selected by the target's kind**. When HA flips the legacy path off or a target
moves to the entity path, ONLY the template changes — stored pistons, the picker, and the
JSON shape are untouched.

The compiler emits, by target kind:
- legacy mobile_app target → a `notify.<id>` service call with `message`/`title`/`data`.
- entity target (emerging) → `notify.send_message` with the target as `target.entity_id`.

v1 targets the legacy `mobile_app_*` path (what Jeremy runs); the entity-target branch is
specified as a seam but is not primary until HA's entity path covers rich payloads.

> The discriminator that tells the template which path to emit is REQUIRED behaviorally
> (the compiler must know legacy-service vs entity target). How it's stored (a `kind` field
> or otherwise) is a coding-time storage choice, NOT a decision for Jeremy and NOT a fixed
> spec contract — reconcile against PISTON_JSON_REFERENCE.md (webCoRE format). The fixed requirement is only that the
> stored target reference is stable and resolves through a template, never a baked service
> string.

### C2. Notify targets come from the SERVICE REGISTRY — a SECOND HA fetch (structural)

Notify targets are NOT entities and are NOT in `get_states`. They live in the service
registry. This forces new backend plumbing: a second HA fetch via `/api/services` (REST) or
`get_services` (websocket), take the `notify` domain, enumerate its services. This parallels
how Speak needs `supported_features` carried and `tts.*` enumerated, but the source is a
different endpoint. **v2 surface TBD:** how notify targets present inside the stock webCoRE
dashboard (its Send Push/notification virtual commands and their parameters) must be mapped
when PISTON_JSON_REFERENCE.md is written — the structural fact recorded here is only that
the target list comes from the service registry and feeds the compiler's resolution (C1).

### C3. message/title interpolation; `data` holds the rich payload

`message` and `title` are token-interpolated strings (literal + variable tokens) using the
same canonical substitution path as Speak. The companion-app richness (actionable buttons,
image, tag/group, priority, TTS-to-phone) lives in the action's `data` payload, attached to
the target's capabilities — NOT on the picker target. v1 may ship message+title plus a core
`data` subset and stage the rest; the contract is only *where* they live and *that* they use
the canonical interpolation path. The per-target-type `data` mapping is a coding-time job
against the live Companion App docs.

---

## C-TYPES. GLOBAL / VARIABLE TYPE TRANSLATION — WebCoRE type → HA storage (compiler reference)

The editor (stock webCoRE dashboard) presents WebCoRE's variable type names.
Translating a WebCoRE type to whatever Home Assistant actually needs is the compiler's
job — the compiler makes HA match the piston's intent. This section is the behavior map
for that translation. **Map by behavior, NOT by name — WebCoRE and HA names do not
reliably match.** This applies to globals and to local variables alike (same types; globals
just live in the shared external list instead of the piston JSON).

| WebCoRE type (user-facing, what value it holds) | HA storage by behavior | Name-mismatch caution |
|---|---|---|
| integer (whole numbers; decimals floored) | `input_number` | HA has ONE numeric helper — no separate integer/decimal. Use mode/min/max/step. |
| decimal / float (fractional numbers) | `input_number` | Same single HA helper as integer — WebCoRE's two numeric types collapse to one. |
| string / text | `input_text` | — |
| boolean (true/false) | `input_boolean` | HA values are `on`/`off`, NOT `true`/`false`. Do not map by the word "boolean." |
| datetime / date / time (three WebCoRE types) | `input_datetime` | ONE HA helper with `has_date` / `has_time` flags covers all three. |
| device (list of device IDs) | NOT an input helper | Stored as arrays of **hashed device IDs** (stock webCoRE format, VERIFIED from dashboard source); resolved through the shim's hash ↔ entity_id map (A6). HA has no "device variable" helper. |

**Key points:**
- WebCoRE's ~7 value types collapse to **4 HA input helpers + the device-picker path**.
- The three traps that break name-based mapping: boolean → on/off (not true/false);
  date/time/datetime → one `input_datetime` (not three); integer+decimal → one
  `input_number` (not two).
- Device globals are NOT input helpers — they hold hashed device IDs exactly like local
  device variables in webCoRE JSON, resolved per A6. Runtime storage feeding the compiler:
  globals export to JSON (or other shim-side storage) that the compilers read; see H for
  how referencing automations get updated on change.
- Globals are any of these types with an `@` prefix, shared across pistons. WebCoRE also
  has superglobals (`@@` prefix) shared across instances — note for future scope, not v1
  (PistonCore collapses the broker to a single local HA instance, so cross-instance
  superglobals have no v1 role).
- The `set_variable` compile sketch in Section G shows the global-write shape
  (`input_text.set_value` against `input_text.pistoncore_*`) — that example's helper choice
  must agree with this table at the v2 compiler spec (a string global → `input_text`).

**Source:** WebCoRE variable data types confirmed from wiki.webcore.co (Variable_data_types,
Variable, Functions) and the ady624/webCoRE Groovy source; HA helper behavior from HA helper
documentation. Verify live at the v2 compiler spec — HA helper capabilities move over time.

---

## D. OPEN — not decided, do not treat as settled


- **Command classification is a PENDING research deliverable.** The full WebCoRE command
  menu (device / emulated / location — see WITH_BLOCK_TASK_FRAMEWORK.md §5.4) must be sorted
  by the **reproduce-cleanly test** against CURRENT HA: can HA cleanly reproduce the action
  (native / PyScript / via an add-on or integration that exposes usable, relevant state)? If
  yes → it STAYS in the wizard. If there's no clean way to reproduce the RESULT → it is CUT
  from the wizard and recorded on the living "can't reproduce in HA currently" docs list (a
  lossy rename to a rough HA equivalent does NOT count as reproducing it). HA moves monthly,
  so version-sensitive commands must be researched live, not classified from memory — and
  **what is hard-impossible is NOT predetermined.** **The non-device command set WAS
  researched in Session 73 — authoritative dated results are in HA_LIMITATIONS.md §10 (vs HA
  2026.6).** Key correction to earlier assumptions: HSM (Set Hubitat Safety Monitor status),
  web request, and file read/write are REPRODUCIBLE and STAY (HSM → HA built-in
  `alarm_control_panel`; web request → `rest_command`; file → File integration). The genuine
  cuts are Hubitat/WebCoRE-platform artifacts (piston tiles, piston engine state) — the ONLY
  two. Research is COMPLETE: capture/restore (→ scene.create), IFTTT-as-webhook
  (→ rest_command), set location mode (→ input_select), and LIFX effects (native lifx.*
  actions) all reproducible. Read §10 rather than this summary (HA_LIMITATIONS.md lives in
  the v1 repo — carry it into pistoncore-v2). (Scope reduction, Session 73: the earlier
  "render everything, fail only at compile" model is dropped.)

---

## E. PYSCRIPT ROUTING — Verified decisions for the compiler (June 2026)

These decisions were researched against PyScript 2.0.1 and HA 2026.6 and are now locked.
They belong in the v2 compiler spec when it is written. Until then, this is the
authoritative holding location. **v2 re-key note:** the JSON field names/values in E2 and
E4 are v1 schema names — the *semantics* (which webCoRE features force PyScript) are the
verified content; the left column re-keys to the webCoRE JSON signatures for the same
features when PISTON_JSON_REFERENCE.md is written. Sources: PyScript official docs (hacs-pyscript.readthedocs.io),
HA script-syntax docs 2026.6.3, WebCoRE wizard source (piston.module.html + piston.js,
pulled June 2026).

### E1. Routing goes through a backend template — never hardcoded, never in the frontend (LOAD-BEARING)

HA gains native capability over time. The routing mechanism must be a data-driven template
that the backend reads — not a hardcoded list, and NOT in the frontend. When HA adds native
support for a feature that currently forces PyScript, ONLY the routing table file changes.
Stored pistons, the wizard, the JSON schema, and the frontend are all untouched.

**Backend owns the routing decision.** The flow on every save:
1. Dashboard saves the piston through the shim's set/set.end flow (SHIM_API_SPEC.md §4.7)
2. Backend reads the piston JSON and scans it against the routing table file
3. Backend sets `compile_target` (`"native_script"` or `"pyscript"`) on the piston wrapper
4. Backend writes the piston to disk with `compile_target` set
5. Backend returns the saved piston (with `compile_target` now populated) to the frontend
6. Frontend reads `compile_target` off the wrapper — if `"pyscript"`, shows the notice on the debug/compile screen

The frontend NEVER determines what forces PyScript. It only reads `compile_target` and
displays accordingly. This means the routing can be updated (a feature goes native in HA,
or a new PyScript feature is discovered) by editing the routing table file and redeploying —
no frontend change, no spec change, no coding session required for the routing logic itself.

**The routing table file** (`routing_table.json`) lives in the backend (v2: the shim). It
maps piston-JSON signatures (webCoRE format) to required compile targets. The backend reads
it at startup (or on each save request if hot-reload is desired). Format: to be determined
at the v2 compiler spec — must be simple enough that Jeremy can read and update it without
a coding session. In v2 the scan naturally happens in the shim's save flow
(SHIM_API_SPEC.md §4.7), after piston reassembly.

**`compile_target` is a backend-set cache, not a user preference.** It is never shown in
the editor as an editable field. It is shown read-only in the Quick Facts panel on the
status page and as a label in the Test Compile panel header.

**The help system (`pyscript.md`)** is the user-facing companion to the routing table.
When a user sees the PyScript notice on the debug screen, the `[Learn more →]` link opens
the help file that explains what PyScript is, why their piston needs it, and how to install
it. This file is also backend-served markdown — editable without a coding session.
See FRONTEND_SPEC.md Help System section for the full spec.

### E2. Full verified PyScript routing table (as of June 2026)

The following JSON fields/values force `compile_target: "pyscript"`. Verified against
PyScript 2.0.1 docs and HA 2026.6 native script syntax docs.

| JSON field / value | PyScript mechanism | Native HA status |
|---|---|---|
| `type: "on_event"` | `task.wait_until()` | No equivalent |
| `type: "break"` | Python `break` | Native `stop` only ends current block — not a loop break |
| `type: "cancel_pending_tasks"` | `task.unique()` | No equivalent |
| `condition_operator: "xor"` on any statement | Python expression `sum([...]) == 1` | No native XOR |
| `operator: "followed_by"` on condition group | Chained `task.wait_until()` with shared deadline | No sequential event chaining |
| `case_traversal_policy: "fallthrough"` on switch | Python `if/elif` without early exit | `choose` always exits first match |
| `interval_unit: "n"` or `"y"` on every | `@time_trigger("cron(...)")` | `time_pattern` has no dom/month fields |
| Non-empty `only_on_dom` on every | cron `dom` field | `time_pattern` has no dom field |
| Non-empty `only_on_months` on every | cron `mon` field | `time_pattern` has no month field |
| Non-empty `only_on_wom` on every | Runtime check in function body | No cron equivalent |

### E3. User notification requirement (BEHAVIORAL — must not be dropped)

When any piston compiles to PyScript, the compiler must surface a prominent notice on
the debug/compile screen: "This piston uses features that require PyScript. It will be
deployed as a PyScript file, not a native HA automation. PyScript must be installed via
HACS." This is not optional — users who haven't installed PyScript will have silently
non-functional pistons. The notice must be at the top of the debug output, not inline.

### E4. `on_event` timeout fields (BEHAVIORAL)

(v1 schema fields — the behavioral requirement survives; where the equivalent knobs live
in webCoRE JSON, if anywhere, is a PISTON_JSON_REFERENCE.md question.) The v1 on_event
schema carried `timeout_seconds` (integer or null) and `continue_on_timeout` (boolean,
default false). The compiler must:
- If `timeout_seconds` is null → emit `task.wait_until(...)` with no timeout and emit
  `CompilerWarning: ON_EVENT_BLOCKING` (existing requirement, unchanged).
- If `timeout_seconds` is set → emit `task.wait_until(..., timeout=N)` and respect
  `continue_on_timeout` to either continue or stop after timeout.

### E5. `exit` value — open decision

`exit` `value` field: native HA `stop:` drops it silently. PyScript can write the value
to a piston-state helper entity before stopping. **Decision required at the v2 compiler spec:** implement
the PyScript path or emit `CompilerWarning: EXIT_VALUE_DROPPED` for both targets and
document it. Do not silently drop without at least the warning.

### E6. `every` `only_on_wom` — runtime check pattern

`only_on_wom` (weeks of month) has no direct cron equivalent. The PyScript compiler must
emit a cron that fires on the correct days of the month (via `dom`), then add an early-
exit `if` check inside the function body to guard against wrong weeks. The exact Python
expression for "Nth week of month" must be confirmed at the v2 compiler spec against real
HA behavior.

---

## G. Per-statement compile-output SKETCHES — OUTPUT-ONLY reference, UNVERIFIED

**DECISION (Jeremy, 2026-07-07): OUTPUT SIDE ONLY.** The input JSON shown in these sketches
is the retired v1 nested-tree format and is DEAD — do not use it, do not re-key it, do not
treat any input field name as real. What is preserved here is the **HA-output side**: what
each statement kind should become in native YAML or PyScript. When the v2 compiler spec is
written, pair each sketch's output with the corresponding webCoRE JSON statement from
PISTON_JSON_REFERENCE.md and validate against real HA before carrying anything forward.

**Status of this section:** LOWER confidence than A–E and C-TYPES. These are illustrative YAML output
sketches pulled verbatim from the retired PISTON_FORMAT_MERGED.md when it was decomposed
(this session). They are NOT verified against a working compiler (the compiler is frozen
until the v2 compiler spec). Several contain placeholders like `[compiled statements]`. They show the
*intended shape* of native HA output per statement type — a starting reference for the v2
compiler work, not a decision and not a contract. At that point, validate each against actual HA
behavior; do not lift verbatim. Field names reconcile against the Structure Map at coding time.

Source: PISTON_FORMAT_MERGED.md `### Compiler Output` blocks (now retired). PyScript-routed
types (on_event, break, cancel_pending_tasks, switch fallthrough) — see Section E for the
verified routing; the sketches below show only the native-target shape where one exists.

### action

```yaml
- alias: "stmt_001"
  action: light.turn_on
  target:
    entity_id:
      - light.living_room
  data:
    brightness_pct: 75
  continue_on_error: true
```

---

### do

```yaml
- alias: "stmt_002"
  sequence:
    [compiled statements]
```

---

### if

```yaml
- alias: "stmt_003"
  if:
    - condition: template
      value_template: "[compiled condition]"
  then:
    [compiled then statements]
  else:
    [compiled else statements]
```

---

### switch

**`case_traversal_policy: "safe"` (native HA):**
```yaml
- alias: "stmt_004"
  choose:
    - conditions:
        - condition: template
          value_template: "{{ states('input_number.pistoncore_count') | int == 1 }}"
      sequence:
        [compiled case statements]
  default:
    [compiled default statements]
```

**`case_traversal_policy: "fallthrough"` (PyScript only):** Forces `compile_target: "pyscript"`. Native HA `choose` always exits after the first matching branch — fall-through is impossible. PyScript emits real Python `if/elif` blocks without early exit between branches. Compiler emits `PYSCRIPT_REQUIRED`.

---

### for

```yaml
- alias: "stmt_005"
  repeat:
    count: 10
    sequence:
      [compiled statements]
```

**Note:** Emits CompilerWarning if start != 1 or step != 1.

---

### for_each

```yaml
- alias: "stmt_006"
  repeat:
    for_each:
      - sensor.smoke_detector_basement
      - sensor.smoke_detector_kitchen
    sequence:
      [compiled statements — actions use target.entity_id: "{{ repeat.item }}"]
```

---

### while

```yaml
- alias: "stmt_007"
  repeat:
    while:
      - condition: template
        value_template: "[compiled condition]"
    sequence:
      [compiled statements]
```

---

### repeat

```yaml
- alias: "stmt_008"
  repeat:
    sequence:
      [compiled statements]
    until:
      - condition: template
        value_template: "[compiled until condition]"
```

---

### every

Compiles as a trigger in the automation wrapper, not as a statement in the script body.

**Native HA (`compile_target: "native_script"`):**

`ms`, `s`, `m`, `h` intervals with no `only_on_dom`, `only_on_wom`, or `only_on_months` filters:
```yaml
- trigger: time_pattern
  minutes: "/5"
```

**PyScript forced when:** `interval_unit` is `"n"` or `"y"`, OR any of `only_on_dom`, `only_on_wom`, `only_on_months` is non-empty. Reason: native HA `time_pattern` has no day-of-month, week-of-month, or month fields.

**PyScript output:** `@time_trigger("cron(min hr dom mon dow)")` using Linux crontab syntax. Restriction arrays map to comma-separated cron fields. `only_on_wom` has no direct cron equivalent and requires a runtime check inside the function body.

**Routing rule:** If `interval_unit` is `"n"` or `"y"`, or `only_on_dom`/`only_on_wom`/`only_on_months` is non-empty → compiler emits `PYSCRIPT_REQUIRED` and routes to PyScript. All other cases compile natively.

---

### on_event

PyScript only. Forces PyScript compilation via target-boundary.json.
Native HA script compilation raises CompilerError with code `PYSCRIPT_REQUIRED`.

---

### break
_(merged spec also had editor-render notes here — not compiler content)_

Editor: `break;`
Compiler: PyScript only. Native HA raises CompilerError.

---

### exit

**Native HA:** The `value` field is dropped — HA `stop:` has no piston-state concept.
```yaml
- alias: "stmt_012"
  stop: "exit"
```

**PyScript:** The `value` field can be written to a piston-state helper entity before stopping. **Design decision required at the v2 compiler spec** — whether to implement this or emit `CompilerWarning: EXIT_VALUE_DROPPED` and drop it silently for both targets.

---

### set_variable

Piston variable:
```yaml
- alias: "stmt_013"
  variables:
    message: "Hello"
```

Global variable:
```yaml
- alias: "stmt_013"
  action: input_text.set_value
  target:
    entity_id: input_text.pistoncore_message
  data:
    value: "Hello"
```

---

### wait_duration
_(merged spec also had editor-render notes here — not compiler content)_

Editor: `do Wait 5 minutes;`

```yaml
- alias: "stmt_014"
  delay:
    minutes: 5
```

---

### wait_until
_(merged spec also had editor-render notes here — not compiler content)_

Editor: `do Wait until 11:00 PM;`

```yaml
- alias: "stmt_015"
  wait_for_trigger:
    - trigger: time
      at: "23:00:00"
  timeout:
    minutes: 60
  continue_on_timeout: true
```

Always emits CompilerWarning. `timeout` defaults to 1 hour.

---

### wait_for_state

```yaml
- alias: "stmt_015b"
  wait_template: "[compiled condition template]"
  timeout:
    seconds: 300
  continue_on_timeout: true
```

---

### log_message

```yaml
- alias: "stmt_016"
  event: PISTONCORE_LOG
  event_data:
    piston_id: "a3f8c2d1"
    message: "Piston ran successfully"
    level: "info"
```

---

### call_piston

```yaml
- alias: "stmt_017"
  action: script.pistoncore_b7e2a1f4
```

If `wait_for_completion: true` with native script target → CompilerError.

---

---

## H. Device Global Update — Targeted Patch, Not Full Recompile

**Decision (Jeremy, session — June 2026):** When a device global is edited (devices added
or removed from the group), updating the referencing pistons is a **targeted patch
operation**, not a full recompile. The piston logic does not change — only which devices
are targeted changes.

**Why this problem doesn't exist in stock webCoRE (VERIFIED, 2026-07-10):** stock webCoRE
is an *interpreter*, not a compiler — `executePiston()` → `piston.execute()` reads the
piston's stored JSON (which only ever holds `@Name`, never a resolved device list, per H1)
and resolves it against the live `atomicState.vars` **fresh on every execution**
(`reference/webcore_source_reference.groovy:2173-2184` — `sendVariableEvent` even fires a
platform event on global change, for pistons that trigger on it). There is no compiled
artifact to go stale, so stock webCoRE has nothing to patch. This problem is entirely a
consequence of PistonCore choosing to compile ahead-of-time into static HA automation
YAML/PyScript. **Nothing to adapt from webCoRE here — this is PistonCore's own design.**

### H1. What the patch does

(Rewritten for v2.) For each piston in the global's `used_by` list:
1. **JSON patch — CONFIRMED unnecessary in v2 (VERIFIED, 2026-07-10, against
   `reference/webcore_source_reference.groovy:1495-1528` `api_intf_variable_set`).** The
   real Hubitat/SmartThings backend stores every global (device-type included) in ONE
   central map, `atomicState.vars`, keyed by `@Name`, holding `{t, v}` — `v` for a device
   global is just the device-id array. Pistons reference the global **only by name** in
   operands; the device list is never embedded in piston JSON, for any global type. The
   piston JSON genuinely never changes when a global's device list changes — the v1
   role_tokens JSON-walk is confirmed dead, not just assumed dead.
2. **HA update — via an HA `group` entity, not YAML/PyScript text patching (DECISION,
   2026-07-10):** every device-type global compiles to one dedicated HA `group` entity
   (e.g. `group.pistoncore_<slug(@Name)>`), and every compiled automation/PyScript that
   references that global targets **the group entity**, never raw resolved entity_ids
   directly. Updating the global then means calling HA's `group.set` service
   (`entity_id: group.pistoncore_<slug>`, `entities: [<resolved entity_ids>]`) —
   confirmed a real, current HA service that creates-or-updates a group's membership live,
   no YAML edit, no restart, immediate effect on every automation that targets it. The
   deployed automation/PyScript file is **never touched** on a device-global edit — only
   the group's membership changes. This sidesteps fragile text-patching entirely.
   **Caveat (verified):** `group.set`-created groups are **not persisted** across an HA
   restart — they're not backed by `configuration.yaml`, so a restart drops membership
   back to nothing. Mitigation: the shim (which owns the authoritative globals store)
   re-issues `group.set` for every device-type global whenever it detects HA has restarted
   — cheapest hook is the shim's own HA WebSocket client subscribing to HA's
   `homeassistant_started` event (same connection already used for `ha_client.py`) and
   replaying every device-global's current membership at that point. No separate polling
   job needed.

This is distinct from the full compile path. The compiler is NOT called for a
device-global patch — it only runs once, at first-compile, to decide that a device-type
global operand compiles to a `group.<slug>` target instead of literal entity_ids.

### H2. Update flow

The "Update all now" path routes through the shim (which owns globals storage in v2):

```
Globals change (variable/set, SHIM_API_SPEC.md §4.10) or "Update all now"
  → shim: call HA service group.set(entity_id=group.pistoncore_<slug>, entities=[...])
    (one call, regardless of how many pistons are in the global's used_by list —
     they all already target the same group entity)

HA restarts (shim's HA WebSocket client sees homeassistant_started)
  → shim: replay group.set for every device-type global from its own storage
```

`used_by` (H4) is still tracked — not for the patch itself (a single `group.set` call
updates every referencing piston at once, no per-piston iteration needed), but so the UI
can show "used by N pistons" and so a future full recompile knows which pistons to
revisit if the *group-vs-inline* compile strategy itself ever changes.

The shim owns this operation. The compiler is not involved.

### H3. Editor-open guard

Not needed. Since H1 confirms the piston JSON never changes on a device-global edit, and
the HA-side update (H1.2) is a `group.set` service call that never touches a deployed
file, there is nothing an open editor or a mid-save piston could ever clobber. The v1
editor-open guard concept does not apply in v2 and can stay retired.

### H4. Tracking mechanism — BUILT (2026-07-10, part of the save flow, shim/storage.py)

(Rewritten for v2 — the v1 wizard maintained `used_by`; the stock dashboard cannot.) The
**shim** maintains `used_by`, and it is better placed to do so than the v1 wizard was:
every save passes through the shim's set/set.end flow (SHIM_API_SPEC.md §4.7), so on each
save the shim scans the reassembled piston JSON for global references (`@Name` device
variables and any other global usage), adds this piston `{id, name}` to each referenced
global's `used_by`, and removes it from globals it no longer references. Event-driven at
the point of save. No background scan. No scheduled job. No frontend involvement.

`used_by` is stored on the global object in the shim's globals storage
(`shim/storage.py:update_used_by`, `{name: {t, v, used_by: [{id, name}, ...]}}`) and
travels with the globals-export JSON that feeds the compilers. Scanner
(`shim/storage.py:find_global_references`) does a generic tree walk for
`{"t": "x", "x": <name-or-list>}` operand nodes rather than enumerating every named field
(lo/ro/ro2/to/to2/wd/p/x/...) — operands can appear in many places and are always shaped
`{"t": ..., ...}`, so the generic walk is more robust than hardcoding field names.

### H5. Status at time of writing

Tracking (H4) is **built** — part of the milestone 3 save flow. The `group.set`-based
patch mechanism (H1.2, H2) is **designed and verified** (HA capability confirmed via web
search, 2026-07-10) but not yet built — there's no compiler yet to decide the
group-vs-inline compile strategy, and nothing deployed yet worth patching. The `used_by`
data is accurate and ready for when the compiler is built. The v1 globals UI is retired;
v2 globals are edited in the stock dashboard's variable editor (served by
SHIM_API_SPEC.md §4.10).

---

## F. Retirement

When the v2 compiler spec is written (after PISTON_JSON_REFERENCE.md locks the webCoRE
JSON as the input format): extract Sections A–E (and C-TYPES) verbatim-faithful from
SPEAK_ACTION_SPEC.md, NOTIFY_ACTION_SPEC.md, and this file into the v2 compiler spec,
resolve the Section D open items and the H1/E2 TO-VERIFY/re-key items against the webCoRE
JSON, then delete this holding doc. Until then, this file is the single place those
compiler decisions are collected.

**Section G (compile-output sketches)** is OUTPUT-ONLY reference (see G header) — at the v2 compiler spec, validate each sketch's output against real HA and pair it with the webCoRE JSON statement; do not carry any sketch forward unverified. It is the lowest-confidence content in this file.

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
up doing) and the *policy* ones (read-only compiler, surfaced-not-mutated errors,
Jinja2-everywhere).
v1 field names appearing below are NOT contracts — they re-key against
PISTON_JSON_REFERENCE.md (webCoRE format) at coding time.

---

## A. Cross-cutting compiler policy (applies to BOTH Speak and Notify, likely all actions)

1. **Compiler is read-only.** It reads the JSON and NEVER writes, reshapes, or mutates it.
   The editor/wizard authors the JSON; it is the source of truth; the compiler is
   input-only. (This is the rule whose violation has bitten the project before.)
2. **Errors are surfaced, never silently mutated or dropped.** On any incompatibility
   (device can't speak, no TTS engine, notify target unresolvable, kind unrecognized), the
   compiler does NOT edit the JSON and does NOT silently drop the task — it raises a clear,
   specific error naming the offending device/engine/target and why, shown on the two
   surfaces CLAUDE.md's UI split defines (front-door piston-list indicator + a banner on
   that piston's own status/view screen) — no error ever ANNOUNCES itself anywhere else
   (Jeremy, 2026-07-12: "adding another level would irritate the hell out of me and any
   future user"). A drill-in compiler help/debug screen may exist for detailed fixing help,
   but only reached from those two surfaces or Settings — never a place an error shows up
   on its own. Source stays untouched regardless of compile outcome.
3. **One canonical error-record shape, designed alongside the debug screen, not bolted on
   after (DECISION, Jeremy 2026-07-12).** Every check the compiler runs (device resolution,
   capability mapping, engine availability, PyScript routing, HA service-call failures)
   raises through ONE structured error record — not each check inventing its own ad hoc
   failure shape that then has to be reconciled later. Fields the record needs at minimum:
   which piston, which statement/device/command, a plain-language explanation, and a
   **"check HA updates" pointer** — the HA domain/service/component implicated, so whoever
   (or whatever) investigates knows exactly where to look in HA's own release notes/
   breaking-changes list for what changed, rather than PistonCore trying to pre-populate a
   link to every possible future HA changelog entry (unmaintainable at scale — HA changes
   constantly, PistonCore can't know in advance what each future break will be).
   Two consumers: (a) the human-facing surfaces (front-door indicator, piston status-
   banner, the drill-in help screen), and (b) a future AI-assisted session reading the same
   feed to diagnose the break and propose the template fix. The drill-in help screen's link
   goes to a PistonCore-authored doc ("how to have an AI update the templates" — a generic
   walkthrough of the fix workflow, NOT written per-error) — the "check HA updates" pointer
   is what lets that AI session go find the SPECIFIC fix for THIS break. Ties to the
   "Recompile All" item (SPEC_ADDENDA_GEMINI.md §3) — the error feed tells you WHICH
   template needs updating, the HA-updates pointer tells the AI WHERE to look for how,
   Recompile All pushes the fixed template to every piston once it's done. Design this
   record's shape when the compiler spec is written; do not let ad hoc per-check error
   handling accrete first. The "how to have an AI update the templates" doc itself is not
   yet written — TO DO when the compiler spec exists.
4. **All HA YAML values go through Jinja2.** Standing project rule, no exceptions.
5. **One canonical variable→Jinja substitution function.** The variable-token → Jinja
   substitution MUST reuse the single canonical substitution function used elsewhere in the
   compiler. Do NOT introduce a second variable-substitution path for Speak or Notify.
6. **Compile-time live-HA lookups inform the OUTPUT only, never the source JSON.** The
   compiler may pull live HA at compile time (engine selection, device compatibility,
   target resolution) to make its hidden translation correct, but those lookups only shape
   what it emits.
7. **Entity resolution happens at COMPILE via the hash ↔ entity_id map.** (Rewritten for
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
     unresolvable error → A2 error naming the hash and any name hints available, surfaced
     per the two-surface rule above (no separate debug page).
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

**CORRECTED 2026-07-12 (Jeremy, real piston screenshots).** `NOTIFY_ACTION_SPEC.md`'s
central premise — "a notify target is NOT a device, it needs its own picker section and a
new `target_ref`/`kind` JSON field" — was reasoned from HA architecture alone and is
**WRONG**. Jeremy's real, working pistons (e.g. the Water Leak piston) show the actual
mechanism: `@Notifications_Push` is an ordinary **device-type variable**, populated with
real "Notification"-capability devices, used in a completely normal
`with {@Notifications_Push} do Send device notification "..."` block — the stock
`deviceNotification` command (capability `notification`, `c: ["deviceNotification"]`,
already in `webcore_vocab.json`), same mechanism as any other device command. No Contact
Book, no per-task target field, no custom JSON shape. `sendNotificationToContacts`
(SmartThings Contact Book) and `sendSMSNotification` (literal phone-number param) are real
stock commands too but are NOT what Jeremy's Hubitat setup uses — do not build toward them.

**Implemented (`shim/device_pipeline.py`, 2026-07-12):** each `notify.mobile_app_*` service
(VERIFIED live `get_services`, HA 2026.7.2 — legacy per-target services; generic
`notify.notify`/`persistent_notification`/`send_message` excluded, they're not a single
destination) becomes a synthetic picker device — same `n/cn/a/c` shape as any real device,
capability `Notification`, command `deviceNotification`, no attributes — hashed from the
service name exactly like every other device. **No rebind/override mechanism**: if the
service name ever changes (phone replaced/re-registered), the old hash simply stops
resolving and the piston shows broken in the editor, same "honest breakage, re-pick in the
UI" rule as any other device (DEVICE_PAYLOAD_SPEC Stage 7) — Jeremy confirmed this is
correct and expected, not a gap to design around. Zero mobile_app services exist on the
test HA today (no phone set up yet), so this is verified as dead-code-safe (returns zero
synthetic devices, no errors) but not yet behaviorally verified end-to-end in the dashboard.

**C1's original "stable target reference" concern is now moot, not unsolved:** since a
notify target is just a hashed device id like any other, the churn-insurance C1 wanted
(never a hard-coded HA service string baked into the piston) already exists for free — the
piston stores `<hashedId>` in the `with` block's device list exactly like any other device,
and the resolution map (Stage 8) is what holds the real `notify.<service>` string, looked up
at compile time. **Future compiler note:** resolving a `deviceNotification` task means
reading the resolution map's `registry_device_id` for that hashed id (already the full
`notify.<service_name>` string), splitting it into an HA service call `action: notify.<name>`
with `data: {message: <compiled message>}` — a single, direct call, no `kind`-branched
Jinja2 template needed (that branching was for the old, wrong design). `sendPushNotification`/
`sendNotificationToContacts`'s stock params (message + optional store-in-messages boolean)
should map onto this the same way if Jeremy ever uses those commands too — same target
resolution, just a different source command key.

Authoritative source: NOTIFY_ACTION_SPEC.md for HA-side facts (tts.speak-adjacent research,
Companion App payload docs) — its picker/JSON-shape design (Section 1, Section 4.4) is
superseded by the correction above; do not implement `target_ref`/`kind`.

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

- **Execution-mode default — genuinely undecided, real options now on the table
  (PYSCRIPT_COMPILER_RESEARCH.md §6, ported 2026-07).** All four HA modes are reproducible
  on both compile targets (`parallel`=default/zero-code, `restart`=`@task_unique`,
  `single`=`@task_unique(kill_me=True)`, `queued`=an `asyncio.Lock`-held function body on
  PyScript; `mode: single/restart/queued/parallel` directly on YAML automations/scripts).
  The question is which one the compiler picks as the DEFAULT when the piston JSON doesn't
  force a specific one. Two real candidates, genuinely in tension:
  - webCoRE itself serializes piston executions per-piston via its own semaphore
    (§2.5 point 1 — events queue, one processed at a time) — that argues `queued` as the
    faithful default.
  - HA automations themselves default to `single` — that argues consistency with what an
    HA-native user would expect from an unconfigured automation.
  Whatever gets picked must apply IDENTICALLY to both compile targets so they agree with
  each other. Do not silently default to one — this needs one explicit line in the v2
  compiler spec, decided once by Jeremy.
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
When a user sees the PyScript notice on the status page, the `[Learn more →]` link opens
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

### E5. `exit` value — PyScript half now has a concrete mechanism; YAML half still open

`exit`'s `value` field (real field name: statement `t:"exit"`'s `lo` operand — VERIFIED,
PISTON_JSON_REFERENCE §2.2): native HA `stop:` drops it silently.

**PyScript path — VERIFIED, concrete (PYSCRIPT_COMPILER_RESEARCH.md §7, ported 2026-07):**
`state.persist("pyscript.pistoncore_<piston_id>_state", ...)` gives a real,
restart-surviving piston-state entity — the exit value writes there before the piston
stops, visible in Developer Tools, readable by other pistons on either compile target
(it's a normal HA entity once persisted). This closes the PyScript half of this decision.

**YAML path — DECIDED 2026-07-15 (make-it-work rule, COMPILER_SPEC §5): IMPLEMENT.**
`state.persist` is PyScript-only, so the native target writes its piston-state helper
entity (`input_text.pistoncore_<piston_id>_state`, C-TYPES scalar pattern; deploy flow
creates it like any other helper) via `input_text.set_value` immediately before `stop:`.
Both bands now implement exit-with-value; the drop-with-warning option is retired. Same
entity also serves `setPistonState` (HA_LIMITATIONS §10.2 upgrade, same date) and the
automatic piston state (§2.5 point 5 — first top-level if's truth value) if/when that
mirrors to HA.

### E6. `every` `only_on_wom` — runtime check pattern

`only_on_wom` (weeks of month) has no direct cron equivalent. The PyScript compiler must
emit a cron that fires on the correct days of the month (via `dom`), then add an early-
exit `if` check inside the function body to guard against wrong weeks. The exact Python
expression for "Nth week of month" must be confirmed at the v2 compiler spec against real
HA behavior.

---

## EE. WebCoRE statement/operator → HA behavioral pairing (VERIFIED reference, folded in 2026-07-12)

Folded in from `reference/WEBCORE_HA_BEHAVIOR_MAP.md` (verified against live HA docs,
2026.6.3) before that file was deleted as reference-folder cleanup — this is the durable
content, kept here so it isn't lost. Complements G below: this is *behavioral pairing*
(what HA construct matches WebCoRE's behavior), G is *illustrative output shape*. Full
per-operator tables lived in the source file; the load-bearing gotchas that aren't obvious
from HA's docs alone are:

- **`numeric_state` trigger only fires on crossing**, not on any change that lands past the
  threshold — if a value is already above 30 and goes 31→32, it does NOT re-fire. WebCoRE's
  "changes to above" fires on any change landing above threshold regardless of prior value.
  Needs a `state` trigger + template filter for exact parity if that distinction matters.
- **`for:` (duration) on triggers/conditions does NOT survive an HA restart or automation
  reload** — resets and re-times from scratch. WebCoRE pistons reset on restart too, so this
  is equivalent behavior, not a gap.
- **`choose` never falls through** — WebCoRE's switch fall-through mode has no HA
  equivalent; `choose` always exits after the first matching branch (PyScript-routed per §E
  if fallthrough is actually used).
- **No native XOR** — HA conditions are AND/OR/NOT only; XOR requires a template
  (`{{ (cond1|int) + (cond2|int) == 1 }}`), same for the "exactly one" comparison operator
  family.
- **No nested/per-condition triggers** — WebCoRE's `on` statement (nested trigger inside an
  action sequence) and per-condition event subscription have no HA equivalent; HA triggers
  are automation-level only. Closest approximation for a one-shot wait is `wait_for_trigger`,
  which is NOT a persistent subscription loop.
- **"Followed by" (sequential condition chaining within a time window)** has no HA
  equivalent — would need `wait_for_trigger` chains with timeout tracking.
- **No explicit `break`** in any HA loop (`repeat: count/for_each/while/until`) — HA loops
  exit via a condition evaluating false/true; the workaround is a boolean flag variable
  checked by the loop's own condition.
- **`repeat.index` is 1-based** with no start/end/step concept (WebCoRE's `for` loop has
  all three) — variable step needs a `variables` action inside the loop.
- Confirmed cut, no HA equivalent at all: AskAlexa/EchoSistant virtual devices, LIFX cloud
  virtual device (HA's LIFX integration uses local entity commands directly instead),
  Contacts/SMS (HA has no equivalent — real `notify` service call instead, see §C),
  SmartThings-specific Routines (HA uses scripts/scenes).

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
   `reference/webcore_source_reference.groovy:1495-1528` `api_intf_variable_set`;
   RE-CONFIRMED 2026-07-12 against a real v2 capture, not just the Hubitat source).**
   The real Hubitat/SmartThings backend stores every global (device-type included) in ONE
   central map, `atomicState.vars`, keyed by `@Name`, holding `{t, v}` — `v` for a device
   global is just the device-id array. Pistons reference the global **only by name** in
   operands; the device list is never embedded in piston JSON, for any global type. The
   piston JSON genuinely never changes when a global's device list changes — the v1
   role_tokens JSON-walk is confirmed dead, not just assumed dead.
   **Live v2 evidence (real saved piston "Test 1", 2026-07-12):** the condition's device
   reference is `lo.d: ["Light"]` and the action's is `d: ["@Announce"]` — bare **names**,
   not hashed ids, in both the local-variable and global cases. The actual hashed device
   ids (`:40b2c5e6...:`, `:1aa3b5eb...:`, `:0599c506...:`) appear ONLY inside the variable/
   global definitions themselves (`piston.v[].v.d`, `globals.json`'s `@Announce.v`) — never
   inline in a statement or condition. This is PistonCore's own real dashboard+shim save
   pipeline confirming the pattern, not an inference from reading someone else's source.
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
(`shim/storage.py:find_global_references`) regex-scans every string value in the piston
tree for `@Name`/`@@SuperGlobal` tokens, rather than checking only `{"t": "x", "x": ...}`
operand nodes (the original approach). **Bug found and fixed 2026-07-12** against a real
capture: a device-type global used as a with-block's target is a bare `@Announce` string
sitting directly in the statement's `d` list, no operand wrapper at all — the
operand-only scanner missed this real, common case entirely and silently left `used_by`
empty. The regex-over-every-string approach also catches globals embedded inside
expression source strings (`e`/`str` fields, where `@Name` can be part of a larger
sentence) and inside local variables' own `v.d` arrays, uniformly, with no need to
special-case where in the structure a reference appears.

### H5. Status at time of writing

Tracking (H4) is **built** — part of the milestone 3 save flow. The `group.set`-based
patch mechanism (H1.2, H2) is **designed and verified** (HA capability confirmed via web
search, 2026-07-10) but not yet built — there's no compiler yet to decide the
group-vs-inline compile strategy, and nothing deployed yet worth patching. The `used_by`
data is accurate and ready for when the compiler is built. The v1 globals UI is retired;
v2 globals are edited in the stock dashboard's variable editor (served by
SHIM_API_SPEC.md §4.10).

---

## I. Vocab `ha` translation layer — multi-mapping resolution (recorded 2026-07-12, not built)

`webcore_vocab.json` carries a per-attribute/per-command `"ha"` array (merged in from the
Fable5/Grok candidate vocab, 2026-07-12) plus a top-level `_ha_translation` metadata block.
Each array entry is one candidate HA mapping (`domain`, optional `device_class`, `read` or
`map`/`scale`, a `tag` of verified/assumed, optional `note`). Multiple entries on one
attribute/command are deliberate — HA has no hard capability definitions the way
SmartThings/Hubitat did, so one webCoRE name legitimately maps to more than one real HA
mechanism (e.g. `level`/`setLevel` cover `light.brightness_pct`, `fan.percentage`,
`cover.position`, AND `media_player.volume_set` — confirmed via live device comparison,
not a research error). `"ha": "n/a"` means confirmed no HA equivalent.

Both `"ha"` and `_ha_translation` are shim/compiler-internal — `fixtures.get_db()` strips
both before the vocab reaches the sealed dashboard client (shim/fixtures.py).

Compiler-side decisions from this analysis (SESSION_BRIEF_VOCAB_PICKER.md Part 3,
Jeremy 2026-07-12) — recorded now, not built, since there is no compiler yet:

- **Multi-mapping resolution is PER-DEVICE, decided by live HA data at compile time.**
  Each resolved member entity is matched against the command/attribute's `ha` array by
  domain/device_class/features; when several mappings match the SAME entity, array order
  is the tiebreaker — first match wins. Array order is therefore MEANINGFUL and must never
  be re-sorted (by hand or by tooling) when this file is edited.
- **Command fan-out with grouping:** one webCoRE command over a mixed-device group compiles
  to multiple HA service calls, one per winning mapping, each targeting the combined entity
  list of the devices that resolved to it (all devices that matched mapping X in one call,
  all that matched mapping Y in another).
- **Mixed-outcome rule:** if any device in the group resolves to `n/a` or no match, that is
  an A6 error naming the device + command, surfaced per the two-surface rule (no separate
  debug page) — never a silent drop of just that
  device from the group.

Not yet done (SESSION_BRIEF_VOCAB_PICKER.md Part 2): a permanent comparison-harness debug
endpoint that dumps the full per-device grouping/capability funnel (raw HA entities → Stage
1 survivors + exclusion reasons → picker-map hits → Stage 4 bridge capabilities → final
served a/c/cn) to diff against real webCoRE device-by-device. Intended as permanent support
tooling ("why isn't X in the picker"), not scratch — still to be built.

---

## F. Retirement

When the v2 compiler spec is written (after PISTON_JSON_REFERENCE.md locks the webCoRE
JSON as the input format): extract Sections A–E (and C-TYPES) verbatim-faithful from
SPEAK_ACTION_SPEC.md, NOTIFY_ACTION_SPEC.md, and this file into the v2 compiler spec,
resolve the Section D open items and the H1/E2 TO-VERIFY/re-key items against the webCoRE
JSON, then delete this holding doc. Until then, this file is the single place those
compiler decisions are collected.

**Section G (compile-output sketches)** is OUTPUT-ONLY reference (see G header) — at the v2 compiler spec, validate each sketch's output against real HA and pair it with the webCoRE JSON statement; do not carry any sketch forward unverified. It is the lowest-confidence content in this file.

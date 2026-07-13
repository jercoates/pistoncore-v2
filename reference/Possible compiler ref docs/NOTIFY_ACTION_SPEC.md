# PistonCore — Notify / Push Notification Action Contract

**Version:** 0.2 (DRAFT — standalone)
**Status:** Pre-coding contract. NOT yet integrated into WIZARD_SPEC.md / COMPILER_SPEC.md.
**Last Updated:** June 2026 (Session 73 — verified/assumed ledger added)
**Authority:** WebCoRE notification-task model (piston.module.html + WebCoRE source
archived in Session 14 chat) + verified live-HA `notify.*` service registry.

---

## LEDGER — Verified vs. Assumed (read this to audit the spec)

Default convention: **the spec records Jeremy's DECISIONS.** Anything Claude *assumed*
to fill a gap is listed in the ASSUMED column below and is **never load-bearing** — it
is a proposal awaiting Jeremy's call, freely overridable in coding without archaeology.
If it is not in the ASSUMED list, it is either a verified fact or a Jeremy decision.

### VERIFIED (live HA / WebCoRE source — facts, not choices)
- Jeremy's phone is `notify.mobile_app_jeremy_s_s25`, a **service** (not an entity),
  under the Notifications category. Confirmed live, Developer Tools → Actions, Session 73.
- `notify.mobile_app_*` services do NOT appear in `get_states`; they live in the service
  registry (`/api/services` / `get_services`). (HA architecture, confirmed by the above.)
- Sibling `notify` domain services confirmed live: `notify.notify`,
  `notify.persistent_notification`, `notify.send_message`. (Session 73 screenshot.)
- HA notify is mid-transition: legacy per-target services today; `notify.send_message`
  with entity targets emerging (2026.5+) but not yet covering rich companion-app payloads.
  (HA docs / discussions, Session 73.)
- The mobile_app suffix is the phone's device name slugified
  (`Jeremy's S25` → `jeremy_s_s25`). (Companion App docs + live confirmation.)

### DECIDED (Jeremy's calls)
- Notify targets get their OWN picker section (modeled like the variables section), NOT
  the device picker. (Section 1 — the central decision.)
- The node stores a stable target reference resolved by Jinja2 template, never a
  hard-coded HA service string, so HA's notify churn is absorbed in the template.
- v1 targets the legacy `mobile_app_*` path (what Jeremy runs); entity-target path is
  specified as a seam but not primary.
- Phone-as-unit cross-referencing (notify target ↔ its sensors) is v2, out of scope.
- Full companion-app `data` payload coverage is staged incrementally.

### ASSUMED by Claude (NOT load-bearing — override freely in coding)
- All field/key names in Section 4.4 (`target_ref`, `kind`, `id`, `label`, `command:
  notify`, `params`, `data`) — PROPOSED only, must be reconciled against PISTON_FORMAT.md.
  Section 8 tracks this.
- The two `kind` values (`mobile_app`, `notify_entity`) as the discriminator scheme —
  proposed shape, not a verified requirement.
- The rendered display string `Send notification "<message>" to {<target>}` — proposed;
  the real WebCoRE notification-task template (Session 14) is authoritative once pulled.
- Which `notify.*` services to surface vs hide/subgroup in the picker — proposed
  presentation, not decided (Section 4.2 / Section 8 item 3).
- The specific `data` field set (actions/image/tag/priority) — proposed examples; the
  real mapping comes from the Companion App docs at coding time.

---

## 0. Why this document exists

Push notifications are core to Jeremy's real automations and have had zero wizard work.
Notify is fundamentally a **different shape** from every other action PistonCore has built
so far, and getting that difference wrong would corrupt the device-picker work, not just
the notify feature. The whole point of pinning this in writing BEFORE code is to stop a
future coding session from doing the tempting-but-wrong thing: forcing notify targets
through the existing device-picker machinery. That path blows up the picker. This spec
exists to make the structural difference impossible to miss.

The drift-class bugs this project has fought (`service_call` vs `with_block`,
`entity_id` vs `entity_ids`, indexed-key params) all came from the frontend and compiler
each assuming a JSON shape with no written contract between them. Notify is a new target
shape AND a new picker source, so both get pinned here first.

This file will be folded into WIZARD_SPEC.md (editor/wizard + picker side) and
COMPILER_SPEC.md (compiler side) as those areas are coded. A TASKS.md entry tracks final
spec integration.

---

## 1. THE CENTRAL INSIGHT — read this before touching any picker code

**A notify target is NOT a device. It is a flat named destination from a different HA
registry, and it must live in its own picker section.**

This is the single most important thing in this document. The instinct to reuse the
device picker for notify is wrong, and acting on it will break the device picker. Here
is exactly why, so the coding session does not have to rediscover it:

### 1.1 What the device picker is

The existing device picker (wizard-core.js `_groupDevices`, etc.):
- reads **entities** from the single `get_states` call,
- groups them by HA `device_id` (one row per physical device),
- stores ALL entity IDs for a device group in `sel.tokens`,
- runs **union-then-intersect capability lookup** across the device's sub-entities,
- uses `_getPrimaryIdsForTokens` / domain-priority to pick a primary entity.

Every one of those mechanics depends on the target being a real entity with a
`device_id`, a domain, sub-entities, and `supported_features`.

### 1.2 What a notify target is

A notify target — verified live on Jeremy's HA, Session 73 — is
`notify.mobile_app_jeremy_s_s25`. It is:
- a **SERVICE**, not an entity. It does NOT appear in `get_states`. It appears only in
  the **service registry** (`/api/services` REST, or `get_services` websocket).
- It has **NO `device_id`.**
- It has **NO sub-entities.**
- It has **NO `supported_features` / capability bits.**
- It is a single flat name. Its only verb is "send a notification."

Verified live-HA `notify` domain services (Developer Tools → Actions, filter "notify"):
- `notify.mobile_app_jeremy_s_s25` — "Send a notification via mobile_app_jeremy_s_s25"
  (the phone — the target we care about).
- `notify.notify` — broadcast to all configured notifiers.
- `notify.persistent_notification` — the HA notifications panel.
- `notify.send_message` — the newer entity-target action (see Section 6, future).

### 1.3 The consequence — why a separate section is EASIER, not a compromise

Forcing a notify target into the device picker would require **fabricating** a
`device_id`, a domain, and a capability set it does not have, then teaching the
grouping/intersection logic to special-case the fakes. That is MORE code and is fragile.

Giving notify targets their own picker section is **LESS code and structurally correct**:
a flat enumeration → a flat list of rows → store the chosen target id. No grouping, no
intersection, no `sel.tokens` union, no primary-entity resolution. None of it applies.

**Decision (locked): notify targets get their own picker section, modeled like the
variables section — a distinct, flat, self-contained list — NOT a device group.**

### 1.4 The "but it might do more than notify" concern — resolved

Worry: a phone can do more than notify (battery, charging, connectivity sensors), so
does a flat notify-only target throw that away?

Answer: **No, because those are different things surfaced through different registries.**
- The notify **service** (`notify.mobile_app_jeremy_s_s25`) does exactly one thing: send
  notifications. Nothing is lost by treating it as flat — there is nothing else there.
- The phone's **sensors** (`sensor.jeremy_s_s25_battery_level`,
  `binary_sensor.jeremy_s_s25_is_charging`, etc.) are real **entities** WITH a `device_id`,
  and they already belong in the normal device picker. They are unaffected by this spec.
- The richness of a notification (actionable buttons, image, TTS-to-phone, priority,
  tag/group) is NOT in the target — it is in the `data` payload of the action, which
  attaches to the wizard **action fields** AFTER the target is picked (Section 4.3).

So the same physical phone legitimately appears in two picker places: as a **notify
target** in the notify section, and as **sensor entities** in the device section. This is
correct and intentional — it mirrors WebCoRE's own split between a device-for-status and a
notification-destination. It is NOT duplication to be designed away.

> Cross-referencing the notify target to its sibling sensors (e.g. "notify this phone AND
> show me its battery in one unit") is explicitly **out of scope for v1** — see Section 6.

---

## 2. First principle — what defines "done"

**PistonCore is a recreation of WebCoRE for Home Assistant, as faithfully as HA allows.**

- **Editor/visual fidelity is the definition of done.** The notify task renders as
  WebCoRE renders a notification task. Verified by eye against the WebCoRE source.
- **The compiler is invisible plumbing.** Given the fixed JSON, it emits HA that delivers
  the notification the visual promises.
- **Under-the-hood choices (which HA service, legacy vs entity target) must never leak
  upward into the editor display.**

---

## 3. The HA reality the compiler must absorb (and why templates matter)

Notify is **mid-transition in HA**, and this is the load-bearing reason the compiler must
go through Jinja2 templates rather than hard-coding service names:

- **Legacy path (today, what Jeremy uses):** per-target services like
  `notify.mobile_app_jeremy_s_s25`. Call the service directly with `message` / `title` /
  `data`.
- **Emerging path:** `notify.send_message` with the target as an **entity** in the
  `target` block (HA 2026.5+ mobile-app notify entities). Basic message/title only today;
  the richer companion-app `data` payloads still require the legacy `mobile_app_*` action.
- **Direction of travel:** HA has marked the legacy notify platform as legacy and is
  moving toward notify entities, but the migration is incomplete and the feature-rich
  payloads are not yet covered by the entity path.

**Consequence (locked):** the stored JSON must NOT contain a hard-coded HA service call.
It stores a **stable target reference** (Section 4). The compiler resolves that reference
to whatever HA currently wants **via a Jinja2 template** — the project's standing
"all HA YAML through Jinja2, no exceptions" rule. When HA flips the legacy path off, or
when a target should move to the entity path, **only the template changes — stored
pistons do not.** This is the entire insurance policy against HA's churn.

---

## 4. Editor / visual + JSON contract

### 4.1 Rendered display

The notify task renders as WebCoRE renders a notification task (pull the exact WebCoRE
template from the Session 14 chat before coding the form). Conceptually:

```
Send notification "<message>" to {<target>};
```

`{<target>}` is the chosen notify destination (display label = de-slugified target name,
e.g. `notify.mobile_app_jeremy_s_s25` → "Jeremy's S25").

### 4.2 Picker source (AUTHORITATIVE — this is the part that's different)

The notify-target picker section is populated from the **service registry**, NOT from
`get_states`:

```
fetch the HA service registry (/api/services REST, or get_services websocket)
  → take the `notify` domain
  → enumerate its services
  → present each as a flat selectable row in the dedicated NOTIFY picker section
       label  = de-slugified service suffix (mobile_app_jeremy_s_s25 → "Jeremy's S25")
       stored = the stable target reference (Section 4.4)
```

No `device_id` grouping. No capability intersection. No `sel.tokens` union. No
primary-entity resolution. It is a flat list. (See Section 1 for why.)

Filtering/scoping of which `notify.*` services to show (e.g. surface `mobile_app_*` and
named groups, optionally hide `notify.notify` / `persistent_notification`, or show them
in a clearly-labeled "other targets" subgroup) is a presentation refinement to settle
during coding — but the SOURCE is the service registry, locked.

### 4.3 Wizard action fields (where the richness lives)

After a target is picked, the task editor exposes the notification payload. At minimum:

- **message** — free text + `$variable` insertion (literals and variables mixed),
  matching the Speak message contract; goes through the canonical variable→Jinja
  substitution function, never a second path.
- **title** — optional, same interpolation rules.
- **data** (companion-app payload, target-type-dependent) — actionable buttons/actions,
  image/attachment, tag/group, priority/channel, TTS-to-phone, etc. These are the
  "more than basic notify" features. They attach to the TARGET's capabilities, which the
  coding session maps from the Companion App notification docs. v1 may ship message+title
  and stage `data` features incrementally; the spec's job is to make clear they live HERE,
  on the action, not on the picker target.

> The exact `data` field set per target type (mobile_app vs persistent vs group) is a
> coding-time mapping against the live Companion App docs. The CONTRACT fixed here is only
> *where* they live (action payload) and *that* message/title use the canonical
> interpolation path.

### 4.4 JSON contract (the shape that backs the visual)

> NOTE — field names below are PROPOSED and must be reconciled against the actual
> action/task schema in PISTON_FORMAT.md during coding (the `entity_id` vs `entity_ids`,
> `service_call` vs `with_block` problem area). The INTENT is fixed; exact key names get
> locked against the existing schema, NOT invented here.

The node stores a **stable target reference**, never a resolved HA service string:

Illustrative (subject to schema reconciliation):

```json
{
  "type": "task",
  "command": "notify",
  "target_ref": {
    "kind": "mobile_app",
    "id": "mobile_app_jeremy_s_s25",
    "label": "Jeremy's S25"
  },
  "params": {
    "message": "{Message}",
    "title": "{Title}",
    "data": {  }
  }
}
```

Fixed by this contract:

- The node stores a **stable target reference** (`kind` + `id` + display `label`), NOT a
  hard-coded `notify.mobile_app_...` service call. The compiler resolves it (Section 5).
- `kind` distinguishes legacy-service targets from entity targets so the compiler/template
  knows which HA path to emit. This is the seam that lets HA's transition be absorbed in
  the template without rewriting pistons.
- `message` / `title` are token-interpolated strings (literal + variable tokens), using
  the canonical substitution function — same as Speak.
- `data` holds companion-app payload options; absent/empty for a basic notification.
- NO HA service name is stored. NO `device_id`. NO capability bits.

---

## 5. Compiler contract (read-only, template-resolved)

### 5.1 Absolute rule

**The compiler reads the JSON. It NEVER writes, reshapes, or mutates it.** The stored
target reference is the source of truth. The compiler is input-only.

### 5.2 Target resolution via Jinja2 template (the churn insurance)

The compiler resolves the stored `target_ref` into the correct HA call **through a
Jinja2 template selected by `target_ref.kind`** — never a hard-coded service string:

- `kind: mobile_app` (legacy, today) → emit `notify.<id>` service call:
  ```yaml
  action: notify.mobile_app_jeremy_s_s25
  data:
    message: "{{ ...compiled message... }}"
    title: "{{ ...compiled title... }}"
    data: {  }
  ```
- `kind: notify_entity` (emerging path) → emit `notify.send_message` with the target as an
  entity:
  ```yaml
  action: notify.send_message
  target:
    entity_id: notify.<id>
  data:
    message: "{{ ...compiled message... }}"
  ```

When HA changes how notify works, the change lands in these templates ONLY. Stored
pistons, the picker, and the JSON shape are untouched. This is the explicit design goal:
**isolate all HA notify churn inside the compiler's templates.**

All message/title/data values go through Jinja2 (standing project rule). The
variable-token → Jinja substitution MUST reuse the single canonical substitution function
used elsewhere in the compiler — do NOT introduce a second variable-substitution path for
notify. (Same rule as Speak.)

PyScript target: same service call via the PyScript service-call mechanism. (Detail
confirmed during compiler work.)

### 5.3 Error handling — debug page, never mutation

If the compiler finds the target reference unresolvable (service no longer registered,
entity missing, kind not recognized):
- it does **not** edit the JSON,
- it does **not** silently drop the task,
- it writes a clear, specific error to the **debug page** naming the offending target and
  why it failed.

The piston source stays untouched regardless of compile outcome.

---

## 6. Data availability + new plumbing (Session 73)

The single biggest backend item: **notify targets are NOT in the `get_states` call that
`ha_client.py` already makes.** They live in the service registry. So notify requires a
**second HA fetch** alongside `get_states` — directly parallel to how Speak needed
`supported_features` carried through and `tts.*` enumerated, except notify's source is a
different endpoint entirely.

- **New fetch:** call `/api/services` (REST) or `get_services` (websocket), take the
  `notify` domain, enumerate its services. This is new plumbing in `ha_client.py` (which
  today only does `get_states`).
- **Surface to frontend:** the enumerated `notify.*` services flow to the dedicated notify
  picker section (parallel to how grouped devices flow to the device picker), as a flat
  list — not through `_groupDevices`.

---

## 7. v2 / explicitly OUT OF SCOPE for v1

Deferred to keep v1 shippable (per Jeremy's call, Session 73 — the cross-reference
complexity is real and not worth blocking v1):

1. **Phone-as-unit cross-referencing.** Linking a notify target to its sibling sensors
   (battery, charging, connectivity) so the same physical phone is presented as one unit
   across the notify section and device section. This requires correlating a `notify.*`
   service suffix back to a `device_id` and its entities — real complexity, real value,
   but v2.
2. **Full companion-app `data` payload coverage.** v1 may ship message + title + a core
   subset of `data`. The complete actionable-notification / image / chronometer / channel
   matrix per the Companion App docs is staged incrementally.
3. **notify entity path as primary.** v1 targets the legacy `mobile_app_*` services
   (what Jeremy actually runs). The `kind: notify_entity` template branch is specified
   (Section 5.2) so the seam exists, but making entity targets the default waits until
   HA's entity path covers the rich payloads.

---

## 8. Open items to reconcile during coding (schema checks, NOT decisions)

1. Exact field/key names in Section 4.4 vs the real action/task schema in
   PISTON_FORMAT.md (`entity_id` vs `entity_ids`, `service_call` vs `with_block`).
2. The exact WebCoRE notification-task template from Session 14 for the form layout.
3. Which `notify.*` services to surface vs hide/subgroup in the picker (presentation only;
   source is locked as the service registry).
4. The per-target-type `data` field mapping against the live Companion App docs.

---

## 9. Summary — the contract in one line each

- **THE INSIGHT:** a notify target is a flat named SERVICE from the service registry, NOT
  a device — it gets its OWN picker section, modeled like the variables section. Forcing
  it into the device picker is more code and breaks the picker. (Section 1.)
- **Picker source:** the HA **service registry** (`/api/services` / `get_services`),
  `notify` domain — a flat list. NOT `get_states`, NOT `_groupDevices`.
- **JSON:** the node stores a **stable target reference** (`kind` + `id` + `label`),
  never a hard-coded HA service string; message/title token-interpolated; `data` holds the
  rich payload.
- **Compiler:** read-only; resolves the target ref to HA via a **Jinja2 template selected
  by `kind`**, so all HA notify churn is absorbed in the template and stored pistons never
  break; reuses the canonical variable substitution; errors go to the debug page.
- **New plumbing:** a SECOND HA fetch (service registry) beyond `get_states`.
- **v2:** phone-as-unit cross-referencing of notify target to its sensors, and full
  companion-app `data` coverage.

---

## CONVENTION NOTE — for the session prompt and TASKS.md

**New standing convention (add to session prompt + TASKS.md):**

> When Claude writes or edits a spec, it MUST mark anything that is Claude's own
> assumption (a gap Claude filled, a proposed name/shape/rule Jeremy did not explicitly
> decide) as ASSUMED. Decisions do not need marking — the default is that a spec records
> Jeremy's decisions. Marking the assumptions is what keeps the rare assumption visible
> instead of letting it masquerade as a settled decision. Assumptions are never
> load-bearing and are freely overridable in coding. Maintain a "Verified vs. Assumed"
> ledger near the top of each standalone spec.

This exists because the project's drift-class bugs came partly from Claude's gap-filling
assumptions hardening into apparent "decisions" across sessions that neither party could
later distinguish. The existing prompt already states Jeremy will break any "rule" that
blocks coding a working product — this convention is the complement: it keeps spec rules
honestly labeled so Jeremy knows which ones are real decisions worth keeping and which
are Claude's proposals safe to break.

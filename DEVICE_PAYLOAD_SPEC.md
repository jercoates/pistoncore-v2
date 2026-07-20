# DEVICE_PAYLOAD_SPEC.md — HA → webCoRE Device Object Pipeline (Grouped Model)

**Status:** Draft 2 — rewritten around the GROUPED device model (DECISION, Jeremy,
2026-07-07): one picker device per physical device (Hubitat feel), not one per HA entity.
Output format verified against webcore.groovy v0.3.114 (`listAvailableDevices`); input
formats verified against the translation files in `frontend/`.
**Authority:** Subordinate to SHIM_API_SPEC.md (§5.1 defines the output contract).
**Hard requirements (Jeremy):** (1) ALL attributes and commands of every member entity
that the vocab can express MUST survive into the device object — grouping must never
silently drop information. (2) The user sees ONLY friendly names — no registry IDs, no
entity_ids, no hashes ever appear in the editor or PistonCore pages.
**Tagging:** `VERIFIED-GROOVY` / `VERIFIED-FILES` / `VERIFIED-JS` / `ASSUMED` / `DECISION`.

---

## 1. Job

Produce the `devices` map served by `intf/dashboard/devices` (SHIM_API_SPEC §4.2), where
each entry is ONE physical device (a group of HA entities), shaped exactly like a webCoRE
hub device:

```
"<hashedId>": {
  "n":  "Kitchen Multisensor",                               // friendly name — the ONLY thing users see
  "cn": ["Motion Sensor", "Temperature Measurement", ...],
  "a":  [ {"n":"motion","t":"enum","o":["active","inactive"],"v":"inactive"},
          {"n":"temperature","t":"decimal","v":71.2}, ... ],  // union across member entities
  "c":  [ {"n":"on"...}, ... ]                                // union across member entities
}
```
(VERIFIED-GROOVY shape. This is byte-identical in structure to a real Hubitat multi-
capability device, which is why the sealed dashboard needs zero changes for grouping —
menus are computed client-side from `a`/`c` per device, VERIFIED-JS piston.module.js:765,
2759–2817.)

## 2. Inputs

| Input | Role |
|---|---|
| HA **device registry** | the grouping: physical devices, their stable device IDs, their names (`name_by_user` else `name`) |
| HA **entity registry** | entity → device_id membership; `entity_category` (for filtering diagnostics); disabled flags |
| HA state API | live values, domain, device_class, supported_features, supported_color_modes |
| `picker_capability_map.json` | HA signals → attribute keys (VERIFIED-FILES) |
| `webcore_vocab.json` | attribute keys → capabilities/attributes/commands definitions, plus per-attribute/command `"ha"` arrays (where the value lives / where commands route — structured, machine-executable read/write rules, retired `pistoncore_attribute_translation.json`'s free-text `ha_source`) (VERIFIED-FILES, merged 2026-07-12) |

## 3. Pipeline

### Stage 0 — Scope
**DECISION (Jeremy, 2026-07-07): all supported devices exposed by default.** No selection
step; inclusion is never opt-in. A later exclusion mechanism may be added if needed.
Changes to the exposed set bump `deviceVersion`.

### Stage 1 — Grouping (NEW)
Fetch device registry + entity registry. Group entities by their registry `device_id`.
- Entities with NO registry device (helpers, template entities, some integrations) become
  **singleton groups** of one entity.
- **Member filter:** exclude entities that are disabled, or whose `entity_category` is
  `diagnostic` or `config` (link-quality, restart buttons, firmware sensors — noise that
  would pollute menus). ASSUMED reasonable default — revisit if a wanted attribute lives
  on a diagnostic entity; the filter must never violate hard requirement (1) for
  attributes the vocab actually expresses, so log every filtered entity for visibility.

### Stage 2 — Per-member signal extraction
Unchanged from Draft 1, but per member entity: domain, device_class, supported_features,
supported_color_modes, declaration attributes. Offline/unavailable members stay in the
group (entity registry knows them; never auto-drop).

### Stage 3 — Picker map lookup, per member → union
Run each member entity through `picker_capability_map.json` → its attribute keys. The
group's attribute key set = the UNION across members. Record, for every attribute key,
**which member entity contributed it** — this binding is the resolution data (Stage 8).

**Duplicate-attribute rule (DECISION, Jeremy, 2026-07-09): never split a device.** A
webCoRE device is device + capabilities, full stop — one HA device_id is always exactly
one picker device, no matter how many members collide on the same attribute or command
key. Splitting a group into multiple picker devices (an earlier draft of this section)
was tried and explicitly rejected: it doesn't generalize ("has to work for all devices
found this way, not just mine") and produces a confusing, chopped-up picker for devices
like a ReSpeaker satellite (one HA device_id, 5+ independent switch entities).
Deterministic resolution instead: lowest entity_id sort wins each attribute/command key;
later contributors' *other*, non-colliding attributes/commands still merge in normally.
Known, accepted limitation: two entities offering the exact same generic command name
(e.g. two "switch" entities each with on/off) can't both be independently invoked from
one device today — webCoRE's `c[].n` must be a real `vocab.commands` key for the editor
to render it, and there's no sub-device mechanism for `switch` the way there is for
`button`/`lock` (Stage 3.1). A future fix would need either a vocab addition or webCoRE's
custom-command mechanism (PISTON_JSON_REFERENCE.md §5 `"cm"`) — not attempted yet.

### Stage 3.1 — Sub-device attributes (button, lock) are the one built-in exception
`vocab.attributes[key].s` names a companion count attribute (e.g. `button`'s
`"numberOfButtons,numButtons"`), and `.i` names a companion "which one fired" attribute
(e.g. `"buttonNumber"`). This is webCoRE's real, existing mechanism for one device with N
indexed sub-things (piston.module.js:3703-3739 reads the count to offer N indexed
sub-devices via an operand's `i` array — PISTON_JSON_REFERENCE.md §4 `"p"` operand's `i`
field). Verified against source, 2026-07-09. For these attribute keys only: never drop a
duplicate contributor — keep every contributing entity, **numerically** ordered (not
lexicographic — `button_10` must sort after `button_2`, not before), and emit the
companion count attribute (`{"n": "numberOfButtons", "t": "integer", "v": <count>}`) so
the editor offers the right number of indexes instead of its 32-slot fallback.

### Stage 3.2 — Custom-attribute fallback (no picker_capability_map rule needed)
**DECISION, Jeremy, 2026-07-09.** An entity that matches *zero* `picker_capability_map.json`
rules (no domain/device_class/unit match — e.g. a generic Hubitat-driver passthrough sensor
with no HA `device_class`) is **not** dropped. It falls through as a device-local custom
attribute: `{"n": <key>, "t": "string"|"decimal"}`, no vocab entry required. This works in
the real editor because `piston.module.js:3688-3701` already falls back to searching a
device's own `a[]` array by name when a key isn't found in the central `db.attributes`
vocab (VERIFIED against source) — this is exactly how custom Hubitat-driver attributes
(e.g. a UniFi Protect camera's `smartDetectType`, typed/compared as free text in the real
editor, never a vocab enum) worked in Jeremy's actual production webCoRE.
**Key derivation:** for Hubitat-platform entities, HA's entity registry `unique_id` embeds
the original Hubitat attribute name literally — format `<hub>::<device>::sensor::<attrName>`
(confirmed: `sensor.doorbell_pro_motion_smart_detect_type`'s unique_id is
`3c8e8863::927::sensor::smartDetectType`, byte-for-byte the old Hubitat attribute name).
Parse that 4th segment when the platform is `hubitat` and the pattern matches; otherwise
fall back to the entity's own object_id. **Why this matters:** it means coverage grows
automatically — enabling a currently-disabled HA entity (most custom Hubitat passthrough
sensors are disabled by default) makes it appear on next `devices` fetch with zero shim
code changes, rather than needing a hand-written rule per attribute.

### Stage 3.3 — Command-only capability lane (added 2026-07-10)
The attribute bridge (Stage 4) can NEVER reach **command-only capabilities** — ones with
commands but no primary attribute (Speech Synthesis, Notification/deviceNotification,
Tone, and similar). Without this lane, speak- and notify-capable devices silently lose
those features: no attribute → picker map emits nothing → bridge never finds the
capability → the device can't be picked for it in the editor. So the pipeline carries a
second, direct mapping: HA signals → **capability keys**, no attribute involved. Seed
rules:
- `media_player` with the PLAY_MEDIA `supported_features` bit → the speech-capable
  capability set (speechSynthesis and whichever companions the vocab defines) — this IS
  the B6 author-time speak gate from COMPILER_DECISIONS_HOLDING.md, implemented here.
- Device-level notification (Hubitat `Notification` capability / `deviceNotification`) →
  rule TBD alongside the notify-target work (COMPILER_DECISIONS_HOLDING.md C2/C2b).
  NOTE: push notifications are NOT this — they're virtual commands (db `commands.virtual`)
  and need no device capability; this lane is only for notify-capable *devices*.
- Extend the same way for other command-only capabilities as devices demand (siren/alarm,
  tone, etc.).
Where these rules live: either a `capabilities` branch added to
`picker_capability_map.json` entries (preferred — keeps one map) or a small companion
map; DECISION at implementation, but the rules must be data, not code, per house style.
Capabilities from this lane merge into the group's capability set before Stage 4 runs,
and their member-entity binding is recorded exactly like attribute contributions
(Stage 8 `cmd_bindings`).

### Stage 4 — Attribute → capability bridge
Invert `vocab.capabilities[*].a` once at startup; group's attribute keys →
capability keys, merged with Stage 3.3's direct capabilities → `cn` display names
(VERIFIED-FILES). Overlapping capabilities are fine —
webCoRE devices routinely advertise overlaps and the dashboard tolerates it (VERIFIED-JS).

### Stage 5 — Attribute array `a`
For each attribute key in the union: copy `{n, t, o}` verbatim from `vocab.attributes`
(VERIFIED-FILES — shapes already match the wire format field-for-field), attach `v` = live
value read from the CONTRIBUTING member entity per the translation table's `ha_source`
value mapping (binary_sensor on/off → active/inactive, open/closed, etc. — the translation
table is the authority). Unavailable member → omit `v` (VERIFIED-GROOVY: dashboard
tolerates missing `v`). Temperature-scale: `u: "°?"` entries resolve F/C from HA config
and must agree with the location payload's `temperatureScale`.

### Stage 6 — Command array `c`
Union of `vocab.capabilities[k].c` across the group's capability keys; emit
`{"n": "<commandKey>", "p": [...]}` with params from `vocab.commands[key].p` (VERIFIED-
FILES). Each command is recorded against the member entity whose capability contributed
it (Stage 8) — commands route to members, e.g. `setLevel` → the light member, `setLevel`
never targets the motion member. Only advertise commands some member can actually execute
(falls out of the per-member capability sets — a color-temp-only light member never
contributes `setColor`).

### Stage 7 — Identity & display
- **Device ID = `":" + md5("core." + <registry device_id>) + ":"`** (stock hashId format,
  VERIFIED-GROOVY webcore.groovy:2343–2347, applied to the registry ID). Singleton groups
  with no registry device hash their entity_id instead.
- Registry device IDs are HA-stable: **renaming a device changes nothing** (the Hubitat
  property preserved). Removing/re-adding an integration issues a new registry ID = a new
  device, same as re-pairing on Hubitat — honest breakage, visible in the editor.
- **Display name = registry `name_by_user`, else `name`** (else the singleton entity's
  friendly_name). Names are DISPLAY-ONLY: they appear in `n` and nowhere else; IDs appear
  in JSON and nowhere the user looks. HA renames propagate on the next `devices` fetch
  (bump `deviceVersion` on name change) and update every rendered piston automatically —
  names are never stored in piston JSON (VERIFIED-JS: editor renders names by ID lookup,
  piston.module.js:2652, 2759).

### Stage 8 — The resolution map (shim-side, feeds the compiler)
Stored per device, never sent to the dashboard:
```
"<hashedId>": {
  "registry_device_id": "...",           // or entity_id for singletons
  "name": "Kitchen Multisensor",         // for debug messages only
  "members": ["binary_sensor.kitchen_motion", "sensor.kitchen_temp", ...],
  "attr_bindings": { "motion": "binary_sensor.kitchen_motion",
                      "temperature": "sensor.kitchen_temp", ... },
  "cmd_bindings":  { "on": "light.kitchen", "setLevel": "light.kitchen", ... }
}
```
Compile-time resolution = read this map: piston references `<hashedId>` + attribute or
command → the exact member entity_id → cross-check against the translation table's
`ha_source` (the v1 mechanism, relocated wizard → compiler). The map is a rebuildable
cache — registry IDs and the deterministic hash mean it can be reconstructed from HA at
any time; losing it loses nothing.

### Stage 9 — deviceVersion
Hash (or monotonic counter) over the serialized devices map EXCLUDING `v` values — bumps
on membership, capability, or name changes; never on value changes (values refresh via
`refresh`/`activity`, not device re-download).

## 4. Worked example — the case that motivated grouping

Zooz 4-in-1 on HA = 4 entities: `binary_sensor.kitchen_motion` (motion),
`sensor.kitchen_temperature`, `sensor.kitchen_humidity`, `sensor.kitchen_battery`, all
under one registry device "Kitchen Multisensor".
→ ONE picker item "Kitchen Multisensor"; `cn`: Motion Sensor, Temperature Measurement,
Relative Humidity Measurement, Battery; `a`: motion/temperature/humidity/battery each
bound to its member; `c`: [] (sensors). Exactly the Hubitat presentation.
A dimmable light whose registry device has one entity behaves identically to Draft 1's
entity-as-device — grouping is a no-op for singles.

## 4a. REQUIRED help (Jeremy, 2026-07-20)

The translation files this spec governs — `webcore_vocab.json` (`"ha"` arrays +
`_ha_translation`) and `picker_capability_map.json` — are user-editable data on
the /data volume (COMPILER_SPEC §1a). They still lack a user/AI editing
walkthrough. A future session MUST add a "how to edit the translation layer"
section to `/help/editing-compiler`: what the `"ha"` read/write rules and the
picker signal→attribute rules do, their shape, and step-by-step instructions
(for a human or an AI) to add recognition for a new device or attribute. Goal:
a user teaches PistonCore a new attribute translation without a code change.

## 5. Open items
1. ~~Duplicate-attribute split rule~~ — RESOLVED (Jeremy, 2026-07-09): never split; see
   Stage 3 decision text.
2. `entity_category` filter (Stage 1) — validate against Jeremy's real device set; log
   exclusions so hard requirement (1) is auditable.
3. ~~Stage 6 `c[].p` element type~~ — RESOLVED (VERIFIED-HE-GROOVY, 2026-07-10,
   `webcore.groovy:3604-3696` `getDevDetails()`): objects `{n, t, h?, c?}` (name/type/hint/
   constraints) when the driver provides structured parameter metadata (`cmd.getParameters()`),
   types UPPERCASE (`"STRING"`, `"NUMBER"`); falls back to a bare list of UPPERCASE type-name
   strings when the driver only provides `cmd.getArguments()`. See SHIM_API_SPEC.md §5.1.
4. Translation-table `assumed` entries (30 of 90) promote as exercised.
5. Domains without picker-map coverage (19 mapped today) are excluded and logged. Note
   (2026-07-10): Stage 3.2's custom-attribute fallback now covers uncovered *entities*
   generically; this item is specifically about uncovered *domains* the fallback doesn't
   reach structurally — still open.
6. Spike order note: fake devices first (grouping irrelevant), then Stage 1–9 against
   live HA as milestone 2 (CLAUDE.md ladder).
7. ~~Stage 3.3 rule inventory~~ — Speak RESOLVED 2026-07-11: `media_player` + PLAY_MEDIA
   bit (512) -> `speechSynthesis` capability, implemented as a `capabilities` branch on
   `picker_capability_map.json`'s `media_player` domain (`_meta.command_only_lane`) and
   consumed by `device_pipeline.py`'s `capability_keys_for_entity()`, merged into the
   group's capability set independent of the attribute bridge. Verified live against
   Jeremy's real HA: all 6 real media_player devices (SHIELD, Family Room, Kitchen,
   Garage, Basement, room2) now correctly show `Speech Synthesis` in `cn` and `speak` in
   `c`; non-media_player devices are unaffected. `tts.*` enumeration also live-verified
   (`tts.google_translate_en_com`, `tts.piper` found via the existing `get_states` call,
   no second HA round trip needed) — served as `tts_engines` alongside `devices`, feeding
   a future default-TTS-engine setting once a Settings page exists. Notify-device rule
   still waits on the C2/C2b target decision, untouched this session.

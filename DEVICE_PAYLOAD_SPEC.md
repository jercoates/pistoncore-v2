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
| `webcore_vocab.json` | attribute keys → capabilities/attributes/commands definitions (VERIFIED-FILES) |
| `pistoncore_attribute_translation.json` | attribute key → `ha_source` (where the value lives / where commands route) (VERIFIED-FILES) |

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

**Duplicate-attribute rule (DECISION needed, recommendation below):** if two members of
one group map to the SAME attribute key (e.g. a device exposing two temperature sensors),
a single webCoRE device cannot carry `temperature` twice. To satisfy hard requirement (1)
— never drop info — the recommended rule: keep the first contributor (deterministic:
lowest entity_id sort) in the group, and **split each additional contributor out as its
own singleton picker device**, named "<Group Name> <entity friendly name>". Nothing is
lost; the user sees two name-only picker items, which matches how Hubitat handles
composite devices (parent + child devices). Confirm or overrule.

### Stage 4 — Attribute → capability bridge
Unchanged: invert `vocab.capabilities[*].a` once at startup; group's attribute keys →
capability keys → `cn` display names (VERIFIED-FILES). Overlapping capabilities are fine —
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

## 5. Open items
1. Duplicate-attribute split rule (Stage 3) — confirm or overrule the recommendation.
2. `entity_category` filter (Stage 1) — validate against Jeremy's real device set; log
   exclusions so hard requirement (1) is auditable.
3. Stage 6 `c[].p` element type (names vs types) — confirm during spike from dashboard
   behavior (VERIFIED-JS shows menus key on `c[].n`; risk low).
4. Translation-table `assumed` entries (30 of 90) promote as exercised.
5. Domains without picker-map coverage (19 mapped today) are excluded and logged.
6. Spike order note: fake devices first (grouping irrelevant), then Stage 1–9 against
   live HA as milestone 2 (CLAUDE.md ladder).

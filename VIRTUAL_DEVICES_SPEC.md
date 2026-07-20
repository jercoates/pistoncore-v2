# VIRTUAL_DEVICES_SPEC.md — Virtual test devices (behavioral testing)

**Status:** Draft 1 — spec'd from Jeremy's roadmap ("after compiler → virtual
devices for testing → trace", 2026-07-20) and the reconciliation finding that
behavioral testing against faithful twins is what surfaces spec-drift.
Research-backed; every HA-mechanism claim tagged VERIFIED (HA knowledge, ≤2026)
/ ASSUMED / **TO-VERIFY** (needs a live-HA check before building).

**Tagging:** VERIFIED = established HA behavior. ASSUMED = design choice not
yet proven. TO-VERIFY = must be checked against a running HA in the build
session. DECISION = Jeremy's call.

---

## 0. Do not confuse with webCoRE `virtualDevices`

webCoRE already has a thing called `virtualDevices` — `fixtures.build_virtual_devices`
serves `webcore_vocab.json`'s `virtualDevices` (Location Mode, HSM, etc.) to the
EDITOR as pickable system devices (VERIFIED-HE-GROOVY webcore.groovy:6032). **That
is NOT this.** This spec is about **PistonCore TEST DEVICES**: controllable dummy
HA entities that let you exercise a *compiled* piston without real hardware. Different
purpose, different mechanism, different UI (`/test-devices`, currently a stub in
`shim/routes/pages.py`). Keep the words straight in code and UI — call these "test
devices," never "virtual devices," to avoid the collision.

## 1. Why this exists

- **Surface spec-drift behaviorally.** A piston that should fire but doesn't, or
  fires wrong, is drift made visible (RECONCILIATION.md). Reading code catches
  a lot; running the real compiled output against faithful twins catches the rest.
- **Author-and-check without hardware.** The stub's own promise:
  "quickly exercising compiler output without real hardware."
- **No HA dry-run exists.** VERIFIED (HA_LIMITATIONS.md:439): "Test button always
  executes real actions. No dry-run mode." So testing = real entities really
  firing. That forces two rules: outputs must also be dummy (§4), and there must
  be an isolated-instance option (§6) for anyone who won't tolerate real side
  effects.

## 2. The faithfulness principle (LOAD-BEARING)

A test MUST exercise the **actual compiled automation as it would run in
production** — otherwise it tests a different thing and proves nothing about
drift. Consequences:

- A test motion sensor must be a real `binary_sensor` with `device_class: motion`,
  because that is what the compiler binds and emits
  `trigger: state, entity_id: binary_sensor.x, to: "on"` against. An
  `input_boolean` is the WRONG domain — the picker would group it differently and
  the compiled trigger wouldn't match. VERIFIED (device_pipeline grouping keys on
  domain + device_class).
- So a test device is not one entity but a **controllable twin**: a real-domain
  entity the piston sees, plus a way to drive its state.

## 3. What a test device IS, per domain (the research)

The chosen mechanism: **template entities backed by input helpers.** You flip an
`input_*` helper on the test page; a `template` entity of the correct domain +
device_class mirrors it; the piston references the template entity. Faithful
(real domain the compiler emits against) and controllable (you own the input).

| webCoRE device | Test twin (real domain the piston sees) | Driven by |
|---|---|---|
| Motion / contact / presence / smoke / water | `template` **binary_sensor** with the matching `device_class` | `input_boolean` |
| Illuminance / temperature / humidity / power / battery | `template` **sensor** with `device_class` + `unit_of_measurement` | `input_number` |
| Switch | `template` **switch** | `input_boolean` (and the switch's own on/off) |
| Light (on/off + level + color) | `template` **light** | `input_boolean` + `input_number` (brightness) |
| Lock | `template` **lock** | `input_boolean` |
| Alarm panel | `template` **alarm_control_panel** | `input_select` (arm states) |
| Media player / speaker | `template` **media_player** (state + volume) | `input_select` + `input_number` |
| Thermostat | `template` **climate** | `input_number` (setpoints) + `input_select` (mode) |

- Template entities support `device_class`, `unit_of_measurement`, and — for
  actuators (light/switch/lock/climate/media_player) — command handlers that write
  back to the backing input, so a piston that TURNS ON a test light visibly flips
  the input. VERIFIED (HA template integration, ≤2026). **TO-VERIFY:** the exact
  current YAML shape for template `alarm_control_panel`, `media_player`, and
  `climate` (these are the least-mature template domains) on the target HA version.
- **ASSUMED:** one PistonCore-managed template package file per test device (or one
  combined file) is cleaner than scattering helpers. Decide at build time.

**Alternative considered — MQTT entities.** Faithful domain + fully scriptable
state, but needs an MQTT broker and is heavier to set up. ASSUMED reject for the
default path; keep as a power-user option. **Alternative — the `demo`
integration:** provides one entity per domain but not targeted/controllable —
reject.

## 4. Outputs must be dummy too

Because Test executes real actions (§1), a test piston's TARGET devices must also
be test devices, or Test would actuate real hardware. DECISION-CANDIDATE (Jeremy
to confirm): the test flow warns if a piston under test targets a NON-test
(real) device, and offers to swap the target to a test twin for the run. This is
the "faithful twin on both ends" rule — drive test inputs, observe test outputs,
touch nothing real.

## 5. Creation, picker, and the test UI

- **Creation.** Two HA-native paths, reusing what PistonCore already has:
  - Input helpers via the websocket helper-CRUD PistonCore already uses for
    Location Mode (VERIFIED: `ha_client.create_input_select`; the same namespace
    covers `input_boolean/create`, `input_number/create`). **TO-VERIFY:** helper
    CRUD covers every input type needed.
  - Template entities via the **configuration.yaml write capability already built**
    (`shim/config_yaml.py` + the write transport) — PistonCore writes a
    `pistoncore/test_devices/` template package, same include mechanism as
    automations, with the same show-changes-then-consent + backup flow.
- **Picker integration is FREE.** Test devices are real HA entities, so they flow
  through the existing device pipeline (DEVICE_PAYLOAD_SPEC) and appear in the
  editor grouped like any device — named e.g. "Test — Motion 1". No compiler or
  picker change. VERIFIED (they're real entities).
- **The `/test-devices` page** (replaces the stub): create/list/delete test
  devices; a control panel to SET each input (toggle the motion, dial the lux);
  a **Fire** affordance and a live view of what the compiled piston did — which
  automation triggered, which services it called, the resulting test-output
  states. Vanilla JS/Jinja per CLAUDE.md, row lists not tiles (memory:
  never-tile-layouts).

## 6. Two environments

1. **Live instance, labeled test devices (default).** Create `Test — …` entities
   on the user's real HA. Cheapest; works today with the existing write path.
   Safe as long as §4 holds (outputs are test twins). This matches the stub.
2. **Dedicated test HA instance (isolated).** The dev-HA bed idea — a throwaway HA
   with PyScript + seeded test devices, nothing real to actuate. Heavier setup;
   the honest choice for anyone who won't risk real side effects, and the natural
   home for an automated corpus behavioral-gate later. Its own session (there's a
   dev-HA-bed brief already noted); this spec just reserves the seam.

## 7. Relationship to trace (the next milestone)

Test devices DRIVE a piston; trace OBSERVES what it did. Complementary, not
sequential-dependent:
- **Before trace exists**, the test page observes via what it can already see:
  the test-output entities' resulting states, and HA's logbook/`get_states`.
- **With trace** (`TRACE_ACTIVITY_CONTRACT.md`, Draft 2, spec-ready), the test
  page shows the per-statement path — which trigger fired, each condition's
  value — turning "it didn't fire" into "it evaluated condition $4 false." That is
  the richest form of drift-surfacing. Build test devices first (they need no
  trace); wire trace into the test view when trace lands.
- **Forced-PyScript + test** is the strongest combo for the toggle Jeremy added:
  a piston forced to PyScript for fidelity, driven by test devices, observed via
  trace, is the full behavioral-fidelity loop. RECONCILIATION.md confirms the
  PyScript path is over-built enough to deliver this.

## 8. Open items / TO-VERIFY before building

1. Template YAML shape for `alarm_control_panel`, `media_player`, `climate` on the
   target HA version (§3) — least-mature template domains.
2. Helper-CRUD coverage for every input type (§5).
3. The output-swap rule (§4) — Jeremy to confirm the warn-and-offer-swap flow.
4. Whether one combined template package or per-device files is cleaner (§3).
5. Package/include path + config.yaml lines for `pistoncore/test_devices/` — mirror
   the automations/scripts include design (COMPILER_DECISIONS_DEPLOY §3).
6. Reset/teardown: deleting a test device must remove BOTH the template entity and
   its backing helper, and clean the package file (no orphans — same discipline as
   the deploy rename cleanup).

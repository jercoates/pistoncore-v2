# VIRTUAL_DEVICES_SPEC.md — Test devices (behavioral testing)

**Status:** Draft 2 — rewritten 2026-07-20 around Jeremy's actual mechanism
(the Draft 1 abstraction missed it). Plain-language behavior first (Jeremy
verifies behaviorally, not by reading code); the under-the-hood realization is
lower down, tagged for the build session.

**Tagging:** VERIFIED = established HA behavior. ASSUMED = design choice not yet
proven. **TO-VERIFY** = check against a running HA in the build session.
DECISION = Jeremy's call.

---

## 0. Don't confuse the name

webCoRE already has "virtualDevices" (Location Mode / HSM, served to the
editor — `fixtures.build_virtual_devices`). This feature is different. Call
these **"test devices"** everywhere in code and UI so the two never collide.

## 1. What you'll be able to do (the whole point, in behavior)

1. PistonCore looks at all your real devices — the ones coming in from Hubitat
   through Home Assistant — and grabs **one of each TYPE** (one motion sensor,
   one contact, one dimmer, one thermostat, one alarm panel, one speaker…).
2. For each, it makes a **controllable copy** — a test device that is the same
   KIND of device but that PistonCore can set the state of.
3. You get a **control panel inside PistonCore** where you flip every
   capability of every test device: turn the test motion active/inactive, drag
   the test lux to 500, arm the test alarm, set the test thermostat to 72.
4. You write (or point) a piston at those test devices, and when you flip a
   control, the piston fires **exactly as it would for the real device** — and
   you watch what it does. A piston that should fire but doesn't, or does the
   wrong thing, is a bug made visible without touching real hardware.

That's it. Grab one of each real type → make a copy you can drive → drive them
all from PistonCore → watch pistons behave.

## 2. Why COPIES, not your real devices (the reason this feature exists)

Two hard reasons, both plain:

- **Home Assistant won't let PistonCore set a real device's state.** Your
  Hubitat devices are owned by the Hubitat integration — PistonCore can read
  them but can't make `binary_sensor.cave_motion` say "active" on command; HA
  ignores or overwrites that. VERIFIED (HA state-machine ownership). So to
  *drive* a device for a test, PistonCore must own a copy it's allowed to set.
- **Testing fires for real.** VERIFIED (HA_LIMITATIONS.md:439 — "Test button
  always executes real actions. No dry-run mode."). If a test piston turned on
  your real cave light every time you tested, that's unusable. So the OUTPUT
  side must be test copies too — drive test inputs, watch test outputs, touch
  nothing real.

## 3. "One of each type" — what a TYPE is

Your device payload already groups devices by capability (DEVICE_PAYLOAD_SPEC).
Two devices are the SAME type when they expose the same capabilities/attributes
— all your motion sensors are one type; a motion+lux camera sensor is a
different type; the thermostat is its own type. PistonCore walks the grouped
payload, buckets by capability signature, and takes ONE representative per
bucket. Result: a test-device set that mirrors exactly the kinds of devices YOU
have — not a generic list, your actual shapes. ASSUMED: dedupe key = the sorted
set of attribute keys + commands. **TO-VERIFY:** confirm against Jeremy's real
payload that this yields a sensible, not-too-long list.

## 4. The control panel (PistonCore owns it) — REQUIRED per device

A page at `/test-devices` (replaces today's stub), showing each test device as
a ROW (never tiles — memory: never-tile-layouts). **Every test-device row MUST
have (Jeremy, 2026-07-20):**

1. **A test/virtual TAG** clearly marking it a test device, not a real one —
   visible on the row, and in its HA name (`Test — …`), so it's never mistaken
   for real hardware anywhere.
2. **An add/remove-from-HA toggle.** Flip ON = PistonCore creates the test
   device in Home Assistant (so it exists to author against and drive); flip
   OFF = PistonCore removes it from HA cleanly (both the copy and its backing
   parts — no orphans, §8.6). So a test device can sit defined-but-not-present
   until you want it, and be pulled out when you're done.
3. **One control per capability, showing its CURRENT state.** Each capability
   the device has gets its own control that both SETS and DISPLAYS the value:
   - on/off (motion, contact, switch, smoke, water) → a toggle showing on/off
   - numbers (lux, temperature, humidity, level) → a slider/box showing the value
   - choices (alarm arm state, thermostat mode, media state) → a dropdown showing
     the current choice
   The current state is always visible, so you can see what the test device is
   reporting right now, and change it in place.

Flipping a capability control sets that test device's state immediately, so you
can set up a scenario (motion active AND it's dark AND alarm armed) and watch
the piston go. DECISION-CANDIDATE (Jeremy): a "fire now / reset all" affordance
too.

## 5. How it's built under the hood (for the build session)

Plain summary: a test device is a **real HA entity of the right kind that
PistonCore can set**, made from parts PistonCore already knows how to create.

- **Settable copies via HA helpers + template entities.** PistonCore creates an
  input helper it's allowed to set (`input_boolean` for on/off,
  `input_number` for values, `input_select` for choices — same helper-create it
  already uses for Location Mode, VERIFIED `ha_client.create_input_select`), and
  a `template` entity of the REAL domain + device_class that mirrors it
  (template `binary_sensor` device_class motion, template `sensor` with a unit,
  template `light`/`switch`/`lock`/`alarm_control_panel`/`climate`/`media_player`).
  The piston sees the template entity (correct kind → correct compiled trigger);
  the PistonCore control panel sets the backing helper; the template mirrors it.
- **Why the template layer is needed:** the copy must be the same DOMAIN the
  compiler emits against. A piston on a motion sensor compiles to
  `trigger: state, entity_id: binary_sensor.x, to: "on"` — so the test copy has
  to be a `binary_sensor`, not a bare `input_boolean`, or the trigger wouldn't
  match. VERIFIED (device_pipeline groups on domain + device_class).
- **Created through the write path already built** — the template entities go in
  a `pistoncore/test_devices/` package via `shim/config_yaml.py` + the write
  transport, same show-changes-consent-backup flow as automations. Helpers via
  the websocket helper-CRUD.
- **The picker needs zero changes** — test devices are real HA entities, so they
  flow through the existing device pipeline and appear in the editor grouped
  like any device, named e.g. "Test — Motion". VERIFIED.
- **TO-VERIFY (build session):** exact current template YAML shape for the
  less-mature domains — `alarm_control_panel`, `media_player`, `climate`; and
  helper-CRUD coverage for `input_boolean`/`input_number` (mode used
  `input_select`).
- **ALTERNATIVE to evaluate at build (may be simpler, and is the most
  "PistonCore controls it directly" option):** a single PyScript module that
  PistonCore deploys, which creates every test entity and exposes ONE service
  to set any of them — PistonCore's control panel just calls that service. No
  template YAML, no separate helpers. Uses the pyscript deploy path already
  built. **TO-VERIFY:** whether a PyScript `state.set` entity lands in HA's
  entity REGISTRY so the device pipeline/picker sees it (state-only entities
  sometimes don't). If it does, this is likely the cleaner mechanism; if not,
  fall back to the template+helper path above.

## 6. Two places to run it

1. **On your real HA, as clearly-labeled test devices (default).** The copies
   live on your live instance named `Test — …`. Works with the write path today.
   Safe as long as both ends are test copies (§2).
2. **On a throwaway test HA (isolated).** Nothing real to touch; the honest
   choice if you never want side effects, and the home for an automated
   behavioral gate later. Its own session; this spec just reserves the seam.

## 7. Relationship to trace (the next milestone)

Test devices DRIVE a piston; trace SHOWS what it did.
- **Before trace:** the control panel shows what it can already see — the test
  OUTPUT devices changing, plus HA's logbook.
- **With trace** (TRACE_ACTIVITY_CONTRACT.md, Draft 2, spec-ready): the panel
  shows the per-statement path — which trigger fired, each condition's value —
  so "it didn't fire" becomes "condition $4 was false." Build test devices first
  (they need no trace); wire trace into the panel when trace lands.
- **Forced-PyScript + test + trace** is the full fidelity loop the compile-band
  override was built for.

## 8. Open items / TO-VERIFY before building

1. Dedupe key for "one of each type" yields a sane list on Jeremy's real payload (§3).
2. Template YAML shape for alarm_control_panel / media_player / climate (§5).
3. Helper-CRUD coverage for every input type (§5).
4. Output side: confirm both ends must be test copies, and how a piston authored
   on real devices gets swapped to test twins for a run (or authored on test
   devices directly) — Jeremy to confirm the workflow.
5. Package/include path + config.yaml lines for `pistoncore/test_devices/`
   (mirror the automations/scripts include, COMPILER_DECISIONS_DEPLOY §3).
6. Teardown: deleting a test device removes BOTH the template entity and its
   backing helper and cleans the package file — no orphans.

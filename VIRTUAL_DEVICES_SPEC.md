# VIRTUAL_DEVICES_SPEC.md — Test devices (behavioral testing)

> ## ⚠ READ BEFORE CHANGING ANYTHING
> **This spec may be out of date, and may be MISSING decisions that were made
> but never written down.** A spec can tell you what to **build**. It NEVER, on
> its own, authorises **undoing** something that already works.
>
> If the code does something this document doesn't mention, that is most likely
> a real decision — check `git log -S "<the thing>"` first, then **ASK JEREMY**.
> **Never delete working behaviour without his explicit go-ahead.** (Removing
> genuinely dead code is fine.)
>
> Standing decisions that outrank this document: **[HARD_RULES.md](HARD_RULES.md)**

**Status:** Draft 3 — mechanism DECIDED 2026-07-20 (Jeremy): build on a fork of
the GPL-3.0 `twrecked/hass-virtual` integration. Draft 2's template+helper
mechanism is REJECTED (it can't group; see §5). Plain-language behavior first
(Jeremy verifies behaviorally, not by reading code); the under-the-hood
realization is lower down, tagged for the build session.

**Tagging:** VERIFIED = established HA behavior / read in code. ASSUMED = design
choice not yet proven. **TO-VERIFY** = check against a running HA in the build
session. DECISION = Jeremy's call.

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

## 1.5 The SECOND purpose — the long-term maintenance bench (Jeremy, 2026-07-20)

Test devices are also **Jeremy's way to work on device types he does NOT own.**
The compiler needs a mapping for every device kind webCoRE can target, but you
can't write or verify a mapping for a siren / humidifier / vacuum / thermostat
you don't have on the bench. A test device of that kind — settable, driveable,
with visible compiled output — lets Jeremy add the missing mapping and *see it
work* without buying hardware or waiting on help. This is what makes PistonCore
**self-maintainable long-term.** So the integration must be able to build **every
device kind the compiler targets, not just the ones in Jeremy's house** (§5.2).
This is why the "needed devices" list below is the compiler's target set, not an
inventory of his home.

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

**Plus the bench types you DON'T own (§1.5).** Auto-discovery covers your house,
but the control panel must ALSO let you spin up a test device of any kind the
compiler targets even when you own none of it — a "add a test device of kind…"
picker over the full §5.2 list — so you can build and verify a siren / humidifier
/ vacuum mapping with nothing of that kind in your home. The owned set is the
default rows; the full target set is what's *available* to add.

## 4. The control panel (PistonCore owns it) — REQUIRED per device

A page at `/test-devices` (replaces today's stub), showing each test device as
a ROW (never tiles — memory: never-tile-layouts). **Every test-device row MUST
have (Jeremy, 2026-07-20):**

1. **A test/virtual TAG** clearly marking it a test device, not a real one —
   visible on the row, and in its HA name (`Test — …`), so it's never mistaken
   for real hardware anywhere.
2. **An add/remove-from-HA toggle.** Flip ON = PistonCore has the integration
   create the test device in Home Assistant (so it exists to author against and
   drive); flip OFF = PistonCore has it removed cleanly (device and all its
   entities — no orphans, §8.6). So a test device can sit defined-but-not-present
   until you want it, and be pulled out when you're done.
3. **One control per capability, showing its CURRENT state.** Each capability
   the device has gets its own control that both SETS and DISPLAYS the value:
   - on/off (motion, contact, switch, smoke, water) → a toggle showing on/off
   - numbers (lux, temperature, humidity, level) → a slider/box showing the value
   - choices (alarm arm state, thermostat mode, media state) → a dropdown showing
     the current choice
   The current state is always visible, so you can see what the test device is
   reporting right now, and change it in place.

Flipping a capability control sets that test device's state immediately (via the
integration's set-state service, §5), so you can set up a scenario (motion active
AND it's dark AND alarm armed) and watch the piston go. DECISION-CANDIDATE
(Jeremy): a "fire now / reset all" affordance too.

## 5. How it's built under the hood — DECIDED: build on `hass-virtual`

### 5.1 The mechanism, and why the two simpler ones were rejected

A faithful test device must be **one real HA device that owns several entities
(one per capability), grouped under a single device-registry entry**, or the
editor's picker shows it as several unrelated one-trick devices instead of one
multi-capability copy. VERIFIED — the grouping code is explicit: an entity with
no registry `device_id` "becomes a singleton group of one"
(`device_pipeline.py:156-169`); your real multi-sensors carry 34–40 entities
under one device, and that shape is what must be matched.

Two mechanisms were evaluated and **REJECTED** for this reason — do not
resurrect either:

- **REJECTED — PyScript `state.set`.** A PyScript-invented entity is
  *state-only*: it appears in the live state machine but never lands in HA's
  **entity registry**, which is what the device pipeline enumerates
  (`ha_client.fetch_registries` → `config/entity_registry/list`, consumed at
  `device_pipeline.py:148`). So it would be invisible in the picker. Dead end.
- **REJECTED — Template helpers + input helpers.** The Template helper builds
  **one entity at a time** and can only attach it to a device that *already
  exists*; it has no way to *create* a device to bundle several readings under.
  So it can't produce a grouped multi-capability copy. VERIFIED against Jeremy's
  live HA (2026-07-20): zero template helpers present, and the helper flow
  offers no create-a-device step.

The only kind of thing HA lets create a device and hang all its entities off it
is a **custom integration**. So:

### 5.2 DECISION (Jeremy, 2026-07-20): fork and extend `twrecked/hass-virtual`

Rather than a clean-room integration, **build on
[`hass-virtual`](https://github.com/twrecked/hass-virtual)**. It is
**GPL-3.0** (matches this repo — fork-clean, and shippable in/with a GPL
project), it is in the **default HACS store** (community-trusted), and it
already delivers most of what we need, VERIFIED from its docs (2026-07-20):

- **Grouped multi-capability devices** — its own example is a motion device
  carrying both a motion binary_sensor and a battery sensor under one device.
- **Live set-state from outside**, the seam PistonCore drives:
  `virtual.turn_on` / `virtual.turn_off` / `virtual.toggle` (on/off),
  `virtual.set` (values), `virtual.move` (device_tracker),
  `virtual.set_availability`.
- **Nine platforms already done and battle-tested:** binary_sensor, sensor,
  light, switch, lock, fan, cover, valve, device_tracker.

**What we ADD on the fork** (the gap between it and webCoRE fidelity):

1. **The device kinds the compiler targets that `hass-virtual` does NOT cover.**
   The authoritative "needed devices" list is the set of HA domains the compiler
   actually emits services against — extracted 2026-07-20 from
   `templates/compiler/yaml/classic/command_maps.json` (that file was deleted
   2026-07-26; the same mappings now live in `webcore_vocab.json` per-command
   `"ha"` entries, so re-extract from there if this list is ever refreshed):
   `button, camera, climate, cover, fan, humidifier, light, lock, media_player,
   siren, switch, vacuum` (`homeassistant` = the generic cross-domain
   turn_on/off, not a device kind), plus `alarm_control_panel` (HSM/arm state,
   handled via value_maps, heavily used). `hass-virtual` already provides
   light, switch, lock, fan, cover (+ binary_sensor, sensor, valve,
   device_tracker for the read side). So the platforms **we must add to the
   fork** are:
   - `alarm_control_panel` — arm/disarm state (webCoRE HSM; heavily used)
   - `climate` — thermostat: settable target temp, mode, current temp
   - `media_player` — speaker: settable state / volume
   - `siren` — on/off + tone (a likely hard-fail source Jeremy doesn't own)
   - `humidifier` — on/off + target humidity/mode
   - `vacuum` — start/stop/dock state
   - `button` — press (stateless; a test press that records it fired)
   - `camera` — edge kind (commands like snapshot); include only if a corpus
     piston needs it, else defer. **TO-VERIFY** which hard-fails actually need it.

   Each new platform is a settable platform in the same style as the existing
   nine, with a set-state path reachable from PistonCore. **This list is what
   makes the bench complete (§1.5)** — with all of these, Jeremy can author and
   verify a mapping for any device kind the compiler targets, owned or not.
2. **Live create/remove an outside app can trigger.** `hass-virtual` configures
   devices via YAML (plus a newer config-flow GUI); neither existing project
   solves *both* live-add AND external set-state (the newer `hassio-virtual-
   devices` does live-add but has no external set-state, so it was not viable).
   So PistonCore must be able to add/remove a test device **without the user
   hand-editing YAML**. **TO-VERIFY (build session):** the cleanest of —
   (a) PistonCore writes the integration's YAML + calls its reload service;
   (b) we add a `create`/`remove` service to the fork; (c) config-flow entries
   created programmatically over the websocket. Goal: the §4 add/remove toggle
   just works.

### 5.3 How PistonCore uses it

- **Discovery** — PistonCore buckets the grouped device payload by capability
  signature (§3) and picks one representative per type.
- **Create** — for each chosen type, PistonCore tells the integration to create
  a matching virtual device with the same domain + device_class entities,
  grouped (name `Test — …`). The picker then surfaces it exactly like any real
  device — **no picker/pipeline change needed**, because it's a real grouped HA
  device. VERIFIED (pipeline groups any device with a registry `device_id`).
- **Drive** — each §4 capability control calls the matching `virtual.*` service
  (or the new alarm/climate/media set-state) and reads current state back from
  HA to display it.
- **Output side** — virtual `light`/`switch`/`lock` the piston acts on; the
  integration records the command, PistonCore/logbook shows it. Nothing real
  moves (§2).

### 5.4 Install & lifecycle (the honest friction)

It's a custom integration, so its files live in HA's `custom_components/` and HA
needs **one restart** to first load it; after that, devices add/remove live
(the §5.2 item 2 goal). DECISION-CANDIDATE: PistonCore *offers to install* the
integration files for the user (via the write path it already has) so they don't
do it by hand. **TO-VERIFY:** whether PistonCore's HA access can write to
`custom_components/` and trigger the restart. If not, the user does a one-time
manual/HACS install; everything after is smooth.

### 5.5 Where the fork lives — DECIDED (Jeremy, 2026-07-21): in-repo folder for now

Develop it **in-repo** as a top-level folder `test-devices-integration/` while it's
young (fast to iterate alongside the shim), and **split it out to its own repo at
release** when it's HACS-ready (a clean one-time move). It is NOT part of `dashboard/`
and NOT inside `shim/`. It keeps its own GPL-3.0 headers and upstream attribution to
`twrecked/hass-virtual`.

### 5.6 STANDALONE SELF-SUFFICIENCY — REQUIRED (Jeremy, 2026-07-21)

The integration must be **fully usable on its own, through Home Assistant's native
UI and services**, with **no PistonCore required**. It is a community deliverable in
its own right; PistonCore's `/test-devices` panel is an **optional nicer front-end**,
never the only control surface. Concretely:

- **Create/remove** works through the integration's HA **config flow** (Settings →
  Devices & Services — the way any HA user adds/removes an integration) — the same
  path PistonCore drives programmatically over the websocket. Never a PistonCore-only
  API.
- **Set state** works through HA **services** (usable from Developer Tools → Actions)
  and through native controls in a Lovelace dashboard where the entity type supports
  it. PistonCore's panel calls those same services.
- So a standalone user gets the full feature set from HA alone; PistonCore adds
  convenience (auto-discovery of "one of each type," the grouped control panel), not
  capability. Do not build any core capability that only PistonCore can reach.

## 5.7 Discovery-driven twins + FULL reproduction (Jeremy, 2026-07-21)

The bench is **discovery-driven**, not a generic catalog: PistonCore reads the
user's REAL devices (`device_pipeline.group_entities`), buckets them by capability
signature, and offers a faithful **twin** of each type — reproducing the same HA
entities (domain + device_class + name). `_discover_twin_types()` in
`shim/routes/pages.py` does this. The generic edge-case catalog
(`TEST_DEVICE_TEMPLATES`) stays too, for kinds the user does NOT own.

**Reproduce EVERYTHING — no trimming (firm).** A full debug suite is large ON
PURPOSE. The "extra" capabilities are the whole point: YoLink alarm thresholds,
Inovelli/Zooz **double-tap / held / pushed / released**, a camera's
**smartDetectType**, mmWave presence, IR — a piston (especially someone else's)
may trigger on any of them, so a twin must carry all of them, not a tidied
subset. An early build trimmed diagnostics/config/noise; that was WRONG and was
removed. Only skip: entities in domains not yet reproducible (below). Simple
devices come out simple, complex devices come out full — that falls out of
reproducing everything, so don't second-guess the size.

**Camera smartDetect:** reproduced as a plain string `sensor` (values like
`person`, `vehicle`, `waiting`). VERIFIED it accepts the state; the panel sets a
`sensor` via a free-text box (typing isn't ideal UX — a dropdown of known values
is a future nicety, but settability is what matters).

### 5.7a FULL-FIDELITY CLONING — abilities, not just entity kinds (BUILT 2026-07-31)

Reproducing every ENTITY was only half of "no trimming". Until this was built the
clone also dropped every ABILITY: it copied platform, device_class and unit and
nothing else, so a cloned thermostat came back as a plain single-setpoint heater
and a cloned speaker as a generic one. VERIFIED against the live test HA:
`climate.my_ecobee` reports `supported_features` **155** — single setpoint AND
heat/cool range, fan modes, preset modes — none of which the virtual climate
platform could express.

**The mechanism.** HA already states a device's abilities as the
`supported_features` bitmask plus a few list/range attributes. Cloning copies
those verbatim; every virtual platform now accepts them and falls back to its
previous hardcoded default when a key is absent (so pre-existing test devices and
hand-written `virtual.yaml` are unaffected).

**WHERE THE ATTRIBUTE LIST COMES FROM — this is a rule, not a note.** It is taken
from HA's own `capability_attributes` property on each entity base class, which is
HA's definition of "the attributes describing what this entity can DO". It must
NOT be derived by looking at one person's devices. A first pass did exactly that,
built the table from Jeremy's install, and silently dropped `target_humidity_step`
(climate AND humidifier) and `swing_horizontal_modes` — because nothing in his
house reports them. **PistonCore is for other people's houses.** Re-derive by
printing those properties from a real HA after an HA upgrade; never infer them.

| domain | captured and accepted |
|---|---|
| climate | supported_features, hvac/preset/fan/swing/swing-horizontal modes, min/max temp, target temp step, min/max humidity, target humidity step, temperature_unit |
| media_player | supported_features, source_list, sound_mode_list, device_class |
| vacuum | supported_features, fan_speed_list |
| siren | supported_features, available_tones |
| humidifier | supported_features, available_modes, min/max humidity, target humidity step, device_class |
| lock | supported_features, code_format |
| alarm_control_panel | supported_features, code_format, code_arm_required |
| cover | supported_features (incl. tilt) |
| light | supported_features, supported_color_modes, effect_list, min/max color temp kelvin |
| fan | supported_features, preset modes, speed count (from percentage_step) |
| sensor / number | state_class, options / min, max, step, mode |

**Rules that fall out of it, and why:**
- **An empty menu is never advertised.** If a clone carries PRESET_MODE but no
  preset list, the flag is cleared — otherwise HA shows a dropdown with nothing
  in it.
- **Everything advertised has a handler.** A clone that claims an ability and
  then raises when it's used is worse than useless as a bench.
- **Two exceptions, deliberate:** `BROWSE_MEDIA` and `SEARCH_MEDIA` are stripped
  from cloned speakers. Jeremy's Sonos reports both (`supported_features`
  8321599, measured); there is no library behind a virtual speaker, so keeping
  them would only add UI buttons that raise. Nothing PistonCore emits uses either.
- **Contradictions are preserved, not tidied.** A bridged fan that populates
  `preset_modes` while leaving the PRESET_MODE flag unset is cloned exactly like
  that — reproducing it is the point.
- **The capture table and the platform schemas move together.** The virtual
  platforms validate against a closed schema, so a key the platform doesn't
  declare fails entity creation outright rather than degrading.

**THE CAPABILITY-ATTRIBUTES-ONLY RULE IS ALSO A PRIVACY BOUNDARY — keep it that
way (found 2026-07-31 by reading the Hubitat bridge on the test HA).** Real
bridged devices carry driver-level extras beyond anything HA defines, and some of
them are secrets:

| domain | bridged extras seen | contains |
|---|---|---|
| alarm_control_panel | `codes`, `code_length`, `max_codes`, `entry_delay`, `exit_delay`, `alarm` | **plaintext PINs and the people they belong to** |
| lock | `codes`, `code_length`, `last_code_name`, `max_codes` | **household member names**, who last unlocked the door |

Because §5.7a captures only what HA's own `capability_attributes` names, none of
this is picked up — the clone spec for a lock carries `code_format` and nothing
else. **That is currently true by scoping, and must stay true by intent.** Item 17
exists so a bug report can carry a device clone; a clone that captured `codes`
would publish a stranger's (or Jeremy's) alarm code to a public GitHub issue.
Anyone widening the capture table past HA's capability attributes has to reckon
with this first.

Separately, these extras are the honest reason a clone of a Hubitat lock is not
a complete stand-in: `last_code_name` in particular is used heavily by real
webCoRE lock pistons. That belongs with the driver/custom-command work (roadmap
item 14), not with capability cloning.

**HARD LIMIT — say this plainly, do not oversell the bench (measured 2026-07-26):**
this clones **SHAPE, not BEHAVIOUR**. It reproduces what a device says it can do;
it does not reproduce how that device's integration mangles values in flight. The
fan bug that motivated the whole feature lives in a *bridge*, and an
attribute-identical clone did **not** reproduce it. Capability and shape bugs are
catchable here; integration-behaviour bugs are not, and no amount of attribute
cloning will change that.

**Fixed on the way past:** `lock.open` on a virtual lock called a sync stub and
raised `NotImplementedError` — it had never worked. It matters now that a clone
can advertise the OPEN (latch) feature. Also, cloning a device containing a
`number` entity could never have succeeded: that platform *requires* min/max and
the clone never sent them. And `VirtualSensor`/`VirtualNumber` are plain `Entity`
subclasses, not `SensorEntity`/`NumberEntity` — so `_attr_state_class`,
`_attr_options`, `_attr_native_step` and `_attr_mode` are INERT on them; those
values reach the state machine only via `extra_state_attributes`.

### 5.7a-i How this is verified (and how to re-verify)

Verified on a **private throwaway HA in Docker**, NOT on Jeremy's test instance —
his install cannot prove portability, since it has no vacuum, siren, humidifier
or cover at all, and using it also interferes with his own work.

    docker run -d --name pc-testha -p 8124:8123 \
      -v <scratch>/ha-config:/config ghcr.io/home-assistant/home-assistant:stable
    # onboard via /api/onboarding/users, then create the `virtual` config entry
    # through the REST config-flow — the same calls _ensure_group() makes.

**Crash-safety suite (run before the 2026-07-31 push, all green):** six HA restarts
with no entity growth and no CRITICAL / integration ERROR / blocking-call warnings;
five back-to-back config-entry reloads; and the device file deliberately EMPTIED,
replaced with a non-mapping, and replaced with broken YAML — in every case HA
reached RUNNING, the entry loaded, the integration degraded to zero devices, and
restoring the good file brought all devices back. The safety net was also
triggered directly: handed a value yaml cannot represent, the saver raises and the
**existing file is left byte-identical**.

Three checks, all green as of 2026-07-31:
1. **14 clone specs** for devices deliberately NOT in Jeremy's house (Roborock,
   Denon receiver, outdoor siren, dehumidifier, Venetian blind, RGBWW bulb,
   cool-only °F thermostat, euro deadbolt...) create successfully and report back
   every ability requested.
2. **43/43 service calls** succeed against those clones — every advertised
   ability is actually drivable.
3. The deliberate BROWSE_MEDIA/SEARCH_MEDIA strip is confirmed by arithmetic
   (asked 5242815, reports 917439, difference exactly those two flags).

### 5.7a-ii WHERE THE CLONE ENGINE LIVES — settled 2026-07-31 (Jeremy)

**In the add-on (`custom_components/virtual/clone.py`), exposed as
`virtual.clone_device`. PistonCore only names a device.**

The deciding argument is not tidiness, it is the closed schema: hand a platform a
config key it does not declare and entity creation fails outright. The capture
list and the platform schemas are therefore ONE contract. In one file tree they
cannot disagree; split across two projects on two release cycles, drift is
guaranteed — which is exactly how `target_humidity_step` and
`swing_horizontal_modes` went missing.

Consequences, all deliberate:
- PistonCore's `create-twin` sends `{label, device_id}` and nothing else. Its
  discovery list is DISPLAY ONLY and no longer has to track the add-on's schemas.
- The service declares a `device` selector, so HA's own Actions screen renders a
  searchable device picker — standalone cloning with no frontend to maintain.
- An `entity_id` is accepted as well as a device id, for entities with no
  device-registry entry of their own (PistonCore's singleton groups).

**Rejected: a separate optional external controller** (Jeremy, 2026-07-31) — a
third component to version, carrying the same drift risk, with no upside over
bundling. **Deferred: a sidebar panel in the add-on.** Right shape, wrong time:
its only audience is people who want virtual devices but not webCoRE, and those
people already have upstream hass-virtual. Deferring costs nothing now that the
engine sits in the right place — a panel later is purely additive.

**Two behaviours worth knowing, both proven here rather than assumed:**
- **Cloned limits are enforced.** Setting 70 on a cloned 60–90 °F thermostat from
  a metric HA is rejected — HA reads it as 70 °C = 158 °F. The clone's range and
  unit are real, not decoration. Same for a cloned lock's `code_format`: calling
  `lock.unlock` without a code is correctly refused.
- **`create_device` used to race itself — FIXED 2026-07-31, no pacing needed now.**
  Both create and remove did read-modify-write on one yaml file then reloaded the
  entry. Fired concurrently, every caller loaded before any caller saved:
  **six concurrent creates produced one device and reported no error at all.**
  `_mutate_and_reload` now serializes the edit per entry and collapses a burst
  into one reload (measured: 8 concurrent creates = the same single reload as 1).
  Proven by rebuilding the whole 14-device bench with 14 simultaneous calls.
- **CLONED ENTITY NAMES MUST BE QUALIFIED BY THEIR DEVICE — FIXED 2026-07-31.**
  This integration keys an entity's identity by its NAME within the group, so two
  devices carrying an identically-named entity fight over one identity and HA
  re-registers the loser on EVERY restart. Cloning one device twice produced five
  colliding names and **five brand-new entities per restart, growing without
  limit** — the entity registry inflating forever, invisibly. Capability-only
  names collide trivially ("Battery", "Automatic backup"), so a clone names each
  entity `<device name> <capability>`, which is also what the base integration
  does when it names entities itself. Verified stable across six restarts.
- **A failed save used to destroy the device file — FIXED 2026-07-31.** The savers
  opened the real file in `'w'` (truncating it) and only then serialized, with the
  exception swallowed at DEBUG. One unserialisable value — an HA enum that reached
  the config — emptied the file, wiped every test device, and left the integration
  unable to load, silently. Now: serialize first, temp-file + atomic replace, errors
  logged and raised, and an unreadable file degrades to "no devices" instead of
  killing setup. **This is the "looks like it deleted everything" failure class
  again** — same shape as the 2026-07-12 Docker mount incident.

**Known gaps — capability kinds that still need work (TO-BUILD):**
1. **Multi-tap / scene button events** (Inovelli, Zooz — double-tap is used
   heavily). These are momentary EVENTS (single/double/held/released/pushed),
   not states, and often arrive as HA `event` entities — a domain the fork
   doesn't reproduce yet. Needs an `event`-style test platform that can FIRE a
   chosen sub-event (like `button.press` but with a value). **Without this the
   twin can't test a double-tap piston.**
2. **`select` domain** capabilities (modes, presets) — skipped today; needs a
   settable select platform for full fidelity.
3. **New device types the user is adding:** a LinkLink/Broadlink **eMotion Ultra**
   with **IR** (command device) and **mmWave presence** (an occupancy/presence
   binary_sensor — reproducible now; IR-blast commands are the harder part).

These are real, named build items — not to be quietly dropped again.

## 5.8 TWO surfaces, two audiences (Jeremy, 2026-07-21 — supersedes single-panel)

The bench serves two different people, so it has two surfaces sharing one engine
(the integration's create/set/remove):

1. **Clone panel — `/test-devices` (USER-facing).** Discovers the user's REAL
   devices (`_discover_twin_types`) and offers a faithful **clone** of each, full
   reproduction (§5.7). This is for a normal user testing THEIR automations
   against copies of THEIR gear — "going to be a hit with users." The commonest
   want, and the friendly default surface.
2. **Debug library panel — DEVELOPER-facing, separate.** The full **72-capability
   library** from `webcore_vocab.json` (`capabilities`), one single instance of
   every capability/edge-case type — the overwhelming majority of which the user
   does NOT own. This is the actual "full debug suite": for debugging pistons and
   building compiler coverage against devices you don't have (yours, a friend's,
   community pistons). Reached from **Diagnostics** AND a **"Developer" link at the
   bottom of the screen** so it's findable. Generated from the vocab's own
   `_ha_translation` attribute/command rules (motionSensor→binary_sensor/motion,
   thermostat→climate, alarm→siren, valve→valve, button/holdableButton→multi-tap,
   …), NOT guessed. Includes a "spin up the whole suite" action.

Why both: cloning gives a user what they HAVE; the library gives a developer what
they DON'T. Neither alone is the bench. The earlier generic 20-item catalog and
the "twin-only" idea are both retired by this split.

**Build state (2026-07-31):** clone discovery engine, create-twin endpoint, the
"Your devices" UI and entity-name de-dup all built. Full-fidelity capability
capture + accept built across all 12 domains (§5.7a) and VERIFIED END TO END on a
private throwaway HA (§5.7a-i): 14 out-of-house clone specs create correctly,
43/43 service calls drive them. Debug library: not built — vocab-driven generator
+ its own panel + the Diagnostics/Developer links.

## 6. Two places to run it

1. **On your real HA, as clearly-labeled test devices (default).** The copies
   live on your live instance named `Test — …`. Safe as long as both ends are
   test copies (§2).
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

## 8. Open items / TO-VERIFY before/at building

1. Dedupe key for "one of each type" yields a sane list on Jeremy's real payload (§3).
2. The three added platforms — alarm_control_panel / climate / media_player —
   built in `hass-virtual`'s style, each with a set-state path (§5.2).
3. Live create/remove mechanism an outside app can trigger — pick a/b/c (§5.2).
4. Output side: confirm both ends must be test copies, and how a piston authored
   on real devices gets swapped to test twins for a run (or authored on test
   devices directly) — Jeremy to confirm the workflow.
5. Can PistonCore install the integration files + trigger the one-time restart,
   or is first install manual/HACS (§5.4)?
6. Teardown: removing a test device removes the device AND all its entities and
   cleans config — no orphans (§4.2).
7. Fork location: sibling repo vs. in-repo folder (§5.5) — Jeremy's call.

## 9. Build order (proposed)

1. **Fork `hass-virtual`**, get it installed and running on the dev HA unchanged
   — prove the baseline (create a grouped virtual motion+battery device via its
   YAML, set it with `virtual.set`, confirm it appears grouped in PistonCore's
   picker). Establishes the whole approach before we add anything.
2. **Add the live create/remove seam** (§5.2 item 2) — so a device can be added
   and removed without hand-YAML. This is the load-bearing new capability.
3. **Add the missing platforms (§5.2 full list)** — alarm_control_panel,
   climate, media_player, siren, humidifier, vacuum, button (camera only if a
   corpus piston needs it). This is what makes the bench complete (§1.5).
4. **PistonCore side:** type-discovery (§3) + the `/test-devices` control panel
   (§4) driving it all; then teardown (§8.6).
5. **Install helper + docs** — offer-to-install (§5.4) and a short standalone
   README so the community can use the fork on its own.

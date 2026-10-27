# Virtual Test Devices for Home Assistant

Virtual devices for testing Home Assistant automations — including **clones of
your real devices** that report the same abilities, so you can try an automation
against a stand-in instead of the real thing.

Works entirely on its own from Home Assistant's own **Developer tools → Actions**.
It is also the test bench for
[PistonCore](https://github.com/jercoates/pistoncore-v2), which is what it was
built for — but nothing here needs PistonCore installed.

> [!IMPORTANT]
> This is a fork of [twrecked/hass-virtual](https://github.com/twrecked/hass-virtual)
> and **uses the same `virtual` domain**, so it installs to the same folder.
> Install this **or** hass-virtual, not both.

---

## What it adds over hass-virtual

**More device kinds.** Upstream covers binary_sensor, sensor, switch, light,
lock, fan, cover, valve, number and device_tracker. This fork adds
`alarm_control_panel`, `camera`, `climate`, `media_player`, `notify`,
`siren`, `humidifier`, `vacuum`, `button`, `event`, `select` and `text`.

**Devices that state their real abilities.** Every platform accepts Home
Assistant's `supported_features` plus the mode lists and limits that go with it,
instead of hardcoding one shape per domain. A virtual thermostat can be a
cool-only single-setpoint unit or a full heat/cool-range one with fan and preset
menus, because that is what you told it to be.

**Cloning a real device** (`virtual.clone_device`). Point it at a device you own
and it creates a test copy reporting the same abilities — mode lists, limits,
feature flags. The list of what gets copied comes from Home Assistant's own
definition of capability attributes, not from guesswork, so it keeps up as HA
adds them.

A real notifier does not say whether it stands for a **push** or a **text**, so
a copy would not either. Choose **Receives notifications as** when you clone to
label the copy's notifier one or the other, so an automation that sends a push or
a text finds it. A phone running the Home Assistant companion app gets a push
notifier automatically (its push is a service, not something that can be copied).
A UI built on this integration — PistonCore's Test Devices page is one — can also
ask for a notifier to be *added* to a device that has none; that is a setting for
UIs and is not offered on Home Assistant's Actions screen.

**Devices that say what they are.** In the devices file a device can be written
as `Name: {name, manufacturer, model, sw_version, area, entities: [...]}` as well
as the original `Name: [entities]`, so its device page reads like the real one,
and an entity can carry an `entity_id` of its own and keeps exactly that id.

**Describing a device without creating it** (`virtual.describe_device`) returns
that same specification as data — useful for putting "here is what my device
looks like" into a bug report so somebody else can rebuild it.

> [!NOTE]
> `describe_device` returns your **real device and entity names**. Nothing is
> sent anywhere — this integration makes no network requests of any kind, so the
> only way that leaves your system is if you paste it somewhere. Give it a read
> before putting it in a public issue. (PistonCore replaces names with stand-ins
> automatically in the reports it builds; this integration on its own does not.)

**A camera that hands over a real picture.** Home Assistant's own snapshot
action does the work — it asks the camera for an image and writes the file — so a
snapshot lands as a real file at a real path, under HA's normal rules about where
it may write. An automation asking for a snapshot somewhere HA won't write fails
here exactly as it would on real hardware. The picture changes every time it is
asked, so two snapshots look different and you can tell an automation fired twice
rather than once.

**A notifier that records what was sent.** Home Assistant ships with almost
nowhere to send a notification — a dashboard pop-up, and that is all; everything
else arrives when you install a phone app, an SMS service or email. That makes
notification automations awkward to test. Send to a virtual notifier instead and
the message, the title and a running count appear on the entity, visible in
Developer tools → States or by clicking it on a dashboard. It also fires a
`virtual_notify_sent` event, so notifications can be watched arriving live in
Developer tools → Events. The count is the useful part: it shows an automation
firing twice when it should have fired once, which the message alone cannot.

**Standing in for another Home Assistant** (`virtual.export_devices`). Run it on
your real Home Assistant and it writes one file describing your devices and
entities. Load that file as a group on a test Home Assistant and every entity
appears there under the **same entity id** with its real state as the starting
state, so an automation you copy across runs unchanged against stand-ins. The two
Home Assistants are connected by nothing but the file.

1. **On the real Home Assistant**, install this integration and add
   ```yaml
   virtual:
     export_only: true
   ```
   to `configuration.yaml`, then restart. In this mode the integration imports
   nothing and refuses to add new groups, so on a Home Assistant with no groups
   the only thing it provides is the export action: no entities, nothing that can
   add test devices to your real home. (A group that is already set up keeps
   running.)
2. **Developer tools → Actions → "Export devices as stand-ins"**. It only reads,
   and writes `virtual_export.yaml` in your config folder. You can leave out
   devices, entities or whole integrations (for example the devices a network
   integration names after MAC addresses).
3. **Copy the file** to the test Home Assistant's config folder, then add a
   *Virtual Test Devices* group there (Settings → Devices & services → Add
   integration) pointing at that file.
4. **To refresh**, export again, copy the file over, and reload the group.
   Devices you add by hand should live in a **different group**, so a re-import
   only replaces the imported one.

The file keeps your **real device and entity names and ids**. That is what makes a
stand-in a stand-in, so read it before sharing it anywhere. Lock and alarm codes
and text-field passwords are never copied, and this integration makes no network
requests of any kind. It copies **shape and starting state, not behaviour**: a
device that reaches your real Home Assistant through a bridge keeps the shape the
bridge gives it, and what it would look like if added natively is not something an
export can show.

A **select** (a setting with a fixed menu) and a **text** (a free-text setting)
are reproduced too, since real devices expose a lot of both.

### What cloning will and will not do

It reproduces **shape, not behaviour**: what a device *says it can do*, not how
its own integration handles values. A capability or shape bug is reproducible on
a clone. A bug in how some bridge mangles a value on the way through is not, and
no amount of attribute copying will change that.

It also **never copies lock or alarm codes**. Bridged panels and locks expose
user code tables — sometimes plaintext PINs with the names attached — and sticking
to Home Assistant's capability attributes keeps all of it out. That matters if you
share a clone in a bug report, and it is guarded by a test: feeding the capture a
real bridged lock and alarm panel and asserting no code, name or PIN survives.

Nothing this integration produces ever leaves your Home Assistant on its own. It
makes **no network requests at all** — no telemetry, no analytics, no calls home.
Clones are written to a file in your own config folder and nowhere else.

---

## Fixes carried over upstream

Three bugs that each caused **silent** data loss, all found and fixed here:

- **Concurrent creates lost devices.** `create_device` / `remove_device` did
  read-modify-write on one file then reloaded. Fired together, every caller read
  before any caller wrote — six concurrent creates produced one device and
  reported success. Now serialised, with a burst collapsing to a single reload.
- **A failed save destroyed the device file.** The savers opened the real file in
  write mode (truncating it) and only then serialised, swallowing failures at
  debug level. One value yaml couldn't represent emptied the file, wiped every
  device, and left the integration unable to load — with nothing in the log.
  Now: serialise first, write via a temp file, replace atomically, and log loudly.
- **`lock.open` never worked.** It called a stub that always raised.

---

## Install

Add this repository to HACS as a custom repository (type: Integration), install,
and restart Home Assistant. Then add **Virtual Test Devices** from
Settings → Devices & Services → Add Integration.

## Usage

Everything is a normal Home Assistant action, so it all works from
**Developer tools → Actions** with no other software:

| action | what it does |
|---|---|
| `virtual.clone_device` | make a test copy of a real device, abilities included |
| `virtual.describe_device` | return that copy's specification without creating it |
| `virtual.create_device` | create a device from an explicit list of entities |
| `virtual.remove_device` | remove one |
| `virtual.set` | set a sensor's value |
| `virtual.set_available` | mark a device available or unavailable — the field is `value: true/false`, **not** `available:` |
| `virtual.fire_event` | fire a button / scene event |
| `virtual.turn_on` / `turn_off` / `toggle` / `move` | drive a device directly |

Per-platform configuration options are documented in
**[UPSTREAM_README.md](UPSTREAM_README.md)** — upstream's documentation, kept
because it is still accurate for everything it covers.

## Tests

`tests/` guards the three data-loss bugs above and the cloning rules. See
[tests/README.md](tests/README.md) — they run inside a Home Assistant container
and need nothing beyond HA and pytest.

## Credit and licence

A fork of [twrecked/hass-virtual](https://github.com/twrecked/hass-virtual) by
**@twrecked**, whose work this is built on. GPL-3.0, unchanged — see
[LICENSE](LICENSE). Upstream copyright headers are intact.

The idea of **exporting a real Home Assistant as stand-ins**, and several of the
problems that come with it (entities keeping their real ids, devices carrying their
maker, model and area, the `select` and `text` platforms, an export-only mode, and
removing one entity without removing its device), came from
[DevLn](https://github.com/DevLn)'s fork of this project, on the
[`ha-test-sim` branch](https://github.com/DevLn/ha-virtual-test-devices/tree/ha-test-sim).
The code in this repository was written separately, but that fork found the traps
first, and this work would have been slower and riskier without it. Thank you.

Please report problems with **this fork** here rather than upstream.

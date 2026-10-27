# PistonCore Test Devices — fork provenance

This folder is a **fork of [`twrecked/hass-virtual`](https://github.com/twrecked/hass-virtual)**
(GPL-3.0), the base for PistonCore's **test devices** feature. See
`../VIRTUAL_DEVICES_SPEC.md` for the why and the plan.

## Upstream snapshot

- **Source:** https://github.com/twrecked/hass-virtual
- **Forked at commit:** `a056ceaf73d4907e258ae055c3541342a3275400` (2026-03-06)
- **Upstream version:** 0.9.4 — domain `virtual`, `config_flow: true`, `iot_class: local_push`
- **License:** GPL-3.0 (unchanged; matches PistonCore). Upstream copyright headers kept.
- Vendored: `LICENSE`, `README.md`, `info.md`, `hacs.json`, `custom_components/virtual/`.
  (Skipped upstream `images/`, `install/`, `changelog/` — not needed to run.)

## What upstream already gives us (verified from source, 2026-07-21)

- **10 platforms:** binary_sensor, sensor, switch, light, lock, fan, cover, valve,
  number, device_tracker.
- **Grouped multi-entity devices** (a device with several entities under one
  device-registry entry — the shape PistonCore's picker needs).
- **GUI config flow** (`config_flow.py`) — the standalone create/remove surface
  (VIRTUAL_DEVICES_SPEC §5.6: standalone self-sufficiency).
- **Set-state services:** `virtual.turn_on / turn_off / toggle / set / set_available / move`.

## What PistonCore adds on this fork (see VIRTUAL_DEVICES_SPEC §5.2)

- **Missing platforms** the compiler targets: `alarm_control_panel`, `climate`,
  `media_player`, `siren`, `humidifier`, `vacuum`, `button` (camera only if a corpus
  piston needs it).
- **Live create/remove an outside app can trigger** (PistonCore drives it without
  hand-YAML), routed through HA-native config-flow/services so standalone users get it too.
- **`virtual.clone_device` — cloning lives HERE, not in the caller (2026-07-31).**
  New `clone.py`. Reads a real device and creates a test copy reporting the same
  abilities. It belongs in this repo because the platforms validate against CLOSED
  schemas: the capture list and those schemas are one contract, and splitting them
  across two projects guarantees drift. PistonCore now only names a device. The
  service takes a `device` selector, so HA's own Actions screen gives standalone
  users a searchable picker with no frontend to maintain.
- **Entity names within a group must be unique (2026-07-31).** Identity is keyed by
  entity NAME within the group, so two devices with an identically-named entity
  re-register on every restart — one device cloned twice grew the entity registry
  by five entities per boot, forever, silently. `clone.py` therefore names entities
  `<device name> <capability>`.
- **Two data-loss bugs fixed in `cfg.py` (2026-07-31) — these are upstream, and
  they destroyed every test device on the bench before being found.**
  `_async_save_yaml`/`_async_save_json` opened the real file in `'w'` (which
  TRUNCATES IT TO ZERO) and only *then* serialized. Anything yaml couldn't
  represent therefore wiped the file, and the exception was swallowed at DEBUG
  level so nothing reported it. The integration then refused to load at all,
  because `_load_user_data` called `.get` on the `None` an empty file parses to.
  Now: serialize first, write to a temp file and `os.replace` it into place, log
  failures at ERROR and re-raise; and `_load_user_data` degrades to "no devices"
  rather than taking the integration down. Worth carrying upstream.
- **Concurrency: `create_device`/`remove_device` were racing.** Both did
  read-modify-write on one yaml file then reloaded the config entry. Fired
  concurrently, every caller loaded before any caller saved, so all but the last
  were silently erased — six concurrent creates produced one device and no error.
  `pistoncore_manage._mutate_and_reload` now serializes the file edit per entry
  and coalesces a burst into a single reload (measured: 8 concurrent creates cost
  the same one reload as 1).
- **Full-fidelity cloning (2026-07-31, VIRTUAL_DEVICES_SPEC §5.7a).** Every
  platform now accepts the abilities a real device advertises — `supported_features`
  verbatim, plus its mode menus and limits — instead of hardcoding one shape per
  domain. Shared helpers live in `entity.py` (`FEATURES_SCHEMA`, `feature_flags`,
  `optional_list`); each platform names its own list/range keys. **Every key is
  optional and falls back to the platform's previous hardcoded default**, so
  upstream behaviour and existing `virtual.yaml` files are unchanged.
  Touches upstream files (light, fan, cover, lock, sensor, number) as well as the
  PistonCore-added ones — keep that in mind on an upstream rebase; the changes are
  confined to the schema block and `__init__`, plus new `async_*` handlers.
  Two upstream bugs fixed in passing: `lock.open` called a sync stub and always
  raised, and cloning any device containing a `number` entity could never succeed
  because that platform requires min/max.

## Device tracker: migrated off `location_name` (2026-08-02)

HA deprecated `TrackerEntity.location_name` (removal 2027.7). Migrated NOW rather
than at the deadline, because the integration had been public for one day and
nobody depended on the old behaviour — waiting would only have meant doing it
when the person who understood it might be gone.

**This is a deliberate behaviour change, not a rename.** `location_name` returned
free text that HA used as the state verbatim, so a virtual tracker could report
`school` with no such zone anywhere. The replacement, `in_zones`, takes zone
entity_ids and HA discards zones that do not exist — so the state can now only be
`home`, `not_home`, or the name of a real zone.

Taken on purpose: a REAL device tracker can only report those things, so a
virtual one inventing states your actual devices can never produce is a worse
bench. A location naming no existing zone now reports `not_home` **and logs a
warning saying so** — silently reporting the wrong thing is what a test bench
must never do.

VERIFIED on 2026.8.0b3: `home` -> `home`, capitalisation handled, unknown zone ->
`not_home` + warning, `not_home` explicit, GPS outside a zone -> `not_home` with
coordinates intact, GPS inside the home zone -> `home`, and the state survives a
restart. Upstream had not migrated this as of 2026-08-02.

## Cloning a device so it can receive a push or a text (2026-10-26, 0.14.0)

A real notifier carries no label saying whether it stands for a push or a text,
so a clone used to come back "generic" and a piston's "send a push" / "send a
text" — which finds its destination by that label — had nothing to land on.

**`virtual.clone_device` takes `notify_as`: `app` (push) or `sms` (text).** It
labels the notifier(s) the source device already has. That is the whole of what
the standalone Actions screen offers.

**Adding a notifier to a device that has none is a UI decision, not an Actions
screen feature.** It is behind `add_notifier: true`, which is accepted by the
schema but deliberately NOT listed in `services.yaml`, so Home Assistant's own
Actions screen never offers it. The reason is bridge-specific: a phone that
arrives through Hubitat looks like a handful of sensors, so no rule inside this
integration can tell it should have a notifier. A UI knows more (PistonCore's Test
Devices page shows a "Notifies as" choice and passes both settings; a future UI
for this add-on would decide when to offer it the same way). This is a
convenience, not a lock: anyone with a Home Assistant token can pass the setting.
`describe_device` accepts the same two, so a preview matches its clone.

**One automatic case, kept on purpose:** a device owned by the `mobile_app`
integration (the companion app) always gets a push notifier, because its push is
a notify SERVICE rather than an entity, so there is nothing to copy. That is
decided by which integration owns the device — a fact, not a guess — and
`notify_as: sms` overrides it.

- An ordinary device with no choice gets nothing, and a device with no notifier
  that is given `notify_as` alone also gets nothing (logged), so the label can
  never silently create entities. Both are tested as controls.
- The added notifier's name goes through the same de-duplicator as every other
  entity, so a source entity already called "Notification" is not duplicated.
- `notify_as` labels EVERY notifier the source has; a device with several real
  notifiers gets them all the same label. Choosing "push" says the device
  notifies as push, so this follows from the choice.
- An unknown or missing device is a plain `ServiceValidationError` (a polite
  refusal) rather than a server error.
- Not done: the legacy `notify.mobile_app_<phone>` SERVICE is not recreated. A
  piston that calls that service directly still cannot reach a clone; the push /
  text path through notify entities (what PistonCore's vocab sends) does.

## Standing in for another Home Assistant (2026-10-26, 0.14.0)

THE IDEA AND ITS HARD PROBLEMS CAME FROM `DevLn/ha-virtual-test-devices` (branch
`ha-test-sim`), a fork of this repo. Nothing was copied: this was written fresh
around this fork's own rules, but its notes are the reason several traps below were
known in advance. It is worth reading beside this.

**The use case (Jeremy):** clone the real, main Home Assistant out, so a test bench
holds stand-ins for exactly what it WILL run, add things by hand to the test side to
delete later, and see how the devices come up as if the main Home Assistant were the
controlling hub. Bridges (a Hubitat hub, say) behave differently from native
integrations, so the bench needs the real shapes without adopting anything native.

**`virtual.export_devices`** (`export.py`) writes a devices file from the live
registries: every reproducible entity under its REAL entity id, with its real name,
its capture from `clone.entity_spec` (the SAME routine `clone_device` uses, so the
two cannot disagree about what a copy carries), its entity category, and its state
as the starting state (unavailable becomes `initial_availability: false`; unknown
gives nothing; button, camera, event and notify give nothing; a light also keeps
brightness, colour and effect, but not colour temperature, which the light platform
reads as kelvin but validates as a byte). Devices carry name, maker, model, version
and area. Every entry is validated against the target platform's OWN closed schema
before it is written; a rejected entry goes to the report, never the file, so the
file always loads. Skips are accounted for: each individual decision, and one line
per non-reproducible domain (a real Home Assistant has hundreds of automations).
Defaults leave out hassio, backup, sun, hacs and virtual, because a test Home
Assistant has its own and exporting them only makes `_2` copies (ASSUMED reasoning,
not measured on every setup). It writes atomically, to the config folder or an
`allowlist_external_dirs` path only: Home Assistant's own `is_allowed_path` does not
cover the config folder itself, so checking it alone refuses the default file.

**Real names and ids are kept on purpose, with no warnings or switches in this
integration** (Jeremy: PistonCore builds its own reports and owns data safety; this
is the standalone side). It makes no network requests. Lock and alarm codes and
text-field passwords are never copied, and that is tested. PistonCore does NOT call
this action and is not linked to it: nothing in `shim/` references it. The add-on
cannot enforce that against a caller with a Home Assistant token, so it is a
convention kept by PistonCore, not a lock.

**`virtual: {export_only: true}`** in `configuration.yaml` stops the integration
creating or importing anything of its own: no YAML import, no new group (the config
flow aborts). On a Home Assistant with no groups that leaves the export action as the
ONLY thing it provides. A group that is ALREADY set up keeps running: an earlier
version made existing groups fail with a setup error, which punished the very home
that had one. The action is registered in `async_setup`, not per group, because a
Home Assistant that only exports has no group to hang it on.
Its platform schemas are loaded in the executor only when an export is run: importing
the platform modules at startup woke Home Assistant's own camera code on the event
loop (found on a real run, as "blocking call" warnings).

**What the loader gained, which is the risky half:**
- An entry may name its own `entity_id` and then keeps exactly that. Its `unique_id`
  is DERIVED from the id (`<entity_id>.virtual`), never random, so a regenerated
  file maps onto the same registry rows. Such entries need no meta row. A wrong
  domain or a repeated id is logged at ERROR and skipped, the first keeps a contested
  id, capitals are lowered with a warning. If Home Assistant gives a stand-in a
  different id, that is logged as a WARNING (something already has the id, or it
  was renamed in the UI), but only for entities whose id came from the file: an
  ordinary entity renamed in the UI must not be reported on every restart.
- A device may be a mapping with `name`, `manufacturer`, `model`, `sw_version`,
  `area` and `entities`. The shorthand list still works. `area` only applies when
  the device is first created (Home Assistant's rule for a suggested area). MAC
  address and configuration URL are deliberately NOT exported: a shared MAC can merge
  a stand-in into a real device, and a URL can be a local address.
- `entity_category` on every platform, so a stand-in sits in the same section.
- The entity passes ONLY `identifiers` to the device registry now. It used to repeat
  maker and model, which would write the constants back over the file's values.
- **Orphan removal was rewritten.** It used to delete the orphan's whole DEVICE,
  taking its surviving entities with it and recreating the device under a new id.
  Now the file is the source of truth: an entity row whose unique id the file no
  longer lists is removed one at a time, and a device goes only when the file no
  longer lists it. This also clears a stand-in dropped from a re-exported file.
  **It only acts on a file it can believe.** A file that is blank, does not parse or
  is not a mapping reads as "lists nothing", and a copy still being written looks
  exactly like that; and a regenerated file with a typo has an entry rejected. Acting
  on either would delete real registry rows (history, area) for entities that were
  never meant to go, so cleanup is skipped, with a warning, until the file is fixed
  (`BlendedCfg.trusted`). A file that says `devices: {}` IS believed, so removing the
  last device still cleans up. Verified live: a blanked file kept all rows and they
  came back under the same ids; a typo kept its row until fixed.
- `__version__` is read from `manifest.json` (it had drifted to 0.9.4), so there is
  one place to change the version.

**`select` and `text` platforms** (`select.py`, `text.py`). HA's TextEntity raises
when its value breaks its own limits, so a starting or restored value that does not
fit becomes "no value" with a warning; a select value off its menu falls back to the
first option; a `password` text keeps no value at all.

**Hand-made devices go in a DIFFERENT group** from an imported file, so a re-import
only replaces the imported group.

**Measured (2026-10-26, Home Assistant 2026.10.4, two throwaway instances):** the
demo integration's 123 entities exported as 82 entities in 78 devices (the rest are domains
that cannot be reproduced, plus the default exclusions) and all 82 loaded on a second
Home Assistant with the same ids and names. States matched except where the source
moved on after the export (the demo's energy sensors), a password text (by design) and
cameras (the virtual camera is idle where the demo's is streaming). Three restarts
changed nothing (82 rows, none unavailable). A re-imported file that dropped a device
and an entity, renamed one, and added broken entries removed exactly what was
dropped, kept a dropped entity's siblings and device, skipped the broken entries with
a clear message each, and left a separate hand-made group alone.

**Known fidelity limits found while doing this (existing platform behaviour, not new,
and not fixed here):** a valve always advertises open, close, stop and set-position
whatever the original did; a media player deliberately masks browse and search; a
virtual camera has no stream.

## Tests (added 2026-08-01)

`tests/` guards the three silent-data-loss bugs fixed in this fork — the mutation
race, the truncate-before-serialize save, and a clone dropping abilities. Run them
inside an HA container (`tests/README.md`); 37 pass, no `pytest-asyncio` needed.

**Tamper-verified**, and that mattered: the first version of the suite passed
every deliberate break, because `docker exec` silently discards stdin without
`-i`, so the tampering never ran. A suite nobody has watched fail is not evidence.

**Backward compatibility is covered by design, not by luck**: every cloning key is
optional and falls back to the platform's original hardcoded default. VERIFIED
2026-08-01 against a hand-written upstream-style `virtual.yaml` — 8/8 devices
behaved identically, including the light and fan paths this fork rewrote most
(`support_color: true` still gives hs mode; `speed: true` still gives 3 speeds).

## Rules

- **Standalone self-sufficiency is REQUIRED** (§5.6): everything works from HA's own
  UI/services with no PistonCore. PistonCore's `/test-devices` panel is a convenience
  layer, never the only control surface.
- Keep it rebase-friendly: prefer ADDING files (new platform modules) over rewriting
  upstream ones, so pulling upstream fixes stays easy.
- **Split to its own repo at release** (§5.5); in-repo folder is for iteration now.

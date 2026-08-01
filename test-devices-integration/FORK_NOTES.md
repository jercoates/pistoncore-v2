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

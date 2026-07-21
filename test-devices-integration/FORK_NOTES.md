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

## Rules

- **Standalone self-sufficiency is REQUIRED** (§5.6): everything works from HA's own
  UI/services with no PistonCore. PistonCore's `/test-devices` panel is a convenience
  layer, never the only control surface.
- Keep it rebase-friendly: prefer ADDING files (new platform modules) over rewriting
  upstream ones, so pulling upstream fixes stays easy.
- **Split to its own repo at release** (§5.5); in-repo folder is for iteration now.

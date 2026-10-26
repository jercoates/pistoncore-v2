# ENGINE DIRECTION — DRAFT

**DRAFT for Jeremy's review.** Direction from the chat of 2026-10-25. Nothing here is
a ruling until Jeremy adds it to HARD_RULES with a date. Until then, HARD_RULES §3 and
§4 still name PyScript as the fallback band, and sessions will follow them.

---

## 1. THE DIRECTION

- **YAML first, unchanged.** Clean pistons still compile to native HA YAML. That is
  what most HA users want, and it outlives PistonCore.
- **PyScript is dropped.** It has been a constant source of trouble, and it's a
  community integration that could stop being maintained (§3's own worry).
- **PistonCore's own engine becomes the fallback**, the "just works" band. Anything
  that doesn't compile cleanly to YAML runs on the engine.
- **The engine runs webCoRE's semantics directly**, ported from the Hubitat groovy.
  It doesn't translate intent into HA idioms; it does what webCoRE does. So
  cancellation policy, waits in loops, persistent variables and trace behave the same
  as webCoRE.
- **Jeremy will run his own pistons on the engine.** YAML output stays available for
  users who want native automations.
- The piston JSON stays law. The editor doesn't change.

## 2. STEP 0 — PULL THE LATEST webCoRE BEFORE PORTING ANYTHING

The repo's reference copy is not current. In
`reference/webCoRE-hubitat-patches-extracted/` the newest Hubitat build is
`v0.3.114.20240115_HE` (package manager `1.0.99`), and the vendored dashboard is
`v0.3.114.20220203`. Jeremy knows of **at least two releases since.**

Before the engine port starts:
1. Pull the current release from the same upstream that folder came from.
2. Diff the piston engine (`webcore-piston.groovy`) and the parent app between the
   vendored copy and the new one, and report what changed **in plain English**.
   Changes to execution semantics, the piston JSON, or the dashboard API are the ones
   that matter.
3. If the dashboard changed, update the sealed `dashboard/` as a deliberate, approved
   step. That's a sealed folder, so it needs Jeremy's explicit go-ahead.
4. Record the version the engine was ported from, so later updates can be diffed the
   same way.

## 3. ENGINE DESIGN RULES (set now, so they aren't retrofitted)

**Read on demand, subscribe only to triggers.** HA keeps every state in memory, so
reading a device is a free lookup, done only when a statement needs it. Subscribe
per entity, only to the devices a piston actually triggers on. Never listen to every
state change and filter. This is Jeremy's "don't pull every device every run" change
to webCoRE. For bridged Hubitat devices it also means zero polling of the hub; only
commands go back.

**One engine, two adapters.** All engine logic talks to HA through one thin layer:
- **Integration adapter:** runs inside HA as a custom integration, calling `hass`
  directly. Works on every install type, including HA Container.
- **Websocket adapter:** runs inside the PistonCore Docker container for locked-down
  setups that can't add custom integrations. Same calls, over the websocket.

Same engine logic on top of either. The locked-down case becomes a second adapter,
not a second engine.

**Survive restarts.** Pending waits and timers live in the engine's own storage, not
in memory. The websocket adapter reconnects and resyncs on HA's startup. (The
integration adapter gets this mostly for free, since it starts and stops with HA.)

**Nothing that tracks HA is hard-coded (§8).** The engine reuses the existing vocab
and templates for service names, attributes and value formats. The HA-churn surface
stays exactly where it is today.

## 4. PACKAGING

- **Editor/compiler:** an add-on for HA OS/Supervised (Jeremy's goal for himself), and
  Docker for HA Container.
- **Engine:** a custom integration installed through HACS, like the test-devices fork.
  In locked-down Docker setups, it runs inside the PistonCore container instead.
- With PistonCore and HA Docker on the same machine, the websocket is local, so
  latency and load aren't an issue. Restart handling is the only real concern.

## 5. FIRST MILESTONE

Pick **one corpus piston that falls back today.** Run it end to end on a minimal engine
on the bench, through the editor, with the same three-part test (§17): it compiles, it
doesn't error, it matches intent. This proves the shape before committing to the full
port.

## 6. RULES THAT WOULD CHANGE IF THIS IS ADOPTED

For Jeremy to rewrite when he decides, not before:
- **§3** "YAML first, PyScript only when there is no other way": PyScript becomes the
  PistonCore engine.
- **§4** "PyScript-only is a deliberate user feature": becomes "engine-only", the same
  guarantee (it must run anything).
- **"Never needs PistonCore running"**: no longer holds for engine-band pistons. That's
  the same trade already accepted for share-path media (SHIM_API_SPEC §10.3), and it
  should be stated to users the same way.

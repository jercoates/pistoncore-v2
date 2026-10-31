# For Albert — field notes on webCoRE, Home Assistant and the Hubitat bridge

Written 2026-10-30 by Claude at Jeremy's request. It is for Albert's engine (a real
webCoRE engine), so it leaves out how PistonCore compiles to YAML and the repo's own
internals, which his agents have already read. It holds what was learned by running
things against real Home Assistant and real Hubitat devices, most of it never written
into the repo.

Every note carries the date it was found. Home Assistant and the integrations change,
so treat them as leads to re-check. Anything marked UNVERIFIED was not confirmed.
No addresses, tokens or machine names are included; the repo is public.

---

## 1. How the same device looks different depending on the route into HA

- **The shape depends on who wrote the integration, not on bridged vs native.**
  (2026-07-29, same hardware both ways, verified live.)
  - A YoLink freezer through the Hubitat bridge shows about **33 attributes**: alarm
    limits, corrections, battery type, signal, online and so on. The official HA
    YoLink integration shows **2**: temperature and humidity.
    The Hubitat driver was written by a friend of Jeremy's who passes everything
    through. The HA integration is opinionated. (That it talks to YoLink's cloud
    instead of the LAN is UNVERIFIED.)
  - A UniFi Protect camera is the opposite. Through the bridge there is no camera
    entity and no snapshot, only one smart-detect sensor whose value is
    person/vehicle. Natively there is a camera entity per stream quality, a snapshot
    action, a separate binary sensor per object type, and PTZ actions.
  - So any rule of the form "bridged devices need X, native need Y" is wrong on one of
    these two. Read what each device actually reports.
- Pistons written against one shape don't port to the other, in either direction.
- **The bridge is read-mostly.** On one install, 1178 of 1357 entities were bridged,
  and 94% of those were sensors or binary sensors. The same install had only a few
  dozen lights and switches, 2 locks and 0 cameras coming through it. (2026-07-27.)
- A viewport/camera view is read-only sensors when bridged and a writable `select`
  when native. (2026-09-04.)

## 2. The Hubitat bridge as a hazard

- **A bridged device is the real device, wherever it appears.** Seeing it in the
  entity list of a test machine does not make it a test device. A fabricated copy
  (a virtual clone) is connected to nothing and is free to drive; a bridged entity
  is not. (2026-08-28.)
- **Bridged state on a test machine is a stale mirror**, frozen at the integration's
  load time. It can't tell you whether you moved the real thing. The hub's own event
  log is the authority and is free to read.
- **Nearly lost a house alarm twice (2026-08-28).** A test piston touched an alarm
  panel entity (platform: hubitat). Only the devices to be driven had been checked, so
  firing the trigger armed the real house. Fix: before any deploy, print the platform of
  EVERY entity in the compiled output, not just the ones you plan to drive.
- **A test machine can hurt the hub.** A Docker test instance on localhost can't be
  reached from the hub. Subscribing it to Maker API events leaves the hub holding
  deliveries that never complete: **137 pending requests** logged 2026-09-08, and the
  app had to be paused by hand. Stopping the container does not unregister it.
  Clones give the same device shapes without touching the hub.
- Hubitat is the automation hub and stays that way. A bridge is test scaffolding for
  the developer, not the path a real migrating user takes; they move devices to HA's
  own integrations. Anything that works only through the bridge serves the developer.
- Hubitat attribute names are recoverable from the bridge's unique_id. On the
  bench it split on `::` into four parts: `hub::device::sensor::attrName`. That is how
  the original name (for example `jobState`) can be found again. Clones and exports
  lose it, because the new entity has a different unique_id. UNVERIFIED across other
  bridge versions.

## 3. Attribute naming problems seen in practice

- A cloned dishwasher exposes its job state as `job_state`, not `jobState`. A piston
  written against `jobState` never fires from the clone, and the compiler wrote
  placeholder entities instead. (2026-10-26.) One sample suggested the nearest HA
  concept is `progress` on the dishwasher entity. Only one sample, so UNVERIFIED.
- With a hybrid attribute feed, about **50% of attributes arrive raw** (759 of 1500 on
  one install; 67% on a dev bench), including things like `DeviceWatch-DeviceStatus`,
  `LQI`, `BSSID`. The curated mapping adds the webCoRE name and type. It adds no access.
  A piston asking for `level` won't bind to an attribute offered as `brightness`.
- Command names are claimed by the device, not by webCoRE. `setDirection` could be a fan
  reversing or an LED strip cycling a sequence. One webCoRE command mapping to several
  HA domains is normal. Don't conclude ownership from where a definition sits in a file.

## 4. How webCoRE behaves, found by reading its source and the editor

(All VERIFIED in the sealed dashboard or `webcore.groovy` unless noted.)

- **Missing device:** piston JSON stores hashed device ids. The editor resolves each hash
  to a friendly name against the live device list. A deleted device has no entry, so the
  editor shows the raw hash and carries on. Editing and saving that statement clears it.
  It is not an error, and an engine shouldn't treat it as one.
- **Custom (driver) commands:** a command in a device's `c` list that isn't in the
  built-in physical commands is flagged `cm: true` and the designer id gets `$custom`.
  It renders as a function call, `name(param1, param2)`, and `cm` is saved in the
  piston JSON. That is why a piston shows `clearImages();`.
  - **Trap:** `cm` does not mean "not a webCoRE command". webCoRE sets it whenever the
    command came from the device's advertised list, which on Hubitat includes commands
    its own dictionary also knows (`playText` carried `cm: true`). The test used on the
    HA side was `cm` AND a dot in the name (an HA service name like `light.turn_on`).
- **How Hubitat feeds the picker** (`getDevDetails`, webcore.groovy ~3604):
  1. every command the device supports is sent, deduped by name, with no filtering;
  2. parameters come from the driver's own metadata (name, type, constraints), where a
     `*` prefix on the name means mandatory;
  3. the only override table has two entries (`push` to `pushMomentary`, `flash` to
     `flashNative`), there only to rename driver commands that collide with built-ins.
- **Task parameters are saved positionally** (`p: [operand, operand]`, no names). That is
  safe while the list is frozen, as with webCoRE's vocabulary. It is unsafe when the list
  comes live from Home Assistant, because HA can add or reorder fields and a value lands
  in the wrong field with no error. The fix chosen was a per-service record of the field
  order at save time, read back at compile. Storing names inside the task was rejected
  because it adds a field webCoRE doesn't have.
- A big piston saved in one request got a bare `400 Invalid HTTP request` and looked like
  a refusal. The editor sends large pistons in chunks; anything else importing must too.
  Also, a failed save left an empty named shell in the piston list.

## 5. What Home Assistant does that surprises webCoRE people

- **HA silently disables automations at setup.** Four lux-gated night lights reported
  "deployed, no message" and HA had switched all four off. Read liveness back from HA;
  the identity is the automation state's `attributes.id`, never the alias. (2026-08-21.)
- **A deploy can silently wipe other pistons' helper entities.**
- **Service names are per domain, not per entity.** HA's service list offered both fans
  `oscillate`, `set_direction` and `set_preset_mode`, though neither supports them.
  HA does declare the filter: a service's `target.entity[].supported_features` carries
  the required bitmask (`fan.oscillate` is 2, `fan.set_preset_mode` is 8,
  `siren.turn_on` is 1, `media_player.volume_set` is 4). Filtering by it on one real
  install cut 649 offered commands to 591 with none unsupported. VERIFIED live
  2026-07-27.
- **HA has far more than webCoRE's vocabulary.** On one install: 68 HA domains, webCoRE's
  vocabulary has words for 20, about 48 domains and 168 services it has no concept of
  (`ai_task`, `assist_satellite`, `conversation`, `lawn_mower`, `counter`, `number`,
  `date`/`datetime` and others). 43 of 174 devices had no usable commands at all
  before the service feed. 194 of 361 fed commands take no parameters.
- **Comparison edge cases:** a numeric trigger on `<=` or `>=` loses its equality edge if
  built from `below:`/`above:`; and an `else` branch never runs if only one direction
  of the threshold is watched. Resolving the intent HA-first fixed both: wake whenever
  the condition flips either way.
- **HA 2026.8 stops merging devices across config entries.** Tested 2026-08-02 on 2026.8.0b3
  with a real bench (30 devices / 45 entities): no entity lost; a device that had been
  merged across two entries split into two, each keeping its own entity. Non-destructive.
  Same-named devices in two virtual groups will split. Separately, overriding the
  deprecated `location_name` on a device tracker is flagged unsupported from 2027.7.
- **Orphaned entities become ghost devices.** A bench whose integrations were removed
  produced 2190 "restored" entities that became 2177 picker devices that could do
  nothing. A real user who removes an integration would see the same.
- **PyScript pistons create no automation entities.** A checker that looks for automation
  entities calls every PyScript piston "dead". That's the checker, not the piston.
- **Settings pages that save partial forms wipe the fields they weren't sent.**
  (Found 2026-10.)
- **Camera snapshots** land in HA's `/media` under a stable per-device filename that is
  overwritten each time. Nothing else gets a stable URL.
- A person's phone tied to Hubitat doesn't bring its push notifier along when cloned; on
  plain HA a real phone clones with its notifier.

## 6. Testing lessons that cost real time

- **A passing device test is not proof.** Test both directions. `cancelTasks` looked
  fine because the waiting automation shared the trigger that cancelled it, so the
  `mode: restart` threw the pending delay away as a side effect. Forcing it to queue
  exposed the bug instantly. A fix once "worked" only because the timer helper hadn't
  been created yet and the wait timed out. Check the prerequisites exist.
- **Deployed isn't verified.** Of 53 bindable pistons in a corpus run, 37 deployed; none
  of those counted until driven and judged against intent. Verified end to end: "motion
  plus dark turns on; off ~2 min after motion clears; motion returning cancels the
  turn-off". HA expressed that as `for: 00:02:00` instead of a running wait: same
  behaviour, different mechanism, which is a pass.
- **Synthetic data proves nothing about real behaviour.** A whole session reported
  numbers from the wrong code path because a feature flag wasn't set. Compare the same
  pistons, same real device map, same globals, committed code against working tree, and
  bisect back past commits made earlier in the same session.
- **Importing a piston by API skips the editor's remap step.** A harness that did so
  couldn't rebind devices named inline in a statement (28 of 154 corpus pistons do) and
  picking devices by attribute match picked wrong. Cloning the real device was better.
- **A fabricating test device** (the virtual add-on) can copy a real device's shape:
  attributes, services, capabilities. That makes device types the tester doesn't own
  testable, which is the point.

## 7. Behavioural gaps found between webCoRE and HA

- `ts` and `fs` (time stamps) silently dropped in one compile path (7 of 7 probes).
- 20 operators collided between two translation tables; one hand-copied operator table
  lost `is`/`is_not` and the guard that stops a numeric comparison firing when a sensor
  is unavailable, which would have raised a false low-battery alert for an offline
  sensor. Keep one operator table.
- Report-style pistons (build a sentence from many devices' states) are one shape: ask
  the set which members match, then add layers. Recognise the base, not whole patterns.
- A define-block value is compile-time in a compiler; Home Assistant never sees a
  variable. That doesn't apply to a real engine, which must handle them at runtime.
- Randomised daily times (`happens daily at {addMinutes('22:00', random(0,90))}`) are
  easy in an engine and awkward in HA automations.
- Pause/resume was solved by `automation.turn_off`/`turn_on` rather than by removing the
  file, which doesn't apply to a real engine.

## 8. Things Jeremy has said that shape any HA/webCoRE work

- Read intent from the piston JSON; resolve it in HA terms. "You keep thinking in webCoRE
  rules; it's HA that matters." Fidelity is behaviour, not mechanism.
- A user who migrates moves devices to HA natively. The bridge is the developer's bench.
- Don't build a repair wizard for missing devices; webCoRE already shows the hash.
- New findings are welcome; re-reporting something already ruled on is the failure mode.
- Document every divergence from webCoRE as a trade-off; never silently accept one.

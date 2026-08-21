# HANDOFF 2026-08-19 — intent compiler, the test loop, and the notify gap

Written before a compaction. Everything here is either NOT in git or is
operational knowledge that a summary destroys. Committed work is not repeated.

---

## 1. THE INTENT COMPILER — where it actually stands

**Behind `PISTONCORE_INTENT_EMIT=1`, default off. The transcoder is untouched
and stays byte-identical (NO DRIFT) through every change below.**

Corpus, both paths: **117 YAML / 32 PyScript / 5 errors** — the intent band now
MATCHES the transcoder exactly, and the remaining failures are the same on both.
It was 91/54/9 at the start of the session.

Two families closed it, and both were answerable with machinery that already
existed (see RESHAPE_LOG.md):

- **17 pistons — an inline `delay` node.** `_resolve_actions` rejected a delay
  node as INPUT even though the transcoder builds delay nodes as OUTPUT and
  `automation.yaml.j2` renders them. One passthrough branch.
- **10 pistons — an instantaneous comparison used as the wake** (`is`,
  `is_less_than`, `was`). `_promote` already subscribes to exactly those
  operators for condition-only pistons. `_PROMOTABLE_WAKE_OPS` lives beside
  `_promote` so the set cannot drift from the branches it describes.

**What the intent band still does NOT do:** it is only wired into the YAML
band. PyScript emits from `analyze`'s read and is not intent-driven at all.
`emit_intent.plan()` does not "decline" — it returns branches and emission
continues, so a failure surfaces downstream as an emission error, never as a
refusal. That cost hours of wrong diagnosis; do not go looking for refusals.

**RESHAPE_LOG.md is the discipline that made this work** — descriptive
observations, never "here is how to emit that". Its one rule exists because
`pattern_recovered.md` reads as law and describes a §3.0 layer that was never
built. 27 fallbacks collapsed to 2 signatures on the first pass, and the
signatures were already being raised as exception text and thrown away by the
routing decision.

---

## 2. THE TEST LOOP — this is the part that took all night to get working

**Do not rebuild a mapper. A previous handoff (2026-08-09) already documented
that the auto-mapper is the weak link and a human using the import picker is
the real answer. I re-derived that from scratch. Read that file first.**

Working loop, proven end to end:

1. deploy through PistonCore's own `compile_and_deploy` (never hand-write
   `automations.yaml` — that tests nothing)
2. **disable every other automation** (`automation.turn_off`) or a stale one
   shadows the test and looks exactly like a compiler regression
3. fire the real trigger with `virtual.turn_on` / `virtual.set`
4. read the outcome entity
5. re-trigger mid-wait to check the cancel policy

### Traps that cost hours, each measured

- **`virtual.yaml` in the config dir persists the device list.** Wiping
  `.storage` does NOT remove the devices; they come back on restart. Delete
  `virtual.yaml` too for a genuine clean slate.
- **Every `create_device` reloads the whole config entry.** 128 sequential
  creates orphaned ~10,000 registry rows (95% of the bench `unavailable`), and
  every capability match then landed on a corpse so deployments were inert.
  **Write all devices into `virtual.yaml` at once and restart ONCE.**
- **The twin specs from `/api/test-devices/discover` use bare capability names**
  — 108 are "Last Update Time", 50 are "Motion" — so they collide across
  devices. Prefix each with the device label.
- **Match capability PER BINDING, not per device.** A device with one live and
  one dead entity looked healthy, the dead entity got bound, and the automation
  deployed pointing at a row that can never change state. This is why only 4 of
  52 deployments were testable until it was fixed.
- **`ha_config_path` must be the HOST path of the bench bind mount**, not
  `/config`. PistonCore reported successful deploys while writing nowhere.
- Bench `/config` mount: `docker inspect -f '{{range .Mounts}}{{.Source}}{{end}}' pc-testha`
- **notify is a no-op on a bare bench** — `notify.notify` and even
  `notify.persistent_notification` accept the call and produce nothing
  observable. Four fully-live corpus automations are notify-only and cannot be
  verified until that is fixed.

### The one behaviour result so far — and it is correct

`12_Cave_motion_V2`, the shape 109 of 154 pistons use:

| test | expected | actual |
|---|---|---|
| motion while dark | light on | on |
| clears, 30/60/90s | stays on | on |
| ~120s after clearing | off | off at ~125s |
| **re-trigger during the wait** | **clock restarts** | on at +40/+80/+110s |
| ~120s after the SECOND clear | off | off at ~125s |

The re-trigger line is the real one: the original timer would have fired at
~+40s and did not. **webCoRE's TCP-restart semantics, reproduced in plain HA
YAML, no PyScript.**

---


### STAGING THE TESTS — the method that works (Jeremy, 2026-08-21)

Loading every clone at once does not work. Stage instead: group pistons by the
device SLOTS they need, load only that round's clones, run, tear down, repeat.
`batches.py` does the grouping -- 154 pistons become **35 rounds of ~10 clones**,
and round 1 alone covers 25 pistons with 9.

**THE `features` KEY IS WHY CLONES LOOKED BROKEN.** Clone specs from
`/api/test-devices/discover` carry `"features": 0`. The add-on's own
`create_device` service handles it; writing `virtual.yaml` by hand does not, and
the platform schema rejects it:

    Error while setting up virtual platform for light: extra keys not allowed @ data['features']

Every platform that uses it (light, fan, lock, media_player) then fails to set
up while sensor/binary_sensor/event load fine. That produced a bench of
thousands of read-only entities and NO controllable ones, which looked like a
scale limit, sent a whole session chasing a phantom compiler bug, and left
10,000 orphaned registry rows from reloading a config half of which never
validated. **Use the service, not the file.**

### WHAT MANUAL TRIGGERING CANNOT TEST

`automation.trigger` does not exercise a compiled piston. Every branch is gated
on `condition: trigger, id: stmtN`, and a hand-fired run carries no trigger id,
so no branch executes -- `skip_condition` skips the AUTOMATION-level conditions,
not the inner `if`. A time/sun-triggered piston therefore needs the real clock;
only state-triggered ones can be driven on demand. Plan rounds accordingly.

## 3. NOTIFY — diagnosed, NOT fixed

**PistonCore cannot see modern notify entities, and this is a product bug.**

- `extract_notify_target_services` (device_pipeline.py:780) builds picker
  devices ONLY from `notify.mobile_app_*` **services** — legacy per-target keys.
- `extract_notify_entities` (:760) does find `notify.*` entities but only feeds
  the email-notifier SETTING; it never becomes a device.

HA moved notify to an **entity platform**. A modern notifier is a `notify.*`
entity driven by `notify.send_message` with `entity_id`, and has **no service
key at all** — so it is invisible to the picker. Bench confirms: the notify
domain exposes exactly `['notify', 'persistent_notification', 'send_message']`.

**Fix direction (unstarted):** notify entities must become picker devices the
way `_build_notify_device` does for services, with the command resolving to
`notify.send_message` + `entity_id`. Reuse `_build_notify_device`'s binding
rather than adding a second path. The service name belongs in the vocab.

**Research still needed before writing it:** how HA's notify entity platform
actually behaves — what `send_message` takes, whether `title` survives, how a
notify entity differs from the legacy service in what it accepts. Do not guess
this from the word "notify"; that exact mistake (inferring `receives` from
English) cost real time this session.

---

## 4. UNCOMMITTED AT HANDOFF

`deploy.py`, `helpers.py`, `resolve.py` — the helper-loss guard (merge when the
compile record is incomplete, two rotating status backups, and a diff naming any
helper that vanished since the last deploy). Plus `COMPILER_DECISIONS_DEPLOY.md`
§3.5 and a `COMPILER_SPEC.md` cross-reference documenting it. Gates pass.

## 5. THE THREE REMAINING CORPUS FAILURES ARE NOT COMPILER BUGS

- `a46` — two conditions with **no comparison set**; `receives` appears zero
  times in webCoRE's source and Albert's own editor flags them invalid
- `a67` — `"active": false`, disabled in webCoRE
- `a75` — the test harness does not seed globals; the global is real

## 6. HOW I KEPT FAILING (worth more than the fixes)

- Reasoned about what the pipeline "must" do instead of reading it — three
  duplications in one night, one written into a docstring as a known limitation
- Rebuilt an auto-mapper a previous handoff had already ruled out
- Reported my own bad seed data as compiler bugs (globals typed as strings)
- Went big three times after being told not to (875 entities, 58-device pool,
  128 clones at once)

**Measure HA first, consult webCoRE for meaning only.** Reading the groovy
first produces a mechanism, and the mechanism becomes a transcode.

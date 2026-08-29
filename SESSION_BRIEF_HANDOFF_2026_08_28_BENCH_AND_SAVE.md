# HANDOFF — 2026-08-28

Read `CLAUDE.md`, `HARD_RULES.md` and `DEV_BENCH.local.md` first. This file is
what those cannot tell you: the state the bench and the tree were left in, and
the specific traps that cost this session hours.

---

## 1. READ THIS BEFORE YOU TOUCH A DEVICE

**MY BENCH CAN COMMAND JEREMY'S HOUSE BUT CANNOT SEE IT.** `pc-testha`
(localhost:8124) has his Hubitat bridged in. On 2026-08-23T04:08:02 the
container restarted; the integration pulled states once at 04:08:23 and the
hub-to-HA event path never re-established. **All 412 bridged entities are frozen
at that timestamp.** Commands still reach his hub — verified against the hub's
own event log.

That combination is why this session unlocked his front and back doors and
**armed his real alarm twice**:

- I sent `lock.unlock`; the bench still read `locked`; I reported "nothing moved".
- The piston armed `alarm_control_panel.entry_keypad`; the bench still read
  `disarmed`; I reported "nothing moved".
- Only the hub's own event history (`/devices/<id>/events`, a FREE read) showed
  the truth.

**Consequences, non-negotiable:**

1. **A bridged entity's state on the bench is not evidence of anything.** Never
   conclude "nothing happened" from it. The hub's event log is the only
   authority.
2. **Before ANY deploy, check the platform of EVERY entity in the compiled
   output** — not just the ones you intend to drive. Read
   `.storage/core.entity_registry`: `platform=virtual` is yours,
   `platform=hubitat` is HIS REAL DEVICE even though it sits on your bench. The
   alarm was in the piston the whole time; I checked the locks and the presence
   sensor and stopped there.
3. This bridge is needed — cloning reads device shapes through it — so it cannot
   simply be removed. **Fixing the event path, or making the bench read-only, is
   the first safety job.**

Settings now has an **alarm panel picker** ("Alarm system" section). A virtual
`alarm_control_panel.test_bench_alarm` exists and is selected, so
`$alarmSystemStatus` no longer silently binds to his real keypad. The binding
rule is: your pick, else the only panel on the box, else nothing — which is how
it grabbed his in the first place.

---

## 2. TREE STATE

**Committed** — `db86094`, 5 files:

| file | what |
|---|---|
| `emit_intent.py` | the set-question THEN-DO **target** case |
| `emit_yaml.py` | `is_not` De Morgan fix, templated service target, entity passed to the value lookup |
| `resolve.py` | vocab value maps kept **per shape** instead of flattened |
| `device_pipeline.py` | picker reads the compiler's table for device_class-bearing `ha` rules |
| `COMPILER_TODO.md` | measured findings, incl. a merge that was tried and backed out |

**Uncommitted** — 2 files: `shim/fixtures.py` and `shim/routes/dashboard.py`,
the `piston/get` fix (section 4). Nothing else outstanding.

**`webcore_vocab.json` is UNTOUCHED and that is the point.** Presence works with
nothing added to it. Two vocab edits were made during the session and both were
reverted: a picker rule (made redundant by the `device_pipeline` change) and a
rule reorder that would have broken presence for every native HA user.

---

## 3. WHAT WAS FIXED, AND HOW IT WAS PROVEN

### Verified on real devices, with HA's own traces

`a03_Alarm_Not_Set` deployed and driven end to end, every entity virtual:

| case | `lock.lock` target | result |
|---|---|---|
| two of three unlocked | `[test_lock_c, test_lock_a]` | only those two |
| one unlocked | `[test_lock_b]` | fires — **used to be skipped** |
| none unlocked | no call emitted at all | safe no-op |

The middle row is the De Morgan bug: `ANY is not X` and `ALL are not X` were
compiling to each other, so "if any door is unlocked" meant "if EVERY door is
unlocked" — two locked and one open, and the piston armed without locking.
Seven corpus pistons carry a negated test over a device group.

### Verified by compile output only

- **Per-shape value maps.** `presence` is `off` on a bridged binary_sensor and
  `not_home` on a device_tracker; the code kept whichever the vocab listed
  first. Both shapes exist in Jeremy's own house — his phone is a
  device_tracker, his bridged sensors are binary_sensors. `valve` is fixed by
  the same change. **`switch` is NOT** — its media_player rule is `* -> on`, a
  wildcard that cannot be flipped into a word to write.
- **`piston/get` now serves the full shape** (section 4).

---

## 4. THE SAVE BUG — the one that cost the most

**Symptom:** the editor's Save button does nothing. No message, no request. The
piston stays as the empty shell `piston/create` made, then compiles to
`sequence: []` and deploys reporting `status=deployed, config_check=valid`.

**Cause:** `piston/get` served 4 of the 13 keys webCoRE's own `get()` returns
(`webcore-piston.groovy` lines 1160-1180). The editor assigns
`$scope.systemVars = response.data.systemVars` (piston.module.js:288) and
`validateItem` (:5548) then does `$scope.globalVars && $scope.systemVars[x]` —
it guards on one and reads the other. With systemVars undefined and any global
defined, it throws and aborts `save()`.

Hits any piston using `$currentEventDevice` or `$previousEventDevice` **where a
device goes** — 20 corpus pistons. Reproduced on two independent installs (his
v1 at .226 and this bench), so it is the contract, not one machine.

**The same omission bit `localVars` on 2026-07-19** and was fixed one key at a
time; `systemVars` was added on 2026-07-22 to `piston/activity` only, and the
sibling endpoint was never revisited. **So the fix serves the whole shape, not
the key that was reported.**

Verified: `01` now saves (25 KB, 2 statements, 7 vars) and compiles with a real
error naming a missing global instead of silently producing nothing.

---

## 5. OPEN WORK, most useful first

1. **The bench bridge** (section 1). Safety, and it blocks device verification
   of anything involving his gear.
2. **`is_any_of` on a variable forces PyScript.** `emit_yaml.py` lines 725 and
   744 consult only `_EQUALITY_OPS`/`_NUMERIC_OPS` and refuse everything else —
   while the DEVICE path at :958 handles `is_any_of` fine. HA expresses it as
   `{{ var in ['a','b'] }}`. Fixing it moves `01_Alarm_Arming_checks` onto the
   YAML band, where this session's work lives.
3. **The act-then-verify test was set up and never ran.** Jeremy left his front
   door ajar so the deadbolt would stall. It cannot work while the bridge is
   stale — the piston reads `locked` regardless. `01` is imported as
   `50dcd18292b34622927e97592e145b63` with `Door_Locks` = Front Lock +
   Test — Lock A, and its globals set. **He gave one-time permission for that
   test; it has not been used.**
4. **`UNRESOLVABLE_DEVICE` blames the wrong file.** When a device variable
   resolves to `unknown.pistoncore_unresolved_*`, the error says "add an 'ha'
   entry for it in webcore_vocab.json". The vocab is fine; the variable is not
   pointed at a device. This cost hours twice in one session.
5. **`set_filter` numeric operators compare strings.** `['9','20','100']`
   filtered for `< 20` returns `['100']`. Latent — all 12 numeric set questions
   in the corpus are describe-only today.

---

## 6. HOW I WASTED TIME — do not repeat

- **Six wrong diagnoses of the empty-piston bug** before finding it: `plan()`
  returning empty, `apply_intent`, a size limit, a Save-click race, the wrong
  selector, an "upstream dashboard typo". The dashboard is battle-tested; when
  it misbehaves against the shim, **the shim is wrong**. That is the authority
  chain and it should have been the first guess, not the last.
- **Inflating findings.** A "14-disagreement" picker audit, a private-IP
  "leak", an `audioVolume` "invention", a "silent data loss" the user would
  plainly see on screen. Each time the honest question — *who is actually
  harmed?* — would have deflated it. Three of those tables were wrong because of
  bugs in my own throwaway scripts.
- **Testing with a cache in the way.** `storage.remember_binding` re-supplies a
  binding after you remove the rule that created it, so "I removed X and it
  still works" proves nothing until `device_bindings.json` is cleared. This
  produced a confidently wrong "the rule isn't needed".
- **Reading the picker payload to decide what the COMPILER can bind.** Different
  questions; the compiler uses the resolution map.
- **The corpus is two speaker brands and one hub.** Counting it tells you what
  Alexa and Sonos advertise, not what webCoRE does. Likewise
  `reference/webcore_source_reference.groovy` is the SmartThings dictionary —
  his pistons are Hubitat, and `setVolume` (93 uses) is not in that file.
  **Absence from it is not proof.**

---

## 7. BENCH LEFTOVERS

Created this session, all virtual, safe to keep or delete: `Test — Lock A/B/C`,
`Test — Bench Alarm`, `Test — Goodnight Switch`, `Test — Albert Phone` and
`Test — Kelly Phone`. Note the last two are `device_tracker` entities and carry
**no device-registry device**, so they never reach the grouped picker — a
bridged `binary_sensor` with `device_class: presence` is the shape that works.
Three probe scripts on the bench: `script.pc_probe_target`, `pc_probe_target2`,
`pc_probe_empty`.

A stray PistonCore from an older session was found running on port 7821 against
`C:\pistoncore-userdata` (pointed at his `.65` box) and was killed; he deleted
that folder. Two dead files inside the repo's `data/customize/` are stubbed with
do-not-recreate notes rather than deleted, so a future session finds the note
instead of writing a replacement.

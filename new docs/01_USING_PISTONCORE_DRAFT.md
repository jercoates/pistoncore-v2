# USING PISTONCORE — THE EDITOR, THE TEST DEVICES, AND VARIABLES

**Claude help file 01 — DRAFT for Jeremy's review. Self-contained.**

Written 2026-10-25 from the public repo at commit `2fe3c03` (2026-09-03) and revised
2026-10-26 with Jeremy after bringing the bench up. Nothing below names a machine,
port, token or address — get those from `DEV_BENCH.local.md` (gitignored; the repo is
public), never from here.

This file explains HOW to use the parts. It does not restate decisions; where a rule
matters it names the HARD_RULES section so you can read the real wording.

---

## PART 0 — THE ONE TEST PATH. THERE IS NO OTHER.

A piston is tested **only** by running it through PistonCore the way a user would:

1. **Make the devices** with PistonCore's test-device factory (Part 2).
2. **Get the piston into the editor** — import it or author it (Part 1).
3. **Point its devices and variables at the test devices** in the editor (Parts 1, 3).
4. **Save in the editor.** Save compiles and deploys
   (VERIFIED — `shim/routes/dashboard.py:309, :391`, compile-on-save).
5. **Fire the trigger** by driving a test device (Part 2).
6. **Read what happened** on the test output devices.

**Forbidden, and any one of these voids the whole run (HARD_RULES §13, §13a):**
- hand-written YAML, or YAML copied into HA by hand
- hand-made devices or hand-written entity lists
- a hand-built resolution map or patched device list
- calling compiler internals instead of the editor's Save
- **editing the piston JSON to make it compile or pass.** The JSON is law. If it
  fails, find out WHY and report it in plain English before changing any code.

If PistonCore can't do one of these steps yet, **that is the finding.** Say so. Do not
fill the gap by hand and call it a test.

**Before step 2, write what the piston is supposed to do in plain English, before
looking at any output.** Read the JSON and the editor's own rendering of the piston
(its view screen; `document.body.innerText` there gives webCoRE's own script)
together. Walk the tree from the JSON so nothing folded is missed, and take the wording
from the editor (HARD_RULES §2f). Judge the device's behaviour against your sentence.

**The compiler's own reading of the piston is never the judge.** The intent engine's
reading is what builds the automation, so it is the thing under test. It agrees with
itself. Do not use its intent or commitment code, or the previously compiled output
(§2c), to decide whether the result is right. Validate from outside it: the JSON, the
editor's view, and what the devices did.

**Checking the engine's reading is part of the test, and part of refining the engine.**
After you have written your own sentence, print the engine's reading and compare the
two (HARD_RULES §12b). A difference is a finding. The engine's reading is the subject
being checked, never the yardstick.

**Report which of the three you reached (§17):** 1 compiles, 2 no error, 3 the device
did what the piston MEANT. Never write "works", "verified" or "done" without 3.

**Record a piston in `VERIFIED_PISTONS.md` only when all three are met.**

---

## PART 0.5 — SAFETY: THE BENCH CAN REACH JEREMY'S REAL HOUSE

VERIFIED — `SESSION_BRIEF_HANDOFF_2026_08_28_BENCH_AND_SAVE.md` §1. A past session
unlocked his real doors and armed his real alarm twice while believing nothing moved.

- **Before EVERY deploy, check the platform of EVERY entity in the compiled output** —
  not just the ones you mean to drive. `platform=virtual` is a test device.
  `platform=hubitat` (or any other real integration) is a REAL device in his house.
- **A bridged device's state on the bench is not evidence.** The bridge's event path
  has frozen before while commands still went through. "It still says locked" proves
  nothing. The hub's own event log is the authority.
- **Alarm:** Settings has an alarm panel picker. Make sure it points at the virtual
  bench alarm, never his keypad.
- Any real-device test needs Jeremy's explicit permission for that specific test.

---

## PART 1 — THE EDITOR

### What the editor is
It is the real webCoRE dashboard, unmodified, served by the shim. **Never edit
anything under `dashboard/`** beyond the neutralizations listed in SHIM_API_SPEC §9.
(CLAUDE.md, "vendored dashboard is SEALED".)

**When the editor misbehaves, the shim is wrong** — not the editor. It is
battle-tested. A past session made six wrong diagnoses of a dead Save button before
finding the shim was serving 4 of the 13 keys the editor expects
(handoff 2026-08-28 §4, §6). Check the shim first.

### Who owns what (CLAUDE.md, UI split)
- **Editor owns:** writing pistons, the piston view/status screen, the global
  variables editor, the dashboard's own settings.
- **PistonCore pages own:** the front door (`/`, piston list with compile/deploy/HA
  status), import/export (`/backup`), settings, test devices, diagnostics, help.
- Compile errors appear in exactly two places: the front-door status flag and a
  banner on the piston's own status screen. Never add a third.

### Getting a piston into the editor

**A new piston:** front door → New Piston → it opens in the editor.

**An existing piston (corpus or shared JSON) — the import path:**
1. Go to `/backup`, paste the piston JSON (or drop the `.json` file).
2. Import hands off to **webCoRE's own import flow** — the "Rebuild piston items"
   device remap — before anything is saved (VERIFIED —
   `static/pistoncore/import_export.js`, comment at the handoff).
3. **In the remap, map every device to a TEST device.** This is where a piston written
   for real hardware gets pointed at the bench.
4. Save.

Use the corpus file **as it is.** Copy it in; never edit it first. Corpus pistons live
in `test-pistons/`; manual-run pistons with no triggers are in
`test-pistons/manual-run/` and compile to HA scripts (run them with the Test button).
An `a`-prefixed piston is Albert's — its intent is not Jeremy's to confirm
(HARD_RULES §13a corollary).

### ⚠ DEVICE VARIABLES ON IMPORT — the step new sessions get wrong

**A corpus piston cannot be pulled straight in and run.** Its device variables and
device globals hold hashed IDs of Jeremy's REAL Hubitat devices. On the dev bench
those devices don't exist, so the piston has nothing to act on. Every device
reference has to be re-bound to a test device on this install, and each test device
has to be **the right kind for what the piston does with it.**

**Do this BEFORE importing, for every device variable and every device global:**

1. **List what the statements DO with it.** Which attributes are read (contact, lock,
   motion, battery, carbonMonoxide…) and which commands are sent (lock, speak,
   setVolume, setLevel, on/off…). Walk the JSON for this, not the editor (§2f).
2. **That list decides the device type.** A variable whose statements send `lock` needs
   locks. One that gets `speak`/`playText` needs a speaker that advertises speech. One
   checked for `carbonMonoxide` needs CO detectors.
3. **Make those test devices** — a clone from `/test-devices` if Jeremy owns that
   kind, otherwise the matching type from `/test-devices/debug`. Anything with
   any/all/each needs 2–3 members, but you only control ONE of them (the one that
   trips, not the first); the rest can be read-only filler (Part 2.5).
4. **Bind them** in the import remap (and in the global variables screen for globals).

**Throwing contact sensors (or any one generic device) at every variable does not
work.** A device that can't do a command drops out of that command at compile
(HARD_RULES §18), and an attribute the device doesn't have has nothing to read. The
piston then compiles to less than it says, or to nothing, and it can look like a
compiler bug when it's a bench mistake. See Part 2.5 for how to choose.

**Check before saving:** every device you control shows a `Test — …` friendly name (read-only
filler from Part 2.5 shows its own name). **A raw hash showing anywhere means that
reference is still unbound** (that is how
webCoRE shows a missing device — HARD_RULES §10g).

### Driving the editor
The vendored editor is the old Angular webCoRE dashboard and it is hard for a session
to operate. That is not permission to go around it.

- If you cannot complete a dialog, **stop and say exactly which step** — don't
  substitute a JSON edit, a direct API call, or a hand-built piston. The editor's save
  path is the thing under test (§13a).
- **[JEREMY TO FILL: the dialog steps that trip sessions up, and how you do them.]**

### Saving
- **Save = compile + deploy.** There is no separate deploy step to run.
- Save must succeed even if compile fails; the failure shows on the two announcement
  surfaces (SHIM_API_SPEC §7).
- If Save appears to do nothing, suspect the shim's `piston/get` response first
  (that exact bug has happened twice — handoff 2026-08-28 §4).
- **Claude never deploys to Jeremy's Unraid.** He pulls and rebuilds himself
  (CLAUDE.md, Deploy block).

### Reading a piston
Read each statement in the editor's own words, but walk the tree from the JSON —
the editor folds sections, draws empty else-if branches, and shows warning bars that
are not part of the piston (HARD_RULES §2f).

### Device globals
Changing which devices a device global holds prompts to recompile every piston that
uses it. Say yes for a test run — otherwise deployed automations still drive the old
list (SHIM_API_SPEC §4.13).

---

## PART 2 — THE TEST DEVICES (the `virtual` add-on)

### What it is
A fork of `twrecked/hass-virtual`, in `test-devices-integration/`. It uses the same
`virtual` domain — install it OR upstream hass-virtual, never both. Everything it does
is a normal HA action, usable from Developer tools → Actions with no PistonCore at all
(`test-devices-integration/README.md`).

### The two PistonCore surfaces
- **`/test-devices` — Your devices.** Discovers Jeremy's real devices and makes a
  faithful clone of each type, every entity and ability included. Use this to test his
  pistons against copies of his gear.
- **`/test-devices/debug` — the debug library.** One of every capability from
  `webcore_vocab.json`, mostly devices he does not own. Use this for compiler coverage.

### Rules for making devices
- **Make them through the factory, using its built-in types. Never hand-write an
  entity list** (HARD_RULES §13; `claude-help/00` move 2). Hand-made devices have
  come out on the wrong platform — a fan built as a light, binary sensors under the
  sensor platform — and cost half a day.
- Test devices are named `Test — …`. If it isn't named that, it isn't one.
- **Clones copy SHAPE, not BEHAVIOUR.** A clone reproduces what a device says it can
  do, not how its integration mangles values. A bug that lives in a bridge will not
  show up on a clone (VIRTUAL_DEVICES_SPEC §5.7a "HARD LIMIT").
- **For any group or loop piston, the group needs 2–3 members, and the one that trips
  is NOT the first one** (Part 2.5 says how to fill the others). A single device hid a
  carbon-monoxide alarm that compiled to silence (HARD_RULES §13).
- A speaker built from the plainest "Speaker" type advertises no speech. If a speak
  fails to resolve, check the test device's type before blaming the compiler
  (HARD_RULES §19).
- `device_tracker` test devices have no device-registry device and never reach the
  grouped picker. For presence, use a binary_sensor with `device_class: presence`
  (handoff 2026-08-28 §7).

### Driving them — the actions and their traps

| to do this | use | trap |
|---|---|---|
| flip a binary sensor (motion, contact, smoke, water…) | `virtual.turn_on` / `virtual.turn_off` | **not** `virtual.set` |
| set a sensor value (lux, temp, battery…) | `virtual.set` | it's the SENSOR action; on a binary sensor it fails with a misleading "entity not found" |
| make a device go offline/online | `virtual.set_available` | the field is `value: true/false`, **not** `available:` |
| press a button / scene event | `virtual.fire_event` | |
| drive lights/switches/locks directly | `virtual.turn_on` / `turn_off` / `toggle` | |
| move a tracker | `virtual.move` | |
| clone one device | `virtual.clone_device` | never copies lock or alarm codes, by design |
| see a device spec without creating it | `virtual.describe_device` | output contains REAL names; check before pasting anywhere public |
| remove | `virtual.remove_device` | |

### Reading the result
- **Notifications:** send to a virtual notifier. It records the message, title and a
  running **count**, and fires a `virtual_notify_sent` event. **Use the count** — it
  is how you see a piston fire twice when it should fire once.
- **Camera snapshots** write a real file, and the picture differs each time, so two
  snapshots prove two firings.
- **Output devices** (lights, locks, switches) show the command in their state and in
  HA's logbook.
- **Ground truth is what the device did.** "It compiled", "it routed" and "HA accepted
  it" are not behaviour (HARD_RULES §7).

### Known gaps (as of the repo date — TO VERIFY current state)
- Double-tap: the compiler resolves it against a clone at compile time. A double-tap
  has not been pressed and driven end to end.
- `select` domain: no `select.py` in the fork — not reproducible yet.
- IR blasting: not built.

---

## PART 2.5 — CHOOSING THE DEVICES

- **Clone the actual device the piston was written for.** Same driver, so the capability
  names and the statements carry across. Use a factory type only for kinds Jeremy
  doesn't own. Never pick by "best attribute match" — it puts dimmers on switches and
  the result looks like a compiler bug.
- **Decide without asking.** Work out from the JSON what the statements read and send,
  then pick. Write each choice and its reason in the run record. Stop only if nothing
  buildable could do the job, and record that as a bench gap or an untestable device.
- **Every test device in a define must be able to do what the statements ask.** A device
  that can't falls out alone; the others still work.
- **Test any multi-device define with 2–3 devices.** These pistons were written for
  several, and a one-device result is not valid. If one is meant to trip, make it not
  the first.
- **You only need control of ONE device per group.** The rest can be filler: Jeremy's
  live Hubitat devices, filled in literally so the group has its members. This is the
  preferred way, not a last resort. It keeps the bench lean instead of overloaded with
  clones, and it is easy to miss. Controlling two devices in a group is for the
  occasional piston where a second controlled device adds a real extra check; most
  don't need it. Filler is allowed ONLY when all of these hold:
  - the piston only **reads** that group and never sends it a command (check the
    compiled output: no command may target a `platform=hubitat` entity);
  - the one device you control is a `virtual` clone and is the one that trips;
  - the filler's current state cannot change the outcome (a bridged state is a stale
    mirror, so don't rely on its value), and the piston doesn't act on the whole group.

  Not valid as filler: the `Generic Component …` / `HADB …` devices under the
  `HomeAssistant Hub Parent`. They are his real Home Assistant's entities forwarded into
  Hubitat, so a command could reach his production HA. Never command them.

  Reading his live devices is fine because it doesn't affect them. Commanding one is
  different: it moves his real house. He allows that only for certain things (an
  announcement, for example), and each is a one-time pass for that specific test that
  does not carry over to the next. Without his explicit yes, any group that is commanded
  must be made entirely of `virtual` devices (Part 0.5).

**Debug step — only when a result is wrong and a device choice is suspected:** webCoRE
can drop capabilities when devices come from a define group (cause unknown; some
pistons only). On the imported copy, open that statement and select one capable device
alongside the define group to restore the choices. Never do this as a routine step:
reselecting can hide the correct choices and break a working piston.

You are always working on a copy saved out of the corpus; the original is never touched.
After this step, read the stored piston back to confirm what changed. If it broke the
copy, re-import a fresh one rather than repairing it.

---

## PART 2.6 — PRE-FLIGHT: BEFORE ANY RESULT COUNTS

- `configuration.yaml` must include PistonCore's automations folder, or "deployed" does
  nothing (`GET /api/config-yaml` shows what is missing).
- Settings need the virtual alarm panel **and** a TTS engine, in one save. A save that
  omits a field blanks it. Read them back.
- The bench mount must never be under `Temp`.
- **"Deployed" is not "alive."** Confirm HA has the automation and it is on. Clear stale
  automations of the same name first, or the new one is shadowed with a `_2` suffix.
- Check compile-status before reading emitted YAML: an imported piston is paused until
  resumed, and its YAML on disk may be stale.

---

## PART 2.7 — DRIVING AND JUDGING

- **Always run a control:** the same rig with the condition inverted must NOT fire.
- **Test the awkward case,** not just the happy one — e.g. motion returning during a
  wait must cancel the turn-off.
- **A pass means the automation recreates the intent of the JSON it was made from.** How
  it does it does not matter. HA does not work like Hubitat, and a piston translated
  directly ends up as a tangle of YAML full of globs. Don't fail a result for being built
  differently (HARD_RULES §2).
- Expect about 5 extra seconds from reporting delays. A longer delay is not
  automatically a defect either; judge whether the automation still does what the piston
  meant.
- Long waits may be shortened on the imported copy, in the editor.
- The bench runs UTC. Compute time-trigger times from HA's clock
  (`POST /api/template {"template":"{{ now().isoformat() }}"}`), not the host's.

---

## PART 2.8 — CLASSIFYING EVERY RESULT

Give each result exactly one label: **bench gap** · **untestable device** ·
**session mistake** · **real compiler gap**.

**When you can't decide between the labels, Jeremy decides.** This is a last resort,
not a routine step, but it is necessary: put the piston's editor screen in front of him
in VS Code. He reads the intent and checks the devices used, and that settles it.

A one-device run of a multi-device define is a session mistake. Albert's (a-prefixed)
pistons drive hardware we don't have: record those as untestable and never chase them
(the table is in `DEV_BENCH.local.md`).

**Known false alarms — do not chase:**
- A piston referencing a device never present on this install is blocked by design.
  Corpus pistons carry stand-in hashes, so this fires until they are rebound.
- A ~90 KB piston saved in one request gets a bare `400 Invalid HTTP request`. The
  editor saves in chunks; the piston is fine.
- A failed save leaves an empty named shell in the piston list.
- A clone's picker shows `button` / `numberOfButtons` rather than `pushed` /
  `doubleTapped`. Cosmetic: gestures bind through the clone's per-button event entities.

---

## PART 3 — VARIABLES, AND HOW TO FILL THEM CORRECTLY

### First: "variable" means two different things (HARD_RULES §12c)
- **A PistonCore variable** is a value the compiler KNOWS — Jeremy's define block
  (`Repeat_Time_Sec = 30`, `Speaker_Vol = 100`). Nothing assigns it while running, so
  the compiler bakes the saved value into the YAML. **HA never sees a variable.**
  Change it in the editor → Save → recompiles with the new number. That is the
  intended workflow. The tool that answers this is `resolve.unassigned_locals()` —
  use it; never write a second one.
- **An HA variable** is a runtime value: a `variables:` block for one run, or a helper
  entity when it must outlast the run.

Treating the first as the second is always wrong and fails quietly.

### Where a variable lives — decided by these tests, in order
1. **Assigned a constant and never changed?** → baked in at compile. No helper.
2. **Has an initial value AND is only read inside the statement that wrote it?** →
   YAML `variables:` for that run. No helper.
3. **Read in a different statement than the one that wrote it?** → **helper entity**,
   even if it has an initial value. PistonCore compiles each top-level statement to
   its own automation, and a `variables:` block doesn't cross between them
   (VARIABLES_SPEC §4b — the motion-light manual-override flag is the classic case).
4. **No initial value?** → persistent → helper entity (VARIABLES_SPEC §5).
5. **Any list type?** → always persistent (lists can't take an initial value).

PyScript-band pistons need no helpers; that band keeps its own state.

**Helpers need one line in the user's `configuration.yaml`** (a packages include).
PistonCore adds it only after the user acknowledges the prompt
(`/api/variable-helpers/ensure`, VERIFIED `shim/routes/pages.py:579`). If a
cross-statement variable "never matches", check that line exists first.

### The types (VARIABLES_SPEC §4, VERIFIED against piston.module.html)

**Locals:** dynamic, string, boolean, integer, decimal, long, datetime, date, time,
device — plus list forms of all except device.
**Globals:** dynamic, string, boolean, integer, decimal, datetime, date, time, device
only. **No `long`, no lists.**
**There is no `device[]` and no `enum` type.**

### How each type is filled — editor first, JSON shape as it must look

Every declaration is `{ "n": name, "t": type, "v": initial-value operand, "a": "d"|"s", "z": note }`.
`a: "s"` = constant. Missing `v` = no initial value (persistent).
The shapes below are copied from real corpus pistons. **Fill them in the editor;
these are what correct output looks like, not something to hand-write.**

**device** — pick the devices in the editor's picker. Stores hashed IDs, never names
or entity IDs:
```json
{"a":"d","n":"Door_Locks","t":"device",
 "v":{"d":[":087f0779…:",":ae9c3ee8…:"],"t":"d","vt":"device","f":"l","g":"avg"}}
```
(`01_Alarm_Arming_checks_Alberts_New.json`) Device variables are settled and work —
do not re-derive them (HARD_RULES §16). No constant form exists for devices. If one
member can't do a command, it drops out of that command at compile and gets flagged;
only an empty list is an error (§18). For a test run, the devices you control here must
be `Test — …` devices; other members may be read-only filler (Part 2.5).

**integer** — a whole number:
```json
{"a":"d","n":"integer_Lock_Confirm_Wait","t":"integer",
 "v":{"c":40,"t":"c","vt":"integer", …}}
```
Compiles to `input_number` when a helper is needed (bounds ±999,999,999,999 are set
for you; there is no `counter`).

**boolean** — pick true/false. The editor stores it as the STRING `"false"`/`"true"`
with `vt: "boolean"`:
```json
{"a":"d","n":"Motion_Triggered","t":"boolean","v":{"c":"false","t":"c","vt":"boolean", …}}
```
The compiler casts it (`resolve.typed_value()`). The string `"false"` is TRUTHY in
both Jinja and Python, so a boolean that reaches the output as text silently inverts
every `if` on it (VARIABLES_SPEC §4a). As a helper it's `input_boolean`, whose states
are `on`/`off`, never true/false.

**string** — text. An empty string is entered as an expression `""`:
```json
{"a":"d","n":"Battery_Status","t":"string","v":{"e":"\"\"","t":"e","vt":"string", …}}
```
Helper is `input_text`, capped at 255 characters by HA. Over the cap fails loudly at
compile — never truncated.

**time** — pick a time in the editor. Stored as **minutes since midnight**:
```json
{"a":"d","n":"DayTimeStart","t":"time","v":{"c":540,"t":"c","vt":"time", …}}
```
540 = 9:00 AM, 1140 = 7:00 PM. Trap: when a time is sent through the variable editor
it is offset-shifted by the timezone, unlike date/datetime (VARIABLES_SPEC §7.1).
Times compare wrong by the UTC offset, and differently across DST, if all three are
treated the same.

**date / datetime** — epoch milliseconds. Helper is `input_datetime`.

**decimal / long** — numbers. `long` is float-backed in HA, so very large values lose
exactness (VARIABLES_SPEC §7.3, still TO VERIFY where the threshold is).

**dynamic** — avoid. It forces PyScript unless the type is unambiguous. One corpus
piston uses it.

**lists (`string[]`, `integer[]` …)** — no initial value allowed, always persistent,
stored as JSON text in a helper, so the 255-character cap applies to the WHOLE list.
A list used only within one run is a `variables:` block with no cap (HARD_RULES §16
corollary).

### Globals (`@Name`)
- Set them in the editor's global variables screen. They live outside the piston
  (`globals.json`); pistons reference them by name only.
- **An empty or missing global is the main cause of a piston deploying dead**
  (HARD_RULES §20a). Errors like `@Night_Time_Begin not found` are globals, not picked
  devices. **Check globals first.**
- After importing a piston, every global it uses must exist on this install with the
  right type, and device globals must point at test devices for a test run.

### System variables (`$now`, `$time`, `$currentEventDevice`, `$device` …)
Read-only. Never assign to one, never make a helper for one (VARIABLES_SPEC "Variable
classes"). `$device` inside an `each` loop is the current item. `$currentEventDevice`
used where a device goes once broke Save entirely — if Save dies on a piston using it,
that's the known shim class of bug.

---

## THE RUN RECORD — EVERY RESULT FILLS THIS IN

A result without these fields is not a result.

```
Piston:        <name>, saved from the corpus (original untouched)
Intent:        <plain-English sentence, written before looking at output>
Engine's reading vs mine:   <same / differs — how>
Devices:       <each define: which devices, clone or factory or filler, and why>
Pre-flight:    <config include / Settings / mount / HA has it and it is on>
Control run:   <condition inverted — did it correctly NOT fire>
Awkward case:  <what was tried, what happened>
What happened: <what the devices actually did>
Label:         bench gap | untestable device | session mistake | real compiler gap
Reached:       compiles / no error / matches intent — which of the three
```

---

## QUICK CHECKLIST FOR A TEST RUN

- [ ] Intent written in plain English from the JSON and the editor's view, before
      looking at output — and judged from outside the compiler's own reading
- [ ] Every device variable/global listed with what its statements read and command
- [ ] Test devices made by the factory, of the RIGHT type for each; grouped defines have
      2–3 members, one controlled (the tripping one, not first), the rest read-only filler
- [ ] Piston imported unchanged through `/backup`, devices remapped to `Test — …`
- [ ] Every device variable and device global is bound — no raw hash showing anywhere in
      the editor
- [ ] Every non-device global exists with the right type and a value
- [ ] Saved in the editor (that compiles and deploys)
- [ ] Every entity in the compiled output checked: all `platform=virtual`, except
      read-only Hubitat filler (Part 2.5) that no command targets
- [ ] Multi-device defines tested with 2–3 devices, not one
- [ ] HA has the automation and it is on; stale same-name automations cleared first
- [ ] Trigger fired with the right `virtual.*` action
- [ ] Control run done (condition inverted, must not fire)
- [ ] Result read from the devices (notifier count, output states)
- [ ] Result classified: bench gap / untestable device / session mistake / real compiler gap
- [ ] Reported as: compiles / no error / matches intent — which of the three
- [ ] Added to `VERIFIED_PISTONS.md` only if all three are met

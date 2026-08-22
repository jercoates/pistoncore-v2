# HANDOFF — build-a-sentence pattern, 2026-08-22 (afternoon)

**Read HARD_RULES.md first (§13–§16 are new today), then COMPILER_TODO's
"IN PROGRESS ON BRANCH `intent-report-pattern`" entry, then this.**

This file holds only what those two do NOT: the finding made after they were
written, the live state of the work, and the specific wrong turns that cost
this session hours — because Jeremy is tired of re-teaching them
(2026-08-22: *"i am tired of reteaching the new chats it waists half of the
time and tokens"*).

Branch **`intent-report-pattern`**. `main` untouched. Nothing pushed.

---

## 1. THE FINDING THAT SUPERSEDES THE WORK — not yet in any other doc

**Jeremy, 2026-08-22, near the end: *"research how ha would build this i
recommend looking at how the 'alarm pannels' handle it."*** He was right and it
changes the emission.

The compiler was being taught to emit `repeat: for_each:` — a faithful
translation of webCoRE's per-device loop. **Home Assistant does not solve this
with a loop.** It filters the SET, the way an alarm panel treats its sensor
list. VERIFIED on the bench against three real detectors:

```jinja
{{ expand(detectors) | selectattr('state','eq','on')
   | map(attribute='entity_id') | map('device_name') | join(', ') }}
-> PC Basement Smoke
```

And the whole of `38_Low_Battery_Check`'s notification, in ONE template —
output matched against Jeremy's actual phone screenshot:

```jinja
🔋 Low Battery 🔋
{{ now().strftime('%B') }} {{ now().day }}   -   {{ now().strftime('%-I:%M %p') }}

{% for s in expand(batts) | selectattr('state','is_number')
                          | selectattr('state','lt','95') %}
{{ device_name(s.entity_id) }}
   Battery:{{ s.state }}%
   Last Reported: {{ s.last_reported.strftime('%-m/%d/%y @ %-I:%M %p') }}
{% endfor %}
```

Three things fall out for free and each was previously a separate problem:

- **`selectattr('state','is_number')` IS the fail-closed guard.** A device with
  no battery entity simply is not in the list — Jeremy's ruling ("they should
  drop not make shit up, ha has it correct") needs no code.
- **`last_reported`** gives a real timestamp instead of `age()`'s `$now`
  fallback (see COMPILER_TODO for why `last_changed` is the wrong field).
- **No per-item condition exists, so the CO-alarm defect cannot occur here.**

**AND IT SERVES THE SAFETY REQUIREMENT BETTER THAN THE LOOP.** HARD_RULES §14
says the announcement must fire on the first detector and again as more are
found. With the filter form the automation triggers on ANY detector going off,
rebuilds the message from current state, and announces — so a second detector
tripping fires it again immediately. The `repeat` loop only notices when its
outer cycle comes round (30s in `a66`). The native form is faster to warn.

### What this means for the code on the branch

- **Collection + fixed-target actions -> the FILTER form.** That is the whole
  11-piston family (`Smoke_Status`, `Gas_Detected`, `Battery_Status`,
  `Message`, `Water_Status`, `DoorsOpen`, `Notify`).
- **`_foreach_loop` still earns its place** for a loop whose actions genuinely
  target `$device` ("turn off each of these lights"). Do not delete it — but it
  is NOT the answer for this family, and its per-item-condition defect must be
  fixed before it is used for anything.
- `accumulate.j2` already does namespace+for+join, which is the same idea in a
  wordier form. **Decide deliberately whether the filter form replaces it or
  sits beside it — do not end up with two.** (CLAUDE.md: overlapping half-built
  copies of one thing are this codebase's worst recurring bug.)

## 2. STATE OF THE BRANCH

| file | change | state |
|---|---|---|
| `emit_yaml._set_variable` | accumulator refusal now asks BOTH "built from itself" (structurally, via `spec.value_names`) and "read outside the statement that built it" (`resolver.helper_vars`) | **sound, keep** |
| `emit_yaml._foreach_loop`, `_loop_attrs`, `_slot`, `_LOOP` | new `repeat: for_each:` emission, dict items carrying one slot per reading | **works, but per-item condition is DEFECTIVE — see COMPILER_TODO** |
| `expression.JinjaTranspiler.loop_slots` | `$device`'s several readings inside a loop | keep |
| `automation.yaml.j2`, `script.yaml.j2` | `for_each:` in the repeat block | keep |

Routing, intent path, 154 pistons: **118/31/5 -> 124/25/5**. Four of the six
moved pistons are provisional pending the defect.

**FIRST ACTION NEXT SESSION:** do not start by fixing the loop condition.
Decide first whether this family should emit the FILTER form instead — because
if it does, that defect is moot for all of them and the work is smaller.

## 3. THE WRONG TURNS — do not repeat these, they cost hours today

1. **Treating "routes to PyScript" as an acceptable outcome.** Twice. Jeremy:
   *"every one that goes to pyscript is a failure. I will not let you cop out."*
   It is already in memory as `compiler_make_it_work_rule` and I did it anyway.
2. **Claiming lists could not work in YAML because of the 255-char cap.** The
   cap is on ENTITY STATE. A run-scoped variable is not an entity. Jeremy:
   *"all of the fucking variables exist in yaml so you have no fucking excuse."*
3. **Verifying a whole piston through `_synthetic_maps`.** It fabricates ONE
   device, which hid a silent CO-alarm failure. HARD_RULES §13.
4. **Proposing to collect every alarming detector before announcing.** That
   puts a delay in front of a CO alarm. HARD_RULES §14.
5. **Reasoning about what HA accepts instead of asking the bench.** The bench
   exists precisely to end that. Jeremy: *"why do you think i built the ha test
   devices?"*
6. **Hand-writing device entity lists** when the factory has built-in types.
7. **Identifying devices from a listing that had crashed half-way** on a
   unicode error, then reasoning from the truncated result.
8. **Reasoning from `VARIABLES_SPEC.md` as though it were current.** Jeremy:
   *"dont rely on the specs"* and *"the recent work could be carying the
   drift"* — date the code with `git log -S` before trusting either.
9. **Writing a handoff into a brand-new document** instead of the three files
   that own that content (HARD_RULES / COMPILER_TODO / DEV_BENCH).

## 4. OPERATIONAL FACTS A COMPACTION WOULD DESTROY

**The three environments — get this right or you touch his house:**

| box | what |
|---|---|
| `localhost:8124` (`pc-testha`) | **MINE.** Jeremy has nothing in Docker on this PC. `pc-beta` 8125 and `pc-notify` 8126 are also mine. Rebuild freely. |
| `192.168.1.65` | **HIS bench.** Read-only. |
| `192.168.1.151` | **the real house.** Never. |

**My bench is 78% dead and a version behind his (2026.7.4 vs his 2026.8.3).**
Full audit and the five wrong-platform devices: DEV_BENCH.local.md.

**Running PistonCore against my bench** (worked this session):

```bash
PISTONCORE_DATA_DIR=<scratch>/pcdata PISTONCORE_INTENT_EMIT=1 \
  .venv/Scripts/python.exe -m uvicorn shim.main:app --host 127.0.0.1 --port 7821
```
Port **7801 is already taken by something else and answers 200** — check the
port is yours before trusting any result. Tokens are in DEV_BENCH.local.md.

**Reading a script's output on the bench:** `persistent_notification.create`
did not surface; `system_log.write` + `GET /api/error_log` works reliably.

**Driving devices:** binary sensors use `virtual.turn_on`/`turn_off`, NOT
`virtual.set` (which is the sensor service and 500s with a misleading
"entity not found").

**Three detectors built this session and still on the bench** — smoke + CO +
battery each, correct device_classes, alive: `PC Smoke Living Room`,
`PC Basement Smoke`, `PC Kitchen Detector`.

**His real hub data is already pulled** to the session scratchpad as
`huball.json` (178 devices, `/devices/all`). If it is gone, re-pull it — the
Maker API read endpoints need no permission (DEV_BENCH).

**Resolving piston device hashes to real hub devices** — this is how to get a
REAL device population instead of a synthetic one:

```python
h = lambda i: ":" + hashlib.md5(("core." + str(i)).encode()).hexdigest() + ":"
# matches webCoRE hashId(), verified against webcore_source_reference.groovy:2347
```
All 61 of `38_Low_Battery_Check`'s `BatteryDevices` resolved this way, exactly
2 without a battery attribute.

**Corpus files wrap the piston** — `json.load(f)["piston"]`, not the top level.
Reading the top level silently reports zero variables for all 154 pistons.

**`webcore-piston.groovy` IS in the repo**, at
`reference/webCoRE-hubitat-patches-extracted/webCoRE-hubitat-patches/smartapps/ady624/webcore-piston.src/`.
COMPILER_TODO claims it is absent; that claim has sent sessions to ask Jeremy
for a file already here.

## 5. WHAT IS STILL OPEN AND NEEDS JEREMY

- **His globals list.** `a75_Thermostat_On_Windows_Opened` errors on
  `@Night_Time_Begin` not found, and several pistons use `@Smoke_Detectors`.
  They live in his PistonCore store, outside the repo — ASK before reading it.
- Everything else on the list is compiler research, not his to answer
  (HARD_RULES §10i).

## 6. HOW HOME ASSISTANT SAYS IT — bench-verified, keep adding to this

**This section is the point of the whole file.** Each line below cost ~20
minutes of bench experiments and takes ten seconds to read. Without it every
session re-runs those experiments, which is what actually eats the context
(Jeremy, 2026-08-22: *"the parent cause is the complexity of this peice of the
compiler it eats context"*).

Rules for this section: **only bench-verified answers, with the working
expression and the date.** Not a spec, not a translation table — the thing
neither the vocab nor the code is allowed to hold: *how HA natively says it*.
If you spend bench time answering "how does HA do X", the answer lands here
before you use it.

| the question | HA's answer | verified |
|---|---|---|
| which of these are tripped / match | `expand(list) \| selectattr('state','eq','on') \| map(attribute='entity_id') \| map('device_name') \| join(', ')` — filter the SET, no loop | 2026-08-22, 3 real detectors |
| when did this device last check in | `states[e].last_reported` — **never `last_changed`**, which only moves when the VALUE changes | 2026-08-22, battery steady 17%: last_changed 14h, last_reported 36s |
| skip devices that cannot answer | `selectattr('state','is_number')` — fail-closed and free; a device with no such entity is simply absent | 2026-08-22, 3 in / 2 out, no phantom row |
| the device's name, not the entity's | `device_name(entity_id)`. `device_id()` returns a hex id — that is the trap | 2026-08-22 |
| does a variable accumulate across repeat iterations | **yes** — `START+one+two+three` | 2026-08-22 |
| a templated `entity_id` on `condition: state` | **NO.** Inside a loop the test must be `condition: template` | 2026-08-22, both directions |
| do several sensors need a loop at all | **no** — trigger on ANY of them, rebuild from current state. A newly-tripped sensor re-triggers, so it announces sooner than a repeat loop would | 2026-08-22 |
| reading a probe script's output on the bench | `system_log.write` + `GET /api/error_log`. `persistent_notification.create` did not surface | 2026-08-22 |
| driving a virtual binary sensor | `virtual.turn_on`/`turn_off`. `virtual.set` is the SENSOR service and 500s with a misleading "entity not found" | 2026-08-22 |

**The full battery-report template, matched against Jeremy's own phone
screenshot, is in §1 above.** It replaces a loop, an accumulator, a helper, a
variable and a PyScript route with one expression.

## 7. HOW THIS PIECE OF THE COMPILER ACTUALLY WORKS — the map

**This is the section that saves the most time.** A single decision in this
area ("should this variable become a helper") requires knowing eight things
spread over ~8,000 lines in four modules, and rebuilding that picture from the
source is what eats a session's context before any work starts. Read this
instead. It is a map, not a spec — if it disagrees with the code, the code
wins and this gets fixed.

### The two paths, and which one you are measuring

```
piston JSON
   |
   +-- analyze.py ........ TRANSCODER reader. statement -> branch IR.
   |                       Default. This is what ships today.
   |
   +-- spec.py ........... INTENT reader. piston -> Promises.
        |                  Only reached when PISTONCORE_INTENT_EMIT=1.
        v
   emit_intent.plan() ..... groups Promises by WHAT WAKES THEM -> branch IR
        |
        v
   emit_yaml.compile_yaml() . branch IR -> YAML (both paths converge HERE)
        |                     falls through to emit_pyscript on NotYetImplemented
        v
   templates/compiler/yaml/classic/*.j2 -> the actual text
```

**Both readers converge on the SAME emitter.** So a fix in `emit_yaml` helps
both paths, and a fix in `spec.py`/`emit_intent` helps only the intent path.
**Any measurement taken without `PISTONCORE_INTENT_EMIT=1` is measuring the
transcoder** — that trap burned a whole earlier session.

### Who answers which question — go straight to the right module

| question | lives in | note |
|---|---|---|
| what does this piston PROMISE | `spec.read()` -> `Promise` | wakes_on · gated_by · devices · values · after · per_device · order |
| is this value built from itself | `spec.Promise.accumulates()` = `writes ∩ reads` | reads come from `spec.value_names()`, which walks the JSON's own `t:"x"` operand tags — **structural, not text** |
| which promises are ONE report | `emit_intent.report_groups()` | `per_device and accumulates()`. Content-blind — verified by renaming everything in piston 38 |
| held-state pairs (on-edge + delayed off-edge) | `spec.behaviours()` -> `Held` | collapses two promises into HA's `for:` duration |
| does this variable outlive its statement | `resolve.variables_needing_helpers()` -> `resolver.helper_vars` | **the ONE place. Never re-derive it.** Over-flags on purpose |
| where is every variable read/written | `resolve.variable_traffic()` | ⚠ detects READS by regexing the name over `json.dumps(node)` — a variable called `Message` matches its own name inside a notification's text. Known-suspect |
| which helper domain for a type | `resolve._HELPER_DOMAIN` | 9 types -> 4 input_* domains; lists -> input_text |
| hash / name -> entity id | `resolve.entities_for_attr()`, `_hashes()` | an unknown ref becomes an inert PLACEHOLDER and is recorded in `resolver.unresolved` — it does NOT fail the piston (ruled 2026-08-01) |
| webCoRE expression -> Jinja | `expression.JinjaTranspiler` | `$device` handled in 3 places: name, `[$device:attr]`, bare device ref |
| webCoRE expression -> Python | `expression.ExprTranspiler` | PyScript band |
| how a reading is spelled | `resolver.read_expr(entity, attr)` | `states()` vs `state_attr()` — one place |
| a command -> an HA service | `resolver.service_spec()` | vocab miss = pass the name through RAW, not an error |

### The variable lifetime decision, end to end

This is the decision that took a whole session to reconstruct:

1. `resolve.variable_traffic(piston)` walks every statement -> `(decls, written, read)`
2. `resolve.variables_needing_helpers()` -> crosses if `read - written` is
   non-empty **OR `len(written) > 1`** ⚠ (the second is a shortcut: it cannot
   tell "statement 20 reads what statement 1 left" from "statement 20 builds
   its own", because the walk records WHICH statements touch a variable, not
   the order inside one. 12 of 28 corpus helpers are flagged by this alone.)
3. `Resolver.__init__` stores it as `self.helper_vars`
4. `emit_yaml._set_variable` refuses only if **`spec.value_names(value_op)`
   contains the name AND it is in `helper_vars`**
5. not helper-backed -> plain HA `variables:` · helper-backed -> `_helper_write()`
   -> a service call on the helper entity
6. `expression.py:~781` reads a helper-backed variable back from its entity

**Where the bodies are buried:** `_HELPER_DOMAIN`, `variables_needing_helpers`
and `typed_value` are from 2026-08-03 and well-exercised. `variable_traffic`,
`unassigned_locals` and `_resolve_named_thresholds` landed **2026-08-22** and
today's commit also refactored the guts of the settled part while claiming
"logic unchanged" — unverified. `git log -S "<symbol>"` before trusting any of
it (Jeremy: *"the recent work could be carying the drift"*).

### The gates, and what each is blind to

```
python test_compile_snapshots.py                  # drift only. baseline on disk is STALE (24 report drift)
python test_intent_probe.py --section statements  # GATE, exits non-zero
python test_intent_probe.py --section commitments # the only check that sees a SILENT DROP
python test_intent_probe.py --section maintainability  # what a human inherits
```

**None of them prove behaviour.** All of them use ONE synthetic device
(HARD_RULES §13). Every silent drop this project has had passed all of them.

### Reading a piston by hand — the two commands worth knowing

```python
p = json.load(open('test-pistons/38_Low_Battery_Check.json'))['piston']  # NOTE the ["piston"]
spec.read(p)                      # the promises
emit_intent.report_groups(spec.read(p))   # the reports it recognises
```
Recursive-scan the whole dict for `c == "setVariable"` to find accumulations —
walking only the obvious keys misses the ones inside `each`/`ts`/`fs`.

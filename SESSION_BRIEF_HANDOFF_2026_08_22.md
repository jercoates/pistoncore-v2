# SESSION BRIEF — handoff, 2026-08-22

Written at the end of a session that went badly. Read the whole thing before
touching the compiler. The useful part is not what got fixed; it is the two
traps that made a working compiler look broken, and one real design finding.

---

## 0. THE TRAP THAT WASTED THIS ENTIRE SESSION

**Direct name matching.** Jeremy, 2026-08-21: *"you keep locking on to direct
name matches that is the real problem."*

It is in the code, not just in how I searched:

- `emit_yaml.py` ~2590 decides "this variable is built from its own previous
  value" with `re.search(r"\b" + name + r"\b", source)` — a substring search
  for the variable's NAME in the expression text. The comment above it admits
  the fragility (word boundaries were added so `count` would not match inside
  `mycount`).
- `resolve.variable_traffic` (extracted this session from
  `variables_needing_helpers`) detects *reads* by regexing the variable's name
  across `json.dumps()` of a node. A variable counts as read if its name
  appears anywhere in that blob — in a message string, a label, another
  variable's text.

**Consequence: the "does this variable cross a run" answer cannot be trusted**,
and that answer is load-bearing for the fix described in §2.

`spec.py` already has the right layer — `accumulates()`, "builds a value out of
its own previous value", derived from the READING rather than from text. The
first job of the next session is to check whether `accumulates()` agrees with
the regex. If they disagree, the regex has been quietly wrong about which
variables persist, and that is the actual bug.

Same failure shape everywhere else it appeared today: hunting `last_reported`
by its name instead of asking what field carries "when did this last report";
scoring bench clones by name tokens, which gave `38_Low_Battery_Check` FOUR
devices when it needs 67 and made healthy code look broken.

## 1. THE OTHER TRAP: measuring the wrong band

**The intent path is behind `PISTONCORE_INTENT_EMIT`.** Every compile run
without it measures the transcoder. Most of a whole session was spent reporting
numbers from the wrong band, against work that lives on the intent path.

Second half of the same trap: **the corpus is stripped** (numbered device
slots). If the bench pool does not cover a piston's slots, it fails for lack of
devices and looks like a compiler bug. Check slot coverage BEFORE concluding
anything about a piston.

## 2. THE REAL FINDING — the report / "build a sentence" pattern

This is the key pattern for multiple pistons (battery checks, "which doors are
open", smoke/CO status). Status: **recognised, not delivered.**

- The reading is correct. For `38_Low_Battery_Check`, `spec.read()` yields 8
  promises, 4 accumulating, and `emit_intent.report_groups()` returns **2**
  reports — `BatteryDevices` and `Smoke_CO` kept separate, exactly as commit
  `009620a` describes. `a61_Paul_Doors_Left_open` returns 1 and is the ONLY
  piston in the corpus that emits the template today.
- Commit `009620a` said so at the time: *"not yet visible in emitted YAML
  because those pistons still fail later on other gaps, so this is wired and
  unproven rather than delivered."* Still true. Verified by bisecting every
  commit from `009620a` to HEAD: the count is 1 at every single one. **Nothing
  regressed. It was never delivered.**
- The blocker is the refusal in §0: `Battery_Status` self-references, so it
  routes to PyScript.

### The design correction (Jeremy, 2026-08-21) — this is the important part

The refusal's premise is WRONG for this pattern. Its reasoning is "built from
its own previous value, which only persists between runs under PyScript". But:

> *"for the batteries the current value is pulled, the last state is only
> needed for the last time it reported aka the battery died"*

The report reads every battery **live, at the moment it runs**, and assembles
the message start to finish inside ONE execution. Nothing needs to survive to
the next run. That is exactly what `accumulate.j2` already does (namespace +
for + join). **No helper, no persistence.**

Measured: `Battery_Status` written in stmt 1, read in stmt 1 — does not cross.
Same for `Battery_Status_Smoke` (stmt 17). `variables_needing_helpers` already
returns "no helper needed" for both. The blanket refusal never asks.

### Why the earlier fix was reverted, and why that reason may not apply

The code comment records: helpers were tried 2026-08-08, worked, moved 3
pistons to YAML, and were **reverted** because two were smoke/CO and water-leak
pistons and the YAML band silently drops their spoken alarm. "Fix the speak
drop first, then this becomes a clean win."

That concern was about HELPERS moving everything indiscriminately. A gate on
"does it actually cross a run" moves only the safe ones. Measured:

| piston | speaks? | self-ref variable | crosses runs? |
|---|---|---|---|
| `62_Smoke_Co_Detected` | **yes — `playText`** | `Smoke_Status` | **True** → stays on PyScript |
| `38_Low_Battery_Check` | push only | `Battery_Status`, `_Smoke` | False → moves |
| `a10_Battery_Check` | push only | `Battery_Status` | False → moves |
| `a36_Guest_Monthly_Mode_Check` | push only | `Notify` | False → moves |
| `03_Auto_Arming_Check_GPT` | no | `unlockedList`, `doorsOpenList` | True → stays |

The speaking safety piston is untouched. **BUT** every "crosses runs" value in
that table came from the regex in §0. Re-derive from `accumulates()` before
trusting it.

### Still unbuilt: the dead-battery case

A dead battery does not report a low number — it stops reporting, and its last
value sits frozen. So the pattern also needs "when did this device last
report". HA carries `last_reported` per entity (present on the bench; it moves
even when the value is unchanged, unlike `last_changed`). **The compiler does
not know that field exists** — it uses only `last_changed`/`last_updated`.
`38` does not currently ask the question either. New capability, not a
regression.

Real data from Jeremy's hub (read-only, 71 battery devices): `light sensor` is
at 20% AND silent for 189 hours — low and dead at once. Four devices carry no
timestamp at all (`Front Door (old)`, `Back Door (old)`, `Reloading 2`,
`Kitchen Window`) and cannot be judged either way; do not treat them as silent.

## 3. VERIFY AGAINST HA, NEVER AGAINST THE COMPILER

A piston can compile, deploy, report `status: deployed`, and be **disabled by
HA at setup**. The compiler cannot see that. Found this way: four lux-gated
night lights reported healthy and were dead in HA.

- Liveness = read the automation back from HA. Identity is `attributes.id` ==
  the emitted `id:`, never the alias (COMPILER_DECISIONS_DEPLOY.md).
- Check EVERY part: each automation the piston split into, AND its helpers.
- **Blind spot:** the PyScript band creates no automation entities, so an
  entity-based liveness check reports every PyScript piston as "dead". That is
  the checker, not the piston. A PyScript liveness check does not exist yet.
- `_synthetic_maps` fabricates devices. Anything measured through it proves
  nothing about real behaviour.

## 4. WORKING TREE — uncommitted, nothing pushed

All of it is from this session; the tree was clean at the start.

| file | change | verified? |
|---|---|---|
| `resolve.py` | `variable_traffic()` extracted from `variables_needing_helpers` (one walk, two callers) | logic unchanged, but see §0 |
| `resolve.py` | `unassigned_locals()` — locals nothing ever assigns, coerced by declared type | yes |
| `resolve.py` | `typed_value` extended: time/date/datetime/string/dynamic/device + per-element list coercion | unit-tested only |
| `resolve.py` | `minutes_hms()` canonical; `ALL_TYPES` (19); `unhandled_variable_types()` | corpus: 0 unknown types |
| `analyze.py` | `_resolve_named_thresholds()` pre-pass — fills operands naming an unassigned local | yes, on the bench |
| `emit_yaml.py`, `emit_pyscript.py` | their minutes-to-clock copies now delegate to `minutes_hms` | compiles |
| `webcore_vocab.json` | cover `by_supported_features`: OPEN(1)/CLOSE(2) → `windowShade` | yes, on the bench |
| `COMPILER_TODO.md` | two findings appended | n/a |

**A/B against HEAD, same pistons, same real device map, same globals:
63 YAML / 8 PyScript / 83 errors BOTH SIDES. Zero regressions.** 14 pistons
emit different text, all improvements:

- the four lux night lights gained `below: 20` / `above: 20` and the equal-edge
  template trigger — they were emitting a `numeric_state` with NO bound, so HA
  disabled the whole automation, silently, while the compile reported success
- **`a10_Battery_Check` was emitting `battery < None` on every device** — now
  `< 80`, `< 25`

`typed_value`'s contract CHANGED: it used to return `None` ("leave it alone")
for `string`, `dynamic` and lists. Callers that branch on `None` now behave
differently. **Not audited.** That is the highest-risk edit in the tree.

## 5. TEST PASS STATE

The plan (Jeremy): stage the tests — find sets of pistons using the same
devices, run them with the fewest clones, tear down, next batch. 35 rounds.
For each piston record: (1) does it work, (2) does it match intent, (3) errors.

Round 1 of 35 complete: 25 pistons → 16 deployed, **15 alive in HA**, 1
unverifiable (`a29`, PyScript band), 9 compile errors (`alarmSystemStatus` ×2,
`$hsmStatus`, `systemStart`, `happens_daily_at`, `selectLiveview` ×2,
`setVolume`, `outlet1On`). Rounds 2–35 not started.

Behaviour — "does it match intent" — was NOT done for round 1. Alive is not
correct. And read intent from the piston JSON directly: using `analyze.py` to
decide what a piston MEANT and then checking the compiler against it is
circular, and hides exactly the bugs being hunted.

## 6. BENCH

Own dev instance on Jeremy's PC (`localhost:8124`), config under the session
scratchpad. Disposable — DEV_BENCH prescribes the cleanup used here (overwrite
`automations.yaml` with `[]`, reload, delete orphaned registry rows, restart).

Added this session: 5 capability clones (presence, cover, colour light with
lux+motion, buttons, speaker), 67 battery devices, and a Google Translate TTS
config entry with `tts_engine` set in PistonCore settings.

Bench gotchas found: `device_tracker` entities arrive tagged
`entity_category=diagnostic` from the virtual integration, so the pipeline
excludes them and presence devices never reach the picker (that is the FORK's
tagging — separate repo, ha-virtual-test-devices). Virtual `event` entities
need `class: button` or they are not recognised as buttons.

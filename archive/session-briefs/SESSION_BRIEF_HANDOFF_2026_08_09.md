# Handoff — 2026-08-09

Read `HARD_RULES.md` and `DEV_BENCH.local.md` **before touching anything**.
Supersedes the 2026-08-08 handoff (now in `archive/session-briefs/`).

This file exists because a context compaction destroyed the operational
knowledge mid-session — which bench is which, how to drive it, what had already
been decided — and the session then rediscovered problems it had fixed hours
earlier, "corrected" a doc that was right, and deleted its own working test
files in a panic. **Section 1 is the part that got lost. It is first for that
reason.**

---

## 1. HOW TO FIND AND RUN THE CORRECT DEV

### The bench is already running. Do not build a second one.

| thing | where | rule |
|---|---|---|
| **Dev bench** | Docker `pc-testha`, **http://localhost:8124** | **YOURS.** Break it freely. |
| Jeremy's TEST HA | see `DEV_BENCH.local.md` | HIS. Ask every time, even to read. |
| Production HA | see `DEV_BENCH.local.md` | NEVER. |
| Jeremy's LIVE Hubitat | see `DEV_BENCH.local.md` | Reads free. **Every write needs permission.** |

> Addresses, ports and the Maker API app/token live ONLY in
> `DEV_BENCH.local.md`, which is gitignored. **This repo is public.**

**THE NAME TRAP:** the container is `pc-testha` but it is the BENCH and it is
yours. `.65` is his. They sound identical.

`pc-testha`'s `/config` is bind-mounted from an **old session's scratchpad
path**, so after a compaction it looks like someone else's box. It is not.
Jeremy also runs pistons on it — look before overwriting, don't build another.

```bash
docker ps -a --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'
docker inspect -f '{{range .Mounts}}{{.Source}}{{end}}' pc-testha   # the /config path
MSYS_NO_PATHCONV=1 docker exec pc-testha ls /config   # git-bash mangles /config without this
```

**Bench HA token:** in `DEV_BENCH.local.md` (gitignored, so it never survives a
summary — go read the file). `data/config.json` points at `.65` and is **NOT**
the bench; taking the address from it has cost a full test cycle twice.

### Run PistonCore against the bench

`PISTONCORE_DATA_DIR` defaults to `C:\pistoncore-userdata` — that is Jeremy's
real store. Use a throwaway one:

```bash
SP=<my scratchpad>
mkdir -p "$SP/pcdata"
cat > "$SP/pcdata/config.json" <<JSON
{"ha_url":"http://localhost:8124","ha_token":"<bench token>",
 "write_mode":"local","ha_config_path":"<bench /config path>"}
JSON
PISTONCORE_DATA_DIR="$SP/pcdata" PISTONCORE_INTENT_EMIT=1 \
  .venv/Scripts/python.exe -m uvicorn shim.main:app --host 127.0.0.1 --port 7811
```
Ports 7802/7803 are often already taken — a bind failure still answers 200 from
whatever else is there, so **check the port is yours** before trusting a result.

### Drive it the way a user does — not by calling compiler functions

- **Save = compile = deploy**, one call, the editor's own endpoint:
  `GET /intf/dashboard/piston/set?id=<pid>&data=<base64(json)>`
  Status afterwards: `GET /api/compile-status/<pid>`.
- **Build devices:** `POST /api/test-devices/setup`, then
  `POST /api/test-devices/create {"type":..,"name":..}`.
  Types come from `shim.routes.pages.TEST_DEVICE_TEMPLATES` (20 of them:
  `Motion sensor`, `Light / dimmer`, `Illuminance sensor`, …). Guessing a type
  name returns `{"error":"Pick a type and a name."}`.
- **Clone REAL devices** rather than inventing shapes (Jeremy: *"virtual test
  devices can clone my devices"*): `/api/test-devices/discover` +
  `create-twin`, or read shapes straight off the hub via its Maker API
  (address, app id and token in `DEV_BENCH.local.md`; 178 real devices,
  READ endpoints only). The bench already carries clones:
  `Hue Gradient`, `tc motion 1`, `Test — Timer Motion`, `tc lux`, `Big Ass Fan`.
- **Fire triggers:** binary sensors use `virtual.turn_on` / `virtual.turn_off`
  — **`virtual.set` does NOT drive a binary_sensor** and raises a 500 naming the
  entity, which reads like the device is missing. `virtual.set` is for sensors.
- **The bench runs UTC** and is hours off the host clock. Compute any time
  trigger from HA's own clock (`POST /api/template {{ now() }}`) or the trigger
  lands in the past, nothing happens, and the test "passes" silently.

### Two hazards that will waste your day

**A deploy REWRITES the shared helper file.** `compile_and_deploy` reconciles
`pistoncore_packages/pistoncore_variables.yaml` from the compile-status list of
*the instance doing the deploying*. Deploying one piston from a throwaway
instance **silently deletes every other piston's helpers** — on 2026-08-09 that
removed 34 definitions including the `binary_sensor.pistoncore_*_cave_motion`
groups three Cave automations use as their turn-off trigger. Everything still
compiles and validates; the off-half just stops firing.
*Prevention:* pre-seed the throwaway's `compile_status.json` with the helpers
already on the bench (rebuild them from the deployed automations: a
`binary_sensor.pistoncore_<pid>_<var>` in a trigger is a group whose MEMBERS are
the raw entities on that automation's `to: "on"` trigger).

**Stale automations shadow your test.** The bench had 149 enabled automations;
an old one on the same light turned it off mid-test and looked exactly like a
compiler regression. **Disable everything except the automation under test.**
As of 2026-08-09 all but one are `automation.turn_off` — nothing was deleted;
`automation.turn_on` or a reload brings them back.

---

## 2. WHAT WE ARE TRYING TO DO

Build an **intent compiler**, not a transcoder (HARD_RULES §2, repeated by
Jeremy roughly thirty times on 2026-08-09 as *"no transcoding"*).

Read what the user WANTED to happen, then build the automation Home Assistant
would naturally use to achieve it. **Same result, not same mechanism.** webCoRE
is the authority for reading intent; on emit its mechanism is irrelevant.

The shape, which two of three parts already exist for:

1. **Pass 1 — intent extraction.** `shim/compiler/spec.py`. Platform-neutral,
   emits no YAML or Python: what wakes it, what must hold, what ends up where,
   in what order, with what holds and fan-out. **Built.**
2. **Pass 2 — native synthesis.** `shim/compiler/emit_intent.py`. Decides the
   automation from the promises. **Built, but see §3 — its output shape is
   still borrowed from the transcoder.**
3. **Translation fills the slots afterwards** — hash → entity, command →
   service, `active` → `on`. Stays in `resolve.py`, the emitters, the templates.

**The test of whether it is an intent engine:** the automation count must be
derived, not copied. Measured 2026-08-09: 12 pistons emit a number of
automations that does NOT match their statement count (Cave and Hall collapse
2→1; Glass break expands 2→4; Tamper 1→3). A per-statement transcoder cannot do
that.

---

## 3. WHAT IS WRONG

**Pass 2 still hands its answer to a webCoRE-shaped struct.** `emit_intent.py`
no longer imports `analyze` (verified by grep), but it builds the transcoder's
branch IR, whose fields are webCoRE's vocabulary (`co`, `lo_type`, `value_vt`,
`duration`). The nearest-neighbour bias survives one level below where it was
cut. **This is the next piece of work and it was NOT started** — Jeremy has not
given a go-ahead.

**Routing ignores intent.** The YAML-vs-PyScript decision is made from
`analyze`'s `yaml_blockers` **before** the intent engine runs, so intent never
gets a vote on the band. The design is "read intent, then route"; the wiring is
the opposite.

**The PyScript band is not intent-driven at all.** It emits from `analyze`'s
read. Intent currently improves only the YAML band.

**Nine pistons fail on the real path** (they "compile" fine against the snapshot
harness's synthetic maps — the harness hides them):
- real gaps: `gets` comparison unimplemented (`48_Pauls_Led`, `65_Symphondisk`);
  `$hsmStatus` unimplemented (`81_test`); no mapping for `off` on
  `alarm_control_panel` (`50_Pauls_lights`)
- unproven: `departed`, `allOff`, `playSound`, `searchAmazonMusic`,
  `setColorTemperature` all hit `domain 'unknown'` because the auto-mapper found
  no bench device offering them. **Not proven broken — the mapper is the weak
  link.** A human using the import picker maps a real device.

**`input_text` is used to mimic local script variables**, which is a
transpiler anti-pattern and the direct cause of the 255-character truncation
(see §4 for why that is not an HA limitation).

**14 pistons contain work the reader gives no wake to.** Partially addressed
(see §4) but ONLY inside the intent path.

**The harnesses lie.** `test_compile_snapshots.py` reported 76/76 while the real
path reported 67/76, and the commitment gate green-lit a Cave that emitted no
turn-off at all, because it only ever tests synthetic one-command pistons.
"It compiled", "it routed" and "HA accepted it" are not behaviour (§7).

---

## 4. WHAT IS RIGHT

**Device-proven** — the only tier that means anything (§7). Fired on real
devices, through PistonCore's own save endpoint, intent engine ON:

`12_Cave_motion_V2`, remapped onto cloned real devices:
```
SINGLE  control: bright + motion  -> light stayed OFF      (rig proven)
        test:    dark + motion    -> light ON
        motion cleared: on at t+60, on at t+110, OFF at t+135   (2-min hold real)
MULTI   both sensors active       -> light ON
        A clears, B still detecting: ON at t+70, ON at t+140    (the 2026-08-08
                                     regression case — now correct)
        both clear:                 OFF by t+140
```
The group entity the intent path builds is doing the work.

**Measured** (re-runnable, not device-proven):
- 62 of 76 pistons can be emitted by the intent engine; the rest fall back
- 67 of 76 deploy through the real PistonCore; 55 land on YAML and every one
  passes HA's config check; 12 on PyScript
- 0 promises dropped and 0 invented on either path (commitment diff over the
  corpus)
- 451 promises read, 4 held pairs, nothing lost through `behaviours()`
- band split moved 61/15 → 62/14 with intent on: one piston came OFF PyScript,
  which is §3's required direction

**Decisions made 2026-08-09 — do NOT "fix" these:**
- **The gate keeps its own waking leaf** (69 of 76 pistons read "WHEN x … ONLY
  IF x AND y"). Deliberate: whether a waking leaf also needs re-checking as an
  HA condition is an EMISSION decision — with `OR` it does, with a single `AND`
  leaf it does not. Removing it breaks `OR`. A session flagged this as a bug
  hours after implementing it deliberately; it is a WARNING, not a task.
- **Vocab miss = RAW, not an error.** `resolve.service_spec` passes a
  `domain.service` name straight through. The hybrid feed hands the editor real
  HA service names precisely so nothing needs translating — demanding a vocab
  entry for a name that came out of HA asked the user to translate English into
  English (Jeremy: *"check vocab, it's not there it is raw, push the names
  through"*).
- **The intent switch defaults OFF.** `PISTONCORE_INTENT_EMIT=1`, or the
  `compiler.intent_emit` setting. It was briefly default-on, which meant an
  ordinary save would recompile a live piston through an unproven path
  (HARD_RULES §12a). The transcoder is untouched and still the shipping path.
- **A promise with no trigger gets its wake derived from its own gate**
  (`emit_intent._wake_from_intent`). `40_My_Lock` says *"back door closed AND
  back lock unlocked -> lock it"* with every leaf `ct: 'c'`. Reading that as
  "nothing wakes this" is trusting webCoRE's flag over the plain meaning — the
  contact is what changes. Intent path only; 55 → 62 pistons.

**The 255-character cap is a transpiler artifact, not an HA limitation.**
Measured on the bench: a native template over the entity list returned **297
characters untruncated**, and a deliberately long one **1473**, because a
run-scope value never touches an entity state. The cap only bites because
webCoRE's accumulator variable is mimicked with an `input_text`. Under native
synthesis the low-battery piston needs no helper and has no cap. **Do not add
the 255 limit to `routing_table.json`** — that would cement the artifact as a
permanent HA "limitation."

---

## Where the durable knowledge lives

Not here. This file is a snapshot and will rot like the last three.

- **Decisions** → `HARD_RULES.md` (first in the authority chain)
- **Why a piece of code exists** → a comment next to it (this is what stopped
  `apply_intent` being deleted)
- **Anything that might get undone** → a GATE that exits non-zero
  (`test_intent_probe.py`), because a test that goes red beats a paragraph that
  goes unread
- **Measurements and open holes** → `COMPILER_TODO.md`
- **Ownership and permission rules** → memory; they are the first thing a
  compaction eats and every destructive mistake on 2026-08-09 came from losing
  them

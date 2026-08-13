# Handoff — 2026-08-08

Read `HARD_RULES.md` (new §2a, §2b) and `DEV_BENCH.local.md` first.
Supersedes the 2026-08-07 handoff (in `archive/session-briefs/`).

Facts and measurements. Where something is unverified it says so.

---

## STATE

```
python test_compile_snapshots.py   84 compiled / 0 errored / 69 yaml / 15 pyscript / NO DRIFT
python test_intent_probe.py        4 gates pass: statements, intent, reading, commitments
python test_compile_fixtures.py    5 pass, 1 skip (HA unreachable)
```

Nothing committed. Nothing pushed. Band split moved 71/13 -> 69/15; the cause is
recorded below and is deliberate.

---

## FILES CHANGED

| file | change |
|---|---|
| `shim/compiler/spec.py` | NEW. Behaviour-spec reader (stage 3). |
| `shim/compiler/commitment.py` | NEW. Promise extractor + diff, gated. |
| `shim/compiler/intent.py` | NEW (prior session, uncommitted). Atom layer. |
| `shim/compiler/emit_yaml.py` | route D timer waits; `_accumulate_loop` refusal; `_set_hsl` generalised; `_intent_comment` added then removed. |
| `shim/compiler/routing.py` | `timer_backed_waits()`, `cancel_commands()`. |
| `shim/compiler/helpers.py` | `timer` branch in `helper_config`. |
| `routing_table.json` | `timer_backed_waits` section. |
| `webcore_vocab.json` | `presetPosition`, `setAdjustedHSLColor` fixed; `setDirection` annotated. |
| `templates/.../automation.yaml.j2` | `wait_for_event` node kind. |
| `templates/help_limitations.html` | timer-restart divergence entry. |
| `test_intent_probe.py` | `reading` + `commitments` sections and gates; colour param fix; `statement_shapes()` extracted. |
| `COMPILER_TODO.md`, `HARD_RULES.md`, `HA_LIMITATIONS.md`, `DEV_BENCH.local.md` | findings and rulings below. |
| `pattern_recovered.md` | NEW. Text recovered from a deleted file's bytecode. |

---

## MEASURED

**Reading completeness.** A walk of `s`/`e`/`ei`/`cs` only finds **465 of 507**
tasks in the corpus — **42 missing (8%)**. Work also hangs off `condition.ts`/
`.fs`, off conditions nested in groups (recursively), and off
`restriction.ts`/`.fs`. Worst: `62_Smoke_Co_Detected` 9 of 11 hidden,
`70_Water_Leak` 7 of 11, `43_Package_delivery` 3 of 3. `analyze.py` already
reaches all 507; the `reading` gate now enforces it.

**`70_Water_Leak` statement `$6`** has `len(s) == 0` — an empty body — and
carries a repeat loop, a per-device announcement and a notify inside its
condition's `ts`, nested two `ts` levels deep.

**Grammar slots read by nothing** (grep of `shim/compiler/*.py` +
`routing_table.json`, both quote styles): `odw`, `odm`, `owm`, `omy`, `to2`,
`dm`, `dn`, `wt` — **8**. Handled after all: `rn`, `tep`, `tsp`, `ctp`, `di`,
`wd`. Corpus occurrences: `odw` 19, `omy` 13, `owm` 3.

**Fall-rule verification.** `attributeTypeToOperatorGroup`: 15/15 match the
vocab. Operator `g`/`p`/`t`/`m` codes: 22 sampled, 22 match, 0 mismatch, 0
missing; traced to `reference/webcore_source_reference.groovy:2872, 2885, 2916`.

**`picker_capability_map.json`** is already in `webcore_vocab.json` as
`_picker_rules` (20 domains), commit `1d9ecbb`. Not a separate file.

**Spec reader coverage.** 459 tasks (excluding waits) -> 459 promises across the
corpus, 0 pistons disagreeing. 68 shape×device-count combinations from the vocab
(all statement types, all within-type variants, 11 placements; 1-device and
3-device forms): 0 failures. 25 device-bearing promises in the 3-device sweep:
all 3 devices present on both action and condition subject, 0 lost.

---

## VERIFIED ON A DEVICE

**Route D (cancellable waits).** Bug reproduced first: with TCP `n` (automation
mode `queued`), `cancelTasks` fired, was accepted, and the cancelled turn-off
ran anyway. After the fix, both directions:
```
cancelled      light stays ON   pending work never ran
not cancelled  light goes OFF   ordinary wait still works
```

**`odw` dropped.** Same rig, only the allowed-day list differs:
```
control  allowed = TODAY      -> fired, light ON   (rig proven)
real     allowed = NOT today  -> FIRED, light ON   (restriction lost)
```
Emitted YAML contains no day condition. `42_New_School_piston`
(`odw:[1,2,3,4,5]`) and `68_Wake_up_Light` are affected.

**Restriction gating** (nested and statement-level): satisfied -> light on,
unsatisfied -> light off, both shapes.

**Bench facts.** HA container runs **UTC** and was **6 hours ahead** of the
Windows host. A fire time computed from the host clock lands in the past and
nothing runs, which is indistinguishable from a restriction working. Get HA's
time from `POST /api/template {{ now() }}`. For any "must NOT happen" test a
control is required.

---

## FIXED

**`_accumulate_loop` dropped every sibling task.** It kept only the
`setVariable` in a loop body and discarded the rest.
`11_Carbon_Monoxide_detected` and `29_Gas_Detector_2` emitted no `tts`, no
`speak`, no `volume`, no `media_player` — verified by grep of the emitted YAML,
and present in the COMMITTED baseline, so pre-existing. Now refuses the mixed
shape and routes to PyScript. **This is the 13 -> 15 PyScript change.**

**Route D.** `cancelTasks` -> `timer.cancel`; `wait` -> `timer.start` + wait on
`timer.finished`/`timer.cancelled` + a `wait.trigger.id` guard that stops the
run on cancellation. `cancelTasks` no longer halts the current run. 5 pistons
drifted, snapshots re-recorded.

**Vocab.** `presetPosition` requested `$1` with zero declared parameters —
could never emit; now a fixed 50% position (tagged assumed).
`setAdjustedHSLColor` had `setAdjustedColor`'s mapping (`rgb_color: $1|hex_rgb`
where `$1` is a hue number) — now shares `_set_hsl`, which was generalised to
match vocab fields by `$n` token.

---

## NOT DONE / KNOWN HOLES

**In `spec.py`:**
- and/or/xor group operators are **discarded** — groups are flattened to leaves,
  so "motion AND dark" and "motion OR dark" produce identical specs.
- expression parameters read as `None` (`p[].c` only; `e`/`x` not carried).
- the waking test is duplicated into `gated_by`.
- nothing emits from it.

**Untested:**
- `spec.py` has had no bench run.
- multi-device tests used three synthetic hashes, not a real HA device-registry
  group or an `@global` list.
- `@global` device lists cannot be expanded from the piston alone.
- statement restrictions: 0 of 84 corpus pistons use them, so no corpus-based
  gate covers them.

**Deliberately not attempted:**
- `setDirection` — mapped to `fan.set_direction`, inert (`$1` with no declared
  parameters, so it always reaches the driver passthrough). No capability row
  references the command, so it is driver-advertised and both a fan and an LED
  strip can offer it. Removing the mapping made both bands refuse the command,
  breaking HARD_RULES §4; it was restored with the hazard annotated.
- Catching `UnresolvableDevice` at the generic command path: re-routes 19
  commands off PyScript onto the raw driver.
- Accumulators given a helper entity: built, worked, moved 3 pistons to YAML,
  reverted because two were safety pistons hitting the accumulate-loop bug.

---

## PROVENANCE WARNINGS

**Another chat's content is not fact** (CLAUDE.md, Jeremy 2026-08-08). A
transcript from a different session was pasted into this one containing a
6-step "scan" for reading intent and claims about prior art. **None of it was
verified here.** Do not treat it as method or as evidence.

**v1 documents are leads, not answers** (HARD_RULES §10e). Two were supplied
this session. `picker_capability_map.json` was already folded into the vocab.
`WIZARD_MENU_FALLS_RAW_EXTRACT.md`'s fall rule verified as above; the same file
also carries v1 **wizard** decisions ("aggregation bar: Any/All/None only",
"intersection-only") which are product choices, not webCoRE facts, and one of
which contradicts webCoRE's `g:` set.

**`pattern.py` was built, then deleted without authorisation.** Its text is in
`pattern_recovered.md`. It classified pistons into seven invented shapes by
matching sequences of outcome atoms; it did not read `ts`/`fs`, restrictions,
loops or group operators.

---

## RULINGS RECORDED THIS SESSION

- **HARD_RULES §2a** — the statements as built carry the intent; the picker
  cascade defines the bounded forms; the forms are derivable from
  `webcore_vocab.json`; no single dimension is the whole.
- **HARD_RULES §2b** — no model in the compile path; HA runs on hardware that
  cannot host one; the reading must be deterministic; the intent step must
  produce everything needed to write the YAML.
- **Do not create more translation JSON files** — new translation data goes
  into `webcore_vocab.json`. Hard-code only what HA cannot rename.
- **Test with more than one device**; the probe's single synthetic device is a
  stated blind spot.

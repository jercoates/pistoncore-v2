# Compiler TODO

> ## ⚠ READ BEFORE CHANGING ANYTHING
> **This spec may be out of date, and may be MISSING decisions that were made
> but never written down.** A spec can tell you what to **build**. It NEVER, on
> its own, authorises **undoing** something that already works.
>
> If the code does something this document doesn't mention, that is most likely
> a real decision — check `git log -S "<the thing>"` first, then **ASK JEREMY**.
> **Never delete working behaviour without his explicit go-ahead.** (Removing
> genuinely dead code is fine.)
>
> Standing decisions that outrank this document: **[HARD_RULES.md](HARD_RULES.md)**

One list, kept current. Add to it when something is found; strike items when
they're built AND verified. The aim is to get this short enough that the
unstarted features can start.

**Always:** run `.venv/Scripts/python.exe test_compile_snapshots.py` before and
after every change. It must say NO DRIFT, or you changed output for pistons you
weren't touching. Baseline: **76 compiled / 0 errored**, bands `{yaml: 61,
pyscript: 15}` (re-measured 2026-08-10). The corpus is **76**, not 84 — eight
pistons moved to `test-pistons/manual-run/`. Every earlier figure in this file
counted against 84 and is stale by that much.

> **⚠ THE SNAPSHOT BASELINE ON DISK IS STALE — 24 PISTONS REPORT DRIFT.**
> Emission was changed deliberately and `test-compile-snapshots.json` was never
> re-recorded, so a fresh clone running the harness sees 24 "emitted code
> changed" lines and reads it as a broken compiler. It is not. Do NOT blind-run
> `--update` to silence it: that blesses changes nobody has reviewed. Work out
> what those 24 changes are, with the commitment checker watching, then
> re-record deliberately.

**Also run `python test_intent_probe.py --section commitments`** (built
2026-08-08). It is the only check that can see a SILENT DROP: it states every
promise the piston makes — *this device ends up X · on this event · after this
delay* — states the same list from the emitted YAML, and fails when the two
differ. Every drop this project has had compiled perfectly and passed
everything else, so "it compiled" was never evidence. It also prints three
things that are divergences rather than bugs and so do NOT fail the run:
raw-driver passthroughs, moved targets, and one promise emitted as a branch.
Its stated blind spots: gates/wakes are recorded but not yet compared, and it
does not read the PyScript band, so anything routed there is counted as
unchecked, never as passed.

**Also run `python test_intent_probe.py --section statements`.** It now GATES
rather than reports: every statement shape must compile on PyScript, and the
analyzer must be able to READ every one of them. It exits non-zero when either
fails. The corpus cannot see this class of bug — on 2026-08-06 it reported NO
DRIFT on all 84 pistons while the gate caught a crash for any piston opening
with a loop or a switch.

---

## ⚠ `pattern.py` WAS DELETED WITHOUT PERMISSION — AND IT IS RECOVERABLE
**(established 2026-08-10)**

**Jeremy did not authorise this.** A session deleted `shim/compiler/pattern.py`
on 2026-08-08, wrote `pattern_recovered.md`, and claimed the file had been
recovered. It had not been: that document contains only the module's
DOCSTRINGS and constants. Every line of logic was left behind.

**HARD_RULES §1 exists for exactly this** — never delete working behaviour
without his go-ahead. The deletion also went into HARD_RULES §2a as settled
fact ("Deleted 2026-08-08"), which means an unauthorised act was written into
the file that outranks every spec. Treat §2a's judgement of the APPROACH as
still open, not as Jeremy's ruling.

**THE FULL BYTECODE SURVIVES.** `shim/compiler/__pycache__/pattern.cpython-314.pyc`
— 32,011 bytes, dated 2026-08-08, **7,652 bytes of real bytecode** across all
17 definitions: `Intent`, `_walk_tasks`, `_outcomes`, `_devices`,
`_holds_work`, `_is_recurring`, `_is_timed_revert`, `_is_announce`,
`_is_reach_out`, `_is_respond`, `_is_remember`, `_shape_of`, `_read_devices`,
`device_aliases`, `_expand`, `_related`, `read`, `coverage`.

That is the whole module, not a summary. It can be disassembled and rebuilt,
and the rebuild is CHECKABLE: recompile it and compare bytecode against the
original `.pyc`. Nothing else in this project has that kind of objective test.

**DO NOT let `__pycache__` be cleaned before this is done.** A copy is only as
safe as the next person who tidies build artefacts.

The sections below describe that module as if it were present. They are kept
because the CONCERNS are still live — but they now belong against `spec.py`,
which is what actually reads pistons today. `intent.py` says what each WORD
wants; `pattern.py` said what the PISTON wants, which is not the sum of its
words (HARD_RULES §10a).

**Shapes, not labels.** Seven, built from the bounded outcome vocabulary and
never from mining the corpus: `timed_revert`, `respond`, `announce`,
`reach_out`, `remember`, `recurring`, and `sequence` — the floor, for a piston
whose purpose cannot be named but which is still perfectly emittable.

**The whole piston is the intent (§10), and it took a real bug to get right.**
Statements are GROUPED first — by the devices they touch — and the merged whole
is classified after. Classifying each statement first was backwards: it made a
piston's purpose depend on how its author happened to split it, and read a hall
motion light as a plain `respond` because the "turn on" and the "wait, turn
off" were in different statements. Grouping first took `timed_revert` from 9
pistons to 20.

**Device use is relative, not exact** (Jeremy, 2026-08-08): statements relate
through devices they WATCH as well as ones they drive, and device-type
variables are expanded to their member hashes first, so a group name and a
member hash are seen as the same devices.

**Gated, not hoped:** `coverage()` proves every statement lands in exactly one
intent — none missing, none counted twice — and that statements inside an
intent stay in the order they were written. Across all 84: **0 coverage
failures, 0 order violations.**

**Announced per HARD_RULES §11:** the reading is written into the emitted YAML
header, where it travels with the automation and survives PistonCore being
deleted. Deliberately not load-bearing — nothing routes, emits or gates on that
text, so the reading can be improved without risking output.

### THE NEXT REAL STEP: model DATA FLOW, do not extend the shape list

**Jeremy, 2026-08-08: *"a word does not on its own show intent."*** He said it
after asking for "build a sentence for announcements" as a shape and then
immediately calling that approach dead — correctly.

The current layer maps each command to an outcome atom and matches the SEQUENCE
of atoms. That is still word-reading in a coarser alphabet. `setVariable`
becomes `remember` whether the piston is composing a spoken sentence naming the
sensors that tripped, or tracking a manual-override flag: identical atom
sequences, entirely different purposes. So "composes an announcement" cannot be
added to `SHAPES` — the words do not distinguish it, and it would be a label
that cannot be reliably detected.

**What distinguishes them is RELATIONSHIP and DATA FLOW** — which statement
writes a value another one READS, which device one statement sets and another
restores, what wakes what. Grouping already uses one such relationship (shared
devices) and that is exactly why it works. Value flow is not modelled at all.

**So the next step is a relationship layer, not more entries in the catalog.**
Adding shapes will not reach anything that depends on what a value is FOR.

### Open on the intent layer — gaps named by Jeremy, 2026-08-08

- [ ] **and / or / mixed condition groups are not read at all.** The shapes look
      only at outcomes and order; the boolean structure of the gate is ignored.
      But "if motion AND dark" and "if motion OR the door opened" are different
      things the user wanted, and that is intent by §10. `pattern.py` currently
      walks a group's children for DEVICES only and never looks at `o`/
      `group_op`. Needed before the layer can claim to read a gate's purpose.
- [ ] **THE HARNESS TESTS ONE DEVICE, ALWAYS.** `test_intent_probe.py` uses a
      single synthetic device (`DEV`) for every probe, so multi-device
      statements — groups, `g:"any"`/`"all"` aggregation, fan-out across mixed
      domains — are exercised nowhere. Jeremy: *"if you are testing single
      devices all the time that is a massive failure."* He is right, and it is
      the same shape of blind spot as corpus-scope: everything passes because
      nothing hard is asked. The probe needs a multi-device and a group variant
      of each shape.
- [ ] **"WHEN TRUE" AND "WHEN FALSE" ARE INVISIBLE TO THE INTENT LAYER**
      (`grep true_actions pattern.py` = 0). `_walk_tasks` walks an action
      tree's `then`/`else`/`body`/`cases`, but NOT the `ts`/`fs` statements
      hung on a condition — so a piston whose real work is attached to a
      condition reads as having almost no outcomes at all, and gets the wrong
      shape or falls to `sequence`.
      **This is the same silent-drop class that has cost this project most,
      rebuilt inside the brand-new layer on day one** — `ts`/`fs` went unread
      by `_cond_node` for months and lost real behaviour. It is only not a
      correctness bug here because nothing emits from this layer yet; the
      moment it does, it would be one. Fix before wiring emission to it.
- [ ] **RESTRICTIONS ARE NOT READ AT ALL** (`grep restrictions pattern.py` = 0).
      "Only when the mode is Home" is one of the plainest statements of intent
      a piston can make — it says WHEN the user wanted any of this to happen —
      and the intent layer is currently blind to it. Worse, a restriction gates
      a whole statement *including its else* (`analyze._restriction_nodes`), so
      ignoring it can make two statements look like the same intent when one is
      fenced off and the other is not.
- [ ] **LOOPS ARE FLATTENED, so "do this to EACH of these" is lost.**
      `_walk_tasks` recurses into loop bodies, so the outcomes are counted —
      but nothing records that they happen once PER DEVICE, or repeatedly. "Set
      every light in the house" and "set one light" currently read as the same
      shape. Repetition and fan-out are part of what the user wanted.
- [ ] **Nested groups are walked for DEVICES only.** `_read_devices` recurses
      through `children`, which is why a device buried in a nested group is
      still found — but the nesting itself, and the operator at each level,
      are discarded. Same root as the and/or gap above: the gate's structure is
      thrown away and only its leaves are kept.

## ✅ FIXED 2026-08-08 — the accumulate-loop silent drop

`_accumulate_loop` collapses `each device: X = X + <text>` into ONE template.
It gathered every task in the loop body, kept only the single `setVariable`,
and **discarded the rest without a word**. `11_Carbon_Monoxide_detected` and
`29_Gas_Detector_2` do `setVolume` + `playText` beside that accumulation, and
their emitted automations contained no speak, no volume, no media_player at
all — carbon-monoxide and gas pistons compiled to automations that never
announce anything.

Invisible everywhere else: the snapshot harness reported NO DRIFT on both for
weeks, because the output never changed — it was always wrong.

**Fix:** the loop body must be ONLY the accumulation; anything else returns
None and the piston routes to PyScript, which runs the loop properly.
**Cost, accepted deliberately: the PyScript band grew 13 → 15.** HARD_RULES §3
wants it to shrink, but §6 outranks — an honest PyScript route beats a silent
drop. To win those back, emit the accumulation AND the per-device actions: real
work, because the accumulation collapses to one template while its siblings
genuinely run once per device.

## ⚠ SILENT DROP: ACTIONS INSIDE NESTED LOOPS (found 2026-08-08, PRE-EXISTING)

**The YAML band loses actions nested inside `repeat`/`each` loops, compiles
clean, and says nothing.** Found by the commitment checker, confirmed against
the COMMITTED baseline — this is not new, and it is not caused by any change
made that day.

Worked example, `11_Carbon_Monoxide_detected.json`: the piston sets the volume
and speaks an alarm. The emitted automation contains **no `tts.`, no `speak`,
no `volume`, no `media_player` at all** — verified by grep, with a TTS engine
configured (an unset `tts_engine` raises honestly, so it is NOT that). Located
precisely: both tasks sit at `if > repeat:s > each:s > if:s`. `29_Gas_Detector_2`
loses 4 the same way.

**These are safety pistons.** A carbon-monoxide alarm that compiles to an
automation which never announces anything is exactly HARD_RULES §6.

**It also blocks work that is otherwise ready.** Two separate improvements were
built, verified, and then REVERTED on 2026-08-08 purely because they moved
pistons onto the YAML band where this drop then bit them:
- accumulators (`count = count + 1`) given a helper entity, which persists
  between runs — moved 3 pistons to YAML, two of them smoke/water pistons;
- `_trigger_attached`, actions hung on a trigger — moved `62_Smoke_Co`.
Both were correct in isolation (each verified on a piston with no other
barrier: promises kept, 0 dropped). Fix this loop drop FIRST, then both land
as clean wins and the PyScript band drops by 3-4.

**Do not re-attempt those two before fixing this** — moving a safety piston
onto a band that loses its announcement is worse than leaving it on PyScript,
where it works today.

## THE PYSCRIPT BAND — the real to-do list (measured 2026-08-08)

Every refusal is a missing piece of compiler, so the honest way to pick what to
build next is to ask why the 13 pistons give up. Measured, not guessed:

(Counts below were taken against the 84-piston corpus and 13 on PyScript. It
is now 76 pistons and **15** on PyScript — re-measure before relying on any
row.)

| n | why it falls to PyScript |
|---|---|
| 4 → 1 | actions attached to a condition (**3 fixed, see below**) |
| 2 | `is_any_of` on a variable |
| 2 | trigger on `alarmSystemAlert` (`executes`) |
| 2 | a variable built from its OWN previous value |
| 1 | piston-scope command `log` |
| 1 | `$nextSunset` has no HA template equivalent |
| 1 | `was_greater_than_or_equal_to` needs held-duration tracking |

**Actions attached to a TRIGGER — NOT BUILT. This section is wrong.**
**(corrected 2026-08-10.)** `_trigger_attached` exists nowhere in the code and
appears nowhere in git history — `git log -S` returns nothing. The document
contradicts itself: the entry further down correctly records it as "built,
verified, and then REVERTED on 2026-08-08". The revert is what happened. What
follows is kept as the DESIGN, which is still sound and still worth building —
read it as a plan, not as a description of the code.
Was the biggest single bucket. webCoRE runs a condition's `ts`/`fs` whenever
that condition is evaluated (:7882-7886), and a trigger node is evaluated on
every wake like any other — so it becomes an `if` on that trigger's comparison,
leading the sequence, before the statement's own body. Reuses
`_recheck_condition` (HARD_RULES §9) rather than a second reader of what a
trigger means, and carries the same documented Tier-3 approximation: webCoRE
judges a trigger against the waking EVENT, HA re-reads current state.

**This is transcoder-FLOOR work, not the intent engine** — it needs nothing HA
cannot do, and leaving it on PyScript is exactly what makes that band grow,
which HARD_RULES §3 forbids. Do not file it as intent.

**Honest result: the corpus count did not move — still 13.** Two of the three
(62, 70) got PAST this barrier and hit the next one (a self-referencing
variable); the third (44) hits a deliberate refusal, because its trigger is a
momentary event with no current state to re-read, and guessing there would be
silent-wrong. Verified instead on a piston whose ONLY barrier is this: it now
compiles to YAML with 3 promises kept, 0 dropped, 0 invented. The barrier is
genuinely gone; the corpus just cannot show it yet (HARD_RULES §5 — the corpus
is the verification vehicle, never the build scope).

**Next by size:** the self-referencing variable (2 pistons, and it blocks 62/70
which are otherwise ready) and `is_any_of` on a variable (2).

## ⚠⚠ EIGHT GRAMMAR SLOTS READ BY NOTHING — the "hidden options" census
**(2026-08-08. Jeremy: "remember to walk the restrictions and the other hidden
options most people dont use")**

Enumerate every field the grammar allows, then grep the WHOLE compiler — code
AND `routing_table.json` — for each. Anything the grammar contains and nothing
mentions is a silent drop by construction. Eight came back zero:

| field | what it is | consequence |
|---|---|---|
| `odw` | only on these days of the week | **PROVEN** — see below |
| `odm` | only on these days of the month | never applied |
| `owm` | only on these weeks of the month | never applied |
| `omy` | only in these months | never applied |
| `to2` | the SECOND duration qualifier | a two-part timing condition loses half |
| `dm` | capture MATCHING devices into a variable | the variable is never populated |
| `dn` | capture NON-matching devices into a variable | same |
| `wt` | the "followed by" option flag (`wd` IS routed) | — |

**Handled after all, do not re-report:** `rn`, `tep`, `tsp`, `ctp`, `di`, `wd`.
Most are routing signals in `routing_table.json` — the design working as
intended, not a gap.

**METHOD WARNING, it bit twice in one session:** a single-quoted grep misses
`node.get("ctp")`. Run any census BOTH ways (`grep -oE "[\"']field[\"']"`) or
it manufactures false findings. The first pass of this table claimed 13 drops;
the real number is 8.

**Corpus absence is why these survived.** 0 of 84 pistons use statement
restrictions at all, so no gate built on the corpus can ever see them. The
reading gate added today walks restriction `ts`/`fs` — but it proves nothing
about restrictions until the probe generates shapes that USE them
(HARD_RULES §5, and the single-device blind spot is the same failure).

## ⚠⚠ SILENT DROP: `odw` / `omy` / `owm` — DAY, MONTH AND WEEK RESTRICTIONS
**(found 2026-08-08 by censusing the grammar against what the code reads)**

**A "weekdays only" piston compiles to an automation that fires EVERY DAY.**

**DEVICE-PROVEN 2026-08-08** (HARD_RULES §7), both directions on the bench:

```
control   allowed days = TODAY        -> fired,  light ON   (rig works)
real      allowed days = NOT today    -> FIRED,  light ON   *** wrong ***
```

Identical rig and timing; only the allowed-day list differs. The emitted YAML
contains no day condition at all.

**THE FIRST TWO ATTEMPTS "PASSED" AND BOTH WERE WORTHLESS** — a lesson worth
more than the finding. The bench runs **UTC and was 6 hours ahead** of the
host, so a fire time computed from the host clock landed in the PAST and the
automation never ran. "The light stayed off" then looks exactly like "the
restriction held". A no-op and a pass are indistinguishable without a CONTROL,
and for any "it must NOT happen" test the control is mandatory. Get HA's own
time from `POST /api/template {{ now() }}` — never from the host, and never
from an entity's `last_updated`, which is not "now" either.

`42_New_School_piston` carries `odw: [1,2,3,4,5]` on every trigger. Emitted
YAML: `trigger: time, at: "05:20:00"` and **no day-of-week condition at all**.
It wakes the kids at 5:20am on Saturday and Sunday. `68_Wake_up_Light` is the
same. Both are on the YAML band today.

**Read by nothing.** `grep odw|omy|owm` over `analyze.py`, `emit_yaml.py` and
`emit_pyscript.py` returns **0** in all three. Occurrences in the corpus:
`odw` 19, `omy` 13, `owm` 3. Pistons that appear to keep the restriction do so
by ACCIDENT — they carry a separate time condition that happens to look like a
day gate.

These are slots on the SUBJECT operand (`lo.odw` etc.), not statement-level
restrictions, which is why every review that walked statements missed them.

**How it was found, because the method generalises:** list every key that
actually occurs on a condition node across the corpus, then grep the compiler
for each one. Anything the data contains and the code never mentions is a
silent drop by construction. That census also flagged `lo.p` (interaction —
any/physically/programmatically, **59 occurrences**) as unread; not yet
confirmed to a piston, so it is a LEAD, not a finding.

## ⚠⚠ THE INTENT READ — MEASURED 2026-08-09, THE GATE THAT MUST PASS FIRST

**Jeremy, 2026-08-09:** *"the intent being correct is the key that unlocks the
ability to make the correct automation. if it reads intent wrong it will make it
do the wrong thing. It has to be correct first."*

Everything below is a MEASUREMENT over the 76-piston corpus, so nobody has to
re-derive it. (This section exists because the same two defects were found,
written down on 2026-08-08, lost to a context compaction, and found again on
2026-08-09 — Jeremy: *"what is annoying is you compacting then finding the same
problem again and fixing it again"*.)

### 1. The waking test also appears in the gate — 69 of 76. THIS IS DELIBERATE. DO NOT "FIX" IT.

The reader keeps the trigger leaf in `gated_by` as well as `wakes_on`, so a
plain-English dump reads *"WHEN contact changes to open, ONLY IF contact changes
to open AND it is between 4:30 and 21:30"*, which looks like a duplication bug.

**It is a decision, made 2026-08-09, and the reason is in `spec.py._statement`:**
the gate stays a WHOLE TREE because whether a waking leaf ALSO needs re-checking
as an HA condition is an EMISSION decision, not a reading one — with `OR` it
genuinely does, with a single `AND` leaf it does not. Deciding it in the reader
would be that layer choosing an HA idiom, which is not its job. An earlier
reading split conditions into "wakes" and "holds" and threw the shape away,
which is what made AND and OR compile identically.

The YAML band already re-expresses those leaves correctly as
`condition: trigger id`. **Removing the leaf from the gate would break `OR`
pistons** (HARD_RULES §1: never undo working behaviour).

Flagged as a defect on 2026-08-09 by the same session that had implemented it
deliberately hours earlier, after a context compaction — Jeremy: *"you fixed it
today"*. Left here as a WARNING, not a task.

### 2. Fourteen pistons contain work with NOTHING TO WAKE IT

`03_Auto_Arming_Check_GPT`, `16_Chicken_lights_Lumen_sensor`,
`19_Claude_Alarm_checks`, `28_Fridge_temp`, `29_Gas_Detector_2`, `34_Haloween`,
`38_Low_Battery_Check`, `40_My_Lock`, `43_Package_delivery`,
`47_Pauls_Door_Chime`, `67_Video_Hall_Motion_Light`, `71_Welcolm_Lights`,
`75_claude_dont_use`, `81_test`.

They are TWO different defects and must not be fixed as one — measured by
counting `ct` on every condition node:

- **No trigger anywhere in the piston** (`ct` is `c` for every condition):
  `03` (9c), `28` (5c), `40` (6c), `43` (1c). webCoRE runs these — a piston
  with no triggers subscribes to its CONDITION devices instead. So "nothing
  wakes it" is a WRONG READ of a piston that works in Jeremy's house.
  **TO VERIFY** against the piston engine (`webcore-piston.groovy`, which is
  NOT in `reference/` — only the SmartApp parent is; ask Jeremy for it or
  confirm behaviourally).
- **The piston HAS triggers but some work lost its wake**: `16` (2t/4c),
  `38` (1t/4c), `47` (4t/5c). Work hanging off `ts`/`fs` or a nested branch is
  read without the trigger that reaches it. This is an attachment bug in the
  reader and is the more clearly wrong of the two.

### 3. One piston reads as nothing at all

`83_webCoRE_Piston__2` — `behaviours()` returns empty.

### How to re-run this

`scratchpad/intent_report.py` prints every piston's intent in plain English and
flags the suspect readings. It is the only artefact that puts the READ in front
of a human, which is the only way to judge it (HARD_RULES §2c: there is no key
to score against except Jeremy).


## Open — correctness (silent-wrong, highest priority)

- [ ] **Should an UNMAPPED command reach the device's driver? (found 2026-08-08,
      tried and reverted — needs a verified pass of its own.)**
      Today a command whose vocab mapping is BROKEN (a data spec asking for a
      `$1` the command does not have) falls through to the integration's driver
      passthrough, while a command with NO mapping at all raises and routes the
      whole piston to PyScript. Those two are the same situation to a user, and
      the second answer is the worse one.
      Catching `UnresolvableDevice` alongside `NotYetImplemented` at
      `emit_yaml.py`'s generic command path is a two-word change and it works —
      but it re-routes **19 commands** off the PyScript band onto the raw driver
      in one go. That is very likely an improvement (HARD_RULES §3 wants the
      PyScript band to SHRINK, and on a native device with no passthrough
      nothing changes at all), but it is a wide behavioural change: on a bridged
      device it means the driver silently accepts a command it may not have,
      failing at runtime rather than at compile. **Do it deliberately, on the
      bench, with the commitment checker watching — not as a side effect of
      something else.** It also makes `"ha": "n/a"` commands like
      `indicatorNever` start reaching the driver, which is exactly what
      HARD_RULES §10c predicts should happen.

- [x] **THREE BROKEN VOCAB MAPPINGS — found by the commitment checker,
      2026-08-08.** All three declared a data spec referencing a parameter the
      command does not have, so none could ever emit its service; every use fell
      through to the device's raw driver, which the compiler's own comment warns
      "fails at RUNTIME, not at compile … will silently do nothing."
      - `presetPosition` — asked for `$1` with **zero** parameters. The source
        says it sets `windowShade` to `"partially open"`
        (webcore_source_reference.groovy:2664), i.e. a FIXED value. Now emits
        `cover.set_cover_position` at 50. Tagged ASSUMED: HA covers have no
        "partially open", only a position, so 50 is the honest midpoint —
        verify against a real cover before promoting it.
      - `setAdjustedHSLColor` — its mapping was copy-pasted from
        `setAdjustedColor`, asking for `rgb_color: $1|hex_rgb` when `$1` is a
        HUE NUMBER. Now shares `_set_hsl` with its sibling (HARD_RULES §9 —
        shared, not copied), which was generalised to match vocab fields by
        their `$n` token rather than by position, plus `transition` for the
        fade. Tagged ASSUMED, not yet run against a real light.
      - `setDirection` — **still open, and NOT for the reason first written.**
        The broken part is the data (`$1` with no parameters, so it is inert
        and always reaches the driver). The first write-up also called the
        `fan` domain wrong, on the grounds that the source lists the command
        under a `//hue` comment beside the colour-loop family. **That was
        adjacency read as ownership, and it does not hold: NO capability row
        references `setDirection` at all**, so it is driver-advertised — a fan
        controller with a reverse function and an LED strip cycling a colour
        sequence can both offer it, and the `ha` array exists precisely to hold
        one mapping per domain (COMPILER_SPEC §3.1). So the gap is a MISSING
        light mapping, not a wrong fan one.
        To settle: webCoRE passes no value, so on a fan the command means
        REVERSE — the current direction has to be read and inverted, not a
        literal `$1`; on a light, find whether HA exposes any loop/sequence
        direction at all (effects are where to look). Until both are worked
        out the passthrough is doing the right thing for driver-backed devices.
        Removing the mapping outright was tried and was WORSE — both bands then
        refused to compile the command, breaking HARD_RULES §4.
      A fourth apparent finding — `setColor`/`setAdjustedColor` also falling
      through — was MY probe's fault: it fed the literal string `"test"` to a
      colour parameter, which the compiler is right to refuse. `_param_operand`
      now gives colour-typed parameters a colour. Judging a command on a value
      it should reject proves nothing.

- [x] **`was_*` family compiles as `is_*` — STALE ENTRY, struck 2026-08-06.**
      This contradicted the three DONE items below it, which fixed exactly this
      on both bands on 2026-08-04. Re-measured: the probe reports **1**
      comparison collision in total (`[yaml] changed == is_any`), not the 10
      claimed here. The entry was a leftover duplicate; the work is done.
- [x] **`remains_*` numeric family — DONE 2026-08-04.** Durationless
      `remains_above/below` (+ `_or_equal_to`) now emit a bare state trigger
      carrying their own value re-check, quarantined into their own automation
      with `mode: single` + `max_exceeded: silent` + a trailing 1s delay as the
      throttle. The noisy trigger is deliberately kept OUT of the shared
      trigger union so it cannot wake the rest of the piston. Collisions
      20 -> 16. `stays_*` was already correct (declares a duration, compiles to
      `numeric_state` + `for:`, native and silent) and was left alone.

- [x] **Same bug in range and parity — DONE 2026-08-04.** `enters_range ==
      remains_inside_of_range`, `exits_range == remains_outside_of_range`,
      `becomes_even == remains_even`, `becomes_odd == remains_odd` were the
      same crossing-vs-held collision in handlers the numeric fix had not
      touched. Fixed by REUSING that machinery, not copying it: `_HELD_OPS`
      now names every "was and still is" operator across all three families,
      `_noisy_state_trigger()` is the one place the wake is built, and every
      re-check mapping needed already existed in `_TRIGGER_RECHECK_OP`.
      Collisions 16 -> 12. The 10 that remain are all PyScript-band `was_* ==
      is_*`, which is the separate `was_*` item below; the YAML band is down
      to 2.

- [x] **`was_*` (14 operators) no longer answers the wrong question — DONE
      2026-08-04.** webCoRE walks state history backwards, accumulating time
      while each past state satisfies an inner comparison
      (webcore-piston.groovy:8255-8300, `valueWas`), so `was_less_than N for T`
      means "has been CONTINUOUSLY below N for T". Both bands were dropping the
      duration for most of the family and answering "is below N right now".
      `resolve.WAS_TO_IS` is now the one place the was_*/is_* pairing is
      written down — verified to cover the vocab exactly, no missing entries
      and no invented ones — and both bands read it.

      YAML: exact, via a watcher helper. HA has no "this predicate has held for
      T" primitive (the numeric_state CONDITION takes no `for:`), so a helper
      records WHEN the inner test became true and the piston reads the elapsed
      time. The watcher automation uses TEMPLATE triggers on the predicate and
      its negation, which fire only on the two flips — not on every sensor
      update — which is what makes one per comparison affordable.

      `last_changed` is still used where it is EXACT and free: "the state has
      been this one value". It is wrong for anything that stays true across a
      value change (a numeric bound, is_not, a list of values), which is
      exactly what `_last_changed_is_exact` decides.

- [x] **PyScript `was_*` is now exact too — DONE 2026-08-04.** It records when
      a predicate became true and reads elapsed time from that, instead of
      `_fn_age`/last_changed which restarts on every update. The stamps live as
      an attribute on the piston's OWN persisted state entity — the one already
      holding its variables — so PyScript needs no helper, no extra entity, and
      no change to the deploy contract, and the stamps survive a restart the
      same way variables do. `_was_held` fails CLOSED when a predicate has
      never been seen becoming true.

      Both bands now share `resolve.WAS_TO_IS` (the was_*/is_* pairing),
      `resolve.last_changed_is_exact` (no leading underscore — spelled
      `_last_changed_is_exact` elsewhere in this file, which finds nothing;
      corrected 2026-08-10) (which comparisons are cheap enough to
      leave alone) and `resolve.was_watcher_entity` (the identity of a watcher,
      so the two bands agree about which comparisons are the same comparison).
      Neither band has its own copy of any of the three.

- [x] **"Every day at sunrise" ran at MIDNIGHT — DONE 2026-08-06, verified on a
      live HA.** The sun event was read, discarded, and never mentioned; same
      for sunset. `_every_decorator` had a partial copy of the daily-time logic
      that looked only at the NUMBER, so a preset anchor fell through to the
      multi-day branch and became `period(2020-01-01 00:00:00, 1d)`. The
      `once(sunrise)` spelling already existed in `_trigger_decorator`; both now
      call `_daily_time_spec`. Noon and midnight came free — the hand-written
      list named only sunrise/sunset while the vocab's `presets.time` declares
      all four, so the list is read from the vocab now.

      **The offset (`lo3`) was ALSO being dropped** — "sunrise + 30 minutes"
      fired at sunrise exactly. Found by reading the sources, not the corpus
      (which contains no `every` statement at all, so it can never cover this):
      the editor renders an offset only when `lo2.t != 'c'` ("anything other
      than constants may have an offset", piston.module.js:4429-4444, signed,
      negative = BEFORE) and the engine keeps `lo3` for exactly that case
      (webcore-piston.groovy:1722-1724). Seconds come from the ONE duration
      converter; a computed offset refuses loudly rather than firing at plain
      sunrise and looking right.

      VERIFIED ON THE BENCH (Docker HA + PyScript 2.0.1, not just emitted text):
      `once(sunrise)` -> 06:02:32, `+ 1800s` -> 06:32:32, `- 900s` -> 05:47:32,
      `once(sunset + 3600s)` -> 19:09:03. And it RECURS daily — PyScript applies
      a day offset to any date-less spec (its own `trigger.py`), so `once()`
      here does not mean "once ever".

      Left open: a sun anchor on a MULTI-day cycle ("every 2 days at sunrise")
      has no PyScript spelling and now raises instead of silently running at
      midnight.

- [ ] **A subscription-less piston cannot host a watcher.** It compiles to a
      SCRIPT and deploy writes exactly one file per piston, so there is nowhere
      to put the watcher AUTOMATION. Those route to PyScript instead of
      emitting a helper nothing would ever stamp. To keep them in YAML, deploy
      needs to accept a second file per piston, with its own cleanup on delete.

- [x] **Piston-level restrictions compile on PyScript — DONE 2026-08-04.**
      They were a deliberate hard-fail ("fail loudly rather than silently
      ignore a gate"), which was the right call while unimplemented but left a
      hole in the valve: a user who FORCES PyScript for Hubitat-grade trace
      fidelity could not compile a piston with an "only execute if..." at all.
      Now gated the same way statement-level restrictions already were — one
      `if` with no else, so a failed restriction runs nothing.

      Applied to BOTH bodies. `guarded` holds the every/on bodies, which reach
      their code through their own decorators and never pass through
      event_body — gating only event_body would have left a scheduled
      statement running while the piston was restricted, which is exactly the
      silent bypass the hard-fail existed to prevent. Negated sets ('rn') still
      hard-fail, same reasoning, now with a piston-level message.

- [x] **Fade commands compile — DONE 2026-08-05.** `fadeLevel`,
      `fadeSaturation`, `fadeHue`, `fadeColorTemperature` had no `ha` mapping
      at all. A fade is HA's `transition:` on the same turn_on that sets the
      target, so it is one call to the FINAL value over the duration. Service
      and field names went in webcore_vocab.json where a user can edit them;
      only the seconds arithmetic is code, as a transform the vocab NAMES
      (`$3|duration_secs`).

      The optional "Starting level" would have been a silent drop, so the vocab
      declares `fade_from` and the compiler emits a second call ahead of the
      fade that jumps there instantly. Declared in DATA rather than a list of
      command names in Python, so a fade added for another attribute gets the
      behaviour for free. Both bands verified on both shapes.

      Commands failing on both bands: 44 -> 40. `fadeInfraredLevel` is left:
      it is a camera IR illuminator with no HA light equivalent.

- [x] **One duration converter — DONE 2026-08-05.** There were three copies of
      the "number in `c`, unit in `vt`" table. The `wait` command's copy was
      missing "d", so a wait authored in DAYS silently became that many
      seconds. Now `resolve.duration_seconds`, read by both bands and by every
      caller.

- [x] **picker_capability_map.json folded into the vocab — DONE 2026-08-05.**
      It was the last file on the vocab's clock that wasn't in it: its contents
      are `device_class`, `supported_features`, `supported_color_modes` — all
      things that change when HA RENAMES something, the same clock as the
      vocab, per the file-split rule. Now `webcore_vocab.json` `_picker_rules`.
      Underscore-prefixed, so fixtures.py strips it from the sealed dashboard
      by rule rather than by a list someone must remember to update — the trap
      that bit twice before.

      Proved neutral against a NEW device-payload harness built for it
      (scratchpad/payload_snap.py, registries from the dev bench and the test
      HA): 219 devices, 1705 attributes, byte-identical.

      Also repointed the self-repair map in pages.py, which still sent users to
      the file — the exact bug the last consolidation hit — and two help pages
      that named `picker_capability_map.json` AND `value_maps.json`, the latter
      deleted ten days earlier.

- [ ] **A split piston's PARTS must all update together on an edit**
      (Jeremy, 2026-08-07: *"we have to track the broken up pistons somehow so
      we can update all the parts on edits"*).

      **Mostly already solved, by reconciliation rather than bookkeeping** —
      checked 2026-08-07, do not rebuild it:
      - one piston compiles to ONE file holding ALL its automations, and deploy
        does a whole-file `writer.write()`, so a part that no longer exists
        disappears on the next deploy. No orphan list to drift
        (`deploy.py`, and its own comment at ~line 288).
      - a rename or band switch deletes the previous file first (~line 154/414).
      - `_verify_and_enable(auto_ids)` already proves EVERY part came back after
        reload, so a 3-automation piston is verified as 3.

      **The real gap: MIXED artifact kinds.** Today a piston is either
      automations OR a script (`kind == "script"` is whole-piston, ~line 403).
      The moment one piston emits automations PLUS a script — which the
      `work_after_wait` split rule would do if built via route B — that breaks:
      one filename, one folder, one entity domain, and the script half is
      neither written nor verified nor cleaned up.

      Route C would have avoided mixed artifacts entirely (no scripts), but it
      is reverted as unsafe — see the cancelTasks entry. So whichever route
      replaces it, check this constraint FIRST: if it emits a second artifact
      kind, the deploy/verify/cleanup path has to grow with it.

      **WIDER THAN AUTOMATIONS** (Jeremy, 2026-08-07: *"we should be tracking
      globals devices etc and where all things need to track back to the parent
      json from webcore for edit and deletion"*). Everything a piston creates or
      depends on must trace back to its parent piston JSON, so an EDIT updates
      every part and a DELETE removes every part. Current state, per artifact:

      **The two GLOBAL rows are already answered — Jeremy, 2026-08-07, and the
      code agrees. An earlier draft of this entry filed them as "unknown", which
      was wrong; do not re-open them.**

      - **Non-device globals track to the GLOBAL SAVED LIST, never to a piston.**
        They need edit-tracking on themselves and nothing more.
      - **Device globals ARE tied to pistons, and this is specced hard**
        (COMPILER_DECISIONS_HOLDING §H, which Jeremy went over carefully).

      | artifact | traces back? | how |
      |---|---|---|
      | automations | YES | one file per piston, whole-file rewrite |
      | helper entities (piston variables) | YES | reconciled — a deleted piston stops writing them, they vanish on reload |
      | scripts | PARTLY | only the whole-piston `kind == "script"` case; a piston that is BOTH is unhandled |
      | **device** globals | **YES** | `storage.update_used_by()` rebuilds each global's `used_by` on EVERY piston save (`storage.py:402`); a device-global edit returns the `affected` piston list (`dashboard.py:436-440`) |
      | **non-device** globals | **N/A BY DESIGN** | `affected` is gated on `is_device`, so a plain global edit never reaches a piston — exactly the intended split |
      | device references | **DECIDED — DO NOTHING, see below** | webCoRE's own behaviour; falls out of hashed-id design, needs no tracking code |

      **What IS still missing is §H's MECHANISM, not the tracking.** §H says a
      device global compiles to an HA `group` entity and an edit calls
      `group.set` — no recompile, no file touched. That is NOT built: device
      globals are inlined at compile time, and the interim is the
      recompile-with-prompt path (`dashboard.py`'s own comment says so:
      *"HOLDING §H's group.set design would avoid the recompile entirely; this
      is the honest interim"*). Building §H also brings its verified caveat:
      `group.set` groups do NOT survive an HA restart, so the shim must replay
      every device-global's membership on `homeassistant_started`.

      **DELETED / MISSING DEVICES — DO WHAT webCoRE DOES, WHICH IS NOTHING**
      (Jeremy, 2026-08-07; VERIFIED against
      `reference/webcore_source_reference.groovy:1757` `listAvailableDevices`).

      There is no scanner, no flag and no repair flow to build. The behaviour
      falls out of the hashed-id design that PistonCore already shares:

      - `listAvailableDevices` returns devices keyed by `hashId(dev.id)`, built
        only from devices that still EXIST. Piston JSON stores those hashes.
      - The editor resolves hash -> friendly name from that live map. A deleted
        device is not in the map, so there is no name — **the editor shows the
        hash**. That IS the notification; nothing else has to raise it.
      - **Editing and saving that statement removes the dead device by
        itself** — the picker only offers devices that exist, so it drops out.
        webCoRE does it for the user, with no pruning code.
      - **Leave the piston alone and the reference stays.** That is correct, not
        a leak.
      - **HA fails safe anyway** (Jeremy): entities go up and down under native
        automations all the time; that is ordinary HA life, not a PistonCore
        problem to engineer around.

      **This kills the design in HA_LIMITATIONS.md's "Entity ID Changes Break
      Deployed Pistons"** — a 30-minute registry sweep, an `entity_missing`
      flag, a warning on the piston list and a guided repair wizard. That
      section is stale v1 (it says "Entity IDs are stored directly on
      condition, action and for_each nodes. There is no device_map", all
      retired) and HA_LIMITATIONS is not in the authority chain. Do not build
      from it.

      **NOT OPEN — ALREADY BUILT. Do not "fix" this.** An earlier draft of this
      entry claimed the compiler hard-fails on an unresolvable device and asked
      Jeremy to rule. Wrong on both counts: he ruled in July and the code has
      done the right thing ever since.

      `resolve.py:685` — *"COMPILE AND FLAG (Jeremy, 2026-08-01). An unknown
      NAME is the same situation as an unknown HASH, which has been handled this
      way since 2026-07-19: keep the reference, let it resolve to an inert
      placeholder entity, record it as unresolved so the UI can say so. Failing
      the whole piston over one stale reference takes the working devices down
      with it."* It appends to `self.unresolved` and carries on.

      `resolve.py:700` `remembered_entity()` goes further — a device that has
      TEMPORARILY left HA keeps its place in the compiled automation (Jeremy,
      2026-07-19).

      The `UnresolvableDevice` raises that remain are a DIFFERENT problem:
      vocab mapping gaps ("no HA service for command X"), a global with no
      devices assigned, or a device that exists but has no entity in the domain
      a service needs. Those are real, actionable, user-facing errors — not
      missing devices. `__init__.py`'s "UnresolvableDevice never falls through"
      is about BAND ROUTING (it must not silently switch to PyScript), not about
      failing pistons whose device went away.

- [ ] **Flag imported pistons whose readings have no HA name — DECISION PENDING**
      (Jeremy, 2026-08-07, proposed as "maybe": *"we will have to flag them on
      save as needing to be fixed"*).

      Some readings Hubitat/SmartThings standardised have no Home Assistant
      equivalent NAME — step count/goal, sleeping, consumable/filament status,
      tilt/orientation/three-axis, touch, altitude and the finer GPS accuracy
      figures. These are integration-named in HA (fitness trackers, 3D printers
      and the like), so there is nothing stable to map to and the RAW FEED is
      the correct path — the user re-points that part of the piston at the
      reading's real HA name. Documented for users in
      `templates/help_limitations.html` ("Readings from fitness trackers,
      printers and other specialist devices"), 2026-08-07.

      The open question is whether to ALSO flag it on save. **Jeremy's
      constraint, and it is the important half:** this may fire ONLY for
      pistons IMPORTED from an old hub. A piston authored here picks from what
      the user's devices actually report, so the old hub's names can never
      appear — a flag on a natively-authored piston would always be a false
      alarm.

      Not started. Needs: a way to tell an imported piston from an authored one
      at save time, and a decision on which of the two announcement surfaces it
      uses (HARD_RULES §11 — no third surface).

- [ ] **The picker rules and the `ha` arrays still state the condition twice.**
      `_picker_rules` answers "which attributes does this device expose"; the
      per-attribute `ha` arrays answer "how is that attribute read, and how do
      its values map". Different questions — but both name a domain and (27 of
      them) a device_class, and those conditions can disagree.

      MEASURED 2026-08-05: 17 HA domains are described in both, and 13 of the
      17 already differ.

      NOT a question of access — CORRECTED after Jeremy pointed out the raw
      feed. `_custom_attribute` exposes ANY attribute HA reports, keyed by its
      raw HA name ("never silently drop what HA exposes"). A picker rule does
      not grant access; it grants the webCoRE NAME and TYPE — `contact` as an
      enum of open/closed rather than a raw key typed by sniffing the current
      value. So the risk is a name/type mismatch, which is silent: an imported
      piston asking for `level` will not bind to an attribute offered as
      `brightness`, and a comparison expecting open/closed gets on/off.

      And the vocab is the wrong side of at least one. A real Sonos shows
      `volume` from the picker rules — webCoRE's own name — while the vocab
      maps `level` -> media_player. So this is NOT "add the vocab's list to the
      picker": each of the 13 needs checking against webCoRE's own naming,
      which is the authority, and either side may be the loose one.

      Deriving the picker FROM the `ha` arrays does not work regardless: the
      picker's rule language is strictly richer (feature bits, colour modes,
      declaration attrs, unit fallback) and would lose information.

- [ ] **Throttle interval must become a Settings knob.** Hardcoded
      `_NOISY_THROTTLE = "00:00:01"` in emit_yaml.py. It renders through the
      template as a plain HA delay so it is editable in the emitted YAML, but
      every first-run/setup setting has to be editable on the Settings page
      too.

- [ ] **Advisory not yet surfaced.** A user can still pick `remains_*` without
      learning it wakes on every update. Needs the compile-time flag on the two
      existing surfaces (front-door list indicator, piston status-screen
      banner) — never a third: "wakes on every update of <entity>, throttled to
      1s".

- [ ] **Two divergences to write up** (fair-warning doc, not bugs): a
      sub-second excursion past the threshold and back inside the throttle
      window reads as "remained" where webCoRE saw a crossing; and statements
      OTHER than the one asking for `remains_*` no longer re-run on its events,
      because the noisy trigger is held out of the shared union.

- [ ] **Interaction filter (`p:'p'`) silently dropped** — "only when physically
      operated" also fires on automated changes. 7 corpus pistons use it. HA
      may genuinely not distinguish; if so it must be FLAGGED, not ignored.
- [ ] **Task `a:true` (async) silently dropped** — changes ordering. HA has
      `parallel:`.
- [ ] **`dm`/`dn` device capture silently dropped** — 0 corpus pistons, so only
      the vocabulary probe can catch regressions here.

## Open — coverage

- [ ] **29 of 79 comparison operators fail on BOTH bands** — RE-MEASURED
      2026-08-06, and the old wording here ("fail on the PyScript band") was
      wrong in a way that misdirects the work. The probe reports them as
      "COMPILES ON NEITHER BAND (real gap): 29", with a SEPARATE bucket of 14
      that YAML can't do and PyScript can — that 14 is the valve working as
      designed, not a bug. So this is a coverage gap on both sides, not a
      PyScript-totality failure. Mostly the `stays_*` family (8), the
      `remains_*` family, range/parity, and the trigger-only operators probed
      as conditions.
      NOTE the related claim at line ~26 that "`stays_*` was already correct"
      is also wrong: only the NUMERIC ones are. `stays_even`, `stays_odd`,
      `stays_unchanged`, `stays_away_from`, `stays_away_from_any_of`,
      `stays_different_than`, `stays_inside_of_range` and
      `stays_outside_of_range` all compile on neither band.
- [ ] **40 of 137 commands fail on both bands** (was written as 44 of 136;
      re-measured 2026-08-06). Really **38** — `pausePiston` and `resumePiston`
      appear in the probe's failure list only because the probe's target piston
      has never been deployed, which is a probe artifact, not a gap. Mostly
      missing vocab `ha` entries, which is editable data rather than code.
- [ ] **System variables: 60 of 99 have no HA expression yet.** They now live
      in `webcore_vocab.json` under `systemVariables`, each with a per-band
      `ha` block; 39 are implemented. Adding one is a VOCAB EDIT — no code
      change, no rebuild. Unimplemented ones keep their research `ha_lead` as
      a starting point; it is NOT wired up.
- [ ] **`$device` / `$devices` / `$index` / `$location` are context-scoped** —
      they take their value from the running trigger or loop, not from a
      lookup. Only `$device` is handled.

## Open — variables (the rest of VARIABLES_SPEC)

- [ ] **255-character entity-state cap** (§7.2) — REAL, currently masked.
      Every long-string piston lands on the PyScript band today, which holds
      variables in the module and needs no helper. That is NOT a solution:
      PyScript is the fallback, not the answer (Jeremy, 2026-08-03 — I had
      written this off as "moot", which was treating a routing failure as a
      resting place). Those pistons belong on YAML, and the cap goes live the
      moment they get there. Measured: the battery format costs 76 chars per
      device + 40 header, so it blows 255 at THREE low devices.
- [ ] **List types** (`string[]` etc.) — 9 of them, always persistent, serialise
      to JSON in an `input_text` and so hit the 255 cap immediately.
- [ ] **`dynamic` type** — no declared type to cast to; §4 says PyScript unless
      unambiguous.
- [ ] **Constants (`assignment: s`)** should inline as literals — no variable,
      no helper. Not implemented; every variable is treated as dynamic.
- [ ] **VAR-V-01, -03, -04, -05** — the remaining verification tasks. All
      runnable now that the engine source is confirmed present. One per session,
      report only, no edits.

## Open — media and files (MEDIA_FILES_SPEC, not implemented)

**The spec document itself is NOT in the repo** as of 2026-08-03 — it was written
but only pasted into a session. Save it before relying on any of this; these
entries are a summary, not the authority.

Decisions already made in it (do not re-litigate):
- Media is REFERENCED, never carried. No image or audio bytes in an entity
  state, helper, or variable — also forced by the 255-char state cap.
- **Never store an `/api/image_proxy/` or `/api/camera_proxy/` URL.** The token
  rotates every 5 minutes (HA core `components/image/__init__.py`,
  `TOKEN_CHANGE_INTERVAL`), so a stored URL dies silently — works in every
  hand-test, fails whenever the notification lags.
- Snapshots go to `/media/pistoncore/<camera>/`, **NOT `/config/www/`**. Both
  are zero-config; only one is safe. `/config/www` is served at `/local/` with
  NO authentication, so a camera capture of the house would sit behind a
  guessable URL. Needs saying in INSTALL.md *with the reason*, or the
  obvious-looking choice gets copied back in.
- Fixed filename per camera, overwritten. Makes the path a compile-time
  constant, bounds disk use, and makes `clearImages()` a no-op.

- [ ] **Pending work as a SCRIPT — only where a cancel exists.** Scoped, not a
      restructure (Jeremy, 2026-08-04: "we only have to change it when the
      cancel is in the piston"). MEASURED: **5 of 84** pistons contain a cancel
      command, and all 5 also contain a wait — that is the whole affected set.
      Pistons without a cancel keep inline delays and emit identically.

      Today a wait becomes an INLINE `delay`, which welds pending work to the
      run. That is why cancellation looks impossible: there is nothing separate
      left to cancel. webCoRE cancels pending/scheduled tasks and CARRIES ON
      (vcmd_cancelTasks, webcore-piston.groovy:7321); HA's `stop:` halts the
      run. Currently emitted as `stop:`, which over-halts — harmless across all
      84 only because every corpus use is the last action in its block, which
      is luck, not design. `cancelTasks; turn on light;` would lose the light.

      **VERIFIED BROKEN ON A DEVICE, 2026-08-07 — and the failure is the
      OPPOSITE of over-halting.** Bench test on `pc-testha`, two automations,
      one holding a pending `delay`, the other running `- stop:`:

      ```
      [STARTED  - delay pending]  waiter cur=1  light=off
      [CANCELLED - stop: ran]     waiter cur=1  light=off   <- UNTOUCHED
      [AFTER DELAY ELAPSED]       waiter cur=0  light=on    <- IT RAN ANYWAY
      ```

      `stop:` halts only the run it is IN. It cannot reach pending work in a
      DIFFERENT automation — and `_merge_branches` puts every wait-carrying
      statement in its own automation, so that is the normal case, not an edge
      one. **A piston that says "cancel the pending task" does the thing
      anyway.** Silence is the bug (HARD_RULES §6).

      It LOOKS fine in most corpus pistons for a reason that is pure accident:
      the split automation usually also subscribes to the trigger that fired
      the cancel, so `mode: restart` discards the pending delay as a side
      effect. Verified on piston 06 (`s23` cur went 1 -> 0 on the cancel
      trigger) — right outcome, wrong mechanism, and it evaporates the moment
      the cancel's trigger is not in that automation's trigger set.

      **ROUTE C — `automation.turn_off`, VERIFIED WORKING ON THE BENCH
      2026-08-07. This is the answer, and it stays in YAML.**

      Found because Jeremy pushed back on the write-up: *"it sounds like you're
      overlooking a part solution it showed you... you looked at the problem and
      not the behavior of the 2 things."* Correct — the first bench test had a
      pending timer that WAS cancelled (piston 06's `s23` went cur 1 -> 0). That
      was dismissed as luck instead of read as a mechanism, which sent the
      write-up straight to "we need scripts".

      HA's automation component defines `CONF_STOP_ACTIONS = "stop_actions"`
      with `DEFAULT_STOP_ACTIONS = True` — so `automation.turn_off` STOPS A
      RUNNING AUTOMATION'S ACTIONS by default. Bench proof:

      ```
      STARTED    cur=1   45s delay pending
      CANCELLED  cur=0   re-armed, light off   <- automation.turn_off killed it
      FINAL      light=off                     <- past the 45s. Never fired.
      ```

      So `cancelTasks` compiles to `automation.turn_off` (stop_actions: true)
      on the automation(s) holding that statement's pending work, then
      `automation.turn_on` to re-arm. The split rule already knows WHICH
      automation that is. **YAML-first is preserved (HARD_RULES §3) and the
      PyScript band does not grow.**

      Trade-off to settle before building: `automation.turn_off` cancels ALL
      pending work in that automation, not one task — fine when the split rule
      has already given the waiting statement its own automation, coarser if
      several waits share one. And there is a brief window where the automation
      is off, so a trigger arriving in it is missed. Route B (scripts) still
      wins on per-task granularity and is the only route that can express
      `cancelPendingTasks` Local/Global SCOPE, so B may still be needed there.

      A SECOND native mechanism also proved itself: re-triggering an automation
      in `mode: restart` discards its own pending delay (that is what rescued
      piston 06). Cheaper still where the cancel's trigger already reaches the
      waiting automation.

      Superseded reasoning, kept so it is not re-derived: this was written up as
      direct evidence for route B — "the continuation must be its own SCRIPT,
      because `script.turn_off` is the only thing that can reach it". **That
      last clause is FALSE**; `automation.turn_off` reaches it too.

      **ROUTE C WAS BUILT, DEVICE-TESTED AND REVERTED — 2026-08-07. Do not
      re-implement it the same way.** `automation.turn_off` + `automation.turn_on`
      emitted as a pair is UNSAFE inside a `mode: restart` automation:

      ```
      PERSON  light=on  s23_cur=0  s23=off   <- left DISABLED
      LEFT    light=on  s23_cur=0  s23=off   <- so no turn-off timer ever started
      ```

      Piston 06's `$8` and `$37` both trigger on the same sensor change, so the
      main automation re-triggers ITSELF mid-sequence. When that abort lands
      between the `turn_off` and the `turn_on`, the target automation stays off
      **permanently**. Adding a delay between them makes the window WIDER, not
      safer — tested, same failure.

      The YAML was valid, parsed, and HA accepted it. Only driving a virtual
      sensor exposed it (HARD_RULES §7).

      Reverted to `stop:`, which is still wrong (it misses the pending work and
      halts a run webCoRE would continue) but never disables anything. NO DRIFT
      after revert.

      **What a real route C needs: no window in which the target is disabled.**
      Candidates not yet tested — `automation.trigger` on the target (it is
      `mode: restart`, so triggering it discards the pending run with no
      off-state at all; the risk is that it RUNS the target's actions when its
      conditions happen to pass), or a cancel FLAG the waiting automation
      re-checks after its delay (route A, no cross-automation call at all).

      ---

      ## ROUTE D — HA TIMER HELPERS. This is the answer. (researched 2026-08-07)

      Jeremy: *"do a search on how to make ha do a proper cancel task, someone
      out there has to have found a way."* They have — it is Home Assistant's
      OWN mechanism, and the community's `automation.turn_off` advice (which
      this project tried and bench-proved unsafe) is the workaround people reach
      for when they don't know about it.

      **Source: the official Timer integration docs** (verified 2026-08-07,
      https://www.home-assistant.io/integrations/timer/):

      | service | what it does |
      |---|---|
      | `timer.start` | starts a timer, **or restarts it with a new duration** |
      | `timer.cancel` | **cancels a running or paused timer WITHOUT firing the finished event** |
      | `timer.finish` | finishes early (DOES fire finished) |
      | `timer.pause` / `timer.change` | pause / add or subtract time |

      Events fired: `timer.started`, `timer.finished`, `timer.cancelled`,
      `timer.restarted`, `timer.paused`, `timer.remaining_time_reached`.

      **The mapping is almost one-to-one with webCoRE:**

      | webCoRE | HA |
      |---|---|
      | `wait N` | `timer.start` on a per-statement timer helper; the continuation is an automation triggered by that timer's `finished` event |
      | `cancelTasks` | `timer.cancel` — no finished event fires, so the pending work simply never happens |
      | TCP cancel-on-condition-change | `timer.cancel` on that statement's timer |
      | re-trigger while pending | `timer.start` again — it restarts, which IS webCoRE's TCP=restart |

      **Why this beats everything tried so far:**
      - **No disable window.** Nothing is ever turned off, so the `mode: restart`
        abort hazard that killed route C cannot occur.
      - **It also fixes `work_after_wait`.** `timer.start` returns immediately,
        so the parent automation CARRIES ON — which is exactly webCoRE's
        scheduler model, and the thing an inline `delay` gets wrong. Route B's
        benefit with no scripts.
      - **Stays in YAML** (HARD_RULES §3). PyScript band does not grow.
      - **Timers are first-class entities**, so they go through the SAME helper
        create/reconcile path PistonCore already has for piston variables — the
        artifact-tracking problem stays solved, no new artifact kind.

      **Caveats to carry, both from the docs:**
      - Timers survive a restart only with `restore` set; and even then, an
        automation on the `finished` trigger **will not fire on startup if the
        timer expired while HA was down**. Needs a documented divergence
        (webCoRE's own scheduler behaviour across a hub restart is the thing to
        compare against — check the groovy before writing it up).
      - This changes the emitted shape substantially: a wait stops being an
        inline `delay` and becomes a timer plus a second automation. Snapshot
        drift is EXPECTED and must be re-recorded deliberately.

      **BENCH-VERIFIED 2026-08-07 — both directions, on real entities:**

      ```
      CASE 1  start -> cancel      timer active -> idle, timer.cancelled fired
                                   light=off        <- the work NEVER ran
      CASE 2  start -> no cancel   timer.finished fired
                                   light ON         <- the work ran normally
      ```

      Both halves matter. A "cancel" that also breaks the uncancelled path would
      have passed a one-sided test — which is how the `stop:` bug survived in
      the first place.

      **WHAT `cancelTasks` TARGETS — ANSWERED 2026-08-08 from the engine, do
      not re-open.** `webcore-piston.groovy:7321` sets `cancelations[ALL]=true`;
      the consumer at :3702-3712 documents the scope itself:

      > *"cancel all statement and any other pending -3,-5 events (device
      > schedules); **does not cancel EVERY blocks** -1 iN1 or $:0 condition
      > requests"*

      So `cancelTasks` is **piston-wide over statement + device schedules, and
      SPARES recurring `every` blocks and condition requests.** Route D must
      therefore cancel the timers backing waits/device schedules and leave any
      timer backing an `every` alone. Cancelling all of a piston's timers would
      silently stop its recurring work — a bug webCoRE does not have.

      ## ✅ ROUTE D IS BUILT AND DEVICE-VERIFIED — 2026-08-08

      `routing_table.json` → `timer_backed_waits` (every HA name lives there,
      HARD_RULES §8), `emit_yaml._timer_plan` / `_timer_wait_nodes`,
      `helpers.helper_config`'s `timer` branch, and the `wait_for_event` node
      in `automation.yaml.j2`.

      **THE BUG WAS REPRODUCED ON A DEVICE FIRST**, which mattered more than
      expected. The obvious test PASSES on the shipped code: the waiting
      automation usually shares the trigger that fires the cancel, and
      `mode: restart` throws the pending delay away as a side effect, so
      `stop:` is never asked to do anything. Set the piston's TCP to `n` so the
      automation becomes `queued` and the bug appears immediately:

      ```
      motion active   light=on    (turn-off pending)
      motion clear    light=on    (cancelTasks fired)
      after delay     light=off   <- the cancelled work RAN
      ```

      **Verified after the fix, BOTH directions** (a one-sided test is how the
      original bug survived):

      ```
      cancelled       light stays ON   - the pending work never ran
      not cancelled   light goes OFF   - the ordinary wait still works
      ```

      **Two things the plan above got wrong, found by running it:**

      1. **The continuation does NOT need its own automation.** The plan said
         "the continuation is an automation triggered by that timer's
         `finished` event". It is simpler and less invasive to stay in one
         automation: `timer.start`, then `wait_for_trigger` on the timer's own
         events. No structural split, so `_merge_branches` is untouched.
      2. **Waiting only for `finished` is not enough, and the failure is
         subtle.** Relying on the timeout to abandon a cancelled wait does stop
         the work — but the run then SITS THERE holding the automation until
         the timeout expires, and under `mode: queued` the next trigger queues
         behind it and fires late (measured: a light coming on ~40s after its
         trigger). So the wait ends on `timer.finished` OR `timer.cancelled`,
         and a template condition on `wait.trigger.id` stops the run at once
         when it was the cancellation. webCoRE frees the piston immediately;
         this now does too.

      **`cancelTasks` no longer halts the current run.** It was emitting
      `stop:`, which ended the statement that issued the cancel — something
      webCoRE never does (it cancels pending tasks and carries on). It now
      emits only `timer.cancel`.

      **Scope respected:** `_timer_plan` skips `every` statements, per the
      engine's own comment below. **`stop:` is retained** for pistons with a
      cancel but no timer-backed wait — `waitForTime`/`waitForDateTime` are
      absolute-time waits and are a different shape, still uncovered and marked
      as such in the routing table's `_not_covered`.

      **Verification:** 5 corpus pistons drifted (04, 06, 10, 32, 54 — every
      one that has a wait plus a cancel), snapshots re-recorded deliberately.
      The commitment checker reports those 5 as **identical before and after:
      0 dropped, 0 invented** — the mechanism changed, the promises did not.

      **Still to settle before building it:**
      - one timer helper per waiting statement, named like the existing piston
        helpers, so the create/reconcile path is reused rather than rebuilt;
      - **the restart divergence — BENCH-VERIFIED 2026-08-08, not just doc-read.**
        A 30s timer with `restore: true` was started, HA was restarted (~45s
        down), and after boot: `timer=idle`, **no `timer.finished` event, the
        continuation never ran, light stayed off.** So pending work whose timer
        expires during downtime is SILENTLY LOST. Document as a divergence
        (`/help/limitations`) in the same change that builds route D.
        ASSUMED, not verified: that Hubitat's scheduler persists across a hub
        reboot and would fire late instead — platform `runIn`/`schedule`
        generally do, but that has NOT been checked in the engine;
      - snapshot drift is expected and deliberate; re-record with `--update`.

      **The right question is not "does HA have a primitive" but "can we
      emulate it"** (Jeremy, 2026-08-04). Two routes, both real:

      A. **Cancel flag.** Guard after every delay; `cancelTasks` sets it; the
         run clears it at start. Exact semantics, but every delayed path grows
         a guard and it does not give per-task granularity.
      B. **Pending work as a SCRIPT.** A statement's delayed continuation
         becomes an HA `script`; `cancelTasks` calls `script.turn_off`, which
         cancels a running script mid-delay while the parent automation
         continues. Much closer to webCoRE's own model, and it is the only one
         that can express `cancelPendingTasks`' Local/Global SCOPE, because
         scripts are addressable individually.

      B is the answer, and gated on "does this piston contain a cancel" it is
      a contained job: detect the flag, split that statement's actions at the
      delay, emit the continuation as a script, call `script.turn_on` and carry
      on, and compile the cancel to `script.turn_off`. Everything else is
      untouched.

      Knock-on: it is also what `cancelPendingTasks` SCOPE needs, since scripts
      are addressable individually — and the split-on-wait grouping may become
      unnecessary once pending work is separately cancellable.

      **Public-release framing (Jeremy, firm): stop making the corpus work and
      dead-ending the rest.** A decision that is only correct because his 84
      pistons happen not to hit the gap is not a decision.

- [ ] **`cancelPendingTasks` GLOBAL scope** — Local works (`stop:`). Global
      reaches OTHER pistons; one automation cannot halt another's in-flight
      run, so it refuses loudly rather than doing the local thing and looking
      like it worked. Needs a real answer.
- [ ] **`media_content_type` extension→type table** — required by HA, no webCoRE
      equivalent (its track parameter is a bare URI). Infer from the extension,
      fail loudly on unknown. Table is DATA, never inline in compiler or
      template. Not built.
- [ ] **Numeric sound index (`Play Sound 12`)** — device-firmware meaning, no HA
      concept. Escape-hatch case via the custom-command mechanism, not a
      translation.
- [ ] **MEDIA-V-01** — webCoRE image store internals, `clearImages()` real scope,
      and how the `File:` notify parameter resolves to image data. Engine source
      IS now available, so this is runnable.
- [ ] **MEDIA-V-02** — can an HA notify platform attach a file from a media
      directory? **This one can overturn the `/media/` decision above.** If media
      dirs don't work for attachment, the location must be revisited — and the
      alternative still must not be `/config/www`.
- [ ] **MEDIA-V-03** — image/audio attribute types; what the engine does with an
      `image`-typed attribute assigned to a variable (no matching variable type
      exists).
- [ ] **Open question (Jeremy's call):** fixed filenames have a narrow race — a
      camera firing twice can have the second capture land while the first
      notification is still assembling, so it sends the newer image. Timestamped
      names avoid it but grow unbounded with no reaper. Arguably correct as-is.

## Open — structural (SESSION_BRIEF_ONE_READER_ONE_WRITER.md)

- [x] **Stage 1, FIRST HALF — top-level discovery is shared. DONE 2026-08-06.**
      `emit_pyscript.build()` iterates `analyze()`'s branches instead of walking
      `piston["s"]` itself. Each branch carries `raw` (the untouched statement)
      and `stmt_type` (webCoRE's own name for it — `kind` is deliberately lossy,
      an `on` block and an `if` are both kind "if"), so emission is unchanged
      and only DISCOVERY moved. That is the layer every silent drop has lived in.

      **THE PRECONDITION THAT NEARLY BIT, and the reason this took a gate.**
      The analyzer's refusals doubled as the ROUTING signal — emit_yaml aborted,
      compile_piston caught it, the piston went to PyScript with the exception
      text as the reason. Fine while the analyzer was the YAML band's private
      reader; fatal once both bands share it, because a refusal then means the
      piston compiles on NEITHER — and a user who FORCED PyScript bypasses
      routing entirely and has no fallback at all (Jeremy, 2026-08-06).

      So reading and judging are now separate: `analyze.yaml_blockers` records
      "the YAML band can't express this" as a fact on the node, and emit_yaml
      re-raises the first note VERBATIM, leaving routing and reason text
      byte-identical. **18 shapes** the analyzer could not read but PyScript
      compiles happily were fixed this way: `on` blocks, `every 90m` / `2d` /
      `1w`, `every day at <sun event>`, `xor`, switch fall-through, and any
      piston whose FIRST statement is a loop / switch / break / exit / do.
      Nine were found by hand; the other nine only by the gate — exactly half.

- [ ] **Stage 1, SECOND HALF — the nested walk.** `_stmt_nodes_unrestricted`,
      `_attached_nodes` and `_block` still walk raw statements. Known
      impedance mismatch to settle FIRST: the IR flattens an action statement
      into one node per TASK, while `_task_nodes` emits a whole statement at a
      time. Decide that with Jeremy before writing code.
- [ ] **Stage 2 — one writer per band.** RE-MEASURED 2026-08-06: ~39 HA-facing
      expressions are still Python strings — `expression.py` 11, `emit_yaml.py`
      22, `resolve.py` 5, `emit_pyscript.py` 1. **The "109-entry `_JINJA_FUNCS`"
      claim repeated here and in COMPILER_SPEC.md is WRONG: it is 24 entries**
      (expression.py:600-625). 109 is the count of webCoRE FUNCTIONS in the
      vocab, and the PyScript half of those already lives in a template
      (`expr_runtime.py.j2`). So this job is far smaller than written.
      Each band needs its OWN templates and they must not share emission
      helpers.
- [ ] **`on` blocks: the YAML handler is dead AND broken.** Routing forces
      PyScript, and `_cond_node` rejects `t:'event'` anyway.

## Open questions — need Jeremy, not code

- [ ] **Accumulate-and-announce: store or rebuild?** Deferred, NOT moot — it
      only looks answered because those pistons currently fall to PyScript.
      When they compile to YAML the question returns: storing the built list
      hits the 255 cap at 3 devices; rebuilding it inline where it is announced
      sidesteps the cap but describes the state *now* rather than *when the
      piston fired*. For a once-a-day battery sweep the difference is nil; for
      a smoke alert it is not.

---

## Done (2026-08-01 → 08-03)

- Condition-attached actions (`ts`/`fs`) on both bands — 9 pistons were
  silently losing behaviour, including the whole safety set.
- Restrictions on nested statements — read by nothing before.
- Accumulate-and-announce resolves to ONE HA template instead of unrolling the
  loop per device.
- `age()`, variable command parameters, unset optional parameters omitted.
- The invented 50-device unroll cap deleted (no HA limit backed it).
- Compile-and-flag for unknown device names, undeclared variables, blank
  `setVariable` targets — all three "damaged" corpus pistons were the compiler
  refusing input real webCoRE accepts.
- Conditions on a piston variable (emitted `{{ () }}` and a null `entity_id`).
- **Declared variable types, BOTH bands** — one shared decision, two formats.
- **Helper entities for variables that cross automations** — decision, naming,
  read/write, package template, deploy wiring with rebuild-based lifecycle,
  startup check, gated Settings action. Creation mechanism verified against a
  live HA (the REST config API cannot do it; write-plus-reload can).
- Duplicate operator tables collapsed; dead code removed.
- `webcore_vocab.json` `systemVariables` — the 91 engine system variables plus
  8 aliases the compiler accepts, each with its per-band HA expression.
- **The "or equal to" edge in HELD comparisons.** The boundary fix went in for
  `is_<=` and never reached `stays_*` / `remains_*` / `was_*`, so those pairs
  emitted identical code and a value sitting exactly on the threshold never
  fired. 27_Food_Temp_NEW watches a probe with `stays_greater_than_or_equal_to`
  and would have missed it. Found by the probe's collision check, not by any
  piston failing — nothing fails, it just quietly does not fire.
- Corpus is 84/84 sound; the "three damaged pistons" story was wrong.
- **`take` (camera snapshot)** — broken since 2026-07-26 and blocked on a
  decision. webCoRE's `take` has NO parameters but the vocab asked for `$1`,
  which never exists, and HA requires a filename. Now emits
  `/media/pistoncore/<camera>/<camera>.jpg` from MEDIA_FILES_SPEC §2.3 — the
  path lives in the VOCAB, the compiler only substitutes `$object_id`.
- **`clearImages`** — was absent from the vocab entirely, so it fell to the
  driver passthrough. Now a declared no-op per §2.4.
- **`clearImages` REALLY deletes.** Home Assistant has NO delete action of any
  kind — it writes files (camera.snapshot, image.snapshot) and reads them
  (file.read_file) and never removes them, verified against a live service
  registry. shell_command is the only route, so PistonCore declares ONE
  constrained command: the caller passes the CAMERA and the folder is fixed
  inside the command, so nothing can reach outside /media/pistoncore/.
  NOT gated: it needs no runtime PistonCore — it lives in HA's config and keeps
  working if PistonCore is removed — so it is documented in INSTALL.md instead.
  Jeremy's test: "if it can work without pistoncore working it can stand with a
  note on what it does. if pistoncore has to be there to do it that is opt in".
- **`cancelPendingTasks` (Local) → HA `stop:`.**
- **`cancelTasks` → HA `stop:`.** It was a silent no-op on the claim that
  `mode: restart` covers it; it does not — restart only fires on RE-TRIGGER,
  while this cancels on demand mid-run. `vcmd_cancelTasks` sets
  `cancellations[ALL]=true` (webcore-piston.groovy:7321) and Jeremy describes
  the effect as "stops the automation at that line", which is `stop:` exactly.
  Removed from the PyScript-only routing list — YAML does this reliably.
- **No-op commands are DATA.** `noop` / `cancelTasks` / `cancelPendingTasks`
  were a hardcoded name list in the emitter; they are now `"ha": "noop"` in the
  vocab with the reason in the note, so a user can declare one without touching
  the compiler.
- **ONE PISTON = ONE AUTOMATION.** Promotion was per-STATEMENT; webCoRE's is
  per-PISTON (`hasTriggers` computed once, webcore-piston.groovy:8771-8772,
  used at :9296). A triggerless statement was becoming its own independently
  firing automation — which is also what split a variable's write from its read
  and forced helpers that were never needed. A trigger-driven piston now
  compiles to ONE automation: every statement's triggers unioned, each
  statement's body behind its own conditions. 64 automations for 64 YAML-band
  pistons, was one per statement. Jeremy: *"the time is the trigger even hubitat
  sees that"* / *"to me 1 piston is 1 automation"*.
  Two bugs in that change, both caught by reading the emitted YAML rather than
  the counts: the 5-minute light-off wake vanished (promotion had been
  supplying it by accident; webCoRE schedules it deliberately via
  requestWakeUp, so duration-bearing conditions now emit a `for:` trigger), and
  a trigger-only statement ended up ungated so it ran on EVERY trigger —
  clearing the override flag in the same run that set it. Now gated on
  `condition: trigger, id: stmtN`, which is webCoRE's rule exactly: a trigger
  is true only for its own event.

## NEXT: PORT THE EDITOR'S RENDERER AND READ INTENT FROM IT (2026-08-08)

HARD_RULES §2f is the ruling; this is the work.

**Port from `dashboard/js/modules/piston.module.js` (SEALED — read only):**
- `renderOperand` :4109 — devices, variables, constants, expressions
- condition renderer :4259 — uses the vocab's `d`/`dd` display strings, and
  switches to the PLURAL wording via `isMultiValueOperand` when the operand is
  several devices. This is where "Any of {Water_Sensor_All}'s water" comes from.
- :4263 — the SAME duration renders "for" on a trigger, "in the last" on a
  condition (HARD_RULES §2e, edge vs state)
- :4246 — `l.p` renders "physically" / "programmatically" (`'s'` = programmatic)
- :4238 — units come off the attribute; `°?` takes the location scale
- :4266 — `comparison.t == 2` -> "for at least" / "for less than" via `to.f`
- task rendering :4541, timers :4421

**Verify by DIFF, not by eye (Jeremy, 2026-08-08 — "you can diff them yourself
faster").** The renderer is JavaScript: run it directly over each corpus piston,
capture its text, and diff against the Python port. Mechanical, objective, and
it does not spend Jeremy's time. Only bring him the cases where the two agree
but the reading still looks wrong.

**Walk from the JSON, render with the editor's words** — the editor folds
sections away, draws empty `ei`/`e` branches as real ones, and shows placeholder
restriction slots and warning bars that are not piston data.

**Live hazard to resolve while doing it:** `spec.py`'s held-state collapse turns
`changes_to inactive` + wait into `stays inactive for N` — an edge into a state.
Correct for `33_Hall_motion`; NOT safe as a general rule (HARD_RULES §2e).

**Scale reality check (2026-08-08):** 88% of the corpus touches more than one
device; fan-outs reach 69 (`38_Low_Battery_Check`), 43 (`66_Tamper_alarm`), 38
(school). Real global lists are now in `data/globals.json` (gitignored).
Anything validated on three synthetic devices has not been validated.

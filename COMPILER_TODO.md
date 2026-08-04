# Compiler TODO

One list, kept current. Add to it when something is found; strike items when
they're built AND verified. The aim is to get this short enough that the
unstarted features can start.

**Always:** run `.venv/Scripts/python.exe test_compile_snapshots.py` before and
after every change. It must say NO DRIFT, or you changed output for pistons you
weren't touching. Baseline: **84 compiled / 0 errored**, bands `{yaml: 72,
pyscript: 12}`.

---

## Open — correctness (silent-wrong, highest priority)

- [ ] **`was_*` family compiles as `is_*`** — the historical lookback is lost.
      "was open five minutes ago" becomes "is open now". 10 collisions measured
      across both bands. COMPILER_SPEC §2.5 says the discrete-sample semantics
      need PyScript's `.old` / `state_hold`; spec'd, not built.
- [ ] **`remains_*` compiles as its edge twin** — `drops_below` and
      `remains_below` emit identical code, likewise `becomes_even` /
      `remains_even`. One of each pair is wrong.
- [ ] **Boundary `=` lost in `stays_*` / `remains_*`** —
      `stays_less_than == stays_less_than_or_equal_to`. The same bug was fixed
      once for `is_<=`; the fix never reached these families.
- [ ] **Interaction filter (`p:'p'`) silently dropped** — "only when physically
      operated" also fires on automated changes. 7 corpus pistons use it. HA
      may genuinely not distinguish; if so it must be FLAGGED, not ignored.
- [ ] **Task `a:true` (async) silently dropped** — changes ordering. HA has
      `parallel:`.
- [ ] **`dm`/`dn` device capture silently dropped** — 0 corpus pistons, so only
      the vocabulary probe can catch regressions here.

## Open — coverage

- [ ] **29 of 79 comparison operators fail on the PyScript band.** Jeremy's rule:
      PyScript is a user-selectable choice for Hubitat-grade trace fidelity, so
      it must be TOTAL. Every failure there is a valve bug, not a missing feature.
- [ ] **44 of 136 commands fail on both bands** — mostly missing vocab `ha`
      entries, which is editable data rather than code.
- [ ] **System variables: 50 of 91 unimplemented.** `webcore_system_vars.json`
      has the inventory, each with an `ha_lead`. 41 have expressions; nothing
      consumes the file yet — the compiler still reads its own hardcoded tables.
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

## Open — structural (SESSION_BRIEF_ONE_READER_ONE_WRITER.md)

- [ ] **Stage 1 — one reader.** `emit_pyscript` still walks the raw piston JSON
      instead of the analyzer's IR. Measured ready: the analyzer reads every
      PyScript-band piston, and the nested-restriction hole that blocked it is
      fixed. This is the root cause of the whole silent-drop class.
- [ ] **Stage 2 — one writer per band.** 45 HA-facing expressions are still
      Python strings across `expression.py` (22 + the 109-entry `_JINJA_FUNCS`),
      `emit_yaml.py` (17), `resolve.py` (5), `emit_pyscript.py` (1). Breaks the
      moving-target rule. Each band needs its OWN templates and they must not
      share emission helpers.
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
- `webcore_system_vars.json` — 91 engine system variables extracted from source.
- Corpus is 84/84 sound; the "three damaged pistons" story was wrong.
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

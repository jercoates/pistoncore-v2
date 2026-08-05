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
- [x] **`remains_*` numeric family — DONE 2026-08-04.** Durationless
      `remains_above/below` (+ `_or_equal_to`) now emit a bare state trigger
      carrying their own value re-check, quarantined into their own automation
      with `mode: single` + `max_exceeded: silent` + a trailing 1s delay as the
      throttle. The noisy trigger is deliberately kept OUT of the shared
      trigger union so it cannot wake the rest of the piston. Collisions
      20 -> 16. `stays_*` was already correct (declares a duration, compiles to
      `numeric_state` + `for:`, native and silent) and was left alone.

- [ ] **Same bug, three more families: range and parity.** The 4 remaining YAML
      collisions are all the crossing-vs-held pair this fix just resolved for
      numbers, in handlers it did not touch:
        `enters_range == remains_inside_of_range`
        `exits_range == remains_outside_of_range`
        `becomes_even == remains_even`
        `becomes_odd == remains_odd`
      The machinery now exists and should be REUSED, not re-written: extend
      `_is_noisy_trigger()` to those families and give each a re-check entry in
      `_TRIGGER_RECHECK_OP`. Both quarantine and throttle then apply with no
      new code. Verify a re-check mapping exists for the parity ops first —
      they emit template triggers, not `numeric_state`, so that path is
      unproven.

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

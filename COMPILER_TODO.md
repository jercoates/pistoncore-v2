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
weren't touching. Baseline: **84 compiled / 0 errored**, bands `{yaml: 71,
pyscript: 13}` (re-measured 2026-08-06; the 72/12 written here before was stale).

**Also run `python test_intent_probe.py --section statements`.** It now GATES
rather than reports: every statement shape must compile on PyScript, and the
analyzer must be able to READ every one of them. It exits non-zero when either
fails. The corpus cannot see this class of bug — on 2026-08-06 it reported NO
DRIFT on all 84 pistons while the gate caught a crash for any piston opening
with a loop or a switch.

---

## Open — correctness (silent-wrong, highest priority)

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
      `resolve.last_changed_is_exact` (which comparisons are cheap enough to
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

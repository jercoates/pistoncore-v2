# COMPILER_SPEC.md — PistonCore v2 Compiler

**Status:** Draft 1 (skeleton + decisions, 2026-07-13). Sections marked [FILL] are
structure-complete but content-light; each names its source doc so ANY session (or model)
can fill it without re-research. Sections marked DECIDED carry Jeremy's settled call: do not silently drift from them or
"improve" them mid-session — but they are NOT immune to evidence. If implementation,
testing, or research contradicts a DECIDED item, STOP, present the evidence to Jeremy,
and he re-decides. (Precedent: packages-vs-includes was reversed by one research pass.)
Decided ≠ frozen; it means changing it requires Jeremy, not that it can't change.
**Authority:** Subordinate to PISTON_JSON_REFERENCE.md (input format is law) and the
webCoRE sources. Consumes research from: WEBCORE_HA_BEHAVIOR_MAP.md,
HA_YAML_COMPILER_RESEARCH.md, PYSCRIPT_COMPILER_RESEARCH.md, HA_LIMITATIONS.md.
Decisions inherited from COMPILER_DECISIONS_HOLDING.md (§A–§H) and
COMPILER_DECISIONS_DEPLOY.md — restated here; on conflict, this doc wins once accepted.
**Tagging:** VERIFIED (source+date) / ASSUMED / TO VERIFY / DECISION (who, when).

---

## 1. Mission and non-negotiable policy (DECIDED — from holding doc §A)

The compiler turns saved webCoRE piston JSON into things Home Assistant executes natively.
It replicates the **intent** of the piston, not webCoRE's architecture. There is no engine.

- **Read-only compiler.** Never mutates piston JSON, vocab, or translation files. Ever.
- **Errors go to the debug page** (piston + statement `$` id + plain-English reason).
  Never mutation, never partial/placeholder output, never TODO comments in deployed YAML
  (considered and REJECTED — a deployed automation that silently skips an action is worse
  than a visible compile failure).
- **Jinja2 everywhere:** all emission goes through editable template files + JSON maps in
  the customize volume. No hardcoded YAML/Python strings in compiler code. This is the
  breaking-change insurance (Recompile All, §10).
- **One canonical variable-substitution function.** All text interpolation flows through it.
- **YAML-native is the primary target; PyScript is the routed exception** (§5) plus an
  optional user preference ("prefer PyScript for fidelity", settings).

## 2. Input contract [pointer section — content lives elsewhere]

- Format: PISTON_JSON_REFERENCE.md (certified against editor source + live captures).
- Trigger identification: node-level `ct` ("t"/"c") and `s` (subscription) fields when
  present (engine-saved pistons); DERIVED from the comparisons vocab buckets
  (`comparisons.triggers{}` vs `.conditions{}`) when absent (imported/AI-authored pistons).
  Vocab is authority on disagreement. [VERIFIED — capture 2026-07-12 + HE groovy]
- Scope: the 84-piston corpus (`test-pistons/`) defines v1 requirements: statement types
  {if, action, each, while, repeat, do, group}, 22 comparisons, ~70 commands, 12 system
  vars (PISTON_JSON_REFERENCE §8b). Types outside the corpus (for, switch, on, break,
  exit) are spec'd but lower priority; `break` and `on` force PyScript anyway (§5).

## 3. The pipeline

```
piston JSON ──► (1) RESOLVE ──► (2) ROUTE ──► (3) EMIT ──► (4) DEPLOY ──► (5) LIFECYCLE
```

### 3.1 RESOLVE — devices, variables, values
- Device refs in `d` arrays are: hashed id | local device-variable name | `@global` name |
  `$device` (inside `each`). Resolution order: literal hash → piston `v[]` definition →
  globals store → loop binding. [VERIFIED — capture]
- Hash → member entities via the shim's resolution map (DEVICE_PAYLOAD_SPEC §8:
  registry_device_id, members, attr_bindings, cmd_bindings). Rebuildable cache.
- **Per-device multi-mapping (DECISION, Jeremy 2026-07-12):** each member entity is
  matched against the vocab entry's `ha` array by domain/device_class/features; array
  order is the tiebreaker when several match one entity (order is MEANINGFUL — never
  re-sort the arrays).
- **Command fan-out with grouping (DECISION):** one webCoRE command over mixed devices
  emits one HA service call per winning mapping, each carrying the combined entity list
  of the devices that resolved to it.
- **Failure rules (DECIDED — COMPILER_DECISIONS_DEPLOY §2):** unavailable = pass through
  (HA skips offline entities in actions); unresolvable = compile error (a trigger on a
  nonexistent entity_id silently never fires); multi-device statements skip+flag bad
  members; single-device statements with an unresolvable sole device error+pause+flag.
- Globals: read from the globals store (shim-side JSON, `used_by`-tracked); global VALUES
  inline per C-TYPES translation (holding doc) — device globals resolve like device vars;
  scalar globals map to their HA helper entities. [FILL: per-type inlining table — source:
  holding doc C-TYPES]

### 3.2 ROUTE — YAML or PyScript
- `routing_table.json`: a list of webCoRE-JSON signatures that FORCE PyScript; YAML is
  default (DECISION). Seed content: holding doc §E + HA_LIMITATIONS §6, re-keyed to real
  field names: `t:"break"`, `t:"on"`, group `o:"xor"`, `followed_by` chains (`wd`/`wt`),
  switch `ctp` fallthrough, monthly/yearly `every` operands, `cancelTasks` task command,
  `exit` with value, [FILL: complete the re-key — source: §E rows × PISTON_JSON_REFERENCE
  §2.2]. Corpus note: `cancelTasks` and `stays_*`/`was_*` appear in real pistons — routing
  WILL fire in practice.
- `stays_*` / `was_*`: `stays` maps native (`for:` on triggers) in simple positions;
  PyScript `state_hold` / `.old` when composed [FILL: exact boundary — sources: behavior
  map §2, PYSCRIPT research, HA_LIMITATIONS §2].
- User preference "prefer PyScript" flips the default for whole pistons (settings).
- The routing scan runs in the shim's save flow, after reassembly.

### 3.3 EMIT — the two bands
**YAML band (primary):**
- **Classic primitives ONLY — never purpose-specific triggers/conditions (DECISION,
  pending Jeremy's one-word confirm; evidence: purpose-specific YAML keys were renamed
  breaking in 2026.7 itself, while classic primitives carry an explicit stability
  promise).** [VERIFIED — HA_YAML_COMPILER_RESEARCH §0/§3]
- Modern key schema (`triggers:`/`conditions:`/`actions:`, `trigger:` type key) per
  HA_YAML_COMPILER_RESEARCH §1. [FILL: emission baseline block]
- Structure per piston: one automation (+ script when reuse/complexity demands) [FILL:
  the automation/script split rule — source: v1 compiler reference + behavior map §1].
- Trigger extraction: all `ct:"t"` nodes → `triggers:` OR-list; full parent condition
  tree → `conditions:`/`choose:`. [FILL: nested if/ei/e → choose mapping — source:
  behavior map §1, §G sketches (output side only)].
- Comparison table: behavior map §2 is the verbatim mapping (state/numeric_state/template
  per comparison, `for:` for stays). [FILL: import the table; mark the corpus-22 as
  must-pass].
- Hard template rules (DECIDED, v1 postmortem — HA_LIMITATIONS §9): ALWAYS quote state
  values; EVERY wait emits `timeout:` + `continue_on_timeout:`; parallel branches carry
  sequence-level `continue_on_error`.
- `ts`/`fs` condition task lists compile (easy to miss). Statement/piston restrictions
  (`r`) → conditions / `@time_active`-equivalents [FILL].
- Header comment on every file: generated-by, piston id/name, template-set version,
  do-not-edit.
**PyScript band (exception path):**
- File layout: `/config/pyscript/scripts/pistoncore/<slug>_<id>.py` [VERIFIED — PyScript
  autoload rules]. One piston = one file.
- Verbatim semantic mappings: `stays`=`state_hold`, edge `changes to`=`state_hold_false=0`,
  `was`=`.old`, restrictions=`@state_active`/`@time_active`, sun offsets native,
  `task.unique` for TCP, `state.persist` for piston state. [FILL: per-construct snippets —
  source: PYSCRIPT_COMPILER_RESEARCH §2–§8, §G sketches].
- Same template/data discipline as YAML band.

### 3.4 DEPLOY (DECIDED — COMPILER_DECISIONS_DEPLOY §3–§5)
- Labeled includes, NOT packages: `automation pistoncore: !include_dir_merge_list
  pistoncore/automations/` (+ scripts). Packages rejected (UI-duplicate bug, filename
  uniqueness).
- Naming: `<slug>_<shortid>.yaml`; id authoritative, old file removed on rename.
- Reload: `automation.reload` + `script.reload`; TO VERIFY whether first-time file
  additions under include_dir need `reload_all` (dev-HA test).
- First-run wizard owns the configuration.yaml consent edit (backup, show diff, explicit
  yes, refuse-if-nonstandard) + pyscript block + PyScript-optional notice + default mode.

### 3.5 LIFECYCLE (DECIDED — COMPILER_DECISIONS_DEPLOY §1, §8)
- Compile on every successful save. Failed compile leaves the previous artifact RUNNING;
  banner on the stock status page (link → debug page) + front-door flag.
- Piston active/paused mirrors one-way PistonCore → HA (`initial_state`/enable);
  new pistons land paused (webCoRE build-0 behavior) — mirrored, not invented.
- Device-global edits: targeted patch of deployed artifacts via `used_by`, never full
  recompile (holding doc §H); piston JSON untouched (verified — names in JSON).
- Recompile All: settings button + stale-template front-door banner; artifacts record
  template-set version.

## 4. Execution modes
First-run prompt sets the default; settings changes it; webCoRE piston settings honored
per-piston where they express an equivalent. TCP default candidate: `mode: restart`
(ASSUMED — per-statement vs automation-wide caution, addenda item 1; resolve during the
TCP semantics fill). [FILL: tcp/tep/tsp value sets from piston.module.html dialogs →
mode/task.unique mapping table].

## 5. What does not compile
- Omitted-from-db features never reach pistons (reproduce-cleanly test; `ha:"n/a"` markers
  drive Stage-3/getDb filtering).
- Pistons using routed-but-PyScript features when PyScript is absent: compile error with
  the E3 notice ("statement $N requires PyScript") + install link. Never silent.
- Truly unmappable (HA_LIMITATIONS + behavior map §6 after reconciliation): [FILL —
  reconcile behavior map §6 against routing table first; four items it lists as cut are
  actually PyScript-routed].

## 6. Regression & acceptance
- Compile-all-84 (`test-pistons/`) is the regression suite and the progress bar; work
  order: single-feature test pistons → mid-size → the three ~80-node alarm pistons.
- Per-construct golden outputs: [FILL: one expected-YAML/py fixture per §3.3 table row].
- Dev-HA test list (port from research docs): reload-new-file behavior; restart kills
  in-flight waits (PyScript §12); `state_hold_false=0` chatty-sensor; event-entity repeat
  under classic state trigger; presence semantics vs Jeremy's zones (2026.7 changes).

## 7. Open items
1. Jeremy: confirm classic-primitives-only (§3.3) → flip to DECIDED.
2. Behavior-map §6 reconciliation pass (Fable, offered).
3. Five uncaptured statement types → hand-built captures (editor session).
4. Engine-mining leftovers: exact TCP per-statement semantics, `a` async flag, mixed
   trigger evaluation order, `every` scheduling internals, expression evaluator coercion
   (webcore-piston.groovy; needed for §3.3 fills and §4).
5. Port-backs listed in both research docs' §5 (Code errand).
6. Notify band: blocked on C2b translation file + phone on test HA (design exists —
   NOTIFY_ACTION_SPEC + C1/C2/C2b).

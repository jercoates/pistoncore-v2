# SESSION BRIEF — YAML Band Expansion (stop over-routing to PyScript)

One-time session instructions (move to archive/session-briefs/ when executed).
Raised by Jeremy 2026-07-19 ("you might be sending too many automations to
pyscript — but you need to check"). Checked: he was right. Evidence below.

## The finding

Corpus run over Jeremy's real pistons (test-pistons/, 98 pistons):
36 YAML / 42 PyScript. Ranked reasons for PyScript routing showed most are
constructs **HA YAML supports natively** — per HA_YAML_COMPILER_RESEARCH.md §2,
which was written for exactly this and had not been applied.

| Reason (count) | Native YAML answer (HA_YAML_COMPILER_RESEARCH §2) |
|---|---|
| computed notification/speech message (9) | Jinja `value_template`/`message` with `trigger.entity_id`, `trigger.to_state.state`, `trigger.from_state.state` |
| `setVariable` (6) | `variables:` action (script-run scope; scoping rules in docs) |
| top-level bare `action` / no subscriptions (9) | emit a **script** instead of an automation — a script IS "a runnable sequence of actions"; also gives executePiston its native target |
| `switch` statement | `choose:` (first match wins; fall-through still PyScript) |
| `while` / `repeat` / `each` | `repeat:` with `while:` / `until:` / `count:` / `for_each:` (+ `repeat.index`) |
| `exit` | `stop:` action |
| `executePiston` | `action: script.X` (waits) or `script.turn_on` (no wait); args via `data:` |
| `cancelTasks` | already fixed this session: no-op under `mode: restart` |
| condition operator `or` | already fixed this session: `condition: or` group |

## Scope of the work

1. **Jinja expression emitter** — a second backend for the existing expression
   AST (shim/compiler/expression.py already parses + has a Python emitter;
   add an emit-to-Jinja path). Needed for computed messages, templated
   values, and `value_template` conditions. The AST, precedence and function
   semantics are already built and tested — this is a new output format, not
   new parsing. Functions with no Jinja equivalent are the honest boundary:
   route those pistons to PyScript as now.
2. **Script emission target** — new band template (script.yaml.j2) + deploy
   support (a `pistoncore/scripts/` include, same include mechanism as
   automations; config_yaml.py already knows how to add include lines).
   Execute-only pistons and executePiston targets both need it.
3. **Statement coverage in emit_yaml**: `variables:`, `choose:`, `repeat:`
   (all four forms), `stop:`.
4. Re-run the corpus; expect the split to invert (most pistons YAML).

## Rules

- Classic primitives ONLY — HA_YAML_COMPILER_RESEARCH §0/§3 DECISION: do NOT
  emit purpose-specific triggers/conditions (their keys renamed in 2026.7
  with "old keys no longer work"; classic carries an explicit stability
  promise). This is load-bearing, not a preference.
- Every emitted line stays in the band templates (no YAML strings in Python).
- Fixture + regression tests must stay green (test_compile_fixtures.py).
- Measure before/after with the real-piston corpus, not the community one.

## Also worth porting while in here (from the same doc, §2/§4)

- `to: null` for true any-change triggers (ignores attribute churn).
- `not_to:` / `not_from:` for changes-away-from (cleaner than the current
  from: form; cannot be combined with to:/from:).
- `not_from: ["unknown","unavailable"]` to suppress restart churn on
  any-change triggers.
- `above:`/`below:` accept an ENTITY ID — device-to-device numeric comparison,
  which currently has no compilation path at all.
- `attribute:` on state/numeric_state for attribute operands.
- §4: 2026.7 changed presence semantics (zone person-counts, device_tracker
  zone-state, person coordinates) — review presence compilation and port the
  findings into HA_LIMITATIONS.md.
- `for:` timers reset on HA restart / automation reload — a real fidelity
  caveat vs webCoRE; belongs in the help text for stays/remains pistons.

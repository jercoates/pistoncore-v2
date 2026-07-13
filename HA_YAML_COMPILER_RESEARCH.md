# PistonCore — HA YAML Compiler Research (codegen layer, native target)

**Status:** Research holding doc — companion to PYSCRIPT_COMPILER_RESEARCH.md; feeds the v2
compiler spec's YAML codegen sections.
**Version:** 1.0 (July 2026 — researched against HA 2026.7 release notes and current
home-assistant.io documentation, all read 2026-07-13)
**Position in authority chain:** research input, NOT authority. Routing lives in
COMPILER_DECISIONS_HOLDING.md §E; HA runtime limits live in HA_LIMITATIONS.md. This doc
covers: **what the emitted YAML looks like, verified against current syntax, and the
purpose-specific triggers decision.**

**Tagging convention (per standing rule — every claim carries a verified-by source):**
- **[Verified — rel 2026.7]** = HA 2026.7 release notes blog post (July 1, 2026), read 2026-07-13.
- **[Verified — docs <path>]** = current page at home-assistant.io/<path>, read 2026-07-13.
- **[Assumed — <why>]** = needs verification before the compiler spec relies on it.
- **[Decision]** = PistonCore choice, not an HA fact.

---

## 0. The headline findings (read this first)

1. **Purpose-specific triggers and conditions are now the HA default — but the compiler
   should NOT emit them. [Decision, rationale in Section 3.]** They graduated from Labs to
   default in 2026.7 [Verified — rel 2026.7], they have first-class YAML forms
   [Verified — rel 2026.7, "we put real effort into making the new building blocks read
   well in YAML too"], and yet **their YAML keys were renamed in this very release with
   "the old keys no longer work"** [Verified — rel 2026.7, backward-incompatible changes:
   `battery.low` → `battery.became_low`, `vacuum.docked` → `vacuum.returned_to_dock`, and
   8 more trigger + 2 condition renames]. A compiler cannot build on keys that break
   between monthly releases. Classic primitives, by contrast, carry an explicit stability
   promise: "Existing automations keep working. Generic triggers, conditions, templates,
   and YAML all keep working" [Verified — rel 2026.7].

2. **Classic primitives are the verbatim match to the piston JSON model anyway** —
   webCoRE conditions are entity + comparison + value, which is exactly the shape of
   `state` / `numeric_state` triggers and conditions. Purpose-specific blocks are
   organized by domain intent and area/floor/label targets [Verified — rel 2026.7], which
   conflicts with the locked rule that entity_id from the picker is the only HA-native
   value in piston JSON. Section 2 is the verbatim mapping table.

3. **2026.7 changed presence semantics** — zone person-counts, device_tracker zone-state
   resolution, and person coordinates all changed [Verified — rel 2026.7, backward-
   incompatible changes]. Presence-based pistons are affected; details and port-backs in
   Section 4.

---

## 1. Emission baseline — the modern key schema

The compiler emits ONLY the modern key schema (current since HA 2024.10, used throughout
all current docs):

- `triggers:` list, each item `- trigger: <type>` [Verified — docs /docs/automation/trigger/]
- `conditions:` list, each item `- condition: <type>` (or shorthand forms, below)
  [Verified — docs /docs/automation/condition/]
- `actions:` list, each item `- action: <domain.service>` (never `service:`)
  [Verified — docs /docs/automation/trigger/ examples + rel 2026.7 which cites the
  `service` → `action` rename as precedent]

Never emit the legacy `platform:` / `service:` / singular `trigger:` block forms — those
appear only in stale third-party tutorials now. (This restates and sources the existing
HA_LIMITATIONS finding about `wait_for_trigger` inner syntax: inner triggers use
`trigger:` type keys, same as top-level.)

**Documentation restructure worth knowing [Verified — rel 2026.7]:** every trigger,
condition, and action now has its own page at home-assistant.io/triggers/,
/conditions/, and /actions/. Future verification sessions should cite the per-block page
(e.g. docs /triggers/numeric_state/) — they're more precise than the old combined pages
and are the pages HA now maintains as canonical.

---

## 2. Verbatim mappings — webCoRE semantic → classic YAML primitive

Same tier structure as the PyScript doc. Every row Verified against the docs page named.

| webCoRE semantic | YAML primitive | Source |
|---|---|---|
| trigger: `changes to X` | `trigger: state` + `to: "X"` (edge — fires on transition) | docs /docs/automation/trigger/ |
| trigger: `changes from A to B` | `from: "A"` + `to: "B"`; both accept lists (OR) | docs /docs/automation/trigger/ (vacuum example: `from: [cleaning, returning] to: error`) |
| trigger: `changes` (any state change, ignore attribute churn) | `to: null` ("trigger on all state changes, but not on attribute changes") | docs /docs/automation/trigger/ |
| trigger: `changes away from X` / negated operands | `not_from:` / `not_to:` (cannot combine with `from`/`to` respectively) | docs /docs/automation/trigger/ |
| exclude unknown/unavailable churn on any-change triggers | `not_from: ["unknown", "unavailable"]` | docs /docs/automation/trigger/ (exact example shown) |
| trigger: `stays X for N` | `for:` on state trigger (HH:MM:SS, mapping, or template) — timer resets if the state leaves; ALSO resets on HA restart / automation reload | docs /docs/automation/trigger/, /triggers/numeric_state/ ("If you use for, the timer resets if Home Assistant restarts or automations reload") — restart-reset is a fidelity caveat webCoRE's Hubitat scheduler shares only partially; note in help text |
| attribute operand | `attribute:` on state/numeric_state trigger and condition | docs /docs/automation/trigger/ |
| numeric `rises above` / `drops below` | `trigger: numeric_state` + `above:` / `below:` — crossing semantics: "fires when a value crosses a threshold. It does not keep firing while the value stays on the same side" — this IS webCoRE's rises/drops edge semantics, verbatim | docs /triggers/numeric_state/ |
| `is inside range` trigger | `above:` + `below:` together = fires on entering the range | docs /triggers/numeric_state/ |
| compare against another device's value (webCoRE device-to-device comparison) | `above:`/`below:` accept an **entity ID** as the threshold; comparison re-evaluated only when the watched entity updates | docs /triggers/numeric_state/ |
| computed operand (expression on the value) | `value_template:` on numeric_state | docs /docs/automation/trigger/ |
| restrictions / conditions: and/or/not groups | `condition: and|or|not` with nested `conditions:`, plus shorthand `- or:` list form; bare sequential list = AND | docs /docs/scripts/conditions/, /docs/automation/condition/ |
| expression conditions | template condition, incl. shorthand: a bare `"{{ ... }}"` string is a valid condition anywhere conditions are accepted | docs /docs/scripts/conditions/ |
| `$currentEventDevice` / `$currentEventValue` / `$previousEventValue` | `trigger.entity_id`, `trigger.to_state.state`, `trigger.from_state.state` in action templates | docs /docs/automation/templating/ |
| which trigger fired (multi-trigger pistons) | `id:` on each trigger + `trigger.id` variable + `condition: trigger` — auto-assigned index ids exist for triggers without explicit `id` | docs /docs/automation/trigger/, /docs/scripts/conditions/ |
| if/then/else | `if:`/`then:`/`else:` action; `choose:` for if/elif/.../else chains with `default:` | docs /docs/scripts/ |
| switch statement | `choose:` (first matching conditions/sequence pair wins) — fall-through still impossible, PyScript routing unchanged | docs /docs/scripts/ |
| for-count / foreach / while / repeat-until loops | `repeat:` with `count:` / `for_each:` / `while:` / `until:` (until runs at least once); `repeat.index/first/last` loop variables | docs /docs/scripts/ (per its own section index) |
| wait N | `delay:` (seconds, HH:MM:SS, mapping, all templatable) | docs /docs/scripts/, /integrations/script/ example |
| wait for condition (with timeout) | `wait_template:` / `wait_for_trigger:` + `timeout:` + `continue_on_timeout:`; `wait.trigger`/`wait.completed` variables. Caveat: wait_template only re-evaluates on referenced-entity state changes — `now()` in a wait template does NOT re-evaluate continuously (webCoRE time-comparison waits must compile to a time trigger inside wait_for_trigger instead, or reference a Time & Date sensor) | docs /docs/scripts/ |
| condition-in-sequence (webCoRE mid-piston condition halting execution) | `condition:` as an action stops the current sequence block only — inside `repeat` it stops the iteration, inside `choose` it stops that branch. NOT a global exit | docs /docs/scripts/ |
| exit piston | `stop:` action (with optional `response_variable`); still not a loop `break` — existing HA_LIMITATIONS finding unchanged | docs /docs/scripts/ (Stopping a script sequence section exists; break behavior per prior verified finding) |
| set variable | `variables:` action — top-level (script-run) scope if not previously defined; scoping rules documented | docs /docs/scripts/ (Variables / Scope of variables sections) |
| execute piston with args, wait/nowait | direct `action: script.X` (calling script WAITS for completion) vs `script.turn_on` (fire-and-forget); variables passed via `data:` (direct) or `data: variables:` (turn_on) — this is webCoRE's "execute piston and wait / don't wait" toggle, verbatim | docs /integrations/script/ |
| piston execution mode | `mode: single|restart|queued|parallel` on script/automation — pairs with the PyScript doc's Section 6 table; the §D default decision applies to both targets identically | docs /integrations/script/ |
| localized event on piston start | `event:` action fires custom events (raise); `trigger: event` consumes | docs /docs/scripts/, /docs/automation/trigger/ |
| grouped/parallel action blocks | `sequence:` grouping and `parallel:` actions | docs /docs/scripts/ (section index) |
| per-action error tolerance | `continue_on_error:` per action; `enabled: false` to disable an action | docs /docs/scripts/ (section index) |

Additional plumbing facts:
- **Blueprint nested-trigger flattening** exists (`triggers:` key inside a trigger list
  item flattens) [Verified — docs /docs/automation/trigger/] — not needed for v1, but it's
  the mechanism if piston templates ever compose trigger fragments.
- **`trigger_variables`** (automation-level, limited templates, evaluated at attach time)
  [Verified — docs /docs/automation/trigger/] — candidate mechanism for injecting
  PistonCore constants (piston id, statement ids) into trigger definitions without string
  interpolation in the Jinja2 templates themselves. [Decision — pick one mechanism and use
  it everywhere; do not mix.]
- **Zone conditions:** multi-entity = ALL must be in zone; `state:` list form = entity in
  ANY listed zone [Verified — docs /docs/scripts/conditions/]. Maps to webCoRE's
  all-of/any-of presence conditions — but see Section 4 before locking presence compilation.

---

## 3. Purpose-specific triggers and conditions — the decision

**What they are [Verified — rel 2026.7]:** domain-intent building blocks ("Temperature
crossed threshold", "Battery low") that graduated from Labs (introduced 2025.12) to the
default editor experience in 2026.7. They support area/floor/label/device **targets**, not
just entities; integrations (including custom/HACS ones) can register their own triggers
and conditions; the blocks internally handle `unknown`/`unavailable` "in the way that makes
sense for their purpose"; and each has a dedicated docs page. Existing generic triggers,
conditions, templates, and YAML are explicitly unaffected.

**[Decision — recommended lock] The compiler emits classic primitives only, for now:**

1. **Key instability.** 2026.7 itself renamed 8 trigger keys and 2 condition keys with
   "the old keys no longer work" [Verified — rel 2026.7]. Emitted pistons must survive HA
   upgrades unattended; classic primitives have years of stability plus an explicit
   keep-working commitment in the same release notes.
2. **Model mismatch.** Purpose-specific blocks are domain-semantic and target-oriented
   (area/floor/label). Piston JSON is webCoRE-shaped: entity + comparison + value, with
   entity_id as the only HA-native field (locked rule). Translating comparison-shaped
   piston JSON into intent-shaped blocks adds a lossy mapping layer for zero fidelity gain.
3. **The versioned template system is the adoption path.** If a purpose-specific block ever
   solves a real routed problem, it's a template-band change, not an architecture change.

**Watch items — where purpose-specific blocks WOULD genuinely help (revisit later):**
- **Event entities.** "Automate around one with a plain state trigger and you may discover
  it doesn't fire the second time the same event happens... A purpose-specific trigger
  expresses the event directly" [Verified — rel 2026.7]. This is a real edge for
  button/scene-controller devices — a webCoRE user's "button pushed" piston compiled to a
  plain state trigger can miss repeat presses. **Port to HA_LIMITATIONS as a flagged
  limitation of the classic path**; interim mitigation is triggering on the event entity's
  state change including same-state timestamps via `to: null`-style forms —
  [Assumed — needs test on dev HA with a real button event entity] whether that fires
  reliably on repeated identical events.
- **Built-in unknown/unavailable handling** [Verified — rel 2026.7] — the classic path
  handles this with explicit `not_from: [unknown, unavailable]` guards (Section 2), which
  is fine but per-trigger boilerplate the templates must carry.
- **first/each/all multi-device matching behaviors** on purpose-specific triggers
  [Assumed — reported in secondary release coverage (maison-et-domotique.com 2026.7
  article); not confirmed in the official release notes text I read — verify on the
  /triggers/ docs pages before citing anywhere]. If real, `all` mode overlaps webCoRE's
  "all of these devices" trigger aggregation, which currently needs template conditions.

**Re-check cadence:** revisit this decision when (a) a full HA release cycle passes with
zero purpose-specific key renames, or (b) a routed piston feature would be materially
simpler on a purpose-specific block. Same monthly-release review cadence as
HA_LIMITATIONS.md.

---

## 4. 2026.7 changes that affect compiled pistons (port to HA_LIMITATIONS)

All [Verified — rel 2026.7, backward-incompatible changes + noteworthy changes]:

1. **Zone person-counts:** zone entity state and `persons` attribute are now calculated
   from person entities' new `in_zones` attribute — **a person can now count in multiple
   zones simultaneously** (e.g. `home` AND `near_home`). Pistons comparing zone occupancy
   counts can see different numbers than pre-2026.7.
2. **Device tracker zone resolution:** position-aware device trackers now report the
   **smallest** zone they're in, not the zone whose center is closest. Presence pistons
   keyed on zone-name states can flip behavior where zones overlap.
3. **Person coordinates:** person entities no longer report home-zone lat/long when their
   location comes from a presence scanner associated with home. Any piston reading person
   coordinates must use `in_zones` instead.
4. **Traces now always include template errors** — direct win for PistonCore's debug story
   on the YAML target; a compile-produced template error is now visible in the trace
   instead of vanishing.
5. **Template engine up to 40% faster** — no correctness impact; noted only so nobody
   "optimizes" templates for a performance problem that shrank.

Items 1–3 belong in HA_LIMITATIONS as a **⚠ presence-semantics change flag** on whatever
section covers presence/zone compilation, with a re-test on the dev HA before presence
pistons are declared fidelity-clean.

---

## 5. Items to port to other docs

1. **HA_LIMITATIONS.md:** the Section 4 presence flags above; the event-entity repeat-fire
   limitation of classic state triggers (Section 3 watch item); the `for:` timer
   restart/reload reset caveat (Section 2 table).
2. **COMPILER_DECISIONS_HOLDING.md §E:** the classic-primitives-only decision (Section 3)
   as a locked entry once Jeremy confirms; the trigger_variables-vs-interpolation
   mechanism choice (Section 2).
3. **Template inventory:** the YAML template band gains the same snippet-per-construct
   layout as pyscript/2.x — Section 2's table is the snippet list; §G statement sketches
   point at template files on graduation, mirroring the PyScript doc.

## 6. Open items / next research

- Verify first/each/all matching behaviors against official /triggers/ docs pages.
- Dev-HA test: event entity repeat-press behavior under a classic state trigger.
- Dev-HA test: presence semantics (items 4.1–4.3) against Jeremy's actual zones.
- When the purpose-specific decision is revisited, pull the per-block docs pages at
  /triggers/, /conditions/, /actions/ — they are now the canonical per-primitive reference
  [Verified — rel 2026.7] and should replace the combined pages as citation targets.

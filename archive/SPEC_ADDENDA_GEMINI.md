# SPEC ADDENDA — items from Gemini review chat (2026-07-12)

Merge each into the named doc's CURRENT copy (do not overwrite newer content). Tag as
shown. Source: Jeremy's Gemini conversation; ideas restated and dispositioned here.

## 1. TCP default → HA `mode: restart` (ASSUMED — promising, needs verification)
→ COMPILER_DECISIONS_HOLDING.md, new §E note or its own item.
WebCoRE's default task-cancellation policy (cancel delayed tasks when the triggering
condition changes — the classic "motion off → wait 5 min → light off, motion on again →
timer resets") may map to HA automation `mode: restart` for free: every new trigger kills
the in-flight run, clearing pending delays, which reproduces default-TCP *intent* with
zero custom scheduling.
CAUTIONS to verify before relying on it: (a) `mode: restart` is automation-wide, while
webCoRE TCP is per-statement — a piston with several independent timed branches under one
automation would have them cancel each other; may force one-automation-per-trigger-branch
splitting or PyScript for mixed-TCP pistons. (b) `tcp` values other than default ("c")
need their own story (`mode: single`/`queued`/`parallel` map to some; enumerate against
the tcp value set, open item PISTON_JSON_REFERENCE §10.3). (c) Cross-check
HA_LIMITATIONS.md §7 "Automation Mode Behavior Differs From Hubitat" — same territory.
File as the leading candidate mechanism for TCP, not a decision.

## 2. Unmapped-feature TODO comments in output YAML — REJECTED (record it)
→ COMPILER_DECISIONS_HOLDING.md §A, one line.
Gemini suggested: on unmapped commands, keep compiling and emit
`# PISTONCORE_TODO: not mapped` comments in the deployed YAML. This CONFLICTS with locked
policy A6 (no silent drop, no placeholder, no partial output — unresolvable = a surfaced
error naming the piston/statement, shown on the front-door indicator + that piston's own
status-screen banner — no separate debug page, Jeremy 2026-07-12). A deployed automation
that silently skips one action is worse than one that visibly failed to compile. Record as
considered-and-rejected so it doesn't get re-proposed; those two surfaces ARE the TODO list.

## 3. "Recompile All" as breaking-change insurance (DECISION-adjacent, cheap, real)
→ COMPILER_DECISIONS_HOLDING.md new item + one line in README's compiler section later.
Because compiler output is driven by editable Jinja2 templates + JSON maps (not hardcoded
Python), an HA breaking change (service/schema rename) is absorbed by updating the
template/map and RECOMPILING ALL pistons — zero manual automation edits, for every user.
Consequences to spec: (a) a "Recompile all" action must exist (front door or settings);
(b) compiled artifacts should record the template-set version they were built with, so
"built with outdated templates" is detectable and the front-door indicator / piston
status-screen banner can suggest recompiling;
(c) this is a headline README selling point once the compiler exists.

## 4. Shipped piston library (DECISION, Jeremy): curated pistons via IMPORT, never auto-fill
→ IMPORT_EXPORT_SPEC.md when written; note in COMPILER_DECISIONS_HOLDING or README roadmap.
PistonCore ships a curated library of Jeremy's genuinely-useful, scrubbed pistons as an
instantly-usable automation starter set. Mechanism is the stock webCoRE IMPORT flow: user
imports a library piston → editor prompts to map its device variables to their real
devices → user explicitly binds → save. NEVER auto-scan/auto-bind devices ("magically
scan and fill would not end well"). Library pistons must therefore reference devices ONLY
through device-type variables/globals (the §9 AI-authoring portability rule — hashes stay
inside variable definitions, rebindable on import). Also planned: a help doc listing
what differs from traditional webCoRE / what won't carry over (seed it from
HA_LIMITATIONS §10 and the neutralized-features list rather than writing from scratch).

## Already covered elsewhere (no action)
- Harvest-all-attributes-from-the-84 script → done; results are PISTON_JSON_REFERENCE §8b.
- Trigger extraction into HA trigger block → resolved via `ct`/`s` fields (§3).
- "Never refactor working code / sealed files" → CLAUDE.md.
- Templates/maps as community-editable data → existing house style, already specced.

# SESSION BRIEF — Deprecation Scanner (cheap first deploy gate)

One-time session instructions (move to archive/session-briefs/ when executed).
Source: Jeremy brought back `OPENCODE_DEPRECATION_SCANNER_REFERENCE.md`
(2026-07-20) — a public-domain pattern-catalog design from
`magnusoverli/opencode`. This brief turns its adoption proposals into a
buildable task. Read that reference doc first; it is the authority for the
schema and the three-roles rationale.

## Goal

A regex text-match gate that blocks a deploy when DEPRECATED Home Assistant
YAML syntax appears in a compiled file — run BEFORE the existing
`check_config` gate (it needs no running HA, so it's the cheapest first
check). It guards two boundaries:
- **our emitter** — regression guard: a template that drifts into
  deprecated/non-primitive syntax gets caught before it ships.
- **user input** — contamination guard: imported real pistons (community
  codes, hand edits, old fixtures) can carry deprecated syntax from the user
  side, not just ours.

## Hard rules (from the reference doc — do NOT violate)

- **FLAG, NEVER REWRITE.** The scanner reports the offending line and blocks;
  it never auto-corrects. Auto-rewriting compiler output would make the
  compiler no longer the source of truth for what deploys and would
  eventually mangle a valid edge case silently. The catalog's `suggestion`
  fields are human hints, not mechanical transforms.
- **If the scanner ever fires on OUR OWN output, that is a COMPILER BUG** —
  fix the template, not the output.
- **Three roles stay separate** (compiler = prevention/authority; scanner =
  reactive gate; HA alerts feed = pre-emptive watch). The scanner is
  reactive-only and CANNOT replace the alerts-feed watch — by the time it
  could match a retired primitive we'd already have shipped it. Do not merge.

## Build

1. **Pattern file — EDITABLE DATA (COMPILER_SPEC §1a).** Create
   `pistoncore_deprecation_patterns.json` using the reference doc's exact
   field schema (§"Pattern schema"). It MUST be added to
   `shim/customize.CUSTOMIZABLE` and loaded through `customize.path` so users
   can add patterns without a rebuild — same rule as every other compiler
   data file. Do NOT open it via `Path(__file__)`/`_REPO_ROOT`.
2. **Seed the 2026.7 renames.** The upstream catalog does NOT cover HA's
   2026.7 trigger/condition renames (8 trigger keys + 2 condition keys) —
   author those as the first PistonCore-specific entries, from
   HA_YAML_COMPILER_RESEARCH.md §0/§3 (which already lists them, e.g.
   `battery.low` → `battery.became_low`, `vacuum.docked` →
   `vacuum.returned_to_dock`). Since the compiler emits CLASSIC primitives it
   should never PRODUCE these — so a match on our output is a bug (see rules).
3. **Wire as the first deploy gate** in `shim/compiler/deploy.py`, ahead of
   the `check_config` gate (~deploy.py:338). A hit -> status "error" naming
   the deprecated pattern + line, no reload, previous artifact untouched
   (same shape as the check_config rejection path).
4. **A hit on an IMPORTED piston** surfaces on the two announcement surfaces
   like any compile error, with a message the user can act on (their piston
   carries deprecated syntax; here's the line). The Diagnostics "Copy AI
   repair prompt" should include the pattern's `suggestion` hint.
5. **Self-hosted only.** Reuse the reference's load/fetch/cache SHAPE but
   point it at PistonCore's own file. NEVER fetch magnusoverli/opencode at
   runtime.
6. **Tests:** a fixture piston containing a deprecated key must be blocked
   with the right message; a clean piston passes; our own corpus output must
   produce ZERO scanner hits (proves the compiler emits no deprecated syntax).

## Also flagged for a live-HA session (from COMPILER_SOURCE_MINING.md)

- **ASSUMED, needs test:** webCoRE "Toggle"/generic on-off across a MIXED
  device list could compile to `homeassistant.turn_on/turn_off/toggle`
  (a legitimate cross-domain service) instead of resolving each entity's own
  domain. Verify against DEVICE_PAYLOAD_SPEC grouping on a real HA before
  adopting. (Everything else in SOURCE_MINING — plural keys, entity_id in
  `target:` not `data:`, unified `action: domain.service` — CONFIRMS what the
  compiler already emits; no action needed.)
- **The HA first-party alerts feed** (reference doc §"Bonus source") is the
  third role — a periodic watch for retirement of the classic primitives our
  whole strategy assumes are stable. Separate future work from the scanner;
  noted here so it isn't forgotten.

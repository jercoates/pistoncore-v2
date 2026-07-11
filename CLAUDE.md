# CLAUDE.md — PistonCore v2

Read this before doing anything. It governs how Claude works in this repo.

## What this project is

PistonCore v2 gives Home Assistant users the real webCoRE editor. The stock webCoRE
dashboard (vendored, GPL-3.0) is served by a FastAPI shim that impersonates the webCoRE
SmartApp API, fabricating webCoRE-shaped data from HA. Saved pistons are stock webCoRE
JSON; PistonCore compiles them to native HA YAML (simple) or PyScript (complex). There is
no webCoRE engine — the compiler replaces it.

Jeremy is the sole director. He has no programming background: he directs, Claude
implements, and he verifies **behaviorally** by clicking through the dev instance — not by
reading code or diffs. Explain in behavior terms, not code terms.

## Authority chain (highest wins)

1. **The webCoRE sources.** `vendor/webcore-dashboard/` (especially js/app.js and
   js/modules/piston.module.js) and `reference/webcore_source_reference.groovy` are ground
   truth for the API contract and the piston JSON format.
2. **The spec docs:** SHIM_API_SPEC.md, DEVICE_PAYLOAD_SPEC.md, PISTON_JSON_REFERENCE.md,
   COMPILER_DECISIONS_HOLDING.md. They describe #1 plus PistonCore decisions. If a spec
   disagrees with the sources, the spec is wrong — fix the spec, tell Jeremy.
3. **Code.** Code is presumed wrong and being caught up to the specs, never the reverse.

COMPILER_DECISIONS_HOLDING.md is a **holding doc, not a spec** — it drifts and adapts as
problems and solutions are found. Update it freely (with Jeremy's sign-off on decisions);
never treat it as gospel.

## Standing design rules — do not re-ask

- **The piston JSON as webCoRE emits it is LAW.** PistonCore adapts to it, never the
  reverse. No custom fields, no reshaping, no "improvements."
- For any design question, the answer is **what webCoRE does**, unless clearly inapplicable
  to HA. Deliberate deviations are enumerated in the specs (copy/paste share instead of
  cloud bins; all devices exposed by default; degraded v1 status page).
- Devices are GROUPED: one picker device per HA device-registry device (Hubitat feel),
  entities unioned per DEVICE_PAYLOAD_SPEC.md. Identity everywhere = hashed IDs
  (`:` + md5("core." + registry_device_id) + `:`; entity_id for singletons), resolved via
  the shim's resolution map. Users see ONLY friendly names — no IDs in any UI. entity_ids
  never appear in piston JSON. (The v1 friendly-names-in-JSON rule is retired.)
- **The vendored dashboard is SEALED.** Never modify anything under
  `vendor/webcore-dashboard/` except the enumerated neutralizations in SHIM_API_SPEC.md §9
  (analytics removal, FontAwesome localization, maps stub, backup-bin UI, optional
  back-link). Any other proposed edit there requires Jeremy's explicit approval first.
- **UI split (Jeremy, 2026-07-10 — supersedes earlier one-liner):**
  - **webCoRE dashboard owns:** the piston editor, the piston view (status/trace screen),
    the global-variables editor, and the dashboard's own settings dialog. Everything
    piston-shaped that already works.
  - **PistonCore pages own:** the FRONT DOOR (landing page: piston tiles with compile
    status + deploy status + HA health — the questions webCoRE structurally can't answer,
    since a saved-but-failed-compile piston looks healthy on webCoRE's list), the
    compile/debug output page (A2 compiler errors, PyScript-routing notices), ALL
    import/export (paste-JSON in, pretty-print + copy out — this page is also the
    AI-authoring door), and PistonCore settings.
  - **webCoRE's own main/list page and its share features (cloud bins, backup/restore
    UI) are INCOMPATIBLE with PistonCore and are neutralized, not used** — the list page
    is a pass-through on the way to the editor, never the primary surface; bin/backup UI
    is hidden per the SHIM_API_SPEC.md §9 table. Users live in PistonCore pages and visit
    the dashboard to author and inspect pistons.
- PistonCore pages: vanilla JS/HTML/CSS + Jinja2. No frontend framework, no build step,
  ever. Backend: Python/FastAPI, JSON file storage, Docker.
- Compiler policy lives in COMPILER_DECISIONS_HOLDING.md §A and is non-negotiable:
  read-only compiler, errors to the debug page (never mutation), Jinja2 everywhere, one
  canonical variable-substitution function.
- Claims in specs carry tags: VERIFIED (with source/line), ASSUMED, TO VERIFY, DECISION
  (with who/when). Keep tagging new claims the same way.

## Session discipline (carried from v1 — unchanged)

- **Plan first, hard stop.** Present the plan and wait for Jeremy's go before writing any
  code or files.
- **No new files without approval.** Name the file and why; wait for a yes.
- **No PowerShell.** Ever.
- **Two-search-then-stop.** If two searches don't find it, stop and ask instead of
  spelunking.
- **Behavioral verification.** Every change ends with "here is what to click and what you
  should see" for the dev instance.
- **Deploy block.** Claude never deploys. Jeremy pulls and rebuilds on Unraid himself.
- **Commits:** Jeremy pushes via GitHub Desktop, single combined commit per session.
- License: this repo is GPL-3.0 (required by the vendored dashboard). Keep upstream
  copyright headers intact.

## Repo map

- `vendor/webcore-dashboard/` — sealed upstream dashboard (see rules above)
- `reference/` — webcore_source_reference.groovy and other read-only upstream references
- `frontend/` translation files: webcore_vocab.json, picker_capability_map.json,
  pistoncore_attribute_translation.json (seed data for the db and device payloads)
- Spec docs at repo root
- `archive/session-briefs/` — one-time SESSION_BRIEF_*.md files, moved here once executed
  (living specs stay at repo root; briefs are session instructions, not specs)
- Shim/backend code: (structure decided at first coding session — plan first)

## Retired v1 concepts — do not resurrect

The v1 nested-tree piston JSON, the custom wizard (wizard-*.js), EDITOR_WIZARD_SPEC /
FRONTEND_SPEC / PISTON_JSON_STRUCTURE_MAP as live specs, the friendly-name device rule,
and the frontend-maintained `used_by` tracking. If old-session context or memory suggests
any of these, it predates the v2 pivot — this file wins.

## Milestone ladder (edit as reality intrudes)

1. **Spike:** shim serves dashboard statics + `/connect` + hardcoded `load`/`devices`/
   `getDb` (3 fake devices) → dashboard renders piston list and device picker.
2. Real device payload from HA (DEVICE_PAYLOAD_SPEC pipeline).
3. Save flow: chunk reassembly → stored piston JSON; validate PISTON_JSON_REFERENCE.md
   against real captures (its §10.6 acceptance test).
4. PistonCore pages: list, status (live HA data), import/export.
5. Compiler (fold holding doc into a real compiler spec first).
6. Trace/console instrumentation (v2 of the status page; PyScript path first).

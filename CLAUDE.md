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

1. **The webCoRE sources.** `dashboard/` (especially js/app.js and
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
  `dashboard/` except the enumerated neutralizations in SHIM_API_SPEC.md §9
  (analytics removal, FontAwesome localization, maps stub, backup-bin UI, optional
  back-link). Any other proposed edit there requires Jeremy's explicit approval first.
- **UI split (Jeremy, 2026-07-10 — supersedes earlier one-liner):**
  - **webCoRE dashboard owns:** the piston editor, the piston view (status/trace screen),
    the global-variables editor, and the dashboard's own settings dialog. Everything
    piston-shaped that already works.
  - **Compile/debug errors are ANNOUNCED on exactly TWO surfaces, never a third (Jeremy,
    2026-07-12 — firm: "adding another level would irritate the hell out of me and any
    future user"):** (1) a status indicator on the front door's piston list (compile/
    deploy/HA-health flag per row), and (2) a banner injected onto the piston's own
    status/view screen (the SAME screen already showing Status/Quick Facts/Automatic
    Backup). That screen already natively shows its own banners this way (VERIFIED —
    piston.module.html:129-133, e.g. the "does not subscribe to any events" alert, each
    one a hardcoded `<div warning ng-if="...">` in the sealed template, no generic slot to
    feed data into) — a PistonCore banner gets added via unsealed JS (same non-invasive
    approach as the Backup-button redirect), styled to match the existing
    `.alert.alert-warning`/`.alert.alert-info` pattern already on that page, never a
    sealed-file edit. A saved-but-failed-compile piston is just another fact about that
    piston, shown where its other facts already live.
  - **A compiler help/debug screen MAY exist, reached only by drilling in — never a place
    errors surface on their own (Jeremy, 2026-07-12).** Same pattern as the existing
    PyScript-notice `[Learn more →]` link (§H below): clicking either of the two
    announcement surfaces above can open it for detailed help fixing that specific issue,
    and it's also reachable directly from PistonCore settings for a general compiler-health
    check. It is NOT a third place an error first appears, and nothing routes you there
    automatically.
  - **PistonCore pages own:** the FRONT DOOR (landing page: a piston list — grouped rows,
    never tiles/cards, Jeremy 2026-07-12 — with compile status + deploy status + HA health —
    the questions webCoRE structurally can't answer,
    since a saved-but-failed-compile piston looks healthy on webCoRE's list), the compiler
    help/debug screen described above, ALL import/export (paste-JSON in, pretty-print +
    copy out — this page is also the AI-authoring door), and PistonCore settings.
  - **webCoRE's own main/list page and its share features (cloud bins, backup/restore
    UI) are INCOMPATIBLE with PistonCore and are neutralized, not used** — the list page
    is a pass-through on the way to the editor, never the primary surface; bin/backup UI
    is hidden per the SHIM_API_SPEC.md §9 table. Users live in PistonCore pages and visit
    the dashboard to author and inspect pistons.
- PistonCore pages: vanilla JS/HTML/CSS + Jinja2. No frontend framework, no build step,
  ever. Backend: Python/FastAPI, JSON file storage, Docker.
- Compiler policy lives in COMPILER_DECISIONS_HOLDING.md §A and is non-negotiable:
  read-only compiler, errors announced on the front-door indicator + piston status-screen
  banner (never mutation, never a third announcement surface — see UI split above; a
  drill-in compiler help/debug screen is fine, reached only from those two or Settings),
  Jinja2 everywhere, one canonical variable-substitution function.
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
- **Deploy block.** Claude never deploys. Jeremy pulls and rebuilds on Unraid himself,
  using the exact command below — the data path is the one real fact worth memorizing
  here, since a wrong/placeholder path silently mounts an empty folder instead of the
  real one (happened once, 2026-07-12 — looked like "deleted everything," wasn't, just
  mounted wrong). Recreate the container, never `docker restart` — a rebuilt image has no
  effect on an already-running container until it's recreated.
  ```bash
  cd /mnt/user/appdata/pistoncore-v2   # wherever the repo is actually cloned
  git pull
  docker build -t pistoncore-v2 .
  docker rm -f pistoncore-v2
  docker run -d --name pistoncore-v2 \
    -p 7778:7777 \
    -v /mnt/user/appdata/pistoncore-data:/data \
    --restart unless-stopped \
    pistoncore-v2
  ```
  Port stays `7778` on the host side — an old v1 `pistoncore` container still holds `7777`.
- **Commits:** Jeremy pushes via GitHub Desktop, single combined commit per session.
- License: this repo is GPL-3.0 (required by the vendored dashboard). Keep upstream
  copyright headers intact.

## Repo map

- `dashboard/` — sealed upstream dashboard (see rules above)
- `reference/` — webcore_source_reference.groovy and other read-only upstream references
- Repo-root translation files: webcore_vocab.json, picker_capability_map.json
  (seed data for the db and device payloads; webcore_vocab.json's "ha" arrays +
  `_ha_translation` block are the HA read/write rules the shim strips before
  serving to the dashboard)
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

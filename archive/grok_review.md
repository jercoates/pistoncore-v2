# PistonCore v2 — whole-project review (Grok)

**Date:** 2026-07-19  
**Mode:** Read-only review against the authority chain (CLAUDE.md → COMPILER_DECISIONS_HOLDING.md → specs → session briefs). No code changes, no new features. Ranked by **real user impact**.

**Method:** Followed `REVIEW_PROMPT.md` authority order, then reviewed `shim/`, `templates/`, `static/pistoncore/`, `dashboard/` (sealed rules only), tests, and Docker packaging against those rules. After the written review, ran fixtures + corpus smoke + targeted checks (in-memory only; no project files modified except this document).

---

## Verification run (tests executed)

### Golden fixtures — `test_compile_fixtures.py`

| Test | Result |
|---|---|
| Cave Motion semantic YAML match | **PASS** |
| else-on-trigger-only-if (PyScript any-change, single deduped trigger) | **PASS** |

### Corpus smoke — 98 pistons under `test-pistons/` (+ `community/`)

In-memory `compile_piston` only; synthetic resolution map + stubbed device globals (not a live HA map).

| Outcome | Count |
|---|---|
| YAML | 33 |
| PyScript | 34 |
| Error | 31 |
| **Crash** | **0** |
| Compiling (yaml+pyscript) | **67/98 (68%)** |

**Caveats on the 68% figure:** Not comparable 1:1 to HOLDING’s reported 78/98 (that used richer/live-shaped resolution). Synthetic stubs still leave real gaps (e.g. `playTrack` domain mapping). The useful signals are: **zero crashes**, and top fallthrough reasons matching **C2** (computed notifications, `setVariable`, execute-only / no-trigger, nested loops).

Top reasons/errors from the smoke (first reason only, ranked):

| Count | Reason (abbreviated) |
|---|---|
| 8 | YAML: notification with computed message → PyScript |
| 7 | Unresolvable: no mapping for `playTrack` (stub domain issue / map gap) |
| 7 | YAML: `setVariable` requires PyScript |
| 4 | YAML: no triggers / no promotable conditions → PyScript |
| 3 | `cancelTasks` requires PyScript |
| 3 | YAML: top-level bare `action` not compiled yet |
| … | nested while/repeat, `$device`, etc. |

### Targeted checks (confirm review findings)

| Finding | Result |
|---|---|
| **A1** multi-device one bad hash | **Confirmed.** Whole piston raises `UnresolvableDevice`; DEPLOY §2 skip-and-flag not implemented |
| **B2** hash in error message | **Confirmed.** Message includes full `:abcdef…:` style hash |
| Atomic helpers | `write_json_atomic` / `read_json_safe` present |
| `classify_conditions` | Stamps `ct: t`, `s: True` on a trigger comparison |

---

## What looks healthy

- Compiler path does not mutate piston JSON; band preference lives in settings (`shim/compiler/__init__.py`).
- Atomic JSON writes + corrupt quarantine are in place (`shim/storage.py` ~483–523) — the failure mode the 2026-07-19 run warned about is addressed. Helpers verified present at runtime.
- Compile errors use the two announcement surfaces: front-door pills + piston-view banner via unsealed `pistoncore-nav.js` (not sealed template edits).
- PistonCore pages stay vanilla JS/HTML/CSS + Jinja2; Docker only ships `shim/`, not the dead `backend/` tree.
- `classify_conditions` / `$` stamping is intentional engine impersonation, documented and allowed by PISTON_JSON_REFERENCE / COMPILER_SPEC — not a “custom piston fields” violation. Runtime stamp of `ct`/`s` verified.
- Fixture suite green; corpus smoke had **zero crashes** across 98 pistons.

---

## A. DRIFT (code vs spec; spec wins)

### A1 — Multi-device unresolvable handling (high)

**Spec:** `COMPILER_DECISIONS_DEPLOY.md` §2 — multi-device statement with some unresolvable devices: skip the bad ones, compile the rest, **flag** the skips.

**Code:** `shim/compiler/resolve.py:74–102` hard-raises `UnresolvableDevice` on the first missing map entry / binding.

**Why it matters:** One dead/imported hash in a multi-device with-block fails the whole piston compile; other devices never deploy.

**Verified (runtime):** Compiling an if with two action devices (one good hash, one missing) raises `UnresolvableDevice` on the bad hash and fails the whole piston — no skip-and-flag path.

**Smallest fix:** In `entities_for_attr` / `entities_for_command`, collect skips, emit resolvable entities, attach warnings to the compile record (same surfaces). Only raise when the resolved set is empty.

### A2 — COMPILER_SPEC error surface wording (medium, doc)

**Spec:** `COMPILER_SPEC.md:25–26` — “Errors go to the **debug page**.”

**Authority:** CLAUDE.md — errors **announce** only on front-door list + piston status banner; debug/help is drill-in only.

**Why it matters:** Future sessions will reintroduce a third announcement surface if they follow COMPILER_SPEC literally.

**Smallest fix:** Change COMPILER_SPEC §1 to match CLAUDE.md’s two-surface + drill-in rule.

### A3 — Holding §G exit sketch vs §E5 (low, doc)

**HOLDING §E5:** YAML exit-with-value **implements** via `input_text` + `stop:`.

**HOLDING §G “exit” sketch (~766–772):** still says native drops the value.

**Why it matters:** Emitter implementers may re-open a settled decision.

**Smallest fix:** Edit §G exit sketch to match E5 (or mark sketch superseded).

### A4 — Stale user-facing / comment text (low)

| Location | Problem |
|---|---|
| `shim/compiler/emit_yaml.py:517–519` | Says “expression engine isn’t built yet” — PyScript expression path exists; YAML still routes computed messages to PyScript |
| `shim/routes/pages.py:25–30` | Docstring: “there is no compiler yet” — compiler is live |
| `shim/routes/dashboard.py:236–238` | Local `variable/set` still described as fully inert; HOLDING session notes claim local vars now persist on the piston state entity for PyScript |

**Smallest fix:** Correct messages/comments only; no behavior change required for the first two.

---

## B. RULE VIOLATIONS

### B1 — Entity IDs shown in Settings TTS picker (medium)

**Rule:** DEVICE_PAYLOAD_SPEC / CLAUDE — users see **only** friendly names; no entity_ids in any UI.

**Code:** `templates/settings.html:72`

```html
{{ e.name }} ({{ e.entity_id }})
```

**Why it matters:** Breaks the “Hubitat feel / names only” contract on a PistonCore page (not just sealed dashboard).

**Smallest fix:** Display `e.name` only; keep `entity_id` as the option `value` (already stored that way).

### B2 — Hashed device IDs in compile-error messages (medium)

**Rule:** No hashes/IDs on UI surfaces.

**Code:** `shim/compiler/resolve.py:80–81, 95–96`  
`f"no resolution-map entry for device {h} ..."` — `h` is the raw `:md5:` hash. That string becomes the banner/pill message.

**Why it matters:** Front-door and piston banners can show opaque hashes the user never picks by.

**Verified (runtime):** `entities_for_attr` with an unknown hash yields message  
`no resolution-map entry for device :abcdef0123456789abcdef0123456789: (attribute 'motion')`.

**Smallest fix:** Prefer resolution-map `name` when known; otherwise “unknown/imported device” + optional short id only on the drill-in diagnostics detail, not the banner.

### B3 — Sealed dashboard / frameworks (none found of note)

- `pistoncore-nav.js` + index script tag match SHIM_API_SPEC §9 approved extension.
- FontAwesome still CDN-first with local fallback (`dashboard/index.html:58–59`); §9 preferred full local vendor — degraded offline icons, not a new sealed edit.
- No React/Vue/build step under `static/pistoncore/` or `templates/`.
- Compiler does not write into piston JSON.

**Not a violation:** Shim stamping of `ct`/`s`/`$` on save (`storage.classify_conditions` / `assign_node_ids`) — authorized engine parity.

---

## C. STRUCTURAL RISK (highest user impact first)

### C1 — Device-global membership does not update deployed automations (critical)

**Design:** HOLDING §H — device globals compile to HA `group` entities; membership changes via `group.set`; no full recompile.

**Reality:**

- `used_by` tracking is built (`storage.update_used_by`).
- `group.set` path is **not** implemented (HOLDING H5 still accurate).
- `variable/set` only updates `globals.json` (`dashboard.py:240–241`).
- Resolve inlines global → hashes → entity_ids **at compile time** (`resolve.py:52–68`).

**Why it matters:** User edits “@Announce” / device group in the editor → UI looks correct → HA still drives the **old** entity list until every referencing piston is re-saved/recompiled. Silent wrong behavior, worst failure class in DEPLOY §2.

**Smallest fix (matches existing decision):** Emit `group.pistoncore_<slug>` targets; on global device edit, call `group.set`; on HA start, replay membership. Until then, force recompile of `used_by` pistons on device-global change (heavier, but honest).

### C2 — YAML band still under-implements native HA (high; known, open brief)

`SESSION_BRIEF_YAML_BAND_EXPANSION.md` is still open. Expression module is **Python-only** (`expression.py` header); no Jinja emitter; no `script.yaml.j2` emission target under `templates/compiler/yaml/`.

**Why it matters:** HOLDING product intent is YAML-first, PyScript as valve. Corpus still over-routes for computed messages, setVariable, switch, loops, execute-only pistons, etc. Users need PyScript for pistons HA can already express; more install friction and “why is this PyScript?” tickets.

**Verified (corpus smoke):** With synthetic maps, 33 YAML / 34 PyScript / 31 error; top fallthroughs include computed notifications (8), `setVariable` (7), no-trigger/execute-only (4+3), bare top-level action (3), nested while/repeat — aligned with `SESSION_BRIEF_YAML_BAND_EXPANSION.md`.

**Smallest fix:** Execute the open YAML expansion brief (Jinja emitter + script target + statement coverage), then re-measure the ~98 corpus (preferably with a real or fixture resolution map, not only synthetic stubs).

### C3 — Templates baked into the image, not a customize volume (medium)

COMPILER_SPEC §1 promises editable templates on a customize volume for “Recompile All” HA-break insurance. Docker copies `templates/` into the image; emitters load from repo-relative paths.

**Why it matters:** Fixing an HA template break requires rebuild/redeploy of the container, not a volume edit + recompile. Recompile All’s operational story is weaker than the spec claims.

**Smallest fix:** Mount/copy templates under `/data` (or a documented customize path) and point Jinja loaders there; fall back to image templates.

### C4 — Global device edit has no recompile hook (medium; related to C1)

Even without groups, `variable/set` never triggers `compile_and_deploy` for `used_by` pistons.

**Smallest fix:** After device-type global save, recompile each `used_by` entry (interim until C1’s group path).

### C5 — Soft swallows that hide environmental problems (medium-low)

Examples: `deploy.py:176–177` (service list check fails → treat as not present / log path); `front_door.js:56` banner best-effort; notify/speak device probes `except: pass` (`emit_yaml.py:472–473`).

**Why it matters:** Some failures still surface via status=error paths; others become “unverified” or silent fallback. Prefer explicit `unverified` / warning fields over empty `pass` where user action is needed.

### C6 — JSON stores (mitigated)

Atomic write + quarantine look correct for pistons, globals, settings, config, compile_status. No open brick-on-truncate path found in current code. Keep using `write_json_atomic` / `read_json_safe` for any new store.

---

## D. DEAD OR STALE

| Item | Notes |
|---|---|
| **`backend/` entire tree** (~10 files, v1 FastAPI + compiler) | Not in Dockerfile; not imported by `shim`. Dead weight and a footgun if someone runs it thinking it’s live. |
| **`SESSION_BRIEF_COMPILER_SPEC_FILL.md`** at repo root | §2.5 is largely filled; brief still looks open. Move to `archive/session-briefs/` if done. |
| **`SESSION_BRIEF_YAML_BAND_EXPANSION.md`** | Still valid open work — keep at root until executed. |
| **HOLDING H5 / “no compiler yet” phrasing** in places | Compiler exists; H’s **group.set** half is what remains unbuilt. |
| **`fuel.module.*.bak`** under dashboard | Sealed tree noise; leave unless cleanup is explicitly approved. |
| **`pages.py` “no compiler yet” docstring** | Stale (see A4). |

---

## E. TEST GAPS

**Existing:** `test_compile_fixtures.py` — Cave Motion golden YAML + one PyScript else/trigger regression. Corpus ≈ 84 + 14 community under `test-pistons/`.

**Run this review (2026-07-19):** fixtures **PASS**; ad-hoc corpus smoke **0 crashes** / 67 compiling under synthetic maps (not CI, not committed).

| Gap | Failure mode with no red test | Review status |
|---|---|---|
| No automated corpus gate | Routing/compile rate can regress without CI noticing | Smoke done once; not in repo CI |
| No test for multi-device partial unresolvable (A1/DEPLOY §2) | Spec behavior never enforced | **Manually confirmed still broken** |
| No test that error messages omit raw hashes (B2) | UI rule regresses silently | **Manually confirmed hashes leak** |
| No test that device-global change updates HA (C1) | Stale automations never caught | Still untested (needs HA or mock group.set) |
| No Jinja-emitter / script-emission tests | YAML expansion can ship half-done | Still open |
| No storage atomic/quarantine test | Corruption path could regress | Helpers present; no crash/recovery unit test |
| No `classify_conditions` promotion cases | Subscription counts / triggerless pistons drift | Basic stamp verified; full promotion matrix untested |

**Smallest high-value adds:** (1) commit a corpus smoke gate (no crash + optional band counts) with a fixture resolution map; (2) unit test for multi-device skip once A1 is fixed; (3) unit test that unresolvable messages never contain `:md5:`; (4) golden for a device-global operand once C1 lands.

---

## Summary ranking (do these first)

1. **C1/C4 — Device globals vs deployed reality** — silent wrong HA behavior after a normal editor action.
2. **C2 — YAML band expansion** — product intent already decided; open brief matches the over-routing finding.
3. **A1 — Multi-device unresolvable** — over-fails whole pistons vs DEPLOY §2.
4. **B1/B2 — IDs/hashes in UI** — clear standing rules, small fixes.
5. **A2/A3/D — Spec and dead `backend/` cleanup** — protect future sessions from wrong guidance.

---

## Explicit non-findings

- Compiler mutating piston JSON: **not found**.
- Third error announcement surface as a first-class route: **not found** (diagnostics remains drill-in).
- Frontend framework / build step on PistonCore pages: **not found**.
- Unauthorized sealed-dashboard surgery beyond SHIM_API_SPEC §9: **not found**.
- Corpus-wide crash bugs: **not found** in smoke (0/98 crashes under synthetic maps).

**Notes on numbers:** HOLDING’s 78/98 compile rate (2026-07-19 session notes) used a richer resolution context. This review’s synthetic-map smoke got **67/98 compiling** (33 YAML + 34 PyScript) with 0 crashes — good stability signal, not a regression scorecard against HOLDING. Re-measure with real maps after YAML band expansion for a fair before/after.

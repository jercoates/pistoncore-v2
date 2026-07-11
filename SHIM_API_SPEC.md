# SHIM_API_SPEC.md — PistonCore v2 Backend Contract

**Status:** Draft 1 — extracted from `dashboard/js/app.js` (ady624/webCoRE master, vendored in this repo).
**Authority:** This document is the spec for the FastAPI shim. Where this document and the shim code disagree, the code is wrong. Where this document and `dashboard/js/app.js` disagree, **app.js wins** — update this document.
**Tagging:** `VERIFIED` = read directly from dashboard source in this repo. `ASSUMED` = inferred, must be confirmed against source or Hubitat Groovy backend before relied on.

---

## 1. Big picture

The webCoRE dashboard is a static AngularJS app. It has no logic server-side awareness — it calls ~25 HTTP endpoints on a backend and renders what comes back. PistonCore v2 replaces that backend with a FastAPI app that:

1. Serves the dashboard's static files (`dashboard/` folder).
2. Answers every `intf/dashboard/...` endpoint below, fabricating webCoRE-shaped data from Home Assistant + PistonCore's translation files.
3. Intercepts saved piston JSON (the chunked `set` flow) and stores it for the compiler.

No changes to dashboard JS are required for v1 except neutralizing external services (§9).

---

## 2. Transport conventions (VERIFIED)

- **All `intf/dashboard/...` calls are JSONP**, not plain JSON. Every request includes a `callback=<fn>` query parameter. The response body MUST be:
  `<fn>({ ...json... })` with content type `application/javascript`.
  A FastAPI dependency should read `callback` and wrap every response. Plain JSON responses will silently fail to render.
- **All requests are GET** with query-string parameters (piston data arrives URL-encoded in the query string, chunked — see §7).
- **Auth parameters:** every call carries `token=<value>` and, if the instance URI included `?access_token=...`, an `access_token=<value>` parameter (VERIFIED: `getAccessToken()` app.js:757). For a local-only shim, both can be accepted and ignored; the shim must still tolerate their presence. The `load` response may include a `token` in the instance object, which the dashboard stores and sends back on subsequent calls (VERIFIED: `setSI()` app.js:664).
- **Error convention:** responses may include `error` (truthy) — dashboard shows a status banner and aborts the operation (VERIFIED: load/devices handlers).
- **Clock sync:** any response may include `now` = server epoch **milliseconds**; dashboard uses it to adjust its clock offset (VERIFIED: `adjustTimeOffset(data.now)`).
- **Emoji:** piston data is emoji-encoded in transit as `:%XX%XX%XX%XX:` sequences (VERIFIED: `encodeEmoji`/`decodeEmoji` app.js). Shim should store what it receives and return it unchanged; decoding is only needed if PistonCore tooling wants to read names.

---

## 3. Instance discovery & serving (VERIFIED)

- **Registration bypass:** route `/init/<base64>` where `<base64>` = base64 of the shim's base URI (utoa/atou, app.js:2398/2402 and route table app.js:484–506). Dashboard decodes it, stores it as the backend URI, redirects to `/`, and calls `<uri>intf/dashboard/load`. The api.webcore.co registration server is only contacted from the manual register page — never required.
  - The base URI **must end with `/`** (endpoints are appended directly: `uri + 'intf/dashboard/load?...'`).
  - Convenience: shim should serve a `/connect` redirect that computes the base64 and 302s to `/init/<base64>` so users never build the URL by hand.
- **Platform detection:** `si.uri.indexOf('things') > 0` → SmartThings mode, else Hubitat (`platformCode = 'he'`) (VERIFIED app.js:978–980). **The shim's URI must not contain the substring "things".** Hubitat mode is what we want (matches Session 14 sources).
- **SPA fallback:** `$locationProvider.html5Mode(true)` (VERIFIED app.js:510) — the shim must serve `index.html` for any non-file, non-`intf/` path (`/piston/xyz`, `/register`, `/init/...`, `/fuel`).

---

## 4. Endpoint catalog

All paths are relative to the base URI. Common params (`callback`, `token`, `access_token`) omitted below.

### 4.1 `intf/dashboard/load` (VERIFIED — the big one)
Params: `pin` (optional), `dashboard` (0/1), `dev` (client's cached deviceVersion), `session` (random client session id).
Response object:
```
{
  "now": <epoch ms>,
  "name": <instance display name>,            // ASSUMED placement; may live in instance
  "location": { see §6 },
  "instance": { see §5 }
}
```
Device-list optimization (VERIFIED app.js:997–1004): if `instance.deviceVersion` differs from the client's `dev` param and `instance.devices` is **omitted**, the dashboard automatically calls `intf/dashboard/devices` (paged) to fetch them. If `dev` matches, the client keeps its cached devices. Simplest v1: always bump/send `deviceVersion` and omit `devices` from `load`, letting the `devices` endpoint be the single source.

### 4.2 `intf/dashboard/devices` (VERIFIED)
Params: `offset` (int, starts 0).
Response: `{ "devices": { "<deviceId>": {device}, ... }, "complete": <bool>, "nextOffset": <int> }`
Client merges pages and re-calls with `nextOffset` until `complete` is truthy. v1 can return everything in one page with `complete: true`. Device object: §5.1.

### 4.3 `intf/dashboard/refresh` (VERIFIED)
No extra params. Returns same shape as `load` (dashboard tile refresh path). May return updated `instance.pistons` meta and current attribute values.

### 4.4 `intf/dashboard/piston/getDb` (VERIFIED)
Returns `{ "dbVersion": <string>, "db": { "capabilities": {...}, ... } }`.
The `db` is the webCoRE vocabulary — capabilities/attributes/commands/virtualCommands definitions that drive every wizard menu. `webcore_vocab.json` in PistonCore v1 was derived from this structure and is the seed content. Dashboard caches db locally keyed by `dbVersion` (VERIFIED piston/get handler app.js:1087–1124; `$scope.db.capabilities[...]` piston.module.js:2606).
**TO VERIFY:** exact top-level keys of `db` (expected: `capabilities`, `attributes`, `commands`, `virtualCommands`, possibly `functions`/`comparisons`) — confirm against Session 14 Groovy source or by diffing with webcore_vocab.json.

### 4.5 `intf/dashboard/piston/get` (VERIFIED — envelope corrected against source during spike)
Params: `id`, `db` (client's cached dbVersion), `dev` (deviceVersion).
Response:
```
{
  "dbVersion": <string, if client's db is stale>,
  "db": {..., optional},
  "location": {optional},
  "instance": {optional},
  "now": ...,
  "data": {
    "piston": {piston JSON},
    "meta": {...},
    "subscriptions": {}, "logs": [], "stats": {}, "state": "", "trace": {},
    "logging": 0, "memory": 0, "lastExecuted":, "nextSchedule":, "schedules":,
    "localVars": {}, "systemVars": {}
  }
}
```
`piston`/`meta` and the rest of the piston-specific fields are nested one level under a literal `data` key — **not top-level**. This is distinct from (and inside) the `$http` response's own `.data` wrapper: `dataService.getPiston` (app.js:1076–1128) resolves its promise to the raw JSONP payload unwrapped exactly once, and `piston.module.js:239–290` reads `response.data.piston`, `response.data.meta`, `response.data.logs`, etc. — confirmed by tracing both call sites during the spike (2026-07-09). An earlier draft of this doc had `piston` top-level; that was wrong.
If `dbVersion` present without `db`, client calls `getDb`. If `instance` absent when needed, client calls `load`. Simplest v1: include `dbVersion` + `db` when stale, omit `instance`/`location` (client re-fetches via `load`).

### 4.6 Piston lifecycle (VERIFIED call sites; response shapes ASSUMED minimal `{error?}` unless noted)
| Endpoint | Params | Notes |
|---|---|---|
| `piston/new` | — | Returns a fresh piston template/id (ASSUMED shape — likely `{piston}` or `{id}`; verify against Groovy) |
| `piston/create` | `author`, `name`, `bin` | Returns new piston id (ASSUMED `{id}`) |
| `piston/delete` | `id` | |
| `piston/pause` | `id` | Returns updated state (ASSUMED includes `state`/meta) |
| `piston/resume` | `id` | |
| `piston/test` | `id` | Fire the piston manually — in PistonCore, trigger the compiled automation |
| `piston/set.modified` | `id` | Touch timestamp |
| `piston/set.category` | `id`, `category` | |
| `piston/logging` | `id`, `level` | Log level 0–3 |
| `piston/clear.logs` | `id` | |
| `piston/tile` | `id`, `tile` | Piston tile interaction from dashboard view |
| `presence/create` | `name`, `dni` | Not applicable to HA — return `{error: "not supported"}` or hide feature |

### 4.7 Save flow — the compiler intercept (VERIFIED app.js:1276–1330)
Piston JSON is serialized, emoji-encoded, URL-encoded, and split into query-string-sized chunks.
- Small piston (1 chunk): single call `piston/set?id=<id>&data=<chunk>&bin=<binId>`.
- Large piston: `piston/set.start?id=<id>&chunks=<n>` → n × `piston/set.chunk?chunk=<i>&data=<...>` → `piston/set.end?bin=<binId>`.
Shim buffers chunks per session/piston, reassembles, URL-decodes, emoji-decodes → **this is the canonical piston JSON handed to storage and the compiler.**
Responses: ASSUMED `{error?}` plus probably updated piston meta; verify against Groovy `set.end` handler.
`bin` is the backup-bin id (§9) — accept and ignore in v1.

### 4.8 `intf/dashboard/piston/activity` (VERIFIED)
Params: `id`, `log` (last seen log timestamp, 0 first call), `session`.
Polled while a piston is open; feeds the console/trace. v1 (degraded status page per project decision): return `{ "logs": [], "state": {...current piston state...} }` — **TO VERIFY** exact keys the piston view reads (piston.module.js) before v2 instrumentation work.

### 4.9 `intf/dashboard/piston/backup` (VERIFIED)
Params: `ids` (comma-separated piston ids). Returns piston JSONs for backup/export. Worth implementing properly — it's the export path for the copy/paste share mechanism (IMPORT_EXPORT_SPEC.md).

### 4.10 `intf/dashboard/variable/set` (VERIFIED against `webcore_source_reference.groovy:1495-1528`, 2026-07-10)
Params: `name`, `value`, `id` (piston id, optional — absent = global variable).
`value` is `utoa(angular.toJson({t, v}))` — base64 of JSON, **no emoji-encode step** (unlike
piston save, §4.7) — then URL-encoded for transport. Decode: base64-decode → UTF-8 → JSON.parse.
The decoded object may also carry `n` (a rename: if present and differs from the `name`
param, the variable is stored under `value.n` instead, removing any entry under the old
`name`). Falsy `value` with a `name` present = delete.
**Global case (no `id`):** read/write the central global-variable store, keyed by `name`
(always `@`-prefixed — VERIFIED `piston.module.js:2278`), value `{t, v}`. Backs the
dashboard's global variable editor.
**Response (VERIFIED):** `{"status": "ST_SUCCESS", "globalVars": {...entire updated map...}}`
— the full map, not just the changed variable.
**Piston-local case (`id` present):** sets the piston's *current runtime value* for that
local variable (separate from the variable's definition/initial value, which lives in the
piston JSON's own `v` array and saves through the normal piston save flow, §4.7). Response:
`{"status": "ST_SUCCESS", "id": <pid>, "localVars": {...}}`. No execution engine exists yet
to give this runtime state meaning — accept and store, but it's inert until the compiler/
runtime exists.
**Device-type globals (VERIFIED, 2026-07-10):** stored exactly like every other type —
`v` is just the device-id array. Never embedded in piston JSON; pistons reference the
global by name only. Confirms COMPILER_DECISIONS_HOLDING.md §H1: editing a device global's
member list never requires a piston JSON patch, only a deployed-automation patch.

### 4.11 `intf/dashboard/settings/set` (VERIFIED)
Params: `settings` (URL-encoded JSON). Instance-level dashboard settings; store as an opaque blob and echo back in `load`.

### 4.12 `intf/dashboard/piston/evaluate` (VERIFIED)
Params: `id`, `expression`, `dataType`, `v`. The dashboard asks the **backend** to evaluate an expression (expression preview in the editor). Real implementation requires the expression engine — out of scope pre-compiler. v1: return `{ "value": "" }` or an "evaluation unavailable" error and confirm the editor degrades gracefully. **TO VERIFY** response shape + graceful-degradation behavior.

---

## 5. Data shapes

### 5.1 Device object (VERIFIED against `webcore.groovy:3541-3729`, `listAvailableDevices`/`getDevDetails`, 2026-07-10)
Keyed by device id in the `devices` map. Real Hubitat-fork shape (`getDevDetails()`) is
exactly 4 keys — **no more, no less**:
```
{
  "n":  <dnm — dev.getDisplayName()>,
  "cn": <dev.getCapabilities()*.name — the device's OWN declared capability list,
         NOT derived from its attributes (see DEVICE_PAYLOAD_SPEC.md Stage 3.3 —
         HA has no equivalent capability list, so PistonCore must derive cn from
         attributes instead; this is exactly why command-only capabilities like
         Speech Synthesis need their own lane)>,
  "a":  [ {"n": <attr.name>, "t": <attr.getDataType()>, "o": <attr.getValues()>}, ... ],
        // built straight from dev.getSupportedAttributes() — driver-reported, NOT
        // filtered through any central vocab (confirms DEVICE_PAYLOAD_SPEC.md
        // Stage 3.2's custom-attribute fallback matches real behavior). PLUS 3
        // synthetic attributes appended to every device, never from the driver:
        // lastActivityWC (datetime), roomIdWC (integer), roomNameWC (string).
  "c":  [ {"n": <command name, or overridden name if custom>, "p": [...]}, ... ]
        // p elements are objects {n, t, h?, c?} (name/type/hint/constraints,
        // types UPPERCASE e.g. "STRING"/"NUMBER") when the driver provides
        // structured parameter metadata, else a bare list of UPPERCASE type-name
        // strings as fallback. Commands not recognized by the vocab get cm:true
        // (custom) and their own param types uppercased the same way.
}
```
**Correction:** an earlier draft of this doc listed `o` (custom command display-name
overrides) and `an` as physical-device fields. VERIFIED WRONG — `getDevDetails()`'s return
has no `o`/`an` key at all. `piston.module.js:2664`'s `device.o` read is on
`instance.virtualDevices[id]` entries (routines/rules/location-modes — synthetic pseudo-
devices), never on a regular physical device. PistonCore's shim currently emits an empty
`"o": {}` and an `"an"` (anonymize-name) field on every device; harmless (nothing reads
either on a physical device) but not part of the real wire shape — safe to leave, not
required.
- Device **id key**: webCoRE hashes hub device ids (MD5-style strings like `:abcdef...:`, formula VERIFIED `:` + md5(`core.` + id) + `:`, `webcore.groovy:6368-6381`, matches PistonCore's `hash_id()` exactly). PistonCore uses a deterministic hash of the HA device-registry id (or entity_id for singletons) as the key and keeps a shim-side map hash → entity_id. Raw entity_ids as keys would probably work but hashed ids match every existing shared piston's format — **DECISION: hash, keep bidirectional map in storage.**

### 5.2 Instance object (VERIFIED `setInstance` app.js:672–740)
```
{
  "id": <stable instance id>,
  "name": <instance name>,
  "uri": <base uri>,            // stored client-side then deleted from object
  "token": <session token>,     // optional; echoed back on later calls
  "deviceVersion": <int/string>,  // bump when HA device set changes
  "devices": { ... } | omitted,   // see §4.1
  "pistons": [ { "id":, "name":, "meta": {...} }, ... ],
  "globalVars": { name: {t:, v:} },   // shape ASSUMED — verify
  "coreVersion": <string>,      // triggers version-nag banners; set equal to dashboard version() to silence (VERIFIED app.js:722–738)
  "settings": {},
  "lifx": {},                   // legacy LIFX integration; empty object
  "contacts": [],               // legacy ST contact book; empty
  "virtualDevices": {}          // defaults to {} client-side
}
```
**Piston `meta` — RESOLVED (VERIFIED-HE-GROOVY, 2026-07-10). Two genuinely different real
shapes exist, for two different call sites — not one shape reused:**
1. **List view** (`instance.pistons[].meta`, this section) — short keys, built by `gtMeta()`
   via `presult()`/`pitem()` (`webcore.groovy:1718-1740`), same shape `curPState()` returns:
   ```
   { "a": <active bool>, "c": <category>, "t": <lastExecuted ms>, "m": <modified ms>,
     "b": <bin id>, "n": <nextSchedule ms>, "z": <description>, "s": <state map>,
     "heCached": <bool> }
   ```
   Matches `dashboard.module.js`'s `piston.meta.a` active/paused-bucket filtering exactly.
2. **`piston/get` response meta** (§4.5) — long keys, built by the piston's own `get()`
   (`webcore-piston.groovy:1148-1166`):
   ```
   { "id":, "author":, "name":, "created":, "modified":, "build":, "bin":, "active":,
     "category": }
   ```
   Matches `piston.module.js:599-606`'s save-success gate (`response.data.build` truthy →
   applies `.active`/`.modified`/`.build`).
PistonCore's shim currently stores one hybrid dict per piston with fields from both shapes
combined, and serves whichever fields each endpoint needs from it — functionally correct
(behaviorally verified, milestone 3) but structurally simpler than real webCoRE's two
separate derived views. Not a bug; worth knowing if a future session wants exact parity.

### 5.3 Location object (VERIFIED field usage)
Fields read: `id`, `name`, `mode` (current), `modes` (list), `shm` (Smart Home Monitor / HSM state — PistonCore maps to HA `alarm_control_panel`), `temperatureScale` (`"F"`/`"C"`), `timeZone`, plus zip/lat-long for sunrise/sunset — **TO VERIFY** exact time/sun field names against Groovy (`getLocationData`). Source in HA: core config API + `sun.sun` + a designated alarm entity + an `input_select` (or HA native) for modes.

---

## 6. The db / vocabulary (design note)

`webcore_vocab.json` (71 capabilities / 90 attributes / 73 commands / 59 virtualCommands) is the seed for the `getDb` payload. Task: confirm the exact envelope shape from Session 14 Groovy (`api_intf_dashboard_piston_get` / db construction) and re-emit vocab in that envelope. `dbVersion` becomes a PistonCore-managed version string; bump whenever vocab changes to bust client caches.

---

## 7. Save pipeline (PistonCore behavior)

1. Reassemble chunks (§4.7) → canonical webCoRE piston JSON.
2. Store verbatim in JSON storage (this format is now the **only** piston format in v2 — PISTON_JSON_REFERENCE.md documents it; the v1 nested-tree format is retired).
3. Queue/trigger compile (compiler spec, future). Save must succeed even if compile fails; compile errors surface via piston state/logs, not save errors.

---

## 8. Import / export & AI authoring (pointer)

`piston/backup` (§4.9) exports piston JSON; a paste-JSON import path replaces webCoRE's cloud bins. Because the entire system speaks one documented JSON format, AI-generated pistons = "produce JSON per PISTON_JSON_REFERENCE.md, import it." Details in IMPORT_EXPORT_SPEC.md (to be written).

---

## 9. External services to neutralize (VERIFIED URLs in source)

| Where | What | Action |
|---|---|---|
| index.html | Google Analytics | Delete |
| index.html | FontAwesome kit (kit.fontawesome.com) + v4-shims (pro.fontawesome.com) | Vendor locally or icons break offline |
| index.html | maps.google.com JS | Stub/remove; only location-map UI uses it |
| app.js:1162–1211 | `api.webcore.co/bins/...` backup bins | Disable/hide UI or point at shim; superseded by §8 |
| app.js:1507 | `api.webcore.co/dashboard/register/` | Unused via `/init/` path; leave |
| app.js | `cdn.jsdelivr.net/gh/imnotbob/webCoRE` reference | **TO VERIFY** what loads from it; localize if active |
| app.js:2 | `cdn = ''` | Already relative — no action (VERIFIED) |

---

## 10. Open items (next spec sessions)

1. Most items below RESOLVED 2026-07-10 against the real ady624 Hubitat-fork source
   (`reference/webCoRE-hubitat-patches-extracted/`, "Last update July 5, 2026 for
   Hubitat" — see SESSION_BRIEF_HUBITAT_MINING.md): db envelope (§4.4/§6), device
   serialization (§5.1 — `c` elements are objects with UPPERCASE types, `an` was never
   real, `o` was mis-attributed to the wrong object), piston meta keys (§5.2, two real
   shapes). Location time/sun fields and `evaluate` degradation remain open — not reached
   this pass.
2. ~~Check `openWebSocket`~~ — RESOLVED (2026-07-10): the Hubitat-fork backend has **zero**
   websocket code. It's purely a cloud feature (`api-us-*.webcore.co:9297`, the commercial
   webcore.co relay) — never served by a self-hosted install. The dashboard already has to
   tolerate its absence (retry-with-backoff on connect failure, app.js's onclose/onerror
   handlers). Shim: ignore, no stub needed.
3. PISTON_JSON_REFERENCE.md — extract full piston JSON format from Session 14 sources. **Status:** §8 ($ id assignment) and §10.5's comparison trigger/condition split resolved 2026-07-10; rest still open.
4. DEVICE_PAYLOAD_SPEC.md — entity_id → device object pipeline using picker_capability_map + vocab + attribute translation. **Status:** built (milestone 2), Stage 3.1/3.2/3.3 added since.
5. Spike milestone: static serving + `/connect` + hardcoded `load`/`devices`/`getDb` with 3 fake devices → dashboard renders piston list and device picker. **Status: DONE (milestone 1).**
6. TRACE_ACTIVITY_CONTRACT.md (new, 2026-07-10) — `piston/activity` response shape and log-entry shape resolved; the `state`/`trace` blobs' write sites (not just where they're read/served from) still need a dedicated trace before the compiler can commit to a trace strategy.

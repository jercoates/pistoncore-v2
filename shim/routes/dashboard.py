"""intf/dashboard/* endpoints (SHIM_API_SPEC.md §4).

load/devices are backed by the real DEVICE_PAYLOAD_SPEC.md pipeline against
live HA data (milestone 2). Pistons and global variables persist for real
via shim/storage.py (milestone 3, SHIM_API_SPEC.md §4.7/§4.10). Location is
still fixture data — no HA location/mode/HSM pipeline built yet.
"""

import hashlib
import json
import logging
import traceback
from datetime import datetime

from fastapi import APIRouter, Request

from .. import device_pipeline, fixtures, ha_client, storage
from ..compiler import deploy as compiler_deploy
from ..jsonp import jsonp

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/intf/dashboard")

# Captured so a remote / first-run user's dashboard-load failure is diagnosable
# WITHOUT their server logs: open /whats-wrong in the browser to read it. Set on
# every /load (SHIM_API_SPEC.md §4) — see the load handler.
LAST_LOAD_DIAG: dict = {
    "ok": True, "stage": None, "error": None, "traceback": None, "skipped": [],
}

# In-memory cache — HA registry fetch is a WebSocket round trip; no point
# repeating it on every /load + /devices pair. Cleared only by server
# restart for now (matches the "simplest v1" level of the rest of this
# milestone); a manual refresh/TTL can come later if it's needed.
# Split from the device payload cache (SHIM_API_SPEC.md §5.3) since location
# building needs the raw states/config too, and may need to bust this cache
# once (see _get_registries) right after auto-creating the Location Mode
# helper, without touching the (unrelated) device payload cache.
_registries_cache: dict | None = None
_device_payload_cache: dict | None = None


async def _get_registries() -> dict:
    global _registries_cache
    if _registries_cache is None:
        _registries_cache = await ha_client.fetch_registries()
    return _registries_cache


def reset_device_cache() -> None:
    """Drop the cached HA device snapshot so the NEXT /load|/devices re-fetches.
    Call after anything that changes HA's devices behind the shim (e.g. creating
    or removing a test device) — otherwise the editor's device picker stays stale
    and a new test device isn't usable until a restart."""
    global _registries_cache, _device_payload_cache
    _registries_cache = None
    _device_payload_cache = None

# Chunked piston save, in progress (SHIM_API_SPEC.md §4.7). set.chunk/set.end
# carry no piston id or session id at all (VERIFIED app.js:1278-1292) — the
# dashboard sends set.start -> n x set.chunk -> set.end strictly sequentially
# per save (recursive promise chain, never interleaved), and this is a
# single-user local shim, so one module-level buffer for "the save currently
# in progress" is correct, not a shortcut.
_pending_save: dict | None = None


async def _get_device_payload() -> dict:
    global _device_payload_cache
    if _device_payload_cache is None:
        registries = await _get_registries()
        _device_payload_cache = device_pipeline.build_device_payload(registries)
    return _device_payload_cache


def _device_version(devices: dict) -> str:
    # Stage 9: hash over the devices map (no "v" values exist yet — Stage 5
    # is deferred — so this only changes on membership/capability/name
    # changes, which is exactly what's supposed to bump it).
    serialized = json.dumps(devices, sort_keys=True)
    return hashlib.md5(serialized.encode("utf-8")).hexdigest()


@router.get("/load")
async def load(request: Request):
    global _registries_cache
    LAST_LOAD_DIAG.update({"ok": True, "stage": None, "error": None, "traceback": None, "skipped": []})
    try:
        LAST_LOAD_DIAG["stage"] = "reading your Home Assistant devices"
        payload = await _get_device_payload()
        LAST_LOAD_DIAG["skipped"] = payload.get("skipped", [])

        LAST_LOAD_DIAG["stage"] = "reading Home Assistant location / mode"
        registries = await _get_registries()
        location, helper_created = await fixtures.build_location(registries)
        if helper_created:
            # Next fetch picks up the newly-created helper for free; this
            # response is already correct without waiting (built from the
            # create call's own result) — see fixtures.build_location.
            _registries_cache = None

        LAST_LOAD_DIAG["stage"] = "assembling the dashboard"
        virtual_devices = fixtures.build_virtual_devices([m["name"] for m in location["modes"]])
        instance = fixtures.fake_instance(str(request.base_url), virtual_devices)
        instance["deviceVersion"] = _device_version(payload["devices"])
        instance["pistons"] = storage.list_pistons()
        instance["globalVars"] = storage.globals_for_wire()
        LAST_LOAD_DIAG["stage"] = None
        return jsonp(request, {
            "location": location,
            "instance": instance,
        })
    except Exception as exc:
        # A first-run user must never be left on an eternal "loading…" with a
        # blank 500 and no clue why. We can't reach their server logs, so capture
        # exactly what broke (which stage, the error, the traceback) — readable
        # at /whats-wrong in their browser — and log it. Re-raise so the
        # dashboard's own retry still applies; the diagnosis is now retrievable.
        LAST_LOAD_DIAG.update({
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        })
        logger.exception("dashboard /load failed at stage: %s", LAST_LOAD_DIAG["stage"])
        raise


@router.get("/devices")
async def devices(request: Request):
    payload = await _get_device_payload()
    return jsonp(request, {
        "devices": payload["devices"],
        "complete": True,
        "nextOffset": 0,
    })


@router.get("/piston/getDb")
def get_db(request: Request):
    return jsonp(request, {
        "dbVersion": fixtures.DB_VERSION,
        "db": fixtures.get_db(),
    })


@router.get("/piston/new")
def piston_new(request: Request):
    return jsonp(request, fixtures.new_piston_name())


@router.get("/piston/create")
def piston_create(request: Request):
    name = request.query_params.get("name", "")
    author = request.query_params.get("author", "")
    entry = storage.create_piston(name, author)
    return jsonp(request, {"id": entry["id"]})


@router.get("/piston/get")
def piston_get(request: Request):
    # piston/meta live under a nested "data" key, distinct from Angular's own
    # $http response.data wrapper — piston.module.js:244 reads
    # response.data.piston, and dataService.getPiston (app.js:1076-1128)
    # resolves to the raw payload unwrapped once, not twice. Verified against
    # source; SHIM_API_SPEC.md §4.5 said "piston" was top-level — that was wrong.
    piston_id = request.query_params.get("id", "")
    entry = storage.load_piston(piston_id)
    if entry is None:
        piston, meta = {"o": {"cto": 0, "ced": 0}, "r": [], "s": [], "v": [], "z": ""}, {}
    else:
        piston, meta = entry["piston"], storage.meta_for_get(entry)

    # Client sends its cached db version (app.js:1083, "&db=" + dbVersion).
    # Only include dbVersion/db when it's actually stale/missing -- sending
    # it unconditionally makes the dashboard show "Database updated" on
    # every single load (app.js:1116-1119 has no comparison of its own).
    client_db_version = request.query_params.get("db", "")
    # subscriptions meta: piston.module.js:258 reads response.data.subscriptions
    # (Quick Facts "Subscriptions: N events" + the no-subscriptions warning
    # banner, piston.module.html:133). Counted from the ct/s stamps the save
    # flow writes (storage.classify_conditions — engine-equivalent behavior).
    subscriptions = {"events": storage.count_subscriptions(piston), "controls": 0}
    # localVars: piston's stored runtime variable values (webcore-piston.groovy
    # get() :1170 serves state.vars = {name: raw value}; empty until a piston
    # has actually run — faithful here since no engine runs pistons). MUST be
    # present even when empty: piston.module.js:724 does
    # `variable.n in $scope.localVars` with no guard — absent map = TypeError
    # on EVERY digest = all global-variable values silently render blank
    # (found via live repro 2026-07-19, "@Speakers_All = ;" bug).
    response: dict = {"data": {"piston": piston, "meta": meta,
                               "subscriptions": subscriptions, "localVars": {}}}
    if client_db_version != fixtures.DB_VERSION:
        response["dbVersion"] = fixtures.DB_VERSION
        response["db"] = fixtures.get_db()
    return jsonp(request, response)


@router.get("/piston/delete")
async def piston_delete(request: Request):
    """webCoRE's delete button (piston.module.js:653 $scope.del ->
    dataService.deletePiston, app.js:1445). This route was missing entirely, so
    every delete 404'd and nothing was removed. Undeploy the compiled automation
    from HA first (so it stops running), then delete the stored piston. The
    caller only needs the request to succeed, then it navigates home."""
    piston_id = request.query_params.get("id", "")
    if piston_id:
        await compiler_deploy.undeploy(piston_id)
        storage.delete_piston(piston_id)
    return jsonp(request, {"status": "ST_SUCCESS"})


def _iso_ms(iso) -> int:
    """HA ISO timestamp -> epoch ms (webCoRE's lastExecuted/nextSchedule unit)."""
    if not iso:
        return 0
    try:
        return int(datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return 0


@router.get("/piston/activity")
async def piston_activity(request: Request):
    """The piston status/trace screen polls this every 3s (app.js:1151). Minimum
    viable today (TRACE_ACTIVITY_CONTRACT.md): live `state` + `lastExecuted` from
    real HA — logs and the per-statement trace overlay layer on next. Response is
    wrapped under "activity" (piston.module.js:164 reads response.activity.*)."""
    piston_id = request.query_params.get("id", "")
    entry = storage.load_piston(piston_id)
    name = entry["name"] if entry else ""
    status = compiler_deploy.load_statuses().get(piston_id, {})
    try:
        states = {s["entity_id"]: s for s in await ha_client.get_states()}
    except Exception:
        states = {}

    last_executed = 0
    state_blob: dict = {}
    local_vars: dict = {}

    # PyScript band: the persisted state entity holds state + local vars; its last
    # update is ~when the piston last ran.
    st = states.get(f"pyscript.pistoncore_{piston_id}_state")
    if st:
        last_executed = _iso_ms(st.get("last_updated") or st.get("last_changed"))
        attrs = st.get("attributes", {}) or {}
        local_vars = attrs.get("vars", {}) or {}
        state_blob = {k: v for k, v in attrs.items() if k != "friendly_name"}

    # YAML/script band: last_triggered across our emitted automations.
    auto_ids = set(status.get("auto_ids") or [])
    if auto_ids:
        for eid, s in states.items():
            if eid.startswith("automation.") and s.get("attributes", {}).get("id") in auto_ids:
                last_executed = max(last_executed, _iso_ms(s.get("attributes", {}).get("last_triggered")))

    return jsonp(request, {"activity": {
        "name": name,
        "state": state_blob,
        "logs": [],          # step 4
        "trace": {},         # step 5
        "localVars": local_vars,
        "memory": "unknown",
        "lastExecuted": last_executed,
        "nextSchedule": 0,
        "schedules": [],
        "systemVars": {},
    }})


def _save_response(entry: dict) -> dict:
    # piston.module.js:599-606 — only treats a save as successful if
    # response.data.build is truthy, then applies these three fields
    # (long names — different from the "a"/"c"/"m" short names the piston
    # LIST view reads elsewhere; both are real, verified webCoRE shapes,
    # storage.py's meta_for_get/meta_for_list build them separately).
    meta = storage.meta_for_get(entry)
    return {"active": meta["active"], "modified": meta["modified"], "build": meta["build"]}


@router.get("/piston/set")
async def piston_set(request: Request):
    piston_id = request.query_params.get("id", "")
    data = request.query_params.get("data", "")
    piston_json = storage.decode_piston_data(data)
    entry = storage.save_piston(piston_id, piston_json)
    await compiler_deploy.compile_and_deploy(piston_id)  # compile-on-save (§1)
    return jsonp(request, _save_response(entry))


@router.get("/piston/set.start")
def piston_set_start(request: Request):
    global _pending_save
    piston_id = request.query_params.get("id", "")
    chunks = int(request.query_params.get("chunks", "0"))
    _pending_save = {"piston_id": piston_id, "chunks": [None] * chunks}
    return jsonp(request, {"status": "ST_READY"})


@router.get("/piston/set.chunk")
def piston_set_chunk(request: Request):
    chunk_index = int(request.query_params.get("chunk", "0"))
    data = request.query_params.get("data", "")
    if _pending_save is not None and 0 <= chunk_index < len(_pending_save["chunks"]):
        _pending_save["chunks"][chunk_index] = data
    return jsonp(request, {"status": "ST_SUCCESS"})


@router.get("/piston/set.end")
async def piston_set_end(request: Request):
    global _pending_save
    if _pending_save is None:
        return jsonp(request, {"error": "ERR_NO_PENDING_SAVE"})
    reassembled = "".join(_pending_save["chunks"])
    piston_json = storage.decode_piston_data(reassembled)
    piston_id = _pending_save["piston_id"]
    entry = storage.save_piston(piston_id, piston_json)
    _pending_save = None
    await compiler_deploy.compile_and_deploy(piston_id)  # compile-on-save (§1)
    return jsonp(request, _save_response(entry))


@router.get("/piston/pause")
async def piston_pause(request: Request):
    piston_id = request.query_params.get("id", "")
    entry = storage.set_piston_active(piston_id, False)
    if entry is None:
        return jsonp(request, {"error": "ERR_INVALID_ID"})
    rec = await compiler_deploy.compile_and_deploy(piston_id)  # paused -> undeploy
    return jsonp(request, {"status": "ST_SUCCESS", "active": entry["meta"]["active"], "compile": rec})


@router.get("/piston/resume")
async def piston_resume(request: Request):
    piston_id = request.query_params.get("id", "")
    entry = storage.set_piston_active(piston_id, True)
    if entry is None:
        return jsonp(request, {"error": "ERR_INVALID_ID"})
    rec = await compiler_deploy.compile_and_deploy(piston_id)  # resume -> redeploy
    return jsonp(request, {"status": "ST_SUCCESS", "active": entry["meta"]["active"], "compile": rec})


@router.get("/variable/recompile")
async def variable_recompile(request: Request):
    """The 'update them now' half of the device-global prompt: recompile every
    piston that uses the changed global so HA stops driving the old device
    list. Declining is equally valid — each piston recompiles on its own next
    save (Jeremy's ruling 2026-07-19: prompt, auto or manual — never silent)."""
    ids = [i for i in (request.query_params.get("ids", "").split(",")) if i]
    done = []
    for pid in ids:
        rec = await compiler_deploy.compile_and_deploy(pid)
        done.append({"id": pid, "status": rec.get("status"),
                     "message": rec.get("message")})
    return jsonp(request, {"status": "ST_SUCCESS", "recompiled": done})


@router.get("/variable/set")
async def variable_set(request: Request):
    name = request.query_params.get("name", "")
    data = request.query_params.get("value", "")
    pid = request.query_params.get("id")
    value = storage.decode_base64_json(data) if data else None

    if pid:
        # Piston-local runtime value — inert until a compiler/execution
        # engine exists to give it meaning (SHIM_API_SPEC.md §4.10).
        return jsonp(request, {"status": "ST_SUCCESS", "id": pid, "localVars": {}})

    before = storage.load_globals().get(name) or {}
    updated = storage.set_global_variable(name, value)

    # A device global is INLINED into compiled automations at compile time, so
    # changing its devices leaves every deployed automation driving the OLD
    # entity list until each piston is re-saved — the UI looks right while HA
    # does the wrong thing (found by external review, 2026-07-19). Recompile
    # the pistons that reference it. (HOLDING §H's group.set design would
    # avoid the recompile entirely; this is the honest interim.)
    # A device global is inlined into compiled automations, so changing its
    # devices leaves deployed automations driving the OLD list until each
    # piston recompiles. RULING (Jeremy, 2026-07-19): do NOT silently
    # recompile — save the variable, then PROMPT: update those pistons now,
    # or leave them and update manually. The prompt is driven from the
    # affected list returned here.
    affected = []
    is_device = (before.get("t") == "device") or ((value or {}).get("t") == "device")
    if is_device and before.get("v") != (value or {}).get("v"):
        affected = [{"id": u["id"], "name": u.get("name")}
                    for u in (before.get("used_by") or [])]
    return jsonp(request, {"status": "ST_SUCCESS", "globalVars": updated,
                           "affected": affected, "variable": name})

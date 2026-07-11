"""intf/dashboard/* endpoints (SHIM_API_SPEC.md §4).

load/devices are backed by the real DEVICE_PAYLOAD_SPEC.md pipeline against
live HA data (milestone 2). Pistons and global variables persist for real
via shim/storage.py (milestone 3, SHIM_API_SPEC.md §4.7/§4.10). Location is
still fixture data — no HA location/mode/HSM pipeline built yet.
"""

import hashlib
import json

from fastapi import APIRouter, Request

from .. import device_pipeline, fixtures, ha_client, storage
from ..jsonp import jsonp

router = APIRouter(prefix="/intf/dashboard")

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
    payload = await _get_device_payload()
    registries = await _get_registries()
    location, helper_created = await fixtures.build_location(registries)
    if helper_created:
        # Next fetch picks up the newly-created helper for free; this
        # response is already correct without waiting (built from the
        # create call's own result) — see fixtures.build_location.
        _registries_cache = None

    virtual_devices = fixtures.build_virtual_devices([m["name"] for m in location["modes"]])
    instance = fixtures.fake_instance(str(request.base_url), virtual_devices)
    instance["deviceVersion"] = _device_version(payload["devices"])
    instance["pistons"] = storage.list_pistons()
    instance["globalVars"] = storage.globals_for_wire()
    return jsonp(request, {
        "location": location,
        "instance": instance,
    })


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
        "dbVersion": "pistoncore-spike-1",
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
    return jsonp(request, {
        "dbVersion": "pistoncore-spike-1",
        "db": fixtures.get_db(),
        "data": {
            "piston": piston,
            "meta": meta,
        },
    })


def _save_response(entry: dict) -> dict:
    # piston.module.js:599-606 — only treats a save as successful if
    # response.data.build is truthy, then applies these three fields
    # (long names — different from the "a"/"c"/"m" short names the piston
    # LIST view reads elsewhere; both are real, verified webCoRE shapes,
    # storage.py's meta_for_get/meta_for_list build them separately).
    meta = storage.meta_for_get(entry)
    return {"active": meta["active"], "modified": meta["modified"], "build": meta["build"]}


@router.get("/piston/set")
def piston_set(request: Request):
    piston_id = request.query_params.get("id", "")
    data = request.query_params.get("data", "")
    piston_json = storage.decode_piston_data(data)
    entry = storage.save_piston(piston_id, piston_json)
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
def piston_set_end(request: Request):
    global _pending_save
    if _pending_save is None:
        return jsonp(request, {"error": "ERR_NO_PENDING_SAVE"})
    reassembled = "".join(_pending_save["chunks"])
    piston_json = storage.decode_piston_data(reassembled)
    entry = storage.save_piston(_pending_save["piston_id"], piston_json)
    _pending_save = None
    return jsonp(request, _save_response(entry))


@router.get("/variable/set")
def variable_set(request: Request):
    name = request.query_params.get("name", "")
    data = request.query_params.get("value", "")
    pid = request.query_params.get("id")
    value = storage.decode_base64_json(data) if data else None

    if pid:
        # Piston-local runtime value — inert until a compiler/execution
        # engine exists to give it meaning (SHIM_API_SPEC.md §4.10).
        return jsonp(request, {"status": "ST_SUCCESS", "id": pid, "localVars": {}})

    updated = storage.set_global_variable(name, value)
    return jsonp(request, {"status": "ST_SUCCESS", "globalVars": updated})

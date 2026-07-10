"""intf/dashboard/* endpoints (SHIM_API_SPEC.md §4).

load/devices are backed by the real DEVICE_PAYLOAD_SPEC.md pipeline against
live HA data (milestone 2). piston/getDb + enough of the new/create/get
lifecycle to reach the editor still run on fixture data — the chunked save
flow (piston/set*) isn't implemented yet; that's milestone 3.
"""

import hashlib
import json

from fastapi import APIRouter, Request

from .. import device_pipeline, fixtures, ha_client
from ..jsonp import jsonp

router = APIRouter(prefix="/intf/dashboard")

# In-memory cache — HA registry fetch is a WebSocket round trip; no point
# repeating it on every /load + /devices pair. Cleared only by server
# restart for now (matches the "simplest v1" level of the rest of this
# milestone); a manual refresh/TTL can come later if it's needed.
_device_payload_cache: dict | None = None


async def _get_device_payload() -> dict:
    global _device_payload_cache
    if _device_payload_cache is None:
        registries = await ha_client.fetch_registries()
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
    payload = await _get_device_payload()
    instance = fixtures.fake_instance(str(request.base_url))
    instance["deviceVersion"] = _device_version(payload["devices"])
    return jsonp(request, {
        "location": fixtures.FAKE_LOCATION,
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
    return jsonp(request, fixtures.create_piston(name, author))


@router.get("/piston/get")
def piston_get(request: Request):
    # piston/meta live under a nested "data" key, distinct from Angular's own
    # $http response.data wrapper — piston.module.js:244 reads
    # response.data.piston, and dataService.getPiston (app.js:1076-1128)
    # resolves to the raw payload unwrapped once, not twice. Verified against
    # source; SHIM_API_SPEC.md §4.5 said "piston" was top-level — that was wrong.
    piston_id = request.query_params.get("id", "")
    entry = fixtures.get_piston_entry(piston_id)
    return jsonp(request, {
        "dbVersion": "pistoncore-spike-1",
        "db": fixtures.get_db(),
        "data": {
            "piston": entry["piston"],
            "meta": entry["meta"],
        },
    })

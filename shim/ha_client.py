"""Home Assistant WebSocket client.

Connection/auth mechanics ported from backend/ha_client.py (v1's HA client):
supervisor-token mode (SUPERVISOR_TOKEN env var, HA add-on deployment) and
token mode (ha_url/ha_token read from config.json in the persistent data
dir, Docker deployment). The registry-fetching methods below are new —
v1 fetched entities only; DEVICE_PAYLOAD_SPEC.md Stage 1 needs the device
registry too, to group entities by their physical device.
"""

import json
import os
from pathlib import Path

import websockets

DATA_DIR = Path(os.environ.get("PISTONCORE_DATA_DIR", "/pistoncore-userdata"))
CONFIG_FILE = DATA_DIR / "config.json"


class HAClientError(Exception):
    pass


def _load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def _load_auth() -> tuple[str, str]:
    """Returns (ha_url, token). Supervisor mode wins if SUPERVISOR_TOKEN is set."""
    supervisor_token = os.environ.get("SUPERVISOR_TOKEN")
    if supervisor_token:
        return "http://supervisor/core", supervisor_token
    config = _load_config()
    return config.get("ha_url", ""), config.get("ha_token", "")


async def _ws_call(messages: list[dict]) -> dict[int, dict]:
    """
    Open a WebSocket connection to HA, authenticate, send all messages,
    collect results keyed by message id, close.
    """
    ha_url, token = _load_auth()
    if not token:
        raise HAClientError("No HA token configured. Set ha_token in config.json.")
    if not ha_url:
        raise HAClientError("No HA URL configured. Set ha_url in config.json.")

    ws_url = (
        ha_url.rstrip("/")
        .replace("http://", "ws://")
        .replace("https://", "wss://")
        + "/api/websocket"
    )

    pending_ids = {m["id"] for m in messages}
    results: dict[int, dict] = {}

    try:
        async with websockets.connect(ws_url, open_timeout=10) as ws:
            auth_req = json.loads(await ws.recv())
            if auth_req.get("type") != "auth_required":
                raise HAClientError(f"Unexpected HA handshake: {auth_req}")

            await ws.send(json.dumps({"type": "auth", "access_token": token}))
            auth_resp = json.loads(await ws.recv())
            if auth_resp.get("type") != "auth_ok":
                raise HAClientError("HA authentication failed. Check ha_token in config.json.")

            for msg in messages:
                await ws.send(json.dumps(msg))

            while pending_ids:
                raw = await ws.recv()
                msg = json.loads(raw)
                msg_id = msg.get("id")
                if msg_id in pending_ids and msg.get("type") == "result":
                    pending_ids.discard(msg_id)
                    results[msg_id] = msg

    except websockets.exceptions.WebSocketException as e:
        raise HAClientError(f"WebSocket error: {e}") from e
    except OSError as e:
        raise HAClientError(f"Could not connect to HA at {ws_url}: {e}") from e

    return results


async def fetch_registries() -> dict:
    """
    Fetch device registry, entity registry, area registry, core config, and
    current states from HA. Raw HA API results, no PistonCore-specific
    shaping — DEVICE_PAYLOAD_SPEC.md Stage 1 grouping happens in
    device_pipeline.py; location building (SHIM_API_SPEC.md §5.3) happens
    in fixtures.py. Shared here (one round trip) since both consumers need
    the same states/config snapshot.
    """
    results = await _ws_call([
        {"id": 1, "type": "config/device_registry/list"},
        {"id": 2, "type": "config/entity_registry/list"},
        {"id": 3, "type": "config/area_registry/list"},
        {"id": 4, "type": "get_states"},
        {"id": 5, "type": "get_config"},
        {"id": 6, "type": "get_services"},
    ])

    for msg_id, result in results.items():
        if not result.get("success"):
            raise HAClientError(f"HA returned error for message id {msg_id}: {result.get('error')}")

    return {
        "devices": results[1]["result"],
        "entities": results[2]["result"],
        "areas": results[3]["result"],
        "states": results[4]["result"],
        "config": results[5]["result"],
        "services": results[6]["result"],
    }


async def create_input_select(name: str, options: list[str]) -> dict:
    """
    Auto-creates a storage-backed input_select helper (SHIM_API_SPEC.md
    §5.3 location-mode decision, Jeremy 2026-07-11). VERIFIED live against
    real HA (2026.7.2): "input_select/create" (name, options) -> HA assigns
    the entity_id as input_select.<slugified name>, defaults state to the
    first option. No "config/" prefix — unlike the registry list calls
    above, helper CRUD is its own top-level command namespace per domain
    (confirmed by testing "config/input_select/list", which does not exist).
    """
    results = await _ws_call([
        {"id": 1, "type": "input_select/create", "name": name, "options": options},
    ])
    result = results[1]
    if not result.get("success"):
        raise HAClientError(f"Could not create input_select helper {name!r}: {result.get('error')}")
    return result["result"]

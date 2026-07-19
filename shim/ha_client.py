"""Home Assistant WebSocket client.

Connection/auth mechanics ported from backend/ha_client.py (v1's HA client):
supervisor-token mode (SUPERVISOR_TOKEN env var, HA add-on deployment) and
token mode (ha_url/ha_token read from config.json in the persistent data
dir, Docker deployment). The registry-fetching methods below are new —
v1 fetched entities only; DEVICE_PAYLOAD_SPEC.md Stage 1 needs the device
registry too, to group entities by their physical device.
"""

import asyncio
import json
import os
import urllib.request
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


def is_configured() -> bool:
    """
    True once there's SOMETHING to connect with -- supervisor mode, or both
    ha_url/ha_token present in config.json. Deliberately not a live check
    (that's check_connection()) -- this only gates the settings-page
    first-run redirect (pages.py), which cares about "has anyone entered
    credentials yet", not "are they currently correct/reachable".
    """
    if os.environ.get("SUPERVISOR_TOKEN"):
        return True
    config = _load_config()
    return bool(config.get("ha_url")) and bool(config.get("ha_token"))


def get_config_for_display() -> dict:
    """ha_url plus whether a token is already set -- never the token itself
    (shim/routes/pages.py's settings form uses this to avoid re-rendering
    the secret on every page load)."""
    config = _load_config()
    return {
        "ha_url": config.get("ha_url", ""),
        "has_token": bool(config.get("ha_token")),
        # write transport (COMPILER_DECISIONS_DEPLOY §2.5)
        "write_mode": config.get("write_mode", "local"),
        "ha_config_path": config.get("ha_config_path", ""),
        "smb_host": config.get("smb_host", ""),
        "smb_share": config.get("smb_share", "config"),
        "smb_username": config.get("smb_username", ""),
        "has_smb_password": bool(config.get("smb_password")),
    }


def save_config(ha_url: str, ha_token: str | None, **extra) -> None:
    """
    Settings-page save (shim/routes/pages.py). ha_token / smb_password are
    None/empty when the user left the field blank to keep the existing one --
    only overwrite when a real new value was typed. `extra` carries the write
    transport fields (write_mode, ha_config_path, smb_host/share/username/
    password — COMPILER_DECISIONS_DEPLOY §2.5).
    """
    config = _load_config()
    config["ha_url"] = ha_url
    if ha_token:
        config["ha_token"] = ha_token
    for key in ("write_mode", "ha_config_path", "smb_host", "smb_share", "smb_username"):
        if key in extra and extra[key] is not None:
            config[key] = extra[key]
    if extra.get("smb_password"):
        config["smb_password"] = extra["smb_password"]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


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


async def call_service(domain: str, service: str, service_data: dict | None = None) -> dict:
    """Call an HA service over the websocket API (e.g. homeassistant.reload_all
    after the configuration.yaml include-lines edit — COMPILER_DECISIONS_DEPLOY
    §9.2 follow-up; later the deploy flow's automation.reload/script.reload)."""
    msg: dict = {"id": 1, "type": "call_service", "domain": domain, "service": service}
    if service_data:
        msg["service_data"] = service_data
    results = await _ws_call([msg])
    result = results.get(1, {})
    if not result.get("success"):
        raise HAClientError(f"HA rejected {domain}.{service}: {result.get('error')}")
    return result


async def get_states() -> list:
    """Current entity states only — compiler deploy's automation lookup
    (pause/enable via automation.turn_off/turn_on needs the entity_ids HA
    assigned to our emitted automations). Cheaper than fetch_registries'
    six-call snapshot."""
    results = await _ws_call([{"id": 1, "type": "get_states"}])
    result = results[1]
    if not result.get("success"):
        raise HAClientError(f"get_states failed: {result.get('error')}")
    return result["result"]


async def check_config() -> dict:
    """REST POST /api/config/core/check_config — HA validates its entire
    ON-DISK configuration (including a just-written automation file) without
    touching the running system. Returns {"result": "valid"|"invalid",
    "errors": str|None, ...}. The deploy flow gates its reload on this
    (DECISION Jeremy 2026-07-18: collect problems from HA BEFORE going live).
    stdlib urllib in a thread — this is the only REST call in the shim, not
    worth a new HTTP dependency."""
    ha_url, token = _load_auth()
    if not (ha_url and token):
        raise HAClientError("No HA credentials configured.")
    url = ha_url.rstrip("/") + "/api/config/core/check_config"

    def _post():
        req = urllib.request.Request(
            url, method="POST", data=b"",
            headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        return await asyncio.to_thread(_post)
    except Exception as exc:
        raise HAClientError(f"check_config failed: {exc}") from exc


async def get_services() -> dict:
    """HA's registered services (websocket get_services) — deploy verifies a
    freshly loaded PyScript piston by its @service registration appearing."""
    results = await _ws_call([{"id": 1, "type": "get_services"}])
    result = results[1]
    if not result.get("success"):
        raise HAClientError(f"get_services failed: {result.get('error')}")
    return result["result"]


async def get_system_log() -> list:
    """HA's recent warning/error log entries (websocket system_log/list) —
    when a compiled YAML file is rejected on reload, HA says exactly what's
    malformed and where; deploy grabs those lines as debug evidence."""
    results = await _ws_call([{"id": 1, "type": "system_log/list"}])
    result = results[1]
    if not result.get("success"):
        raise HAClientError(f"system_log/list failed: {result.get('error')}")
    return result["result"]


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


async def check_connection() -> tuple[bool, str]:
    """
    Lightweight HA reachability check for the PistonCore front door's
    HA-health badge (CLAUDE.md UI split). Reuses get_config (already used
    elsewhere) rather than a separate ping-style call -- cheapest real round
    trip that proves auth + connectivity both work.
    """
    try:
        await _ws_call([{"id": 1, "type": "get_config"}])
        return True, "Connected"
    except HAClientError as e:
        return False, str(e)


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

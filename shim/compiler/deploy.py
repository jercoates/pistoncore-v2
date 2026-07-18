"""DEPLOY + LIFECYCLE (COMPILER_DECISIONS_DEPLOY §1-§5): compile-on-save,
write through the configured write target, reload HA, record the result.

Rules honored here:
- A failed compile NEVER blocks the save and NEVER touches the previously
  deployed artifact (§1) — it only records the error for the two UI surfaces.
- Paused piston -> its automation file is removed (v1 pause mechanism; the
  spec's initial_state/disable variant can replace this later without moving
  the hook points).
- Rename-safe (§4): the deployed filename is recorded per piston; a rename
  deletes the old file before writing the new one.
- Reload (§5): automation.reload first, homeassistant.reload_all as fallback
  — this doubles as the open dev-HA test for new-file pickup.
"""

import re
import time

from .. import deploy_writer, device_pipeline, ha_client, storage
from . import compile_piston
from .errors import CompilerError

_AUTOMATIONS_DIR = "pistoncore/automations"

_reg_cache: dict = {"t": 0.0, "map": None}


async def _resolution_map() -> dict:
    if _reg_cache["map"] is None or time.time() - _reg_cache["t"] > 60:
        registries = await ha_client.fetch_registries()
        payload = device_pipeline.build_device_payload(registries)
        _reg_cache["map"] = payload["resolution_map"]
        _reg_cache["t"] = time.time()
    return _reg_cache["map"]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40] or "piston"


def _record(entry: dict, **fields) -> None:
    entry["meta"]["compile"] = {"ts": int(time.time() * 1000), **fields}
    storage._save_piston_file(entry)


async def _reload_ha() -> str:
    try:
        await ha_client.call_service("automation", "reload")
        return "automation.reload"
    except Exception:
        try:
            await ha_client.call_service("homeassistant", "reload_all")
            return "reload_all (automation.reload failed)"
        except Exception as exc:
            return f"reload FAILED: {exc}"


async def compile_and_deploy(piston_id: str) -> dict:
    """Runs after every successful save / pause / resume / import. Never
    raises — every outcome lands in meta.compile for the UI surfaces."""
    entry = storage.load_piston(piston_id)
    if entry is None:
        return {"status": "missing"}
    name = entry["name"]
    prev = (entry["meta"].get("compile") or {})
    filename = f"{_AUTOMATIONS_DIR}/{_slug(name)}_{piston_id[:8]}.yaml"

    def _remove_deployed(writer, why: str):
        for f in {prev.get("file"), filename} - {None}:
            try:
                writer.delete(f)
            except Exception:
                pass
        return why

    try:
        writer = deploy_writer.get_writer()
    except deploy_writer.WriteTargetError as exc:
        _record(entry, status="error", message=f"write target: {exc}")
        return entry["meta"]["compile"]

    # Paused -> not deployed (v1 pause mechanism)
    if not entry["meta"].get("active", True):
        _remove_deployed(writer, "paused")
        reload_note = await _reload_ha()
        _record(entry, status="paused", message="paused — not deployed", reload=reload_note)
        return entry["meta"]["compile"]

    try:
        resolution_map = await _resolution_map()
        result = compile_piston(entry["piston"], piston_id, name, resolution_map,
                                storage.load_globals())
    except CompilerError as exc:
        _record(entry, status="error", **exc.record())
        return entry["meta"]["compile"]
    except Exception as exc:
        _record(entry, status="error", message=f"internal compiler error: {exc}")
        return entry["meta"]["compile"]

    if result["target"] == "pyscript":
        _remove_deployed(writer, "pyscript")
        _record(entry, status="pyscript",
                message="requires PyScript — that band isn't built yet: " +
                        "; ".join(result["reasons"][:3]))
        return entry["meta"]["compile"]

    try:
        if prev.get("file") and prev["file"] != filename:
            writer.delete(prev["file"])
        writer.write(filename, result["yaml"])
    except Exception as exc:
        _record(entry, status="error", message=f"deploy write failed: {exc}")
        return entry["meta"]["compile"]

    reload_note = await _reload_ha()
    _record(entry, status="deployed", file=filename, reload=reload_note)
    return entry["meta"]["compile"]

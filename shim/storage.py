"""Persistence: piston JSON files, global variables, and the save-flow wire
encoding (SHIM_API_SPEC.md §4.7, §4.10).

Storage layout (PISTONCORE_DATA_DIR, same env var convention as
shim/ha_client.py's config.json):
  <data_dir>/pistons/<id>.json
  <data_dir>/globals.json

Encode/decode pipeline verified against source (app.js):
  piston save:    utoa(encodeEmoji(angular.toJson(piston)))  — base64(emoji-encoded JSON)
  variable save:  utoa(angular.toJson(value))                — base64(JSON), no emoji step
utoa is the classic UTF-8-safe base64 trick (btoa(unescape(encodeURIComponent(str))));
its exact reverse is base64-decode-to-bytes -> utf-8-decode, no intermediate trick needed
in Python. encodeEmoji replaces astral-plane characters with ":%XX%XX%XX%XX:" sequences
(percent-encoded UTF-8 bytes); decode_emoji reverses that with urllib.parse.unquote.
"""

import json
import os
import re
import time
import urllib.parse
import uuid
from pathlib import Path

DATA_DIR = Path(os.environ.get("PISTONCORE_DATA_DIR", "/pistoncore-userdata"))
PISTONS_DIR = DATA_DIR / "pistons"
GLOBALS_FILE = DATA_DIR / "globals.json"

_EMOJI_RE = re.compile(r":(%[0-9A-Fa-f]{2}%[0-9A-Fa-f]{2}%[0-9A-Fa-f]{2}%[0-9A-Fa-f]{2}):")


def _ensure_dirs():
    PISTONS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Wire encoding (piston save chunks + variable values)
# ---------------------------------------------------------------------------

def decode_emoji(value: str) -> str:
    return _EMOJI_RE.sub(lambda m: urllib.parse.unquote(m.group(1)), value)


def decode_base64_json(data: str) -> dict:
    """utoa(angular.toJson(value)) reversed — variable/set values (no emoji step)."""
    import base64
    raw = base64.b64decode(data).decode("utf-8")
    return json.loads(raw)


def decode_piston_data(data: str) -> dict:
    """utoa(encodeEmoji(angular.toJson(piston))) reversed — piston/set(.end) payloads."""
    import base64
    raw = base64.b64decode(data).decode("utf-8")
    return json.loads(decode_emoji(raw))


# ---------------------------------------------------------------------------
# Global-reference scanner (COMPILER_DECISIONS_HOLDING.md §H4)
# ---------------------------------------------------------------------------

def find_global_references(piston: dict) -> set[str]:
    """
    Walk a piston JSON tree for operand nodes {"t": "x", "x": <name-or-list>}
    and collect every referenced name that starts with "@" (a global — stock
    webCoRE's own prefix convention, VERIFIED piston.module.js:2278; local/
    system-var references don't start with "@" and are not globals).
    Generic tree walk rather than enumerating every named field (lo/ro/ro2/
    to/to2/wd/p/x/...) per PISTON_JSON_REFERENCE.md §4 — operands can appear
    in many places and are always shaped {"t": ..., ...}, so this is more
    robust than hardcoding each field name.
    """
    found: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            if node.get("t") == "x":
                x = node.get("x")
                names = x if isinstance(x, list) else [x] if x else []
                for name in names:
                    if isinstance(name, str) and name.startswith("@"):
                        found.add(name)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(piston)
    return found


# ---------------------------------------------------------------------------
# Pistons
# ---------------------------------------------------------------------------

def _piston_path(piston_id: str) -> Path:
    return PISTONS_DIR / f"{piston_id}.json"


def load_piston(piston_id: str) -> dict | None:
    path = _piston_path(piston_id)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def meta_for_get(entry: dict) -> dict:
    """
    Long-key meta shape — VERIFIED-HE-GROOVY webcore-piston.groovy:1148-1166
    (piston.get()). What intf/dashboard/piston/get and piston/set(.end) return
    (SHIM_API_SPEC.md §4.5/§5.2) — piston.module.js:599-606's save-success gate
    reads response.data.{active,modified,build} from exactly this shape.
    """
    m = entry["meta"]
    return {
        "id": entry["id"],
        "author": m["author"],
        "name": entry["name"],
        "created": m["created"],
        "modified": m["modified"],
        "build": m["build"],
        "bin": m["bin"],
        "active": m["active"],
        "category": m["category"],
    }


def meta_for_list(entry: dict) -> dict:
    """
    Short-key meta shape — VERIFIED-HE-GROOVY webcore.groovy:1718-1740
    (gtMeta()/pitem(), same shape curPState() returns). What
    instance.pistons[].meta serves (SHIM_API_SPEC.md §5.2) —
    dashboard.module.js's piston.meta.a active/paused-bucket filtering reads
    this shape, not meta_for_get's. lastExecuted/nextSchedule/state have no
    real value yet (no execution engine) — 0/{} accurately means "never run",
    not a placeholder guess.
    """
    m = entry["meta"]
    return {
        "a": m["active"],
        "c": m["category"],
        "t": 0,
        "m": m["modified"],
        "b": m["bin"],
        "n": 0,
        "z": entry["piston"].get("z", ""),
        "s": {},
        "heCached": False,
    }


def list_pistons() -> list[dict]:
    _ensure_dirs()
    result = []
    for path in PISTONS_DIR.glob("*.json"):
        with open(path, encoding="utf-8") as f:
            entry = json.load(f)
        result.append({"id": entry["id"], "name": entry["name"], "meta": meta_for_list(entry)})
    return result


def create_piston(name: str, author: str) -> dict:
    _ensure_dirs()
    piston_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)
    entry = {
        "id": piston_id,
        "name": name or "New Piston",
        "piston": {"o": {"cto": 0, "ced": 0}, "r": [], "s": [], "v": [], "z": ""},
        "meta": {
            "author": author,
            "created": now_ms,
            "modified": now_ms,
            # 0 = "never explicitly saved" (piston.module.js:291-292 gates
            # the fresh-piston designer setup on meta.build == 0)
            "build": 0,
            "bin": "",
            "active": True,
            "category": "0",
        },
    }
    _save_piston_file(entry)
    return entry


def save_piston(piston_id: str, piston_json: dict) -> dict:
    """Reassembled, decoded piston JSON from the save flow. Stored verbatim
    (the piston JSON as webCoRE emits it is law — CLAUDE.md) except for the
    meta bookkeeping fields this function owns."""
    _ensure_dirs()
    existing = load_piston(piston_id)
    now_ms = int(time.time() * 1000)
    meta = dict(existing["meta"]) if existing else {
        "author": "", "created": now_ms, "bin": "", "active": True, "category": "0",
    }
    meta["modified"] = now_ms
    meta["build"] = meta.get("build", 0) + 1

    name = piston_json.get("n") or (existing["name"] if existing else "New Piston")

    entry = {
        "id": piston_id,
        "name": name,
        "piston": piston_json,
        "meta": meta,
    }
    _save_piston_file(entry)
    update_used_by(piston_id, name, find_global_references(piston_json))
    return entry


def _save_piston_file(entry: dict):
    _ensure_dirs()
    with open(_piston_path(entry["id"]), "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2)


# ---------------------------------------------------------------------------
# Global variables (SHIM_API_SPEC.md §4.10, §5.2; COMPILER_DECISIONS_HOLDING §H4)
# ---------------------------------------------------------------------------

def load_globals() -> dict:
    """{"@Name": {"t": ..., "v": ..., "used_by": [{"id":, "name":}, ...]}}"""
    if not GLOBALS_FILE.exists():
        return {}
    with open(GLOBALS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_globals(globals_store: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(GLOBALS_FILE, "w", encoding="utf-8") as f:
        json.dump(globals_store, f, indent=2)


def globals_for_wire() -> dict:
    """instance.globalVars shape — {t, v} only, used_by is shim-internal
    bookkeeping and never sent to the dashboard (same pattern as the device
    resolution map, DEVICE_PAYLOAD_SPEC.md Stage 8)."""
    return {name: {"t": g["t"], "v": g["v"]} for name, g in load_globals().items()}


def set_global_variable(name: str, value: dict | None) -> dict:
    """
    VERIFIED against webcore_source_reference.groovy:1495-1528
    (api_intf_variable_set). value is the decoded {"t":, "v":, "n"?:} payload
    or None (delete). name/value["n"] already include "@" (dashboard's own
    convention, piston.module.js:2278). value["n"], if present and different
    from name, renames: written under the new key, old key removed. Returns
    the full updated globals map (wire shape, {t,v} only) — the real backend
    returns the whole map in the response, not just the changed variable.
    """
    globals_store = load_globals()
    if not value:
        globals_store.pop(name, None)
    else:
        target_name = value.get("n") or name
        if target_name != name:
            globals_store.pop(name, None)
        existing = globals_store.get(target_name, {})
        globals_store[target_name] = {
            "t": value["t"], "v": value["v"], "used_by": existing.get("used_by", []),
        }
    save_globals(globals_store)
    return {name: {"t": g["t"], "v": g["v"]} for name, g in globals_store.items()}


def update_used_by(piston_id: str, piston_name: str, referenced_globals: set[str]):
    """COMPILER_DECISIONS_HOLDING.md §H4 — event-driven at save time, no
    background scan. Adds this piston to used_by on every global it
    references now, removes it from every global it no longer references."""
    globals_store = load_globals()
    changed = False
    for name, g in globals_store.items():
        used_by = g.setdefault("used_by", [])
        currently_listed = any(u["id"] == piston_id for u in used_by)
        should_be_listed = name in referenced_globals
        if should_be_listed and not currently_listed:
            used_by.append({"id": piston_id, "name": piston_name})
            changed = True
        elif not should_be_listed and currently_listed:
            g["used_by"] = [u for u in used_by if u["id"] != piston_id]
            changed = True
    if changed:
        save_globals(globals_store)

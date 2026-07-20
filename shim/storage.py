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
SETTINGS_FILE = DATA_DIR / "settings.json"

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

_GLOBAL_REF_RE = re.compile(r"@@?[A-Za-z0-9_]+")


def find_global_references(piston: dict) -> set[str]:
    """
    Walk the entire piston JSON tree and regex-scan every string value for
    @Name / @@SuperGlobal tokens (stock webCoRE's own prefix convention,
    VERIFIED piston.module.js:2278). A real capture (2026-07-12) showed the
    original "{t:'x', x:...} operands only" approach missing a genuinely
    common case: a device-type global used as a with-block's target is a
    bare "@Announce" string sitting directly in the statement's "d" list, no
    operand wrapper at all -- action.d = ["@Announce"]. Globals can also
    appear embedded inside expression source strings ("e"/"str" fields,
    e.g. "...@Name..." as part of a larger sentence, not the whole value)
    and inside local variables' own v.d arrays (a local device variable
    initialized from a global). A single regex pass over every string in the
    tree catches all of these uniformly, including the bare-string case (a
    bare "@Announce" string is just a whole-string match of the same
    pattern) -- no need to special-case where in the structure it appears.
    Also matches "@@" superglobals, tracked the same way.
    """
    found: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, str):
            found.update(_GLOBAL_REF_RE.findall(node))

    walk(piston)
    return found


# ---------------------------------------------------------------------------
# Node ID assignment (PISTON_JSON_REFERENCE.md §8, VERIFIED-HE-GROOVY
# webcore-piston.groovy:1412-1475 msetIds()) — the engine, not the editor,
# assigns "$" ids, so the shim must do it on save. A node keeps its existing
# "$" id if it has one AND that id hasn't already been claimed elsewhere in
# the tree; otherwise (missing OR a duplicate of one already seen) it's
# queued and gets max(seen)+1, incrementing per node, in traversal order.
# Only statement/condition/restriction/group/task nodes get ids — operands
# never do, so this walks the tree's known shape (PISTON_JSON_REFERENCE.md
# §2-§7) rather than tagging every dict with a "t" field.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_comparison_buckets: dict | None = None


def _get_comparison_buckets() -> dict:
    """{co_name: 't'|'c'} from webcore_vocab.json's comparisons buckets."""
    global _comparison_buckets
    if _comparison_buckets is None:
        with open(_REPO_ROOT / "webcore_vocab.json", encoding="utf-8") as f:
            comp = json.load(f)["comparisons"]
        _comparison_buckets = {}
        for name in comp.get("conditions", {}):
            _comparison_buckets[name] = "c"
        for name in comp.get("triggers", {}):
            _comparison_buckets[name] = "t"  # triggers win on any overlap
    return _comparison_buckets


def classify_conditions(piston: dict) -> int:
    """Stamp ct/s onto condition nodes the way the ENGINE does at save —
    PistonCore has no engine, so the shim replicates webcore-piston.groovy's
    subscribeAll() classification (rule VERIFIED at :9296, COMPILER_SPEC §2.5
    point 2): ct from the vocab comparison bucket; then
      s = sm != "never" and (ct == "t" or sm == "always" or not hasTriggers)
    (the no-triggers case promotes EVERY condition to subscribe — the engine's
    own "no triggers, promoting conditions" rule, :9242). Editor deletes sm
    when "auto", so absent sm == auto. Restriction nodes (r arrays) never
    subscribe (behavior map §4) — only statement condition trees are walked.
    Returns the subscribed-event count for piston/get's subscriptions meta.
    These are webCoRE's OWN engine-written fields, not custom additions —
    stamping them is impersonating the engine, which is the shim's job."""
    buckets = _get_comparison_buckets()
    nodes: list[dict] = []

    def walk(obj, in_conditions: bool):
        if isinstance(obj, dict):
            if obj.get("t") == "condition" and "co" in obj:
                nodes.append(obj)
            for key, val in obj.items():
                if key == "r":
                    continue  # restrictions never subscribe
                walk(val, in_conditions or key == "c")
        elif isinstance(obj, list):
            for item in obj:
                walk(item, in_conditions)

    walk(piston.get("s", []), False)

    has_triggers = False
    for node in nodes:
        ct = buckets.get(node.get("co"))
        if ct:
            node["ct"] = ct
            if ct == "t":
                has_triggers = True

    events = 0
    for node in nodes:
        sm = node.get("sm", "auto")
        ct = node.get("ct")
        subscribed = sm != "never" and (ct == "t" or sm == "always" or not has_triggers)
        node["s"] = subscribed
        if subscribed:
            events += 1
    return events


def assign_node_ids(piston: dict) -> None:
    seen_ids: set[int] = set()
    to_assign: list[dict] = []

    def claim(node: dict):
        existing = node.get("$")
        if isinstance(existing, int) and existing not in seen_ids:
            seen_ids.add(existing)
        else:
            to_assign.append(node)

    def visit_task(task: dict):
        claim(task)

    def visit_condition(cond: dict):
        claim(cond)
        if cond.get("t") == "group":
            for child in cond.get("c", []):
                visit_condition(child)
        else:
            for task in cond.get("ts", []):
                visit_task(task)
            for task in cond.get("fs", []):
                visit_task(task)

    def visit_restriction(restr: dict):
        claim(restr)
        if restr.get("t") == "group":
            for child in restr.get("r", []):
                visit_restriction(child)

    def visit_statement(stmt: dict):
        claim(stmt)
        for restr in stmt.get("r", []):
            visit_restriction(restr)
        for cond in stmt.get("c", []):
            visit_condition(cond)
        for task in stmt.get("k", []):
            visit_task(task)
        for child in stmt.get("s", []):
            visit_statement(child)
        for child in stmt.get("e", []):
            visit_statement(child)
        for ei in stmt.get("ei", []):
            claim(ei)
            for cond in ei.get("c", []):
                visit_condition(cond)
            for child in ei.get("s", []):
                visit_statement(child)
        for case in stmt.get("cs", []):
            claim(case)
            for child in case.get("s", []):
                visit_statement(child)

    for restr in piston.get("r", []):
        visit_restriction(restr)
    for stmt in piston.get("s", []):
        visit_statement(stmt)

    next_id = (max(seen_ids) if seen_ids else 0) + 1
    for node in to_assign:
        node["$"] = next_id
        next_id += 1


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


def set_piston_active(piston_id: str, active: bool) -> dict | None:
    """piston/pause and piston/resume (SHIM_API_SPEC.md §4.6) -- only the
    active flag changes, no other meta bookkeeping (unlike save_piston,
    this isn't a content edit, so build/modified stay untouched)."""
    entry = load_piston(piston_id)
    if entry is None:
        return None
    entry["meta"]["active"] = active
    _save_piston_file(entry)
    return entry


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

    assign_node_ids(piston_json)
    classify_conditions(piston_json)  # engine-equivalent ct/s stamping (see docstring)

    entry = {
        "id": piston_id,
        "name": name,
        "piston": piston_json,
        "meta": meta,
    }
    _save_piston_file(entry)
    update_used_by(piston_id, name, find_global_references(piston_json))
    return entry


def count_subscriptions(piston: dict) -> int:
    """Subscribed-event count for piston/get's subscriptions meta — counts the
    s:true condition nodes stamped by classify_conditions() (older pistons
    saved before stamping existed just count 0 until re-saved)."""
    events = 0

    def walk(obj):
        nonlocal events
        if isinstance(obj, dict):
            if obj.get("t") == "condition" and obj.get("s") is True:
                events += 1
            for key, val in obj.items():
                if key != "r":
                    walk(val)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(piston.get("s", []))
    return events


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


# ---------------------------------------------------------------------------
# PistonCore settings (SHIM_API_SPEC.md §5.3) — no Settings UI yet
# (memory: PistonCore needs a real settings page, incl. HA creds); until
# then this file is hand-edited like data/config.json was before it existed.
# ---------------------------------------------------------------------------

def load_settings() -> dict:
    if not SETTINGS_FILE.exists():
        return {}
    with open(SETTINGS_FILE, encoding="utf-8") as f:
        return json.load(f)


def compile_band(piston_id: str) -> str:
    """The user's compile-target preference for one piston: "auto" (default),
    "pyscript" (force, for when the YAML translation misbehaves) or "yaml".
    Falls back to the instance-wide default. Stored in PistonCore settings —
    NEVER in the piston JSON (read-only-compiler rule)."""
    s = load_settings()
    per = (s.get("piston_band") or {}).get(piston_id)
    if per in ("auto", "yaml", "pyscript"):
        return per
    return s.get("default_band", "auto")


def set_compile_band(piston_id: str, band: str):
    s = load_settings()
    per = s.setdefault("piston_band", {})
    if band == "auto":
        per.pop(piston_id, None)
    else:
        per[piston_id] = band
    save_settings(s)


def save_settings(settings: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)

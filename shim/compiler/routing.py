"""ROUTE — routing_table.json signatures force the PyScript band (§3.2).
YAML/classic is the default; returns the list of reasons if PyScript is
required (empty list = native)."""

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_table: dict | None = None


def _load() -> dict:
    global _table
    if _table is None:
        with open(_REPO_ROOT / "routing_table.json", encoding="utf-8") as f:
            _table = json.load(f)
    return _table


def pyscript_reasons(piston: dict) -> list[str]:
    t = _load()
    reasons: list[str] = []

    def walk(node, stmt_id):
        if isinstance(node, dict):
            sid = node.get("$", stmt_id)
            nt = node.get("t")
            if nt in t["statement_types"]:
                reasons.append(f"statement ${sid}: '{nt}' statement requires PyScript")
            if nt == "switch" and node.get("ctp") in t["switch_ctp_values"]:
                reasons.append(f"statement ${sid}: switch fall-through requires PyScript")
            if isinstance(node.get("c"), str) and node["c"] in t["task_commands"]:
                reasons.append(f"task ${sid}: command '{node['c']}' requires PyScript")
            if node.get("o") in t["group_operators"]:
                reasons.append(f"node ${sid}: '{node['o']}' group requires PyScript")
            for field in t["condition_fields_present"]:
                if field in node:
                    reasons.append(f"node ${sid}: followed-by window ('{field}') requires PyScript")
            for field, vals in t["statement_fields_nondefault"].items():
                if node.get(field) in vals:
                    reasons.append(f"statement ${sid}: {field}='{node[field]}' requires PyScript")
            for v in node.values():
                walk(v, sid)
        elif isinstance(node, list):
            for i in node:
                walk(i, stmt_id)

    walk(piston.get("s", []), None)
    return reasons

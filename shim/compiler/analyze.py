"""ANALYZE — piston tree -> per-branch intent IR (COMPILER_SPEC §3.0/§2.5).

Trigger identification: node ct/s when present (engine- or shim-stamped),
else derived from the comparisons vocab buckets (§2 input contract)."""

import json
from pathlib import Path

from .errors import NotYetImplemented

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_buckets: dict | None = None


def _comparison_buckets() -> dict:
    global _buckets
    if _buckets is None:
        with open(_REPO_ROOT / "webcore_vocab.json", encoding="utf-8") as f:
            comp = json.load(f)["comparisons"]
        _buckets = {}
        for name in comp.get("conditions", {}):
            _buckets[name] = "c"
        for name in comp.get("triggers", {}):
            _buckets[name] = "t"
    return _buckets


def _classify(cond: dict) -> str:
    ct = cond.get("ct")
    if ct in ("t", "c"):
        return ct
    return _comparison_buckets().get(cond.get("co"), "c")


def analyze(piston: dict, piston_id: str, piston_name: str) -> list[dict]:
    """Returns a list of branch IRs, one per top-level statement."""
    branches = []
    for stmt in piston.get("s", []):
        sid = stmt.get("$")
        kwargs = {"piston_id": piston_id, "piston_name": piston_name, "stmt_id": sid}
        if stmt.get("t") != "if":
            raise NotYetImplemented(
                f"top-level statement type '{stmt.get('t')}' (statement ${sid}) "
                f"is not compiled yet — session-1 scope is if-branches", **kwargs)
        if stmt.get("o", "and") != "and":
            raise NotYetImplemented(
                f"condition operator '{stmt.get('o')}' (statement ${sid}) not compiled yet", **kwargs)
        if stmt.get("ei"):
            raise NotYetImplemented(f"else-if chains (statement ${sid}) not compiled yet", **kwargs)

        triggers, conditions = [], []
        for cond in stmt.get("c", []):
            if cond.get("t") != "condition":
                raise NotYetImplemented(
                    f"condition node type '{cond.get('t')}' (statement ${sid}) not compiled yet", **kwargs)
            node = {
                "co": cond.get("co"),
                "attr": (cond.get("lo") or {}).get("a"),
                "devices": (cond.get("lo") or {}).get("d", []),
                "aggregation": (cond.get("lo") or {}).get("g", "any"),
                "value": (cond.get("ro") or {}).get("c"),
            }
            (triggers if _classify(cond) == "t" else conditions).append(node)

        def _actions(stmts: list, where: str) -> list:
            out = []
            for a in stmts:
                if a.get("t") != "action":
                    raise NotYetImplemented(
                        f"nested statement type '{a.get('t')}' in {where} of ${sid} not compiled yet", **kwargs)
                for task in a.get("k", []):
                    out.append({"command": task.get("c"),
                                "params": task.get("p", []),
                                "devices": a.get("d", [])})
            return out

        branches.append({
            "stmt_id": sid,
            "tcp": stmt.get("tcp", "c") or "c",
            "triggers": triggers,
            "conditions": conditions,
            "then": _actions(stmt.get("s", []), "then"),
            "else": _actions(stmt.get("e", []), "else"),
        })
    return branches

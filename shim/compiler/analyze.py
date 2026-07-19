"""ANALYZE — piston tree -> per-branch intent IR (COMPILER_SPEC §3.0/§2.5).

Trigger identification: node ct/s when present (engine- or shim-stamped),
else derived from the comparisons vocab buckets (§2 input contract).

Session-3 scope: top-level `if` (with else / else-if chains / nested ifs as
an action TREE) and top-level `every` timer statements. Anything else raises
NotYetImplemented — which the emit layer converts into PyScript routing, so
"not compiled yet" means "runs via PyScript", never "dropped".
"""

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


def _cond_node(cond: dict, kwargs: dict) -> dict:
    if cond.get("t") != "condition":
        raise NotYetImplemented(
            f"condition node type '{cond.get('t')}' not compiled yet", **kwargs)
    lo = cond.get("lo") or {}
    ro = cond.get("ro") or {}
    ro2 = cond.get("ro2") or {}
    return {
        "co": cond.get("co"),
        "attr": lo.get("a"),
        "devices": lo.get("d", []),
        "aggregation": lo.get("g", "any"),
        "lo_type": lo.get("t"),       # 'p' physical device, 'v' variable, ...
        "lo_var": lo.get("v"),        # variable name when lo_type == 'v'
        "value": ro.get("c"),
        "value_vt": ro.get("vt"),
        "value2": ro2.get("c"),       # second operand (is_between)
        "value2_vt": ro2.get("vt"),
        "ct": _classify(cond),
    }


def _action_tree(stmts: list, where: str, kwargs: dict) -> list:
    """Nested statements -> action-node tree. Nodes: task | if."""
    out = []
    for a in stmts:
        at = a.get("t")
        if at == "action":
            for task in a.get("k", []):
                out.append({"kind": "task", "command": task.get("c"),
                            "params": task.get("p", []), "devices": a.get("d", [])})
        elif at == "if":
            if a.get("o", "and") != "and":
                raise NotYetImplemented(
                    f"condition operator '{a.get('o')}' (nested statement "
                    f"${a.get('$')}) not compiled yet", **kwargs)
            conds = [_cond_node(c, kwargs) for c in a.get("c", [])]
            for c in conds:
                if c["ct"] == "t":
                    raise NotYetImplemented(
                        f"trigger comparison '{c['co']}' nested inside another "
                        f"statement (${a.get('$')}) requires PyScript", **kwargs)
            out.append({"kind": "if", "conditions": conds,
                        "then": _action_tree(a.get("s", []), where, kwargs),
                        "else": _fold_ei(a, where, kwargs)})
        else:
            raise NotYetImplemented(
                f"nested statement type '{at}' in {where} not compiled yet", **kwargs)
    return out


def _fold_ei(stmt: dict, where: str, kwargs: dict) -> list:
    """else-if chains fold into nested if-nodes seated in the else slot —
    exactly the webCoRE evaluation order (first matching branch wins)."""
    els = _action_tree(stmt.get("e", []), where, kwargs)
    for ei in reversed(stmt.get("ei") or []):
        conds = [_cond_node(c, kwargs) for c in ei.get("c", [])]
        for c in conds:
            if c["ct"] == "t":
                raise NotYetImplemented(
                    f"trigger comparison '{c['co']}' in an else-if chain "
                    f"requires PyScript", **kwargs)
        els = [{"kind": "if", "conditions": conds,
                "then": _action_tree(ei.get("s", []), where, kwargs),
                "else": els}]
    return els


def _if_branch(stmt: dict, sid, kwargs: dict) -> dict:
    if stmt.get("o", "and") != "and":
        raise NotYetImplemented(
            f"condition operator '{stmt.get('o')}' (statement ${sid}) not compiled yet", **kwargs)
    triggers, conditions = [], []
    for cond in stmt.get("c", []):
        node = _cond_node(cond, kwargs)
        (triggers if node["ct"] == "t" else conditions).append(node)
    return {
        "stmt_id": sid,
        "kind": "if",
        "tcp": stmt.get("tcp", "c") or "c",
        "triggers": triggers,
        "conditions": conditions,
        "then": _action_tree(stmt.get("s", []), f"then of ${sid}", kwargs),
        "else": _fold_ei(stmt, f"else of ${sid}", kwargs),
    }


def _every_branch(stmt: dict, sid, kwargs: dict) -> dict:
    """`every` timer statement (VERIFIED webcore-piston.groovy scheduleTimer
    :4770 — lo = interval + unit (om = minute offset for hourly), lo2 = the
    at-time for day+ units; time constants are minutes since midnight per
    PISTON_JSON_REFERENCE §operands)."""
    lo = stmt.get("lo") or {}
    interval, unit = lo.get("c"), lo.get("vt")
    if not isinstance(interval, int) or interval <= 0:
        raise NotYetImplemented(
            f"'every' with non-constant interval (statement ${sid}) requires PyScript", **kwargs)

    timer: dict
    if unit == "s" and 1 <= interval <= 59:
        timer = {"kind": "time_pattern", "seconds": f"/{interval}"}
    elif unit == "m" and 1 <= interval <= 59:
        timer = {"kind": "time_pattern", "minutes": f"/{interval}"}
    elif unit == "h" and 1 <= interval <= 23:
        om = lo.get("om") or 0
        timer = {"kind": "time_pattern", "hours": f"/{interval}",
                 "minutes": str(int(om) if isinstance(om, (int, float)) else 0)}
    elif unit == "d" and interval == 1:
        lo2 = stmt.get("lo2") or {}
        at = lo2.get("c")
        if lo2.get("vt") != "time" or not isinstance(at, (int, float)):
            raise NotYetImplemented(
                f"'every day at' with a non-fixed time (sunrise/sunset/variable) "
                f"(statement ${sid}) requires PyScript", **kwargs)
        at = int(at)
        timer = {"kind": "time", "at": f"{at // 60:02d}:{at % 60:02d}:00"}
    else:
        raise NotYetImplemented(
            f"'every {interval}{unit}' (statement ${sid}) has no native HA trigger "
            f"— requires PyScript", **kwargs)

    return {
        "stmt_id": sid,
        "kind": "timer",
        "tcp": stmt.get("tcp", "c") or "c",
        "timer": timer,
        "triggers": [],
        "conditions": [],
        "then": _action_tree(stmt.get("s", []), f"every ${sid}", kwargs),
        "else": [],
    }


def analyze(piston: dict, piston_id: str, piston_name: str) -> list[dict]:
    """Returns a list of branch IRs, one per top-level statement."""
    branches = []
    for stmt in piston.get("s", []):
        sid = stmt.get("$")
        kwargs = {"piston_id": piston_id, "piston_name": piston_name, "stmt_id": sid}
        t = stmt.get("t")
        if t == "if":
            branches.append(_if_branch(stmt, sid, kwargs))
        elif t == "every":
            branches.append(_every_branch(stmt, sid, kwargs))
        else:
            raise NotYetImplemented(
                f"top-level statement type '{t}' (statement ${sid}) not compiled yet", **kwargs)
    return branches

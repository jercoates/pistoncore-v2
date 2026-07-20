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
    if cond.get("t") == "group":
        # nested condition group with its own and/or operator
        return {"co": "_group", "group_op": cond.get("o", "and"),
                "children": [_cond_node(c, kwargs) for c in cond.get("c", [])],
                "ct": "c", "devices": [], "attr": None, "lo_type": "group",
                "value": None, "value2": None, "duration": {},
                "aggregation": "any", "lo_var": None,
                "value_vt": None, "value2_vt": None,
                "value_preset": None, "value2_preset": None}
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
        "duration": cond.get("to") or {},   # stays/remains/was hold time
        "value_preset": ro.get("s"),        # preset operand: sunrise/sunset/...
        "value2_preset": ro2.get("s"),
        "value_expr": ro.get("x"),          # bare expression operand ($sunrise)
        "value2_expr": ro2.get("x"),
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
            conds = [_cond_node(c, kwargs) for c in a.get("c", [])]
            if a.get("o", "and") == "or" and len(conds) > 1:
                conds = [{"co": "_group", "group_op": "or", "children": conds,
                          "ct": "c", "devices": [], "attr": None,
                          "lo_type": "group", "value": None, "value2": None,
                          "duration": {}, "aggregation": "any", "lo_var": None,
                          "value_vt": None, "value2_vt": None,
                          "value_preset": None, "value2_preset": None,
                          "value_expr": None, "value2_expr": None}]
            elif a.get("o", "and") not in ("and", "or"):
                raise NotYetImplemented(
                    f"condition operator '{a.get('o')}' (nested statement "
                    f"${a.get('$')}) not compiled yet", **kwargs)
            # A trigger comparison nested inside an if evaluates as a
            # CONDITION (current state) on both bands — webCoRE judges it
            # against the waking event, which HA has no equivalent for inside
            # a nested condition. Tier-3 approximation, not a reason to route
            # the whole piston to PyScript.
            out.append({"kind": "if", "conditions": conds,
                        "then": _action_tree(a.get("s", []), where, kwargs),
                        "else": _fold_ei(a, where, kwargs)})
        elif at == "switch":
            lo = a.get("lo") or {}
            cases = []
            default = []
            for cs in a.get("cs", []):
                body = _action_tree(cs.get("s", []), where, kwargs)
                if cs.get("t") == "d":
                    default = body
                else:
                    cases.append({"ro": cs.get("ro") or {}, "body": body})
            if a.get("ctp") in ("f", "e"):
                raise NotYetImplemented(
                    "switch with fall-through has no HA equivalent "
                    "(choose always exits after the first match)", **kwargs)
            out.append({"kind": "switch", "lo": lo, "cases": cases,
                        "default": default})
        elif at in ("repeat", "while"):
            body = _action_tree(a.get("s", []), where, kwargs)
            conds = [_cond_node(c, kwargs) for c in a.get("c", [])]
            count = (a.get("lo") or {}).get("c")
            out.append({"kind": "loop", "conditions": conds, "body": body,
                        "count": count if isinstance(count, int) else None,
                        "until": at == "repeat" and bool(conds)})
        elif at == "for":
            lo, lo2, lo3 = (a.get(k) or {} for k in ("lo", "lo2", "lo3"))
            if not all(isinstance(x.get("c"), (int, float)) for x in (lo, lo2)):
                raise NotYetImplemented(
                    "'for' with non-constant bounds not compiled yet", **kwargs)
            step = lo3.get("c") if isinstance(lo3.get("c"), (int, float)) and lo3.get("c") else 1
            span = int(abs(int(lo2["c"]) - int(lo["c"])) / abs(int(step) or 1)) + 1
            out.append({"kind": "loop", "conditions": [], "body": body if False else
                        _action_tree(a.get("s", []), where, kwargs),
                        "count": span, "until": False})
        elif at == "do":
            out.extend(_action_tree(a.get("s", []), where, kwargs))
        elif at == "exit":
            out.append({"kind": "stop"})
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
        els = [{"kind": "if", "conditions": conds,
                "then": _action_tree(ei.get("s", []), where, kwargs),
                "else": els}]
    return els


def _if_branch(stmt: dict, sid, kwargs: dict) -> dict:
    op = stmt.get("o", "and")
    if op not in ("and", "or"):
        raise NotYetImplemented(
            f"condition operator '{op}' (statement ${sid}) not compiled yet", **kwargs)
    triggers, conditions = [], []
    for cond in stmt.get("c", []):
        node = _cond_node(cond, kwargs)
        (triggers if node["ct"] == "t" else conditions).append(node)
    # top-level OR over the non-trigger conditions -> HA's `condition: or`
    # (triggers are already OR'd by HA: any one firing runs the automation)
    if op == "or" and len(conditions) > 1:
        conditions = [{"co": "_group", "group_op": "or", "children": conditions,
                       "ct": "c", "devices": [], "attr": None,
                       "lo_type": "group", "value": None, "value2": None,
                       "duration": {}, "aggregation": "any", "lo_var": None,
                       "value_vt": None, "value2_vt": None,
                       "value_preset": None, "value2_preset": None,
                       "value_expr": None, "value2_expr": None}]
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
        elif t == "action":
            # a bare top-level action: no subscription, just steps to run
            branches.append({
                "stmt_id": sid, "kind": "actions", "tcp": stmt.get("tcp", "c") or "c",
                "triggers": [], "conditions": [],
                "then": _action_tree([stmt], f"statement ${sid}", kwargs),
                "else": [],
            })
        else:
            raise NotYetImplemented(
                f"top-level statement type '{t}' (statement ${sid}) not compiled yet", **kwargs)
    return branches

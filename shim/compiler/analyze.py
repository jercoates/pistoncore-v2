"""ANALYZE — piston tree -> per-branch intent IR (COMPILER_SPEC §3.0/§2.5).

Trigger identification: node ct/s when present (engine- or shim-stamped),
else derived from the comparisons vocab buckets (§2 input contract).

Session-3 scope: top-level `if` (with else / else-if chains / nested ifs as
an action TREE) and top-level `every` timer statements. Anything else raises
NotYetImplemented — which the emit layer converts into PyScript routing, so
"not compiled yet" means "runs via PyScript", never "dropped".
"""

import json

from .errors import NotYetImplemented

_buckets: dict | None = None


def _comparison_buckets() -> dict:
    global _buckets
    if _buckets is None:
        from .. import customize
        with open(customize.path("webcore_vocab.json"), encoding="utf-8") as f:
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
        # nested group with its own and/or operator. A CONDITION group carries
        # its children in `c` with operator `o`; a RESTRICTION group carries
        # them in `r` with operator `rop` (PISTON_JSON_REFERENCE §7) — same
        # anatomy, different key names.
        kids, op = cond.get("c"), cond.get("o", "and")
        if not kids and cond.get("r"):
            kids, op = cond.get("r"), cond.get("rop", "and")
        return {"co": "_group", "group_op": op,
                "children": [_cond_node(c, kwargs) for c in kids or []],
                "ct": "c", "devices": [], "attr": None, "lo_type": "group",
                "value": None, "value2": None, "duration": {},
                "aggregation": "any", "lo_var": None,
                "value_vt": None, "value2_vt": None,
                "value_preset": None, "value2_preset": None,
                "raw": cond,
                **_attached_actions(cond, kwargs)}
    if cond.get("t") == "event":
        # An `on <events> do` entry: a bare subscription with an `lo` and NO
        # comparison at all (VERIFIED piston.module.js:1481-1484 — editEvent
        # seeds {t:'event', lo:{...}} and never sets co/ro).
        #
        # READ, don't refuse (2026-08-06). This used to raise, which meant the
        # analyzer could not read an `on` block at ALL — while the PyScript
        # band compiles them fine. That was survivable only because the
        # analyzer was the YAML band's private reader; the moment PyScript
        # reads through it, refusing here stops those pistons compiling on the
        # only band that can run them, including for a user who FORCED
        # PyScript and so has no routing fallback left.
        lo = cond.get("lo") or {}
        return {"co": None, "attr": lo.get("a"), "devices": lo.get("d", []),
                "aggregation": lo.get("g", "any"), "lo_type": lo.get("t"),
                "lo_var": lo.get("v"), "lo_var_name": lo.get("x"),
                "value": None, "value_vt": None, "value2": None,
                "value2_vt": None, "duration": {}, "value_preset": None,
                "value2_preset": None, "value_expr": None, "value2_expr": None,
                "ct": "t",          # an event block is nothing but a subscription
                "yaml_blocker": f"condition node type '{cond.get('t')}' "
                                f"not compiled yet",
                "raw": cond, **_attached_actions(cond, kwargs)}
    # "restriction" nodes have the SAME comparison anatomy as "condition"
    # (PISTON_JSON_REFERENCE §7) and so reuse this parser verbatim.
    if cond.get("t") not in ("condition", "restriction"):
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
        "lo_var": lo.get("v"),        # virtual-device key when lo_type == 'v'
        # piston VARIABLE name when lo_type == 'x'. Was never carried, so a
        # condition on a variable had nothing to compile from.
        "lo_var_name": lo.get("x"),
        "value": ro.get("c"),
        "value_vt": ro.get("vt"),
        "value2": ro2.get("c"),       # second operand (is_between)
        "value2_vt": ro2.get("vt"),
        "duration": cond.get("to") or {},   # stays/remains/was hold time
        "value_preset": ro.get("s"),        # preset operand: sunrise/sunset/...
        "value2_preset": ro2.get("s"),
        "value_expr": ro.get("x"),          # bare expression operand ($sunrise)
        "value2_expr": ro2.get("x"),
        # "only when physically/programmatically operated" (PISTON_JSON_REFERENCE
        # §4, `p`: "a"|"p"|"s"). Was never carried, so the emitters could not
        # honour it and the filter was silently dropped — a piston asking for a
        # human's touch also fired on its own automated changes.
        "interaction": lo.get("p"),
        "ct": _classify(cond),
        # the untouched node: PyScript transpiles operands straight from this,
        # so consuming this IR costs it no fidelity (Stage 1 of the brief).
        "raw": cond,
        **_attached_actions(cond, kwargs),
    }


def _attached_actions(cond: dict, kwargs: dict) -> dict:
    """Statements hung directly on a condition, run when it tests true (`ts`)
    or false (`fs`) — PISTON_JSON_REFERENCE §3, and SILENTLY DROPPED here until
    2026-08-01: `_cond_node` never read them, so 9 corpus pistons compiled
    clean and lost behaviour. Proof: stripping every ts/fs block produced
    byte-identical output on both bands.

    SEMANTICS (VERIFIED webcore-piston.groovy:7882-7886 for conditions,
    :7474-7478 for groups): whenever the node is evaluated, `ts` runs if the
    result is true, `fs` if false. Not transition-only — the engine computes a
    changed-flag right above and uses it only for task cancellation.

    ORDERING: they run DURING the test, so BEFORE the owning if's own body.

    Note these are STATEMENTS (each with its own task list, and they may nest
    whole ifs), never bare tasks."""
    return {
        "true_actions": _action_tree(cond.get("ts") or [],
                                     f"condition ${cond.get('$')} (true)", kwargs),
        "false_actions": _action_tree(cond.get("fs") or [],
                                      f"condition ${cond.get('$')} (false)", kwargs),
    }


def _restriction_nodes(owner: dict, kwargs: dict) -> list:
    """webCoRE restrictions ("only when ...") — piston root `r` or statement `r`
    (PISTON_JSON_REFERENCE §7). Same comparison anatomy as conditions, so they
    reuse `_cond_node`, but their INTENT is different in two load-bearing ways:

    1. A restriction GATES THE WHOLE STATEMENT, else included. "Only when mode is
       Home: if dark, light on, else light off" must do NOTHING when the mode is
       not Home — it must NOT run the else. So restrictions are kept in their own
       list and emitted at AUTOMATION-condition level, OUTSIDE the if/else action.
       Folding them in with the branch's own conditions would put them inside the
       if (see emit_yaml `_emit_branch`), and a failed restriction would then fire
       the else — precisely backwards.
    2. A restriction NEVER SUBSCRIBES. A piston does not wake because a
       restriction changed; it is a gate checked when something else wakes it.
       Keeping them out of `conditions` also keeps them out of promotion.
    """
    raw = owner.get("r") or []
    if not raw:
        return []
    if owner.get("rn"):
        # "except when ..." — needs a NOT the condition IR has no node for.
        # Fail loudly: silently dropping a restriction is the bug this whole
        # feature exists to prevent.
        raise NotYetImplemented(
            "negated restriction set ('rn') not compiled yet", **kwargs)
    nodes = []
    for node in raw:
        n = _cond_node(node, kwargs)
        n["ct"] = "c"          # a gate, never a subscription
        nodes.append(n)
    if owner.get("rop", "and") == "or" and len(nodes) > 1:
        return [{"co": "_group", "group_op": "or", "children": nodes,
                 "ct": "c", "devices": [], "attr": None, "lo_type": "group",
                 "value": None, "value2": None, "duration": {},
                 "aggregation": "any", "lo_var": None,
                 "value_vt": None, "value2_vt": None,
                 "value_preset": None, "value2_preset": None,
                 "value_expr": None, "value2_expr": None}]
    return nodes


def _action_tree(stmts: list, where: str, kwargs: dict) -> list:
    """Nested statements -> action-node tree. Nodes: task | if.

    EVERY node carries `raw` — the piston dict it was built from — and task
    nodes also carry `raw_stmt`, the owning action statement.

    WHY (2026-08-01, SESSION_BRIEF_ONE_READER_ONE_WRITER §3 Stage 1): the
    PyScript band kept its own walk over the raw piston JSON instead of using
    this IR, because the IR flattens conditions to a summary (`value`,
    `value_vt`) and PyScript needs the full operand trees to transpile
    expressions. Two walkers is the root cause of the whole silent-drop class
    — condition-attached ts/fs were missed because NEITHER walker looked, and
    `$device`-as-a-value works in one and not the other.

    Carrying `raw` lets PyScript walk THIS tree for structure while still
    reading operand detail from the original dict: one reader for discovery
    (which is where every silent drop happened) with no loss of fidelity.
    Detail then migrates out of `raw` into real IR fields one at a time."""
    out = []
    for a in stmts:
        at = a.get("t")
        start = len(out)
        if at == "action":
            for task in a.get("k", []):
                out.append({"kind": "task", "command": task.get("c"),
                            "params": task.get("p", []), "devices": a.get("d", []),
                            # `cm` marks a CUSTOM command — one the editor
                            # offered from the device itself rather than from
                            # webCoRE's dictionary (PISTON_JSON_REFERENCE §5).
                            # Its name is an HA service, so it resolves without
                            # any vocab lookup.
                            "custom": bool(task.get("cm")),
                            "raw": task, "raw_stmt": a})
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
            nested_blocker = None
            if a.get("o", "and") not in ("and", "or"):
                # xor / nand / nor / xnor — webCoRE's full operator set. HA's
                # condition language has only and/or/not, PyScript has all of
                # them (it counts the true conditions), so this is recorded,
                # not raised.
                nested_blocker = (f"condition operator '{a.get('o')}' (nested "
                                  f"statement ${a.get('$')}) not compiled yet")
            # A trigger comparison nested inside an if evaluates as a
            # CONDITION (current state) on both bands — webCoRE judges it
            # against the waking event, which HA has no equivalent for inside
            # a nested condition. Tier-3 approximation, not a reason to route
            # the whole piston to PyScript.
            out.append({"kind": "if", "conditions": conds,
                        "then": _action_tree(a.get("s", []), where, kwargs),
                        "else": _fold_ei(a, where, kwargs), "raw": a,
                        "yaml_blocker": nested_blocker})
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
            out.append({"kind": "switch", "lo": lo, "cases": cases,
                        "default": default, "raw": a,
                        # Recorded rather than raised — HA's `choose` really
                        # cannot fall through, but PyScript can, and it must
                        # still be able to read this statement.
                        "yaml_blocker": (
                            "switch with fall-through has no HA equivalent "
                            "(choose always exits after the first match)"
                            if a.get("ctp") in ("f", "e") else None)})
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
        elif at == "each":
            # for-each over a device list (PISTON_JSON_REFERENCE §2.2):
            # x = loop variable name, lo = device-list operand, s = body.
            lo = a.get("lo") or {}
            out.append({"kind": "foreach",
                        "var": a.get("x"),
                        "devices": lo.get("d", []),
                        "lo_type": lo.get("t"),
                        "body": _action_tree(a.get("s", []), where, kwargs), "raw": a})
        elif at == "break":
            out.append({"kind": "break", "raw": a})
        elif at == "do":
            out.extend(_action_tree(a.get("s", []), where, kwargs))
        elif at == "exit":
            out.append({"kind": "stop", "raw": a})
        else:
            raise NotYetImplemented(
                f"nested statement type '{at}' in {where} not compiled yet", **kwargs)
        _gate_nested(a, out, start, kwargs)
    return out


def _gate_nested(stmt: dict, out: list, start: int, kwargs: dict) -> None:
    """A restriction on a NESTED statement gates that statement, else included.

    FOUND 2026-08-01, same silent-drop class as condition-attached ts/fs: this
    walker never read `r` at all. `_restriction_nodes` is applied to the piston
    root and to TOP-LEVEL statements only, so a restriction on anything nested
    was dropped without a word — the YAML band would run a gated statement
    unconditionally. 0 of 84 corpus pistons use one, which under the standing
    rule says nothing about anyone else's (corpus absence is never evidence).

    Wrapping is the same shape `_restriction_nodes` documents for the top
    level: gate the WHOLE statement with no else of its own, so a failed
    restriction runs nothing rather than falling through to an else."""
    nodes = out[start:]
    if not nodes or not stmt.get("r"):
        return
    gate = _restriction_nodes(stmt, kwargs)      # raises on 'rn', as it should
    if not gate:
        return
    out[start:] = [{"kind": "if", "conditions": gate,
                    "then": nodes, "else": [], "raw": stmt}]


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
    blocker = None
    if op not in ("and", "or"):
        blocker = (f"condition operator '{op}' (statement ${sid}) "
                   f"not compiled yet")
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
        "yaml_blocker": blocker,
        "raw": stmt,
    }


def _every_branch(stmt: dict, sid, kwargs: dict) -> dict:
    """`every` timer statement (VERIFIED webcore-piston.groovy scheduleTimer
    :4770 — lo = interval + unit (om = minute offset for hourly), lo2 = the
    at-time for day+ units; time constants are minutes since midnight per
    PISTON_JSON_REFERENCE §operands)."""
    lo = stmt.get("lo") or {}
    interval, unit = lo.get("c"), lo.get("vt")
    blocker = None
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
    elif unit == "d" and interval == 1 and isinstance(
            (stmt.get("lo2") or {}).get("c"), (int, float)) and \
            (stmt.get("lo2") or {}).get("vt") == "time":
        at = int((stmt.get("lo2") or {})["c"])
        timer = {"kind": "time", "at": f"{at // 60:02d}:{at % 60:02d}:00"}
    elif unit == "d" and interval == 1:
        # sunrise/sunset/variable rather than a fixed clock time
        timer = {"kind": "unexpressible"}
        blocker = (f"'every day at' with a non-fixed time (sunrise/sunset/"
                   f"variable) (statement ${sid}) requires PyScript")
    else:
        # RECORDED, not raised (2026-08-06) — see _cond_node. The YAML band
        # still refuses these (emit_yaml raises on the recorded blocker, with
        # this exact wording, so routing and the reason text are unchanged);
        # the difference is that the piston is now fully READ first, so the
        # PyScript band can consume the same IR.
        timer = {"kind": "unexpressible"}
        blocker = (f"'every {interval}{unit}' (statement ${sid}) has no native "
                   f"HA trigger — requires PyScript")

    return {
        "stmt_id": sid,
        "kind": "timer",
        "tcp": stmt.get("tcp", "c") or "c",
        "timer": timer,
        "yaml_blocker": blocker,
        "raw": stmt,
        "triggers": [],
        "conditions": [],
        "then": _action_tree(stmt.get("s", []), f"every ${sid}", kwargs),
        "else": [],
    }


def yaml_blockers(node) -> list[str]:
    """Every "the YAML band can't express this" note recorded anywhere under a
    branch, in the order the tree is walked.

    WHY THIS EXISTS (2026-08-06). The analyzer used to RAISE at each of these
    points, and that raise doubled as the routing decision: emit_yaml would
    abort, compile_piston caught it, and the piston went to PyScript with the
    exception text as the reason. That worked only while the analyzer was the
    YAML band's private reader. Stage 1 of SESSION_BRIEF_ONE_READER_ONE_WRITER
    has BOTH bands read it, and then a raise means the piston compiles on
    neither band — with no fallback at all for a user who forced PyScript,
    which bypasses routing entirely (Jeremy, 2026-08-06).

    So the two jobs are separated: the analyzer READS everything, and records
    what YAML can't express as a fact. emit_yaml turns the first note back into
    the identical exception, so routing behaviour and the recorded reason text
    are unchanged.

    Deliberately NOT a fixed list of "shapes that need PyScript" — that set
    SHRINKS as HA gains abilities and as the YAML emitter grows, and each note
    is removed by making the emitter handle the shape, never by editing a
    table (Jeremy, 2026-08-06: the gate has to stay adjustable as HA changes)."""
    found = []
    if isinstance(node, list):
        for item in node:
            found += yaml_blockers(item)
    elif isinstance(node, dict):
        if node.get("yaml_blocker"):
            found.append(node["yaml_blocker"])
        for key, value in node.items():
            # `raw` is the untouched piston dict hanging off every node; it can
            # never hold a blocker and walking it would revisit the whole
            # subtree once per node.
            if key not in ("raw", "raw_stmt", "yaml_blocker"):
                found += yaml_blockers(value)
    return found


def analyze(piston: dict, piston_id: str, piston_name: str) -> list[dict]:
    """Returns a list of branch IRs, one per top-level statement."""
    branches = []
    # piston-level restrictions ("only execute if ...") gate EVERY statement.
    piston_kwargs = {"piston_id": piston_id, "piston_name": piston_name, "stmt_id": None}
    piston_restrictions = _restriction_nodes(piston, piston_kwargs)
    for stmt in piston.get("s", []):
        sid = stmt.get("$")
        kwargs = {"piston_id": piston_id, "piston_name": piston_name, "stmt_id": sid}
        t = stmt.get("t")
        if t == "if":
            branches.append(_if_branch(stmt, sid, kwargs))
        elif t == "every":
            branches.append(_every_branch(stmt, sid, kwargs))
        elif t == "on":
            # on-events-do (PISTON_JSON_REFERENCE §2.2): an explicit event block.
            # Its `c` entries are the events to subscribe to — webCoRE forces
            # o="or" and n=false — and `s` is the body. Every entry is a TRIGGER,
            # never a checked condition: the block exists precisely to say "when
            # any of these happen, do this".
            on_triggers = []
            for c in stmt.get("c", []):
                node = _cond_node(c, kwargs)
                node["ct"] = "t"
                on_triggers.append(node)
            branches.append({
                "stmt_id": sid, "kind": "if", "tcp": stmt.get("tcp", "c") or "c",
                "triggers": on_triggers, "conditions": [],
                "then": _action_tree(stmt.get("s", []), f"on ${sid}", kwargs),
                "else": [], "raw": stmt,
            })
        elif t == "action":
            # a bare top-level action: no subscription, just steps to run
            branches.append({
                "stmt_id": sid, "kind": "actions", "tcp": stmt.get("tcp", "c") or "c",
                "triggers": [], "conditions": [],
                "then": _action_tree([stmt], f"statement ${sid}", kwargs),
                "else": [], "raw": stmt,
            })
        else:
            # do / while / repeat / for / each / switch / break / exit at the
            # TOP level. _action_tree already knows every one of them — they
            # are ordinary nested statements — so the reader can read them
            # here too; this dispatch simply raised before reaching it, which
            # meant the analyzer could not read a piston that opens with a
            # bare `each` or `while` while the PyScript band compiles them.
            #
            # FOUND 2026-08-06 by the statement gate in test_intent_probe.py,
            # not by inspection: eight shapes, none of them in the corpus, all
            # of them invisible to every other check. An unknown type still
            # raises — from _action_tree, which is the one place that decides
            # what a statement type means.
            branches.append({
                "stmt_id": sid, "kind": "actions",
                "tcp": stmt.get("tcp", "c") or "c",
                "triggers": [], "conditions": [],
                "then": _action_tree([stmt], f"statement ${sid}", kwargs),
                "else": [], "raw": stmt,
                "yaml_blocker": (f"top-level statement type '{t}' "
                                 f"(statement ${sid}) not compiled yet"),
            })
        # Kept OUT of "conditions" on purpose — see _restriction_nodes: these
        # gate the whole statement (else included) and must be emitted above the
        # if/else action, and they must never be promoted to a subscription.
        branches[-1]["restrictions"] = (_restriction_nodes(stmt, kwargs)
                                        + list(piston_restrictions))
        # webCoRE's OWN name for this statement. `kind` is the analyzer's
        # summary and is deliberately lossy — an `on` block and an `if` are
        # both kind "if" — but the PyScript band subscribes differently for
        # each, so the distinction has to survive the read. Recorded once here
        # rather than each band re-deriving it from the raw JSON.
        branches[-1]["stmt_type"] = t

    # IS THIS PISTON TRIGGER-DRIVEN? An intent-level fact about the WHOLE
    # piston, so it is read here rather than re-derived by each emitter.
    #
    # webCoRE computes the same thing once (`hasTriggers`,
    # webcore-piston.groovy:8771-8772) and uses it at :9296 to decide whether
    # conditions get promoted to subscriptions. A piston that subscribes to
    # ANYTHING promotes nothing: every statement runs on that event, gated by
    # its own conditions. Deciding this per statement is what made a
    # triggerless statement compile into its own independently firing
    # automation.
    #
    # Stamped on every branch so both bands read the same answer instead of
    # each computing its own — one reader, which is the whole point.
    has_triggers = any(br.get("triggers") for br in branches)
    for br in branches:
        br["piston_has_triggers"] = has_triggers
    return branches

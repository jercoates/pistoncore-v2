"""EMIT (PyScript/2.x band) — piston JSON -> a pyscript module, via the band
templates (PYSCRIPT_COMPILER_RESEARCH.md — the authority for every mechanism
used here).

Shape per research §4: ONE trigger function per piston (deterministic name,
stable log path), all triggers as OR'd decorators stamped with
kwargs={"stmt_id": ...}, a file-preamble task.unique that kills the in-flight
old version on redeploy (§2), @task_unique for webCoRE-restart execution
(§6), forgiving numeric guards + state.get string form (§9 locked rules),
plain `def` / task.sleep / never exit() (§10 never-emit list), and a
@service execute hook (§8).

Execution model (webCoRE engine semantics): a device event wakes the piston
and the whole statement list runs top-to-bottom; `every` timers and `on`
event blocks fast-forward — only the firing statement's body runs.

Fidelity caveats (Tier-3, research §10): trigger comparisons inside an if's
condition set evaluate against CURRENT state on non-originating events;
cancelTasks is a no-op breadcrumb (the restart execution model already kills
pending waits on retrigger). webCoRE $expressions are NotYetImplemented —
the one honest hard boundary left."""

from pathlib import Path

from jinja2 import ChoiceLoader, Environment, FileSystemLoader

from .. import customize

from .errors import NotYetImplemented
from .expression import ExprTranspiler
from .resolve import Resolver

_BAND_REL = "templates/compiler/pyscript/2.x"
_env = Environment(
    loader=ChoiceLoader([FileSystemLoader(d) for d in customize.search_dirs(_BAND_REL)]),
    trim_blocks=False, lstrip_blocks=False)

MODE_ENTITY = "input_select.pistoncore_location_mode"

_NUMERIC_OPS = {"is_less_than": "<", "is_less_than_or_equal_to": "<=",
                "is_greater_than": ">", "is_greater_than_or_equal_to": ">="}
_EQUALITY_OPS = {"is": "==", "is_equal_to": "==",
                 "is_not": "!=", "is_not_equal_to": "!="}
_TRIGGER_COS = {
    "changes_to", "changes", "changes_away_from", "rises_above", "drops_below",
    "changes_to_any_of", "changes_away_from_any_of", "gets", "arrives",
    "rises", "drops", "rises_to_or_above", "drops_to_or_below",
    "enters_range", "exits_range", "happens_daily_at",
    "becomes_even", "becomes_odd",
    "stays", "stays_equal_to", "stays_any_of", "stays_away_from",
    "stays_different_than", "stays_unchanged", "stays_even", "stays_odd",
    "stays_greater_than", "stays_greater_than_or_equal_to",
    "stays_less_than", "stays_less_than_or_equal_to",
    "stays_inside_of_range", "stays_outside_of_range",
    "remains_above", "remains_above_or_equal_to",
    "remains_below", "remains_below_or_equal_to",
    "remains_even", "remains_odd",
    "remains_inside_of_range", "remains_outside_of_range",
}


def _hold_seconds(op) -> int | None:
    """The `to` operand on stays/remains — hold time in seconds, or None."""
    if not isinstance(op, dict):
        return None
    n = op.get("c")
    if not isinstance(n, (int, float)) or isinstance(n, bool):
        return None
    return int(n * {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(op.get("vt", "s"), 1))


def _q(s) -> str:
    return "'" + str(s).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _wait_seconds(params: list) -> float:
    p = params[0] if params else {}
    n = p.get("c", 0)
    return {"s": n, "m": n * 60, "h": n * 3600}.get(p.get("vt", "s"), n)


class _PyEmitter:
    def __init__(self, piston: dict, piston_id: str, piston_name: str,
                 resolver: Resolver):
        self.piston = piston
        self.piston_id = piston_id
        self.piston_name = piston_name
        self.resolver = resolver
        self.decorators: list[dict] = []
        array_vars = {v.get("n") for v in piston.get("v", [])
                      if str(v.get("t", "")).endswith("]")}
        self.expr = ExprTranspiler(resolver.local_var_names, resolver.globals_map,
                                   resolver, self._ctx(None), MODE_ENTITY,
                                   array_vars=array_vars)

    def _ctx(self, sid) -> dict:
        return {"piston_id": self.piston_id, "piston_name": self.piston_name,
                "stmt_id": sid}

    def _string_param(self, op: dict, ctx: dict) -> str:
        """String-typed task param: constants go through webCoRE's
        string-interpolation grammar ({expr} blocks — the dashboard's own
        parseString path, run on EVERY string constant at save); expression
        operands through the full expression grammar."""
        self.expr.ctx = ctx
        if op.get("t") == "c":
            text = op.get("c")
            if isinstance(text, str) and "{" in text:
                return self.expr.transpile_string(text)
            return repr("" if text is None else str(text))
        return self._operand_expr(op, ctx)

    _SYS_FALLBACK = {"alarmSystemAlert": "_sys_alarm()",
                     "alarmSystemRules": "''",
                     "time": "_now_min()", "datetime": "_now_ms()",
                     "currentEventDescription": "_event_description()"}

    def _var_expr(self, name, ctx: dict) -> str:
        """Variable operand: declared piston locals read from pv; entity-backed
        system variables read their HA entity. Anything else is an unknown
        system variable — hard NotYetImplemented, NEVER a silent pv.get(None)
        that would make conditions quietly false forever."""
        sysent = self.resolver.system_entity(name) if name else None
        if sysent:
            return f"_s({_q(sysent)})"
        if name in self.resolver.local_var_names:
            return f"pv.get({_q(name)})"
        if name in self._SYS_FALLBACK:
            return self._SYS_FALLBACK[name]
        raise NotYetImplemented(
            f"system variable '{name}' not compiled yet", **ctx)

    # ── operands ───────────────────────────────────────────────────────────

    def _operand_expr(self, op: dict, ctx: dict) -> str:
        """A right-side / value operand -> python expression."""
        t = op.get("t")
        if t == "c":
            v = op.get("c")
            return repr(v) if not isinstance(v, str) else _q(v)
        if t == "p":
            entities = self.resolver.entities_for_attr(op.get("d", []), op.get("a"), ctx)
            return f"_s({_q(entities[0])})"
        if t == "s":
            # preset operand (color names etc.) — value lives in the s field
            return repr(op.get("s"))
        if t == "v":
            return self._var_expr(op.get("v"), ctx)
        if t == "x":
            # bare variable/system-var reference — same grammar, tiny source
            self.expr.ctx = ctx
            return self.expr.transpile_operand({"e": op.get("x"), "exp": op.get("exp")})
        if t == "e":
            self.expr.ctx = ctx
            return self.expr.transpile_operand(op)
        if t == "u":
            # raw user-entered expression text (trailing ';' is editor noise)
            self.expr.ctx = ctx
            return self.expr.transpile_operand({"e": str(op.get("u", "")).rstrip("; ")})
        raise NotYetImplemented(f"operand type '{t}' not compiled yet", **ctx)

    # ── conditions ─────────────────────────────────────────────────────────

    def _condition_expr(self, cond: dict, ctx: dict) -> str:
        co = cond.get("co")
        lo = cond.get("lo") or {}
        ro = cond.get("ro") or {}
        ro2 = cond.get("ro2") or {}

        if lo.get("t") == "v":
            var = lo.get("v")
            # pure time triggers are gated by their own decorator — the body
            # has nothing to re-check (there is no "current value" of a clock)
            if var == "time" and co in ("happens_daily_at", "happens_at", "executes",
                                        "gets", "arrives"):
                return "True"
            if var in ("time", "datetime") and co in ("is_between", "is_not_between"):
                a, b = ro.get("c"), ro2.get("c")
                a_sun, b_sun = ro.get("s"), ro2.get("s")
                if a_sun or b_sun:
                    lo_e = f"_sun_min({_q(a_sun)})" if a_sun else str(int(a or 0))
                    hi_e = f"_sun_min({_q(b_sun)})" if b_sun else str(int(b or 0))
                    body = f"_time_between({lo_e}, {hi_e})"
                    return f"(not {body})" if co == "is_not_between" else body
                if _is_number(a) and _is_number(b):
                    body = f"_time_between({int(a)}, {int(b)})"
                    return f"(not {body})" if co == "is_not_between" else body
                if ro.get("t") in ("x", "e") or ro2.get("t") in ("x", "e"):
                    lo_e = (f"_as_min({self._operand_expr(ro, ctx)})"
                            if ro.get("t") in ("x", "e") else str(int(a or 0)))
                    hi_e = (f"_as_min({self._operand_expr(ro2, ctx)})"
                            if ro2.get("t") in ("x", "e") else str(int(b or 0)))
                    body = f"_time_between({lo_e}, {hi_e})"
                    return f"(not {body})" if co == "is_not_between" else body
                raise NotYetImplemented("time window with non-fixed bounds requires "
                                        "the expression engine", **ctx)
            if var in ("time", "datetime") and co in ("is_before", "is_after"):
                bound = (f"_sun_min({_q(ro.get('s'))})" if ro.get("s")
                         else str(int(ro.get("c") or 0)))
                op = "<" if co == "is_before" else ">="
                return f"(_now_min() {op} {bound})"
            left = self._var_expr(var, ctx)
            sysent_ = self.resolver.system_entity(var)
            if co in ("changes_to_any_of", "is_any_of", "stays_any_of",
                      "is_not_any_of", "was_any_of"):
                raw = ro.get("c")
                vals = raw if isinstance(raw, list) else [raw]
                opts = ", ".join(_q(self.resolver.system_value(var, v)) for v in vals)
                neg = "not " if "not" in co else ""
                return f"({neg}str({left}) in ({opts},))"
            if co in ("executes", "changes", "changed", "gets", "arrives"):
                return "True"   # gated by the decorator; nothing to re-check
            if co in ("changes_to", "changes_away_from") and sysent_:
                mapped = self.resolver.system_value(var, ro.get("c"))
                op = "==" if co == "changes_to" else "!="
                return f"{left} {op} {_q(mapped)}"
            if co in _EQUALITY_OPS:
                if self.resolver.system_entity(var) and (ro.get("t") == "c"):
                    mapped = self.resolver.system_value(var, ro.get("c"))
                    return f"{left} {_EQUALITY_OPS[co]} {_q(mapped)}"
                return f"{left} {_EQUALITY_OPS[co]} {self._operand_expr(ro, ctx)}"
            raise NotYetImplemented(
                f"comparison '{co}' on variable '{var}' not compiled yet", **ctx)

        if lo.get("t") == "x":
            left = self._operand_expr(lo, ctx)
            return self._compare(left, co, ro, ro2, ctx)

        drefs = [str(d) for d in (lo.get("d") or [])]
        runtime_ref = next((d for d in drefs
                            if d in ("$device", "$currentEventDevice")), None)
        if runtime_ref:
            # the subject is the loop / triggering entity — known only at
            # runtime, so compare its live state directly
            var = "_device" if runtime_ref == "$device" else "var_name"
            left = f"_s({var})"
            return self._compare(left, co, ro, ro2, ctx)
        entities = self.resolver.entities_for_attr(lo.get("d", []), lo.get("a"), ctx)
        joiner = " and " if lo.get("g") == "all" else " or "
        attr = lo.get("a")
        value = ro.get("c")

        if co in _NUMERIC_OPS or (co in ("rises_above", "drops_below")):
            op = _NUMERIC_OPS.get(co) or (">" if co == "rises_above" else "<")
            parts = [f"(_f({_q(e)}) is not None and _f({_q(e)}) {op} {value})"
                     for e in entities]
        elif co == "is_between" and _is_number(value) and _is_number(ro2.get("c")):
            parts = [f"(_f({_q(e)}) is not None and {value} <= _f({_q(e)}) <= {ro2.get('c')})"
                     for e in entities]
        elif co in _EQUALITY_OPS:
            op = _EQUALITY_OPS[co]
            if _is_number(value):
                parts = [f"(_f({_q(e)}) is not None and _f({_q(e)}) {op} {value})"
                         for e in entities]
            else:
                mapped = self.resolver.ha_state_value(attr, value)
                parts = [f"_s({_q(e)}) {op} {_q(mapped)}" for e in entities]
        elif co in ("changes_to",):
            # current-state approximation of the originating event (Tier-3)
            mapped = self.resolver.ha_state_value(attr, value)
            parts = [f"_s({_q(e)}) == {_q(mapped)}" for e in entities]
        elif co == "changes_away_from":
            mapped = self.resolver.ha_state_value(attr, value)
            parts = [f"_s({_q(e)}) != {_q(mapped)}" for e in entities]
        elif co == "changes":
            ids = ", ".join(_q(e) for e in entities)
            parts = [f"(var_name is None or var_name in ({ids},))"]
        elif co in ("is_any_of", "is_not_any_of", "is_any", "was_any_of", "was_not_any_of"):
            vals = value if isinstance(value, list) else [value]
            opts = ", ".join(_q(self.resolver.ha_state_value(attr, v)) for v in vals)
            neg = "not " if "not" in co else ""
            parts = [f"({neg}_s({_q(e)}) in ({opts},))" for e in entities]
        elif co in ("is_even", "is_odd", "was_even", "was_odd"):
            want = 0 if co.endswith("even") else 1
            parts = [f"(_f({_q(e)}) is not None and int(_f({_q(e)})) % 2 == {want})"
                     for e in entities]
        elif co in ("is_not_between", "is_outside_of_range", "was_outside_of_range"):
            v2 = ro2.get("c")
            # fail-closed: an unavailable sensor must NOT satisfy an
            # outside-range check (was a fail-open `is None or` — review 2026-07-20)
            parts = [f"(_f({_q(e)}) is not None and not ({value} <= _f({_q(e)}) <= {v2}))"
                     for e in entities]
        elif co in ("is_inside_of_range", "was_inside_of_range"):
            v2 = ro2.get("c")
            parts = [f"(_f({_q(e)}) is not None and {value} <= _f({_q(e)}) <= {v2})"
                     for e in entities]
        elif co == "is_different_than":
            parts = [f"_s({_q(e)}) != {_q(self.resolver.ha_state_value(attr, value))}"
                     for e in entities]
        elif co in ("changed", "did_not_change"):
            ids = ", ".join(_q(e) for e in entities)
            neg = "not " if co == "did_not_change" else ""
            parts = [f"({neg}(var_name in ({ids},)))"]
        elif co in ("was_greater_than", "was_greater_than_or_equal_to",
                    "was_less_than", "was_less_than_or_equal_to",
                    "was_equal_to", "was_different_than"):
            # history comparisons approximate to current state + age (Tier-3)
            OPS = {"was_greater_than": ">", "was_greater_than_or_equal_to": ">=",
                   "was_less_than": "<", "was_less_than_or_equal_to": "<=",
                   "was_equal_to": "==", "was_different_than": "!="}
            op = OPS[co]
            if op in ("==", "!="):
                parts = [f"(_s({_q(e)}) {op} {_q(self.resolver.ha_state_value(attr, value))})"
                         for e in entities]
            else:
                parts = [f"(_f({_q(e)}) is not None and _f({_q(e)}) {op} {value})"
                         for e in entities]
        elif co in ("stays_greater_than", "stays_greater_than_or_equal_to",
                    "stays_less_than", "stays_less_than_or_equal_to",
                    "remains_above", "remains_below"):
            OPS = {"stays_greater_than": ">", "stays_greater_than_or_equal_to": ">=",
                   "stays_less_than": "<", "stays_less_than_or_equal_to": "<=",
                   "remains_above": ">", "remains_below": "<"}
            op = OPS[co]
            hold = _hold_seconds(cond.get("to")) or 0
            parts = [f"(_f({_q(e)}) is not None and _f({_q(e)}) {op} {value} and "
                     f"(_fn_age({_q(e)}) or 0) >= {hold * 1000})" for e in entities]
        elif co in ("stays", "stays_equal_to", "stays_any_of"):
            vals = value if isinstance(value, list) else [value]
            opts = ", ".join(_q(self.resolver.ha_state_value(attr, v)) for v in vals)
            hold = _hold_seconds(cond.get("to")) or 0
            parts = [f"(_s({_q(e)}) in ({opts},) and "
                     f"(_fn_age({_q(e)}) or 0) >= {hold * 1000})" for e in entities]
        elif co in ("was", "was_not"):
            # "was (not) X for T": exact via last_changed — the state has been
            # its CURRENT value since last_changed, so current-check + age
            # covers the whole window (webCoRE history semantics for the
            # constant-state case; sub-window flapping shows as a younger age
            # -> fail-closed false)
            dur = self._duration_ms(cond.get("to"))
            if dur is None:
                raise NotYetImplemented(
                    f"'{co}' without a fixed duration not compiled yet", **ctx)
            qual = ">=" if (cond.get("to") or {}).get("f", "g") == "g" else "<"
            mapped = self.resolver.ha_state_value(attr, value)
            eq = "==" if co == "was" else "!="
            parts = [f"(_s({_q(e)}) {eq} {_q(mapped)} and "
                     f"(_fn_age({_q(e)}) or 0) {qual} {dur})" for e in entities]
        else:
            raise NotYetImplemented(f"condition comparison '{co}' not compiled yet", **ctx)

        return parts[0] if len(parts) == 1 else "(" + joiner.join(parts) + ")"

    def _compare(self, left: str, co: str, ro: dict, ro2: dict, ctx: dict) -> str:
        """Generic comparison against an already-transpiled left expression —
        used for variable/expression left sides."""
        if co in _EQUALITY_OPS or co in ("changes_to", "gets", "is_equal_to"):
            op = _EQUALITY_OPS.get(co, "==")
            return f"_op({left}, {op!r}, {self._operand_expr(ro, ctx)})"
        if co == "changes_away_from":
            return f"_op({left}, '!=', {self._operand_expr(ro, ctx)})"
        if co in _NUMERIC_OPS:
            return f"_op({left}, {_NUMERIC_OPS[co]!r}, {self._operand_expr(ro, ctx)})"
        if co in ("is_between", "is_inside_of_range", "is_outside_of_range"):
            a = self._operand_expr(ro, ctx)
            b = self._operand_expr(ro2, ctx)
            body = f"_fn_isbetween({left}, {a}, {b})"
            return body if co != "is_outside_of_range" else f"(not {body})"
        if co in ("is_any_of", "is_not_any_of", "is_any"):
            vals = ro.get("c")
            vals = vals if isinstance(vals, list) else [vals]
            opts = ", ".join(_q(v) for v in vals)
            neg = "not " if co == "is_not_any_of" else ""
            return f"({neg}str({left}) in ({opts},))"
        if co in ("is_true",):
            return f"_truthy({left})"
        if co in ("is_false", "is_not_true"):
            return f"(not _truthy({left}))"
        raise NotYetImplemented(
            f"comparison '{co}' on expression operand not compiled yet", **ctx)

    @staticmethod
    def _duration_ms(op: dict) -> int | None:
        n = (op or {}).get("c")
        if not isinstance(n, (int, float)):
            return None
        return int(n * {"s": 1, "m": 60, "h": 3600, "d": 86400}
                   .get((op or {}).get("vt", "s"), 1) * 1000)

    def _group_expr(self, conds: list, operator: str, ctx: dict) -> str:
        exprs = []
        for c in conds:
            # "restriction" nodes share the condition anatomy (PISTON_JSON_REFERENCE
            # §7); a restriction GROUP carries children in `r`/`rop` where a
            # condition group uses `c`/`o`.
            if c.get("t") in ("condition", "restriction"):
                exprs.append(self._condition_expr(c, ctx))
            elif c.get("t") == "group":
                kids, op = c.get("c"), c.get("o", "and")
                if not kids and c.get("r"):
                    kids, op = c.get("r"), c.get("rop", "and")
                exprs.append(self._group_expr(kids or [], op, ctx))
            else:
                raise NotYetImplemented(
                    f"condition node type '{c.get('t')}' not compiled yet", **ctx)
        if not exprs:
            return "True"
        if operator == "xor":
            return f"sum([bool(x) for x in [{', '.join(exprs)}]]) == 1"
        joiner = " or " if operator == "or" else " and "
        return joiner.join(exprs) if len(exprs) == 1 else "(" + joiner.join(exprs) + ")"

    # ── triggers (decorators) ──────────────────────────────────────────────

    def _add_state_trigger(self, exprs: list[str], sid, edge: bool, hold=None):
        # dedupe exact repeats: two trigger comparisons on the same entity
        # (e.g. changes_to on + changes_to off with an else) would otherwise
        # register identical decorators and double-fire the handler per
        # transition (code-review find, 2026-07-19)
        for d in self.decorators:
            if (d["kind"] == "state_trigger" and d["exprs"] == exprs
                    and d["edge"] == edge and d["stmt_id"] == sid
                    and d.get("hold") == hold):
                return
        self.decorators.append({"kind": "state_trigger", "exprs": exprs,
                                "edge": edge, "stmt_id": sid, "hold": hold})

    def _trigger_decorator(self, cond: dict, sid, ctx: dict):
        co = cond.get("co")
        lo = cond.get("lo") or {}
        if lo.get("t") == "v":
            var = lo.get("v")
            sysent = self.resolver.system_entity(var)
            if var in ("time", "datetime"):
                value = (cond.get("ro") or {}).get("c")
                ro_ = cond.get("ro") or {}
                preset = ro_.get("s")
                if not preset and isinstance(ro_.get("x"), str) and \
                        ro_["x"].strip().lower().lstrip("$") in ("sunrise", "sunset"):
                    preset = ro_["x"].strip().lower().lstrip("$")
                if preset:
                    self.decorators.append(
                        {"kind": "time_trigger",
                         "spec": f"once({str(preset).lower()})", "stmt_id": sid})
                    return
                if _is_number(value):
                    at = int(value)
                    self.decorators.append(
                        {"kind": "time_trigger",
                         "spec": f"cron({at % 60} {at // 60} * * *)", "stmt_id": sid})
                    return
            if sysent:
                raw = (cond.get("ro") or {}).get("c")
                vals = raw if isinstance(raw, list) else [raw]
                mapped = [self.resolver.system_value(var, v) for v in vals]
                if co in ("changes_to", "gets", "is", "executes"):
                    self._add_state_trigger([f"{sysent} == {_q(mapped[0])}"], sid, True)
                    return
                if co in ("changes_to_any_of", "is_any_of"):
                    opts = ", ".join(_q(v) for v in mapped)
                    self._add_state_trigger([f"{sysent} in ({opts},)"], sid, True)
                    return
                self._add_state_trigger([sysent], sid, False)
                return
            raise NotYetImplemented(
                f"trigger comparison '{co}' on system variable '{var}' "
                f"not compiled yet", **ctx)
        entities = self.resolver.entities_for_attr(lo.get("d", []), lo.get("a"), ctx)
        value = (cond.get("ro") or {}).get("c")
        value2 = (cond.get("ro2") or {}).get("c")
        attr = lo.get("a")
        hold = _hold_seconds(cond.get("to"))

        def mv(v):
            return self.resolver.ha_state_value(attr, v)

        # "stays/remains X for N" -> PyScript's native state_hold (research §3:
        # the docs' own definition of state_hold IS webCoRE's `stays`)
        STAYS_EQ = ("stays", "stays_equal_to")
        if co in STAYS_EQ and hold:
            self._add_state_trigger([f"{e} == {_q(mv(value))}" for e in entities],
                                    sid, True, hold)
            return
        if co == "stays_any_of" and hold:
            vals = value if isinstance(value, list) else [value]
            opts = ", ".join(_q(mv(v)) for v in vals)
            self._add_state_trigger([f"{e} in ({opts},)" for e in entities],
                                    sid, True, hold)
            return
        if co in ("stays_away_from", "stays_different_than") and hold:
            self._add_state_trigger([f"{e} != {_q(mv(value))}" for e in entities],
                                    sid, True, hold)
            return
        if co == "stays_unchanged" and hold:
            self._add_state_trigger(list(entities), sid, False, hold)
            return
        NUM_HOLD = {"stays_greater_than": ">", "stays_greater_than_or_equal_to": ">=",
                    "stays_less_than": "<", "stays_less_than_or_equal_to": "<=",
                    "remains_above": ">", "remains_above_or_equal_to": ">=",
                    "remains_below": "<", "remains_below_or_equal_to": "<="}
        if co in NUM_HOLD:
            op = NUM_HOLD[co]
            self._add_state_trigger(
                [f"{e} is not None and {e} not in ('unknown','unavailable') "
                 f"and float({e}) {op} {value}" for e in entities], sid, True, hold)
            return
        if co in ("changes_to_any_of", "changes_away_from_any_of"):
            vals = value if isinstance(value, list) else [value]
            opts = ", ".join(_q(mv(v)) for v in vals)
            inop = "in" if co == "changes_to_any_of" else "not in"
            self._add_state_trigger([f"{e} {inop} ({opts},)" for e in entities],
                                    sid, True)
            return
        if co in ("rises", "rises_to_or_above"):
            self._add_state_trigger(
                [f"{e} is not None and {e} not in ('unknown','unavailable') "
                 f"and float({e}) >= {value}" for e in entities], sid, True)
            return
        if co in ("drops", "drops_to_or_below"):
            self._add_state_trigger(
                [f"{e} is not None and {e} not in ('unknown','unavailable') "
                 f"and float({e}) <= {value}" for e in entities], sid, True)
            return
        if co in ("enters_range", "exits_range", "remains_inside_of_range",
                  "stays_inside_of_range", "remains_outside_of_range",
                  "stays_outside_of_range") and _is_number(value) and _is_number(value2):
            inside = "outside" not in co
            body = (f"{value} <= float({{e}}) <= {value2}" if inside
                    else f"not ({value} <= float({{e}}) <= {value2})")
            self._add_state_trigger(
                [f"{e} is not None and {e} not in ('unknown','unavailable') and "
                 + body.replace("{e}", e) for e in entities], sid, True,
                hold if "remains" in co or "stays" in co else None)
            return
        if co == "happens_daily_at" and _is_number(value):
            at = int(value)
            self.decorators.append({"kind": "time_trigger",
                                    "spec": f"cron({at % 60} {at // 60} * * *)",
                                    "stmt_id": sid})
            return
        if co in ("becomes_even", "becomes_odd", "remains_even", "remains_odd",
                  "stays_even", "stays_odd"):
            want = 0 if co.endswith("even") else 1
            self._add_state_trigger(
                [f"{e} is not None and {e} not in ('unknown','unavailable') "
                 f"and int(float({e})) % 2 == {want}" for e in entities], sid, True,
                hold if ("remains" in co or "stays" in co) else None)
            return
        if co == "changes_to":
            mapped = self.resolver.ha_state_value(attr, value)
            self._add_state_trigger([f"{e} == {_q(mapped)}" for e in entities], sid, True)
        elif co == "changes":
            self._add_state_trigger(list(entities), sid, False)
        elif co == "changes_away_from":
            mapped = self.resolver.ha_state_value(attr, value)
            self._add_state_trigger([f"{e} != {_q(mapped)}" for e in entities], sid, True)
        elif co in ("rises_above", "drops_below"):
            op = ">" if co == "rises_above" else "<"
            self._add_state_trigger(
                [f"{e} is not None and {e} not in ('unknown', 'unavailable') "
                 f"and float({e}) {op} {value}" for e in entities], sid, True)
        else:
            raise NotYetImplemented(f"trigger comparison '{co}' not compiled yet", **ctx)

    def _promote_triggers(self, stmt: dict, sid, ctx: dict) -> bool:
        """Condition-only statement: webCoRE subscribes to its conditions
        (promotion, webcore-piston.groovy :9242) — INCLUDING conditions inside
        nested ifs, and $time windows schedule wakeups at their edges
        (scheduleTimer for time conditions). Any of those wakes the piston;
        condition evaluation in the body decides what runs."""
        entities = []
        time_edges = []

        def collect(s):
            for c in s.get("c", []):
                lo = c.get("lo") or {}
                if lo.get("t") == "p" and lo.get("d"):
                    entities.extend(
                        self.resolver.entities_for_attr(lo.get("d"), lo.get("a"), ctx))
                elif (lo.get("t") == "v" and lo.get("v") == "time"
                        and c.get("co") == "is_between"):
                    for op in (c.get("ro"), c.get("ro2")):
                        v = (op or {}).get("c")
                        if (op or {}).get("vt") == "time" and isinstance(v, (int, float)):
                            time_edges.append(int(v))
            for sub in list(s.get("s", [])) + list(s.get("e", [])):
                if sub.get("t") == "if":
                    collect(sub)
            for ei in s.get("ei") or []:
                collect(ei)

        collect(stmt)
        if entities:
            self._add_state_trigger(sorted(set(entities)), sid, False)
        for at in sorted(set(time_edges)):
            self.decorators.append({"kind": "time_trigger",
                                    "spec": f"cron({at % 60} {at // 60} * * *)",
                                    "stmt_id": sid})
        return bool(entities or time_edges)

    def _every_decorator(self, stmt: dict, sid, ctx: dict):
        lo = stmt.get("lo") or {}
        interval, unit = lo.get("c"), lo.get("vt")
        if not isinstance(interval, int) or interval <= 0:
            raise NotYetImplemented("'every' with non-constant interval — expression "
                                    "engine not built yet", **ctx)
        lo2 = stmt.get("lo2") or {}
        at = lo2.get("c") if lo2.get("vt") == "time" and _is_number(lo2.get("c")) else None
        if unit in ("s", "m", "h"):
            om = lo.get("om") or 0
            start = f"00:{int(om):02d}:00" if unit == "h" and om else "00:00:00"
            spec = f"period({start}, {interval}{unit})"
        elif unit == "d" and interval == 1 and at is not None:
            spec = f"cron({int(at) % 60} {int(at) // 60} * * *)"
        elif unit in ("d", "w"):
            days = interval * (7 if unit == "w" else 1)
            hhmm = f"{int(at) // 60:02d}:{int(at) % 60:02d}:00" if at is not None else "00:00:00"
            spec = f"period(2020-01-01 {hhmm}, {days}d)"
        else:
            raise NotYetImplemented(
                f"'every {interval}{unit}' timer not compiled yet", **ctx)
        self.decorators.append({"kind": "time_trigger", "spec": spec, "stmt_id": sid})

    def _on_decorator(self, stmt: dict, sid, ctx: dict):
        """'on <events>' — supported source: location-mode changes (the shim's
        input_select). Other event sources need their own mapping."""
        for c in stmt.get("c", []):
            lo = c.get("lo") or {}
            if c.get("t") == "event" and lo.get("t") == "v" and lo.get("v") == "mode":
                self._add_state_trigger([MODE_ENTITY], sid, False)
            elif c.get("t") == "event" and lo.get("t") == "p" and lo.get("d"):
                entities = self.resolver.entities_for_attr(lo.get("d"), lo.get("a"), ctx)
                self._add_state_trigger(list(entities), sid, False)
            else:
                raise NotYetImplemented(
                    f"'on' event source {lo.get('t')}/{lo.get('v')} not compiled yet", **ctx)

    # ── tasks ──────────────────────────────────────────────────────────────

    def _task_nodes(self, action_stmt: dict, ctx: dict) -> list:
        out = []
        devices = action_stmt.get("d", [])
        for task in action_stmt.get("k", []):
            cmd = task.get("c")
            params = task.get("p", [])
            if cmd == "wait":
                out.append({"kind": "sleep", "seconds": _wait_seconds(params)})
            elif cmd in ("sendPushNotification", "sendSMSNotification",
                         "deviceNotification"):
                msg = self._string_param(params[0] if params else {"t": "c", "c": ""}, ctx)
                players = (self.resolver.speaker_targets(devices, ctx)
                           if cmd == "deviceNotification" else None)
                if players:
                    engine = self.resolver.system_entity("tts")
                    if not engine:
                        raise NotYetImplemented(
                            "spoken device notification needs a TTS engine "
                            "(PistonCore Settings)", **ctx)
                    out.append({"kind": "service", "domain": "tts", "service": "speak",
                                "entities": [engine],
                                "data": {"media_player_entity_id": repr(players),
                                         "message": f"str({msg})", "cache": "True"}})
                else:
                    out.append({"kind": "service", "domain": "notify",
                                "service": "notify", "entities": [],
                                "data": {"message": f"str({msg})"}})
            elif cmd in ("sendNotification", "sendNotificationToContacts"):
                p0 = params[0] if params else {}
                # in-app notification == HA notifications panel (NOTIFY_ACTION_SPEC)
                out.append({"kind": "service", "domain": "notify",
                            "service": "persistent_notification",
                            "entities": [],
                            "data": {"message": f"str({self._string_param(p0, ctx)})"}})
            elif cmd == "setVariable":
                p0 = params[0] if params else {}
                name = p0.get("x") or p0.get("c")
                if not name:
                    raise NotYetImplemented("setVariable without a variable name", **ctx)
                if p0.get("xi"):
                    self.expr.ctx = ctx
                    idx = self.expr.transpile_operand({"e": p0["xi"]})
                    if str(name).startswith("@"):
                        raise NotYetImplemented(
                            f"writing @global array '{name}' isn't wired yet", **ctx)
                    value_expr = self._operand_expr(
                        params[1] if len(params) > 1 else {"t": "c", "c": None}, ctx)
                    out.append({"kind": "setvar_index", "name": _q(name),
                                "index": idx, "value": value_expr})
                    continue
                value_expr = self._operand_expr(params[1] if len(params) > 1 else {"t": "c", "c": None}, ctx)
                if str(name).startswith("@"):
                    # runtime global write: persisted pyscript entity
                    # (research §7 namespace) + local cache for same-run reads
                    self.expr.used_globals.add(str(name))
                    out.append({"kind": "raw", "code":
                                f"gv[{_q(name)}] = _gv_set({_q(name)}, {value_expr})"})
                else:
                    out.append({"kind": "setvar", "name": _q(name), "value": value_expr})
            elif cmd == "log":
                msg = next((str(p.get("c")) for p in params if p.get("c")), "log")
                out.append({"kind": "log", "msg": _q(f"[{self.piston_id}] {msg}")})
            elif cmd == "exit":
                out.append({"kind": "return"})
            elif cmd == "break":
                out.append({"kind": "break"})
            elif cmd == "setState":
                val = self._string_param(params[0] if params else {"t": "c", "c": ""}, ctx)
                out.append({"kind": "raw", "code":
                            f"state.set('pyscript.pistoncore_{self.piston_id}_state', str({val}))"})
            elif cmd in ("setTile", "setTileTitle", "setTileText", "setTileColor", "clearTile"):
                # webCoRE dashboard tiles have no PistonCore surface yet —
                # persist the values as attributes on the piston state entity
                # so nothing is lost and a future tile renderer can read them
                exprs = [self._string_param(prm, ctx) if prm.get("t") == "c"
                         else self._operand_expr(prm, ctx) for prm in params]
                kv = ", ".join(f"'p{i}': str({e})" for i, e in enumerate(exprs))
                out.append({"kind": "raw", "code":
                            f"state.setattr('pyscript.pistoncore_{self.piston_id}_state."
                            f"{cmd.lower()}', {{{kv}}})"})
            elif cmd in ("speak", "playText", "playTextAndResume", "playTextAndRestore"):
                engine = self.resolver.system_entity("tts")
                if not engine:
                    raise NotYetImplemented(
                        "Speak needs a TTS engine — pick one in PistonCore "
                        "Settings (several tts.* engines exist in HA)", **ctx)
                if not devices:
                    raise NotYetImplemented("Speak with no speaker devices", **ctx)
                players = self.resolver.entities_for_command(devices, cmd, ctx)
                msg = self._string_param(params[0] if params else {"t": "c", "c": ""}, ctx)
                out.append({"kind": "service", "domain": "tts", "service": "speak",
                            "entities": [engine],
                            "data": {"media_player_entity_id": repr(players),
                                     "message": f"str({msg})", "cache": "True"}})
            elif cmd == "setLocationMode":
                mode = (params[0] or {}).get("c") if params else None
                if not isinstance(mode, str):
                    raise NotYetImplemented("setLocationMode with non-constant mode", **ctx)
                mode_ent = self.resolver.system_entity("mode") or MODE_ENTITY
                out.append({"kind": "service", "domain": "input_select",
                            "service": "select_option", "entities": [mode_ent],
                            "data": {"option": repr(mode)}})
            elif cmd == "setAlarmSystemStatus":
                alarm = self.resolver.system_entity("alarmSystemStatus")
                if not alarm:
                    raise NotYetImplemented(
                        "setAlarmSystemStatus needs exactly one alarm_control_panel "
                        "in HA (none found, or several — ambiguous)", **ctx)
                status = (params[0] or {}).get("c") if params else None
                service = self.resolver.alarm_commands.get(str(status))
                if not service:
                    raise NotYetImplemented(
                        f"alarm status '{status}' has no service mapping "
                        f"(value_maps.json alarm_commands)", **ctx)
                out.append({"kind": "service", "domain": "alarm_control_panel",
                            "service": service, "entities": [alarm], "data": {}})
            elif cmd == "executePiston":
                target = (params[0] or {}).get("c") if params else None
                if not isinstance(target, str) or not target.strip(":"):
                    raise NotYetImplemented("executePiston without a piston target", **ctx)
                # every compiled PyScript piston registers
                # pyscript.pistoncore_<id>_execute (research §8) — YAML-band
                # targets have no service; the call logs a runtime error then
                out.append({"kind": "service", "domain": "pyscript",
                            "service": f"pistoncore_{target.strip(':')}_execute",
                            "entities": [], "data": {}})
            elif cmd in ("cancelTasks", "cancelPendingTasks"):
                # restart execution model already kills pending waits on
                # retrigger (research §6) — breadcrumb only (Tier-3 caveat)
                out.append({"kind": "log",
                            "msg": _q(f"[{self.piston_id}] cancelTasks: no-op under "
                                      f"restart execution model")})
            elif cmd in self.resolver.command_maps.get("_piston_scope", []):
                raise NotYetImplemented(f"piston-scope command '{cmd}' not compiled yet", **ctx)
            else:
                if not devices:
                    raise NotYetImplemented(
                        f"command '{cmd}' with no target devices", **ctx)
                if any(str(d) in ("$device", "$currentEventDevice") for d in devices):
                    var = "_device" if "$device" in [str(d) for d in devices] else "var_name"
                    svc = {"on": "turn_on", "off": "turn_off", "toggle": "toggle"}.get(cmd)
                    if not svc:
                        raise NotYetImplemented(
                            f"command '{cmd}' on a runtime device reference "
                            f"isn't compiled yet", **ctx)
                    out.append({"kind": "raw", "code":
                                f"service.call('homeassistant', '{svc}', entity_id={var})"})
                    continue
                entities = self.resolver.entities_for_command(devices, cmd, ctx)
                service, data_spec = self.resolver.service_spec(cmd, entities[0], ctx)
                domain, svc = service.split(".", 1)
                data = {}
                if data_spec:
                    from .emit_yaml import _param_value
                    data = {k: repr(_param_value(v, params, ctx)) for k, v in data_spec.items()}
                out.append({"kind": "service", "domain": domain, "service": svc,
                            "entities": entities, "data": data})
        return out

    # ── statements ─────────────────────────────────────────────────────────

    def _stmt_nodes(self, stmt: dict, ctx: dict, top: bool = False) -> list:
        """Emit a statement, GATED BY ITS RESTRICTIONS if it has any.

        A restriction ("only when ...") gates the WHOLE statement, its else
        included — see analyze._restriction_nodes for the full reasoning. So the
        statement's nodes are wrapped in a single `if <restrictions>:` with NO
        else: when a restriction fails, nothing runs — not the then, not the
        else. Restrictions never subscribe; this is a gate checked when
        something else wakes the piston.
        """
        nodes = self._stmt_nodes_unrestricted(stmt, ctx, top)
        raw = stmt.get("r") or []
        if not raw:
            return nodes
        if stmt.get("rn"):
            # "except when ..." — silently dropping a restriction is exactly the
            # bug this guards against, so fail loudly instead.
            raise NotYetImplemented(
                "negated restriction set ('rn') not compiled yet", **ctx)
        return [{"kind": "if",
                 "expr": self._group_expr(raw, stmt.get("rop", "and"), ctx),
                 "then": nodes, "else": []}]

    def _stmt_nodes_unrestricted(self, stmt: dict, ctx: dict, top: bool = False) -> list:
        t = stmt.get("t")
        sid = stmt.get("$")
        if t == "action":
            return self._task_nodes(stmt, ctx)
        if t == "if":
            node = {"kind": "if",
                    "expr": self._group_expr(stmt.get("c", []), stmt.get("o", "and"), ctx),
                    "then": self._block(stmt.get("s", []), ctx),
                    "else": self._block(stmt.get("e", []), ctx)}
            for ei in reversed(stmt.get("ei") or []):
                node["else"] = [{"kind": "if",
                                 "expr": self._group_expr(ei.get("c", []), ei.get("o", "and"), ctx),
                                 "then": self._block(ei.get("s", []), ctx),
                                 "else": node["else"]}]
            return [node]
        if t == "switch":
            lo = stmt.get("lo") or {}
            if lo.get("t") in ("c", "v", "x"):
                sw_expr = self._operand_expr(lo, ctx)
            elif lo.get("t") == "p" and lo.get("d"):
                entities = self.resolver.entities_for_attr(lo.get("d"), lo.get("a"), ctx)
                sw_expr = f"_s({_q(entities[0])})"
            else:
                raise NotYetImplemented(f"switch operand type '{lo.get('t')}' not compiled yet", **ctx)
            cases = []
            default = []
            for cs in stmt.get("cs", []):
                body = self._block(cs.get("s", []), ctx)
                if cs.get("t") == "d":
                    default = body
                else:
                    cases.append({"value": self._operand_expr(cs.get("ro") or {}, ctx),
                                  "body": body})
            fallthrough = stmt.get("ctp") in ("f", "e")
            return [{"kind": "switch", "expr": sw_expr, "cases": cases,
                     "default": default, "fallthrough": fallthrough}]
        if t == "for":
            lo, lo2, lo3 = (stmt.get(k) or {} for k in ("lo", "lo2", "lo3"))
            if not all(_is_number(x.get("c")) for x in (lo, lo2)):
                raise NotYetImplemented("'for' with non-constant bounds — expression "
                                        "engine not built yet", **ctx)
            step = lo3.get("c") if _is_number(lo3.get("c")) and lo3.get("c") else 1
            return [{"kind": "for", "start": int(lo.get("c")), "stop": int(lo2.get("c")),
                     "step": int(step), "body": self._block(stmt.get("s", []), ctx)}]
        if t == "do":
            return self._block(stmt.get("s", []), ctx)
        if t == "each":
            # for-each over a device list -> iterate the resolved entities
            lo = stmt.get("lo") or {}
            if lo.get("t") == "p" and lo.get("d"):
                ents = self.resolver.entities_for_attr(lo.get("d"), lo.get("a"), ctx)                     if lo.get("a") else None
                if ents is None:
                    raise NotYetImplemented("'each' over devices without an attribute", **ctx)
                return [{"kind": "foreach", "items": repr(ents),
                         "body": self._block(stmt.get("s", []), ctx)}]
            if lo.get("t") == "d" and lo.get("d"):
                hashes = []
                for dref in lo["d"]:
                    hashes.extend(self.resolver._hashes(str(dref), ctx))
                ents = []
                for h in hashes:
                    entry = self.resolver.resolution_map.get(h) or {}
                    binds = entry.get("cmd_bindings") or {}
                    first = next((v for v in (binds.get(k) for k in
                                  ("on", "off", "lock", "unlock", "open", "close"))
                                  if v), None)
                    if first:
                        ents.append(first)
                if not ents:
                    raise NotYetImplemented(
                        "'each' over devices with no controllable entities", **ctx)
                return [{"kind": "foreach_device", "items": repr(ents),
                         "body": self._block(stmt.get("s", []), ctx)}]
            raise NotYetImplemented(f"'each' over {lo.get('t')} not compiled yet", **ctx)
        if t == "repeat":
            # repeat N times (lo = count) or repeat-while (c = conditions)
            lo = stmt.get("lo") or {}
            body = self._block(stmt.get("s", []), ctx)
            if stmt.get("c"):
                expr = self._group_expr(stmt.get("c", []), stmt.get("o", "and"), ctx)
                return [{"kind": "while", "expr": expr, "body": body}]
            n = lo.get("c")
            if not _is_number(n):
                raise NotYetImplemented("'repeat' with a non-constant count", **ctx)
            return [{"kind": "foreach", "items": f"range({int(n)})", "body": body}]
        if t == "while":
            expr = self._group_expr(stmt.get("c", []), stmt.get("o", "and"), ctx)
            return [{"kind": "while", "expr": expr,
                     "body": self._block(stmt.get("s", []), ctx)}]
        if t == "exit":
            return [{"kind": "return"}]
        if t == "break":
            return [{"kind": "break"}]
        raise NotYetImplemented(f"statement type '{t}' (statement ${sid}) not compiled yet", **ctx)

    def _block(self, stmts: list, ctx: dict) -> list:
        out = []
        for s in stmts:
            out.extend(self._stmt_nodes(s, ctx))
        return out

    # ── top level ──────────────────────────────────────────────────────────

    def build(self) -> dict:
        event_body = []      # runs on device/service wakes (whole-piston walk)
        guarded = []         # every/on bodies: fast-forward to firing stmt only

        # Piston-level restrictions ("only execute if ...") gate EVERY statement.
        # Statement-level ones are handled in _stmt_nodes; this band does not yet
        # wrap the whole piston body, and silently ignoring a gate is the exact
        # bug this feature exists to prevent — so fail loudly until implemented.
        if self.piston.get("r"):
            raise NotYetImplemented(
                "piston-level restrictions are not compiled in the PyScript band yet",
                piston_id=self.piston_id, piston_name=self.piston_name, stmt_id=None)

        for stmt in self.piston.get("s", []):
            sid = stmt.get("$")
            ctx = self._ctx(sid)
            t = stmt.get("t")
            if t == "every":
                self._every_decorator(stmt, sid, ctx)
                guarded.append({"stmt_id": sid,
                                "body": self._block(stmt.get("s", []), ctx)})
            elif t == "on":
                self._on_decorator(stmt, sid, ctx)
                guarded.append({"stmt_id": sid,
                                "body": self._block(stmt.get("s", []), ctx)})
            elif t == "if":
                triggers = [c for c in stmt.get("c", [])
                            if c.get("t") == "condition" and c.get("co") in _TRIGGER_COS]
                has_else = bool(stmt.get("e") or stmt.get("ei"))
                if triggers:
                    for trig in triggers:
                        if has_else and trig.get("co") in ("changes_to", "changes_away_from"):
                            # else must run on the OPPOSITE transition too —
                            # subscribe to any change; the body's condition
                            # check routes then/else (semantic-audit find)
                            lo = trig.get("lo") or {}
                            ents = self.resolver.entities_for_attr(
                                lo.get("d", []), lo.get("a"), ctx)
                            self._add_state_trigger(list(ents), sid, False)
                        else:
                            self._trigger_decorator(trig, sid, ctx)
                else:
                    self._promote_triggers(stmt, sid, ctx)
                event_body.extend(self._stmt_nodes(stmt, ctx, top=True))
            else:
                event_body.extend(self._stmt_nodes(stmt, ctx, top=True))

        # No subscriptions is legal: an execute-only piston (Test button or
        # another piston's executePiston). The @service registration in the
        # template is its entry point — nothing else is needed.

        variables = {}
        for v in self.piston.get("v", []):
            if v.get("t") == "device":
                continue
            init = v.get("v")
            if isinstance(init, dict):
                init = init.get("c")
            variables[v["n"]] = init if isinstance(init, (str, int, float, bool)) else None

        # compile-time snapshot of every @global the expressions read
        global_values = {}
        for name in sorted(self.expr.used_globals):
            g = self.globals_map_value(name)
            global_values[name] = g
        return {"decorators": self.decorators, "event_body": event_body,
                "guarded": guarded, "variables": variables,
                "global_values": global_values,
                "alarm_entity": self.resolver.system_entity("alarmSystemStatus")}

    def globals_map_value(self, name: str):
        g = (self.resolver.globals_map or {}).get(name) or {}
        v = g.get("v")
        if isinstance(v, dict):
            v = v.get("c") if "c" in v else v.get("d")
        return v if isinstance(v, (str, int, float, bool, list)) else None


def compile_pyscript(piston: dict, piston_id: str, piston_name: str,
                     resolution_map: dict, globals_map: dict | None,
                     reasons: list) -> dict:
    resolver = Resolver(piston, resolution_map, globals_map)
    built = _PyEmitter(piston, piston_id, piston_name, resolver).build()
    code = _env.get_template("piston.py.j2").render(
        piston_id=piston_id,
        piston_name=piston_name,
        unique_name=f"pistoncore_{piston_id}",
        func_name=f"piston_{piston_id}",
        reasons=reasons,
        **built,
    )
    return {"target": "pyscript", "code": code, "yaml": None,
            "reasons": reasons, "auto_ids": [], "unresolved": resolver.unresolved}

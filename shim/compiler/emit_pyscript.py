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

from .analyze import analyze
from .errors import NotYetImplemented
from .expression import _EQUALITY_OPS, _NUMERIC_OPS, ExprTranspiler
from .resolve import (Resolver, WAS_TO_IS, was_watcher_entity,
                      last_changed_is_exact, duration_seconds,
                      pause_target_automations)

from . import routing as _routing

_BAND_REL = "templates/compiler/pyscript/2.x"
_env = Environment(
    loader=ChoiceLoader([FileSystemLoader(d) for d in customize.search_dirs(_BAND_REL)]),
    trim_blocks=False, lstrip_blocks=False)


# Scale conversions that have vocab ranges (_value_maps.scales).
_SCALE_TRANSFORMS_PY = {"pct_float", "hue_hs", "sat_hs"}


def _scale_spec(name):
    """(from, to, round) for a vocab scale — the NUMBERS stay in the vocab."""
    from .resolve import _load_vocab
    spec = (_load_vocab().get("_value_maps") or {}).get("scales", {}).get(name)
    if not isinstance(spec, dict):
        return None
    return float(spec["from"]), float(spec["to"]), int(spec.get("round", 2))


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


def _time_presets() -> set:
    """The preset time names, read from the VOCAB's own `presets.time` rather
    than written out here (Jeremy, 2026-08-06: "do not hard code vocab").

    The literal tuple this replaces named only sunrise/sunset, so `every day at
    noon` and `at midnight` were not recognised as presets at all. The vocab
    declares all four, and PyScript's datetime spec accepts all four
    (PYSCRIPT_COMPILER_RESEARCH §"at sunrise/sunset ± offset": "Also
    noon/midnight")."""
    from .resolve import _load_vocab
    return {str(p).lower()
            for p in ((_load_vocab().get("presets") or {}).get("time") or [])}


def _daily_time_spec(op: dict, offset_op: dict | None = None) -> str | None:
    """PyScript time spec for a DAILY time operand — a sun preset or a fixed
    clock time — or None when the operand is neither.

    ONE helper because two callers need the identical answer: a
    `happens_daily_at` comparison (_trigger_decorator) and an `every day at`
    statement (_every_decorator). The second had its own partial copy that
    handled only the number and never looked at `s`, so "every day at sunrise"
    fell through to the multi-day branch and compiled to a plain MIDNIGHT
    timer — silently, with the sun event discarded (found 2026-08-06 by the
    statement-variant probe; 0 of 84 corpus pistons use the shape).

    Sun form per PYSCRIPT_COMPILER_RESEARCH §"at sunrise/sunset ± offset"
    (`once(sunrise)`), and its DST decision (§408-413): a daily/weekly "at
    time" compiles to once()/cron(), NEVER a period() spanning days."""
    op = op or {}
    preset = op.get("s")
    if not preset and isinstance(op.get("x"), str):
        bare = op["x"].strip().lower().lstrip("$")
        if bare in _time_presets():
            preset = bare
    if preset:
        spec = str(preset).lower()
        # THE OFFSET (`lo3`). webCoRE allows one only when the time anchor is
        # NOT a plain constant — VERIFIED twice from the sources rather than
        # inferred: the editor renders it under `if (timer.lo2.t != 'c')`
        # ("anything other than constants may have an offset",
        # piston.module.js:4429-4444, signed, negative = BEFORE), and the
        # engine keeps `lo3` for exactly that case and strips it otherwise
        # (webcore-piston.groovy:1722-1724).
        #
        # It was being dropped silently — "every day at sunrise + 30 minutes"
        # fired at sunrise exactly. PyScript expresses it natively
        # (PYSCRIPT_COMPILER_RESEARCH §"at sunrise/sunset ± offset"), so this
        # is a translation, not a limitation. Seconds come from the ONE
        # duration converter; a non-constant offset yields None and the caller
        # raises rather than guessing.
        if offset_op:
            secs = duration_seconds(offset_op)
            if secs is None:
                return None
            if secs:
                spec += f" {'+' if secs > 0 else '-'} {abs(secs)}s"
        return f"once({spec})"
    if _is_number(op.get("c")):
        at = int(op["c"])
        return f"cron({at % 60} {at // 60} * * *)"
    return None


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
        # was_* comparisons that need their own "how long has this held"
        # tracker; keyed by slug so two identical comparisons share one.
        self.was_watchers: dict = {}
        array_vars = {v.get("n") for v in piston.get("v", [])
                      if str(v.get("t", "")).endswith("]")}
        # HA has no location mode; the helper entity standing in for it is
        # named in the vocab (virtualDevices.mode), never in this file.
        self.mode_entity = resolver.virtual_device_ha("mode").get("entity")
        self.expr = ExprTranspiler(resolver.local_var_names, resolver.globals_map,
                                   resolver, self._ctx(None), self.mode_entity,
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

    def _driver_command(self, cmd: str, devices, params, ctx: dict) -> dict:
        """A driver command routed through the integration's passthrough.

        The PyScript spelling of emit_yaml._driver_command — same passthrough
        spec, same fields, same accepted limitation (a passthrough takes any
        command name and fails at RUNTIME, not compile). VERIFIED on Jeremy's
        hardware 2026-07-29: `take` via hubitat.send_command produced a
        picture."""
        spec = self.resolver.passthrough(devices, ctx)
        if not spec:
            raise NotYetImplemented(
                f"'{cmd}' is a command only the device's own driver knows, and "
                f"this device's integration offers no way to pass one through",
                **ctx)
        data = {spec["command_field"]: _q(cmd)}
        if spec.get("target_field"):
            data[spec["target_field"]] = _q(spec["entity_id"])
        args = [p for p in (params or []) if (p or {}).get("c") not in (None, "")]
        if args:
            if not spec.get("args_field"):
                raise NotYetImplemented(
                    f"'{cmd}' was given values, but {spec['service']} takes no "
                    f"arguments field", **ctx)
            from .emit_yaml import _passthrough_arg
            values = [_passthrough_arg((p or {}).get("c"), spec, cmd, self.resolver, ctx) for p in args]
            data[spec["args_field"]] = repr(values[0] if len(values) == 1 else values)
        domain, svc = spec["service"].split(".", 1)
        return {"kind": "service", "domain": domain, "service": svc,
                "entities": [], "data": data}

    def _read(self, entity: str, attr: str, numeric: bool = False) -> str:
        """Read one device reading — the ONLY way this band spells a read.

        Asks the shared Resolver.read_spec() where the value lives and what
        units it's in, then spells it for PyScript: _s/_f when the value is
        the entity's state, _sa/_fa when it lives in a field inside the
        entity. The YAML band asks the same question and spells it
        state_attr(); the decision is made once, in one place, for both
        (Jeremy, 2026-07-29 — one translation source, routing separate)."""
        field, scale = self.resolver.read_spec(entity, attr) if attr else (None, None)
        fn = "_f" if numeric else "_s"
        if not field:
            return f"{fn}({_q(entity)})"
        if field.endswith("]") and "[" in field:
            # a packed pair (hue is hs_color[0]) — index after the lookup
            name, _, idx = field[:-1].partition("[")
            base = f"({fn}a({_q(entity)}, {_q(name)}) or [0, 0])[{idx}]"
            return base
        args = f"{_q(entity)}, {_q(field)}"
        if scale:
            mult, div = self.resolver.scale_factors(scale, f" on {attr} ({entity})")
            args += f", {mult!r}, {div!r}"
        return f"{fn}a({args})"

    def _reads(self, entities, attr, numeric: bool = False) -> list[str]:
        return [self._read(e, attr, numeric) for e in entities]

    def _spec_data_py(self, data_spec: dict, params: list, ctx: dict,
                      entity: str | None = None) -> dict:
        """Service data for THIS band — Python expressions, not Jinja.

        `$N` tokens resolve through _operand_expr, so a parameter given as a
        VARIABLE or an EXPRESSION works the same as a literal. A `|transform`
        suffix that is a vocab scale is applied with the vocab's own numbers.

        An UNSET optional parameter is OMITTED (Jeremy: "the default on volume
        is just keep what is there and dont send a new").

        Do NOT route this back through emit_yaml: that helper emits Jinja, and
        Jinja inside a PyScript module is just a broken string."""
        from .resolve import rescale
        out = {}
        for key, token in (data_spec or {}).items():
            raw, tname = str(token), None
            if "|" in raw:
                raw, tname = raw.split("|", 1)
            if not raw.startswith("$"):
                out[key] = repr(raw)
                continue
            # $object_id / $entity_id name THE DEVICE the command is aimed at,
            # not a piston parameter — `take` has no parameters at all, so a
            # snapshot filename can only come from the camera. The YAML band
            # has handled these since the media work; this band assumed every
            # `$` token was positional and did int("object_id"), which took
            # the WHOLE compile down with an internal error. Any camera piston
            # that routes to PyScript hit it.
            if entity and ("$object_id" in raw or "$entity_id" in raw):
                out[key] = repr(raw.replace("$object_id", entity.split(".", 1)[1])
                                   .replace("$entity_id", entity))
                continue
            if not raw[1:].isdigit():
                raise NotYetImplemented(
                    f"command data token {raw} is not a parameter and has no "
                    f"device to resolve it against", **ctx)
            idx = int(raw[1:]) - 1
            if idx >= len(params):
                raise NotYetImplemented(f"command param {raw} missing", **ctx)
            prm = params[idx] or {}
            if (not prm.get("t") and prm.get("c") is None and prm.get("s") is None
                    and not prm.get("e") and not prm.get("x")):
                continue                      # unset optional parameter
            if tname == "duration_secs":
                # A fade's length. HA's `transition` is seconds; webCoRE keeps
                # the unit beside the number, so this MUST convert or "2
                # minutes" arrives as 2 seconds. Same converter the YAML band
                # uses (resolve.duration_seconds) so the bands cannot drift.
                secs = duration_seconds(prm)
                if secs is None:
                    raise NotYetImplemented(
                        f"'{key}' needs a fixed duration", **ctx)
                out[key] = repr(secs)
                continue
            if prm.get("c") is not None and not prm.get("t") in ("x", "e"):
                value = prm.get("c")
                out[key] = repr(rescale(tname, value) if tname in _SCALE_TRANSFORMS_PY
                                else value)
                continue
            expr = self._operand_expr(prm, ctx)
            if tname in _SCALE_TRANSFORMS_PY:
                spec = _scale_spec(tname)
                if spec:
                    src, dst, digits = spec
                    expr = (f"round(_num({expr}) * {dst / src!r}, {digits})"
                            if src != dst else f"round(_num({expr}), {digits})")
            out[key] = expr
        return out

    def _operand_expr(self, op: dict, ctx: dict) -> str:
        """A right-side / value operand -> python expression."""
        t = op.get("t")
        if t == "c":
            v = op.get("c")
            return repr(v) if not isinstance(v, str) else _q(v)
        if t == "p":
            entities = self.resolver.entities_for_attr(op.get("d", []), op.get("a"), ctx)
            return self._read(entities[0], op.get("a"))
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

    def _attached_nodes(self, conds: list, ctx: dict) -> list:
        """Statements hung on a condition itself (`ts` true / `fs` false).

        These were read by NOTHING until 2026-08-01 — the compiler opened a
        condition only to find out what it TESTS, and never looked in this
        second box. Nine corpus pistons lost behaviour that way, silently,
        including the whole safety set (smoke, CO, gas, water leak, low
        battery): their alarms still fired, but the steps that build "which
        detector, what reading" live here, so the announcement went out empty.

        webCoRE runs them DURING the test — `ts` when the condition comes out
        true, `fs` when false (VERIFIED webcore-piston.groovy:7882-7886 for a
        condition, :7474-7478 for a group) — therefore BEFORE the owning if's
        own body. Emitting them ahead of the if reproduces that order.

        DIVERGENCE, deliberate and documented: webCoRE short-circuits an
        and/or group (:7452-7456), so a condition it never reaches never runs
        its attached statements. Here each one is evaluated on its own, so in
        "A and B" with A false, B's attached statements still run. webCoRE
        itself disables that optimization whenever a group holds triggers or
        nested groups, which covers the corpus cases; the gap is narrow and is
        vastly preferable to dropping the statements entirely."""
        out = []
        for c in conds or []:
            if not isinstance(c, dict):
                continue
            if c.get("t") == "group":
                kids = c.get("c") or c.get("r") or []
                out.extend(self._attached_nodes(kids, ctx))
                expr = (self._group_expr(kids, c.get("o", c.get("rop", "and")), ctx)
                        if kids else None)
            else:
                expr = None
                if c.get("ts") or c.get("fs"):
                    expr = self._condition_expr(c, ctx)
            then_nodes = self._block(c.get("ts") or [], ctx)
            else_nodes = self._block(c.get("fs") or [], ctx)
            if (then_nodes or else_nodes) and expr:
                out.append({"kind": "if", "expr": expr,
                            "then": then_nodes, "else": else_nodes})
        return out

    def _condition_expr(self, cond: dict, ctx: dict) -> str:
        co = cond.get("co")
        # was_* ops that share a branch with their is_* twin below would drop
        # the duration entirely and compile to the same code. Build the inner
        # test by RECURSING as the twin (resolve.WAS_TO_IS is the one place
        # that pairing is written down) and gate it on how long the state has
        # held. The numeric/equality was_* ops are handled in their own branch
        # further down and are excluded here so they are not gated twice.
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
        # $device is only a RUNTIME reference when nothing has bound it. Inside
        # an unrolled `each` it IS bound, to that iteration's device — and then
        # the normal path below is not just usable but required: bindings are
        # per device, so the entity holding `smoke` differs per detector, and
        # the value has to be mapped (webCoRE 'detected' -> HA 'on'). The old
        # shortcut emitted _s(_device) == 'detected', which compiled clean and
        # could never be true (2026-07-29).
        if runtime_ref == "$device" and self.resolver.local_device_vars.get("$device"):
            runtime_ref = None
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
        # How each reading is spelled in this band. `entities` is still the
        # raw entity list — some branches below need the ENTITY itself (age,
        # var_name identity), which is not the same thing as its value.
        sread = self._reads(entities, attr)
        fread = self._reads(entities, attr, numeric=True)

        # was_* asks "has this held CONTINUOUSLY for T". Where last_changed
        # can answer that exactly it is left alone (the cheap path); everywhere
        # else a watcher records when the predicate became true, because
        # last_changed restarts on every update and would never accumulate.
        # The inner test is built by RECURSING as the is_* twin, so was_* never
        # needs its own copy of any comparison — resolve.WAS_TO_IS is the one
        # place that pairing lives.
        if co in WAS_TO_IS and not last_changed_is_exact(cond):
            inner = self._condition_expr(dict(cond, co=WAS_TO_IS[co]), ctx)
            dur = self._duration_ms(cond.get("to"))
            if dur is None:
                raise NotYetImplemented(
                    f"'{co}' without a fixed duration not compiled yet", **ctx)
            at_least = (cond.get("to") or {}).get("f", "g") == "g"
            # Same identity function as the YAML band, so the two bands agree
            # about which comparisons are the same comparison.
            slug = was_watcher_entity(self.piston_id, entities, attr, co,
                                      ro.get("c"),
                                      ro2.get("c")).split("_")[-1]
            self.was_watchers.setdefault(slug, {
                "slug": slug,
                "watch": ", ".join(_q(e) for e in entities),
                "predicate": inner,
                "describe": f"{attr} {co.replace('_', ' ')}",
            })
            return f"_was_held({_q(slug)}, {inner}, {dur}, {at_least})"


        if co in _NUMERIC_OPS or (co in ("rises_above", "drops_below")):
            op = _NUMERIC_OPS.get(co) or (">" if co == "rises_above" else "<")
            parts = [f"({r} is not None and {r} {op} {value})"
                     for r in fread]
        elif co == "is_between" and _is_number(value) and _is_number(ro2.get("c")):
            parts = [f"({r} is not None and {value} <= {r} <= {ro2.get('c')})"
                     for r in fread]
        elif co in _EQUALITY_OPS:
            op = _EQUALITY_OPS[co]
            if _is_number(value):
                parts = [f"({r} is not None and {r} {op} {value})"
                         for r in fread]
            else:
                mapped = self.resolver.ha_state_value(attr, value)
                parts = [f"{r} {op} {_q(mapped)}" for r in sread]
        elif co in ("changes_to",):
            # current-state approximation of the originating event (Tier-3)
            mapped = self.resolver.ha_state_value(attr, value)
            parts = [f"{r} == {_q(mapped)}" for r in sread]
        elif co == "changes_away_from":
            mapped = self.resolver.ha_state_value(attr, value)
            parts = [f"{r} != {_q(mapped)}" for r in sread]
        elif co == "changes":
            ids = ", ".join(_q(e) for e in entities)
            parts = [f"(var_name is None or var_name in ({ids},))"]
        elif co in ("is_any_of", "is_not_any_of", "is_any", "was_any_of", "was_not_any_of"):
            vals = value if isinstance(value, list) else [value]
            opts = ", ".join(_q(self.resolver.ha_state_value(attr, v)) for v in vals)
            neg = "not " if "not" in co else ""
            parts = [f"({neg}{r} in ({opts},))" for r in sread]
        elif co in ("is_even", "is_odd", "was_even", "was_odd"):
            want = 0 if co.endswith("even") else 1
            parts = [f"({r} is not None and int({r}) % 2 == {want})"
                     for r in fread]
        elif co in ("is_not_between", "is_outside_of_range", "was_outside_of_range"):
            v2 = ro2.get("c")
            # fail-closed: an unavailable sensor must NOT satisfy an
            # outside-range check (was a fail-open `is None or` — review 2026-07-20)
            parts = [f"({r} is not None and not ({value} <= {r} <= {v2}))"
                     for r in fread]
        elif co in ("is_inside_of_range", "was_inside_of_range"):
            v2 = ro2.get("c")
            parts = [f"({r} is not None and {value} <= {r} <= {v2})"
                     for r in fread]
        elif co == "is_different_than":
            parts = [f"{r} != {_q(self.resolver.ha_state_value(attr, value))}"
                     for r in sread]
        elif co in ("changed", "did_not_change"):
            ids = ", ".join(_q(e) for e in entities)
            neg = "not " if co == "did_not_change" else ""
            parts = [f"({neg}(var_name in ({ids},)))"]
        elif co in ("was_greater_than", "was_greater_than_or_equal_to",
                    "was_less_than", "was_less_than_or_equal_to",
                    "was_equal_to", "was_different_than"):
            # "was X for T". The comment here used to say "current state +
            # age", but the age was never emitted — the duration was dropped
            # outright, so `was_less_than 50 for 10 minutes` answered "is below
            # 50 right now". That is why was_* and is_* compiled to identical
            # code (Round E collision check, 2026-08-04).
            OPS = {"was_greater_than": ">", "was_greater_than_or_equal_to": ">=",
                   "was_less_than": "<", "was_less_than_or_equal_to": "<=",
                   "was_equal_to": "==", "was_different_than": "!="}
            op = OPS[co]
            dur = self._duration_ms(cond.get("to"))
            if dur is None:
                raise NotYetImplemented(
                    f"'{co}' without a fixed duration not compiled yet", **ctx)
            qual = ">=" if (cond.get("to") or {}).get("f", "g") == "g" else "<"
            # APPROXIMATE for the numeric ops, and knowingly so: _fn_age is
            # last_changed, which resets on EVERY update — so a fridge going
            # 11° -> 12° restarts the clock even though it stayed above 10.
            # It under-reports the duration, so it fails CLOSED. The YAML band
            # answers this exactly via a watcher helper
            # (emit_yaml._was_condition); doing the same here needs a persisted
            # pyscript state variable — see COMPILER_TODO.md.
            age = f"(_fn_age({{e}}) or 0) {qual} {dur}"
            if op in ("==", "!="):
                parts = [f"({r} {op} {_q(self.resolver.ha_state_value(attr, value))}"
                         f" and " + age.format(e=_q(e)) + ")"
                         for e, r in zip(entities, sread)]
            else:
                parts = [f"({r} is not None and {r} {op} {value}"
                         f" and " + age.format(e=_q(e)) + ")"
                         for e, r in zip(entities, fread)]
        elif co in ("stays_greater_than", "stays_greater_than_or_equal_to",
                    "stays_less_than", "stays_less_than_or_equal_to",
                    "remains_above", "remains_below"):
            OPS = {"stays_greater_than": ">", "stays_greater_than_or_equal_to": ">=",
                   "stays_less_than": "<", "stays_less_than_or_equal_to": "<=",
                   "remains_above": ">", "remains_below": "<"}
            op = OPS[co]
            hold = _hold_seconds(cond.get("to")) or 0
            parts = [f"({r} is not None and {r} {op} {value} and "
                     f"(_fn_age({_q(e)}) or 0) >= {hold * 1000})"
                     for e, r in zip(entities, fread)]
        elif co in ("stays", "stays_equal_to", "stays_any_of"):
            vals = value if isinstance(value, list) else [value]
            opts = ", ".join(_q(self.resolver.ha_state_value(attr, v)) for v in vals)
            hold = _hold_seconds(cond.get("to")) or 0
            parts = [f"({r} in ({opts},) and "
                     f"(_fn_age({_q(e)}) or 0) >= {hold * 1000})"
                     for e, r in zip(entities, sread)]
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
            parts = [f"({r} {eq} {_q(mapped)} and "
                     f"(_fn_age({_q(e)}) or 0) {qual} {dur})"
                     for e, r in zip(entities, sread)]
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
                spec = _daily_time_spec(cond.get("ro") or {})
                if spec:
                    self.decorators.append(
                        {"kind": "time_trigger", "spec": spec, "stmt_id": sid})
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

        # A reading that lives in a FIELD has to be named as one in the trigger
        # expression, or the trigger watches the entity's STATE — a thermostat
        # temperature trigger would fire on mode changes and compare against
        # "heat" (2026-07-30; same bug as the reads, one path over).
        # DOMAIN.name.attr is pyscript's documented form, and "attributes
        # maintain their original type", so the float()/unknown guards the
        # branches below already apply stay valid.
        refs, scales = [], []
        for e in entities:
            field, scale = self.resolver.read_spec(e, attr) if attr else (None, None)
            refs.append(f"{e}.{field.split('[')[0]}" if field else e)
            scales.append(scale)
        scale = next((s for s in scales if s), None)
        if scale and len(set(scales)) > 1:
            raise NotYetImplemented(
                f"'{attr}' needs a different unit conversion on each of these "
                f"devices — one trigger can't carry both", **ctx)
        if scale:
            # Convert the THRESHOLD into HA's units rather than the reading
            # into webCoRE's. Doing the arithmetic in the trigger expression
            # would raise on a null attribute (a light that is off has no
            # brightness); moving a constant is exact and can't blow up.
            mult, div = self.resolver.scale_factors(scale, f" on {attr}")
            def _to_ha(v):
                try:
                    return float(v) * div / mult
                except (TypeError, ValueError):
                    return v
            value, value2 = _to_ha(value), _to_ha(value2)

        def mv(v):
            return self.resolver.ha_state_value(attr, v)

        # "stays/remains X for N" -> PyScript's native state_hold (research §3:
        # the docs' own definition of state_hold IS webCoRE's `stays`)
        STAYS_EQ = ("stays", "stays_equal_to")
        if co in STAYS_EQ and hold:
            self._add_state_trigger([f"{e} == {_q(mv(value))}" for e in refs],
                                    sid, True, hold)
            return
        if co == "stays_any_of" and hold:
            vals = value if isinstance(value, list) else [value]
            opts = ", ".join(_q(mv(v)) for v in vals)
            self._add_state_trigger([f"{e} in ({opts},)" for e in refs],
                                    sid, True, hold)
            return
        if co in ("stays_away_from", "stays_different_than") and hold:
            self._add_state_trigger([f"{e} != {_q(mv(value))}" for e in refs],
                                    sid, True, hold)
            return
        if co == "stays_unchanged" and hold:
            self._add_state_trigger(list(refs), sid, False, hold)
            return
        NUM_HOLD = {"stays_greater_than": ">", "stays_greater_than_or_equal_to": ">=",
                    "stays_less_than": "<", "stays_less_than_or_equal_to": "<=",
                    "remains_above": ">", "remains_above_or_equal_to": ">=",
                    "remains_below": "<", "remains_below_or_equal_to": "<="}
        if co in NUM_HOLD:
            op = NUM_HOLD[co]
            self._add_state_trigger(
                [f"{e} is not None and {e} not in ('unknown','unavailable') "
                 f"and float({e}) {op} {value}" for e in refs], sid, True, hold)
            return
        if co in ("changes_to_any_of", "changes_away_from_any_of"):
            vals = value if isinstance(value, list) else [value]
            opts = ", ".join(_q(mv(v)) for v in vals)
            inop = "in" if co == "changes_to_any_of" else "not in"
            self._add_state_trigger([f"{e} {inop} ({opts},)" for e in refs],
                                    sid, True)
            return
        if co in ("rises", "rises_to_or_above"):
            self._add_state_trigger(
                [f"{e} is not None and {e} not in ('unknown','unavailable') "
                 f"and float({e}) >= {value}" for e in refs], sid, True)
            return
        if co in ("drops", "drops_to_or_below"):
            self._add_state_trigger(
                [f"{e} is not None and {e} not in ('unknown','unavailable') "
                 f"and float({e}) <= {value}" for e in refs], sid, True)
            return
        if co in ("enters_range", "exits_range", "remains_inside_of_range",
                  "stays_inside_of_range", "remains_outside_of_range",
                  "stays_outside_of_range") and _is_number(value) and _is_number(value2):
            inside = "outside" not in co
            body = (f"{value} <= float({{e}}) <= {value2}" if inside
                    else f"not ({value} <= float({{e}}) <= {value2})")
            self._add_state_trigger(
                [f"{e} is not None and {e} not in ('unknown','unavailable') and "
                 + body.replace("{e}", e) for e in refs], sid, True,
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
                 f"and int(float({e})) % 2 == {want}" for e in refs], sid, True,
                hold if ("remains" in co or "stays" in co) else None)
            return
        if co == "changes_to":
            mapped = self.resolver.ha_state_value(attr, value)
            self._add_state_trigger([f"{e} == {_q(mapped)}" for e in refs], sid, True)
        elif co == "changes":
            self._add_state_trigger(list(refs), sid, False)
        elif co == "changes_away_from":
            mapped = self.resolver.ha_state_value(attr, value)
            self._add_state_trigger([f"{e} != {_q(mapped)}" for e in refs], sid, True)
        elif co in ("rises_above", "drops_below"):
            op = ">" if co == "rises_above" else "<"
            self._add_state_trigger(
                [f"{e} is not None and {e} not in ('unknown', 'unavailable') "
                 f"and float({e}) {op} {value}" for e in refs], sid, True)
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
        lo3 = stmt.get("lo3") or {}
        at = lo2.get("c") if lo2.get("vt") == "time" and _is_number(lo2.get("c")) else None
        if unit in ("s", "m", "h"):
            om = lo.get("om") or 0
            start = f"00:{int(om):02d}:00" if unit == "h" and om else "00:00:00"
            spec = f"period({start}, {interval}{unit})"
        elif unit == "d" and interval == 1 and _daily_time_spec(lo2, lo3):
            # Fixed clock time OR a sun preset (with its offset) — the one
            # helper answers all of them. This used to read only the NUMBER, so
            # "every day at sunrise" fell past here into the multi-day branch
            # below and became a midnight period() timer with the sun event
            # silently discarded.
            spec = _daily_time_spec(lo2, lo3)
        elif unit == "d" and interval == 1 and lo2.get("s"):
            # The anchor IS a sun event, so the only way to get here is an
            # offset that isn't a fixed duration (an expression or variable).
            # Refuse rather than fire at plain sunrise and look correct.
            raise NotYetImplemented(
                f"'every day at {lo2['s']}' with a computed offset — the "
                f"offset must be a fixed duration", **ctx)
        elif unit in ("d", "w"):
            if lo2.get("s"):
                # A sun event on a MULTI-day cycle. once() repeats daily and
                # period() cannot express a sun event at all, so there is no
                # honest spelling for it — raise rather than drop the preset
                # and emit a plain clock timer, which is what happened before.
                raise NotYetImplemented(
                    f"'every {interval}{unit} at {lo2['s']}' — a sun event on a "
                    f"multi-day cycle has no PyScript time spec", **ctx)
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
                self._add_state_trigger([self.mode_entity], sid, False)
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
            if task.get("cm") and "." in str(cmd):
                # CUSTOM command whose name is an HA service, offered straight
                # from the device. The DOT is the discriminator, not the cm
                # flag — webCoRE also sets cm on commands it does know when the
                # original hub's driver advertised them, and those keep their
                # normal translation. (See emit_yaml._custom_service for why
                # parameters are refused rather than guessed at.)
                if params:
                    raise NotYetImplemented(
                        f"'{cmd}' was given parameters, and custom commands can't "
                        f"carry them yet — webCoRE stores them by position, and a "
                        f"Home Assistant update that adds a field would silently "
                        f"move them", **ctx)
                dom, svc = str(cmd).split(".", 1)
                out.append({"kind": "service", "domain": dom, "service": svc,
                            "entities": self.resolver.entities_for_domain(devices, dom, ctx),
                            "data": {}})
            elif cmd == "wait":
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
                    spec = self.resolver.ha_spec("speak", ctx)
                    dom, svc = spec["service"].split(".", 1)
                    slots = {"$target": repr(players), "$1": f"str({msg})"}
                    out.append({"kind": "service", "domain": dom, "service": svc,
                                "entities": [engine],
                                "data": {k: slots.get(v, "True" if v is True else v)
                                         for k, v in spec["data"].items()}})
                else:
                    nspec = self.resolver.ha_spec(cmd, ctx)
                    ndom, nsvc = nspec["service"].split(".", 1)
                    out.append({"kind": "service", "domain": ndom,
                                "service": nsvc, "entities": [],
                                "data": {next(iter(nspec["data"])): f"str({msg})"}})
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
                    # The editor's variable field was left blank, so there is
                    # nothing to assign — webCoRE has no variable to write and
                    # simply does nothing. COMPILE AND FLAG rather than fail
                    # the piston over one empty field (Jeremy, 2026-08-01).
                    self.resolver.unresolved.append(
                        {"label": "setVariable", "for": "variable name",
                         "kind": "blank", "entity": None})
                    continue
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
                # DECLARED TYPE first. `"false"` is truthy in Python exactly
                # as in Jinja, so a boolean left as text silently inverts
                # `if <var>` here too (VARIABLES_SPEC §4). The DECISION is
                # shared with the YAML band via resolve.typed_value; only the
                # literal FORMAT differs — Python spells it True, YAML true.
                # Do NOT reach for the YAML band's formatter: that is how a
                # Jinja template ended up inside a PyScript module.
                from .resolve import typed_value
                _vop = params[1] if len(params) > 1 else {"t": "c", "c": None}
                _decl = getattr(self.resolver, "local_var_decls", {}).get(str(name))
                _typed = typed_value(_vop, _decl)
                value_expr = (repr(_typed) if _typed is not None
                              else self._operand_expr(_vop, ctx))
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
                spec = self.resolver.ha_spec(cmd, ctx)
                dom, svc = spec["service"].split(".", 1)
                slots = {"$target": repr(players), "$1": f"str({msg})"}
                out.append({"kind": "service", "domain": dom, "service": svc,
                            "entities": [engine],
                            "data": {k: slots.get(v, "True" if v is True else v)
                                     for k, v in spec["data"].items()}})
            elif cmd == "setLocationMode":
                mode = (params[0] or {}).get("c") if params else None
                if not isinstance(mode, str):
                    raise NotYetImplemented("setLocationMode with non-constant mode", **ctx)
                mode_ent = self.resolver.system_entity("mode") or self.mode_entity
                spec = self.resolver.command_ha_entry("setLocationMode", ctx)
                svc_domain, svc = spec["service"].split(".", 1)
                field = next(iter(spec["data"]))
                out.append({"kind": "service", "domain": svc_domain,
                            "service": svc, "entities": [mode_ent],
                            "data": {field: repr(mode)}})
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
                        f"(add it under setAlarmSystemStatus in webcore_vocab.json)", **ctx)
                svc_domain = self.resolver.command_ha_entry(
                    "setAlarmSystemStatus", ctx)["service_domain"]
                out.append({"kind": "service", "domain": svc_domain,
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
            elif cmd in ("pausePiston", "resumePiston"):
                # Was refused outright on this band, which is a hole in the
                # valve: forcing PyScript is a user's CHOICE for trace fidelity,
                # so a piston it cannot compile is a fallback bug, not a
                # limitation of the piston.
                #
                # Same compile-time lookup and the same refusals as the YAML
                # band (resolve.pause_target_automations), so both bands accept
                # and reject exactly the same pistons.
                _, auto_ids = pause_target_automations(cmd, params)
                service = self.resolver.command_ha_entry(cmd, ctx)["service"]
                svc_domain, svc_name = service.split(".", 1)
                out.append({
                    "kind": "service", "domain": svc_domain, "service": svc_name,
                    "entities": [],
                    "data": {"entity_id": f"_piston_automations({auto_ids!r})"}})
            elif cmd in ("cancelTasks", "cancelPendingTasks"):
                # restart execution model already kills pending waits on
                # retrigger (research §6) — breadcrumb only (Tier-3 caveat)
                out.append({"kind": "log",
                            "msg": _q(f"[{self.piston_id}] cancelTasks: no-op under "
                                      f"restart execution model")})
            elif cmd in _routing.piston_scope_commands():
                raise NotYetImplemented(f"piston-scope command '{cmd}' not compiled yet", **ctx)
            else:
                if not devices:
                    raise NotYetImplemented(
                        f"command '{cmd}' with no target devices", **ctx)
                _bound_each = ("$device" in [str(d) for d in devices]
                               and self.resolver.local_device_vars.get("$device"))
                if not _bound_each and any(
                        str(d) in ("$device", "$currentEventDevice") for d in devices):
                    var = "_device" if "$device" in [str(d) for d in devices] else "var_name"
                    svc = {"on": "turn_on", "off": "turn_off", "toggle": "toggle"}.get(cmd)
                    if not svc:
                        raise NotYetImplemented(
                            f"command '{cmd}' on a runtime device reference "
                            f"isn't compiled yet", **ctx)
                    out.append({"kind": "raw", "code":
                                f"service.call('homeassistant', '{svc}', entity_id={var})"})
                    continue
                # DRIVER command (take, clearImages, selectLiveview): a name
                # only the device's own driver knows, which HA has no
                # vocabulary for. Same decision the YAML band makes — is this
                # a vocab command on this device, and if not does the
                # integration offer a passthrough — just spelled for PyScript.
                if (not self.resolver.has_command_binding(devices, cmd, ctx)
                        and self.resolver.passthrough(devices, ctx)):
                    out.append(self._driver_command(cmd, devices, params, ctx))
                    continue
                try:
                    entities = self.resolver.entities_for_command(devices, cmd, ctx)
                    service, data_spec = self.resolver.service_spec(cmd, entities[0], ctx)
                    domain, svc = service.split(".", 1)
                    # Vocab-declared: this command may jump to a starting value
                    # before it fades. Popped BEFORE the data is built, or it
                    # would be sent to HA as an invented service field.
                    # READ, never popped — see the YAML band: this is the
                    # vocab's own cached dict, shared by every piston.
                    fade_from = (data_spec or {}).get("fade_from")
                    data_spec = {k: v for k, v in (data_spec or {}).items()
                                 if k != "fade_from"}
                    data = {}
                    if data_spec:
                        # Inside the try: an unfillable data spec is the
                        # "vocab mapping unusable on this device" signal. A
                        # blank value raises PistonDefect, which this except
                        # deliberately does not catch.
                        # _spec_data, not _param_value: an OPTIONAL parameter
                        # the piston left unset must be OMITTED, not converted.
                        # Jeremy's rule for volume specifically — "the default
                        # is keep what is there and don't send a new one" —
                        # which is exactly what dropping the key does.
                        data = self._spec_data_py(
                            data_spec, params, ctx,
                            entity=(entities[0] if entities else None))
                except NotYetImplemented:
                    # in the vocab, but unreachable on THIS device (a bridged
                    # camera has no camera entity to call `take` on)
                    if self.resolver.passthrough(devices, ctx):
                        out.append(self._driver_command(cmd, devices, params, ctx))
                        continue
                    raise
                # Hue-only / saturation-only. HA's hs_color is a PAIR, so a
                # bare number is rejected outright — which is what this emitted
                # before. One call per light, because each has its own current
                # colour to preserve. Matches the YAML band exactly.
                keep = next((("saturation" if "|hue_hs" in str(tok) else "hue")
                             for tok in (data_spec or {}).values()
                             if "|hue_hs" in str(tok) or "|sat_hs" in str(tok)),
                            None)
                if keep and data and entities:
                    key = next(iter(data))
                    asked = data[key]
                    for ent in entities:
                        out.append({
                            "kind": "service", "domain": domain, "service": svc,
                            "entities": [ent],
                            "data": dict(data, **{
                                key: f"_hs_keep({ent!r}, {asked}, {keep!r})"})})
                    continue
                if fade_from and data:
                    # HA cannot express a start and an end in one call, so the
                    # jump is a separate call placed ahead of the fade — same
                    # shape the YAML band emits.
                    start = self._spec_data_py(
                        {k: fade_from for k in data if k != "transition"},
                        params, ctx, entity=(entities[0] if entities else None))
                    if start:
                        out.append({"kind": "service", "domain": domain,
                                    "service": svc, "entities": entities,
                                    "data": start})
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
            # attached statements run during the TEST, so they precede the body
            prelude = self._attached_nodes(stmt.get("c", []), ctx)
            node = {"kind": "if",
                    "expr": self._group_expr(stmt.get("c", []), stmt.get("o", "and"), ctx),
                    "then": self._block(stmt.get("s", []), ctx),
                    "else": self._block(stmt.get("e", []), ctx)}
            for ei in reversed(stmt.get("ei") or []):
                node["else"] = [{"kind": "if",
                                 "expr": self._group_expr(ei.get("c", []), ei.get("o", "and"), ctx),
                                 "then": self._block(ei.get("s", []), ctx),
                                 "else": node["else"]}]
                prelude = self._attached_nodes(ei.get("c", []), ctx) + prelude
            return prelude + [node]
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
            # `each` over a VARIABLE holding the device list (lo.t == "x", the
            # name in lo.x) is the same loop as lo.t == "d" — webCoRE just
            # records the list by reference instead of inline, and the resolver
            # resolves a device-variable NAME exactly like a hash. Surfaced
            # 2026-08-01: these loops sit inside condition-attached statements,
            # so nothing ever compiled them until those started being read.
            drefs = lo.get("d")
            if lo.get("t") == "x" and lo.get("x"):
                drefs = [lo["x"]] if not isinstance(lo["x"], list) else lo["x"]
            if lo.get("t") in ("d", "x") and drefs:
                hashes = []
                for dref in drefs:
                    hashes.extend(self.resolver._hashes(str(dref), ctx))
                # UNROLL: emit the body once per device, with $device bound to
                # that device. Two reasons this is the right shape, not a
                # shortcut (2026-07-29, from Jeremy's smoke pistons):
                #
                # 1. It's the only CORRECT one. Bindings are per device — each
                #    detector's `smoke` lives on its own entity — so a runtime
                #    loop over a flat entity list can't know which entity holds
                #    which reading for the device it's currently on.
                # 2. The old code resolved each device to a CONTROLLABLE entity
                #    (on/off/lock/...) and gave up when there wasn't one. That
                #    assumed `each` means "do something to these devices". It
                #    equally means "ask each of these devices something", which
                #    is what a smoke-detector loop does — and a smoke detector
                #    has nothing controllable, so those pistons died on a
                #    premise that was never true.
                #
                # Freezing the list at compile time matches the standing rule
                # that capability resolution is compile-time and recompiling is
                # the refresh (no runtime PistonCore dependency).
                if not hashes:
                    raise NotYetImplemented("'each' over an empty device list", **ctx)
                # NO CAP on device count, deliberately. There was a bare
                # `> 50` here; traced to commit 95fdaf9 (2026-07-29), added
                # inside an unrelated change with no reason given, and NO HA
                # limit backs it — HA caps neither actions per automation nor
                # anything else relevant, and this band emits plain Python. It
                # failed a 61-sensor battery report, an ordinary size for a
                # whole-house check. A compile error needs a verified reason it
                # cannot be done (COMPILER_SPEC §5); an invented number is not
                # one.
                #
                # Note this is NOT the answer to "the loop is big" — the
                # intent-based path resolves an accumulate-and-announce loop to
                # ONE HA template (accumulate.j2) and is preferred wherever the
                # shape is recognised. Unrolling is the fallback for loops that
                # genuinely need per-device bindings.
                out = []
                had = "$device" in self.resolver.local_device_vars
                prev = self.resolver.local_device_vars.get("$device")
                try:
                    for h in hashes:
                        self.resolver.local_device_vars["$device"] = [h]
                        out.extend(self._block(stmt.get("s", []), ctx))
                finally:
                    if had:
                        self.resolver.local_device_vars["$device"] = prev
                    else:
                        self.resolver.local_device_vars.pop("$device", None)
                return out
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

        # STAGE 1 (SESSION_BRIEF_ONE_READER_ONE_WRITER §3): the top-level
        # statement list is DISCOVERED by the shared reader, not walked again
        # here. This is the layer every silent drop lived in — a statement kind
        # one band knew about and the other didn't — so it is the layer that
        # has to be read once.
        #
        # Each branch still carries `raw`, the untouched statement, and the
        # emit code below reads operands from it exactly as before. Discovery
        # is shared; emission stays per-band (§Stage 2b: the bands must NOT
        # share an emission helper).
        for branch in analyze(self.piston, self.piston_id, self.piston_name):
            stmt = branch["raw"]
            sid = branch["stmt_id"]
            ctx = self._ctx(sid)
            t = branch["stmt_type"]
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
        var_exprs = []
        for v in self.piston.get("v", []):
            if v.get("t") == "device":
                continue
            init = v.get("v")
            if isinstance(init, dict):
                # An EXPRESSION initializer (`t: "x"`), not a constant: the
                # piston declared `hsm_status = $hsmStatus`. Only `.c`
                # (constants) was ever read, so every expression-initialized
                # variable compiled to None and the piston went on to notify
                # with the literal string "None" (2026-07-30, found in
                # 81_test). Evaluated per run, in the event body, because the
                # expression can read entity state that changes.
                if init.get("t") in ("x", "e", "u") and (
                        init.get("x") or init.get("e") or init.get("u")):
                    try:
                        var_exprs.append({
                            "name": repr(v["n"]),
                            "value": self._operand_expr(init, self._ctx(None))})
                        variables[v["n"]] = None
                        continue
                    except NotYetImplemented:
                        # keep the old behaviour for expressions this band
                        # can't transpile rather than failing the whole piston
                        pass
                init = init.get("c")
            variables[v["n"]] = init if isinstance(init, (str, int, float, bool)) else None

        # compile-time snapshot of every @global the expressions read
        global_values = {}
        for name in sorted(self.expr.used_globals):
            g = self.globals_map_value(name)
            global_values[name] = g
        # expression-initialized variables assign at the TOP of each run, so
        # the piston body sees them already computed
        if var_exprs:
            event_body = [{"kind": "setvar", "name": e["name"], "value": e["value"]}
                          for e in var_exprs] + list(event_body)
        # Piston-level restrictions ("only execute if ...") gate EVERY statement,
        # so they wrap the whole body rather than any one statement — the same
        # shape _stmt_nodes uses for a statement's own restrictions: one `if`
        # with NO else, because a failed restriction runs nothing at all.
        #
        # Applied to BOTH bodies. `guarded` holds the every/on bodies, which are
        # reached by their own decorators and never pass through event_body — so
        # gating only event_body would leave a scheduled statement running while
        # the piston is restricted, which is the silent-bypass this used to
        # hard-fail rather than risk.
        rest = self.piston.get("r") or []
        if rest:
            if self.piston.get("rn"):
                # "except when ..." — same reasoning as the statement-level
                # case: dropping a gate silently is worse than not compiling.
                raise NotYetImplemented(
                    "negated piston-level restriction set ('rn') not compiled yet",
                    piston_id=self.piston_id, piston_name=self.piston_name,
                    stmt_id=None)
            gate = self._group_expr(rest, self.piston.get("rop", "and"),
                                    self._ctx(None))
            if event_body:
                event_body = [{"kind": "if", "expr": gate,
                               "then": event_body, "else": []}]
            for g in guarded:
                if g.get("body"):
                    g["body"] = [{"kind": "if", "expr": gate,
                                  "then": g["body"], "else": []}]

        return {"decorators": self.decorators, "event_body": event_body,
                "guarded": guarded, "variables": variables,
                "was_watchers": sorted(self.was_watchers.values(),
                                      key=lambda w: w["slug"]),
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

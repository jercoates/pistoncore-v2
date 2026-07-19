"""webCoRE EXPRESSION ENGINE — parser port + python transpiler.

PARSER: line-faithful port of the dashboard's own parser
(piston.module.js:5226-5512 parseExpression / :5222 parseString) — the same
code that produces the `exp` trees live saves embed. When a saved operand
already carries `exp` (dashboard writes it at serialize time,
piston.module.js:4799-4808; anonymized bin exports strip it), that tree is
used as-is and this parser is only the fallback for bin imports / corpus /
AI-authored JSON.

SEMANTICS: per the engine's evaluateExpression (webcore-piston.groovy
:10497+): operand/operator fixups (implicit ZERO before leading unary
+,-,!,...; adjacent operands default to '+' for strings and '*' for numbers
— groovy :10700-10724), ternary as the 3-item ?/: special case (:10729),
and the exact operator precedence table opPriorityFLD (:10449-10461).

TRANSPILE TARGET: python for the PyScript band. Value coercion happens at
RUNTIME via the band's expr_runtime helpers (_op/_cast/...), matching
webCoRE's dynamic typing — the transpiler only fixes STRUCTURE (precedence,
arity), never types. The YAML band routes expression-bearing pistons to
PyScript (COMPILER_DECISIONS_HOLDING session-3 note).
"""

import re

from .errors import NotYetImplemented

# opPriorityFLD verbatim (groovy :10449-10461); lower tier binds tighter
_PRECEDENCE = {
    "!": 2, "!!": 2, "~": 2,
    "**": 3,
    "*": 4, "/": 4, "\\": 4, "%": 4,
    "+": 5, "-": 5,
    "<<": 6, ">>": 6,
    ">": 7, "<": 7, ">=": 7, "<=": 7,
    "==": 8, "!=": 8, "<>": 8,
    "&": 9,
    "^": 10,
    "|": 11,
    "&&": 12, "!&": 12,
    "^^": 13, "!^": 13,
    "||": 14, "!|": 14,
}
# leading-operator implicit-zero set (groovy L1opt, :10464)
_L1OPT = {"+", "-", "**", "&", "|", "^", "~", "<", ">", "<=", ">=", "==",
          "!=", "<>", "<<", ">>", "!", "!!", "?"}

_TWO_CHAR_OPS = ["**", "&&", "||", "^^", "!&", "!|", "!^", "==", "!=", "!!",
                 ">=", "<=", "<>", "<<", ">>"]

_NUM_RE = re.compile(r"^-?(0(\.\d*)?|([1-9]\d*\.?\d*)|(\.\d+))([Ee][+-]?\d+)?$")
_ESCAPE_RE = re.compile(r"\\[\[\]\{\}\'\"0-9abcdefghijklmopqsuvwxyz]", re.I)

_COMPOSITE_PREFIXES = ("$args.", "$json.", "$response.", "$nfl.", "$places.",
                      "$weather.", "$twcweather.", "$incidents.",
                      "$args[", "$json[", "$places[", "$response[", "$incidents[")

_NUMERIC_TYPES = {"integer", "decimal"}
_STRING_TYPES = {"string", "boolean", "dynamic"}


def parse_string(s: str, array_vars=None) -> dict:
    """Interpolated-string mode (parseString): literal text with {expr} blocks."""
    return parse_expression(s, parse_as_string=True, array_vars=array_vars)


def parse_expression(s, parse_as_string: bool = False, device_lookup=None,
                     array_vars=None) -> dict:
    """Port of piston.module.js:5226 parseExpression. device_lookup:
    optional callable(display_name) -> device hash (the dashboard resolves
    [Device Name : attr] via getDeviceByName; the shim resolves via the
    resolution map's names). Unresolved names become device-variable refs
    ({t:'device', x:name}) exactly like the original."""
    s = "" if s is None else str(s)
    state = {"i": 0, "func": 0, "parenthesis": 0, "osq": False, "odq": False}
    init_exp = 0 if parse_as_string else 1
    exp_depth = {"exp": init_exp}

    arrays = array_vars or set()

    def is_composite(start):
        if s[start:].startswith(_COMPOSITE_PREFIXES):
            return True
        rest = s[start:]
        for n in arrays:
            if rest.startswith(n + "["):
                return True
        return False

    def main():
        arr = []
        sq = dq = dv = False
        start = state["i"]

        def add_operand():
            nonlocal start
            i = state["i"]
            if i - 1 > start:
                value = s[start:i - 1].strip()
                if _NUM_RE.match(value):
                    num = float(value)
                    arr.append({"t": "decimal" if "." in value else "integer",
                                "v": num if "." in value else int(num)})
                    return True
                if value in ("true", "false"):
                    arr.append({"t": "boolean", "v": value})
                elif value == "null":
                    arr.append({"t": "dynamic", "v": None})
                else:
                    arr.append({"t": "variable", "x": value})
                return True
            return False

        def add_constant(allow_empty=False):
            i = state["i"]
            if i - (0 if allow_empty else 1) > start:
                value = _ESCAPE_RE.sub(lambda m: m.group(0)[1], s[start:i - 1])
                if _NUM_RE.match(value.strip()):
                    num = float(value.strip())
                    arr.append({"t": "decimal" if "." in value else "integer",
                                "v": num if "." in value else int(num)})
                    return
                if value in ("true", "false"):
                    arr.append({"t": "boolean", "v": value})
                else:
                    arr.append({"t": "string", "v": None if value == "null" else value})

        def add_device():
            i = state["i"]
            if i - 1 > start:
                value = s[start:i - 1]
                pos = value.rfind(":")
                name, attr = value, ""
                if pos > 0:
                    name = _ESCAPE_RE.sub(lambda m: m.group(0)[1], value[:pos].strip())
                    attr = value[pos + 1:].strip()
                dev_id = device_lookup(name) if device_lookup else None
                if dev_id:
                    arr.append({"t": "device", "id": dev_id, "a": attr})
                else:
                    arr.append({"t": "device", "x": name, "a": attr})

        def add_function():
            nonlocal start
            i = state["i"]
            value = s[start:i - 1].lower().strip()
            if value and re.match(r"^[a-z_][a-z0-9_]*$", value):
                state["func"] += 1
                params = main()
                items, item = [], None
                for p in params:
                    if item is None:
                        item = {"t": "expression", "i": []}
                    if p.get("t") == "operator" and p.get("o") == ",":
                        items.append(item)
                        item = {"t": "expression", "i": []}
                    else:
                        item["i"].append(p)
                if item is not None:
                    items.append(item)
                arr.append({"t": "function", "n": value, "i": items})
                state["func"] -= 1
            else:
                add_operand()
                arr.append({"t": "expression", "i": main()})
                start = state["i"]

        composite = is_composite(start)
        while state["i"] < len(s):
            c = s[state["i"]]
            state["i"] += 1
            i = state["i"]
            exp = exp_depth["exp"]

            if c in " \t\r\n":
                if exp and not dv and not dq and not sq:
                    add_operand()
                    start = i
                    composite = is_composite(start)
                continue
            if c in "+-/*~^\\%&|,!=<>?:":
                c2 = s[i] if i < len(s) else ""
                if exp and not dv and not sq and not dq and not (composite and c in ".["):
                    add_operand()
                    if c + c2 in _TWO_CHAR_OPS:
                        state["i"] += 1
                        c = c + c2
                    arr.append({"t": "operator", "o": c})
                    start = state["i"]
                    composite = is_composite(start)
                elif c == "\\":
                    state["i"] += 1
                continue
            if c in "\"“”":
                if exp and not dv and not sq:
                    dq = not dq
                    state["odq"] = not state["odq"]
                    add_operand() if dq else add_constant(True)
                    start = i
                    composite = is_composite(start)
                continue
            if c in "'‘’":
                if exp and not dq and not dv:
                    sq = not sq
                    state["osq"] = not state["osq"]
                    add_operand() if sq else add_constant(True)
                    start = i
                    composite = is_composite(start)
                continue
            if c == "(":
                if exp and not dv and not dq and not sq:
                    state["parenthesis"] += 1
                    add_function()
                    start = state["i"]
                    composite = is_composite(start)
                continue
            if c == ")":
                if exp and not dv and not dq and not sq:
                    state["parenthesis"] -= 1
                    add_operand()
                    start = state["i"]
                    return arr
                continue
            if c == "[":
                if not composite and exp and not dq and not sq and not dv:
                    dv = True
                    add_operand()
                    start = i
                    composite = is_composite(start)
                continue
            if c == "]":
                if not composite and exp and dv and not dq and not sq:
                    add_device()
                    dv = False
                    start = i
                    composite = is_composite(start)
                continue
            if c == "{":
                exp_depth["exp"] += 1
                if exp == init_exp:
                    add_constant()
                else:
                    pass
                start = state["i"]
                arr.append({"t": "expression", "i": main()})
                start = state["i"]
                composite = is_composite(start)
                continue
            if c == "}":
                add_operand()
                exp_depth["exp"] -= 1
                return arr
        state["i"] += 1
        if exp_depth["exp"]:
            add_operand()
        else:
            add_constant()
        return arr

    items = main()
    result = {"t": "expression", "i": items, "str": s}
    if exp_depth["exp"] != init_exp:
        result["err"] = "Invalid expression closure termination"
    elif state["osq"]:
        result["err"] = "Invalid single quote termination"
    elif state["odq"]:
        result["err"] = "Invalid double quote termination"
    elif state["parenthesis"]:
        result["err"] = "Invalid parenthesis closure termination"
    result["ok"] = "err" not in result
    return result


# ── transpiler ──────────────────────────────────────────────────────────────

# system variables with a direct runtime mapping (expr_runtime.py.j2 helpers /
# trigger kwargs). Composite feeds ($weather, $twcweather, $response, ...)
# have no HA equivalent -> NotYetImplemented names them.
_SYSVARS = {
    "$now": "_now_ms()", "$localnow": "_now_ms()", "$utc": "_utc_ms()",
    "$time": "_sysdate('%I:%M %p')", "$time24": "_sysdate('%H:%M')",
    "$hour": "_sysnum('hour12')", "$hour24": "_sysnum('hour')",
    "$minute": "_sysnum('minute')", "$second": "_sysnum('second')",
    "$day": "_sysnum('day')", "$month": "_sysnum('month')",
    "$year": "_sysnum('year')",
    "$monthname": "_sysdate('%B')", "$dayofweekname": "_sysdate('%A')",
    "$dayofweek": "_sysnum('dow')",
    "$date": "_sysdate('%x')", "$datetime": "_now_ms()",
    "$midnight": "_daytime_ms(0, 0)", "$noon": "_daytime_ms(12, 0)",
    "$sunrise": "_sun_ms('next_rising')", "$sunset": "_sun_ms('next_setting')",
    "$currenteventdevice": "var_name", "$currenteventvalue": "value",
    "$previouseventvalue": "old_value",
    "$currenteventattribute": "var_name",
    "$index": "_index",
    "$random": "_fn_random()", "$randomlevel": "_fn_random(100)",
}


class ExprTranspiler:
    """AST (dashboard parse tree) -> python expression string. Needs the
    emitter's context to resolve locals/globals/devices."""

    def __init__(self, local_names: set, globals_map: dict, resolver, ctx: dict,
                 mode_entity: str, array_vars: set | None = None):
        self.array_vars = array_vars or set()
        self.local_names = local_names
        self.globals_map = globals_map if globals_map is not None else {}
        self.resolver = resolver
        self.ctx = ctx
        self.mode_entity = mode_entity
        self.used_globals: set = set()

    # entry points ----------------------------------------------------------

    def transpile_operand(self, op: dict) -> str:
        """Expression operand (t:'e'): prefer the dashboard-parsed exp tree
        embedded at save time; fall back to parsing the source string."""
        tree = op.get("exp")
        if not (isinstance(tree, dict) and tree.get("i") is not None):
            tree = parse_expression(op.get("e"), device_lookup=self._device_by_name,
                                    array_vars=self.array_vars)
            if not tree.get("ok"):
                raise NotYetImplemented(
                    f"expression parse error: {tree.get('err')} in "
                    f"\"{str(op.get('e'))[:60]}\"", **self.ctx)
        return self.expression(tree)

    def transpile_string(self, text: str) -> str:
        """Interpolated string constant ({expr} blocks)."""
        tree = parse_string(text, array_vars=self.array_vars)
        if not tree.get("ok"):
            raise NotYetImplemented(
                f"string parse error: {tree.get('err')} in \"{text[:60]}\"", **self.ctx)
        return self.expression(tree, concat_strings=True)

    # AST walk --------------------------------------------------------------

    def expression(self, node: dict, concat_strings: bool = False) -> str:
        items = node.get("i") or []
        # pair each operand with the operator that follows it, applying the
        # engine's fix-ups (groovy :10650-10724): implicit ZERO before a
        # leading unary-capable operator; '!'/'~' unary handling; missing
        # operators between adjacent operands default '+' (strings) /
        # '*' (numbers).
        operands = []   # list of [py_expr, op_or_None, is_string_literal]
        pending_unary = []
        for item in items:
            if item.get("t") == "operator":
                o = item.get("o")
                if o == ",":
                    raise NotYetImplemented(
                        "unexpected ',' outside function call", **self.ctx)
                if not operands or operands[-1][1] is not None:
                    # leading operator: unary
                    if o in ("!", "!!", "~", "-", "+"):
                        pending_unary.append(o)
                        continue
                    if o in _L1OPT:
                        operands.append(["0", o, False])
                        continue
                    raise NotYetImplemented(
                        f"expression operator '{o}' in unary position", **self.ctx)
                operands[-1][1] = o
            else:
                expr = self.value(item)
                for u in reversed(pending_unary):
                    if u == "!":
                        expr = f"(not _truthy({expr}))"
                    elif u == "!!":
                        expr = f"_truthy({expr})"
                    elif u == "~":
                        expr = f"(~_int({expr}))"
                    elif u == "-":
                        expr = f"_op(0, '-', {expr})"
                    # unary '+' is a no-op
                pending_unary = []
                is_str = item.get("t") in ("string",)
                if operands and operands[-1][1] is None:
                    # adjacent operands, no operator: engine default
                    operands[-1][1] = "+" if (concat_strings or is_str
                                              or operands[-1][2]) else "*"
                operands.append([expr, None, is_str])
        if pending_unary:
            raise NotYetImplemented("dangling unary operator", **self.ctx)
        if not operands:
            return "''" if concat_strings else "None"

        # ternary special case (groovy :10729): cond ? a : b at this level
        ops = [o for _, o, _ in operands if o]
        if "?" in ops:
            qi = next(i for i, (_, o, _) in enumerate(operands) if o == "?")
            ci = next((i for i, (_, o, _) in enumerate(operands)
                       if o == ":" and i >= qi), None)
            if ci is None:
                raise NotYetImplemented("ternary '?' without ':'", **self.ctx)
            cond = self._reduce(operands[:qi] + [[operands[qi][0], None, False]])
            then = self._reduce(operands[qi + 1:ci] + [[operands[ci][0], None, False]])
            els = self._reduce(operands[ci + 1:])
            return f"(({then}) if _truthy({cond}) else ({els}))"
        return self._reduce(operands)

    def _reduce(self, operands: list) -> str:
        """Precedence reduction per opPriorityFLD — leftmost highest tier."""
        operands = [list(o) for o in operands]
        while len(operands) > 1:
            best, besti = 99, 0
            for i in range(len(operands) - 1):
                o = operands[i][1]
                tier = _PRECEDENCE.get(o, 99)
                if tier < best:
                    best, besti = tier, i
            a, o, _ = operands[besti]
            b = operands[besti + 1]
            if o is None or best == 99:
                raise NotYetImplemented(
                    f"expression operator '{o}' not supported", **self.ctx)
            merged = f"_op({a}, {o!r}, {b[0]})"
            operands[besti:besti + 2] = [[merged, b[1], False]]
        return operands[0][0]

    def value(self, item: dict) -> str:
        t = item.get("t")
        if t in ("integer", "decimal"):
            return repr(item.get("v"))
        if t == "boolean":
            return "True" if item.get("v") == "true" else "False"
        if t == "string":
            return repr(item.get("v") if item.get("v") is not None else "")
        if t == "dynamic":
            return repr(item.get("v"))
        if t == "expression":
            return "(" + self.expression(item) + ")"
        if t == "variable":
            return self.variable(item.get("x"))
        if t == "device":
            return self.device(item)
        if t == "function":
            return self.function(item)
        if t == "operand":
            return repr(item.get("v"))
        raise NotYetImplemented(f"expression item type '{t}' not supported", **self.ctx)

    def variable(self, name) -> str:
        name = str(name or "")
        m = re.match(r"^([@$]?[A-Za-z_][\w]*)\s*\[(.+)\]$", name)
        if m and not name.startswith("$"):
            idx_tree = parse_expression(m.group(2), array_vars=self.array_vars)
            idx = self.expression(idx_tree)
            return f"_fn_arrayitem({idx}, {self.variable(m.group(1))})"
        if name.startswith("$"):
            low = name.lower()
            if low in _SYSVARS:
                return _SYSVARS[low]
            if low.split(".")[0].split("[")[0] in (
                    "$weather", "$twcweather", "$response", "$args", "$json",
                    "$nfl", "$places", "$incidents", "$httpstatuscode"):
                raise NotYetImplemented(
                    f"system variable '{name}' has no HA equivalent (external "
                    f"data feed) — fetch it into an HA sensor instead", **self.ctx)
            raise NotYetImplemented(
                f"system variable '{name}' not compiled yet", **self.ctx)
        if name.startswith("@"):
            if name in self.globals_map:
                self.used_globals.add(name)
                return f"_gv({name!r})"
            raise NotYetImplemented(
                f"global variable '{name}' not found (create it in the Global "
                f"variables panel)", **self.ctx)
        if name in self.local_names:
            return f"pv.get({name!r})"
        # mode: webCoRE exposes location mode as a bare variable too
        if name == "mode":
            return f"_s({self.mode_entity!r})"
        raise NotYetImplemented(
            f"variable '{name}' is not a declared piston variable", **self.ctx)

    def device(self, item: dict) -> str:
        """[Device : attribute] — id (hash) or x (device-variable name); both
        resolve through the resolver's own dref logic."""
        attr = item.get("a") or ""
        dref = item.get("id") or item.get("x")
        if not attr or attr == "?":
            # attribute-less device ref = the device's display NAME
            if dref == "$currentEventDevice":
                return "_fname(var_name)"
            if item.get("id"):
                entry = self.resolver.resolution_map.get(item["id"]) or {}
                return repr(entry.get("name", "device"))
            if dref:
                # device VARIABLE without attribute -> its devices' display names
                hashes = self.resolver._hashes(str(dref), self.ctx)
                names = [(self.resolver.resolution_map.get(h) or {}).get("name", h)
                         for h in hashes]
                return repr(" and ".join(str(n) for n in names))
            raise NotYetImplemented(
                "device reference without a valid attribute in expression", **self.ctx)
        if dref == "$currentEventDevice":
            # the triggering entity itself — its state IS the subscribed
            # attribute's value under the one-entity-per-attribute binding
            return "_s(var_name)"
        entities = self.resolver.entities_for_attr([dref], attr, self.ctx)
        if len(entities) == 1:
            return f"_s({entities[0]!r})"
        lst = ", ".join(f"_s({e!r})" for e in entities)
        return f"[{lst}]"

    def function(self, item: dict) -> str:
        name = str(item.get("n") or "").lower()
        args = [self.expression(sub) for sub in (item.get("i") or [])]
        if name not in _FUNCTIONS:
            raise NotYetImplemented(
                f"expression function '{name}()' not compiled yet", **self.ctx)
        return f"_fn_{name}({', '.join(args)})"

    def _device_by_name(self, display_name: str):
        for h, entry in getattr(self.resolver, "resolution_map", {}).items():
            if h == "$system" or not isinstance(entry, dict):
                continue
            if str(entry.get("name", "")).lower() == display_name.lower():
                return h
        return None


# functions implemented in templates/compiler/pyscript/2.x/expr_runtime.py.j2
# (band-editable — add a function there AND list it here)
_FUNCTIONS = {
    "lower", "upper", "trim", "left", "right", "mid", "substring", "replace",
    "concat", "contains", "startswith", "endswith", "indexof", "length",
    "string", "format", "sprintf",
    "int", "integer", "decimal", "float", "number", "round", "floor", "ceil",
    "abs", "min", "max", "sum", "avg", "median", "power", "sqrt", "random",
    "isempty", "coalesce", "boolean", "bool", "isbetween",
    "count", "arrayitem", "item",
    "time", "date", "datetime", "addseconds", "addminutes", "addhours",
    "adddays", "formatdatetime", "formatduration",
    "age",
}

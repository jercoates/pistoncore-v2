"""ROUND E — the intent probe. Walks the VOCAB, not the corpus.

WHY (Jeremy, 2026-08-01): every silent compiler bug found so far was invisible
to the corpus. RESTRICTIONS were dropped on all four paths for weeks because
0 of 84 corpus pistons use them, and the intent catalog (COMPILER_SPEC §3.0)
is corpus-MINED — so anything nobody happened to write is missing from the
catalog too. The corpus can only ever prove things about what it contains.
This walks the vocabulary instead: every comparison, command, function and
statement type webCoRE can express, whether or not a real piston uses it.

METHOD LESSON, proven wrong three times before this (see the roadmap memory):
grep-based coverage counting lies in BOTH directions, and so does a compile
probe fed the WRONG operands — `stays_*` need a hold duration, range operators
need a second value, `is_before` is a time operator. Feed one a bare number and
it reports a gap that doesn't exist.

So this probe derives every operand FROM THE VOCAB'S OWN DECLARATIONS, never
from a hand-written table:
    `g`  the operator group letters -> which attribute type can sit on the left
    `p`  how many right operands (ro, ro2)
    `m`  right operand is a multi-value list
    `t`  1 = needs a hold duration (`to`), 2 = "was" lookback (also `to`)
Commands read their parameter list from the vocab's `p` the same way. If the
vocab can't tell us how to build a valid operand, the probe records NO-OPERAND
and skips it — it never guesses, because a guessed operand produces a fake
result, which is the exact failure this file exists to stop repeating.

THREE FAILURE CLASSES, and only the first one is visible to a normal test:

  ERROR      the compiler says it can't. Honest; goes on the backlog.
  COLLISION  two DIFFERENT intents compile to byte-identical output. One of
             them is being silently treated as the other — e.g. `drops_below`
             emitting what `rises_above` emits. Nothing errors; the automation
             just does the wrong thing.
  DROP       adding a modifier to a piston changes NOTHING in the output, so
             the modifier was silently discarded. This is the restrictions bug
             class, and it's the reason this file exists. Detected by compiling
             with and without the modifier and diffing — which needs no
             knowledge of what correct output looks like.

FOUR PATHS, because all three silent bugs so far lived in the gap between two
of them: yaml/pyscript (band=) x automation/script (subscribed or not). An
intent is probed on every path it can reach, not just the one the corpus
happened to exercise.

USE:
    python test_intent_probe.py              # full report
    python test_intent_probe.py --section comparisons
    python test_intent_probe.py --verbose    # include per-intent detail

This is a REPORT, not a pass/fail gate — test_compile_snapshots.py is the gate.
Exit code is 0 unless the probe itself broke.
"""
import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shim.compiler import compile_piston                      # noqa: E402
from shim.compiler import emit_yaml as _emit_yaml             # noqa: E402
from test_compile_snapshots import _synthetic_maps            # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
DEV = ":" + "a" * 32 + ":"          # one synthetic device, hashed-id shaped


def vocab():
    with open(os.path.join(ROOT, "webcore_vocab.json"), encoding="utf-8") as f:
        return json.load(f)


V = vocab()

# ── A. operands, built from the vocab's own declarations ────────────────────

# The empty operand the editor writes for unused slots (VERIFIED against the
# corpus: every condition carries ro2/to/to2 even when meaningless).
EMPTY = {"g": "any", "t": "c"}


def const(value, vt="string"):
    return {"c": value, "f": "l", "g": "any", "t": "c", "vt": vt}


# Operator-group letter -> the left operand to measure with. webCoRE keys
# operators to attribute TYPES via attributeTypeToOperatorGroup; these are the
# canonical attribute of each type, so `is_greater_than` gets a number and
# `changes_to` gets an enum. Recorded explicitly so a reader can audit the
# probe's inputs — an operator judged "broken" against the wrong operand is
# the mistake this whole file is built to avoid.
LEFT_BY_LETTER = {
    "s": ("attr", "switch"),        # enum
    "i": ("attr", "battery"),       # integer
    "d": ("attr", "temperature"),   # decimal
    "b": ("attr", "switch"),        # boolean group: no boolean-typed attribute
                                    # exists in the vocab; `is`/`is_not` (g=bs)
                                    # are used on enums in every real piston
    "f": ("attr", "image"),         # image
    "t": ("virtual", "time"),       # time/date virtual device
    "m": ("attr", "button"),        # momentary
    "e": ("attr", "presence"),      # presence
    "v": (None, None),              # piston reference — see NO-OPERAND below
}


def left_operand(group_letters):
    """Build the left operand for an operator's group, plus the attribute spec
    we'll need to make a type-correct right operand. Returns (lo, attr_entry)
    or (None, None) when the vocab gives us nothing to build from."""
    for letter in group_letters or "":
        kind, name = LEFT_BY_LETTER.get(letter, (None, None))
        if kind == "attr":
            entry = V["attributes"].get(name)
            if entry:
                return ({"t": "p", "d": [DEV], "a": name, "g": "any", "f": "l"},
                        entry)
        if kind == "virtual":
            entry = V["virtualDevices"].get(name)
            if entry:
                return ({"t": "v", "v": name, "g": "any", "f": "l",
                         "vt": entry.get("t", "string")}, entry)
    return None, None


def right_operand(attr_entry, multi=False, second=False):
    """A value that is VALID for the attribute on the left — from the
    attribute's own declared options/range, never invented."""
    t = (attr_entry or {}).get("t", "string")
    opts = (attr_entry or {}).get("o") or []
    rng = (attr_entry or {}).get("r")
    # MULTI-VALUE operands are a real JSON LIST in `c` (VERIFIED against the
    # corpus: changes_to_any_of carries c:["armedAway","disarmed",...]). The
    # comma-joined form appears only in `exp.str`, the editor's cached parse —
    # feeding the compiler a comma STRING makes any_of look broken when it
    # isn't, which is exactly the wrong-operand trap this probe exists to avoid.
    if t in ("enum", "string", "color", "hexcolor"):
        if multi:
            return const([str(o) for o in (opts[:2] or ["on"])], "enum")
        if opts:
            return const(str(opts[1 if (second and len(opts) > 1) else 0]), "enum")
        return const("on", "string")
    if t in ("integer", "decimal"):
        lo_v, hi_v = (rng or [0, 100])[0], (rng or [0, 100])[1]
        mid = int(lo_v + (hi_v - lo_v) / 4)
        val = mid + (10 if second else 0)
        if multi:
            return const([val, val + 5], "integer")
        return const(val, "integer" if t == "integer" else "decimal")
    if t in ("time", "date", "datetime"):
        # time constants are MINUTES SINCE MIDNIGHT (PISTON_JSON_REFERENCE §4)
        return const(1260 if second else 480, "time")
    if t == "image":
        return const("image", "string")
    return const("on", "string")


def hold_operand(minutes=5):
    """The duration qualifier. `vt` is the UNIT — corpus captures show
    "s"/"m"/"h"/"ms" — not a value type. Used for `t:1` (stays ... for N) and
    `t:2` (was ... N ago)."""
    return {"c": minutes, "f": "l", "g": "any", "t": "c", "vt": "m"}


def condition_node(op, spec, nid=2, as_trigger=True):
    """A single comparison node with every operand the vocab says it needs.
    Returns None when the vocab gives us no way to build a valid left operand
    (recorded as NO-OPERAND rather than guessed)."""
    lo, attr = left_operand(spec.get("g"))
    if lo is None:
        return None
    n_params = spec.get("p", 0)
    multi = bool(spec.get("m"))
    node = {
        "$": nid, "t": "condition", "co": op, "lo": lo,
        "ro": right_operand(attr, multi) if n_params >= 1 else dict(EMPTY),
        "ro2": right_operand(attr, False, True) if n_params >= 2 else dict(EMPTY),
        "to": hold_operand() if spec.get("t") in (1, 2) else dict(EMPTY),
        "to2": dict(EMPTY),
        "ts": [], "fs": [], "sm": "auto",
        "ct": "t" if as_trigger else "c",
        "s": bool(as_trigger),
    }
    return node


# ── B. piston builders ──────────────────────────────────────────────────────

def action(cmd="on", params=None, nid=90):
    return {"$": nid, "t": "action", "a": "0", "d": [DEV],
            "k": [{"$": nid + 1, "c": cmd, "p": params or [], "a": False}]}


def piston(statements, restrictions=None, variables=None):
    return {"o": "and", "r": restrictions or [], "rn": False, "rop": "and",
            "s": statements, "v": variables or [], "z": ""}


def if_stmt(conditions, then=None, els=None, nid=1, restrictions=None,
            elseifs=None):
    return {"$": nid, "t": "if", "a": "0", "o": "and",
            "c": conditions,
            "s": then if then is not None else [action()],
            "e": els or [], "ei": elseifs or [],
            "r": restrictions or [], "rop": "and"}


# ── C. running one probe on all four paths ──────────────────────────────────

def compile_on(p, band):
    """Compile and return ('ok', emitted-code, kind) or ('error', message, None)."""
    _emit_yaml._MEDIA_CFG_OVERRIDE = {}
    reso, globs = _synthetic_maps(p)
    try:
        out = compile_piston(p, "probe", "Probe", reso, globs, band=band)
    except Exception as exc:                                    # noqa: BLE001
        return "error", f"{type(exc).__name__}: {exc}"[:220], None
    body = out.get("yaml") or out.get("pyscript") or out.get("code") or ""
    return "ok", body, out.get("kind") or out.get("target")


def probe_paths(p, script_variant=None):
    """Run a piston on every path it can reach.

    yaml/pyscript come from the band argument. automation/script is NOT a
    setting — a piston becomes a script when nothing can wake it — so the
    caller passes a subscription-free variant to reach that path."""
    res = {}
    for band in ("yaml", "pyscript"):
        res[band] = compile_on(p, band)
    if script_variant is not None:
        for band in ("yaml", "pyscript"):
            res[f"{band}/script"] = compile_on(script_variant, band)
    return res


# ── D. the three failure classes ────────────────────────────────────────────

def find_collisions(outputs):
    """outputs: {intent: emitted-code}. Two different intents emitting
    byte-identical code means one is being silently compiled as the other."""
    by_code = defaultdict(list)
    for name, code in outputs.items():
        if code:
            by_code[code].append(name)
    return [sorted(names) for names in by_code.values() if len(names) > 1]


def dropped(base_code, modified_code):
    """True when adding a modifier changed nothing — it was discarded."""
    return base_code is not None and base_code == modified_code


# ── E. sections ─────────────────────────────────────────────────────────────

def section_comparisons(verbose=False):
    """Every comparison operator webCoRE can express, on every path."""
    print("\n" + "=" * 72)
    print("COMPARISONS — %d operators (%d conditions + %d triggers)"
          % (len(V["comparisons"]["conditions"]) + len(V["comparisons"]["triggers"]),
             len(V["comparisons"]["conditions"]), len(V["comparisons"]["triggers"])))
    print("=" * 72)

    findings = {"error": [], "no_operand": [], "collisions": [], "band": []}
    per_path_code = {"yaml": {}, "pyscript": {}}

    for bucket in ("conditions", "triggers"):
        for op, spec in V["comparisons"][bucket].items():
            node = condition_node(op, spec, as_trigger=(bucket == "triggers"))
            if node is None:
                findings["no_operand"].append((op, spec.get("g")))
                continue
            p = piston([if_stmt([node])])
            res = probe_paths(p)
            for band in ("yaml", "pyscript"):
                status, body, _kind = res[band]
                if status == "error":
                    findings["error"].append((f"{op} [{band}]", body))
                else:
                    per_path_code[band][op] = body
            # an operator the YAML band can't express but PyScript can is
            # CORRECT behaviour (the valve), not a finding — record it only.
            if res["yaml"][0] == "error" and res["pyscript"][0] == "ok":
                findings["band"].append(op)

    for band in ("yaml", "pyscript"):
        for group in find_collisions(per_path_code[band]):
            findings["collisions"].append((band, group))

    _report_comparisons(findings, verbose)
    return findings


def _report_comparisons(f, verbose):
    hard = [(o, m) for o, m in f["error"] if o.endswith("[pyscript]")]
    yaml_only = [o for o in f["band"]]

    print("\n  NO-OPERAND (vocab gives no way to build a valid test): %d" % len(f["no_operand"]))
    for op, g in f["no_operand"]:
        print(f"    {op:<32} group '{g}'")

    print("\n  COMPILES ON NEITHER BAND (real gap): %d" % len(hard))
    for op, msg in hard:
        print(f"    {op.replace(' [pyscript]',''):<32} {msg[:110]}")

    print("\n  YAML can't, PyScript can (valve working as designed): %d" % len(yaml_only))
    if verbose:
        for op in yaml_only:
            print(f"    {op}")

    print("\n  COLLISIONS — different operators, identical emitted code: %d" % len(f["collisions"]))
    for band, group in f["collisions"]:
        print(f"    [{band}] {' == '.join(group)}")


def section_modifiers(verbose=False):
    """The silent-drop class: modifiers that change behaviour but might not
    change output. This is the restrictions bug, generalised."""
    print("\n" + "=" * 72)
    print("MODIFIERS — silent-drop probe (add it, see if output changes)")
    print("=" * 72)

    trig = condition_node("changes_to", V["comparisons"]["triggers"]["changes_to"])
    cond = condition_node("is", V["comparisons"]["conditions"]["is"],
                          nid=3, as_trigger=False)
    restriction = dict(cond, t="restriction", nid=4)
    restriction.pop("ct", None)
    restriction.pop("s", None)

    base = piston([if_stmt([trig])])
    # a piston that subscribes to nothing -> the SCRIPT path
    base_script = piston([action(nid=1)])

    cases = []

    # statement-level restrictions
    cases.append(("statement restriction (`r` on the if)",
                  piston([if_stmt([trig], restrictions=[restriction])]),
                  piston([dict(action(nid=1), r=[restriction], rop="and")])))

    # piston-level restrictions
    cases.append(("piston-level restriction (root `r`)",
                  piston([if_stmt([trig])], restrictions=[restriction]),
                  piston([action(nid=1)], restrictions=[restriction])))

    # restriction on a NESTED statement. 0 of 84 corpus pistons use one, and it
    # was dropped by the analyzer entirely until 2026-08-01 — exactly the kind
    # of hole the corpus can never reveal, which is why this probe exists.
    _inner = {"$": 20, "t": "if", "a": "0", "o": "and",
              "c": [condition_node("is", V["comparisons"]["conditions"]["is"],
                                   nid=21, as_trigger=False)],
              "s": [action(cmd="off", nid=22)], "e": [], "ei": [],
              "r": [], "rop": "and"}
    cases.append(("restriction on a NESTED statement",
                  piston([if_stmt([trig], then=[dict(_inner, r=[restriction])])]),
                  None))

    # condition true/false task lists — PISTON_JSON_REFERENCE §3: "exist on
    # every condition; the compiler must honor them; they are easy to miss"
    # ts/fs hold STATEMENTS, each with its own task list — NOT bare tasks.
    # Built wrong here at first, which made a working compiler look broken
    # the moment it started reading them.
    trig_ts = dict(trig, ts=[action(cmd="off", nid=50)])
    cases.append(("condition `ts` (tasks when condition turns TRUE)",
                  piston([if_stmt([trig_ts])]), None))
    trig_fs = dict(trig, fs=[action(cmd="off", nid=52)])
    cases.append(("condition `fs` (tasks when condition turns FALSE)",
                  piston([if_stmt([trig_fs])]), None))

    # duration qualifier on an operator that does NOT declare t:1
    trig_to = dict(trig, to=hold_operand(3))
    cases.append(("`to` duration on a non-hold operator",
                  piston([if_stmt([trig_to])]), None))

    # dm/dn — capture matching/non-matching devices (0/84 corpus; the spec says
    # the compiler IMPLEMENTS them, never silently ignores)
    trig_dm = dict(trig, lo=dict(trig["lo"], dm="Matched"))
    cases.append(("`dm` capture-matching-devices",
                  piston([if_stmt([trig_dm])],
                         variables=[{"n": "Matched", "t": "device", "v": {"d": []}}]),
                  None))
    trig_dn = dict(trig, lo=dict(trig["lo"], dn="Unmatched"))
    cases.append(("`dn` capture-non-matching-devices",
                  piston([if_stmt([trig_dn])],
                         variables=[{"n": "Unmatched", "t": "device", "v": {"d": []}}]),
                  None))

    # operand interaction filter: physical vs programmatic (VERIFIED :4248)
    trig_phys = dict(trig, lo=dict(trig["lo"], p="p"))
    cases.append(("operand `p:'p'` (physically-operated only)",
                  piston([if_stmt([trig_phys])]), None))

    # aggregation across multiple devices
    _agg_base = condition_node("is", V["comparisons"]["conditions"]["is"],
                               nid=30, as_trigger=False)
    trig_all = dict(_agg_base, lo=dict(_agg_base["lo"], d=[DEV, ":" + "b" * 32 + ":"], g="all"))
    trig_any = dict(_agg_base, lo=dict(_agg_base["lo"], d=[DEV, ":" + "b" * 32 + ":"], g="any"))
    cases.append(("aggregation `g:'all'` vs `g:'any'`", None, None))

    # else-if chain
    cases.append(("`ei` else-if branch",
                  piston([if_stmt([trig], elseifs=[{
                      "$": 60, "o": "and", "n": False,
                      "c": [condition_node("is", V["comparisons"]["conditions"]["is"],
                                           nid=61, as_trigger=False)],
                      "s": [action(cmd="off", nid=62)]}])]), None))

    # async task flag
    cases.append(("task `a:true` (async)",
                  piston([if_stmt([trig], then=[
                      dict(action(), k=[{"$": 91, "c": "on", "p": [], "a": True}])])]),
                  None))

    base_out = {b: compile_on(base, b) for b in ("yaml", "pyscript")}
    base_script_out = {b: compile_on(base_script, b) for b in ("yaml", "pyscript")}

    rows = []
    for label, variant, script_variant in cases:
        if variant is None:
            rows.append((label, "SKIPPED (needs a bespoke comparison)", ""))
            continue
        marks = []
        for band in ("yaml", "pyscript"):
            bstat, bcode, _ = base_out[band]
            vstat, vcode, _ = compile_on(variant, band)
            marks.append(_verdict(band, bstat, bcode, vstat, vcode))
        if script_variant is not None:
            for band in ("yaml", "pyscript"):
                bstat, bcode, _ = base_script_out[band]
                vstat, vcode, _ = compile_on(script_variant, band)
                marks.append(_verdict(f"{band}/script", bstat, bcode, vstat, vcode))
        rows.append((label, "  ".join(marks), ""))

    # aggregation is a two-variant comparison, not a base/variant one
    a_all = {b: compile_on(piston([if_stmt([trig, trig_all])]), b) for b in ("yaml", "pyscript")}
    a_any = {b: compile_on(piston([if_stmt([trig, trig_any])]), b) for b in ("yaml", "pyscript")}
    marks = []
    for band in ("yaml", "pyscript"):
        if a_all[band][0] == "error" or a_any[band][0] == "error":
            marks.append(f"{band}:ERROR")
        elif a_all[band][1] == a_any[band][1]:
            marks.append(f"{band}:DROP")
        else:
            marks.append(f"{band}:ok")
    rows = [(l, m, x) if l != "aggregation `g:'all'` vs `g:'any'`"
            else (l, "  ".join(marks), x) for l, m, x in rows]

    print()
    for label, verdict, _ in rows:
        print(f"  {label:<48} {verdict}")
    print("\n  DROP = compiling with the modifier produced byte-identical output,")
    print("         so the modifier was silently discarded.")
    return rows


def _verdict(band, bstat, bcode, vstat, vcode):
    if vstat == "error":
        return f"{band}:ERROR"
    if bstat == "error":
        return f"{band}:n/a"
    return f"{band}:DROP" if dropped(bcode, vcode) else f"{band}:ok"


def section_statements(verbose=False):
    """Statement types, including the ones 0 of 84 corpus pistons use."""
    print("\n" + "=" * 72)
    print("STATEMENT TYPES")
    print("=" * 72)
    trig = condition_node("changes_to", V["comparisons"]["triggers"]["changes_to"])
    cond = condition_node("is", V["comparisons"]["conditions"]["is"],
                          nid=3, as_trigger=False)

    stmts = {
        "if": if_stmt([trig]),
        "action": action(nid=1),
        # an `on` block holds EVENT nodes, not conditions: t='event' with an
        # `lo` and no comparison at all (VERIFIED piston.module.js:1481-1484 —
        # editEvent seeds {t:'event', lo:{t:'p',...}, z, sm} and never sets
        # co/ro). PISTON_JSON_REFERENCE §2 calls them "<condition>", which is
        # imprecise; the source wins.
        "on": {"$": 1, "t": "on", "a": "0", "s": [action(nid=10)],
               "c": [{"$": 2, "t": "event", "sm": "auto", "z": "",
                      "lo": {"t": "p", "d": [DEV], "a": "switch", "g": "any",
                             "v": None, "c": "", "x": None, "e": ""}}]},
        # `every`'s interval carries its UNIT in vt (s/m/h/d/w), the same
        # encoding as a duration — not a plain integer.
        "every": {"$": 1, "t": "every", "a": "0",
                  "lo": {"c": 5, "f": "l", "g": "any", "t": "c", "vt": "m"},
                  "lo2": const(0, "time"), "s": [action(nid=10)]},
        "do": {"$": 1, "t": "do", "a": "0", "s": [action(nid=10)]},
        "while": {"$": 1, "t": "while", "a": "0", "o": "and", "n": False,
                  "c": [cond], "s": [action(nid=10)]},
        "repeat": {"$": 1, "t": "repeat", "a": "0", "o": "and", "n": False,
                   "c": [cond], "s": [action(nid=10)]},
        "for": {"$": 1, "t": "for", "a": "0", "x": "i",
                "lo": const(1, "integer"), "lo2": const(3, "integer"),
                "lo3": const(1, "integer"), "s": [action(nid=10)]},
        "each": {"$": 1, "t": "each", "a": "0", "x": "d",
                 "lo": {"t": "d", "d": [DEV]}, "s": [action(nid=10)]},
        "switch": {"$": 1, "t": "switch", "a": "0",
                   "lo": {"t": "p", "d": [DEV], "a": "switch", "g": "any"},
                   "cs": [{"t": "c", "ro": const("on", "enum"), "ro2": dict(EMPTY),
                           "s": [action(nid=10)], "z": ""}],
                   "e": [], "ctp": "a"},
        "break": {"$": 1, "t": "break", "a": "0"},
        "exit": {"$": 1, "t": "exit", "a": "0", "lo": dict(EMPTY)},
    }

    print()
    for name, stmt in stmts.items():
        p = piston([stmt])
        marks = []
        for band in ("yaml", "pyscript"):
            status, body, kind = compile_on(p, band)
            marks.append(f"{band}:{'ok(' + str(kind) + ')' if status == 'ok' else 'ERROR'}")
        detail = ""
        if verbose:
            for band in ("yaml", "pyscript"):
                status, body, _ = compile_on(p, band)
                if status == "error":
                    detail = "\n      " + body[:150]
        print(f"  {name:<12} {'  '.join(marks)}{detail}")
    return stmts


def section_commands(verbose=False):
    """Every command in the vocab, with its declared parameter count."""
    print("\n" + "=" * 72)
    cmds = {**V["commands"], **V["virtualCommands"]}
    print("COMMANDS — %d (%d physical + %d virtual)"
          % (len(cmds), len(V["commands"]), len(V["virtualCommands"])))
    print("=" * 72)

    trig = condition_node("changes_to", V["comparisons"]["triggers"]["changes_to"])
    fails = {"both": [], "yaml_only": []}
    codes = {}
    for name, spec in cmds.items():
        params = []
        for pspec in spec.get("p", []) or []:
            params.append(_param_operand(pspec))
        p = piston([if_stmt([trig], then=[action(cmd=name, params=params)])])
        r_yaml = compile_on(p, "yaml")
        r_py = compile_on(p, "pyscript")
        if r_yaml[0] == "error" and r_py[0] == "error":
            fails["both"].append((name, r_py[1]))
        elif r_yaml[0] == "error":
            fails["yaml_only"].append(name)
        if r_yaml[0] == "ok":
            codes[name] = r_yaml[1]

    print("\n  COMPILES ON NEITHER BAND: %d of %d" % (len(fails["both"]), len(cmds)))
    for name, msg in fails["both"]:
        print(f"    {name:<26} {msg[:110]}")
    print("\n  YAML can't, PyScript can: %d" % len(fails["yaml_only"]))
    if verbose:
        for n in fails["yaml_only"]:
            print(f"    {n}")

    coll = find_collisions(codes)
    print("\n  COLLISIONS — different commands, identical emitted code: %d" % len(coll))
    for group in coll:
        print(f"    {' == '.join(group)}")
    return fails


def _param_operand(pspec):
    """A parameter value valid for the command's declared parameter type."""
    t = (pspec or {}).get("t", "string")
    opts = (pspec or {}).get("o") or []
    if opts:
        return const(str(opts[0]), "enum")
    # The vocab's parameter types are an OPEN vocabulary — webCoRE names them
    # after the quantity ("hue", "saturation", "volume"), not after a base
    # type. Anything measured on a scale has to arrive as a NUMBER; passing a
    # string makes a working command look broken (it did for setHue /
    # setSaturation / setVolume on the first run of this probe).
    if t in ("integer", "level", "number", "hue", "saturation", "volume",
             "percent", "brightness", "colorTemperature", "temperature",
             "contrast", "infraredLevel", "position", "speed"):
        return const(50, "integer")
    if t == "decimal":
        return const(1.5, "decimal")
    if t in ("time", "date", "datetime"):
        return const(480, "time")
    if t == "duration":
        return {"c": 5, "f": "l", "g": "any", "t": "c", "vt": "m"}
    if t == "bool" or t == "boolean":
        return const("true", "boolean")
    return const("test", "string")


def section_functions(verbose=False):
    """Every expression function, called with its declared arity."""
    print("\n" + "=" * 72)
    print("FUNCTIONS — %d" % len(V["functions"]))
    print("=" * 72)
    trig = condition_node("changes_to", V["comparisons"]["triggers"]["changes_to"])
    fails = []
    for name, spec in V["functions"].items():
        expr = f"{name}({_fn_args(spec)})"
        p = piston([if_stmt([trig], then=[
            action(params=[{"t": "e", "e": expr, "g": "any"}])])])
        r_yaml = compile_on(p, "yaml")
        r_py = compile_on(p, "pyscript")
        if r_yaml[0] == "error" and r_py[0] == "error":
            fails.append((name, expr, r_py[1]))
    print("\n  COMPILES ON NEITHER BAND: %d of %d" % (len(fails), len(V["functions"])))
    for name, expr, msg in fails:
        print(f"    {expr:<28} {msg[:100]}")
    return fails


def _fn_args(spec):
    """Arity from the vocab where it declares one, else a single argument."""
    n = spec.get("a")
    if isinstance(n, int):
        return ", ".join(["1"] * max(n, 0))
    params = spec.get("p")
    if isinstance(params, list) and params:
        return ", ".join(["1"] * len(params))
    return "1"


SECTIONS = {
    "comparisons": section_comparisons,
    "modifiers": section_modifiers,
    "statements": section_statements,
    "commands": section_commands,
    "functions": section_functions,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--section", choices=sorted(SECTIONS), action="append")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    for name in (args.section or list(SECTIONS)):
        SECTIONS[name](args.verbose)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

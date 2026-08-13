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
from shim.compiler.analyze import analyze as _analyze         # noqa: E402
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


def statement_shapes():
    """One piston statement of every type webCoRE has.

    Lifted out of `section_statements` so the commitment sweep runs over the
    same shapes instead of keeping its own copy of them (HARD_RULES §9) — a
    second list would drift, and the shapes nobody exercises are exactly the
    ones that go wrong."""
    trig = condition_node("changes_to", V["comparisons"]["triggers"]["changes_to"])
    cond = condition_node("is", V["comparisons"]["conditions"]["is"],
                          nid=3, as_trigger=False)

    return {
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


def section_statements(verbose=False):
    """Statement types, including the ones 0 of 84 corpus pistons use."""
    print("\n" + "=" * 72)
    print("STATEMENT TYPES")
    print("=" * 72)
    stmts = statement_shapes()

    print()
    failures = []
    for name, stmt in stmts.items():
        failures += _report_shape(name, stmt, verbose, width=12)

    # VARIANTS WITHIN a statement type. The dict above proves each type
    # compiles ONCE, with one set of operands — which is not the same as
    # proving the type is covered. `every` passes above on "every 5 minutes"
    # while "every 90 minutes" and "every day at sunrise" take completely
    # different paths, and an `if` passes on "and" while "xor" does not.
    #
    # FOUND 2026-08-06: nine shapes below compile on PyScript but the ANALYZER
    # cannot read at all. That is invisible to the corpus (0 of 84 use any of
    # them) and invisible to the section above, and it is a live hazard for
    # Stage 1 of SESSION_BRIEF_ONE_READER_ONE_WRITER: the moment the PyScript
    # band reads through the analyzer, every one of them stops compiling —
    # including for a user who FORCED PyScript, which bypasses routing and so
    # has no fallback left (Jeremy, 2026-08-06).
    print("\n  VARIANTS WITHIN A TYPE")
    print()
    for name, stmt in statement_variants().items():
        failures += _report_shape(name, stmt, verbose, width=26)
    return failures


def _report_shape(name, stmt, verbose, width):
    """Compile one statement shape on both bands and print a row.

    Returns the PyScript failures — the band that MUST be total, because it is
    user-selectable and bypasses routing when forced (COMPILER_SPEC §3.2)."""
    p = piston([stmt])
    marks, failures = [], []
    pyscript_ok = False
    for band in ("yaml", "pyscript"):
        status, body, kind = compile_on(p, band)
        marks.append(f"{band}:{'ok(' + str(kind) + ')' if status == 'ok' else 'ERROR'}")
        if band == "pyscript":
            pyscript_ok = status == "ok"
            if status == "error":
                failures.append((name, body))

    # STAGE 1 PRECONDITION: can the ANALYZER read this shape?
    #
    # Both bands are to share one reader (SESSION_BRIEF_ONE_READER_ONE_WRITER
    # §3). Any shape PyScript can compile but the analyzer cannot READ is a
    # piston that stops compiling the moment that lands — and stops on the only
    # band that could run it. Nine such shapes existed on 2026-08-06 and no
    # test could see them, so the precondition is checked here rather than
    # spot-checked by hand.
    try:
        _analyze(p, "probe", "Probe")
        reads = True
    except Exception as exc:                                    # noqa: BLE001
        reads, why = False, f"{type(exc).__name__}: {exc}"
    marks.append("reader:ok" if reads else "reader:CANNOT-READ")
    if pyscript_ok and not reads:
        failures.append((name, "PyScript compiles it but the analyzer cannot "
                               "read it - " + why))
    detail = ""
    if verbose:
        for band in ("yaml", "pyscript"):
            status, body, _ = compile_on(p, band)
            if status == "error":
                detail = "\n      " + body[:150]
    print(f"  {name:<{width}} {'  '.join(marks)}{detail}")
    return failures


def statement_variants():
    """Shapes WITHIN a statement type that take a different compilation path.

    Each entry is here because it reaches code the plain form does not. The
    `every` family splits on unit and on whether the daily time is a fixed
    clock time or a sun event; `switch` splits on fall-through; `if` splits on
    the operator joining its conditions."""
    cond_on = condition_node("is", V["comparisons"]["conditions"]["is"],
                             nid=3, as_trigger=False)
    cond_off = condition_node("is", V["comparisons"]["conditions"]["is"],
                              nid=4, as_trigger=False)

    def every(interval, unit, lo2=None, nid=1):
        s = {"$": nid, "t": "every", "a": "0",
             "lo": {"c": interval, "f": "l", "g": "any", "t": "c", "vt": unit},
             "s": [action(nid=10)]}
        if lo2 is not None:
            s["lo2"] = lo2
        return s

    def sun(which):
        """A sun-event time operand, VERIFIED against the corpus rather than
        guessed: 13_Chicken_Light_Morning_GPT / 14 / 15 all carry exactly
        {"f":"l","g":"any","s":"sunrise","t":"s","vt":"time"}.

        Note `t` is "s" (a PRESET operand), not "c" — a constant with an `s`
        field is not the same node and would probe a path the editor never
        emits. Hence its own builder rather than const()."""
        return {"f": "l", "g": "any", "s": which, "t": "s", "vt": "time"}

    return {
        "every 5 minutes": every(5, "m"),
        "every 90 minutes": every(90, "m"),
        "every 5 hours": every(5, "h"),
        "every 2 days": every(2, "d", const(480, "time")),
        "every 1 week": every(1, "w", const(480, "time")),
        "every day at 08:00": every(1, "d", const(480, "time")),
        "every day at sunrise": every(1, "d", sun("sunrise")),
        "every day at sunset": every(1, "d", sun("sunset")),
        "on <mode changes>": {
            "$": 1, "t": "on", "a": "0", "s": [action(nid=10)],
            "c": [{"$": 2, "t": "event", "sm": "auto", "z": "",
                   "lo": {"t": "v", "v": "mode", "g": "any", "c": "",
                          "x": None, "e": ""}}]},
        "if A xor B": if_stmt([cond_on, cond_off]) | {"o": "xor"},
        "switch fall-through": {
            "$": 1, "t": "switch", "a": "0", "ctp": "f",
            "lo": {"t": "p", "d": [DEV], "a": "switch", "g": "any"},
            "cs": [{"t": "c", "ro": const("on", "enum"), "ro2": dict(EMPTY),
                    "s": [action(nid=10)], "z": ""}],
            "e": []},
    }


def section_intent(verbose=False):
    """Every command in the VOCAB must have a stated OUTCOME (§3.0).

    This is the atom layer of the intent engine: what each webCoRE word wants
    to happen, independent of whether HA can currently oblige. It is scoped to
    the vocabulary and NOT to the corpus on purpose (HARD_RULES §5) — the
    vocabulary is the bounded list of everything webCoRE can express.

    NOT the whole picture, and must not be mistaken for it (Jeremy,
    2026-08-07): a piston's intent is a SHAPE across statements, not the sum
    of its words. This gate proves no word is unaccounted for; it says nothing
    about whether the piston's purpose was understood.

    Returns the hard failures (unclassified) as (name, reason) pairs."""
    from shim.compiler import intent
    cov = intent.coverage()
    print(f"INTENT: {cov['classified']}/{cov['total']} commands have a stated "
          f"outcome")
    for kind in sorted(cov["by_outcome"], key=lambda k: -len(cov["by_outcome"][k])):
        names = cov["by_outcome"][kind]
        print(f"   {kind:<14} {len(names):>3}")
        if verbose:
            print(f"        {', '.join(names)}")
    if cov["residual"]:
        print(f"   (review queue: {len(cov['residual'])} fell through to "
              f"'be' — check any that are not 'make the device be this way')")
    return [(n, "no outcome stated for this command")
            for n in cov["unclassified"]]


def _placement_shapes():
    """Shapes that put an action somewhere STRUCTURALLY awkward.

    Every silent drop this project has had was a placement bug, not a command
    bug: the action itself compiled perfectly well elsewhere, and was lost
    because of WHERE it sat. `ts`/`fs` hung off a condition went missing for
    months; a restriction on a nested statement was never read at all. Each
    shape below parks a plain `on` in one of those places, so a diff can ask
    the only question that matters — did the light still get turned on?"""
    trig = condition_node("changes_to", V["comparisons"]["triggers"]["changes_to"])
    cond = condition_node("is", V["comparisons"]["conditions"]["is"],
                          nid=3, as_trigger=False)

    def with_attached(key):
        c = json.loads(json.dumps(trig))
        c[key] = [action(nid=70)]
        return if_stmt([c], then=[action(cmd="off", nid=80)])

    nested_restricted = {"$": 5, "t": "do", "a": "0", "s": [action(nid=70)],
                         "r": [json.loads(json.dumps(cond))], "rop": "and"}

    return {
        "action in if/then": if_stmt([trig], then=[action(nid=70)]),
        "action in if/else": if_stmt([trig], then=[action(cmd="off", nid=80)],
                                     els=[action(nid=70)]),
        "action in else-if": if_stmt(
            [trig], then=[action(cmd="off", nid=80)],
            elseifs=[{"o": "and", "n": False, "c": [json.loads(json.dumps(cond))],
                      "s": [action(nid=70)]}]),
        "condition ts (true)": with_attached("ts"),
        "condition fs (false)": with_attached("fs"),
        "nested restriction": if_stmt([trig], then=[nested_restricted]),
        "statement restriction": if_stmt([trig], then=[action(nid=70)],
                                         restrictions=[json.loads(json.dumps(cond))]),
        "action behind a wait": if_stmt([trig], then=[
            {"$": 60, "t": "action", "a": "0", "d": [DEV],
             "k": [{"$": 61, "c": "wait", "a": False,
                    "p": [{"t": "c", "c": 300, "vt": "integer", "g": "any",
                           "f": "l"}]}]},
            action(nid=70)]),
        "action in switch case": if_stmt([trig], then=[{
            "$": 6, "t": "switch", "a": "0",
            "lo": {"t": "p", "d": [DEV], "a": "switch", "g": "any"},
            "cs": [{"t": "c", "ro": const("on", "enum"), "ro2": dict(EMPTY),
                    "s": [action(nid=70)], "z": ""}], "e": [], "ctp": "a"}]),
        "action in switch default": if_stmt([trig], then=[{
            "$": 6, "t": "switch", "a": "0",
            "lo": {"t": "p", "d": [DEV], "a": "switch", "g": "any"},
            "cs": [{"t": "d", "ro": dict(EMPTY), "ro2": dict(EMPTY),
                    "s": [action(nid=70)], "z": ""}], "e": [], "ctp": "a"}]),
        "action in each loop": if_stmt([trig], then=[{
            "$": 7, "t": "each", "a": "0", "x": "d",
            "lo": {"t": "d", "d": [DEV]}, "s": [action(nid=70)]}]),
    }


def section_commitments(verbose=False):
    """Did every promise the piston made survive the compile?

    The one check that can see a SILENT DROP. Everything else in this file
    asks "did it compile" or "did two things compile the same"; this asks
    whether the emitted automation still does what the piston said, which is
    the failure that has actually hurt (HARD_RULES §6 — silence is the bug).

    Scoped to the VOCABULARY and to structural placements, never the corpus
    (HARD_RULES §5). Returns the hard failures as (name, reason) pairs."""
    from shim.compiler import commitment as C

    print("\n" + "=" * 72)
    print("COMMITMENTS — promises made vs promises kept")
    print("=" * 72)

    cmds = {**V["commands"], **V["virtualCommands"]}
    trig = condition_node("changes_to", V["comparisons"]["triggers"]["changes_to"])
    cases = {}
    for name, spec in cmds.items():
        params = [_param_operand(p) for p in (spec.get("p") or [])]
        cases[f"command {name}"] = piston(
            [if_stmt([trig], then=[action(cmd=name, params=params)])])
    for name, stmt in _placement_shapes().items():
        cases[f"placement {name}"] = piston([stmt])

    tally = {k: [] for k in ("dropped", "retimed", "invented", "passthrough",
                             "target_moved", "alternative")}
    kept = skipped = 0
    failures = []
    for name, p in cases.items():
        _emit_yaml._MEDIA_CFG_OVERRIDE = {}
        reso, globs = _synthetic_maps(p)
        status, code, _kind = compile_on(p, "yaml")
        if status != "ok":
            # A piston the YAML band refuses goes to PyScript, which this
            # check does not read yet. Counted, never silently ignored.
            skipped += 1
            continue
        try:
            result = C.diff(C.from_piston(p, reso, globs), C.from_yaml(code))
        except Exception as exc:                                # noqa: BLE001
            failures.append((name, f"the checker crashed: "
                                   f"{type(exc).__name__}: {exc}"[:160]))
            continue
        kept += result["kept"]
        for bucket in tally:
            for item in result[bucket]:
                tally[bucket].append((name, item))
        for promise, _ in result["dropped"]:
            failures.append((name, f"DROPPED — {promise.describe()}"))
        for extra in result["invented"]:
            failures.append((name, f"INVENTED — {extra.describe()}"))

    print(f"\n  {len(cases)} shapes checked, {kept} promises kept, "
          f"{skipped} routed to PyScript (not read by this check yet)")
    print(f"\n  DROPPED  {len(tally['dropped']):>3}   a promise the emitted "
          f"automation no longer makes")
    print(f"  INVENTED {len(tally['invented']):>3}   a call the piston never "
          f"asked for")
    print(f"  RETIMED  {len(tally['retimed']):>3}   kept, but at a different "
          f"delay")
    print(f"\n  and, reported rather than failed:")
    for bucket, why in (
            ("passthrough", "sent to the device's raw driver instead of the "
                            "HA service the vocab names"),
            ("target_moved", "delivered, but not to the device the piston "
                             "pointed at"),
            ("alternative", "one promise emitted as a branch (a toggle is two "
                            "calls, one choice)")):
        names = sorted({n.split(" ", 1)[1] for n, _ in tally[bucket]})
        print(f"  {bucket:<13}{len(tally[bucket]):>3}   {why}")
        if names:
            print(f"                    {', '.join(names)[:180]}")
    if verbose:
        for bucket in ("dropped", "invented", "retimed"):
            for name, item in tally[bucket]:
                thing = item[0] if isinstance(item, tuple) else item
                print(f"    {bucket:<10} {name:<34} {thing.describe()[:90]}")
    return failures


def _raw_tasks(node, out):
    """Every task anywhere in a piston, found by walking EVERY key.

    GROUND TRUTH on purpose. It does not know where work is supposed to live,
    so it cannot inherit a reader's blind spots — which is the only way to
    measure a reader that is itself the thing under test."""
    if isinstance(node, list):
        for x in node:
            _raw_tasks(x, out)
    elif isinstance(node, dict):
        if isinstance(node.get("c"), str) and node.get("t") is None:
            out.append(node.get("c"))
        for v in node.values():
            _raw_tasks(v, out)


def _ir_tasks(nodes, out):
    """Every task the ANALYZER can see, walking its IR."""
    for x in nodes or []:
        if not isinstance(x, dict):
            continue
        if x.get("kind") == "task":
            out.append(x.get("command"))
        for k in ("then", "else", "body", "default"):
            _ir_tasks(x.get(k), out)
        for c in x.get("cases") or []:
            _ir_tasks(c.get("body"), out)
        for c in x.get("conditions") or []:
            _ir_tasks(c.get("true_actions"), out)
            _ir_tasks(c.get("false_actions"), out)
            for ch in c.get("children") or []:
                _ir_tasks(ch.get("true_actions"), out)
                _ir_tasks(ch.get("false_actions"), out)


def section_reading(verbose=False):
    """Can the reader SEE everything the piston contains?

    The first stage boundary: raw JSON -> the analyzer's IR. Every later stage
    is built on this one, so a task invisible here is invisible everywhere
    after it, and no downstream gate can notice — they would all be measuring
    the same blind reader.

    WHY IT EXISTS (measured 2026-08-08). A reader that walks only bodies
    (`s`/`e`/`ei`/`cs`) misses **42 of the corpus's 507 tasks — 8%**. Work also
    hangs off CONDITIONS (`ts`/`fs`), off conditions nested inside GROUPS
    (recursively), and off RESTRICTIONS. It is not an edge case:
    `62_Smoke_Co_Detected` hides 9 of its 11 tasks that way,
    `70_Water_Leak_Notification` 7 of 11, and `43_Package_delivery` hides ALL
    THREE — the entire piston reads as empty. One real statement
    (`70_Water` $6) has an EMPTY then-branch and carries its whole job,
    including a repeat loop and a per-device announcement, on its condition.

    Returns hard failures as (name, reason) pairs."""
    import glob

    print("\n" + "=" * 72)
    print("READING — does the reader see everything the piston contains?")
    print("=" * 72)

    failures, checked, raw_total, seen_total = [], 0, 0, 0
    for path in sorted(glob.glob(os.path.join(ROOT, "test-pistons", "*.json"))):
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        piston = doc.get("piston") or doc
        if not piston.get("s"):
            continue
        raw = []
        _raw_tasks(piston.get("s"), raw)
        seen = []
        try:
            for br in _analyze(piston, "gate", os.path.basename(path)):
                _ir_tasks(br.get("then"), seen)
                _ir_tasks(br.get("else"), seen)
                for c in ((br.get("conditions") or []) + (br.get("triggers") or [])
                          + (br.get("restrictions") or [])):
                    _ir_tasks(c.get("true_actions"), seen)
                    _ir_tasks(c.get("false_actions"), seen)
                    for ch in c.get("children") or []:
                        _ir_tasks(ch.get("true_actions"), seen)
                        _ir_tasks(ch.get("false_actions"), seen)
        except Exception as exc:                                # noqa: BLE001
            failures.append((os.path.basename(path),
                             f"the reader could not read it: "
                             f"{type(exc).__name__}: {exc}"[:150]))
            continue
        checked += 1
        raw_total += len(raw)
        seen_total += len(seen)
        if len(seen) < len(raw):
            missing = list(raw)
            for c in seen:
                if c in missing:
                    missing.remove(c)
            failures.append((os.path.basename(path),
                             f"{len(raw) - len(seen)} of {len(raw)} tasks are "
                             f"invisible to the reader: {sorted(set(missing))[:6]}"))

    print(f"\n  {checked} pistons, {raw_total} tasks in the JSON, "
          f"{seen_total} visible to the reader")
    if not failures:
        print("  every task the piston contains is reachable by the reader")
    return failures


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
    # A COLOUR is a string, but not any string. The generic "test" made
    # setColor / setAdjustedColor / setAdjustedHSLColor look like they fell
    # back to the device's raw driver, when the compiler was right to reject
    # a value that is not a colour — three false findings from a bad input.
    # The probe's job is to feed each command something VALID for its declared
    # type; judging a command on a value it should refuse proves nothing.
    if t in ("color", "colour"):
        return const("#ff8800", "string")
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


def section_understanding(verbose=False):
    """Does the READING actually understand each form, or just survive it?

    THE GAP THIS FILLS (Jeremy, 2026-08-08: *"why is the intent engine not
    catching all of this"*). The other gates check that a shape COMPILES, that
    a task is REACHABLE, and that a promise SURVIVES emission. None of them ask
    whether the reading is right, so a form that reads as EMPTY passes every
    one of them. Six real misses hid behind four green gates and were found by
    hand: `on` blocks reading as having no trigger, `every` the same, `switch`
    reading as unconditional, triggers found only via a stamped `ct`, five
    pistons reading as "nothing starts this" (including a gas detector), and
    every preset — sunrise and sunset — collapsing into the word "expression".

    Each check below is one of those, turned into something that fails by
    itself. Scoped to the VOCABULARY, never the corpus (HARD_RULES §5): these
    forms are what webCoRE can express, not what Jeremy happens to have
    written, and the corpus is exactly what hid them.

    Nothing here says anything about BEHAVIOUR. It proves the reading is not
    silently empty; only a device proves what an automation does (HARD_RULES
    §7)."""
    from shim.compiler import spec

    fails = []
    shapes = statement_shapes()

    def tree(st):
        return list(spec.read_tree({"s": [st], "v": []}).walk())

    # 1. A form whose whole purpose is the trigger must read one.
    for name in ("on", "every", "if"):
        if name in shapes and not sum(len(b.wakes) for b in tree(shapes[name])):
            fails.append((name, "reads as having nothing that wakes it"))

    # 2. A form that carries conditions must read them.
    for name in ("if", "while", "repeat", "switch"):
        if name in shapes and not sum(
                len(b.gate.leaves()) if b.gate is not None else 0
                for b in tree(shapes[name])):
            fails.append((name, "carries conditions the reading does not see"))

    # 3. Work written in a form must be read.
    for name, st in shapes.items():
        if name in ("break", "exit"):
            continue          # known open: they carry control flow, not work
        if not sum(len(b.does) for b in tree(st)):
            fails.append((name, "the work inside it is not read"))

    # 4. Every operand kind the picker can produce stays itself. Collapsing
    #    them is how sunrise/sunset became invisible.
    for kind, lo, want in (
            ("preset", {"t": "s", "s": "sunrise"}, "preset"),
            ("constant", {"t": "c", "c": 5}, "constant"),
            ("expression", {"t": "e", "e": "$now - 5"}, "expr"),
            ("argument", {"t": "u", "u": "a"}, "argument"),
            ("variable", {"t": "x", "x": "v"}, "variable"),
            ("system", {"t": "v", "v": "time"}, "virtual"),
            ("device", {"t": "p", "d": [":a:"], "a": "switch"}, "device"),
            ("device list", {"t": "d", "d": [":a:", ":b:"]}, "device")):
        got = spec._subject(lo)
        if got.kind != want:
            fails.append((kind, "reads as '%s', not '%s'" % (got.kind, want)))
        if not got.describe() or got.describe() in ("an expression", "None"):
            fails.append((kind, "renders as %r — the value is gone" % got.describe()))

    # 5. An indexed variable is not the same variable.
    if spec._subject({"t": "x", "x": "l", "xi": 2}).describe() == \
            spec._subject({"t": "x", "x": "l", "xi": 5}).describe():
        fails.append(("indexed variable", "list[2] and list[5] read identically"))

    # 6. The false case must not read as the true case.
    c = {"t": "condition", "lo": {"t": "p", "d": [":a:"], "a": "switch"},
         "co": "is", "ro": {"t": "c", "c": "on"}, "ct": "t"}
    t = spec._test(c)
    if t.describe() == t.negate().describe():
        fails.append(("negation", "a test and its opposite read identically"))

    # 7. AND is not OR.
    def g(op):
        return spec._gate([dict(c), dict(c, co="is_not")], op).describe()
    if g("and") == g("or"):
        fails.append(("gate operator", "AND and OR read identically"))

    # 8. A TRIGGER WITH NO `ct` STAMP still has to read as a trigger.
    #    `ct` is written by the engine, so it is ABSENT on every imported,
    #    AI-authored or hand-built piston — and the classifier must fall back
    #    to the vocabulary bucket (PISTON_JSON_REFERENCE §3). Testing `ct`
    #    directly made 5 corpus pistons read as "nothing starts this",
    #    including a gas detector.
    #    THIS CHECK EXISTS BECAUSE THE GATE MISSED IT: with the bug deliberately
    #    reinstated, checks 1-7 all passed. A gate nobody has seen fail is
    #    worth nothing, and this one had a hole until it was tested that way.
    unstamped = {"t": "condition", "co": "changes_to",
                 "lo": {"t": "p", "d": [":a:"], "a": "switch", "g": "any"},
                 "ro": {"t": "c", "c": "on"}}          # note: no "ct"
    if not spec._test(unstamped).wakes:
        fails.append(("unstamped trigger",
                      "a trigger comparison with no ct stamp reads as a condition"))
    stamped_cond = dict(unstamped, co="is")
    if spec._test(stamped_cond).wakes:
        fails.append(("unstamped condition",
                      "a condition comparison reads as a trigger"))

    # 9. WORK HANGS OFF RESTRICTIONS, NOT JUST CONDITIONS. A restriction is a
    #    condition node and carries its own ts/fs. Walking only `c` loses it —
    #    the tree reader did exactly that and found 1 task where 3 exist.
    #    0 of 84 corpus pistons use restrictions, so nothing else can see this.
    act = {"t": "action", "$": 9, "d": [":b:"],
           "k": [{"t": "command", "c": "on", "p": []}]}
    restr = {"t": "condition", "co": "is", "ro": {"t": "c", "c": "on"},
             "lo": {"t": "p", "d": [":a:"], "a": "switch", "g": "any"},
             "ts": [dict(act)], "fs": [dict(act, **{"$": 8})]}
    piston = {"s": [{"t": "if", "$": 1, "c": [], "r": [restr], "rop": "and",
                     "s": [dict(act, **{"$": 2})]}]}
    tree_n = sum(len(b.does) for b in spec.read_tree(piston).walk())
    flat_n = len(spec.read(piston))
    if tree_n != flat_n:
        fails.append(("restriction ts/fs",
                      "work hung on a restriction is lost (%d of %d read)"
                      % (tree_n, flat_n)))

    # 10. EVERY VARIABLE TYPE the picker offers — carried, not just named.
    #
    #     THE FIRST VERSION OF THIS CHECK WAS THEATRE: it called `_subject`
    #     with the same operand 19 times and asserted it said "variable". It
    #     could not fail, because the DECLARED TYPE never reached the reader
    #     at all. A device group, a string and a `time[]` list were the
    #     identical token `{name}` — so the reading could not tell nine
    #     sensors from one, which is the difference that has already produced
    #     one device-proven bug.
    vts = [e["key"] for grp in V.get("variableTypes", {}).values() for e in grp]
    if len(vts) != 19:
        fails.append(("variable types",
                      "%d types enumerated, expected 19 (10 basic + 9 list)"
                      % len(vts)))
    declared = [{"n": "v_%d" % i, "t": key,
                 "v": ({"d": [":x:", ":y:"]} if key == "device" else "")}
                for i, key in enumerate(vts)]
    probe = {"v": declared, "s": []}
    spec.read_tree(probe)
    for i, key in enumerate(vts):
        got = spec._subject({"t": "x", "x": "v_%d" % i})
        if got.var_type != key:
            fails.append(("variable " + key,
                          "declared type is not carried (read %r)" % got.var_type))

    # 11. A DEVICE VARIABLE IS A GROUP, and its size must be known from the
    #     piston alone — `Water_Sensor_All` is nine sensors, not one name.
    dev = spec._subject({"t": "p", "d": ["v_%d" % vts.index("device")],
                         "a": "switch", "g": "any"})
    if len(dev.members) != 2:
        fails.append(("device variable",
                      "a device group does not expand to its members (%d)"
                      % len(dev.members)))

    print()
    print("=" * 72)
    print("UNDERSTANDING - is the reading right, not merely surviving")
    print("=" * 72)
    if fails:
        for what, why in fails:
            print("  %-18s %s" % (what, why))
    else:
        print("  every form reads with its trigger, its conditions, its work,")
        print("  and every operand kind keeps its own identity.")
    return fails


SECTIONS = {
    "understanding": section_understanding,
    "comparisons": section_comparisons,
    "modifiers": section_modifiers,
    "reading": section_reading,
    "statements": section_statements,
    "intent": section_intent,
    "commitments": section_commitments,
    "commands": section_commands,
    "functions": section_functions,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--section", choices=sorted(SECTIONS), action="append")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    wanted = args.section or list(SECTIONS)
    results = {name: SECTIONS[name](args.verbose) for name in wanted}
    print()

    # GATE — the one invariant this file enforces rather than reports.
    #
    # PyScript is user-selectable ("prefer PyScript for fidelity",
    # COMPILER_SPEC §3.2) and forcing it bypasses routing entirely, so there is
    # no fallback behind it: whatever it cannot compile, the user simply cannot
    # compile. Jeremy's rule is that it must therefore be TOTAL — a piston
    # failing there is a bug in the valve, never a missing feature.
    #
    # Scoped to STATEMENT SHAPES on purpose. Comparison operators and commands
    # are not total yet (29 and 40 open respectively, COMPILER_TODO.md) and
    # gating on those would just fail every run and teach everyone to ignore
    # it. Statement shapes ARE total today, and Stage 1 of the one-reader work
    # is precisely the change that could silently break them.
    # UNDERSTANDING is a gate, not a report. The other gates all pass while the
    # reading is silently empty — that is how `on` blocks with no trigger, a
    # switch with no conditions and sunrise-as-"an expression" survived four
    # green gates. Proven to detect by reinstating each bug and watching it
    # fail (2026-08-08); one of the checks exists only because the first
    # version of this gate did NOT catch the trigger-classification bug.
    misread = results.get("understanding") or []
    if misread:
        print("GATE FAILED - the reading loses something it used to keep:\n")
        for what, why in misread:
            print("   %-20s %s" % (what, why))
        print()
        return 1
    if "understanding" in wanted:
        print("GATE PASSED - every form reads with its trigger, its conditions")
        print("and its work, and every operand kind keeps its own identity.\n")

    broken = results.get("statements") or []
    if broken:
        print("GATE FAILED - a statement shape either stopped compiling on the")
        print("PyScript band (which has no fallback behind it), or compiles")
        print("there while the shared reader cannot read it:\n")
        for name, err in broken:
            print(f"  {name}\n      {err[:170]}")
        print()
        return 1
    if "statements" in wanted:
        print("GATE PASSED - every statement shape compiles on PyScript, and")
        print("the analyzer can read every one of them.\n")

    # INTENT GATE — every word in the vocabulary must have a stated outcome.
    # Total today, so it gates rather than reports. Unlike the comparison and
    # command coverage numbers, there is no reason for this one to have holes:
    # stating what a word MEANS never depends on HA being able to do it.
    unstated = results.get("intent") or []
    if unstated:
        print("GATE FAILED - the vocabulary contains commands with no stated")
        print("outcome, so the compiler cannot say what the user wanted:\n")
        for name, why in unstated:
            print(f"  {name}\n      {why}")
        print()
        return 1
    if "intent" in wanted:
        print("GATE PASSED - every command in the vocabulary has a stated "
              "outcome.\n")

    # COMMITMENT GATE — nothing the piston promised may go missing, and the
    # compiler may not invent a call nobody asked for. This is the one gate
    # that can see a SILENT drop: the other two prove things compile, and
    # every drop this project has had compiled perfectly (HARD_RULES §6, §7).
    #
    # Total today, so it gates rather than reports. The categories that are
    # NOT failures — a raw-driver passthrough, a moved target, a promise
    # emitted as a branch — are printed every run instead, because each is a
    # real divergence worth a human's eye and none of them is a bug.
    # READING GATE — the first stage boundary. A task invisible to the reader
    # is invisible to every stage after it, and no later gate can see the
    # difference, because they would all be measuring the same blind reader.
    unread = results.get("reading") or []
    if unread:
        print("GATE FAILED - the reader cannot see everything the piston")
        print("contains, so later stages are measuring an incomplete read:")
        print()
        for name, why in unread:
            print(f"  {name}")
            print(f"      {why}")
        print()
        return 1
    if "reading" in wanted:
        print("GATE PASSED - every task in every piston is reachable by the "
              "reader.")
        print()

    lost = results.get("commitments") or []
    if lost:
        print("GATE FAILED - the emitted automation does not make the same")
        print("promises the piston did:\n")
        for name, why in lost:
            print(f"  {name}\n      {why}")
        print()
        return 1
    if "commitments" in wanted:
        print("GATE PASSED - every promise the piston makes survives into the "
              "emitted automation.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Golden-fixture acceptance test (COMPILER_SPEC §6): compile the real corpus
piston and compare SEMANTICALLY (parsed YAML, comments ignored) against the
behaviorally-approved fixture. `alias` text is excluded from comparison (the
fixture's aliases carry hand-written descriptions); everything else must
match. Run: .venv/Scripts/python test_compile_fixtures.py"""

import json
import re
import sys

import yaml

from shim.compiler import compile_piston

# The fixture's own hash -> entity mapping (fixture header, 12_Cave_motion_V2)
CAVE_RESOLUTION_MAP = {
    ":d313c63940ae1a4dcd8dae46c940b8bb:": {
        "name": "Cave motion A",
        "attr_bindings": {"motion": "binary_sensor.cave_motion_a"},
        "cmd_bindings": {},
    },
    ":70dc91546bba4d51ff162f830ae72610:": {
        "name": "Cave motion B",
        "attr_bindings": {"motion": "binary_sensor.cave_motion_b"},
        "cmd_bindings": {},
    },
    ":791b45ec63ada4b93cf1eb74c2cbeff6:": {
        "name": "Cave Light",
        "attr_bindings": {"switch": "light.cave_light"},
        "cmd_bindings": {"on": "light.cave_light", "off": "light.cave_light"},
    },
    ":5a0d2c765d7779900ff56de2c8d6b578:": {
        "name": "Lumen sensor",
        "attr_bindings": {"illuminance": "sensor.cave_lumen"},
        "cmd_bindings": {},
    },
}


def _normalize(node):
    """Drop alias keys; collapse whitespace inside strings (template blocks)."""
    if isinstance(node, dict):
        return {k: _normalize(v) for k, v in sorted(node.items()) if k != "alias"}
    if isinstance(node, list):
        return [_normalize(i) for i in node]
    if isinstance(node, str):
        return re.sub(r"\s+", " ", node).strip()
    return node


def main() -> int:
    with open("test-pistons/12_Cave_motion_V2.json", encoding="utf-8") as f:
        entry = json.load(f)

    result = compile_piston(entry["piston"], "12cavemotionv2", entry["name"],
                            CAVE_RESOLUTION_MAP)
    assert result["target"] == "yaml", f"unexpected routing: {result['reasons']}"

    with open("test-pistons/fixtures/12_Cave_motion_V2.expected.yaml", encoding="utf-8") as f:
        expected = _normalize(yaml.safe_load(f.read()))
    actual = _normalize(yaml.safe_load(result["yaml"]))

    if actual == expected:
        print("PASS — Cave Motion compiles to the approved fixture (semantic match)")
        return 0

    print("FAIL — semantic diff:\n")
    print("--- expected ---")
    print(yaml.dump(expected, sort_keys=False))
    print("--- actual ---")
    print(yaml.dump(actual, sort_keys=False))
    print("--- raw output ---")
    print(result["yaml"])
    return 1




def test_else_on_trigger_only_if():
    """Regression (semantic-audit find + code review, 2026-07-19): an
    'if X changes to Y THEN..ELSE..' must wake on ANY change of the attribute
    (webCoRE subscribes to the attribute; the opposite transition runs the
    else) -> routes to PyScript with exactly ONE plain any-change trigger —
    never an edge-filtered trigger, never duplicate decorators."""
    import ast
    from shim.compiler import compile_piston
    reso = {":sw:": {"name": "Master", "attr_bindings": {"switch": "switch.master"},
                     "cmd_bindings": {}},
            ":lt:": {"name": "Mirror", "attr_bindings": {},
                     "cmd_bindings": {"on": "light.mirror", "off": "light.mirror"}},
            "$system": {}}
    cond_on = {"t": "condition", "ct": "t", "co": "changes_to",
               "lo": {"t": "p", "d": [":sw:"], "a": "switch", "g": "any"},
               "ro": {"t": "c", "c": "on", "vt": "enum"}}
    cond_off = {"t": "condition", "ct": "t", "co": "changes_to",
                "lo": {"t": "p", "d": [":sw:"], "a": "switch", "g": "any"},
                "ro": {"t": "c", "c": "off", "vt": "enum"}}
    piston = {"v": [], "s": [{"$": 1, "t": "if", "tcp": "c", "o": "and",
        "c": [cond_on],
        "s": [{"t": "action", "$": 2, "d": [":lt:"], "k": [{"c": "on", "p": []}]}],
        "e": [{"t": "action", "$": 3, "d": [":lt:"], "k": [{"c": "off", "p": []}]}]}]}

    for label, conds in [("one comparison", [cond_on]),
                         ("two comparisons same entity", [cond_on, cond_off])]:
        piston["s"][0]["c"] = conds
        r = compile_piston(piston, "mirror01", "Mirror", reso, {})
        assert r["target"] == "pyscript", f"{label}: expected pyscript, got {r['target']}"
        ast.parse(r["code"])
        trigs = [l.strip() for l in r["code"].splitlines()
                 if l.strip().startswith("@state_trigger")]
        assert len(trigs) == 1, f"{label}: {len(trigs)} state triggers, want 1 (dedup)"
        assert '"switch.master"' in trigs[0] and "==" not in trigs[0],             f"{label}: trigger must be plain any-change: {trigs[0]}"
    print("PASS — else-on-trigger-only-if: any-change wake, single deduped trigger")
    return 0




def test_unavailable_sensor_fails_closed():
    """A sensor going unavailable must never SATISFY a condition — for every
    operator, positive or negative (COMPILER_DECISIONS_DEPLOY §2: silent dead
    or spuriously-firing automations are the worst failure mode). Regression
    for the fail-open bug the 2026-07-20 review found: the old
    float(default=1.0e9) sentinel failed OPEN for > / >= / outside-range.
    We render each emitted template with the sensor unavailable and assert it
    evaluates False."""
    import re
    from shim.compiler import compile_piston
    try:
        from jinja2 import Environment
    except ImportError:
        print("SKIP — jinja2 unavailable"); return 0

    reso = {":s:": {"name": "Lux", "attr_bindings": {"illuminance": "sensor.lux"},
                    "cmd_bindings": {}},
            ":l:": {"name": "L", "attr_bindings": {},
                    "cmd_bindings": {"on": "light.l"}}, "$system": {}}

    def cond(co, v, v2=None):
        c = {"t": "condition", "ct": "c", "co": co,
             "lo": {"t": "p", "d": [":s:"], "a": "illuminance", "g": "any"},
             "ro": {"t": "c", "c": v, "vt": "integer"}}
        if v2 is not None:
            c["ro2"] = {"t": "c", "c": v2, "vt": "integer"}
        return c

    # a fake HA template environment: unavailable sensor
    def is_number(x):
        try:
            float(x); return x not in ("unknown", "unavailable", "none")
        except (TypeError, ValueError):
            return False
    env = Environment()
    env.filters["is_number"] = is_number
    env.filters["float"] = lambda x, d=0.0: (float(x) if is_number(x) else d)

    def evaluate(tmpl):
        body = tmpl.strip()[2:-2]
        return env.from_string("{{ (" + body + ") | string }}").render(
            states=lambda e: "unavailable")

    failures = []
    for co, v, v2 in [("is_greater_than", 50, None),
                      ("is_greater_than_or_equal_to", 50, None),
                      ("is_less_than", 50, None),
                      ("is_between", 10, 50),
                      ("is_not_between", 10, 50),
                      ("is_inside_of_range", 10, 50),
                      ("is_outside_of_range", 10, 50)]:
        piston = {"v": [], "s": [{"$": 1, "t": "if", "tcp": "c", "o": "and",
            "c": [{"t": "condition", "ct": "t", "co": "changes_to",
                   "lo": {"t": "p", "d": [":s:"], "a": "illuminance", "g": "any"},
                   "ro": {"t": "c", "c": 1, "vt": "integer"}},
                  cond(co, v, v2)],
            "s": [{"t": "action", "$": 2, "d": [":l:"], "k": [{"c": "on", "p": []}]}],
            "e": []}]}
        r = compile_piston(piston, "u", "U", reso, {})
        if r["target"] != "yaml":
            continue
        import yaml as _y
        auto = _y.safe_load(r["yaml"])[0]
        tmpls = [c["value_template"] for c in auto.get("conditions", [])
                 if c.get("condition") == "template"]
        for t in tmpls:
            if evaluate(t) != "False":
                failures.append((co, t, evaluate(t)))
    if failures:
        print("FAIL — unavailable sensor satisfied a condition (fail-open):")
        for co, t, got in failures:
            print(f"   {co}: {t} -> {got}")
        return 1
    print("PASS — every numeric condition fails closed when the sensor is unavailable")
    return 0


if __name__ == "__main__":
    rc = main()
    rc = test_else_on_trigger_only_if() or rc
    rc = test_unavailable_sensor_fails_closed() or rc
    sys.exit(rc)

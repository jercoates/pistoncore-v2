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


if __name__ == "__main__":
    rc = main()
    rc = test_else_on_trigger_only_if() or rc
    sys.exit(rc)

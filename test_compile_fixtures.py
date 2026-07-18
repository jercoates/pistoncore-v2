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


if __name__ == "__main__":
    sys.exit(main())

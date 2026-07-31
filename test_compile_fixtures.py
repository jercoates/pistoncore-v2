"""Golden-fixture acceptance test (COMPILER_SPEC §6): compile the real corpus
piston and compare SEMANTICALLY (parsed YAML, comments ignored) against the
behaviorally-approved fixture. `alias` text is excluded from comparison (the
fixture's aliases carry hand-written descriptions); everything else must
match. Run: .venv/Scripts/python test_compile_fixtures.py"""

import json
import os
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
    """YAML-FIRST (foundational since v1): 'if X changes to Y THEN..ELSE..' must
    wake on ANY change of the attribute (webCoRE subscribes to the attribute; the
    opposite transition runs the else) — and YAML expresses that natively with
    ONE bare any-change state trigger (entity_id, no to/from) + a re-check
    condition that routes then vs else. NOT PyScript (that's the valve, never the
    answer when YAML can do it), NOT edge-filtered to:/from: triggers (those miss
    multi-value transitions), NOT duplicate triggers when two conditions share an
    entity (deduped)."""
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
        assert r["target"] == "yaml", f"{label}: expected yaml (YAML-first), got {r['target']}"
        y = r["yaml"]
        trigs = [l for l in y.splitlines() if l.strip().startswith("- trigger:")]
        assert len(trigs) == 1, f"{label}: {len(trigs)} triggers, want 1 (deduped bare any-change)"
        assert "trigger: state" in trigs[0], f"{label}: want a state trigger: {trigs[0]}"
        # bare any-change: the switch entity is the wake, with NO to:/from: filter
        assert "switch.master" in y and "\n      to:" not in y and "\n      from:" not in y, \
            f"{label}: trigger must be a bare any-change (no to/from filter)"
        # the re-check condition routes then vs else on each change
        assert "states('switch.master') == 'on'" in y, f"{label}: missing re-check condition"
    print("PASS — else-on-trigger-only-if: YAML bare any-change wake + re-check, deduped")
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


def test_readings_inside_entities():
    """A reading that lives in a FIELD must be read as a field, in BOTH bands,
    with the vocab's unit conversion applied.

    WHY THIS EXISTS (2026-07-30): the snapshot corpus cannot catch this. Its
    synthetic map binds attributes to sensor.* entities, where reading the
    entity's state is already correct — so a thermostat reading "heat" instead
    of 72, or a dimmer reading "on" instead of 60, produced NO drift. The bug
    shipped in the YAML band, was found by hand against Jeremy's live install,
    and then shipped again in the PyScript band for the same reason. Three
    times the pass count said everything was fine.

    Also asserts the two bands AGREE, which is the actual property that
    matters: Resolver.read_spec() is the single decision and each band only
    spells it (one translation source, routing separate)."""
    from shim.compiler.resolve import Resolver
    import shim.compiler.emit_pyscript as EP

    reso = {
        ":c:": {"name": "Stat", "cmd_bindings": {},
                "attr_bindings": {"temperature": "climate.t"}},
        ":l:": {"name": "Lamp", "cmd_bindings": {"on": "light.l"},
                "attr_bindings": {"level": "light.l"}},
        ":m:": {"name": "Spk", "cmd_bindings": {},
                "attr_bindings": {"volume": "media_player.m"}},
        ":k:": {"name": "Lock", "cmd_bindings": {},
                "attr_bindings": {"lock": "lock.k", "last_code_name": "lock.k"},
                "attr_field_bindings": {"last_code_name": "last_code_name"}},
        "$system": {},
    }
    r = Resolver({"v": []}, reso, {})
    cls = next(c for _, c in vars(EP).items()
               if isinstance(c, type) and hasattr(c, "_read"))
    py = cls.__new__(cls); py.resolver = r

    # (entity, attr, expected field, expected scale factors or None)
    cases = [
        ("climate.t", "temperature", "current_temperature", None),
        ("light.l", "level", "brightness", (100.0, 255.0)),
        ("media_player.m", "volume", "volume_level", (100.0, 1.0)),
        ("lock.k", "last_code_name", "last_code_name", None),   # raw feed
        ("lock.k", "lock", None, None),                         # state-backed
        ("sensor.b", "battery", None, None),                    # state-backed
    ]
    failures = []
    for entity, attr, want_field, want_scale in cases:
        field, scale = r.read_spec(entity, attr)
        if field != want_field:
            failures.append(f"{attr} on {entity}: field {field!r}, expected {want_field!r}")
            continue
        got_scale = r.scale_factors(scale, "") if scale else None
        if got_scale != want_scale:
            failures.append(f"{attr} on {entity}: scale {got_scale}, expected {want_scale}")
            continue
        yaml_read = r.read_expr(entity, attr)
        py_read = py._read(entity, attr)
        if want_field is None:
            # state-backed: neither band may reach for an attribute
            if "state_attr" in yaml_read or "_sa(" in py_read:
                failures.append(f"{attr} on {entity}: read as a field but its "
                                f"value IS the state — {yaml_read} / {py_read}")
        else:
            if "state_attr" not in yaml_read or want_field not in yaml_read:
                failures.append(f"{attr} on {entity}: YAML did not read the field — {yaml_read}")
            if "_sa(" not in py_read or want_field not in py_read:
                failures.append(f"{attr} on {entity}: PyScript did not read the field — {py_read}")
            if want_scale and (str(int(want_scale[0])) not in yaml_read
                               or str(want_scale[0]) not in py_read):
                failures.append(f"{attr} on {entity}: unit conversion missing — "
                                f"{yaml_read} / {py_read}")

    # end to end: a condition on a thermostat must not compile to states()
    from shim.compiler import compile_piston
    piston = {"v": [], "s": [{
        "t": "if", "$": 1,
        "c": [{"t": "condition", "ct": "c", "co": "is_greater_than",
               "lo": {"t": "p", "d": [":c:"], "a": "temperature", "g": "any"},
               "ro": {"t": "c", "c": 72, "vt": "integer"}}],
        "s": [{"t": "action", "$": 2, "d": [":l:"], "k": [{"c": "on", "p": []}]}],
        "e": []}]}
    out = compile_piston(piston, "u", "U", reso, {})
    body = out.get("yaml") or out.get("pyscript") or ""
    if "current_temperature" not in body:
        failures.append("end-to-end: a thermostat condition never mentioned "
                        "current_temperature — it is reading the entity state "
                        f"({out.get('target')} band)")

    # TRIGGERS, not just reads. A pyscript @state_trigger built from the bare
    # entity watches its STATE — a thermostat trigger would fire on mode
    # changes and compare against "heat". DOMAIN.name.attr is pyscript's
    # documented attribute form (VERIFIED 2026-07-30 against the pyscript
    # reference: "you can also use state variable attributes in the trigger
    # expression, with an identifier of the form DOMAIN.name.attr").
    trig_cases = [
        # (device, attr, threshold, must appear, must NOT appear)
        (":c:", "temperature", 72, "climate.t.current_temperature", None),
        # scaled: the THRESHOLD converts into HA units (webCoRE 50 of 100 ->
        # 127.5 of 255), never the reading, which would blow up on a light
        # that is off and has no brightness at all.
        (":l:", "level", 50, "light.l.brightness", "> 50"),
    ]
    for dref, a, thresh, must, must_not in trig_cases:
        em = EP._PyEmitter.__new__(EP._PyEmitter)
        em.resolver = r; em.decorators = []; em.piston_id = "u"; em.piston_name = "U"
        cond = {"t": "condition", "ct": "t", "co": "rises_above",
                "lo": {"t": "p", "d": [dref], "a": a, "g": "any"},
                "ro": {"t": "c", "c": thresh, "vt": "integer"}}
        try:
            em._trigger_decorator(cond, 1, {})
        except Exception as exc:                                   # noqa: BLE001
            failures.append(f"trigger on {a}: raised {type(exc).__name__}: {exc}")
            continue
        exprs = " ".join(x for d in em.decorators for x in d.get("exprs", []))
        if must not in exprs:
            failures.append(f"trigger on {a}: watches the entity state, not the "
                            f"field — {exprs[:120]}")
        if must_not and must_not in exprs:
            failures.append(f"trigger on {a}: compares HA units against a webCoRE "
                            f"threshold — {exprs[:120]}")

    if failures:
        print("FAIL — readings that live inside an entity:")
        for f in failures:
            print(f"   {f}")
        return 1
    print("PASS — field-backed readings read the field, both bands, "
          "with units, in conditions and triggers")
    return 0


def test_ha_service_feed():
    """Raw HA services offered as commands, and the hybrid rule that keeps
    them from duplicating the vocab.

    WHY (2026-07-30): this feed shipped ON by default with NO automated
    coverage — it had only ever been checked by hand against Jeremy's live
    install. The compiler tests don't touch it: they start from a resolution
    map, and this runs earlier, building the payload the editor sees.

    The hybrid rule is the part worth guarding. Vocab wins where it has a
    command; raw fills the gaps. If dedupe breaks, every dimmer sprouts a
    `light.turn_on` next to webCoRE's own `on`, and the editor becomes a mess
    nobody can navigate — which is exactly the failure Jeremy would see first
    and could not diagnose."""
    from shim.device_pipeline import ha_service_commands, services_covered_by_vocab
    import json as _json

    services = {
        "light": {
            "turn_on": {"fields": {"brightness_pct": {"selector": {"number": {}}}}},
            "turn_off": {"fields": {}},
            "some_odd_service": {"fields": {}},
        },
        "vacuum": {
            "send_command": {"fields": {"command": {"selector": {"text": {}}},
                                        "params": {"selector": {"object": {}}}}},
        },
    }
    states = {"light.l": {"entity_id": "light.l", "state": "on", "attributes": {}}}
    failures = []

    cmds = ha_service_commands(services, {"light"}, states=states, members=["light.l"])
    names = [c["n"] for c in cmds]
    if "light.turn_on" not in names:
        failures.append(f"a plain service was not offered at all: {names}")
    if any("." not in n for n in names):
        failures.append(f"names must stay domain-qualified (the name IS the service): {names}")
    # parameters come from the service's own fields, not the vocab
    on = next((c for c in cmds if c["n"] == "light.turn_on"), None)
    if on is not None and not on.get("p"):
        failures.append("light.turn_on offered no parameters, but the service declares "
                        "brightness_pct — parameters must come from HA's own field list")

    # the hybrid rule: a device whose vocab command already reaches turn_on
    # must not ALSO be offered the raw service
    try:
        with open("webcore_vocab.json", encoding="utf-8") as f:
            vocab = _json.load(f)
    except OSError:
        print("SKIP — vocab unavailable"); return 0
    covered = services_covered_by_vocab({"on": "light.l", "off": "light.l"}, vocab)
    if "light.turn_on" not in covered:
        failures.append("a device bound to webCoRE 'on' did not mark light.turn_on as "
                        f"covered — the raw service would duplicate it. covered={sorted(covered)}")
    # ...and a service the vocab has no word for stays available
    if "light.some_odd_service" in covered:
        failures.append("a service the vocab cannot reach was wrongly treated as covered")

    if failures:
        print("FAIL — HA service feed:")
        for f in failures:
            print(f"   {f}")
        return 1
    print("PASS — HA services feed as commands; vocab-covered ones are not duplicated")
    return 0


def test_emitted_output_is_valid():
    """Everything the compiler emits must PARSE, and the pyscript modules must
    not reference a name nothing defines.

    WHY (2026-07-30): the snapshot test compares emitted code as TEXT. It has
    no idea whether that text is valid YAML, valid Python, or refers to
    variables that exist — so a broken emitter produces confident, stable,
    unrunnable output and the suite stays green. That is exactly how
    `_s(_device)` reached the corpus: syntactically fine, `_device` never
    assigned. Runs over the recorded snapshot, so it covers every piston.

    The undefined-name pass is deliberately conservative — it only flags a
    Load of a name with no binding anywhere in the module, after allowing
    builtins and the globals pyscript injects."""
    import ast
    import builtins
    import json as _json
    try:
        import yaml as _yaml
    except ImportError:
        print("SKIP — pyyaml unavailable"); return 0

    snap_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "test-compile-snapshots.json")
    if not os.path.exists(snap_path):
        print("SKIP — no snapshot recorded yet"); return 0
    with open(snap_path, encoding="utf-8") as f:
        snap = _json.load(f)

    # names pyscript injects into every module's namespace
    PYSCRIPT_GLOBALS = {
        "state", "service", "task", "log", "pyscript", "event", "hass", "sun",
        "state_trigger", "time_trigger", "event_trigger", "service_call",
        "task_unique", "time_active", "state_active", "mqtt_trigger",
        "webhook_trigger", "pyscript_compile", "pyscript_executor",
    }

    def bound_names(tree):
        out = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.add(node.name)
                args = node.args
                for a in list(args.args) + list(args.kwonlyargs) + list(args.posonlyargs):
                    out.add(a.arg)
                if args.vararg:
                    out.add(args.vararg.arg)
                if args.kwarg:
                    out.add(args.kwarg.arg)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                out.add(node.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    out.add((a.asname or a.name).split(".")[0])
            elif isinstance(node, ast.ExceptHandler) and node.name:
                out.add(node.name)
            elif isinstance(node, ast.Global):
                out.update(node.names)
            elif isinstance(node, ast.comprehension):
                for t in ast.walk(node.target):
                    if isinstance(t, ast.Name):
                        out.add(t.id)
        return out

    failures = []
    n_yaml = n_py = 0
    for name, rec in sorted(snap.items()):
        if rec.get("outcome") != "compiled":
            continue
        code = rec.get("code") or ""
        if rec.get("band") == "yaml":
            n_yaml += 1
            try:
                _yaml.safe_load(code)
            except Exception as exc:                                # noqa: BLE001
                failures.append(f"{name}: emitted YAML does not parse — {str(exc)[:100]}")
        else:
            n_py += 1
            try:
                tree = ast.parse(code)
            except SyntaxError as exc:
                failures.append(f"{name}: emitted PyScript does not parse — "
                                f"line {exc.lineno}: {exc.msg}")
                continue
            known = bound_names(tree) | PYSCRIPT_GLOBALS | set(dir(builtins))
            used = {n.id for n in ast.walk(tree)
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
            unknown = sorted(used - known)
            if unknown:
                failures.append(f"{name}: references names nothing defines "
                                f"(NameError at runtime): {unknown}")

    if failures:
        print("FAIL — emitted output is not valid:")
        for f in failures:
            print(f"   {f}")
        return 1
    print(f"PASS — all emitted output parses ({n_yaml} YAML, {n_py} PyScript) "
          f"with no undefined names")
    return 0


def test_templates_render_in_ha():
    """Every emitted Jinja template, rendered by HOME ASSISTANT'S OWN engine.

    WHY (2026-07-30): nothing else can catch a template that is valid Jinja
    but wrong about HA. This found `state_attr('sun.sun', 'next_sunrise')` —
    HA spells it next_rising, there is no next_sunrise, so the attribute came
    back None, `None | as_datetime` raised, and the whole condition errored at
    runtime. Two of Jeremy's chicken-coop pistons had been silently dead. The
    YAML parsed, the snapshot was stable, every unit test passed.

    SKIPS when no HA is configured or reachable — this is a bench check, not
    a hard dependency. `trigger` is expected to be undefined here: it only
    exists while an automation is actually firing, so those are filtered."""
    import urllib.error
    import urllib.request
    try:
        from shim import ha_client
        cfg = ha_client._load_config() or {}
        url = (cfg.get("ha_url") or "").rstrip("/")
        token = cfg.get("ha_token") or ""
    except Exception:                                              # noqa: BLE001
        print("SKIP — no HA configured"); return 0
    if not url or not token:
        print("SKIP — no HA configured"); return 0

    snap_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "test-compile-snapshots.json")
    if not os.path.exists(snap_path):
        print("SKIP — no snapshot recorded yet"); return 0
    with open(snap_path, encoding="utf-8") as f:
        snap = json.load(f)

    def collect(node, out):
        if isinstance(node, dict):
            for v in node.values():
                if isinstance(v, str) and "{{" in v:
                    out.append(v)
                else:
                    collect(v, out)
        elif isinstance(node, list):
            for x in node:
                collect(x, out)

    templates, seen = [], set()
    for name, rec in sorted(snap.items()):
        if rec.get("outcome") != "compiled" or rec.get("band") != "yaml":
            continue
        for auto in (yaml.safe_load(rec["code"]) or []):
            found = []
            collect(auto, found)
            for t in found:
                if t not in seen:
                    seen.add(t)
                    templates.append((name, t))

    failures, checked = [], 0
    for name, t in templates:
        req = urllib.request.Request(
            url + "/api/template", method="POST",
            data=json.dumps({"template": t}).encode(),
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=20).read()
            checked += 1
        except urllib.error.HTTPError as exc:
            msg = exc.read().decode()[:200]
            # `trigger` only exists while an automation is firing
            if "'trigger' is undefined" in msg:
                checked += 1
                continue
            failures.append((name, t[:90], msg))
        except Exception:                                          # noqa: BLE001
            print("SKIP — HA unreachable"); return 0

    if failures:
        print("FAIL — templates Home Assistant cannot render:")
        for name, t, msg in failures:
            print(f"   {name}\n      {t}\n      -> {msg[:150]}")
        return 1
    print(f"PASS — all {checked} emitted templates render in Home Assistant")
    return 0


if __name__ == "__main__":
    rc = main()
    rc = test_else_on_trigger_only_if() or rc
    rc = test_unavailable_sensor_fails_closed() or rc
    rc = test_readings_inside_entities() or rc
    rc = test_ha_service_feed() or rc
    rc = test_emitted_output_is_valid() or rc
    rc = test_templates_render_in_ha() or rc
    sys.exit(rc)

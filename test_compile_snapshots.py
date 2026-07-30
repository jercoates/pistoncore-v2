"""Golden-snapshot regression for the compiler.

WHY (Jeremy, 2026-07-23: "you need to make sure you dont break what works"):
the corpus check only proved pistons ANALYZE — it never compiled them, so a
change in emitted YAML/PyScript was invisible. Three separate edits to
_emit_branch landed in one day with no automated check on output.

WHAT: compile every test-pistons/*.json against a SYNTHETIC resolution map
derived from the piston's own device references (deterministic, needs nothing
from a live instance), then record the exact result — band + emitted code, or
the exact error. Errors are recorded outcomes too: a piston that currently
fails is part of "what works" in the sense that CHANGING it must be deliberate.

USE:
    python test_compile_snapshots.py            # compare against snapshots (exit 1 on drift)
    python test_compile_snapshots.py --update   # re-record after an intended change

The snapshot file is committed. A diff on it in review IS the regression report.
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shim.compiler import compile_piston                      # noqa: E402
from shim.compiler import emit_yaml as _emit_yaml             # noqa: E402

SNAPSHOT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "test-compile-snapshots.json")


def _collect(node, hashes, attrs, cmds, globs):
    """Walk a piston collecting device refs, attribute names and command names."""
    if isinstance(node, list):
        for x in node:
            _collect(x, hashes, attrs, cmds, globs)
        return
    if not isinstance(node, dict):
        return
    lo = node.get("lo")
    if isinstance(lo, dict):
        for d in lo.get("d") or []:
            (globs if str(d).startswith("@") else hashes).add(str(d))
        if lo.get("a"):
            attrs.add(str(lo["a"]))
    if node.get("t") == "action":
        for d in node.get("d") or []:
            (globs if str(d).startswith("@") else hashes).add(str(d))
        for k in node.get("k") or []:
            if isinstance(k, dict) and k.get("c"):
                cmds.add(str(k["c"]))
    for key in ("s", "e", "ei", "cs", "c", "r", "k"):
        if key in node:
            _collect(node[key], hashes, attrs, cmds, globs)


def _vocab():
    with open(os.path.join(os.path.dirname(SNAPSHOT), "webcore_vocab.json"),
              encoding="utf-8") as f:
        return json.load(f)


def _domain_choices(vocab):
    """command -> the HA domain it's actually for, and attribute -> likewise,
    read from the vocab's own translation rules.

    WHY (2026-07-26): the map used to bind EVERY command to `light.dev0`, so
    47 of 84 pistons "errored" with 'no HA service mapping for lock on domain
    light' — an artefact of the fake map, not a real result. That made the
    harness a drift detector wearing a coverage number's clothes: it never
    exercised the emission path for anything that isn't a light, which is
    where the silent bugs have actually been. Binding each command to a domain
    the vocab says it belongs to makes the harness compile those pistons for
    real."""
    cmd_domain, attr_domain = {}, {}
    for section in ("commands", "virtualCommands"):
        for name, entry in vocab.get(section, {}).items():
            for rule in (entry.get("ha") or []):
                if not isinstance(rule, dict):
                    continue
                dom = rule.get("domain")
                if dom and dom not in ("*", "_any"):
                    cmd_domain[name] = dom
                    break
    for name, entry in vocab.get("attributes", {}).items():
        for rule in (entry.get("ha") or []):
            if not isinstance(rule, dict):
                continue
            dom = rule.get("domain")
            if dom and dom not in ("*", "_any"):
                attr_domain[name] = dom
                break
    return cmd_domain, attr_domain


# Stand-ins for the entities PistonCore resolves from Settings rather than from
# the piston (the TTS engine, the email notifier, the location-mode helper, the
# alarm panel). Without these, every Speak / Send email / alarm / location-mode
# piston errors on missing configuration instead of compiling — so the harness
# never covered them, including the command translation migrated this session.
_SYSTEM_ENTITIES = {
    "tts": "tts.dev_engine",
    "email": "notify.dev_email",
    "mode": "input_select.dev_location_mode",
    "alarmSystemStatus": "alarm_control_panel.dev_panel",
    "hsmStatus": "sensor.dev_hub_hsm_status",
}


def _synthetic_maps(piston):
    """A deterministic resolution map covering every device ref in the piston.

    Every device gets every attribute and every command seen anywhere in that
    piston — deliberately over-broad, because the point is a STABLE input. The
    entity DOMAINS are realistic though (see _domain_choices): a lock command
    binds to a lock entity, so the compiler runs its real emission path."""
    hashes, attrs, cmds, globs = set(), set(), set(), set()
    _collect(piston.get("s") or [], hashes, attrs, cmds, globs)
    # local device variables resolve to hashes
    for v in piston.get("v") or []:
        if v.get("t") == "device":
            for h in ((v.get("v") or {}).get("d") or []):
                hashes.add(str(h))
    # device refs that are local-variable NAMES are resolved by the Resolver
    # itself, so only real hashes need entries; keep names out of the map.
    names = {str(v.get("n")) for v in (piston.get("v") or [])}
    real = sorted(h for h in hashes if h not in names)

    # Virtual commands (flashLevel, fadeLevel, setHSLColor, adjustLevel, …) don't
    # resolve on their OWN name — they delegate to the base capability they
    # "require" (vocab `r`, e.g. fadeLevel -> setLevel). A real device that
    # supports the virtual command always has the base command bound, so the
    # synthetic map must too, or these pistons error on a missing base binding
    # that wouldn't be missing in production. Fold each seen command's `r`
    # requirements into the binding set.
    cmd_domain, attr_domain = {}, {}
    try:
        vocab = _vocab()
        _vc = {**vocab.get("commands", {}), **vocab.get("virtualCommands", {})}
        for c in list(cmds):
            for base in (_vc.get(c, {}) or {}).get("r", []) or []:
                cmds.add(str(base))
        cmd_domain, attr_domain = _domain_choices(vocab)
    except (OSError, ValueError):
        pass

    attrs = sorted(attrs) or ["switch"]
    cmds = sorted(cmds) or ["on"]

    # Only VOCAB commands get bound. Real cmd_bindings come from mapping HA
    # entity signals to webCoRE capabilities, so a DRIVER command (clearImages,
    # stopColorLoop) is never bound on a real device — it has to reach the
    # integration's passthrough instead. Binding everything made the harness
    # claim those were ordinary commands and hid that path entirely.
    _vocab_cmds = set()
    try:
        _v = _vocab()
        _vocab_cmds = set(_v.get("commands", {})) | set(_v.get("virtualCommands", {}))
    except (OSError, ValueError):
        _vocab_cmds = set(cmds)
    cmds = [c for c in cmds if c in _vocab_cmds] or ["on"]

    def _bindings(slug):
        # attributes read from an entity of their own domain; commands act on
        # one of theirs. Anything the vocab has no domain for keeps the old
        # stand-in, so unmapped things still produce a stable, recorded result.
        return (
            {a: f"{attr_domain.get(a, 'sensor')}.{slug}_{a.lower()}" for a in attrs},
            {c: f"{cmd_domain.get(c, 'light')}.{slug}" for c in cmds},
        )

    reso = {}
    for i, h in enumerate(real):
        slug = f"dev{i}"
        attr_b, cmd_b = _bindings(slug)
        reso[h] = {"name": f"Device {i}", "attr_bindings": attr_b, "cmd_bindings": cmd_b}
    globals_map = {g: {"t": "device", "v": {"d": real[:1] or [":synthetic:"]}}
                   for g in sorted(globs)}
    if not real:
        attr_b, cmd_b = _bindings("dev0")
        reso[":synthetic:"] = {"name": "Device 0",
                               "attr_bindings": attr_b, "cmd_bindings": cmd_b}
    # A command passthrough, as a real bridged/remote/vacuum device has — the
    # route a DRIVER command takes when Home Assistant has no vocabulary for it
    # (device_pipeline.detect_passthroughs). Without this the harness never
    # exercises that path, and every driver command in the corpus just errors.
    for hashed_id, entry in reso.items():
        if hashed_id == "$system":
            continue
        members = entry.get("attr_bindings") or {}
        entry["passthrough"] = {
            "service": "hubitat.send_command",
            "command_field": "command",
            "args_field": "args",
            "target_field": "entity_id",
            "entity_id": sorted(members.values())[0] if members else "switch.dev0",
        }
    reso["$system"] = dict(_SYSTEM_ENTITIES)
    return reso, globals_map


def run():
    results = {}
    for path in sorted(glob.glob(os.path.join(os.path.dirname(SNAPSHOT),
                                              "test-pistons", "*.json"))):
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        piston = doc.get("piston", doc)
        reso, globs = _synthetic_maps(piston)
        _emit_yaml._MEDIA_CFG = {}          # keep media routing out of snapshots
        try:
            out = compile_piston(piston, "snap", doc.get("name") or name, reso, globs)
            body = out.get("yaml") or out.get("pyscript") or out.get("code") or ""
            results[name] = {
                "outcome": "compiled",
                "band": out.get("target"),
                "kind": out.get("kind"),
                "code": body,
            }
        except Exception as exc:                                  # noqa: BLE001
            results[name] = {
                "outcome": "error",
                "error_type": type(exc).__name__,
                "error": str(exc)[:300],
            }
    return results


def summarize(results):
    comp = sum(1 for r in results.values() if r["outcome"] == "compiled")
    bands = {}
    for r in results.values():
        if r["outcome"] == "compiled":
            bands[r.get("band")] = bands.get(r.get("band"), 0) + 1
    return comp, len(results) - comp, bands


def main():
    update = "--update" in sys.argv
    results = run()
    comp, errs, bands = summarize(results)
    print(f"compiled: {comp}  errored: {errs}  bands: {bands}")

    if update or not os.path.exists(SNAPSHOT):
        with open(SNAPSHOT, "w", encoding="utf-8", newline="\n") as f:
            json.dump(results, f, indent=1, ensure_ascii=False, sort_keys=True)
            f.write("\n")
        print(f"snapshots written: {SNAPSHOT}")
        return 0

    with open(SNAPSHOT, encoding="utf-8") as f:
        base = json.load(f)

    drift = []
    for name in sorted(set(base) | set(results)):
        if name not in base:
            drift.append((name, "NEW piston (not in snapshot)"))
        elif name not in results:
            drift.append((name, "MISSING piston (was in snapshot)"))
        elif base[name] != results[name]:
            b, r = base[name], results[name]
            if b.get("outcome") != r.get("outcome"):
                drift.append((name, f"outcome {b.get('outcome')} -> {r.get('outcome')}"))
            elif b.get("band") != r.get("band"):
                drift.append((name, f"band {b.get('band')} -> {r.get('band')}"))
            elif b.get("error") != r.get("error"):
                drift.append((name, f"error changed: {r.get('error')[:80]}"))
            else:
                drift.append((name, "emitted code changed"))

    if not drift:
        print("NO DRIFT - every piston compiles to byte-identical output.")
        return 0
    print(f"\nDRIFT in {len(drift)} piston(s):")
    for name, why in drift:
        print(f"  {name}: {why}")
    print("\nIf these changes are intended, re-record with --update and commit the diff.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

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


def _synthetic_maps(piston):
    """A deterministic resolution map covering every device ref in the piston.

    Deliberately over-broad: every device gets every attribute and every command
    seen anywhere in that piston. The point is a STABLE input, not a realistic
    one — the snapshot records whatever the compiler does with it."""
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

    attrs = sorted(attrs) or ["switch"]
    cmds = sorted(cmds) or ["on"]
    reso = {}
    for i, h in enumerate(real):
        slug = f"dev{i}"
        reso[h] = {
            "name": f"Device {i}",
            "attr_bindings": {a: f"sensor.{slug}_{a.lower()}" for a in attrs},
            "cmd_bindings": {c: f"light.{slug}" for c in cmds},
        }
    globals_map = {g: {"t": "device", "v": {"d": real[:1] or [":synthetic:"]}}
                   for g in sorted(globs)}
    if not real:
        reso[":synthetic:"] = {
            "name": "Device 0",
            "attr_bindings": {a: f"sensor.dev0_{a.lower()}" for a in attrs},
            "cmd_bindings": {c: "light.dev0" for c in cmds},
        }
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

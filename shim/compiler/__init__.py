"""PistonCore v2 compiler (COMPILER_SPEC.md) — turns saved webCoRE piston JSON
into native HA YAML (classic band) or PyScript (pyscript/2.x band).

Pipeline: ANALYZE -> RESOLVE -> ROUTE -> EMIT. Read-only over piston JSON —
never mutates it (locked policy §1). Every emitted line comes from the
templates/compiler/ band files, never from Python strings — that is the
breaking-change insurance Recompile All depends on.

Routing (session 3): routing_table.json signatures force PyScript up front;
otherwise the YAML band tries first and anything it can't express
(NotYetImplemented) falls through to the PyScript band with the reason
recorded — "not compiled yet" in YAML means "runs via PyScript", never
"dropped" (make-it-work rule). UnresolvableDevice never falls through: a
missing device is a real user-facing error on either band.
"""

from .errors import CompilerError, NotYetImplemented, UnresolvableDevice  # noqa: F401
from .routing import pyscript_reasons
from . import emit_pyscript, emit_yaml


def compile_piston(piston: dict, piston_id: str, piston_name: str,
                   resolution_map: dict, globals_map: dict | None = None,
                   band: str = "auto") -> dict:
    """Returns {"target": "yaml"|"pyscript", "yaml"|"code": str, "reasons": [...],
    "auto_ids": [...]} — auto_ids is empty on the pyscript target (no HA
    automation entities; the module registers pyscript triggers instead).

    `band` is the user's compile-target preference (COMPILER_SPEC §3.2's
    "prefer PyScript for fidelity" option, Jeremy 2026-07-19 — a per-piston
    escape hatch for when the YAML translation misbehaves):
      "auto"     — routing table, then YAML, falling through to PyScript
      "pyscript" — always PyScript, even when YAML could express it
      "yaml"     — YAML only; if it can't be expressed, that's an honest
                   error rather than a silent switch of execution model
    The preference lives in PistonCore's own settings, NEVER in the piston
    JSON (read-only-compiler rule)."""
    if band == "pyscript":
        return emit_pyscript.compile_pyscript(
            piston, piston_id, piston_name, resolution_map, globals_map,
            ["forced to PyScript by your setting for this piston"])

    reasons = pyscript_reasons(piston)
    if band == "yaml":
        if reasons:
            raise NotYetImplemented(
                "this piston is set to YAML-only, but it uses features HA "
                "automations can't express: " + "; ".join(reasons[:3]),
                piston_id=piston_id, piston_name=piston_name)
        return emit_yaml.compile_yaml(piston, piston_id, piston_name,
                                      resolution_map, globals_map)

    if not reasons:
        try:
            return emit_yaml.compile_yaml(piston, piston_id, piston_name,
                                          resolution_map, globals_map)
        except NotYetImplemented as exc:
            reasons = [f"YAML band can't express it: {exc}"]
    return emit_pyscript.compile_pyscript(piston, piston_id, piston_name,
                                          resolution_map, globals_map, reasons)

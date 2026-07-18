"""PistonCore v2 compiler (COMPILER_SPEC.md) — turns saved webCoRE piston JSON
into native HA YAML (classic band) or PyScript (routed exceptions).

Pipeline: ANALYZE -> RESOLVE -> ROUTE -> EMIT. Read-only over piston JSON —
never mutates it (locked policy §1). Every emitted line comes from the
templates/compiler/ band files, never from Python strings — that is the
breaking-change insurance Recompile All depends on.

Session 1 scope (2026-07-18): intent patterns #1/#4 (trigger-gated action,
timed follow-up with TCP cancel) on the YAML band — the constructs the
approved Cave Motion golden fixture exercises. Everything else raises
NotYetImplemented naming the exact construct + statement, per the
make-it-work rule: those are scheduled work, not feature cuts.
"""

from .errors import CompilerError, NotYetImplemented, UnresolvableDevice  # noqa: F401
from .emit_yaml import compile_piston  # noqa: F401

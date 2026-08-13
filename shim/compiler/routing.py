"""ROUTE — how a piston has to be HANDLED, read off routing_table.json.

Two questions, ONE plan, because a piston has to be analyzed for ALL of the
ways it has to be handled — not until the first obstacle (Jeremy,
2026-08-07). Bailing at the first problem is what made the compiler throw
whole pistons over the wall to PyScript.

  1. What can HA not DO at all?   -> the PyScript failover (§3.2)
  2. What can HA not RUN AS ONE AUTOMATION?  -> the split rule (§3.2b)

Both lines MOVE as HA gains abilities, which is why both live in
routing_table.json and not in this file (HARD_RULES §3 + §8). PyScript is a
failover for what HA cannot do, and separately a thing a user can FORCE for
a whole piston (HARD_RULES §4) — forcing bypasses all of this.

Splitting is a CONSEQUENCE of what HA can run, never a style choice: the
piston as a whole is the intent (HARD_RULES §10), and the pieces stay
connected and in order.
"""

import json
from pathlib import Path

from .. import customize


def _load() -> dict:
    # re-read every compile (not cached) so a user's edit to the routing table
    # on the /data volume takes effect immediately, no restart — the routing
    # table decides what needs PyScript, and it's meant to be editable like
    # the maps and templates (Jeremy, 2026-07-20; COMPILER_DECISIONS_HOLDING
    # §E1: "edit the table, never the code").
    with open(customize.path("routing_table.json"), encoding="utf-8") as f:
        return json.load(f)


def piston_scope_commands() -> list:
    """Commands that act on PISTON state (variables, tiles, logs, piston
    control) rather than on a device. YAML has no way to express them, so they
    route to PyScript.

    This is ROUTING, not translation, which is why it lives in the routing
    table and not in the vocab — the vocab says what a command is CALLED in
    Home Assistant, this says which band can express it (Jeremy's split:
    translation is band-agnostic, routing is the moving target)."""
    return _load().get("piston_scope_commands", [])


def wait_commands() -> list:
    """The commands that leave PENDING WORK behind them.

    THE one list — `emit_yaml._has_wait` asks here rather than carrying its
    own copy. It used to hardcode three of them and miss `waitForDateTime`,
    which no corpus piston happens to use (HARD_RULES §5: the corpus is the
    verification vehicle, never the build scope). A missed wait command is
    silent and nasty: that statement gets merged into the shared automation,
    where an unrelated trigger can restart the run and kill its pending
    work."""
    rules = _load().get("split_rules", {})
    return (rules.get("work_after_wait") or {}).get("wait_commands") or []


def timer_backed_waits() -> dict:
    """How a cancellable wait is emitted — the timer-helper policy (route D).

    Every HA NAME in here (`timer.start`, `timer.cancel`, the `timer.finished`
    event) lives in the table rather than in the emitter, because those are the
    things that move when Home Assistant changes (HARD_RULES §8). The emitter
    owns the SHAPE — start a timer, wait for its finished event, give up if it
    never comes — which is a fact about how cancellation works and does not
    move."""
    return _load().get("timer_backed_waits", {}) or {}


def cancel_commands() -> list:
    """The commands that cancel pending work. THE one list — read from the
    same rule the split logic uses, never a second copy."""
    rules = _load().get("split_rules", {})
    return (rules.get("work_after_wait") or {}).get("cancel_commands") or []


def pyscript_reasons(piston: dict) -> list[str]:
    t = _load()
    reasons: list[str] = []

    def walk(node, stmt_id):
        if isinstance(node, dict):
            sid = node.get("$", stmt_id)
            nt = node.get("t")
            if nt in t["statement_types"]:
                reasons.append(f"statement ${sid}: '{nt}' statement requires PyScript")
            if nt == "switch" and node.get("ctp") in t["switch_ctp_values"]:
                reasons.append(f"statement ${sid}: switch fall-through requires PyScript")
            if isinstance(node.get("c"), str) and node["c"] in t["task_commands"]:
                reasons.append(f"task ${sid}: command '{node['c']}' requires PyScript")
            if node.get("o") in t["group_operators"]:
                reasons.append(f"node ${sid}: '{node['o']}' group requires PyScript")
            for field in t["condition_fields_present"]:
                if field in node:
                    reasons.append(f"node ${sid}: followed-by window ('{field}') requires PyScript")
            for field, vals in t["statement_fields_nondefault"].items():
                if node.get(field) in vals:
                    reasons.append(f"statement ${sid}: {field}='{node[field]}' requires PyScript")
            for v in node.values():
                walk(v, sid)
        elif isinstance(node, list):
            for i in node:
                walk(i, stmt_id)

    walk(piston.get("s", []), None)
    return reasons


# ── the split rule (§3.2b) ──────────────────────────────────────────────────
#
# What HA cannot RUN as a single automation. Distinct from the question above:
# that one asks whether HA can do the thing AT ALL, this one asks whether it
# can hold it in one automation. A piston can need a split and no PyScript, or
# PyScript and no split, or both.


def _commands_in(node) -> list:
    """Every task command name in this subtree, in document order."""
    found: list = []

    def walk(n):
        if isinstance(n, dict):
            if isinstance(n.get("c"), str) and n.get("t") is None:
                # a task carries its command in `c`; a condition group also
                # uses `c` but for its CHILD LIST, so only a string counts
                found.append(n["c"])
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for i in n:
                walk(i)

    walk(node)
    return found


def _statement_types_in(node) -> list:
    """Every statement type present in this subtree."""
    found: list = []

    def walk(n):
        if isinstance(n, dict):
            if isinstance(n.get("t"), str):
                found.append(n["t"])
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for i in n:
                walk(i)

    walk(node)
    return found


def _wait_not_last(stmt: dict, waits: set) -> bool:
    """Is there a wait with more work behind it inside this statement?

    Two shapes count: a wait that is not the last task in its own task list,
    and a wait anywhere in a statement that has later sibling statements. Both
    mean HA would hold the rest of the sequence hostage until the delay
    elapses, which webCoRE never did."""
    found = False

    def walk(n):
        nonlocal found
        if isinstance(n, dict):
            tasks = n.get("k")
            if isinstance(tasks, list):
                for i, task in enumerate(tasks):
                    if (isinstance(task, dict) and task.get("c") in waits
                            and i < len(tasks) - 1):
                        found = True
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for idx, item in enumerate(n):
                if (isinstance(item, dict) and idx < len(n) - 1
                        and set(_commands_in(item)) & waits):
                    found = True
                walk(item)

    walk(stmt)
    return found


def split_pieces(piston: dict) -> list[dict]:
    """Every part of this piston that HA cannot run inside the SAME
    automation as the rest, with the rule that says so and why.

    Empty list = the whole piston runs as one automation, which is the
    preferred answer: the piston as a whole is the intent (HARD_RULES §10)."""
    rules = _load().get("split_rules", {})
    pieces: list[dict] = []
    stmts = piston.get("s", []) or []

    def record(rule_name, rule, stmt_id, detail):
        pieces.append({
            "rule": rule_name,
            "becomes": rule.get("becomes", "automation"),
            "statement": stmt_id,
            "reason": detail,
            "why": rule.get("why", ""),
        })

    # 1. a subscription living inside the piston — HA has no nested trigger
    rule = rules.get("nested_subscription") or {}
    if rule.get("enabled"):
        wanted = set(rule.get("statement_types") or [])
        for stmt in stmts:
            if not isinstance(stmt, dict):
                continue
            if set(_statement_types_in(stmt)) & wanted:
                record("nested_subscription", rule, stmt.get("$"),
                       "listens for its own events while the piston runs; HA "
                       "can only listen at automation level")

    # 2. more than one branch with pending work — mode:restart would let them
    #    cancel each other, which webCoRE's per-condition-group scoping never did
    rule = rules.get("independent_timed_branches") or {}
    if rule.get("enabled"):
        waits = set((rules.get("work_after_wait") or {}).get("wait_commands")
                    or [])
        timed = [s for s in stmts
                 if isinstance(s, dict) and set(_commands_in(s)) & waits]
        if len(timed) > 1:
            for stmt in timed:
                record("independent_timed_branches", rule, stmt.get("$"),
                       f"one of {len(timed)} branches with its own pending "
                       "work; bundled together they would cancel each other")

    # 3. work queued behind a wait, in a piston that can cancel — the
    #    continuation has to be separately addressable to be cancellable
    rule = rules.get("work_after_wait") or {}
    if rule.get("enabled"):
        waits = set(rule.get("wait_commands") or [])
        cancels = set(rule.get("cancel_commands") or [])
        if waits and set(_commands_in(piston.get("s", []))) & cancels:
            for stmt in stmts:
                if isinstance(stmt, dict) and _wait_not_last(stmt, waits):
                    record("work_after_wait", rule, stmt.get("$"),
                           "has work queued behind a wait, and this piston "
                           "cancels pending tasks; HA can only reach that "
                           "work if it is its own script")
    return pieces


def handling_plan(piston: dict) -> dict:
    """EVERY way this piston has to be handled, in one answer.

    Deliberately not a verdict and not first-match — a piston can need a
    split AND PyScript AND neither excuses skipping the other.

      pyscript     — what HA cannot do at all (the failover)
      splits       — what HA cannot run as one automation (the split rule)
      connections  — what the split pieces then owe each other

    `connections` is the debt splitting creates and is why a split is never
    free: pieces that were one piston no longer share memory, so any piston
    variable crossing a piece boundary has to become a real HA helper entity
    (COMPILER_TODO.md:496 — this is what forced helper entities in the first
    place), and any ordering the user intended has to be enforced explicitly
    rather than by the statements sitting in the same file. "In this order"
    is intent, not syntax (HARD_RULES §10)."""
    splits = split_pieces(piston)
    connections = []
    if splits:
        connections.append(
            "shared state: any piston variable read in one piece and written "
            "in another must become an HA helper entity — split pieces do not "
            "share memory")
        connections.append(
            "ordering: whatever order the user intended across these pieces "
            "must be enforced explicitly; they no longer run down one file")
    return {
        "pyscript": pyscript_reasons(piston),
        "splits": splits,
        "connections": connections,
    }

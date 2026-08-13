"""COMMITMENTS — the behavioural promises a piston makes, and whether they
survived the compile.

WHAT A COMMITMENT IS. One promise, in the form the handoff of 2026-08-08 wrote
it: *this device ends up X · on this event · after this delay · gated by these
conditions · in this order.* A piston is a bag of these. So is the automation it
compiled to. If the two bags differ, something was dropped or invented.

WHY THIS EXISTS. The bug class that keeps hurting this project is SILENT LOSS —
condition-attached `ts`/`fs` tasks, sun offsets, `waitForDateTime`. Every one of
them compiled clean, passed the snapshot harness, passed HA's own config check,
and quietly did less than the piston said (HARD_RULES §6). None of them were
findable by reading output, because the output looked fine; they were findable
only by asking "is everything the piston promised still in here?" — which is
what this module asks, mechanically.

WHY IT DOES NOT REGENERATE THE PISTON JSON. Rejected deliberately. The intent
layer is *meant* to be lossy — a perfect structural round-trip would prove we
had built a transcoder, which is the thing HARD_RULES §2 forbids. Different
structure with the same commitments is CORRECT and expected. So the comparison
is over promises, never over shape.

═══════════════════════════════════════════════════════════════════════════════
A DELIBERATE EXCEPTION TO HARD_RULES §9 (search before you write) — READ THIS
═══════════════════════════════════════════════════════════════════════════════
`_PistonReader` below is a SECOND reader of the piston JSON. The codebase has
one already (`analyze.py`), and the one-reader rule exists for good reason: two
walkers in the COMPILE PATH is the root cause of the whole silent-drop class,
because a shape neither walker looks at is lost with nobody to notice.

This walker is not in the compile path, and its independence is precisely what
makes it worth having. Reading through `analyze.py` would make this module
blind to exactly the bugs it exists to catch: when `_cond_node` did not read
`ts`/`fs`, a checker sharing that reader would have cheerfully reported that
nothing was missing. A cross-check is only a check when the two derivations are
independent.

So: independent on purpose, documented as an exception rather than smuggled in,
and it must never be imported by the emitters.

═══════════════════════════════════════════════════════════════════════════════
WHAT THIS VERSION COMPARES, AND WHAT IT ONLY RECORDS
═══════════════════════════════════════════════════════════════════════════════
Compared (so a difference is a reported failure):
    the HA service · the entities it lands on · the delay in front of it

Recorded but NOT keyed:
    the waking event, and the gate (the conditions in front of the promise).
    Both sides express these too differently to compare without writing a third
    translator, which is the thing the handoff rejected. They are carried on
    every record and printed in the report, so a human reading a diff can see
    them; they are not yet a pass/fail signal. Stated here rather than left to
    be discovered — a checker with an unadvertised blind spot is worse than no
    checker.

Not compared at all, and REPORTED as uncompared rather than skipped in silence
(`uncompared` in the diff): outcomes that do not become a device-visible service
call — `remember`, `piston_self`, `cancel_later`, and a bare trailing `later`.
These land as helper writes, automation calls and timers, whose YAML shape is
still moving (route D). Silence about them would be the same failure this module
exists to catch, so they are counted and named on both sides.

KNOWN FALSE POSITIVE, do not chase it as a compiler bug (measured 2026-08-08):
the SPEAK / NOTIFY family reports as `dropped`, and it is not. Those commands
have a dedicated emitter path (`_speak`, `_send_notification`) which reads the
vocab's FIRST `ha` entry, while this module asks `service_spec` for the entry
matching the device's DOMAIN. When a command has several entries the two pick
different services, the names do not line up, and a promise that was kept looks
lost. Verified by hand on `80_sound_Test`: reported dropped, and the emitted
YAML plainly contains `tts.speak` with the speaker in `media_player_entity_id`.
Six corpus pistons are affected, all of them sound/notify tests.
THE FIX is for a piston-side promise to carry every service the vocab could
reach for that command and match on any of them, rather than committing to one.
Until then: treat a `dropped` on the speak/notify family as unproven, and read
the emitted YAML before believing it.

MAPPING vs LOSS. Both sides are normalised through the SAME `Resolver` — so a
wrong hash→entity or command→service mapping is wrong identically on both sides
and cancels out. That is intentional: this detects STRUCTURAL loss (a promise
that stopped existing), not mis-translation (a promise pointed at the wrong
thing). Mis-translation is the probe's collision check, which is a different
tool for a different bug.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import intent
from .errors import CompilerError
from .resolve import Resolver

# Outcomes that become a device-visible service call, and so can be compared
# against emitted YAML. Derived from intent.OUTCOMES rather than restated, so
# adding an outcome there forces a decision here instead of silently falling
# into one bucket or the other (HARD_RULES §9 — one list, not two).
_EMITS_A_CALL = {"be", "adjust", "transition", "tell", "offbox"}
# "nothing" is NOT here, and that is the point of having the outcome at all:
# `noop`/`poll`/`refresh` promise that nothing observable happens, so emitting
# no service call KEEPS that promise. Counting them as comparable reported
# `noop` as a dropped action — the checker demanding the compiler do something
# for a word that means "do nothing".


@dataclass(frozen=True)
class Commitment:
    """One behavioural promise, in neutral terms both sides can speak."""

    outcome: str                    # intent.OUTCOMES key — piston side only
    service: str | None             # the HA service that delivers it
    targets: tuple                  # entity ids it lands on, sorted
    after: int                      # seconds of delay in front of it
    # recorded, not keyed — see the module docstring
    on: tuple = ()                  # what wakes it
    gate: tuple = ()                # what must hold first
    source: str = ""                # where it came from, for the report
    detail: dict = field(default_factory=dict, compare=False)

    # `outcome` is deliberately NOT part of any comparison. It is a fact about
    # the webCoRE word, and the emitted side has no honest way to recover it: a
    # single HA service is the destination of MANY commands with DIFFERENT
    # outcomes (`siren.turn_on` serves both `siren` and `strobe`, which are
    # "be" and "transition"). An earlier draft guessed it back from the service
    # and reported ~20 false drops on exactly those collisions. The service
    # already says what happens; the outcome only says what it was called.

    def describe(self) -> str:
        who = ", ".join(self.targets) if self.targets else "(no target)"
        when = f" after {self.after}s" if self.after else ""
        wake = f" on {'; '.join(self.on)}" if self.on else ""
        gated = f" gated by {'; '.join(self.gate)}" if self.gate else ""
        return f"{who} — {self.service or self.outcome}{when}{wake}{gated}"


# ── the piston side ─────────────────────────────────────────────────────────


class _PistonReader:
    """Walks the raw piston JSON and states every promise it makes.

    Independent of analyze.py on purpose — see the module docstring."""

    def __init__(self, piston: dict, resolver: Resolver, piston_id: str,
                 piston_name: str):
        self.piston = piston
        self.resolver = resolver
        self.ctx = {"piston_id": piston_id, "piston_name": piston_name,
                    "stmt_id": None}
        self.out: list[Commitment] = []
        self.unresolved: list[str] = []

    # -- naming ------------------------------------------------------------

    def _entities(self, drefs: list, command: str) -> tuple:
        if not drefs:
            return ()
        try:
            return tuple(sorted(
                self.resolver.entities_for_command(list(drefs), command,
                                                   self.ctx)))
        except CompilerError as exc:
            # An unresolvable device is NOT an error here (HARD_RULES §10g) —
            # the promise still exists, it just cannot be named. Recorded so
            # the report can say so, and keyed on the raw reference so the two
            # sides can still line up when the emitter did the same.
            self.unresolved.append(f"{command}: {exc}"[:160])
            return tuple(sorted(str(d) for d in drefs))

    def _service(self, command: str, entities: tuple) -> tuple:
        """(service, targets) for this command, via the SAME mapping the
        emitter uses.

        The returned TARGETS are not always the devices the user picked, and
        that distinction is load-bearing. A command resolves one of two ways:

          - through `service_spec`, keyed on the picked device's own domain —
            the call lands ON those devices, so they are the targets;
          - through `command_ha_entry`/`ha_spec`, the vocab's entry with NO
            domain — the vocab's own words for "a command that isn't aimed at
            a device the user picked" (resolve.py:871). A push notification
            targets nothing; `wake_on_lan` takes a MAC. Claiming the picked
            device as the target of those produced a false "dropped" on every
            notification command, because the emitter — correctly — puts no
            entity there.

        None when the vocab has no mapping at all, which is a fact about the
        vocab and never a reason to drop the promise."""
        for name in self._delegates_to(command):
            for ent in entities:
                try:
                    return self.resolver.service_spec(
                        name, ent, self.ctx)[0], entities
                except CompilerError:
                    continue
            for getter in (self.resolver.ha_spec,
                           self.resolver.command_ha_entry):
                try:
                    entry = getter(name, self.ctx)
                except CompilerError:
                    continue
                if entry.get("service"):
                    return entry["service"], ()
        return None, entities

    @staticmethod
    def _delegates_to(command: str) -> list:
        """This command, then the base capabilities it is built on.

        A VIRTUAL command has no HA service of its own — `toggleLevel` and
        `fadeLevel` are shapes over `setLevel`, and the vocab records that in
        its `r` ("requires") list. Reading only the command's own name left
        them with no service at all, which the diff then reported as a dropped
        promise. The delegation is the vocab's own, not a second table."""
        from .resolve import _load_vocab
        vocab = _load_vocab()
        spec = ((vocab.get("commands") or {}).get(command)
                or (vocab.get("virtualCommands") or {}).get(command) or {})
        return [command] + [str(r) for r in (spec.get("r") or [])]

    # -- operands, for the human-readable half -----------------------------

    @staticmethod
    def _operand_text(op) -> str:
        if not isinstance(op, dict):
            return str(op)
        if op.get("t") == "p":
            return f"{op.get('a')} of {','.join(map(str, op.get('d') or []))}"
        if op.get("t") == "v":
            return f"${op.get('v')}"
        if op.get("t") == "x":
            return f"var {op.get('x')}"
        if op.get("s"):
            return str(op["s"])
        if op.get("x"):
            return str(op["x"])
        return str(op.get("c"))

    def _cond_text(self, cond: dict) -> str:
        if cond.get("t") == "group":
            inner = "; ".join(self._cond_text(c) for c in cond.get("c") or [])
            return f"({cond.get('o', 'and')}: {inner})"
        if cond.get("t") == "event":
            return f"event {self._operand_text(cond.get('lo'))}"
        bits = [self._operand_text(cond.get("lo")), str(cond.get("co"))]
        if cond.get("ro"):
            bits.append(self._operand_text(cond["ro"]))
        if cond.get("ro2") and (cond["ro2"] or {}).get("c") is not None:
            bits.append(f"..{self._operand_text(cond['ro2'])}")
        if (cond.get("to") or {}).get("c") is not None:
            bits.append(f"for {self._operand_text(cond['to'])}")
        return " ".join(b for b in bits if b and b != "None")

    @staticmethod
    def _is_trigger(cond: dict) -> bool:
        """A saved piston records the engine's own classification on the node
        (`ct`), and the shim stamps it on save (PISTON_JSON_REFERENCE §3). An
        `event` node is nothing but a subscription."""
        if cond.get("t") == "event":
            return True
        return cond.get("ct") == "t"

    # -- delays ------------------------------------------------------------

    def _wait_seconds(self, task: dict) -> int:
        """How long a wait command holds the sequence up.

        Reuses the compiler's own duration reader rather than re-deriving the
        unit table (HARD_RULES §9). Anything it cannot read counts as 0 and is
        recorded — an unreadable delay must not silently become 'immediately'."""
        from .resolve import duration_seconds
        params = task.get("p") or []
        for op in params:
            secs = duration_seconds(op)
            if secs is not None:
                return int(secs)
        self.unresolved.append(
            f"{task.get('c')}: could not read a duration from its parameters")
        return 0

    # -- the walk ----------------------------------------------------------

    def read(self) -> list[Commitment]:
        gate = tuple(self._cond_text(r) for r in self.piston.get("r") or [])
        self._statements(self.piston.get("s") or [], on=(), gate=gate,
                         where="piston")
        return self.out

    def _statements(self, stmts: list, on: tuple, gate: tuple,
                    where: str) -> None:
        """A statement list, in order. `after` accumulates across the list
        because a wait holds up everything behind it — which is exactly what
        the promise 'after this delay' means."""
        after = 0
        for stmt in stmts or []:
            if not isinstance(stmt, dict):
                continue
            after = self._statement(stmt, on, gate, where, after)

    def _statement(self, stmt: dict, on: tuple, gate: tuple, where: str,
                   after: int) -> int:
        t = stmt.get("t")
        sid = stmt.get("$")
        me = f"{where}/${sid}"
        self.ctx["stmt_id"] = sid
        # A statement's own restrictions gate it and everything inside it.
        gate = gate + tuple(self._cond_text(r) for r in stmt.get("r") or [])

        if stmt.get("di"):
            # disabled statement — the editor's soft delete. It promises
            # nothing, and counting it would report inventions on every piston
            # that has one parked.
            return after

        if t == "action":
            return self._tasks(stmt.get("k") or [], stmt.get("d") or [],
                               on, gate, me, after)

        if t == "if":
            trigs, conds = [], []
            for cond in stmt.get("c") or []:
                (trigs if self._is_trigger(cond) else conds).append(cond)
            wake = on + tuple(self._cond_text(c) for c in trigs)
            mine = gate + tuple(self._cond_text(c) for c in conds)
            # condition-attached task lists run DURING the test, before the
            # body — the exact thing that was silently dropped for months.
            for cond in (stmt.get("c") or []):
                self._attached(cond, wake, gate, me)
            self._statements(stmt.get("s") or [], wake, mine, f"{me}/then")
            for i, ei in enumerate(stmt.get("ei") or []):
                for cond in ei.get("c") or []:
                    self._attached(cond, wake, gate, f"{me}/elseif{i}")
                self._statements(
                    ei.get("s") or [], wake,
                    gate + tuple(self._cond_text(c) for c in ei.get("c") or []),
                    f"{me}/elseif{i}")
            self._statements(stmt.get("e") or [], wake,
                             gate + (f"NOT ({' and '.join(mine) or 'if'})",),
                             f"{me}/else")
            return after

        if t == "on":
            wake = on + tuple(self._cond_text(c) for c in stmt.get("c") or [])
            self._statements(stmt.get("s") or [], wake, gate, me)
            return after

        if t == "every":
            lo = stmt.get("lo") or {}
            wake = on + (f"every {lo.get('c')}{lo.get('vt') or ''}",)
            self._statements(stmt.get("s") or [], wake, gate, me)
            return after

        if t == "switch":
            subject = self._operand_text(stmt.get("lo"))
            for case in stmt.get("cs") or []:
                if case.get("t") == "d":
                    label = f"{subject} default"
                else:
                    label = f"{subject} is {self._operand_text(case.get('ro'))}"
                self._statements(case.get("s") or [], on, gate + (label,), me)
            self._statements(stmt.get("e") or [], on,
                             gate + (f"{subject} default",), me)
            return after

        if t in ("while", "repeat", "for", "each", "do"):
            inner = gate
            if t in ("while", "repeat"):
                inner = gate + tuple(self._cond_text(c)
                                     for c in stmt.get("c") or [])
            self._statements(stmt.get("s") or [], on, inner, me)
            return after

        if t in ("break", "exit"):
            return after

        # An unknown statement type is a GAP, not a nothing. Recorded so the
        # report says "this piston holds a shape I cannot read" rather than
        # quietly promising less than the piston does.
        self.unresolved.append(f"{me}: unknown statement type '{t}'")
        return after

    def _attached(self, cond: dict, on: tuple, gate: tuple, where: str) -> None:
        """`ts`/`fs` — statements hung on a condition, run when it tests true
        or false (PISTON_JSON_REFERENCE §3, VERIFIED webcore-piston.groovy
        :7882-7886). These are the canonical silent drop."""
        text = self._cond_text(cond)
        if cond.get("ts"):
            self._statements(cond["ts"], on, gate + (f"{text} is true",),
                             f"{where}/ts")
        if cond.get("fs"):
            self._statements(cond["fs"], on, gate + (f"{text} is false",),
                             f"{where}/fs")
        for child in cond.get("c") or []:
            if isinstance(child, dict):
                self._attached(child, on, gate, where)

    def _tasks(self, tasks: list, drefs: list, on: tuple, gate: tuple,
               where: str, after: int) -> int:
        for task in tasks or []:
            if not isinstance(task, dict):
                continue
            command = task.get("c")
            outcome = intent.outcome_of(command)
            if outcome == "later":
                # a wait makes no promise of its own; it moves everything
                # behind it later, which is what `after` carries.
                after += self._wait_seconds(task)
                continue
            picked = self._entities(drefs, command) if drefs else ()
            service, entities = ((None, picked) if outcome not in _EMITS_A_CALL
                                 else self._service(command, picked))
            self.out.append(Commitment(
                outcome=outcome or "unknown",
                service=service,
                targets=entities,
                after=after,
                on=on,
                gate=gate,
                source=where,
                detail={"command": command, "params": task.get("p") or []},
            ))
        return after


def from_piston(piston: dict, resolution_map: dict,
                globals_map: dict | None = None, piston_id: str = "check",
                piston_name: str = "check") -> dict:
    """Every promise the piston makes, read from the JSON itself."""
    resolver = Resolver(piston, resolution_map, globals_map)
    reader = _PistonReader(piston, resolver, piston_id, piston_name)
    made = reader.read()
    # The integration passthroughs reachable from this piston's devices. The
    # emitter falls back to one when the vocab's mapping can't be used here
    # (emit_yaml.py:1426-1435), and the diff needs to recognise the result as
    # the promise being KEPT DIFFERENTLY rather than dropped and replaced.
    through = {(dev.get("passthrough") or {}).get("service")
               for dev in (resolution_map or {}).values()
               if isinstance(dev, dict)}
    return {"commitments": made, "notes": reader.unresolved,
            "passthrough_services": {s for s in through if s}}


# ── the emitted side ────────────────────────────────────────────────────────
#
# This reads the ARTIFACT — the YAML we produced — not a re-translation of it
# back into webCoRE's grammar. That direction was rejected in the 2026-08-08
# handoff: a third translator whose failures would tell you about itself rather
# than about the compile.

def _num(value) -> int:
    """A number HA would accept, or 0 when it is a template.

    A templated delay (`waitRandom` emits `{{ range(300, 301) | random }}`)
    has no compile-time length. 0 is the honest answer — this module must never
    claim to know a duration it cannot read."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _delay_seconds(value) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and ":" in value:
        parts = [_num(p) for p in value.split(":")]
        while len(parts) < 3:
            parts.insert(0, 0)
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if isinstance(value, dict):
        return (_num(value.get("hours")) * 3600
                + _num(value.get("minutes")) * 60
                + _num(value.get("seconds"))
                + _num(value.get("milliseconds")) // 1000)
    return 0


# domain.object_id, HA's entity-id shape. Used to FIND entity ids rather than
# trusting them to sit under a key called `entity_id` — several services name
# theirs something else (`tts.speak` puts the speakers in
# `media_player_entity_id`), and looking only at `entity_id` made the emitted
# side appear to have lost the device.
_ENTITY_RE = __import__("re").compile(r"^[a-z_]+\.[a-z0-9_]+$")


def _entity_list(node) -> tuple:
    """Every entity id named anywhere on a service call.

    Deliberately shape-based, not key-based. The target of a call is whatever
    entities it mentions; which key HA chose to hold them is exactly the sort
    of detail that moves, and it is not what this module is measuring."""
    found: list[str] = []

    def take(v):
        if isinstance(v, str):
            for part in v.split(","):
                part = part.strip()
                if _ENTITY_RE.match(part):
                    found.append(part)
        elif isinstance(v, list):
            for i in v:
                take(i)
        elif isinstance(v, dict):
            for i in v.values():
                take(i)

    for key, value in node.items():
        if key in ("action", "service", "alias"):
            continue        # the service NAME is also domain.object shaped
        take(value)
    return tuple(sorted(set(found)))


# Helper entities PistonCore creates carry this prefix, which is how the
# emitted output distinguishes its own machinery from anything the user's
# piston asked for. Kept next to the reader that needs it rather than imported
# from the emitter — this module must never depend on the compile path.
_OURS = "pistoncore_"


def _is_our_timer(node: dict) -> bool:
    return any(e.startswith("timer.") and _OURS in e
               for e in _entity_list(node))


def _is_machinery(c: "Commitment") -> bool:
    """Is this emitted call PistonCore's own plumbing rather than a promise?

    A piston variable that outlives one run becomes an `input_boolean` (or
    number/text) helper, and a cancellable wait becomes a `timer` — both named
    `pistoncore_*` by construction. Writing to one is HOW a promise is kept,
    not a promise in its own right, and the piston side already files the
    matching webCoRE words (`setVariable`, `wait`) under `uncompared`.

    Without this the diff reported six to eight INVENTED calls on every piston
    that uses a variable — the compiler being blamed for its own bookkeeping.
    Requires EVERY target to be ours, so a call that also touches a real device
    is still judged as a promise."""
    return bool(c.targets) and all(_OURS in t for t in c.targets)


def _trigger_text(trig: dict) -> str:
    kind = trig.get("trigger") or trig.get("platform") or "?"
    bits = [kind]
    for k in ("entity_id", "to", "from", "at", "event", "above", "below",
              "minutes", "hours", "seconds"):
        if trig.get(k) not in (None, ""):
            bits.append(f"{k}={trig[k]}")
    return " ".join(str(b) for b in bits)


class _YamlReader:
    def __init__(self):
        self.out: list[Commitment] = []
        self.notes: list[str] = []
        # duration carried by a `timer.start` that has not yet met its wait
        self._pending_wait: int | None = None

    def read(self, text: str) -> list[Commitment]:
        import yaml
        docs = yaml.safe_load(text) or []
        if isinstance(docs, dict):
            docs = [docs]
        for block in docs:
            if not isinstance(block, dict):
                continue
            name = block.get("id") or block.get("alias") or "?"
            wake = tuple(_trigger_text(t)
                         for t in (block.get("triggers")
                                   or block.get("trigger") or []))
            seqs = block.get("actions") or block.get("action") or []
            if not seqs and isinstance(block.get("sequence"), list):
                seqs = block["sequence"]        # a script block
            self._sequence(seqs, wake, (), name, 0)
        return self.out

    def _sequence(self, seq, wake: tuple, gate: tuple, where: str,
                  after: int) -> int:
        for node in seq or []:
            if not isinstance(node, dict):
                continue
            after = self._node(node, wake, gate, where, after)
        return after

    def _node(self, node: dict, wake: tuple, gate: tuple, where: str,
              after: int) -> int:
        if "delay" in node:
            return after + _delay_seconds(node["delay"])
        if "wait_template" in node or "wait_for_trigger" in node:
            # A TIMER-BACKED WAIT (route D) is a `timer.start` followed by a
            # wait for that timer's event, so its real length is the DURATION
            # the start call carried — not the wait's timeout, which is only a
            # backstop and is deliberately longer. Reading the timeout here
            # reported every post-wait action as happening minutes late.
            if self._pending_wait is not None:
                held, self._pending_wait = self._pending_wait, None
                return after + held
            # otherwise a wait whose length is not knowable statically; the
            # timeout is the honest upper bound rather than pretending it is
            # immediate.
            return after + _delay_seconds(node.get("timeout"))
        if "if" in node:
            g = gate + (_conds_text(node.get("if")),)
            self._sequence(node.get("then"), wake, g, where, after)
            self._sequence(node.get("else"), wake,
                           gate + (f"NOT ({_conds_text(node.get('if'))})",),
                           where, after)
            return after
        if "choose" in node:
            for opt in node.get("choose") or []:
                if not isinstance(opt, dict):
                    continue
                self._sequence(opt.get("sequence"), wake,
                               gate + (_conds_text(opt.get("conditions")),),
                               where, after)
            self._sequence(node.get("default"), wake, gate + ("default",),
                           where, after)
            return after
        if "repeat" in node:
            rep = node["repeat"] or {}
            self._sequence(rep.get("sequence"), wake, gate + ("repeat",),
                           where, after)
            return after
        if "parallel" in node:
            for branch in node.get("parallel") or []:
                if isinstance(branch, dict) and "sequence" in branch:
                    self._sequence(branch["sequence"], wake, gate, where, after)
                elif isinstance(branch, dict):
                    self._node(branch, wake, gate, where, after)
            return after
        if "sequence" in node:
            return self._sequence(node["sequence"], wake, gate, where, after)
        if "condition" in node:
            return after
        if node.get("stop") is not None:
            return after

        service = node.get("action") or node.get("service")
        # A timer being STARTED is the front half of a timer-backed wait: it
        # makes no promise of its own, it sets how long the promises behind it
        # are held back. Remembered so the wait that follows can read it.
        #
        # NARROWED to timers PistonCore created for this piston, and the gate
        # is what forced that: `.start` alone also matches a real webCoRE
        # command that maps to `timer.start`, and swallowing it reported that
        # command's promise as DROPPED. Machinery is recognised by being ours,
        # never by the service name resembling ours.
        if service and _is_our_timer(node):
            dur = (node.get("data") or {}).get("duration")
            if dur is not None:
                self._pending_wait = _delay_seconds(str(dur).strip('"'))
                return after
        if service:
            self.out.append(Commitment(
                outcome="",         # not recoverable from a service — see above
                service=service,
                targets=_entity_list(node),
                after=after,
                on=wake,
                gate=gate,
                source=where,
                detail={"data": node.get("data") or {}},
            ))
        return after


def _conds_text(conds) -> str:
    if conds is None:
        return ""
    if isinstance(conds, str):
        return conds
    if isinstance(conds, dict):
        return json.dumps(conds, sort_keys=True, default=str)[:120]
    return "; ".join(_conds_text(c) for c in conds)


_VOCAB_SERVICES: set = set()


def _vocab_services() -> set:
    """Every HA service that delivers a COMPARABLE promise.

    Read off the vocab itself, so there is no second table to drift
    (HARD_RULES §9). Two kinds of emitted call are excluded, because reading
    either as a promise made a false "invented":

      - services no vocab command names — helper writes, timers,
        `automation.turn_off`. That is machinery the compiler added to make
        the piston work, not something the piston asked for.
      - services belonging only to commands whose outcome is not comparable
        (`setLocationMode` is `piston_self`). The piston side files those under
        `uncompared`, so the emitted side must too, or every one of them looks
        invented.

    A service reachable from BOTH a comparable and an uncomparable command
    stays in the set. That direction is deliberate: it can over-report an
    invention, which gets triaged, rather than under-report a real one, which
    is the bug this module exists to catch."""
    if not _VOCAB_SERVICES:
        from .resolve import _load_command_ha, _load_vocab
        for command, entries in (_load_command_ha(_load_vocab()) or {}).items():
            if intent.outcome_of(command) not in _EMITS_A_CALL:
                continue
            for entry in entries or []:
                if entry.get("service"):
                    _VOCAB_SERVICES.add(entry["service"])
    return _VOCAB_SERVICES


def from_yaml(text: str) -> dict:
    """Every promise the emitted automation actually makes."""
    reader = _YamlReader()
    made = reader.read(text)
    return {"commitments": made, "notes": reader.notes}


# ── the comparison ──────────────────────────────────────────────────────────


def _lands_on(promise: Commitment, emitted: Commitment) -> bool:
    """Does this emitted call deliver that promise's targets?

    SUBSET, not equality, and the direction matters. Every device the piston
    aimed at must appear on the call — that is the promise. The call may name
    MORE entities than the piston did, because some services take an engine or
    a helper alongside the real target (`tts.speak` carries the TTS engine as
    its target and the speakers in its data). Requiring equality reported those
    as both a drop and an invention: one promise, counted twice, wrongly."""
    return set(promise.targets) <= set(emitted.targets)


def diff(piston_side: dict, yaml_side: dict) -> dict:
    """What the piston promised against what the automation promises.

      dropped     — in the piston, not in the emission. A silent loss.
      invented    — in the emission, not in the piston. The compiler made
                    something up: just as wrong, and much rarer.
      retimed     — the same promise, at a different delay. Split from
                    `dropped` because the cause differs: a lost wait rather
                    than a lost action.
      passthrough — the promise is kept, but by handing the raw command to the
                    integration's driver passthrough instead of the HA service
                    the vocab names. NOT a drop: this is a documented,
                    deliberate fallback (emit_yaml.py:1426-1435). It gets its
                    own category because it is invisible everywhere else and
                    it carries a real risk the emitter's own comment states —
                    "a passthrough accepts any command name and fails at
                    RUNTIME, not at compile. A command the driver doesn't have
                    will silently do nothing."
      uncompared  — promises this version cannot compare (see the module
                    docstring), counted on BOTH sides so the blind spot is
                    visible rather than silent.

    Matching is greedy and one-to-one: each emitted call can satisfy at most
    one promise, so a piston asking for the same thing twice is not silently
    satisfied by a single emitted call."""
    p_all = piston_side["commitments"]
    y_all = yaml_side["commitments"]
    through = set(piston_side.get("passthrough_services") or ())

    p_cmp = [c for c in p_all if c.outcome in _EMITS_A_CALL]
    # Machinery the compiler added — helper writes, timers, automation control
    # — is not a promise the piston made and must not read as an invention.
    y_cmp = [c for c in y_all
             if (c.service in _vocab_services() or c.service in through)
             and not _is_machinery(c)]

    unclaimed = list(y_cmp)
    dropped, retimed, passthrough, target_moved = [], [], [], []
    matched_emitted, kept = [], 0
    for promise in p_cmp:
        exact = next((e for e in unclaimed if e.service == promise.service
                      and _lands_on(promise, e) and e.after == promise.after),
                     None)
        if exact is not None:
            unclaimed.remove(exact)
            matched_emitted.append(exact)
            kept += 1
            continue
        loose = next((e for e in unclaimed if e.service == promise.service
                      and _lands_on(promise, e)), None)
        if loose is not None:
            unclaimed.remove(loose)
            matched_emitted.append(loose)
            retimed.append((promise, loose))
            continue
        # the driver fallback: the command name itself travels in the call's
        # data, so it is matched on the COMMAND rather than on the service.
        raw = next((e for e in unclaimed if e.service in through
                    and promise.detail.get("command")
                    in json.dumps(e.detail, default=str)), None)
        if raw is not None:
            unclaimed.remove(raw)
            matched_emitted.append(raw)
            passthrough.append((promise, raw))
            continue
        # The promise is delivered, but NOT to the devices it named. The
        # notification family does this by design — `notify.notify` is aimed
        # at a notify service, and the picked device does not appear on the
        # call at all. Separated from `dropped` because the failure is a
        # different one and needs a different answer: the action happens, but
        # possibly not where the user pointed it.
        moved = next((e for e in unclaimed if e.service == promise.service),
                     None)
        if moved is not None:
            unclaimed.remove(moved)
            matched_emitted.append(moved)
            target_moved.append((promise, moved))
        else:
            dropped.append((promise, None))

    # An emitted call left over because ONE promise became a BRANCH — a toggle
    # is one webCoRE word and two HA calls (`light.turn_on` in the then,
    # `light.turn_off` in the else), only one of which can ever run.
    #
    # THE GATE IS WHAT MAKES IT A BRANCH, and getting this wrong is not
    # theoretical: a first version asked only for the same devices and the same
    # domain, and it swallowed a deliberately injected invention — the checker
    # stopped detecting the thing it exists to detect. Two calls sitting in the
    # SAME branch are two actions; two calls under DIFFERENT gates are one
    # choice. So an unclaimed call only counts as an alternative when its gate
    # differs from every call that satisfied a promise.
    matched_gates = {m.gate for m in matched_emitted}
    kept_targets = {t for p in p_cmp for t in p.targets}
    alternative = [e for e in unclaimed
                   if e.targets and set(e.targets) <= kept_targets
                   and e.gate not in matched_gates
                   and any((e.service or "").split(".")[0]
                           == (p.service or "").split(".")[0] for p in p_cmp)]
    unclaimed = [e for e in unclaimed if e not in alternative]

    return {
        "dropped": dropped,
        "retimed": retimed,
        "passthrough": passthrough,
        "target_moved": target_moved,
        "alternative": alternative,
        "invented": unclaimed,
        "kept": kept,
        "uncompared": {
            "piston": [c for c in p_all if c.outcome not in _EMITS_A_CALL],
            "yaml": [c for c in y_all
                     if c.service not in _vocab_services() or _is_machinery(c)],
        },
        "notes": list(piston_side.get("notes") or [])
                 + list(yaml_side.get("notes") or []),
        "counts": {"piston": len(p_cmp), "yaml": len(y_cmp)},
    }

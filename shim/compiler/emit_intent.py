"""EMIT FROM INTENT — the behaviour decides the automation, not the statement.

THE LINE THIS FILE MUST NOT CROSS (Jeremy, 2026-08-09, repeatedly): NO
TRANSCODING. The first version of this module iterated `piston.s` and produced
one branch per statement. That is `analyze.py` in a different file — statement
in, branch out — and it is the failure this project has repeated for five
sessions. It was deleted.

WHAT THIS DOES INSTEAD. It starts from `spec.behaviours()`: the PROMISES the
piston makes, already grouped into intents, with held-state pairs collapsed.
Each promise carries everything an automation needs and nothing about how
webCoRE wrote it:

    what ends up where · on what event · gated by what · after what delay ·
    once per device or not · repeating or not · in what order

Emission groups promises by WHAT WAKES THEM, because that is what decides how
many automations there are — not how many statements the user typed. Two
statements that share a trigger are one automation; one statement whose work
hangs off two different events is two. The piston's shape has no vote.

TRANSLATION FILLS THE SLOTS, AFTER (Jeremy: "the translation comes in after
intent to fill the spots needed"). The intent says "this device ends up on,
when that sensor becomes active, only while it is dark". Turning `active` into
`on`, a hash into an entity and a command into a service is translation, and it
stays where it already lives — `resolve.py`, the emitters, the templates. A
leaf's raw operand is used ONLY for that filling; it never decides structure.

FALLBACK, NEVER APPROXIMATION. `plan()` returns None for any piston whose
intent it cannot express, and the caller keeps the existing path. A shape is
added only once it is device-proven (HARD_RULES §7); a confident
half-translation is worse than an honest refusal (§6).
"""

from __future__ import annotations

import os
import re

from . import spec

# NOTHING IS IMPORTED FROM `analyze`. That import is the whole argument: while
# it was here, every trigger, condition and action in this "intent" path was
# still built by the transcoder's statement reader, and the intent only chose
# which shapes to attempt. Jeremy, 2026-08-09: *"i see you re doing shit from
# the transcoding compiler that never should have been made ... i want the
# fucking intent engine to work from intent not transcoding."* The nodes below
# are built from the behaviour spec's own fields and nothing else.
#
# The transcoder is untouched and still the default (`enabled()` is off), so
# the output he relies on is not at risk: *"i dont currently want that data
# lost it works mostly."*


def enabled() -> bool:
    """Is intent-driven emission on? (Jeremy, 2026-08-09: "keep the intent as a
    switch keeping the old usable while we debug it".)

    Off sends every piston down the pre-intent path, so a wrong intent read can
    never stop him compiling — the old behaviour is one flag away, not one
    revert away.

    DEFAULT OFF (HARD_RULES §12a: the intent engine lands as a WHOLE, and
    partial intent work does not become what a running install uses). It was
    briefly written default-ON, which meant Jeremy's next ordinary save would
    have silently recompiled a live piston through an unproven path — the
    engine has never passed a §7 device test. Opt in per process with
    PISTONCORE_INTENT_EMIT=1, or per install with the stored setting; nothing
    turns it on by itself.

    Order: the env var wins (harnesses and A/B runs set it per process), then
    the stored setting."""
    env = os.environ.get("PISTONCORE_INTENT_EMIT")
    if env is not None:
        return env.strip().lower() not in ("0", "off", "false", "no")
    try:
        from .. import storage
        return bool((storage.load_settings().get("compiler") or {})
                    .get("intent_emit", False))
    except Exception:
        return False


def _wake_key(promise) -> tuple:
    """What wakes this promise — the identity that decides which automation it
    belongs to. Promises woken by the same events are one automation."""
    out = []
    for t in promise.wakes_on:
        s = t.subject
        # repr, not the values themselves: a comparison value can be a LIST
        # (`is any of`), which is unhashable and crashed the grouping on
        # 58_Reloading_Motion. The key only needs to say "same event or not".
        out.append(repr((s.kind, tuple(s.devices), s.attribute, s.virtual,
                         t.operator, t.values, t.negated)))
    return tuple(sorted(out))


def _gate_key(promise) -> tuple:
    out = []
    for g in promise.gated_by:
        out.append(g.describe())
    return tuple(out)


# Subject.kind -> the operand type the emitter keys on. The emitter's names
# are webCoRE's letters because that is the contract it already speaks; the
# READING is what had to stop being webCoRE-shaped, not the wire format.
_LO_TYPE = {"device": "p", "virtual": "v", "variable": "x",
            "preset": "s", "constant": "c", "expr": "e", "argument": "u"}


def _side(sub, slot: str) -> dict:
    """One right-hand operand into the emitter's value slots.

    `slot` is "" for the first operand and "2" for the second, matching the
    emitter's `value`/`value2` pairs. Which slot an operand lands in is decided
    by its KIND, which the reading now keeps (spec.Subject) — a preset goes to
    value_preset, a variable or expression to value_expr, a literal to value
    with its unit. Flattening these was why `sunrise` and the string "sunrise"
    were indistinguishable."""
    if sub is None:
        return {}
    if sub.kind == "constant":
        return {f"value{slot}": sub.constant, f"value{slot}_vt": sub.vt}
    if sub.kind == "preset":
        return {f"value{slot}_preset": sub.preset, f"value{slot}_vt": sub.vt}
    if sub.kind == "variable":
        return {f"value{slot}_expr": sub.variable, f"value{slot}_vt": sub.vt}
    if sub.kind == "expr":
        return {f"value{slot}_expr": sub.expression, f"value{slot}_vt": sub.vt}
    return {}


def _leaf(test):
    """One Test as the node the emitter consumes — built from the READING.

    Every field comes off the behaviour spec. Nothing reopens the piston JSON,
    which is what stops this being a transliteration wearing a new name.

    `true_actions`/`false_actions` are deliberately EMPTY: work hung on a
    condition's `ts`/`fs` was already turned into its own promises by the
    reader, so carrying it here as well would emit it twice. The transcoder has
    to read it here because it has no promise layer; this path must not."""
    s = test.subject
    if test.negated:
        return None          # no node field carries "must be false" — refuse
    if len(test.right) > 2:
        return None

    hold = test.hold if test.hold is not None else test.offset
    node = {
        "co": test.operator,
        "attr": s.attribute,
        "devices": list(s.devices),
        "aggregation": s.aggregation,
        "lo_type": _LO_TYPE.get(s.kind),
        "lo_var": s.virtual,
        "lo_var_name": s.variable,
        "value": None, "value_vt": None, "value2": None, "value2_vt": None,
        "value_preset": None, "value2_preset": None,
        "value_expr": None, "value2_expr": None,
        # seconds, because that is what the reading normalised every duration
        # to; the emitter's converter reads {c, vt} (resolve.duration_seconds).
        "duration": {"c": int(hold), "vt": "s"} if hold is not None else {},
        "ct": "t" if test.wakes else "c",
        # THE CALENDAR RESTRICTION HAS TO TRAVEL WITH THE LEAF. `raw` was an
        # empty dict, and `emit_yaml._time_restriction_conds` looks for these
        # under `raw.lo` — so this path emitted NO weekday and NO month
        # condition at all while the transcoder emitted both. Measured on
        # `42_New_School_piston`: intent ON dropped `weekday: [mon..fri]` and
        # the October-excluded month test, which is a 5:20am alarm going off on
        # Saturdays and through July. A silent drop of the exact kind
        # HARD_RULES §6 exists for, inside the newer path.
        #
        # Fed back through the emitter's OWN restriction builder rather than
        # emitting the conditions here, so both paths keep sharing one
        # implementation and one set of HA day names (HARD_RULES §9).
        "raw": {"lo": {k: list(v) for k, v in (
            ("odw", test.only_days_of_week),
            ("odm", test.only_days_of_month),
            ("owm", test.only_weeks_of_month),
            ("omy", test.only_months)) if v}},
        "true_actions": [], "false_actions": [],
    }
    node.update(_side(test.right[0] if test.right else None, ""))
    node.update(_side(test.right[1] if len(test.right) > 1 else None, "2"))
    return node


def _wake_from_intent(promise):
    """What wakes a promise that webCoRE never marked with a trigger.

    THE FLAG IS NOT THE INTENT (Jeremy, 2026-08-09: *"read its intent. if you
    cant catch the trigger your not thinking correctly"*). `40_My_Lock` says
    *"the back door is closed AND the back lock is unlocked -> lock it"* with
    every leaf `ct: 'c'`. Reading that as "nothing wakes this" is the
    transpiler brain trusting webCoRE's flag over the plain meaning: nobody
    writes that intending it never to run. The thing that CHANGES is the
    contact; the lock's state is the guard.

    So the wake is derived from the gate: the leaves that watch a DEVICE
    become the events, and everything else stays a condition. webCoRE reaches
    the same place from the other direction — a piston with no triggers
    subscribes to its condition devices — so this is not an invention, it is
    the same behaviour read from the intent instead of from a flag.

    Returns the leaves to wake on, or () when nothing here is watchable (a
    time-only or variable-only gate, which genuinely has no event)."""
    out = []
    for g in promise.gated_by:
        for t in (g.leaves() if isinstance(g, spec.Gate) else [g]):
            s = t.subject
            if s.kind == "device" and s.attribute and s.devices:
                if not any(x.subject.devices == s.devices
                           and x.subject.attribute == s.attribute for x in out):
                    out.append(t)
    return tuple(out)


def plan(piston: dict, piston_id: str, piston_name: str):
    """Branch IR built from the piston's INTENT, or None if not expressible."""
    promises = spec.read(piston)
    if not promises:
        return None
    # Give the unwoken promises the event their own words imply, BEFORE they
    # are grouped — grouping is by what wakes a promise, so a derived wake has
    # to exist by then or the promise lands in its own lonely automation.
    from dataclasses import replace
    promises = [p if p.wakes_on else replace(p, wakes_on=_wake_from_intent(p))
                for p in promises]
    behaviours = spec.behaviours(promises)

    # Anything the intent layer carries but emission cannot yet honour must
    # refuse, not approximate: a per-device fan-out, a repeat, or a poll
    # interval changes what the automation IS.
    flat = []
    for b in behaviours:
        if isinstance(b, spec.Held):
            if b.engage.per_device or b.release.per_device: return None
            if b.engage.repeating or b.release.repeating: return None
            # BOTH HALVES, ALWAYS. A held state is one intent but two
            # promises, and the first version of this loop emitted only the
            # engage — on 12_Cave_motion_V2 the lights came on and NOTHING
            # turned them off again. Grouping puts them back together when
            # they share a wake and leaves them apart when they don't; that
            # is the grouping's job, not a reason to drop one.
            flat.append(b.engage)
            flat.append(b.release)
        else:
            if b.per_device or b.repeating: return None
            # A custom (`cm`) command is NOT a reason to refuse. It is a raw
            # HA service name that the hybrid feed put in front of the user
            # precisely because the vocab does not carry it, and it needs no
            # translation — `service_spec` passes it straight through.
            flat.append(b)

    # ONE AUTOMATION PER THING THAT WAKES IT. This is the whole difference
    # from the transcoder: the grouping key is the EVENT, never the statement.
    groups: dict = {}
    order: list = []
    for p in flat:
        key = (_wake_key(p), _gate_key(p))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(p)

    branches = []
    for i, key in enumerate(order):
        members = groups[key]
        lead = members[0]
        if not lead.wakes_on:
            return None                       # no event: not this path's shape

        triggers, gates = [], []
        for t in lead.wakes_on:
            n = _leaf(t)
            if n is None:
                return None
            triggers.append(n)
        for g in lead.gated_by:
            for t in (g.leaves() if isinstance(g, spec.Gate) else [g]):
                if t.wakes:
                    continue
                n = _leaf(t)
                if n is None:
                    return None
                gates.append(n)

        then = [_task(p) for p in sorted(members, key=lambda x: x.order)]
        if any(t is None for t in then):
            return None

        branches.append({
            "stmt_id": _sid(lead.source, i), "kind": "if", "tcp": "c",
            "triggers": triggers, "conditions": gates,
            "then": then, "else": [], "restrictions": [],
            "yaml_blocker": None, "raw": {}, "stmt_type": "if",
        })

    has = any(br["triggers"] for br in branches)
    for br in branches:
        br["piston_has_triggers"] = has
    return branches


def _sid(source: str | None, i: int) -> str:
    """A stable, readable trigger id from the promise's source path.

    `source` is `piston/$1/then/$4`; emitted raw it became
    `id: stmtpiston/$1/then/$4`, which HA accepts but is unreadable in a
    trace. The digits alone identify it and stay stable across recompiles of
    the same piston, which is what a trace id has to be."""
    nums = re.findall(r"\d+", str(source or ""))
    return "_".join(nums) if nums else str(i)


def _param(sub) -> dict:
    """One command parameter, from the reading, in the operand shape the
    emitter's parameter transforms expect ({c, vt} for a duration, and so on).

    This is the translation step, and it is the right way round: the intent
    says "five minutes" and this spells it for the emitter. It does not read
    the piston."""
    if sub.kind == "constant":
        return {"c": sub.constant, "vt": sub.vt}
    if sub.kind == "preset":
        return {"s": sub.preset, "vt": sub.vt}
    if sub.kind == "variable":
        return {"x": sub.variable, "vt": sub.vt}
    if sub.kind == "expr":
        return {"e": sub.expression, "vt": sub.vt}
    if sub.kind == "argument":
        return {"u": sub.argument, "vt": sub.vt}
    if sub.kind == "device":
        return {"d": list(sub.devices), "vt": sub.vt}
    return {"vt": sub.vt}


def _task(promise):
    """A promise as the action node the emitter consumes — from the reading."""
    return {"kind": "task", "command": promise.command,
            "devices": list(promise.devices),
            "params": [_param(p) for p in promise.params],
            "custom": bool(promise.custom),
            "raw": {}, "raw_stmt": {}}

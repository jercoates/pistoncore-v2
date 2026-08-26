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


_IDIOM_TIME_OPS = ("happens_daily_at", "happens_at")


def _hms(seconds: int) -> str:
    seconds = int(seconds)
    sign = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    return "%s%02d:%02d:%02d" % (sign, seconds // 3600, (seconds % 3600) // 60, seconds % 60)


def _occasion(test):
    """The occasion as HOME ASSISTANT states it, or None if this is not one.

    webCoRE says "happens daily at", and stores either minutes-since-midnight
    (1200 = 20:00) or a preset like `$sunset` with a separate offset in
    seconds. HA has a native word for each of those and they are not the same
    trigger, so the reading is asked WHICH occasion it is rather than being
    translated one-to-one:

        every day at a clock time   -> trigger: time, at:
        relative to sun             -> trigger: sun, event:, offset:

    Nothing about a loop, a variable or a re-check survives here, because the
    intent never contained one -- `happens_daily_at` is how webCoRE SPELLS a
    daily occasion, not a mechanism to reproduce."""
    if not test.values:
        return None
    v = test.values[0]

    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return {"kind": "time", "at": _hms(int(v) * 60)}

    if not isinstance(v, str):
        return None

    # WHICH HA TRIGGER A TIME WORD MEANS IS DATA, NOT CODE (Jeremy, 2026-08-13:
    # "they should just be added to the json not another place"). Each of
    # webCoRE's time variables carries an `ha.trigger` in webcore_vocab.json
    # beside the `ha.yaml`/`ha.pyscript` rules that READ its value -- so a user
    # can add or repair one without touching Python, and there is exactly one
    # place to look. `$sunset` and `$nextSunset` name the same trigger there,
    # because HA's sun trigger already fires at the NEXT occurrence.
    from .resolve import _load_vocab
    sysvars = _load_vocab().get("systemVariables") or {}
    key = v.strip()
    if not key.startswith("$"):
        key = "$" + key
    for name, entry in sysvars.items():
        if name.lower() != key.lower():
            continue
        trig = (entry.get("ha") or {}).get("trigger")
        if not trig:
            return None
        out = dict(trig)
        if test.offset:
            if out.get("kind") == "sun":
                out["offset"] = _hms(test.offset)
            else:
                h, m, s = (int(x) for x in str(out.get("at", "0:0:0")).split(":"))
                out["at"] = _hms((h * 3600 + m * 60 + s + int(test.offset)) % 86400)
        return out
    return None


def daily_time(piston: dict, piston_id: str, piston_name: str, resolver):
    """IDIOM: "at this occasion, put these things in this state."

    Six pistons in the corpus, from both authors, all active, and the compiler
    emitted nothing for any of them. Returns rendered YAML, or None when the
    piston is not this shape -- never an approximation (HARD_RULES §6).

    ONE IDIOM IN, ONE HA CONSTRUCT OUT. The emitter is handed the recognised
    occasion and the state wanted, never a statement, so there is nowhere for
    webCoRE's machinery to ride along even if the piston contained some."""
    from . import intent as _intent_vocab
    from jinja2 import ChoiceLoader, Environment, FileSystemLoader
    from .. import customize

    promises = spec.read(piston)
    if not promises:
        return None

    autos = []
    for i, p in enumerate(promises):
        # every promise must be a bare "make this thing be that way" on an
        # occasion; anything else (a report, a loop, a remembered value) is a
        # different idiom and must not be forced into this one.
        if p.per_device or p.repeating or p.writes or p.reads or p.after:
            return None
        if _intent_vocab.outcome_of(p.command) != "be":
            return None
        if len(p.wakes_on) != 1 or not p.devices:
            return None
        t = p.wakes_on[0]
        if t.subject.kind != "virtual" or t.subject.virtual != "time":
            return None
        if t.operator not in _IDIOM_TIME_OPS:
            return None
        when = _occasion(t)
        if when is None:
            return None

        ctx = {"piston_id": piston_id, "piston_name": piston_name, "stmt_id": p.source}
        entities = resolver.entities_for_command(list(p.devices), p.command, ctx)
        if not entities:
            return None
        service, data_spec = resolver.service_spec(p.command, entities[0], ctx)
        if not service or data_spec:
            # a command needing parameter substitution is not this idiom yet
            return None

        # THE NAMING IS THE APP'S, NOT MINE (device-proven on the bench,
        # 2026-08-14). An idiom that invents its own id and alias produced
        # `automation.real_path_bench_test_1` where every other automation
        # PistonCore owns is `automation.pistoncore_<piston>_s<stmt>`, and it
        # reported no auto_ids at all -- so the app could not enable, disable or
        # PAUSE what it had just deployed ("enabled": "no automation ids").
        # Only the real compile-and-deploy showed this; the snapshot harness
        # never looks at an id. Same convention as emit_yaml.py:2742.
        autos.append({
            "id": "pistoncore_%s_s%s" % (piston_id, _sid(p.source, i)),
            "alias": "PistonCore: %s — $%s" % (piston_name, _sid(p.source, i)),
            "when": when,
            "weekday": list(t.only_days_of_week or ()),
            "months": list(t.only_months or ()),
            "actions": [{"service": service, "entities": entities, "data": None}],
        })

    if not autos:
        return None
    env = Environment(
        loader=ChoiceLoader([FileSystemLoader(d)
                             for d in customize.search_dirs("templates/compiler/yaml/classic")]),
        trim_blocks=False, lstrip_blocks=False, keep_trailing_newline=True)
    # The ids go back WITH the yaml. The deploy step needs them to enable,
    # disable and pause what it wrote; returning only text left the app holding
    # an automation it could not name.
    return {"yaml": env.get_template("daily_time.yaml.j2").render(automations=autos),
            "auto_ids": [a["id"] for a in autos]}


# WHY THE INTENT PATH REFUSED, for the last plan() call. Coverage is the number
# that decides whether this path can ever replace the transcoder, and "it
# returned None" is not an answer you can prioritise from. Diagnostic only:
# nothing branches on it, and the refusal behaviour is unchanged.
last_refusal: str | None = None


def _refuse(why: str):
    global last_refusal
    last_refusal = why
    return None


def report_groups(promises):
    """The promises that together are ONE report: "tell me which of these match".

    THE LOOP IS NOT THE POINT. webCoRE writes "for each device, if it matches,
    add its name to a string" because it has no way to ask a list a question.
    16 of the 17 per-device loops in the corpus are this one shape, and Home
    Assistant answers it with a single template — so the loop does not get
    translated, it stops existing.

    Recognised from the READING, not from node shapes: a value that is started
    fresh, added to once per device, and then used. `accumulates()` is exactly
    "this promise builds a value out of its own previous value", which is what
    the value-flow layer exists to know.

    ONE PER VALUE, not one per piston. `38_Low_Battery_Check` builds TWO
    reports — the ordinary batteries and the smoke/CO ones — and an earlier
    version of this refused the whole piston for having two, which threw away
    the very case that motivates the work. A piston may say "which of these,
    and also which of those".

    Returns [(variable, [start], [adds], [users]), ...], empty when none.
    """
    out = []
    for var in sorted({n for p in promises if p.per_device and p.accumulates()
                       for n in p.writes}):
        adds = [p for p in promises
                if p.per_device and p.accumulates() and var in p.writes]
        starts = [p for p in promises
                  if not p.per_device and var in p.writes and not p.accumulates()]
        users = [p for p in promises if var in p.reads and var not in p.writes]
        out.append((var, starts, adds, users))
    return out



def _is_cursor(t) -> bool:
    """Is this test asking about the LOOP'S CURSOR rather than about a device?

    `$device` is webCoRE's "the one I am standing on" inside a per-device loop.
    It is not a device, it is never in the picker, and it has no meaning
    outside the loop — so it can never be looked up, never goes offline and
    never comes back, which is why the remembered-binding safeguard
    (`storage.remember_binding`, Jeremy's 2026-07-19 ruling) cannot help it.

    Emitted at automation level it became `unknown.pistoncore_unresolved_$device`,
    Home Assistant rejected the entity id as invalid, and DISABLED THE WHOLE
    AUTOMATION — triggers and actions both (HARD_RULES §20, measured on
    `38_Low_Battery_Check` 2026-08-22: `state: unavailable`, never fired).

    And nothing was lost by it, because HOME ASSISTANT HAS ALREADY ANSWERED
    THAT QUESTION (Jeremy, 2026-08-24: *"ha just goes does any of these devices
    meet this requirment"*). The loop's collection emits a `numeric_state`/
    `state` trigger listing every entity — which fires when ANY of them
    matches — and a `condition: or` over the same list. The cursor test was a
    second, broken copy of a question already asked natively.

    The cursor's real job is the other one: walking the list to build the
    sentence, where each device contributes its OWN name and its OWN reading.
    That happens inside the report template and is untouched."""
    s = getattr(t, "subject", None)
    return tuple(getattr(s, "devices", ()) or ()) == ("$device",)


def _without_cursor(g):
    """The same gate with its cursor tests removed, or None if that was all it
    said. Structure is preserved: an AND/OR group keeps its shape and its other
    children, because the gate's shape IS intent (spec.Gate's own docstring)."""
    if isinstance(g, spec.Gate):
        kids = tuple(k for k in (_without_cursor(c) for c in g.children)
                     if k is not None)
        if not kids:
            return None
        from dataclasses import replace
        return replace(g, children=kids)
    return None if _is_cursor(g) else g


def _cursor_test(p):
    """The loop's own per-device test, which the report consumes."""
    found = None
    for g in p.gated_by:
        for t in (g.leaves() if isinstance(g, spec.Gate) else [g]):
            if _is_cursor(t):
                found = t
    return found


class _Unexpressible(Exception):
    """A leaf this emitter has no words for. Raised rather than returned so a
    nested group cannot quietly lose one child and change its own meaning."""


def _gate_node(g):
    """One gate as the NESTED condition IR the emitter ALREADY understands.

    THE TREE IS THE INTENT AND FLATTENING IT IS A SILENT WRONG ANSWER.
    `spec.Gate`'s own docstring says it: flattening makes "motion AND dark"
    and "motion OR dark" identical, and drops NOT so the false case reads as
    the true one. This function exists because `plan()` used to call
    `g.leaves()` and hand the emitter a flat list, which did both.

    Measured on Jeremy's `door chime` (2026-08-25): the piston says "chime
    quietly between 8pm and 8am (weekdays OR weekends), otherwise chime
    louder". Flattened, the two day-halves became an AND — mon-fri AND
    sat-sun, which is never true — so the automation triggered and said
    NOTHING, and the NOT that separated day from night vanished entirely,
    leaving both branches with identical conditions.

    NOTHING NEW IS BUILT HERE. `_group` / `group_op` is the shape
    `analyze._cond_node` already produces and `emit_yaml._condition` already
    renders into HA's own `condition: and` / `or` / `not` blocks
    (automation.yaml.j2:176). The intent path simply never fed it one.

    Leaves that WAKE the automation are still skipped, matching the previous
    behaviour: they are triggers, and repeating them as conditions would gate
    the automation on the event that just fired."""
    if isinstance(g, spec.Gate):
        kids = []
        for c in g.children:
            k = _gate_node(c)
            if k is not None:
                kids.append(k)
        if not kids:
            return None
        if len(kids) == 1 and not g.negated:
            return kids[0]
        return {"co": "_group", "group_op": (g.op or "and"),
                "group_negated": bool(g.negated),
                "children": kids,
                # the flat keys every consumer of a condition node reads; a
                # group answers "not applicable" to all of them, exactly as
                # analyze._cond_node does.
                "ct": "c", "devices": [], "attr": None, "lo_type": "group",
                "value": None, "value2": None, "duration": {},
                "aggregation": "any", "lo_var": None,
                "value_vt": None, "value2_vt": None,
                "value_preset": None, "value2_preset": None, "raw": {}}
    if _is_cursor(g):
        return None
    if getattr(g, "wakes", False):
        return None
    n = _leaf(g)
    if n is None:
        raise _Unexpressible(str(getattr(g, "operator", "?")))
    return n


def _gate_sig(g) -> str:
    """A gate's identity, negation INCLUDED. Two promises carrying the same
    signature are gated by the same thing and belong in the same block."""
    return g.describe()


def _gate_base(g):
    """(identity ignoring negation, is_negated) — the pair that says whether
    two gates are exact OPPOSITES. `spec.Gate` already carries `negated`
    separately from the tree, which is what makes this answerable at all."""
    if isinstance(g, spec.Gate) and g.negated:
        from dataclasses import replace
        return replace(g, negated=False).describe(), True
    if not isinstance(g, spec.Gate) and getattr(g, "negated", False):
        return g.negate().describe(), True
    return g.describe(), False


def _are_opposites(a: tuple, b: tuple) -> bool:
    """Do these two gate-sets say "when X" and "when NOT X"?

    Used to turn a pair of blocks into ONE `if/else`, which is how Home
    Assistant writes "otherwise". Requires a single differing gate: two
    conditions that each flip is not an if/else, it is four cases."""
    if len(a) != 1 or len(b) != 1:
        return False
    (ka, na), (kb, nb) = _gate_base(a[0]), _gate_base(b[0])
    return ka == kb and na != nb


def _report_node(p, var, test):
    """One report, as the node the emitter resolves. Slots only — no HA words.

    The emitter turns these into the single template (report_variables); this
    side just says WHAT the report is: which devices, which test decides
    membership, and what each match contributes.

    `test` is passed IN rather than dug back out of `p.gated_by`, because by
    now it has been removed from there — see `_is_cursor`. The report is the
    one and only consumer of it, and making that a parameter is what stops a
    second copy leaking to automation level again."""
    expr = ""
    for sub in p.params:
        if sub.kind == "expr" and sub.expression:
            expr = sub.expression
    return {"kind": "report", "var": var,
            "over": list(p.per_device_over),
            "attr": test.subject.attribute if test else None,
            "test": _leaf(test) if test is not None else None,
            "expr": expr}


def plan(piston: dict, piston_id: str, piston_name: str):
    """Branch IR built from the piston's INTENT, or None if not expressible."""
    promises = spec.read(piston)
    if not promises:
        return None
    # ONE PASS, TWO PREPARATIONS, IN THIS ORDER — the order is the point.
    #
    # 1. THE LOOP'S CURSOR STOPS BEING A DEVICE. `$device` is consumed by the
    #    report that owns it and taken off the promise, so no later step can
    #    emit it as a trigger, a condition, or a reason to split the piston up
    #    (see `_is_cursor`).
    # 2. Only THEN give the unwoken promises the event their own words imply.
    #    Derived wakes are read off the gate, so stripping first is what keeps
    #    the cursor from becoming a trigger via the back door — which is
    #    exactly how it got into `38_Low_Battery_Check`'s trigger list.
    #
    # Both happen before grouping: grouping is by what wakes a promise AND by
    # its gate, so a promise still carrying the cursor keys differently from
    # its own header and its own notification and lands in a separate
    # automation — which is why that piston built its device list into a
    # variable nothing read, and sent the header on its own.
    from dataclasses import replace
    cursor_test: dict = {}
    prepared = []
    for p in promises:
        cursor = _cursor_test(p)
        if cursor is not None:
            p = replace(p, gated_by=tuple(
                g for g in (_without_cursor(x) for x in p.gated_by)
                if g is not None))
        if not p.wakes_on:
            p = replace(p, wakes_on=_wake_from_intent(p))
        if cursor is not None:
            cursor_test[id(p)] = cursor
        prepared.append(p)
    promises = prepared
    behaviours = spec.behaviours(promises)

    # Which promises are the per-device half of a report. Worked out ONCE,
    # before grouping, because a report is a property of the piston's value
    # flow rather than of any single promise.
    reports = report_groups(promises)
    report_for = {id(p): var for var, _s, adds, _u in reports for p in adds}

    # Anything the intent layer carries but emission cannot yet honour must
    # refuse, not approximate: a per-device fan-out, a repeat, or a poll
    # interval changes what the automation IS.
    flat = []
    for b in behaviours:
        if isinstance(b, spec.Held):
            if b.engage.per_device or b.release.per_device: return _refuse("held pair is per-device (fan-out)")
            if b.engage.repeating or b.release.repeating: return _refuse("held pair is inside a loop")
            # BOTH HALVES, ALWAYS. A held state is one intent but two
            # promises, and the first version of this loop emitted only the
            # engage — on 12_Cave_motion_V2 the lights came on and NOTHING
            # turned them off again. Grouping puts them back together when
            # they share a wake and leaves them apart when they don't; that
            # is the grouping's job, not a reason to drop one.
            flat.append(b.engage)
            flat.append(b.release)
        else:
            # A PER-DEVICE LOOP THAT BUILDS A REPORT IS NOT A LOOP. 16 of the
            # 17 per-device loops in the corpus say "tell me which of these
            # match", and Home Assistant answers that with one template — so
            # the loop stops existing rather than being translated. Anything
            # else per-device still refuses.
            if b.per_device and id(b) in report_for:
                flat.append(b)
                continue
            if b.per_device or b.repeating: return _refuse("per-device fan-out" if b.per_device else "inside a loop")
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
        # THE GATE IS NO LONGER PART OF THE KEY, and that is the fix for a
        # chime that fired and said nothing (2026-08-25). Keying on the gate
        # put "build the Message" and "speak the Message" in SEPARATE
        # top-level branches, and Home Assistant scopes a `variables:` block
        # to the sequence that declares it — so `Message` did not exist by the
        # time the speak ran. HA emitted a valid automation, triggered it,
        # set the right volume, and spoke an empty string.
        #
        # One event -> one sequence, in order, with the gates that DIFFER
        # nested inside it. That is also how a person writes this automation
        # by hand, and it is what the transcoder already does.
        key = _wake_key(p)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(p)

    branches = []
    for i, key in enumerate(order):
        members = groups[key]
        lead = members[0]
        if not lead.wakes_on:
            return _refuse("nothing wakes it and no wake could be derived")

        triggers, gates = [], []
        for t in lead.wakes_on:
            n = _leaf(t)
            if n is None:
                return _refuse("trigger shape not expressible: %s" % (t.operator,))
            triggers.append(n)
        # GATES EVERY MEMBER SHARES belong to the automation; gates only SOME
        # of them carry belong inside the sequence, next to the actions they
        # actually guard. Splitting it this way is what lets one event own one
        # automation without losing anyone's conditions.
        #
        # THE GATE KEEPS ITS SHAPE either way. See `_gate_node` — flattening
        # is what turned "weekdays OR weekends" into "weekdays AND weekends".
        members_sorted = sorted(members, key=lambda x: x.order)
        sigs = [{_gate_sig(g): g for g in m.gated_by} for m in members_sorted]
        shared = set(sigs[0])
        for d in sigs[1:]:
            shared &= set(d)
        for k, g in sigs[0].items():
            if k not in shared:
                continue
            try:
                n = _gate_node(g)
            except _Unexpressible as exc:
                return _refuse("gate shape not expressible: %s" % (exc,))
            if n is not None:
                gates.append(n)

        # THE DELAY IS PART OF THE PROMISE AND WAS BEING LEFT BEHIND HERE
        # (2026-08-13). `Promise.after` is read correctly -- "wait 10 seconds,
        # then play reveille" -- and `_task()` never carried it, so on the
        # intent path the whole sequence fired at once. Measured against the
        # pistons' own promises: 08 lost a 30-minute turn-off, 09 and 46 lost
        # the 10 seconds before the volume and the announcement, 42 lost the
        # five gaps in the school wake-up, 48 lost 200ms and 1s.
        #
        # `after` is measured from the TRIGGER, not from the previous action,
        # so the wait to insert is the difference. Two promises both at
        # after=10 are simultaneous; emitting 10 then another 10 would push the
        # second one out to 20 and invent a delay the piston never asked for.
        # Consecutive promises with the SAME leftover gate share one block, so
        # "set the volume then speak" stays two actions under one condition
        # rather than the same condition written twice.
        runs, clock = [], 0
        for m, sig in zip(members_sorted, sigs):
            extra = tuple(k for k in sig if k not in shared)
            gap = int(m.after or 0) - clock
            if gap > 0:
                clock = int(m.after or 0)
            node = (_report_node(m, report_for[id(m)], cursor_test.get(id(m)))
                    if id(m) in report_for else _task(m))
            if node is None:
                return _refuse("an action could not be expressed")
            if runs and runs[-1][0] == extra and gap <= 0:
                runs[-1][1].append(node)
            else:
                if gap > 0:
                    runs.append(((), [{"kind": "delay", "delay_seconds": gap}]))
                runs.append((extra, [node], sig))

        then = []
        idx = 0
        while idx < len(runs):
            run = runs[idx]
            extra, nodes = run[0], run[1]
            if not extra:
                then.extend(nodes)
                idx += 1
                continue
            sig = run[2]
            try:
                conds = [c for c in (_gate_node(sig[k]) for k in extra) if c is not None]
            except _Unexpressible as exc:
                return _refuse("gate shape not expressible: %s" % (exc,))
            # "OTHERWISE" IS `else:`, NOT A SECOND BRANCH WITH A NEGATED COPY.
            # HA's own word for the false case, and it keeps both halves in the
            # same scope as the variables built above them.
            els = []
            nxt = runs[idx + 1] if idx + 1 < len(runs) else None
            if nxt is not None and nxt[0] and _are_opposites(
                    [sig[k] for k in extra],
                    [nxt[2][k] for k in nxt[0]]):
                els = nxt[1]
                idx += 1
            if conds:
                then.append({"kind": "if", "conditions": conds,
                             "then": nodes, "else": els})
            else:
                then.extend(nodes)
                then.extend(els)
            idx += 1

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
    # `t` IS NOT OPTIONAL. The emitter decides how to render a parameter from
    # the operand's TYPE key -- `prm.get("t") in ("x", "e")` is what makes a
    # variable become a runtime template instead of a literal. Building the
    # operand without it meant `{"x": "Day_Vol"}` fell through to the constant
    # path, arrived as None, and six of Albert's pistons died on "a 'pct_float'
    # parameter has no value" while the transcoder compiled them fine. Operands
    # read from the piston JSON carry `t` already; synthesised ones have to say
    # it too. Same class as the delay that was read and then not passed on.
    if sub.kind == "constant":
        return {"t": "c", "c": sub.constant, "vt": sub.vt}
    if sub.kind == "preset":
        return {"t": "s", "s": sub.preset, "vt": sub.vt}
    if sub.kind == "variable":
        return {"t": "x", "x": sub.variable, "vt": sub.vt}
    if sub.kind == "expr":
        return {"t": "e", "e": sub.expression, "vt": sub.vt}
    if sub.kind == "argument":
        return {"t": "u", "u": sub.argument, "vt": sub.vt}
    if sub.kind == "device":
        return {"t": "d", "d": list(sub.devices), "vt": sub.vt}
    return {"vt": sub.vt}


def _task(promise):
    """A promise as the action node the emitter consumes — from the reading."""
    return {"kind": "task", "command": promise.command,
            "devices": list(promise.devices),
            "params": [_param(p) for p in promise.params],
            "custom": bool(promise.custom),
            "raw": {}, "raw_stmt": {}}

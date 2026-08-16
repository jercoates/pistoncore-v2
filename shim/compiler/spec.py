"""SPEC — the behaviour spec: everything needed to write the YAML.

STAGE 3. Stage 1 is the reader (`analyze.py`, gated: every task in every piston
is reachable). Stage 2 is commitments (`commitment.py`, gated: nothing dropped
or invented). This stage sits between them and is what the other two were
missing a middle for.

WHAT IT PRODUCES, and why that is the whole point (Jeremy, 2026-08-08: "all the
info to create the yaml"). Not a label. Not a one-line purpose. A LABEL CANNOT
EMIT ANYTHING — that is why the first attempt at this layer was deleted. Each
record here carries enough to generate the automation from, and belongs to
neither webCoRE's grammar nor Home Assistant's syntax:

    what wakes it · what must hold · what happens to which devices ·
    with what values · after what delay · how often · in what order

CARRIES EVERY SLOT, INCLUDING THE ONES NOTHING ELSE READS. Eight grammar slots
are currently read by no line of the compiler (`odw`, `odm`, `owm`, `omy`,
`to2`, `dm`, `dn`, `wt`), and one of them is device-proven to break real
pistons: a "weekdays only" piston fires every day, so a school alarm wakes the
kids on Saturday. They are carried here whether or not emission uses them yet,
because a slot the spec does not carry is a slot that CANNOT be emitted later
and will be lost silently. `unsupported()` reports what is carried but not yet
emitted — an honest list, never silence (HARD_RULES §6).

DETERMINISTIC, NO MODEL (HARD_RULES §2b). Home Assistant runs on Raspberry Pis;
a local model is not shippable and a cloud call breaks "works with nobody
upstream". Everything here is a walk over the forced forms.

IT READS THE FORMS, IT DOES NOT INVENT SHAPES (HARD_RULES §2a). webCoRE's editor
builds statements from a bounded set of forms and the picker cascade decides
which slots each one has. This module fills those slots from the JSON. It does
NOT classify pistons into a taxonomy of its own — that was the deleted layer's
mistake, and "the pattern is a part not the whole" is why naming shapes was
never going to be the answer.

WHAT IT DOES NOT DO. It does not choose an HA idiom, name a service, or build
YAML. That is emission, and it stays in `emit_yaml.py` + the templates where
the hard-won HA knowledge already lives (HARD_RULES §8).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import routing

# Grammar slots this module CARRIES but nothing emits yet. Named here so the
# gap is a reportable fact rather than a silence — see unsupported().
NOT_YET_EMITTED = {
    "only_days_of_week": "the piston restricts which weekdays it may run",
    "only_days_of_month": "the piston restricts which days of the month",
    "only_weeks_of_month": "the piston restricts which weeks of the month",
    "only_months": "the piston restricts which months",
    "hold2": "a second duration qualifier on the same condition",
    "capture_matching": "capture the devices that matched into a variable",
    "capture_other": "capture the devices that did NOT match into a variable",
    "within": "the 'followed by' window option flag",
}


@dataclass
class Subject:
    """What a test measures. One of a device attribute, a virtual device, a
    variable or an expression — the picker cannot produce anything else."""

    kind: str                      # 'device' | 'virtual' | 'variable' | 'expr'
    devices: tuple = ()            # refs as written: hash, variable or @global
    attribute: str | None = None
    virtual: str | None = None     # $time, $alarmSystemStatus, ...
    variable: str | None = None
    aggregation: str = "any"       # g: any/all/... across several devices
    interaction: str | None = None  # p: any / physically / programmatically
    index: object = None           # xi — {list[2]} is not {list[5]}
    var_type: str | None = None    # the DECLARED type from piston.v
    members: tuple = ()            # a device variable's actual member hashes
    preset: str | None = None      # s  — sunrise/sunset live here
    constant: object = None        # c  — a literal is not an expression
    argument: str | None = None    # u  — {$args.name}
    expression: str | None = None  # e  — the expression TEXT, not the word
    vt: str | None = None          # the operand's UNIT/type ('m', 'time', ...)

    # How the EDITOR words an aggregation (piston.module.js renderDeviceList).
    # Ported, not invented — the editor is ground truth for what the user was
    # shown when they authored it (HARD_RULES §2f).
    _AGG = {"any": "Any of ", "all": "All of ", "count": "Count of ",
            "avg": "Average of ", "median": "Median of ",
            "least": "Least of ", "most": "Most of "}

    def describe(self, aggregate: bool = True) -> str:
        """`aggregate=False` for a list being ITERATED rather than combined.

        An aggregation says how to fold an attribute across several devices —
        "any of them is wet", "the average of their temperatures". A loop does
        neither: it visits each one. The operand still carries a `g`, because
        the editor leaves its default (`avg`) behind on operands that never
        aggregate, so an `each` over nine water sensors read as "for each of
        AVERAGE OF {Water_Sensor_All}". Reading a leftover default as a
        decision, the same way a stale `ro2` once produced "daily at sunrise
        and sunrise"."""
        if self.kind == "device":
            who = ", ".join("{%s}" % d for d in self.devices) if self.devices else "?"
            # The prefix appears when there is more than one device OR the ref
            # is a VARIABLE — because a variable stands for a list whose size
            # the piston cannot show. Dropping it made "any of these sensors
            # went wet" and "all of them did" read identically: 231 lines of
            # the corpus, and a different automation in each case.
            several = len(self.devices) > 1 or any(
                not str(d).startswith(":") for d in self.devices)
            agg = (self._AGG.get(self.aggregation, "")
                   if several and aggregate else "")
            # ONLY when the attribute actually supports the distinction — the
            # editor gates this on the attribute's `p` flag (renderOperand
            # :4246). Without the gate this reader printed "lock physically
            # changes to unlocked", inventing a distinction `lock` does not
            # have. Added and caught within the hour by the same diff.
            how = ""
            if self.interaction in ("p", "s"):
                from .resolve import _load_vocab
                attr = ((_load_vocab().get("attributes") or {})
                        .get(self.attribute) or {})
                if attr.get("p"):
                    how = " physically" if self.interaction == "p" else " programmatically"
            # A BARE DEVICE LIST has no attribute — "the lights" is a
            # complete subject on its own and must not render "'s None".
            if not self.attribute:
                return f"{agg}{who}"
            return f"{agg}{who}'s {self.attribute}{how}"
        if self.kind == "virtual":
            # The editor shows the virtual device's DISPLAY NAME ("Alarm system
            # status"), not its token. Same information, and the token is
            # webCoRE's spelling rather than anything the user chose.
            from .resolve import _load_vocab
            vd = ((_load_vocab().get("virtualDevices") or {})
                  .get(self.virtual) or {})
            return vd.get("n") or f"${self.virtual}"
        if self.kind == "variable":
            ix = f"[{self.index}]" if self.index is not None else ""
            return f"{{{self.variable}{ix}}}"
        if self.kind == "preset":
            # SUNRISE AND SUNSET LIVE HERE. Collapsing a preset to the words
            # "an expression" is why a sun offset was invisible to this reader
            # while the editor plainly says "30 minutes past sunrise".
            return str(self.preset)
        if self.kind == "constant":
            return str(self.constant)
        if self.kind == "argument":
            return f"{{$args.{self.argument}}}"
        if self.kind == "expr" and self.expression:
            return "{%s}" % self.expression
        return "an expression"


def operand_value(v):
    """An operand's value, whatever KIND the picker produced.

    Reading only `c` loses every non-constant operand: a PRESET
    (`{t:'s', s:'sunrise'}`) and a system variable (`{t:'x', x:'$sunrise'}`)
    both vanish, so "happens daily at sunrise" reads as "happens daily at"
    with nothing at all — visible in `15_Chicken_Lights_morning`, where two of
    four triggers had no time.

    MODULE LEVEL because COMMAND PARAMETERS need the same rule and were not
    getting it: promises read `p[].c` only, so a parameter that was an
    expression or a variable came through as None and the intent said the
    command had no value. Same operand grammar, same reader — the fix belongs
    in the one function, never a second copy (HARD_RULES §9)."""
    if not isinstance(v, dict):
        return None
    # `u` IS THE FIFTH KIND AND WAS MISSING. `_subject` has always read it
    # (Subject.argument), so the two readers of the same operand grammar
    # disagreed — exactly the split this docstring warns about, one kind short.
    # `05_Basement_Person_Detection` stores `$now` into `datetime_LastAlert` to
    # remember when it last alerted, and the value it stores read as nothing.
    for k in ("c", "s", "x", "e", "u"):
        if v.get(k) is not None:
            return v[k]
    return None


# The editor's own calendar names, and CRUCIALLY its two different bases:
# `weekDays[odw[i]]` is ZERO-based with Sunday first, while
# `yearMonths[omy[i] - 1]` is ONE-based (piston.module.js:35-36, renderer
# :4286 and :4319). Getting either wrong shifts every restriction by a day or
# a month and still looks entirely plausible.
_WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday",
             "Friday", "Saturday"]
_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]


def _ordinal(n: int) -> str:
    n = int(n)
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def say_days(odw=(), odm=(), owm=(), omy=()) -> str:
    """A subject's calendar restriction, worded as the editor words it.

    Printed as raw index lists (`only on days [1, 2, 3, 4, 5]`) nobody can
    check this against a piston, and it is the restriction that has already
    been device-proven to go missing entirely."""
    def joined(items):
        items = list(items)
        if len(items) == 1:
            return items[0]
        return ", ".join(items[:-1]) + " or " + items[-1]
    bits = []
    if odw:
        bits.append("on " + joined([_WEEKDAYS[int(d) % 7] + "s" for d in odw]))
    if owm:
        bits.append("on the " + joined([_ordinal(w) for w in owm]) + " week of the month")
    if odm:
        bits.append("on the " + joined([_ordinal(d) for d in odm]) + " day of the month")
    if omy:
        bits.append("in " + joined([_MONTHS[int(m) - 1] for m in omy if 1 <= int(m) <= 12]))
    return ("but only " + ", ".join(bits)) if bits else ""


def _clock(v, subject) -> str:
    """A time operand as a clock time, the way the editor shows it.

    webCoRE stores a time of day as MINUTES SINCE MIDNIGHT, so a piston that
    fires at 07:00 reads as `420`. Left raw, a time comparison is unreadable
    and a wrong one is undetectable — "is between 420 and 1230" tells nobody
    anything. 42 lines of the corpus are times.

    Only applied when the SUBJECT is a time, never to bare numbers: 420 lux
    must stay 420 lux."""
    # A VARIABLE DECLARED `time` IS A TIME TOO. Keying only on the system
    # $time device left every time-typed variable rendering as a raw
    # minutes-since-midnight number. webCoRE offers time/date/datetime as
    # variable types AND as list forms of each, so the declared type has to be
    # honoured wherever it appears — and Home Assistant has the matching shape
    # (`input_datetime`), which `helpers.py` already builds.
    kind = getattr(subject, "kind", None)
    declared = str(getattr(subject, "var_type", "") or "").rstrip("[]")
    if (kind == "virtual" and subject.virtual in ("time", "date", "datetime")) \
            or (kind == "variable" and declared in ("time", "date", "datetime")):
        try:
            m = int(v)
        except (TypeError, ValueError):
            return str(v)
        if 0 <= m < 1440:
            h, mm = divmod(m, 60)
            ap = "AM" if h < 12 else "PM"
            h12 = h % 12 or 12
            return f"{h12}:{mm:02d}:00 {ap}"
    return str(v)


@dataclass
class Test:
    """One comparison, with every slot the fall rule can attach to it."""

    subject: Subject
    operator: str | None = None
    values: tuple = ()             # ro / ro2 — count decided by the operator's p
    hold: int | None = None        # to  — "for N" / "in the last N", seconds
    hold2: int | None = None       # to2 — SECOND qualifier, read by nothing today
    offset: int | None = None      # `to` when it is a SUN offset, not a hold

    # ── WHAT MAKES THIS RUN: TWO FACTS, NOT ONE ────────────────────────────
    # Collapsing them is the bug underneath the worst misreadings here, so they
    # are kept apart and named for what they MEAN rather than how webCoRE
    # spells them (the spec is owned by neither platform — HARD_RULES §2b).
    #
    # `wakes`   — the author said THIS is the occasion: "when water CHANGES TO
    #             wet". An edge. It is the piston's purpose showing (§2e), and
    #             it is what decides how often a person gets bothered.
    # `watched` — the platform has to keep an eye on this subject so the gate
    #             can be answered again. Every device behind every condition
    #             qualifies. It is machinery, not purpose.
    #
    # A test can be watched WITHOUT being the occasion, and that is the common
    # case: `29_Gas_Detector_2` is watched on "gas is CLEAR" (the loop's exit
    # test) and on presence. Reading those as occasions says the gas alarm
    # starts when the detectors go clear, and that somebody coming home sets it
    # off. Reading them as nothing at all is how five pistons came to look like
    # they had nothing to start them, when webCoRE had recorded the answer.
    wakes: bool = False
    watched: bool | None = None
    # The author overrode subscription by hand — the editor's "+ Always
    # subscribe" / "- Never subscribe" badges (piston.module.html:824-825).
    # An explicit statement about what should start this, so it outranks every
    # inference below it.
    wake_forced: str | None = None
    negated: bool = False          # this test must be FALSE for the gate to hold
    # restrictions that ride on the SUBJECT operand, not the statement.
    # Read by nothing in the compiler today; device-proven to be lost.
    only_days_of_week: tuple = ()
    only_days_of_month: tuple = ()
    only_weeks_of_month: tuple = ()
    only_months: tuple = ()
    capture_matching: str | None = None   # dm
    capture_other: str | None = None      # dn
    within: str | None = None             # wt
    raw: object = None             # the condition node, for translation ONLY
    # The right-hand operands, parsed by the SAME reader as the left one
    # (_subject). `values` above flattens them to bare values for describe();
    # this keeps each one's KIND, so emission can tell the preset `sunrise`
    # from the literal string "sunrise" without going back to the raw JSON.
    right: tuple = ()

    def _phrasing(self):
        """The comparison as the EDITOR words it, and its unit.

        Ported from `renderComparison` (piston.module.js:4259): the vocab's `d`
        display string, or `dd` when the operand is several devices — webCoRE
        saying "presence ARE not present" instead of "is", which is it telling
        you in plain English that this is a multi-device test.

        The vocab is a HELPER here, never the authority (Jeremy: "the vocab
        helps with intent to a point") — if it has nothing to say, the raw
        operator is used and nothing is lost."""
        from .resolve import _load_vocab
        v = _load_vocab()
        comp = ((v.get("comparisons") or {}).get("triggers") or {}).get(self.operator) \
            or ((v.get("comparisons") or {}).get("conditions") or {}).get(self.operator) \
            or {}
        s = self.subject
        plural = (s.kind == "device" and s.aggregation == "all"
                  and (len(s.devices) > 1
                       or any(not str(d).startswith(":") for d in s.devices)))
        word = (comp.get("dd") if plural else None) or comp.get("d") \
            or str(self.operator or "").replace("_", " ")
        unit = ""
        if s.kind == "device" and s.attribute:
            unit = ((v.get("attributes") or {}).get(s.attribute) or {}).get("u") or ""
        return word, unit

    def describe(self) -> str:
        word, unit = self._phrasing()
        bits = [self.subject.describe(), word]
        if self.values:
            # The unit rides on the VALUE, as the editor shows it: "700lux".
            # Dropped, a threshold reads as a bare number and a unit change
            # would never be noticed.
            bits.append(" and ".join(_clock(v, self.subject) + unit
                                     for v in self.values))
        if self.offset:
            m = abs(self.offset) // 60
            bits.append("(%d min %s)" % (m, "after" if self.offset > 0 else "before"))
        if self.hold:
            bits.append(f"for {self.hold}s")
        cal = say_days(self.only_days_of_week, self.only_days_of_month,
                       self.only_weeks_of_month, self.only_months)
        if cal:
            bits.append(cal)
        said = " ".join(b for b in bits if b)
        return f"NOT ({said})" if self.negated else said

    def negate(self) -> "Test":
        from dataclasses import replace
        return replace(self, negated=not self.negated)


@dataclass
class Gate:
    """A boolean tree over Tests — the shape of "what must hold".

    WHY THIS IS NOT BOOKKEEPING. Flattening a group to its leaves makes
    "motion AND dark" and "motion OR dark" identical, and they are different
    things the user wanted (HARD_RULES §10: the gate's structure is intent).
    It also decides what the automation IS: with OR, either side can WAKE it,
    so both become triggers; with AND, one wakes it and the other is a check.
    Same words, same devices, different automation. A reading that cannot tell
    them apart cannot choose an HA idiom, which is why every layer built on the
    flattened form stalled at "recorded but not usable".

    NEGATION LIVES HERE TOO, and it is the other half of the same hole. webCoRE
    states the false case in three places — a condition's `fs`, an `else`, and
    the `n` flag on a statement or group. Without a way to say NOT, all three
    read as if the test were TRUE, so "turn the light off when motion stops"
    came out as "turn the light off while motion is active". That is a silent
    inversion, which is worse than a drop (HARD_RULES §6): it emits confidently
    and does the opposite.

    Fields are webCoRE's own, VERIFIED in PISTON_JSON_REFERENCE §2.1/§3: `o` on
    a statement or group node, `n` to negate it, `rop`/`rn` for restrictions,
    and `on` forcing "or"."""

    op: str = "and"                # 'and' | 'or' | 'xor' — as webCoRE wrote it
    children: tuple = ()           # Test | Gate, in the order authored
    negated: bool = False          # the whole group is inverted (`n` / `rn`)

    def describe(self) -> str:
        if not self.children:
            return ""
        joiner = f" {self.op.upper()} "
        said = joiner.join(c.describe() for c in self.children if c.describe())
        if len(self.children) > 1:
            said = f"({said})"
        return f"NOT {said}" if self.negated else said

    def negate(self) -> "Gate":
        from dataclasses import replace
        return replace(self, negated=not self.negated)

    def leaves(self) -> tuple:
        """Every Test in the tree, in order. For asking which tests WAKE the
        automation — a question about the leaves, not about the shape."""
        out = []
        for c in self.children:
            out += list(c.leaves()) if isinstance(c, Gate) else [c]
        return tuple(out)


@dataclass
class Promise:
    """One thing that must happen, with everything needed to emit it."""

    command: str
    devices: tuple                 # refs as written; resolution is emission's job
    values: tuple = ()             # the command's declared parameters, in order
    wakes_on: tuple = ()           # Tests that subscribe
    gated_by: tuple = ()           # Tests that must hold (incl. restrictions)
    after: int = 0                 # seconds of delay ahead of it
    per_device: bool = False       # inside an each -> runs once per device
    # WHAT THE `each` RUNS OVER. "for each of THESE" is part of the intent, and
    # without it a per-device promise says it repeats but not over what — which
    # left the only route to the device list as guessing from a sibling gate.
    per_device_over: tuple = ()
    repeating: bool = False        # inside a repeat/while
    order: int = 0                 # position, and order IS intent (§10)
    virtual: bool = False          # a CONTROL command, not a device command
    custom: bool = False           # `cm` — a RAW command, not in the vocabulary
    raw_task: object = None        # the task node, for translation ONLY
    # The command's parameters, parsed by the SAME operand reader as every
    # other operand (_subject). `values` flattens them to bare values; these
    # keep the kind and unit, so emission never has to reopen the raw task.
    params: tuple = ()
    raw_stmt: object = None        # the statement it sat in, for translation
    source: str = ""               # where in the piston, for the report
    # THE THREAD BETWEEN STATEMENTS. A value one statement writes and another
    # reads is what makes them one thing the user wanted rather than two
    # unrelated acts (HARD_RULES §10). Without it, the three writes that build
    # `Water_Status` and the one send that reports it read as four separate
    # promises, and the flags that make a light "get out of your way" scatter.
    writes: tuple = ()
    reads: tuple = ()

    def accumulates(self) -> bool:
        """Is this value built FROM ITSELF — `Water_Status = Water_Status + x`?

        The distinction that a flat reading cannot make: the same command,
        against the same variable, is "start a fresh list" or "add to the list"
        depending only on whether its own name appears in the value."""
        return bool(set(self.writes) & set(self.reads))

    def outcome(self) -> str | None:
        """The KIND of thing this is, in plain words rather than webCoRE's.

        `intent.outcome_of` is the one table that answers this and it is gated
        complete against the whole vocabulary, so it is asked rather than
        re-decided here (HARD_RULES §9 — a second, partial copy of a
        vocabulary table is this project's most expensive recurring bug).

        This is the layer the spec is supposed to be written in: `playText`,
        `sendSMSNotification` and `speak` are three webCoRE spellings of
        TELLING A PERSON, and an automation that has to inform someone is the
        fact worth carrying forward. The exact command survives beside it for
        translation, but nothing choosing the shape of an automation should
        have to know webCoRE's word for it."""
        from . import intent
        return intent.outcome_of(self.command)

    def describe(self) -> str:
        who = ", ".join(self.devices) if self.devices else "(no device)"
        when = f" after {self.after}s" if self.after else ""
        each = " (once per device)" if self.per_device else ""
        rep = " (repeating)" if self.repeating else ""
        wake = (" on " + "; ".join(t.describe() for t in self.wakes_on)
                if self.wakes_on else "")
        gate = (" only if " + "; ".join(t.describe() for t in self.gated_by)
                if self.gated_by else "")
        val = f" {list(self.values)}" if self.values else ""
        return f"{who}: {self.command}{val}{each}{rep}{when}{wake}{gate}"


# ── reading the forced forms ────────────────────────────────────────────────


_VARS: dict = {}


def _declared_vars(piston: dict) -> dict:
    """name -> (declared type, member device hashes) from the piston itself.

    THE TYPE NEVER REACHED THE READING BEFORE THIS. webCoRE offers 19 variable
    types (10 basic + 9 list forms, `variableTypes`), and a `device` variable
    is a GROUP — `Water_Sensor_All` is nine sensors, `duh` is two. Read as a
    bare name, a device group, a string and a `time[]` list are the same token,
    so the reading cannot tell "any of nine sensors" from one, and cannot know
    a list can be indexed or iterated.

    Read straight from `piston.v` (PISTON_JSON_REFERENCE §1), so it needs no
    resolution map and no Home Assistant. `@global` lists live outside the
    piston and stay unexpanded — a stated limit, not a silent one."""
    from .resolve import local_device_vars, local_var_decls
    devs = local_device_vars(piston)
    decls = local_var_decls(piston)
    return {name: (d.get("type"), tuple(str(x) for x in devs.get(name, ())))
            for name, d in decls.items()}


def _subject(lo: dict) -> Subject:
    """Every operand kind the picker can produce, kept apart.

    They were collapsing into "an expression", which threw away the value, the
    preset (sunrise/sunset) and the index — so `{list[2]}` and `{list[5]}` read
    identically and a sun offset read as nothing at all."""
    lo = lo or {}
    kind = lo.get("t")
    vt = lo.get("vt")
    if kind == "v":
        return Subject("virtual", virtual=lo.get("v"), vt=vt)
    if kind == "x":
        name = lo.get("x")
        _vt, members = _VARS.get(str(name), (None, ()))
        return Subject("variable", variable=name, index=lo.get("xi"),
                       var_type=_vt, members=members, vt=vt)
    if kind == "s":
        return Subject("preset", preset=lo.get("s"), vt=vt)
    if kind == "u":
        return Subject("argument", argument=lo.get("u"), vt=vt)
    if kind == "e":
        return Subject("expr", expression=lo.get("e"), vt=vt)
    if kind == "c":
        return Subject("constant", constant=lo.get("c"), vt=vt)
    if kind == "d":
        # a bare DEVICE LIST — no attribute, so it must not render "'s None"
        return Subject("device", devices=tuple(str(d) for d in (lo.get("d") or [])),
                       aggregation=lo.get("g") or "any")
    if lo.get("a") or lo.get("d"):
        mem = []
        for d in (lo.get("d") or []):
            mem += list(_VARS.get(str(d), (None, ()))[1])
        return Subject("device", members=tuple(mem),
                       devices=tuple(str(d) for d in (lo.get("d") or [])),
                       attribute=lo.get("a"),
                       aggregation=lo.get("g") or "any",
                       interaction=lo.get("p"))
    return Subject("expr")


def _seconds(op) -> int | None:
    from .resolve import duration_seconds
    return duration_seconds(op) if isinstance(op, dict) else None


def _classify(cond: dict) -> str:
    from .analyze import _classify as _c
    return _c(cond)


# A `{N}` slot, optionally wrapped in `[?prefix ... ]` meaning "show this
# prefix only if the slot has a value". Ported verbatim from the editor's own
# task renderer (piston.module.js:4561).
_TASK_SLOT = __import__("re").compile(r"(?:\[\?(.*?))?\{(\d)\}(?:\s*\])?")

# The editor's duration wording (piston.module.js:4369-4381), read here rather
# than restated as a second table.
_DURATION_UNIT = {"ms": "millisecond", "s": "second", "m": "minute",
                  "h": "hour", "d": "day", "w": "week", "n": "month",
                  "y": "year"}


def say_duration(secs: int) -> str:
    """A delay the way a person says it, not always in seconds.

    The author wrote "wait 10 minutes"; normalising to 600 for arithmetic is
    right, printing 600 back at them is not."""
    for size, word in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if secs >= size and secs % size == 0:
            n = secs // size
            return f"{n} {word}{'' if n == 1 else 's'}"
    return f"{secs} second{'' if secs == 1 else 's'}"


def _added_part(p: "Promise") -> str:
    """What a self-building assignment ADDS, with its own name stripped off.

    `Water_Status = Water_Status + <device> + battery` adds the device and its
    battery; repeating the variable back is the mechanism, not the point."""
    raw = (p.raw_task or {}).get("p") or []
    for i, param in enumerate(raw):
        if i == 0 or not isinstance(param, dict):
            continue
        said = str(((param.get("exp") or {}).get("str") or "")).strip()
        for name in p.writes:
            if said.startswith(name):
                said = said[len(name):].strip()
        return said
    return ""


def say_task(p: "Promise") -> str:
    """One task in the words the EDITOR shows, not webCoRE's field names.

    THE PLAIN ENGLISH WAS ALREADY IN THE VOCABULARY and nothing read it. Every
    command carries a display template — `"Speak text \\"{0}\\""`,
    `"Set variable {0} = {1}"`, `"Set Volume to {0}"` — and each parameter can
    carry its own fragment, which is where `" at volume {v}"` comes from. That
    is how the editor draws `Speak text "Naomi time to get up" at volume 100`,
    and it is what a person actually authored against.

    Printing `playText ['Naomi time to get up', 100]` instead was webCoRE's
    internal spelling leaking into a layer that is supposed to belong to
    neither platform.

    Ported from `renderTask` (piston.module.js:4541-4585, SEALED — read, never
    edited), including its three rules that are not obvious:
      - a `[?...]` prefix appears only when its slot produced something;
      - an optional parameter explicitly set to `false` is not shown at all;
      - a `duration` parameter takes its unit word from the operand's own type.
    A command the vocabulary has never heard of keeps its own name, which is
    the raw feed working as intended."""
    from .resolve import _load_vocab
    v = _load_vocab()
    cmd = ((v.get("commands") or {}).get(p.command)
           or (v.get("virtualCommands") or {}).get(p.command) or {})

    # WHERE webCoRE'S WORDS STOP DESCRIBING (Jeremy, 2026-08-10: "a lot of the
    # webcore language IS descriptive, in those cases it is great"). Almost all
    # of it is kept — "Turn on", "Speak text", "Set Volume to 90", "changes to
    # wet" are what anyone would say, and replacing them would be churn with a
    # chance of getting it wrong.
    #
    # A VARIABLE IS THE EXCEPTION, because the assignment shows the mechanism
    # and hides the purpose. `Set variable {Water_Status} = {Water_Status
    # $device " - " {[$device:battery]}"%"}` is webCoRE telling you HOW; what
    # the author was doing is BUILDING A REPORT of which sensors are wet. The
    # two cases are told apart by nothing more than whether the variable's own
    # name appears in its new value, which is why this needs the value flow and
    # could never be read off the command.
    if p.writes:
        name = p.writes[0]
        if p.accumulates():
            add = _added_part(p)
            return f"add to {{{name}}}" + (f": {add}" if add else "")
        val = (p.values[1] if len(p.values) > 1 else "")
        return f"start {{{name}}}" + (f" = {val}" if val not in (None, "") else "")

    fmt = cmd.get("d")
    if not fmt:
        # No template: the command's display name, or — for a raw HA service
        # the vocab has never seen — the name the author picked.
        return cmd.get("n") or p.command
    decls = cmd.get("p") or []
    raw = (p.raw_task or {}).get("p") or []

    def slot(m):
        prefix, idx = m.group(1), int(m.group(2))
        if idx >= len(raw):
            return " (?) "
        decl = decls[idx] if idx < len(decls) else {}
        rp = raw[idx] if isinstance(raw[idx], dict) else {}
        said = p.params[idx].describe() if idx < len(p.params) else ""
        if decl.get("t") == "duration":
            unit = _DURATION_UNIT.get(rp.get("vt"), "")
            said = f"{said} {unit}s".rstrip() if said else ""
        elif rp.get("t") == "c" and decl.get("d") and rp.get("c") == "false":
            said = ""                      # an unset optional flag is not shown
        if said and decl.get("d"):
            said = decl["d"].replace("{v}", said) if rp.get("t") else ""
        return ((prefix or "") + said) if said else ""

    return _TASK_SLOT.sub(slot, fmt).replace("{T}", "°")


def value_names(node) -> set:
    """Every variable an operand DEPENDS ON, however deeply it is nested.

    A value can be a bare variable operand (`{t:'x', x:'Water_Status'}`) or a
    variable token buried in an expression's parse tree — and webCoRE nests
    expressions inside expressions, so `Water_Status $device " - "
    {[$device:battery]}` has its tokens two levels down. Walking only the top
    level found none of them.

    `$device`-style DEVICE tokens are deliberately not collected: they carry
    `t:'device'`, they are the loop's current device rather than a value the
    piston keeps, and counting them would tie every statement in a loop to
    every other one."""
    out = set()
    if isinstance(node, dict):
        if node.get("t") in ("variable", "x") and node.get("x"):
            out.add(str(node["x"]))
        for v in node.values():
            out |= value_names(v)
    elif isinstance(node, list):
        for v in node:
            out |= value_names(v)
    return out


def _writes_reads(task: dict, cmd: dict) -> tuple:
    """(what this task SETS, what its value DEPENDS ON).

    Which parameter is the target is declared BY THE VOCABULARY — a parameter
    of type `variable` — so this is derived from the same table the editor
    builds its picker from, not a list of command names kept in step by hand
    (HARD_RULES §9). Today only `setVariable` qualifies; a command added later
    gets the behaviour without touching this code.

    The target must not count as a read, or every assignment would look like it
    depended on itself and `Water_Status = Water_Status + ...` would be
    indistinguishable from `Water_Status = "start again"` — which is exactly
    the difference between building a list up and starting a fresh one."""
    decls = cmd.get("p") or []
    params = task.get("p") or []
    writes, reads = set(), set()
    for i, param in enumerate(params):
        if not isinstance(param, dict):
            continue
        decl = decls[i] if i < len(decls) else {}
        if decl.get("t") == "variable":
            if param.get("x"):
                writes.add(str(param["x"]))
        else:
            reads |= value_names(param)
    return tuple(sorted(writes)), tuple(sorted(reads))


def _wakes(cond: dict) -> bool:
    """Is THIS test the occasion the author wanted acted on?

    THE AUTHOR'S OWN OVERRIDE WINS. The editor lets a condition be forced to
    subscribe or never to subscribe, and draws a badge for it — that is a
    person stating outright what should start this, so no inference may
    overrule it. Read by nothing in the compiler before now, and invisible to
    the corpus because all 388 of its conditions are left on the default
    (HARD_RULES §5: what nobody has written yet still has to work)."""
    forced = cond.get("sm")
    if forced == "never":
        return False
    if forced == "always":
        return True
    return _classify(cond) == "t"


def _test(cond: dict) -> Test:
    """One condition node -> a Test with every slot the grammar allows.

    The operand-level restriction slots (`odw`/`odm`/`owm`/`omy`) live on `lo`,
    NOT on the statement, which is why every review that walked statements
    missed them and why a compiler passing all its gates still fires a
    weekday-only piston on a Saturday."""
    if cond.get("t") == "event":
        # An `on <events> do` entry — a bare subscription with an `lo` and no
        # comparison at all (VERIFIED piston.module.js:1481-1484). It has no
        # `ct`, so the old test read the ONE form whose entire purpose is the
        # trigger as having no trigger.
        return Test(subject=_subject(cond.get("lo") or {}),
                    operator="changes", wakes=True)
    lo = cond.get("lo") or {}
    ro, ro2 = cond.get("ro") or {}, cond.get("ro2") or {}

    _val = operand_value

    # HOW MANY right operands this comparison actually HAS — the vocab
    # declares it as `p` (the picker cascade again: the operator decides how
    # many slots the editor shows). Reading `ro2` regardless produced
    # "happens daily at $sunrise and $sunrise", because the editor leaves a
    # stale second operand behind and only `p` says whether it means anything.
    from .resolve import _load_vocab
    _c = (_load_vocab().get("comparisons") or {})
    _spec = (_c.get("triggers") or {}).get(cond.get("co"))         or (_c.get("conditions") or {}).get(cond.get("co")) or {}
    _n = _spec.get("p")
    _n = 2 if _n is None else int(_n)
    values = tuple(x for x in (_val(ro), _val(ro2))[:_n] if x is not None)


    # `to` IS AN OFFSET, NOT A HOLD, when the subject is a time and the right
    # side is not a constant — the editor gates it exactly this way
    # (piston.module.js:4254). "sunrise + 10 minutes" was being read as
    # "sunrise, held for 600 seconds", which is a different trigger.
    is_time_subject = (lo.get("t") == "v" and lo.get("v") in
                       ("time", "date", "datetime"))
    offset_not_hold = is_time_subject and ro.get("t") not in (None, "c")
    return Test(
        subject=_subject(lo),
        operator=cond.get("co"),
        values=values,
        right=tuple(_subject(o) for o in (ro, ro2)[:_n] if o),
        # A DURATION QUALIFIER ONLY EXISTS IF THE COMPARISON DECLARES ONE.
        # The vocab's `t` says so (1 = "for N", 2 = "for at least/less than"),
        # and the editor renders it on exactly that condition. `happens_daily_at`
        # declares none — so a `to` sitting on one is STALE DATA left behind
        # when the operand was changed from a sun preset to a fixed time.
        # Read blindly it produced "happens daily at 8:00 PM for -1800s",
        # a negative hold that means nothing and that the editor never shows.
        hold=(None if (offset_not_hold or _spec.get("t") not in (1, 2))
              else _seconds(cond.get("to"))),
        hold2=(None if (offset_not_hold or _spec.get("t") not in (1, 2))
               else _seconds(cond.get("to2"))),
        offset=_seconds(cond.get("to")) if offset_not_hold else None,
        # WHAT WAKES IT, decided by the compiler's ONE classifier. `ct` is
        # stamped by the engine and is ABSENT on any piston that never ran
        # through one — imported, AI-authored, or hand-built. Testing `ct ==
        # "t"` directly (which this did) made every such piston read as having
        # no trigger at all: 13 in the corpus, and `40_My_Lock` reads as
        # trigger-less here while the compiler correctly emits an automation
        # with triggers for it. `_classify` falls back to the vocabulary
        # bucket, which PISTON_JSON_REFERENCE §3 names as the authority.
        # A second copy of an existing tool, wrong in the exact case the
        # original exists to handle (HARD_RULES §9).
        wakes=_wakes(cond),
        # webCoRE's OWN RECORD of what it watches, not a re-derivation of it.
        # PISTON_JSON_REFERENCE §3: "whether this condition is subscribed —
        # i.e. actually drives event subscriptions". 18 conditions in the
        # corpus say yes while their `ct` says "condition", and every one sits
        # in a piston that otherwise reads as having nothing to start it.
        watched=cond.get("s"),
        wake_forced=(cond.get("sm")
                     if cond.get("sm") in ("always", "never") else None),
        only_days_of_week=tuple(lo.get("odw") or ()),
        only_days_of_month=tuple(lo.get("odm") or ()),
        only_weeks_of_month=tuple(lo.get("owm") or ()),
        only_months=tuple(lo.get("omy") or ()),
        capture_matching=lo.get("dm"),
        capture_other=lo.get("dn"),
        within=cond.get("wt"),
        # CARRIED FOR TRANSLATION, NEVER FOR STRUCTURE. The intent decides
        # which automation a test belongs to; this is only how the leaf's
        # value gets filled in afterwards (Jeremy: "the translation comes in
        # after intent to fill the spots needed").
        raw=cond,
    )


def _gate(nodes, op: str = "and", negated: bool = False) -> Gate:
    """A condition list as the boolean tree webCoRE saved it, never as leaves.

    Nested groups keep their OWN operator and negation (`o`/`n` on the group
    node, VERIFIED PISTON_JSON_REFERENCE §3), so "motion AND (dark OR late)"
    survives as that and not as three loose comparisons."""
    children = []
    for c in nodes or []:
        if not isinstance(c, dict):
            continue
        if c.get("t") == "group":
            children.append(_gate(c.get("c"), c.get("o") or "and",
                                  bool(c.get("n"))))
        else:
            children.append(_test(c))
    return Gate(op=op or "and", children=tuple(children), negated=bool(negated))


# The editor's OWN wording for the task-cancellation picker
# (piston.module.html:357, badges :499-501). Anything outside this set — empty
# string, or the key absent — is the "Never" option, which is how the editor
# itself decides which badge to draw.
_CANCEL_PENDING = {"c": "condition changes",
                   "p": "piston changes",
                   "b": "condition or piston changes"}


def _cancel_pending(st: dict) -> str:
    """When this statement runs again, is work already waiting thrown away?

    READ BY THE INTENT LAYER FOR THE FIRST TIME. `analyze.py` carries it for
    translation, but nothing that decides what an automation IS has ever
    looked at it — and it decides whether a re-trigger restarts a pending
    timer or leaves two of them running, which is the difference between one
    notification and several.

    NOTE, not corrected here: `analyze.py` reads it as
    `stmt.get("tcp", "c") or "c"`, so an author who explicitly picks "Never"
    (which the editor saves as an empty string) has it silently turned into
    "cancel on condition change" — the opposite. Every statement in the corpus
    is an explicit "c", so nothing here changes today."""
    return _CANCEL_PENDING.get(st.get("tcp"), "never")


def _restrictions(node: dict) -> tuple:
    """Statement- or piston-level restrictions as one gate ("only when ...").

    Their operator and negation are `rop`/`rn`, NOT `o`/`n` — a separate pair
    on the same node (VERIFIED §2.1), so reading them with the condition
    operator would silently apply the wrong one."""
    if not node.get("r"):
        return ()
    return (_gate(node.get("r"), node.get("rop") or "and",
                  bool(node.get("rn"))),)


def _conditions(st: dict) -> Gate:
    """A statement's own conditions, honouring the forced forms.

    `on` forces "or" with negation off (VERIFIED §2.2) — that IS the form's
    meaning: any of these events wakes it."""
    if st.get("t") == "on":
        return _gate(st.get("c"), "or", False)
    return _gate(st.get("c"), st.get("o") or "and", bool(st.get("n")))


class _Reader:
    def __init__(self, piston: dict):
        self.piston = piston
        self.waits = set(routing.wait_commands())
        self.out: list[Promise] = []
        self.n = 0
        # the `each` device lists currently open, innermost last
        self._each_over: list[tuple] = []

    def read(self) -> list[Promise]:
        global _VARS
        _VARS = _declared_vars(self.piston)
        self._statements(self.piston.get("s"), (), _restrictions(self.piston),
                         "piston", False, False)
        return self.out

    def _statements(self, stmts, wake, gate, where, per_device, repeating):
        """A statement list, in order. `after` accumulates across it because a
        wait holds up everything behind it — which is what "after this delay"
        means, and the ordering is itself intent (HARD_RULES §10)."""
        after = 0
        for st in stmts or []:
            if not isinstance(st, dict) or st.get("di"):
                continue
            after = self._statement(st, wake, gate, where, per_device,
                                    repeating, after)

    def _statement(self, st, wake, gate, where, per_device, repeating, after):
        t = st.get("t")
        me = f"{where}/${st.get('$')}"
        gate = gate + _restrictions(st)

        if t == "action":
            for task in st.get("k") or []:
                if not isinstance(task, dict):
                    continue
                cmd = task.get("c")
                if cmd in self.waits:
                    after += _seconds((task.get("p") or [{}])[0]) or 0
                    continue
                self.n += 1
                # THE VALUE FLOW BELONGS TO BOTH READERS, NOT ONE (2026-08-13).
                # `writes`/`reads` were wired into the tree reader's promise
                # builder only, so every promise from THIS reader came back with
                # empty sets and `accumulates()` was False everywhere — which is
                # why 38_Low_Battery_Check read "start {Battery_Status}" where it
                # means "add to". `emit_intent.plan()` consumes this reader, so
                # the whole report shape was invisible to emission. Same helper,
                # same vocabulary lookup — never a second copy (HARD_RULES §9).
                from .resolve import _load_vocab
                _v = _load_vocab()
                _cmd = ((_v.get("commands") or {}).get(cmd)
                        or (_v.get("virtualCommands") or {}).get(cmd) or {})
                _writes, _reads = _writes_reads(task, _cmd)
                self.out.append(Promise(
                    command=cmd,
                    writes=_writes, reads=_reads,
                    devices=tuple(str(d) for d in (st.get("d") or [])),
                    values=tuple(operand_value(p) for p in (task.get("p") or [])
                                 if isinstance(p, dict)),
                    params=tuple(_subject(p) for p in (task.get("p") or [])
                                 if isinstance(p, dict)),
                    wakes_on=wake, gated_by=gate, after=after,
                    per_device=per_device,
                    per_device_over=(self._each_over[-1] if self._each_over else ()),
                    repeating=repeating,
                    order=self.n, source=me,
                    custom=bool(task.get("cm")),
                    # For TRANSLATION only — the parameters and the device list
                    # this promise's command needs spelled out in HA terms. The
                    # intent above already decided the promise exists and what
                    # wakes it; nothing structural is read back out of these.
                    raw_task=task, raw_stmt=st))
            return after

        # THE GATE STAYS A TREE. An earlier reading split the conditions into
        # "wakes" and "holds" and threw the shape away — which is what made
        # AND and OR identical. The waking tests are a QUESTION ABOUT THE
        # LEAVES (which ones subscribe); the gate is the whole tree, because
        # webCoRE evaluates a trigger condition as a condition too. Whether a
        # waking leaf ALSO needs re-checking as an HA condition is an emission
        # decision — with OR it does, with a single AND leaf it does not — and
        # deciding it here would be this layer choosing an HA idiom, which is
        # not its job.
        g = _conditions(st)
        wakes = tuple(x for x in g.leaves() if x.wakes)

        # WORK HANGS OFF CONDITIONS. A statement can have an EMPTY body and
        # carry its whole job on `ts`/`fs` — 42 of the corpus's 507 tasks live
        # here, and one water-leak statement keeps a repeat loop and a
        # per-device announcement two levels deep in `ts`.
        self._attached(st.get("c"), wake + wakes, gate, me, per_device, repeating)
        for r in st.get("r") or []:
            if isinstance(r, dict):
                self._attached([r], wake + wakes, gate, me, per_device, repeating)

        if t == "if":
            # A LATER BRANCH ALSO MEANS "AND NONE OF THE EARLIER ONES MATCHED".
            # That is the whole meaning of else / else-if, and leaving it out
            # made an else-branch promise read as unconditional — the light
            # turning off looked like something that always happens.
            self._statements(st.get("s"), wake + wakes, gate + (g,),
                             f"{me}/then", per_device, repeating)
            earlier = [g]
            for i, ei in enumerate(st.get("ei") or []):
                eg = _gate(ei.get("c"), ei.get("o") or "and", bool(ei.get("n")))
                self._attached(ei.get("c"), wake + wakes, gate, f"{me}/ei{i}",
                               per_device, repeating)
                self._statements(
                    ei.get("s"), wake + wakes,
                    gate + tuple(e.negate() for e in earlier) + (eg,),
                    f"{me}/ei{i}", per_device, repeating)
                earlier.append(eg)
            self._statements(st.get("e"), wake + wakes,
                             gate + tuple(e.negate() for e in earlier),
                             f"{me}/else", per_device, repeating)
        elif t == "on":
            self._statements(st.get("s"), wake + g.leaves(), gate, me,
                             per_device, repeating)
        elif t == "every":
            self._statements(st.get("s"), wake, gate, me, per_device, True)
        elif t == "each":
            over = tuple(str(d) for d in ((st.get("lo") or {}).get("d") or []))
            self._each_over.append(over)
            try:
                self._statements(st.get("s"), wake + wakes, gate + (g,), me,
                                 True, repeating)
            finally:
                self._each_over.pop()
        elif t in ("repeat", "while", "for"):
            self._statements(st.get("s"), wake + wakes, gate + (g,), me,
                             per_device, True)
        elif t == "switch":
            for case in st.get("cs") or []:
                self._statements(case.get("s"), wake + wakes, gate, me,
                                 per_device, repeating)
            self._statements(st.get("e"), wake + wakes, gate, me,
                             per_device, repeating)
        elif t == "do":
            self._statements(st.get("s"), wake + wakes, gate + (g,), me,
                             per_device, repeating)
        return after

    def _attached(self, conds, wake, gate, where, per_device, repeating):
        for c in conds or []:
            if not isinstance(c, dict):
                continue
            if c.get("t") == "group":
                # Groups carry no ts/fs of their own (§3) — only conditions do.
                self._attached(c.get("c"), wake, gate, where, per_device,
                               repeating)
                continue
            here = _test(c)
            if c.get("ts"):
                self._statements(c["ts"], wake, gate + (here,),
                                 f"{where}/ts", per_device, repeating)
            if c.get("fs"):
                # `fs` IS THE FALSE CASE. Gating it on the un-negated test said
                # the opposite of the piston: "turn the light off" came out as
                # "while motion is active". A confident inversion, not a drop.
                self._statements(c["fs"], wake, gate + (here.negate(),),
                                 f"{where}/fs", per_device, repeating)
            self._attached(c.get("c"), wake, gate, where, per_device, repeating)


@dataclass
class Block:
    """One statement, with what wakes it, what gates it, and its body — TOGETHER.

    STEP 0, AND THE REASON EVERY PREVIOUS ATTEMPT PRODUCED AN INVENTORY.
    The flat reader below walks the same statements but pushes each trigger and
    gate DOWN onto every task underneath, so one restriction written once on the
    piston arrives as 21 identical copies stapled to 21 promises. At that point
    "written once, covering everything" and "written 21 times" are ind22
    istinguishable, and the shape the intent was stated in is gone.

    Every step of the reading — what wakes this, what sits under it, how this
    block differs from that one, what the whole thing is for — is a walk over
    structure. On a flat list they are not missing features, they are
    impossible. So the tree is kept, and nothing is copied downward.

    This is also the mistake that got `pattern.py` deleted (flatten, then guess
    the shape back). It was rebuilt here in a new file without noticing, which
    is why `_held` has to re-pair two statements that were adjacent all along."""

    kind: str                      # the statement form, as authored
    stmt_id: object = None
    wakes: tuple = ()              # Tests that subscribe, AT THIS LEVEL
    gate: object = None            # Gate written at this level, not inherited
    restrictions: tuple = ()       # "only when ...", stated here, said once
    does: tuple = ()               # Promises written directly in this block
    children: tuple = ()           # nested Blocks, in authored order
    per_device: bool = False
    repeating: bool = False
    branch: str = ""               # 'then' | 'else' | 'ei0' | 'ts' | 'fs' | ''
    interval: int = 0              # trailing wait: how often a loop RE-CHECKS
    # WHAT HAPPENS TO WORK ALREADY WAITING when this statement runs again —
    # in plain words, never webCoRE's letter codes. "Turn the light off in 5
    # minutes" that is re-triggered either restarts its 5 minutes or ends up
    # with two timers, and that difference is what the user feels
    # (HARD_RULES §2e: not spamming me is the point).
    # None = not a statement of the author's at all (the `when-true`, `else`
    # and `case` blocks this reader builds to hold structure). Only a real
    # authored statement can carry a policy, and saying "never" for the rest
    # would be inventing an answer to a question nobody asked.
    cancel_pending: str | None = None
    attached_to: object = None     # the Test whose ts/fs this block hangs off
    promoted_wake: bool = False    # woken via condition subscription, not a trigger
    # WHAT THE AUTHOR SAID IT IS FOR, in their own words (`z`, the description
    # the editor shows). EVIDENCE, NEVER THE ANSWER: a description can be
    # stale, copied from whoever shared the piston, or plain wrong, and a
    # reading that leans on it is the supervised-by-labels trap. It is carried
    # because discarding what the author wrote down is throwing away the one
    # place purpose is stated outright, and because it lets a read be checked
    # against it without asking a person.
    note: str = ""
    # WHAT A LOOP RUNS OVER, and what the body calls each one. An `each` says
    # "do this to every one of these" (HARD_RULES §2a) and the list is the
    # whole point of the form — but it lives on the statement's `lo` operand,
    # which this reader walked straight past, so a fan-out over nine water
    # sensors read as "for each of" followed by nothing. `x` is the name the
    # body refers to them by, defaulting to `$device`.
    over: object = None
    loop_var: str = ""

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    # The form each statement takes, said the way the editor says it. These are
    # not translations invented here — they are the words on the editor's own
    # keyword lines and dialog text (`until` piston.module.html:708, the WHILE
    # description :991, the repeat-loop description piston.module.js:1209).
    # A reading nobody can read is a reading nobody can check.
    _FORM = {"piston": "", "if": "", "action": "do", "each": "for each of",
             "repeat": "keep doing this", "while": "keep doing this",
             "every": "repeatedly", "on": "", "do": "do", "for": "count through",
             "switch": "depending on", "case": "in the case", "else": "otherwise",
             "else-if": "or else when", "when-true": "and when",
             "when-false": "and when NOT"}

    def describe(self, depth: int = 0, parent_wakes: frozenset = frozenset()) -> str:
        pad = "  " * depth
        head = pad + (self._FORM.get(self.kind, self.kind) or "")
        if self.over is not None and self.over.describe(aggregate=False):
            head += " " + self.over.describe(aggregate=False)
            if self.loop_var and self.loop_var != "$device":
                head += f" (each called {{{self.loop_var}}})"
        if self.note:
            head += "  (author's note: %s)" % " ".join(self.note.split())
        said_wake = "; ".join(t.describe() for t in self.wakes)
        if self.wakes:
            head += " WHEN " + said_wake
        if self.gate is not None and self.gate.describe():
            # THE EDITOR'S OWN KEYWORD, because the word is the meaning. A
            # `repeat` is a repeat-UNTIL — it runs its body until the condition
            # is met (piston.module.js:1209, and the editor draws the keyword
            # `until`, piston.module.html:708) — while a `while` runs its body
            # for as long as the condition holds (piston.module.html:991).
            # Printing both as "IF" made the water piston read as "announce the
            # leak only if every sensor is dry", which is the piston backwards.
            word = {"repeat": "UNTIL", "while": "WHILE"}.get(self.kind, "IF")
            gate_said = self.gate.describe()
            # SAID ONCE, THE WAY IT WAS WRITTEN. The waking test deliberately
            # stays in the gate as well (that is what keeps `OR` pistons
            # correct on emit), but repeating it here is the editor stating one
            # trigger twice — noise that buried the real gate on 69 of 76
            # pistons. Suppressed for READING only; the gate itself is
            # untouched.
            # SAID ONCE. The waking test deliberately stays in the gate too —
            # that is what keeps `OR` pistons correct when they are emitted —
            # but showing it in both places is the editor's one trigger printed
            # twice. Only ever dropped from an AND, where re-checking a leaf
            # changes nothing; inside an OR each leaf genuinely matters, so
            # nothing is hidden there.
            if word == "IF" and self.wakes:
                spoken = {t.describe() for t in self.wakes}
                if gate_said in spoken:
                    gate_said = ""
                elif getattr(self.gate, "op", "") == "and":
                    rest = [c.describe() for c in self.gate.children
                            if c.describe() and c.describe() not in spoken]
                    gate_said = (" AND ".join(rest) if len(rest) > 1
                                 else (rest[0] if rest else ""))
            if gate_said:
                head += f" {word} " + gate_said
        if self.attached_to is not None:
            # The condition this block hangs off, said as one clause instead of
            # the reader's two ("... is true OF ..." read like machine output).
            head = pad + "and when " + self.attached_to.describe()
            head += (" is true" if self.kind == "when-true" else "")
        for r in self.restrictions:
            if r.describe():
                head += " ONLY-WHEN " + r.describe()
        if self.per_device:
            head += " (once for each one)"
        if self.interval:
            head += f", checking again every {say_duration(self.interval)}"
        if self.cancel_pending not in (None, "condition changes"):
            head += f" (work already waiting is dropped when the "
            head += f"{self.cancel_pending})"
        # AN EMPTY HEADER IS NOISE, NOT STRUCTURE. A block whose only task was
        # a wait, or a `when-true` hanging off the very condition that already
        # woke the statement above it, adds a line that says nothing and buries
        # the lines that do. The block still EXISTS in the tree — only its
        # heading is skipped, so nothing is lost from the reading.
        redundant = (self.attached_to is not None and parent_wakes
                     and self.attached_to.describe() in parent_wakes)
        bare = not head.strip() or (not self.does and not self.children)
        out = [] if (redundant or bare) else [head]
        if redundant:
            depth -= 1
        for p in self.does:
            when = f" — after {say_duration(p.after)}" if p.after else ""
            who = ", ".join(p.devices) if p.devices else ""
            # PLAIN WORD FIRST, webCoRE's word second. What the automation has
            # to accomplish is "tell a person"; `playText` is merely how this
            # piston happened to say it.
            #
            # THE EDITOR'S SENTENCE, not webCoRE's field names. `say_task`
            # reads the display template the vocabulary already carries, which
            # is the same one the author was looking at when they wrote this.
            said = say_task(p)
            with_who = f"{who}: " if who else ""
            out.append(f"{pad}   - {with_who}{said}{when}")
        for c in self.children:
            out.append(c.describe(depth + 1))
        return "\n".join(out)


def read_tree(piston: dict) -> Block:
    """The piston as the shape it was written in. Nothing pushed downward."""
    global _VARS
    _VARS = _declared_vars(piston)
    root = Block(kind="piston", restrictions=_restrictions(piston),
                 note=(piston.get("z") or "").strip())
    root.children = tuple(_block(st) for st in (piston.get("s") or [])
                          if isinstance(st, dict) and not st.get("di"))
    _promote(root)
    return root


def _promote(root: Block) -> None:
    """A piston with no trigger still runs — webCoRE subscribes to the devices
    its CONDITIONS reference.

    Without this, five corpus pistons read as "nothing starts this", including
    `29_Gas_Detector_2` and `40_My_Lock`, while the compiler correctly emits
    automations with triggers derived from exactly these conditions. A safety
    piston reading as unreachable is the worst version of a silent wrong
    answer (HARD_RULES §6).

    It must NOT fire on a genuinely manual piston — Jeremy's sound and light
    tests have no conditions to promote and run from webCoRE's Test button, so
    keying on "has device conditions" separates them without a special case."""
    NOT_A_SUBSCRIPTION = ("repeat", "while", "for")

    def subscribable(g):
        """The leaves of one gate that name a real device to subscribe to.

        TWO KINDS OF CONDITION LOOK LIKE DEVICES AND ARE NOT.

        A LOOP VARIABLE. Inside an `each`, `$device` is whichever device this
        pass is handling — there is no device to subscribe to, and the leaf
        was written to filter the loop, not to start the piston.

        And the promotion has to be conservative for the same reason it
        exists: `29_Gas_Detector_2` has no trigger, so every one of these got
        promoted and the read said the gas alarm WAKES WHEN THE DETECTORS ARE
        CLEAR — the piston backwards, on a safety piston."""
        out = []
        for leaf in g.leaves():
            s = leaf.subject
            if s.kind != "device" or not s.devices:
                continue
            if any(str(d).startswith("$") for d in s.devices):
                continue
            out.append(leaf)
        return out

    def own_gate(b):
        """The gate to promote from — a LOOP'S is its exit test, not a wake.

        `repeat ... until all clear` asks "am I done yet" after each pass. It
        is answered at the END of an iteration, never on a device event, so
        subscribing to it says the piston starts when the emergency ENDS.

        NOR IS ANYTHING INSIDE A LOOP. A test in a loop body is asked again on
        every pass, about whichever device the pass is handling — it filters
        the iteration. `29_Gas_Detector_2` checks presence inside its `each`
        to decide whether to text as well as push; promoted, that read as "the
        gas alarm starts when somebody comes home"."""
        if b.gate is None or b.kind in NOT_A_SUBSCRIPTION:
            return None
        if b.repeating or b.per_device:
            return None
        return b.gate

    blocks = list(root.walk())
    if any(b.wakes for b in blocks):
        return
    promoted = []
    for b in blocks:
        g = own_gate(b)
        for gate in ([g] if g is not None else []) + list(b.restrictions):
            promoted += subscribable(gate)
    if not promoted:
        return                      # genuinely manual: the Test button runs it
    root.promoted_wake = True
    for b in blocks:
        g = own_gate(b)
        if g is not None:
            hits = subscribable(g)
            if hits:
                b.wakes = b.wakes + tuple(hits)


def _virtual_commands() -> set:
    """webCoRE's CONTROL commands, as the vocab lists them (59).

    They are not device commands and must not read as though they were.
    `pausePiston`, `executePiston`, `noop`, `setVariable` and `exit` change the
    flow or the piston's own state; "pause the other piston" is a different
    kind of thing from "turn on a light", and the reading called them the same.
    `routing.wait_commands()` knew about 4 of these; the other 55 were
    undifferentiated."""
    from .resolve import _load_vocab
    return set(_load_vocab().get("virtualCommands") or {})


def _promises_of(st: dict, per_device: bool, repeating: bool) -> tuple:
    """Just the tasks written in THIS action statement — no inherited context."""
    from . import routing
    waits = set(routing.wait_commands())
    virt = _virtual_commands()
    out, after = [], 0
    for task in st.get("k") or []:
        if not isinstance(task, dict):
            continue
        if task.get("c") in waits:
            after += _seconds((task.get("p") or [{}])[0]) or 0
            continue
        from .resolve import _load_vocab
        _v = _load_vocab()
        _cmd = ((_v.get("commands") or {}).get(task.get("c"))
                or (_v.get("virtualCommands") or {}).get(task.get("c")) or {})
        _writes, _reads = _writes_reads(task, _cmd)
        out.append(Promise(command=task.get("c"),
                           writes=_writes, reads=_reads,
                           devices=tuple(str(d) for d in (st.get("d") or [])),
                           values=tuple(operand_value(p) for p in (task.get("p") or [])
                                        if isinstance(p, dict)),
                           params=tuple(_subject(p) for p in (task.get("p") or [])
                                        if isinstance(p, dict)),
                           after=after, per_device=per_device,
                           repeating=repeating, source=str(st.get("$")),
                           virtual=task.get("c") in virt,
                           # `cm` MEANS DO NOT LOOK IT UP. The editor gates on
                           # it — `!task.cm && getCommandById(...)`
                           # (piston.module.js:4536) — and renders the command
                           # raw. It is how a raw HA service reaches the picker
                           # ([[hybrid_vocab_plus_raw_feed]]), so reading a
                           # custom command as a vocabulary one treats a
                           # service the vocab has never heard of as though it
                           # had. `analyze.py:212` has carried this for months.
                           custom=bool(task.get("cm")),
                           raw_task=task, raw_stmt=st))
        # `after` IS NOT RESET. A wait delays everything that follows it, not
        # just the next task — the tasks in a `with ... do` run one after
        # another, so once the sequence is 10 seconds in, it stays 10 seconds
        # in. Resetting it put the delay on the first task only:
        # `02_Alarm_Intrusion_Albert` is "wait 10, set volume, play the siren"
        # and read as the volume changing after 10 seconds while the siren
        # sounded IMMEDIATELY — the siren jumping ahead of the volume it
        # depends on, and the intrusion alarm playing at whatever volume
        # happened to be set.
    # A WAIT WITH NOTHING BEHIND IT IS NOT A DELAY — IT IS AN INTERVAL.
    # Absorbing a wait into the "after" of the next task loses it completely
    # when there is no next task, which is exactly where it matters: the last
    # thing in a repeat loop is "wait, then test the condition again", i.e. how
    # often the loop RE-CHECKS. Jeremy, 2026-08-08, on `70_Water_Leak`: "the 60
    # seconds is a wait before it checks the state again." Dropped, the piston
    # reads as an unthrottled loop instead of a once-a-minute poll.
    return tuple(out), after


def _delay_subtree(b: "Block", secs: int) -> None:
    """Push a delay onto everything this block and its children promise.

    A wait does not stop at the end of the statement it was written in — the
    statements after it happen that much later, however deeply they nest."""
    from dataclasses import replace
    b.does = tuple(replace(p, after=p.after + secs) for p in b.does)
    for c in b.children:
        _delay_subtree(c, secs)


def _kids(stmts, per_device=False, repeating=False, branch="") -> tuple:
    """The statements of one body, in order, with waits carried ACROSS them.

    A TRAILING WAIT IS ONLY AN INTERVAL WHEN IT ENDS A LOOP. `_promises_of`
    hands back a wait that had no task behind it, and its note is right about
    the case it was written for: the last thing in a repeat is "wait, then test
    again", which is how often the loop re-checks (`70_Water_Leak`, 60s).

    But that was applied to EVERY action block, and most trailing waits do not
    end a loop — they end one `with ... do` inside an ordinary `if`, and mean
    "pause before the next one". Read as an interval, the pause was reported as
    a re-check on a block that never repeats AND the delay vanished from every
    statement after it: `42_New_School_piston` says "speak, wait 10 seconds",
    then wakes Naomi with reveille and her lights — which read as firing at the
    same instant as the speech.

    So the interval reading is kept for exactly the case that earned it — the
    last statement of a loop body — and every other trailing wait is carried
    forward onto the statements it delays, which is what the editor shows and
    what the flat reader has always done."""
    out, carry = [], 0
    kept = [st for st in stmts or []
            if isinstance(st, dict) and not st.get("di")]
    for i, st in enumerate(kept):
        b = _block(st, per_device, repeating)
        b.branch = branch or b.branch
        if carry:
            _delay_subtree(b, carry)
        ends_a_loop = repeating and i == len(kept) - 1
        if b.interval and not ends_a_loop:
            carry += b.interval
            b.interval = 0
        out.append(b)
    return tuple(out)


def _attached_blocks(conds, per_device, repeating) -> tuple:
    """Work hung on a condition's true/false lists, kept where it was written."""
    out = []
    for c in conds or []:
        if not isinstance(c, dict):
            continue
        if c.get("t") == "group":
            out += list(_attached_blocks(c.get("c"), per_device, repeating))
            continue
        here = _test(c)
        # RECORDED, NOT RESTATED. The condition already sits in its
        # statement's gate; giving the attached block a gate of its own made
        # the same test appear twice — 7 pistons over-counted, including the
        # smoke/CO and water-leak ones, and a duplicated gate is a duplicated
        # condition on emit. `attached_to` says which test this hangs off
        # without copying it into the tree a second time.
        if c.get("ts"):
            out.append(Block(kind="when-true", attached_to=here,
                             children=_kids(c["ts"], per_device, repeating),
                             branch="ts"))
        if c.get("fs"):
            out.append(Block(kind="when-false", attached_to=here.negate(),
                             children=_kids(c["fs"], per_device, repeating),
                             branch="fs"))
        out += list(_attached_blocks(c.get("c"), per_device, repeating))
    return tuple(out)


def _block(st: dict, per_device: bool = False, repeating: bool = False) -> Block:
    t = st.get("t")
    if t == "action":
        does, interval = _promises_of(st, per_device, repeating)
        return Block(kind="action", stmt_id=st.get("$"),
                     restrictions=_restrictions(st), does=does,
                     interval=interval, cancel_pending=_cancel_pending(st),
                     per_device=per_device, repeating=repeating)
    g = _conditions(st)
    wakes = tuple(x for x in g.leaves() if x.wakes)
    if t == "every":
        # A schedule IS a trigger — it is what starts the piston — but it is
        # carried on the statement's operands, not as a condition, so a walk
        # over `c` finds nothing and a recurring piston reads as something
        # that never runs.
        wakes = wakes + (Test(subject=Subject("virtual", virtual="time"),
                              operator="every", wakes=True,
                              values=(_seconds(st.get("lo")) or st.get("lo"),)),)
    b = Block(kind=t, stmt_id=st.get("$"), gate=g,
              wakes=wakes,
              restrictions=_restrictions(st),
              cancel_pending=_cancel_pending(st),
              per_device=per_device, repeating=repeating)
    # WORK HANGS OFF RESTRICTIONS TOO, not just conditions. A restriction is a
    # condition node, so it carries its own ts/fs — and walking only `c` loses
    # it. Part of the same 42-task hiding place the flat reader was fixed for;
    # the tree reader was written without it.
    kids = list(_attached_blocks(st.get("c"), per_device, repeating))
    kids += list(_attached_blocks(st.get("r"), per_device, repeating))
    if t == "each":
        per_device = True
        b.over = _subject(st.get("lo") or {})
        b.loop_var = st.get("x") or "$device"
    if t in ("every", "repeat", "while", "for"):
        repeating = True
    kids += list(_kids(st.get("s"), per_device, repeating,
                       "then" if t == "if" else ""))
    for i, ei in enumerate(st.get("ei") or []):
        eg = _gate(ei.get("c"), ei.get("o") or "and", bool(ei.get("n")))
        kids.append(Block(kind="else-if", gate=eg, branch=f"ei{i}",
                          wakes=tuple(x for x in eg.leaves() if x.wakes),
                          children=_kids(ei.get("s"), per_device, repeating)))
    if st.get("e"):
        kids.append(Block(kind="else", branch="else",
                          children=_kids(st["e"], per_device, repeating)))
    for case in st.get("cs") or []:
        # A CASE IS A COMPARISON, not an unconditional block. Reading `cs`
        # for its body only made every branch of a switch look like it always
        # runs — a piston that reads as doing everything at once.
        case_gate = _gate(case.get("c"), case.get("o") or "and",
                          bool(case.get("n")))
        if not case_gate.children and st.get("lo") is not None:
            case_gate = Gate(children=(Test(
                subject=_subject(st.get("lo")), operator="is",
                values=tuple(v.get("c") for v in (case.get("lo"),)
                             if isinstance(v, dict) and v.get("c") is not None)),))
        kids.append(Block(kind="case", gate=case_gate, branch="case",
                          children=_kids(case.get("s"), per_device, repeating)))
    b.children = tuple(kids)
    return b


def _subject_refs(sub) -> set:
    """What a test's subject identifies — a device list, or a VIRTUAL device.

    A virtual subject (`$alarmSystemStatus`, `$mode`) has no device references,
    so two statements woken by the SAME alarm-status change had nothing to
    overlap on and read as unrelated: `19_Claude_Alarm_checks` came out as four
    separate intents when it is one piston about the alarm. Sharing a virtual
    device is the same kind of evidence as sharing a real one.

    Measured before adding it: this corrects that one piston and moves no
    other, so it does not collapse everything that happens to run on a clock."""
    out = {str(d) for d in sub.devices}
    if sub.kind == "virtual" and sub.virtual:
        out.add("virtual:" + str(sub.virtual))
    return out


def _touches(b: "Block") -> set:
    """Every device reference a block touches, in EITHER role.

    Statements relate through what they WATCH as much as what they drive:
    "motion active -> light on" and "motion clear -> wait, light off" are one
    intent, and they share the sensor as surely as the light."""
    out = set()
    for kid in b.walk():
        for p in kid.does:
            out |= {str(d) for d in p.devices}
        for g in ([kid.gate] if kid.gate is not None else []) + list(kid.restrictions):
            for leaf in g.leaves():
                out |= _subject_refs(leaf.subject)
        for t in kid.wakes:
            out |= _subject_refs(t.subject)
        if kid.over is not None:
            out |= {str(d) for d in kid.over.devices}
    return out


def _expand_refs(refs: set, piston: dict) -> set:
    """Device references with any group NAME replaced by its members.

    A device-type local variable is one name covering several real devices
    (`Water_Sensor_All` is nine). So a statement naming the group and one
    naming a member hash are the SAME devices, and comparing the bare strings
    would call them unrelated and split one intent in two.

    Uses the reader's own declaration table rather than a second copy
    (HARD_RULES §9). `@global` lists live outside the piston and stay
    unexpanded — a stated limit, not a silent one: the cost is a piston read as
    MORE intents than it has, never a wrong emission."""
    decl = _declared_vars(piston)
    out = set()
    for r in refs:
        members = (decl.get(str(r)) or (None, ()))[1]
        out |= set(members) if members else {str(r)}
    return out


def intents(root: "Block", piston: dict) -> list:
    """The piston's top-level statements grouped into the things it is FOR.

    HARD_RULES §10: the whole piston is ONE intent by DEFAULT and is not
    chopped up because the pieces would compile more easily. §10b: a run-on
    piston genuinely carries several, and that is the COMMON authoring style,
    so more than one has to be findable.

    RECOVERED LOGIC. This test — any overlap across the devices two statements
    touch in either role, after expanding groups — was written on 2026-08-08
    with Jeremy's correction that device use is RELATIVE, not exact. The file
    holding it was deleted without permission the same day; it was rebuilt here
    from its own bytecode on 2026-08-10, against the tree rather than the flat
    atom list it was first written for.

    Order is preserved: groups come back in the order their first statement was
    written, because "in this order" is intent, not syntax (§10)."""
    tops = list(root.children)
    sets = [_expand_refs(_touches(b), piston) for b in tops]
    group_of = list(range(len(tops)))

    def root_of(i):
        while group_of[i] != i:
            i = group_of[i]
        return i

    for i in range(len(tops)):
        for j in range(i + 1, len(tops)):
            if sets[i] & sets[j]:
                group_of[root_of(j)] = root_of(i)
    ordered, seen = [], {}
    for i, b in enumerate(tops):
        r = root_of(i)
        if r not in seen:
            seen[r] = len(ordered)
            ordered.append([])
        ordered[seen[r]].append(b)
    return ordered


def coverage(root: "Block", piston: dict) -> dict:
    """Is every top-level statement in exactly one intent, in order?

    THE GATE. A statement in NO intent would be silently unread — the failure
    this project keeps being bitten by — and one in TWO would be emitted twice.
    Both are hard failures, never warnings (HARD_RULES §6)."""
    tops = list(root.children)
    groups = intents(root, piston)
    placed = [b for g in groups for b in g]
    ids = [id(b) for b in placed]
    return {
        "statements": len(tops),
        "intents": len(groups),
        "missing": len([b for b in tops if id(b) not in set(ids)]),
        "twice": len(ids) - len(set(ids)),
        "reordered": sum(1 for g in groups
                         for a, b in zip(g, g[1:])
                         if tops.index(a) > tops.index(b)),
    }


def read(piston: dict) -> list[Promise]:
    """Every promise the piston makes, in the order it makes them."""
    return _Reader(piston).read()


@dataclass
class Ends:
    """WHAT STATE A DEVICE ENDS UP IN — said without webCoRE's words.

    THE WHOLE LAYER TURNS ON THIS (Jeremy, 2026-08-08: *"webcore has absolutely
    NOTHING to do with how ha yaml does things"*). A record holding
    `command="on"` is a webCoRE record wearing a new name, and everything
    reading it can only produce a translation — which is why every attempt so
    far came out a transcoder however the front end was rearranged.

    So the boundary is here: *this device's `switch` ends up `on`*. An attribute
    and the value it lands on. webCoRE can say it, Home Assistant can say it,
    neither one owns it, and nothing downstream needs to know a piston existed.

    IT IS NOT INVENTED — THE VOCAB ALREADY STATES IT. Every command carries `a`
    (the attribute it changes) and `v` (the value it lands on): `on` -> switch/
    on, `lock` -> lock/locked, `open` -> door/open. Reading it from there keeps
    it right for everyone's pistons and lets a user repair it (HARD_RULES §8,
    §9) instead of it being a table in Python.

    HONEST WHEN IT CANNOT SAY IT. `toggle` lands on no particular state — it
    depends where it started — and a parameterised command like `setLevel`
    names its attribute but takes its value from the parameter. Those are
    recorded as such rather than guessed, because a made-up end state is the
    silent-wrongness this project keeps paying for (HARD_RULES §6)."""

    devices: tuple
    attribute: str | None = None   # what changes
    value: object = None           # what it becomes
    relative: bool = False         # depends on the prior state (toggle, adjust)
    command: str = ""              # kept ONLY so an unmappable one stays honest

    def describe(self) -> str:
        who = ", ".join(self.devices) if self.devices else "(no device)"
        if self.attribute and self.value is not None:
            return f"{who}'s {self.attribute} ends up {self.value}"
        if self.attribute:
            return f"{who}'s {self.attribute} changes"
        if self.relative:
            return f"{who} flips from whatever it was ({self.command})"
        return f"{who}: {self.command} (no end state stated in the vocabulary)"


def _ends_up(command: str, values: tuple, devices: tuple) -> Ends:
    """A command as the state it leaves the device in, read from the vocab."""
    from .resolve import _load_vocab
    c = (_load_vocab().get("commands") or {}).get(command) or {}
    attr, val = c.get("a"), c.get("v")
    if attr and val is not None:
        return Ends(devices, attr, val, False, command)
    if attr:
        # names the attribute, takes the value from its first parameter
        first = values[0] if values else None
        return Ends(devices, attr, first, False, command)
    if command in ("toggle",) or str(c.get("n", "")).lower().startswith("adjust"):
        return Ends(devices, None, None, True, command)
    return Ends(devices, None, None, False, command)


@dataclass
class Held:
    """ONE INTENT: a device is put one way while something holds, and put back
    once that thing has been released for a delay.

    THIS IS THE POINT OF THE WHOLE LAYER, so read why it is shaped like this.
    webCoRE has no way to say "for five minutes", so a user states it as two
    separate jobs: act on the rising edge, and act on the falling edge with a
    wait in front. Translated one-for-one that becomes a delay plus timer and
    cancel machinery, because the pending job has to be killed if the thing
    comes back. Read as ONE thing the user wanted, Home Assistant states it in
    the trigger itself — released FOR that long — and the machinery does not
    get translated, it stops existing. That is the difference between a
    transcoder and this (HARD_RULES §2), and it is measurable: the emitted
    automation has fewer moving parts, not differently-spelled ones.

    NOTHING IS CLASSIFIED. There is no taxonomy here and no label — the deleted
    layer's mistake was producing a name (HARD_RULES §2a). This keys purely on
    a RELATIONSHIP between two promises and its output is a different
    automation. A heater, a lock relocking itself and a fan all match it
    identically; no device type, no attribute name and no piston title is read
    (HARD_RULES §5, §12).

    NO TABLE OF OPPOSITES. It does not need to know that `off` undoes `on`.
    The two promises are recognised by their WAKING EDGES — the same subject
    compared the same way against different values — so whatever the first sets
    is what holds, and whatever the second sets is what it returns to. Nothing
    HA-shaped and nothing hand-listed, so it cannot rot when HA renames
    something (HARD_RULES §8)."""

    target: tuple                  # the devices both promises act on
    engage: "Promise"              # what happens while it holds
    release: "Promise"             # what it returns to
    subject: Subject               # the thing being watched
    operator: str | None           # how it is compared, on both edges
    engage_values: tuple           # value on the edge that engages
    release_values: tuple          # value on the edge that releases
    release_after: int             # seconds it must stay released

    def describe(self) -> str:
        who = ", ".join(self.target) if self.target else "(no device)"
        gate = ("; ".join(g.describe() for g in self.engage.gated_by
                          if g.describe()))
        only = f", only while {gate}" if gate else ""
        return (f"{who}: {self.engage.command} while "
                f"{self.subject.describe()} {self.operator} "
                f"{'/'.join(str(v) for v in self.engage_values)}{only}; "
                f"back to {self.release.command} once it has been "
                f"{'/'.join(str(v) for v in self.release_values)} for "
                f"{self.release_after}s")


def _is_a_release(q: "Promise", promises: list) -> bool:
    """Is this promise a RELEASE — the thing that ends a held state — or just
    a step that happens to sit behind a pause?

    ARRANGEMENT ANSWERS THIS, not a word list (Jeremy, 2026-08-08: intent is
    read from how the piston is put together; the vocab "helps to a point" and
    is never what decides). A release stands alone: its branch does one thing
    after the wait, and that is the whole point of the branch. Pacing looks
    different — several actions strung together with short pauses between them,
    where a delay is punctuation rather than purpose.

    THIS IS THE REAL DIFFERENCE between your hall light and Paul's LED, and it
    is visible without knowing what a motion sensor or a button is: the hall
    piston's delayed branch contains ONLY the turn-off, while the LED's delayed
    actions are the third and fifth of five. That distinction survives a raw HA
    command with no vocabulary entry at all, which a lookup-based test cannot."""
    kin = [x for x in promises if x.source == q.source]
    delayed = [x for x in kin if x.after]
    return len(delayed) == 1 and delayed[0] is q and kin[-1] is q


def _edge(p: "Promise"):
    """The single waking edge of a promise: (subject key, operator, values).

    None when it has no single edge — several triggers, or none. Both cases
    are honest non-matches rather than a guess at which one meant it."""
    if len(p.wakes_on) != 1:
        return None
    t = p.wakes_on[0]
    s = t.subject
    if s.kind != "device" or not s.devices or not s.attribute:
        return None
    return ((tuple(s.devices), s.attribute), t.operator, t.values, s)


def behaviours(promises: list) -> list:
    """The promises, with held-state pairs collapsed into one intent each.

    Order is preserved and every promise appears exactly once — a promise in
    no behaviour would be silently unread, and one in two would be emitted
    twice (HARD_RULES §6). Anything that does not pair stays exactly as it
    was, so this can only ever collapse, never drop."""
    used, out = set(), []
    for i, p in enumerate(promises):
        if i in used:
            continue
        pe = _edge(p)
        pair = None
        if pe and not p.after:
            for j in range(i + 1, len(promises)):
                if j in used:
                    continue
                q = promises[j]
                qe = _edge(q)
                if not qe or not q.after:
                    continue
                # SAME devices acted on, SAME thing watched, SAME comparison,
                # DIFFERENT values — that is one subject's two edges.
                if (set(p.devices) == set(q.devices) and p.devices
                        and pe[0] == qe[0] and pe[1] == qe[1]
                        and pe[2] != qe[2]
                        # ...and the delayed one is a RELEASE, not a step that
                        # happens to sit behind a pause. Arrangement decides
                        # this; nothing is looked up (Jeremy, 2026-08-08).
                        and _is_a_release(q, promises)):
                    pair = (j, q, qe)
                    break
        if pair:
            j, q, qe = pair
            used.add(i)
            used.add(j)
            out.append(Held(target=tuple(p.devices), engage=p, release=q,
                            subject=pe[3], operator=pe[1],
                            engage_values=pe[2], release_values=qe[2],
                            release_after=q.after))
        else:
            used.add(i)
            out.append(p)
    return out


def apply_intent(branches: list, piston: dict, resolver=None,
                 piston_id: str = "piston") -> list:
    """Rewrite the analyzer's branches to say what the piston MEANT.

    THIS IS WHERE INTENT CHANGES THE AUTOMATION. Without it the reading is a
    description and the tell is that emitted output never changes (Jeremy,
    2026-08-08: *"the tell was no change in output"*).

    WHAT IT REWRITES. A held state is authored as two statements — act on one
    edge, and on the opposite edge wait then act — because webCoRE cannot say
    "for five minutes". Transliterated that becomes a delay plus timer and
    cancel machinery so the pending job can be killed if the thing comes back.
    Read as ONE intent, Home Assistant states it in the trigger: released FOR
    that long. Nothing is pending, so nothing needs cancelling.

    ON A DEVICE GROUP IT MUST USE A GROUP ENTITY. HA tracks a state trigger's
    `for:` PER ENTITY, so a trigger listing several sensors fires when ANY ONE
    has been clear for the window. Device-proven 2026-08-08: with one sensor
    quiet and another still detecting, the light went out — on `12_Cave_motion_V2`
    that is the lights dying while Jeremy stands at the far sensor. A group
    entity has ONE combined state, so `for:` on it means what the piston said;
    proven both directions on the bench. Groups are named per piston per
    variable (Jeremy: *"we have to make uniq ones"*) so rooms never merge.

    IT SPEAKS webCoRE, NOT HA. The rewrite sets the comparison to `stays` with
    a duration — a form webCoRE already has and this compiler already emits
    correctly through its tested path — so no new emission code exists and
    every downstream piece keeps its hard-won HA knowledge (§8, §9).

    EDGE vs STATE IS INTENT (§2e) and this converts one to the other, which is
    why it is narrow: it fires only where `behaviours()` recognised a held
    state — same devices acted on, two edges of one subject, and the delayed
    branch containing ONLY the release."""
    held = [b for b in behaviours(read(piston)) if isinstance(b, Held)]
    if not held:
        return branches
    windows = {}
    for h in held:
        for t in h.release.wakes_on:
            sub = t.subject
            if sub.kind == "device" and sub.attribute:
                windows[(tuple(sub.devices), sub.attribute, t.operator,
                         t.values)] = h.release_after
    if not windows:
        return branches
    waits = set(routing.wait_commands())
    for br in branches:
        trigs = br.get("triggers") or []
        if len(trigs) != 1:
            continue
        tr = trigs[0]
        key = (tuple(tr.get("devices") or ()), tr.get("attr"), tr.get("co"),
               (tr.get("value"),))
        secs = windows.get(key)
        if not secs:
            continue
        body = br.get("then") or []
        lead = next((i for i, n in enumerate(body)
                     if isinstance(n, dict) and n.get("kind") == "task"), None)
        # TWO BRANCH SHAPES REACH HERE, and both mean the same thing.
        #   - The analyzer's: the wait is still a task in the body, and the
        #     rewrite lifts it into the trigger and deletes it.
        #   - The intent path's: `read()` already absorbed the wait into the
        #     promise's `after`, so there is no wait task to find — the hold
        #     is `release_after`, which is what `windows` already holds.
        # Matching only the first shape is why the intent path emitted Cave
        # with no `for:` at all and the lights went out the moment ONE sensor
        # cleared. A held state is a held state whoever read it.
        waiting = lead is not None and body[lead].get("command") in waits
        if lead is None:
            continue
        if resolver is not None and not _group_for(tr, resolver, piston_id):
            # more than one entity and no group could be made -> leave the
            # piston exactly as it was rather than emit the per-entity form,
            # which is device-proven wrong (§6: an honest refusal beats a
            # confident wrong answer).
            continue
        tr["co"] = "stays"
        if waiting:
            tr["duration"] = (body[lead].get("params") or [{}])[0]
            br["then"] = body[:lead] + body[lead + 1:]
        else:
            # `windows` is in seconds; a duration operand is {c, vt} (see
            # resolve.duration_seconds). The body is already only the release.
            tr["duration"] = {"c": int(secs), "vt": "s"}
    return branches


def _group_for(tr: dict, resolver, piston_id: str = "piston") -> bool:
    """Give this trigger a GROUP entity when it watches more than one device.

    Returns False only when a group is needed and cannot be built, so the
    caller can decline the rewrite instead of emitting the per-entity form."""
    from .helpers import group_sensor
    ctx = {"piston_id": piston_id}
    try:
        entities = resolver.entities_for_attr(tr.get("devices") or [],
                                              tr.get("attr"), ctx)
    except Exception:
        return False
    if len(entities) <= 1:
        return True                      # single entity: `for:` is already right
    name = "_".join(str(d) for d in (tr.get("devices") or [])) or tr.get("attr")
    dc = _device_class(tr.get("attr"))
    if not dc:
        return False                     # not a binary attribute -> no group
    g = group_sensor(str(piston_id), name, entities, dc)
    groups = getattr(resolver, "device_groups", None)
    if groups is None:
        groups = resolver.device_groups = {}
    groups[g["entity"]] = g
    tr["_group_entity"] = g["entity"]
    return True


def _device_class(attribute: str) -> str | None:
    """The HA device_class a group of these should report as, from the vocab's
    own read rules — never a hand-written list (HARD_RULES §8)."""
    from .resolve import _load_vocab
    for rule in (((_load_vocab().get("attributes") or {})
                  .get(attribute) or {}).get("ha") or []):
        if isinstance(rule, dict) and rule.get("domain") == "binary_sensor":
            classes = rule.get("device_class") or []
            if classes:
                return classes[0]
    return None


def unsupported(promises: list) -> list[str]:
    """Slots this spec CARRIES that emission does not use yet.

    Reported, never silent. A carried-but-unemitted slot is a known gap; an
    uncarried one is a silent drop, and the difference is the whole reason
    these fields exist on the record."""
    seen = set()
    for p in promises:
        for t in tuple(p.wakes_on) + tuple(p.gated_by):
            for slot, why in NOT_YET_EMITTED.items():
                if getattr(t, slot, None):
                    seen.add(f"{slot}: {why}")
    return sorted(seen)

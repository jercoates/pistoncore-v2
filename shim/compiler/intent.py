"""INTENT — what the user wanted to happen (COMPILER_SPEC §3.0).

THE MIDDLE LAYER. Until now the compiler had two layers: webCoRE's words and
HA's words, with a translation between them. That is why the output reads like
the input wearing a costume, and why every webCoRE word HA lacks became a
reason to give up and route to PyScript.

This module is neither side's words. It answers ONE question about a piston:
**what did the user want to happen?** The statements are EVIDENCE of that; they
are not the thing to convert (HARD_RULES §2).

WHY THIS IS PYTHON AND NOT DATA (Jeremy, 2026-08-07). Two different things get
confused as one:

  - *What a webCoRE word MEANS* — `setLevel` expresses "this light ends up at
    40%". That is a fact about webCoRE and about human intent. It does not move
    when Home Assistant renames a service. -> Python, here.
  - *How Home Assistant ACHIEVES it* — which service, which field, which
    template function. That moves constantly. -> the vocab's `ha` rules and the
    emission templates, where it already lives. NOT here, and never copied here
    (HARD_RULES §8 + §9).

SCOPE IS THE VOCABULARY, NEVER THE CORPUS (HARD_RULES §5). The bounded list of
everything webCoRE can express is `webcore_vocab.json`. `coverage()` below
checks this module against it, and `test_intent_probe.py --section intent`
fails when anything in the vocab has no outcome. That gate is the whole reason
this can claim "all possible things" instead of "the 84 pistons I looked at" —
a hand-written partial copy of a vocabulary table is precisely the failure that
has already cost this project its worst bugs.
"""

import json

from . import routing

# ── the outcome vocabulary ──────────────────────────────────────────────────
#
# Deliberately SMALL. These are kinds of thing a person wants to happen in
# their home, not kinds of statement webCoRE has. Adding one should feel hard;
# if a new command seems to need a new outcome, first check it isn't one of
# these wearing a different word.

OUTCOMES = {
    "be": "a thing ends up in a particular state (light on, door locked, "
          "thermostat at 21)",
    "adjust": "a thing changes RELATIVE to how it is now (dim by 10%, volume "
              "up, toggle) — needs reading before writing",
    "transition": "a thing gets somewhere OVER TIME or repeatedly (fade, "
                  "flash, colour loop) — a shape, not a value",
    "tell": "a person is informed (notification, SMS, email, speech)",
    "remember": "a value is kept for later (variables, saved state)",
    "later": "something happens after a delay or at a time",
    "cancel_later": "something that was going to happen must NOT happen",
    "piston_self": "the automation acts on ITSELF (pause, resume, exit, log, "
                   "tiles) rather than on the home",
    "offbox": "something outside Home Assistant is made to happen (web "
              "request, webhook, wake-on-LAN, take a picture)",
    "nothing": "explicitly does nothing observable (noop, poll, refresh)",
}


# ── which outcome each webCoRE command expresses ────────────────────────────
#
# Only commands whose outcome is NOT derivable by rule are listed. Everything
# else falls through to `_derive`, so this table stays small and the rules do
# the work. Anything neither names nor derives is a GATE FAILURE, never a
# silent default — see coverage().

_EXPLICIT = {
    # relative — must read current state first
    "toggle": "adjust", "toggleLevel": "adjust", "toggleRandom": "adjust",
    "volumeUp": "adjust", "volumeDown": "adjust",
    "setDirection": "adjust",
    # "next"/"previous" are relative for the same reason volumeUp is: there is
    # no destination, only a step from wherever you are. Caught by the residual
    # review queue, which had them falling through to "be".
    "nextTrack": "adjust", "previousTrack": "adjust",
    "lifxToggle": "adjust",

    # a shape over time, not a destination
    "flash": "transition", "flashColor": "transition",
    "flashLevel": "transition", "startLoop": "transition",
    "stopLoop": "transition", "setLoopTime": "transition",
    "lifxBreathe": "transition", "lifxPulse": "transition",
    "alert": "transition", "strobe": "transition", "both": "transition",
    "beep": "transition",

    # informing a person
    "speak": "tell", "playText": "tell", "playTextAndRestore": "tell",
    "playTextAndResume": "tell", "sendEmail": "tell",
    "sendNotification": "tell", "sendPushNotification": "tell",
    "sendSMSNotification": "tell", "sendNotificationToContacts": "tell",
    "deviceNotification": "tell",
    # The "...AndRestore"/"...AndResume" pair are the ANNOUNCEMENT shape:
    # interrupt whatever is playing, say the thing, put it back. The intent is
    # informing a person, not choosing music — which is why plain `playTrack`
    # below stays "be" while these two do not.
    "playTrackAndRestore": "tell", "playTrackAndResume": "tell",

    # keeping a value
    "setVariable": "remember", "setState": "remember",
    "saveStateLocally": "remember", "saveStateGlobally": "remember",
    "loadStateLocally": "remember", "loadStateGlobally": "remember",
    "writeToFuelStream": "remember", "parseJson": "remember",
    "setConsumableStatus": "remember",

    # time
    "wait": "later", "waitRandom": "later", "waitForTime": "later",
    "waitForDateTime": "later",
    "cancelTasks": "cancel_later",

    # reaching outside Home Assistant
    "httpRequest": "offbox", "iftttMaker": "offbox", "wolRequest": "offbox",
    "storeMedia": "offbox", "take": "offbox", "clearImages": "offbox",
    "executeRoutine": "offbox", "startActivity": "offbox",
    "getAllActivities": "offbox", "getCurrentActivity": "offbox",

    # explicitly nothing observable
    "noop": "nothing", "poll": "nothing", "refresh": "nothing",
    "configure": "nothing", "reset": "nothing",
    "indicatorNever": "nothing", "indicatorWhenOn": "nothing",
    "indicatorWhenOff": "nothing",

    # the piston's own tile. Its five siblings live in the routing table's
    # piston_scope_commands and are picked up by rule; setTileFooter was
    # MISSING from that list (found by this module's gate, 2026-08-07, and
    # added there). Named here too so the intent reading never depends on
    # that list being complete.
    "setTileFooter": "piston_self",
}

# Prefixes that reliably mean "change relative to current". Checked before the
# plain set-a-value rule, since `adjustLevel` and `setLevel` differ only here.
_ADJUST_PREFIXES = ("adjust",)
_TRANSITION_PREFIXES = ("fade",)


def _vocab() -> dict:
    from .. import customize
    with open(customize.path("webcore_vocab.json"), encoding="utf-8") as f:
        return json.load(f)


def _derive(command: str) -> str | None:
    """The outcome of a command that the table doesn't name, or None.

    Rules only, in the order that matters — `adjust*`/`fade*` are checked
    before anything else because they are `set*` with a shape attached."""
    if command.startswith(_ADJUST_PREFIXES):
        return "adjust"
    if command.startswith(_TRANSITION_PREFIXES):
        return "transition"
    # Commands that act on the PISTON rather than the home already have a
    # canonical list — the routing table's piston_scope_commands. USE it; do
    # not restate it here (HARD_RULES §9). It exists because those commands
    # are the ones YAML cannot express, which is the same set.
    if command in routing.piston_scope_commands():
        return "piston_self"
    return None


def outcome_of(command: str) -> str | None:
    """What OUTCOME this webCoRE command expresses, or None if unknown.

    None is never a default to compile against — callers must treat it as a
    gap to close, because compiling something whose purpose is unknown is how
    a piston silently does less than it says (HARD_RULES §6)."""
    if not command:
        return None
    named = _EXPLICIT.get(command)
    if named:
        return named
    derived = _derive(command)
    if derived:
        return derived
    # Everything left is a plain "make this thing be that way" — the large
    # majority (on, off, lock, open, setLevel, cool, setVolume, ...).
    #
    # WHAT THIS DELIBERATELY DOES NOT CONSULT: whether Home Assistant can DO
    # it. An earlier draft of this function decided "be" only for commands the
    # vocab already had an `ha` rule for, which silently left `setInfraredLevel`
    # and `setSchedule` (both `"ha": "n/a"`) with NO intent at all. That is the
    # exact confusion this module exists to prevent: "HA has no service for it"
    # is a ROUTING fact, and it says nothing about what the user wanted
    # (HARD_RULES §2 — a failed transliteration says nothing about whether the
    # outcome is reachable). The user who picked `setInfraredLevel` wanted the
    # infrared level to end up at a value, and that is true whether or not HA
    # can currently oblige.
    # AND IT DOES NOT CONSULT THE VOCABULARY EITHER (Jeremy, 2026-08-10:
    # "we feed raw ha for things not in vocab, quit locking shit down ...
    # they literally tell you what they do").
    #
    # This used to read `if command in _known_commands(): return "be"`, which
    # is the same confusion as the paragraph above, one step over: being
    # ABSENT FROM A TABLE was treated as not knowing what the user wanted. It
    # never was. A command reaches a piston either because webCoRE offered it
    # or because the hybrid feed handed the editor a real Home Assistant
    # service name — and in both cases the author picked it to make a device
    # end up some way. `allOn`, `allOff`, `playSound` and `searchAmazonMusic`
    # were reported as having no intent at all on that basis, while saying in
    # plain words what they do.
    #
    # The rules above still get first refusal, so a raw `fadeUpLights` is a
    # transition rather than a state. This is the floor, not a guess: "the
    # author wanted this thing to end up that way" is the weakest claim that
    # is still true of every command anyone can pick.
    return "be"


_known_cache: set | None = None


def _known_commands() -> set:
    """Every command name the vocabulary defines — nothing about capability.

    The vocab's `commands`/`virtualCommands` sections ARE webCoRE's device
    commands, so membership is what makes "be" a rule rather than a guess: a
    name this does not contain is genuinely unknown and must fail the gate."""
    global _known_cache
    if _known_cache is None:
        vocab = _vocab()
        _known_cache = set(vocab.get("commands") or {}) | set(
            vocab.get("virtualCommands") or {})
    return _known_cache


def coverage() -> dict:
    """Check this module against the WHOLE vocabulary.

    `unclassified` is a hard gate failure — a command whose purpose nothing
    here can state.

    `residual` is the softer, more useful signal: commands that reached the
    "be" fallback rather than being named or derived. Because "be" catches
    anything known, a new vocabulary entry can never land in `unclassified`;
    it lands here instead. So this list is the review queue — if a command
    shows up in it that is NOT simply "make the device be this way", it needs
    a row in `_EXPLICIT`. Without this, the fallback would quietly absorb
    every future addition and the gate would be decorative."""
    vocab = _vocab()
    cmds = sorted(set(vocab.get("commands") or {})
                  | set(vocab.get("virtualCommands") or {}))
    by_outcome: dict = {}
    unclassified, residual = [], []
    for name in cmds:
        kind = outcome_of(name)
        if kind is None:
            unclassified.append(name)
            continue
        if kind not in OUTCOMES:
            # A typo in _EXPLICIT would otherwise invent a silent new outcome
            # kind that nothing downstream knows how to emit.
            raise AssertionError(
                f"command '{name}' claims outcome '{kind}', which is not in "
                f"OUTCOMES — every outcome must be one of: "
                f"{', '.join(sorted(OUTCOMES))}")
        if name not in _EXPLICIT and _derive(name) is None:
            residual.append(name)
        by_outcome.setdefault(kind, []).append(name)
    return {
        "total": len(cmds),
        "classified": len(cmds) - len(unclassified),
        "unclassified": unclassified,
        "residual": residual,
        "by_outcome": by_outcome,
    }

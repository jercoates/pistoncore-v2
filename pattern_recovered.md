MODULE DOCSTRING
======================================================================
PATTERN — what a piston is FOR (COMPILER_SPEC §3.0, the middle layer).

`intent.py` answers what each WORD wants. This answers what the PISTON wants,
which is not the sum of its words (HARD_RULES §10a): "motion light with a
timeout" is one thing a person wanted, not `on` + `wait` + `off`.

WHAT AN INTENT IS HERE. A SHAPE, never a label (2026-08-08 handoff). PistonCore
does not need to know a piston is "a motion light"; it needs to know what to
EMIT. The emittable thing is a shape over the atoms — *this device is set one
way on an event, and set back after a delay unless it happens again* — which is
computable from the statements, their order, the outcomes of their commands and
the devices they touch. The human-readable sentence each shape carries is for
the banner and the YAML comment (HARD_RULES §11) and is never load-bearing: no
routing, no emission and no gate reads it.

NO AI IN THE COMPILE PATH. A model may label a piston at authoring or import
time; never here. The compiler has to work with nobody upstream, and Jeremy has
already run that experiment — AIs converting his pistons gave "shaky results, a
lot of back and forth", because the task has no feedback loop. A compiler can be
gated; a conversation cannot.

THE BOUNDARY (draw it once, hold it). This module decides WHAT the automation
should be. It NEVER decides how a piece is written in Home Assistant, and it
never builds YAML. What it hands back is the analyzer's own IR nodes — triggers,
conditions, action trees — which `emit_yaml` already consumes. So `resolve.py`,
`expression.py` and the templates keep every bit of hard-won HA knowledge and
this layer cannot drag transcoder assumptions into them. The freedom it has is
which statements belong together, what wakes them, and in what order.

WHY PYTHON AND NOT DATA (HARD_RULES §8). Recognising purpose does not move when
Home Assistant renames a service. Service names and template syntax churn
constantly and stay in the vocab and the templates. This file names no HA
service, no entity and no template function — check that before adding to it.

═══════════════════════════════════════════════════════════════════════════════
THE STATEMENTS ALREADY ARE THE INTENT — READ THIS BEFORE CHANGING ANYTHING HERE
═══════════════════════════════════════════════════════════════════════════════
**Jeremy, 2026-08-08: *"webCoRE statements as built show you the intent — they
are just set up in patterns."*** This is the governing insight and this module
does NOT yet honour it.

webCoRE's editor does not let anyone write arbitrary code. It builds statements
from a BOUNDED SET OF FORMS, and each form already states a purpose:

    if <trigger> then <tasks>          = "when this happens, do that"
    condition with ts / fs             = "when true do this, when false do that"
    with <devices> do <tasks>          = "make these devices do this"
    restriction on a statement         = "only when ..."
    every <interval>                   = "repeatedly"
    each <device list>                 = "to every one of these"

So the intent is not something to be INFERRED from the piston — it is already
carried by the shape the editor saved. The right job for this layer is to READ
those forms faithfully and decide the HA emission from them.

What is built below does something weaker: it flattens each statement into a
sequence of outcome atoms and pattern-matches that sequence. That throws away
the very structure the intent was stated in, and then tries to guess it back.
It works for the shapes it names (the gate proves every statement is accounted
for, in order), but it is the wrong foundation to keep extending — every gap
listed in COMPILER_TODO under "Open on the intent layer" is a piece of
structure this flattening discarded: ts/fs, restrictions, and/or nesting, loops.

REBUILD DIRECTION: enumerate webCoRE's statement FORMS (they are bounded, and
PISTON_JSON_REFERENCE §2.2 already lists them) and read the intent off each
form directly, instead of deriving it from what its commands happen to be.

AND THE FORMS DO NOT HAVE TO BE INVENTED — THE PICKER ALREADY DEFINES THEM
(Jeremy, 2026-08-08: *"the way the picker and falls are built shows you a
pattern"*). The editor's cascade is the pattern: a device leads to its
capabilities, a capability to its attributes and commands, an attribute's TYPE
to the comparison operators legal on it, and a command to its declared
parameters. A user cannot author outside that cascade, so every statement in
every piston is one of its products.

That cascade is already in this repo — `webcore_vocab.json` (capabilities,
commands with their `p` parameter lists, `comparisons` bucketed by operator
group, `attributeTypeToOperatorGroup`) and the sealed editor module itself,
which is ground truth for the API contract. So the bounded form set is
DERIVABLE, not guesswork, and deriving it from the vocab keeps it correct for
everyone's pistons rather than fitted to one corpus (HARD_RULES §5, §12).

HOW TO USE THE PATTERNS — the actual open question (Jeremy, 2026-08-08: *"i
know they are patterns but how to use them is the question"* and *"words are a
PART not the whole"*). The answer this session arrived at, unbuilt:

  0. NOTHING HERE IS THE WHOLE ON ITS OWN. Jeremy said it of the words —
     *"words are a PART not the whole"* — and then immediately of the forms
     too: *"the pattern is a part not the whole."* Both corrections matter, and
     the second lands on the obvious next mistake: having learned that words
     are insufficient, the tempting move is to crown the FORM instead. That is
     the same error one level up. The intent is the COMBINATION — form, words,
     devices, order, gates, relationships — and any design that elevates one of
     them to primary will be wrong in the same way this module is wrong today.
  1. THE FORM CONTRIBUTES THE FRAME. Each statement form carries a purpose with
     empty slots: "when <this> happens, do <that> to <those>, only when
     <gate>". The frame is one input, not the answer.
  2. THE WORDS FILL THE SLOTS. Commands and comparisons say WHAT goes in each
     slot — the atoms in `intent.py` are exactly this, and no more. Reading
     them as the whole is what this module currently does wrong.
  3. RELATIONSHIPS JOIN FRAMES INTO ONE INTENT. Shared devices (built, and it
     works), shared variables (not built — the value written by one statement
     and read by another), and order. This is what makes several statements one
     thing the user wanted, per HARD_RULES §10.
  4. EMISSION IS CHOSEN PER FRAME, not per word. That is the payoff: the frame
     says what the automation IS, so the HA idiom is picked once for the whole
     shape instead of translated command by command — which is the difference
     between an intent compiler and a transcoder (HARD_RULES §2).

Only (2) and part of (3) exist below. (1) and (4) are the build.

A WORD DOES NOT ON ITS OWN SHOW INTENT (Jeremy, 2026-08-08) — the same point
from the other end. Read this before extending the catalog.

`_outcomes()` turns each command into an atom and the shape tests then match
the SEQUENCE of atoms. That is still reading words, just in a coarser alphabet.
`setVariable` becomes `remember` whether the piston is composing a spoken
sentence out of the sensors that tripped or tracking a manual-override flag —
identical atom sequences, completely different purposes. So a shape like "build
a sentence for an announcement" CANNOT be added to the catalog below: the words
do not distinguish it, and adding it would produce a label that cannot be
reliably detected, which is precisely the decorative labelling this module's
first paragraph forbids.

What actually distinguishes them is DATA FLOW and RELATIONSHIP — which
statement writes a value that another one READS, which device one statement
sets and another restores, what wakes what. Grouping already uses one such
relationship (shared devices, §10) and that is why it works. The value flow is
not modelled at all yet, and until it is, any shape that depends on what a
value is FOR is out of reach. Extending the catalog will not fix that; adding
the relationship layer will.

SCOPE IS THE VOCABULARY, NEVER THE CORPUS (HARD_RULES §5). Shapes are built from
the bounded outcome set in `intent.OUTCOMES`, so a piston nobody has ever
written is still classified. `coverage()` proves every branch of a piston lands
in exactly one intent — that gate is what makes "nothing was overlooked" a fact
rather than a hope.



----------------------------------------------------------------------
Intent
----------------------------------------------------------------------
Intent


----------------------------------------------------------------------
sentence
----------------------------------------------------------------------
What the compiler will say it thinks this piston is for.


----------------------------------------------------------------------
<genexpr>
----------------------------------------------------------------------
$


----------------------------------------------------------------------
_walk_tasks
----------------------------------------------------------------------
Every task node under an action tree, in document order.

Order matters and is part of the intent (HARD_RULES §10: "in this order"
is intent, not syntax), so this never sorts or de-duplicates.


----------------------------------------------------------------------
_outcomes
----------------------------------------------------------------------
The atom outcomes this branch expresses, in order.

Reads `intent.outcome_of` rather than re-deciding what a command means —
that table is gated as complete against the whole vocabulary, and a second
opinion here is exactly the duplicate-source failure HARD_RULES §9 names.


----------------------------------------------------------------------
_devices
----------------------------------------------------------------------
Every device reference this branch acts ON (not the ones it reads).

The acting set is what decides whether two statements are the same intent:
a piston that turns a light on and later off is one thing about that light,
while a light statement and a lock statement are two.


----------------------------------------------------------------------
_holds_work
----------------------------------------------------------------------
then


----------------------------------------------------------------------
<genexpr>
----------------------------------------------------------------------
command


----------------------------------------------------------------------
_is_timed_revert
----------------------------------------------------------------------
Set something, hold, then set something — the motion-light family.

THE SHAPE SPANS STATEMENTS, and that is the whole reason this test runs on
a MERGED intent rather than one branch (HARD_RULES §10: the piston as a
whole is the intent). A real motion light is written as two statements —
"motion active: light on" and "motion clear: wait, light off" — so a
per-statement reading sees `be` in one and `later, be` in the other and can
never see the shape. Classifying each branch first was exactly that
mistake, and it read Jeremy's hall motion light as a plain `respond`.

Keyed on outcomes and order only. No device type, no attribute, no name —
so a heater on a timer, a fan, or a lock relocking itself all match the
same way. This must not become a motion-light detector: it is written for
everyone's pistons, not one corpus (HARD_RULES §5, §12).


----------------------------------------------------------------------
<genexpr>
----------------------------------------------------------------------
be


----------------------------------------------------------------------
<genexpr>
----------------------------------------------------------------------
be


----------------------------------------------------------------------
_is_announce
----------------------------------------------------------------------
tell


----------------------------------------------------------------------
<genexpr>
----------------------------------------------------------------------
tell


----------------------------------------------------------------------
_is_reach_out
----------------------------------------------------------------------
offbox


----------------------------------------------------------------------
<genexpr>
----------------------------------------------------------------------
offbox


----------------------------------------------------------------------
<genexpr>
----------------------------------------------------------------------
be


----------------------------------------------------------------------
<genexpr>
----------------------------------------------------------------------
remember


----------------------------------------------------------------------
_shape_of
----------------------------------------------------------------------
sequence


----------------------------------------------------------------------
_read_devices
----------------------------------------------------------------------
Devices this branch READS — its triggers and conditions.

Statements relate through what they watch as much as through what they
drive: "motion active -> light on" and "motion clear -> wait, light off"
are one intent, and they share the SENSOR as surely as the light.


----------------------------------------------------------------------
take
----------------------------------------------------------------------
devices


----------------------------------------------------------------------
device_aliases
----------------------------------------------------------------------
Local device-VARIABLE name -> the hashed ids it stands for.

Devices arrive in GROUPS (Jeremy, 2026-08-08), and a device-type local
variable is exactly that: one name covering several real devices, its
member hashes stored on the variable itself (`piston.v[].v.d`,
PISTON_JSON_REFERENCE §1). So "Gas_Detectors" in one statement and a single
detector's hash in another are the SAME devices, and comparing the bare
references would call them unrelated and split one intent into two.

Read straight from the piston, which is why this belongs here: no
resolution map, no Home Assistant, nothing that depends on what is
currently plugged in. `@global` device lists live outside the piston
(globals store, COMPILER_DECISIONS_HOLDING §H1) and stay unexpanded — a
stated limit, not a silent one.


----------------------------------------------------------------------
_expand
----------------------------------------------------------------------
Device references with any group names replaced by their members.


----------------------------------------------------------------------
_related
----------------------------------------------------------------------
Do these two statements belong to ONE thing the user wanted?

HARD_RULES §10: the whole piston is ONE intent by DEFAULT, and it is not
chopped up because the pieces would be easier to compile. §10b: but a
run-on piston genuinely carries several, and that is the COMMON authoring
style — so more than one must be findable.

DEVICE USE IS RELATIVE, NOT EXACT (Jeremy, 2026-08-08). An earlier version
intersected the exact sets of devices ACTED ON, which is too strict twice
over: the same device can be written as a hashed id in one statement and as
a local variable or `@global` name in another (PISTON_JSON_REFERENCE §4 —
never assume a `d` entry is already a hash), and two statements can belong
together through a device one of them only WATCHES. So the test is any
overlap across the devices each statement touches in either role.

GROUPS are expanded first (`device_aliases`), so a statement naming a
device-type variable and one naming a member hash are correctly seen as the
same devices.

KNOWN LIMIT, stated rather than hidden: `@global` device lists live outside
the piston, so they cannot be expanded here and two statements referring to
the same global by different routes still read as different. The effect of
getting it wrong is a piston split into more intents than it really has,
which costs accuracy in the ANNOUNCEMENT and never changes what is
emitted.


----------------------------------------------------------------------
read
----------------------------------------------------------------------
Every intent in this piston, in the order the statements were written.

Returns at least one for any piston with statements — a piston whose
purpose cannot be named still gets a `sequence` intent, never nothing.


----------------------------------------------------------------------
<genexpr>
----------------------------------------------------------------------
kind


----------------------------------------------------------------------
coverage
----------------------------------------------------------------------
Is every statement accounted for, in exactly one intent?

The gate. A statement in NO intent would be silently unread — the failure
this whole project keeps being bitten by — and a statement in TWO would be
emitted twice. Both are hard failures, never warnings (HARD_RULES §6).


----------------------------------------------------------------------
<genexpr>
----------------------------------------------------------------------
sequence


======================================================================
OTHER CONSTANTS
======================================================================
[('annotations',), ('dataclass', 'field'), ('intent', 'routing'), ('recurring', 'timed_revert', 'announce', 'reach_out', 'respond', 'remember', 'sequence'), (None,), ('check', 'check')]
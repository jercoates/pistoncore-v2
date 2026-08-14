# HARD RULES

Standing decisions by Jeremy, in plain words, with dates. **These outrank every
spec and all code.** Specs go stale and are known to be missing decisions; this
file is where a ruling lands the day it is made.

If a rule here conflicts with a spec, this file wins and the spec is wrong —
say so, don't silently follow either.

---

## 1. NEVER DELETE WORKING BEHAVIOUR WITHOUT JEREMY'S GO-AHEAD
**(Jeremy, 2026-08-06)**

A spec can tell you what to **build**. It NEVER, on its own, authorises
**undoing** something that already works.

**Why:** the specs are incomplete. Jeremy has updated them as he made decisions
but does not know that every change landed — *"i have been loath to have you
'stick to the specs' because i have been bitten by that before and had things
undone."* So if the code does something a spec doesn't mention, the likeliest
explanation is **a real decision that never got written down**, not a bug.

Silence in a spec is missing information, never permission to remove.

**How to apply:**
- Code and spec disagree → that is a QUESTION for Jeremy, never a mandate.
- Check the history FIRST: `git log -S "<the thing>" -- <file>`. This repo's
  commit messages carry reasoning, dates and often Jeremy's own words, so they
  are a second record of decisions the specs missed. One command, and it usually
  answers it.
- Still looks like a conflict? Bring it as a finding. Do not act.
- **Carve-out:** removing genuinely DEAD code (defined, referenced by nothing —
  grep the JSON and templates too) needs no permission. That is hygiene, not a
  behaviour change. See [[never_leave_dead_code]].

## 2. THIS IS AN INTENT COMPILER, NOT A TRANSCODER
**(Jeremy, repeated in every session, hourly)**

Never ask "how did webCoRE do this." Ask **"what did the user want to happen"**,
then let HA do it HA's own way. Same result, not same mechanism.

webCoRE is the authority for reading INTENT. Its mechanism is irrelevant on
emit. COMPILER_SPEC §3.0 (the intent-pattern catalog) is this component; as of
2026-08-06 it is **specified but essentially unbuilt**, and `analyze.py` carries
its name while actually producing a reshaped syntax tree.

A failed transliteration says NOTHING about whether HA can achieve the outcome.

## 2a. HOW TO READ INTENT — AND THE WRONG WAY, WHICH HAS ALREADY BEEN BUILT ONCE
**(Jeremy, 2026-08-08, across one long correction)**

§2 says this is an intent compiler. This says how to READ intent, because an
attempt was built on the wrong footing and thrown away the same day. Do not
rebuild it.

**THE STATEMENTS ALREADY ARE THE INTENT.** *"webCoRE statements as built show
you the intent — they are just set up in patterns."* The editor does not let
anyone write arbitrary code; it builds statements from a BOUNDED SET OF FORMS,
and each form already states a purpose:

    if <trigger> then <tasks>     "when this happens, do that"
    condition with ts / fs        "when true do this, when false do that"
    with <devices> do <tasks>     "make these devices do this"
    restriction on a statement    "only when ..."
    every <interval>              "repeatedly"
    each <device list>            "to every one of these"

**THE FORMS DO NOT NEED INVENTING — THE PICKER DEFINES THEM.** *"the way the
picker and falls are built shows you a pattern."* A device leads to its
capabilities, a capability to its attributes and commands, an attribute's TYPE
to the operators legal on it, a command to its declared parameters. A user
cannot author outside that cascade. VERIFIED 2026-08-08 that the cascade really
is in this repo: `webcore_vocab.json` carries 72 capabilities, 92 typed
attributes, 79 commands with parameter lists, comparisons bucketed into
conditions/triggers, and `attributeTypeToOperatorGroup`. So the form set is
DERIVABLE from the vocab, which also keeps it right for everyone's pistons
rather than fitted to Jeremy's (§5, §12).

**NOTHING IS THE WHOLE ON ITS OWN.** *"words are a PART not the whole"* — and
then, immediately, *"the pattern is a part not the whole."* Both halves matter,
and the second one names the obvious next mistake: having learned that words
are insufficient, the tempting move is to crown the FORM instead. Same error,
one level up. Intent is the COMBINATION — form, words, devices, order, gates,
relationships. Any design that elevates one of these to primary is wrong.

**WHAT WAS BUILT WRONG, so it is recognisable:** a layer that flattened each
statement into a sequence of outcome atoms (`on`+`wait`+`off` -> `be, later,
be`) and pattern-matched the SEQUENCE. It reads words in a coarser alphabet and
discards the structure the intent was stated in — then tries to guess it back.
It scored well on a gate (every statement accounted for, in order) while being
unable to tell a piston composing a spoken sentence from one tracking a flag,
because both are the same atom sequence. Deleted 2026-08-08.

**THE REMAINING QUESTION IS HOW TO USE THE FORMS** (*"i know they are patterns
but how to use them is the question"*) — that is genuinely open, and it is
compiler research, not something to hand back to Jeremy (§10i).

## 2b. NO MODEL IN THE COMPILE PATH — THE HARDWARE DECIDES IT
**(Jeremy, 2026-08-08: "AINT GOIN TO HAPPEN. not usable on 90% of the hardware
people use for ha")**

The idea of shipping a small local model (1.5B-3B, quantized) to read intent is
**dead, and not on grounds of taste.** Home Assistant's install base is
Raspberry Pis, HA Green/Yellow and cheap mini-PCs, frequently already swapping.
A model that needs a couple of gigabytes of RAM at compile time is unusable for
most of the people this is being built for (§12). A cloud call is worse: it
breaks the standing rule that the compiler works with nobody upstream.

**So intent reading MUST be deterministic.** That is a hard constraint on the
design, not a preference to revisit when models get smaller.

**And it is not the setback it sounds like.** The reading was demonstrated by
hand on raw JSON with the piston title HIDDEN, using an ordered scan — primary
triggers first, then what sits directly under each, then how device groups are
used differently, treating time/presence as policy rather than purpose, and
ignoring noise. Nothing in that scan needs a model; it needs the forced forms
(§2a) and PISTON_JSON_REFERENCE.md.

**Where the real difficulty actually sits.** Not "decoding" in some mystical
sense — it is designing the OUTPUT. The intent step must produce everything
needed to write the YAML (Jeremy, 2026-08-08), which means a behaviour spec
that is:
  - COMPLETE enough to emit from (a label or a one-line summary is useless),
  - PLATFORM-NEUTRAL — owned by neither webCoRE's grammar nor HA's syntax,
  - DERIVABLE deterministically from the forced forms.

That is what separates this from a transcoder, and the separation is in the
REPRESENTATION, not the mechanism: a transcoder maps piston nodes to HA nodes
one-for-one, while this maps the piston to a behaviour spec and then chooses an
HA idiom for the spec AS A WHOLE. Both are deterministic. Only one can see the
piston's purpose.

## 2c. THE OLD OUTPUT IS NOT THE YARDSTICK — MATCHING IT IS PROOF OF FAILURE
**(Jeremy, 2026-08-08: *"if the output matches then you failed anyway think about
it the compiled output before was wrong"*)**

The existing compiled output is WRONG in ways nobody has enumerated. So any
check of the form "the new reading agrees with what the compiler already
produced" validates nothing — it proves the bug was reproduced.

**This was broken all day on 2026-08-08**, in three forms that all felt like
diligence: proposing a shadow-diff of the intent path against the 84 snapshots,
quoting "NO DRIFT" as reassurance after intent changes, and scoring a reading as
4-of-5 against another chat's reading of the same piston.

**NO DRIFT means nothing changed. It never meant anything is right.** It is a
regression alarm for the transcoder, not evidence about intent.

**The only ground truth is what the piston actually does in Jeremy's house.**
Not the JSON's literal reading, not the emitted YAML, not another model's
reading, not agreement between two models — on the water piston an assistant and
Grok agreed with each other and were both wrong.

## 2d. THE AUTHOR CAN BE WRONG ABOUT THEIR OWN PISTON
**(Jeremy, 2026-08-08; the claim below RETRACTED 2026-08-13)**

This section used to state as fact: *"Jeremy gets ONE push, ONE text and ONE
speak per event"* on `70_Water_Leak`. **That was wrong, and it is deleted.**
The piston is a repeat loop with a 60-second wait, and it does exactly what it
says — re-sends every minute until every sensor is dry. Jeremy read the
compiler's own output on 2026-08-13 and said *"it looks like it will spam me
every minute untill dry."*

Why the wrong belief survived years of use: he has always been home when a
sensor tripped, so he either never noticed the repeat or pulled the battery to
silence the on-device siren. The path that would spam him — a non-critical
sensor while somebody is home, so the valve never closes — has never happened.

**Two things follow, and they point in opposite directions. Keep both.**

1. A reading that walks the statements faithfully can still be wrong, because
   what webCoRE's ENGINE does with an arrangement changes what it means (task
   cancellation on re-trigger; a wait inside a loop when the piston re-fires —
   COMPILER_SPEC §2.5, §10h: the groovy is TIER ONE for this).
2. **But it must not be replaced by deferring to what the owner remembers.**
   This entry was wrong for months precisely because a remembered behaviour was
   written down as fact, and every session afterwards read the piston through
   it. And most of the complex pistons are not his — Albert shared them and
   Jeremy adapted the devices — so for those his description is a READING, with
   no more authority than anyone else's.

Do not present a structural reading as an intent reading, and do not report an
accuracy score for one — there is no key to score against.

## 2e. EDGE vs STATE IS INTENT — NEVER NORMALISE ONE INTO THE OTHER
**(Jeremy, 2026-08-08: *"the watching for the change is the key to not spamming
me"*)**

`changes_to wet` fires ONCE, on the transition. `is wet` / `stays wet` fires
while the condition holds. They are not two spellings of one thing: the choice
decides **how often the user gets bothered**, and Jeremy picked the edge on
purpose so one leak is not a night of notifications.

**So any rewrite that turns an edge into a state, or a state into an edge,
changes the product.** It will look like a simplification and read fine in YAML.

webCoRE itself makes the distinction, so it is not an interpretation: the same
duration reads as "for" on a trigger and "in the last" on a condition.

Implementation status and the live hazard in `spec.py`: COMPILER_TODO.

## 2f. READ FROM THE EDITOR'S WORDS, WALK FROM THE JSON
**(Jeremy, 2026-08-08, after showing the editor beside the raw file)**

Neither source is sufficient alone, and the failure of each is the other's
strength.

**The JSON loses nothing and reads terribly.** No "any of", no "physically", no
units, no "for" vs "in the last". A walk over it produces an inventory.

**The editor reads beautifully and hides things.** Sections are FOLDED out of
view; empty `ei`/`e` branches draw as `else if / + add a new condition` and look
like real branches; every unused restriction slot draws as an affordance; the
orange WARNING bars are the editor talking ABOUT the piston, not part of it.

**So: render each node with the editor's own wording, but walk the tree from the
JSON so nothing folded, nested, or hung on a `ts`/`fs` is missed — and discard
the editor's furniture.**

The renderer already exists in the vendored dashboard and is battle-tested. It
is SEALED — read it, port it, never edit it (CLAUDE.md). Which functions, and
the port: COMPILER_TODO.

Evidence it matters: reading the water piston from a screenshot surfaced the
per-device battery accumulation, the speak sitting inside the `each`, and the
"Any of" aggregation — all present in the JSON and all read past.

## 2g. MEASURE IT BY WHETHER IT USES HA'S OWN IDIOMS — 0 OF 75 TODAY
**(Jeremy's research, CONFIRMED BY COUNT 2026-08-10)**

The question that separates an intent compiler from a transcoder, and it is
countable: **of the places Home Assistant has a native idiom, how many does the
compiler use?**

Measured over all 76 corpus pistons, YAML band:

```
conditions emitted:  template 152 · trigger 143 · time 30 · or 8 · sun 3
                     state      0     <- never emitted, not once
of those templates:   75 are exactly {{ states('x') == 'y' }}
                          — every one has a native `condition: state`
```

The transcoder owns ONE mechanism — render webCoRE's operand/comparison/operand
as Jinja — and puts everything through it, because that is the shape it
inherited. It never asks what HA has. `numeric_state`, `device` and native
`for:` are missing from that census too, so **0/75 is a floor.**

**Not cosmetic.** A native condition is an editable row in HA's visual editor; a
template is an opaque blob needing Jinja to touch. The YAML must outlive
PistonCore and be maintainable by whoever inherits it.

**USE THIS YARDSTICK BECAUSE THE OBVIOUS ONES ARE WORTHLESS.** Band split proves
nothing while nothing is device-validated (1 of 76 has been driven on real
devices). "It compiled / routed / HA accepted it" is not behaviour (§7).
Matching the old output proves the bug was reproduced (§2c). This number needs
no device, counts in one pass, and moves only when the compiler starts CHOOSING
an HA idiom instead of translating an expression.

**It is also the only honest case FOR the intent engine.** "The user wanted the
contact to be closed" maps to `condition: state`; "translate this expression"
can only produce a template. There is still NO PROOF the intent engine will be
better (Jeremy, 2026-08-10: *"it should, that does not mean it will"*) — as of
today it drops delays and timer-backed waits. Measure it; do not believe it.

## 3. YAML FIRST. PYSCRIPT ONLY WHEN THERE IS NO OTHER WAY
**(Jeremy, 2026-08-06)**

**Why YAML is the default:** PyScript is an optional community integration and
**could stop being maintained**. YAML is native HA and outlives everything. This
is survival, not taste.

**Route to PyScript only when HA cannot achieve the OUTCOME by any means** — not
when a transliteration fails. The PyScript band must SHRINK over time. If a
change moves more pistons onto PyScript, it went backwards.

The routing boundary must live in editable DATA (`routing_table.json`), never in
hardcoded logic, because HA gains abilities and that file is the one place to
update. (HA_LIMITATIONS.md §1 states this; several entries there were classified
by "can HA imitate webCoRE's mechanism" and are suspect — see §2.)

## 4. PYSCRIPT-ONLY IS A DELIBERATE USER FEATURE, AND MUST STAY TOTAL
**(Jeremy, 2026-08-06)**

A user can force PyScript for a piston. This is **not** "only when we have to" —
it exists so a user can get **full webCoRE trace emulation on every piston**.

Therefore the PyScript band must compile **anything**, always. Forcing it
bypasses routing entirely, so there is no fallback behind it: whatever it cannot
compile, the user simply cannot compile. A piston failing there is a bug in the
valve, never a missing feature.

## 5. TESTING SCOPE IS NOT BUILD SCOPE
**(Jeremy, 2026-08-06: "testing is not the same as not making more than that work")**

Jeremy's ~84 pistons are the **verification vehicle** — the things he can click
through and confirm, because they are his and he knows what they should do.

That says NOTHING about what gets BUILT. **Build for everything webCoRE can
express**; verify against his pistons plus the bench.

**Origin of the error:** he once told an early session he would "test through my
pistons and wait for feedback", and it was taken as where to STOP. Every session
since inherited corpus scope — including COMPILER_SPEC §3.0, which is specified
as *corpus-mined* and would repeat the mistake if built as written.

The correct basis is the bounded list in `webcore_vocab.json`: statement types,
comparisons, commands, functions, modifiers. Never the corpus.

## 6. SILENCE IS THE BUG
**(standing)**

A piston must NEVER deploy doing less than it says. Compiling to something
incomplete is worse than an honest refusal. If a shape can't be expressed,
raise — and note that routing to PyScript is not a safe fallback for anything
PyScript also drops.

## 7. VERIFY ON A DEVICE, NOT IN TEXT
**(Jeremy, 2026-08-06: "the only way to confirm exact behavior quickly")**

"It compiled", "it routed" and "HA accepted it" are **not behaviour**. Only a
device is. On 2026-08-06 a silently dropped action passed the snapshot harness,
the statement gate AND Home Assistant's own config check — all three said fine.

The bench makes this the FAST path, not the last resort: every
`test-devices-integration` action is a normal HA action, usable from
**Developer tools → Actions with no other software**. `virtual.create_device`
can fabricate any device at all, so coverage is not limited to hardware anyone
owns — which is what makes §5 achievable rather than a slogan.

**THE STANDARD, in Jeremy's words (2026-08-07):** *"any automation that is not
validated by making virtual devices and making it trigger and it does the
corresponding action is not tested correctly. Being valid to HA is not a good
test."*

So the test is always the same four steps: **build the device → deploy →
fire the trigger → read the resulting state.** An automation is validated when
the DEVICE did the thing, and at no earlier point.

**It proved itself twice inside twenty minutes on 2026-08-07**, both times on a
`cancelTasks` fix that looked finished:

1. The emitted YAML was valid, parsed, and HA accepted it — and the piston
   silently lost its turn-off timer, because two `automation` calls raced and
   left the target automation DISABLED.
2. The obvious repair (put a gap between them) failed the same way, and the
   device run showed WHY: the piston's own two triggers fire together, the
   automation is `mode: restart`, so it aborts itself in the gap and the target
   stays permanently off. Widening the gap makes it MORE likely, not less.

Neither was visible in the YAML, in the config check, or in the snapshot
harness. Both were obvious the moment a virtual sensor was driven. The fix was
reverted on that evidence — see COMPILER_TODO's cancelTasks entry.

## 8. NOTHING THAT TRACKS HOME ASSISTANT IS HARD-CODED
**(Jeremy, scoped 2026-08-01)**

Anything that moves when HA renames or changes things — service names, template
functions, how a value is read — lives in templates/JSON the USER can edit.
Compiler internals HA churn can't touch may stay in code. Fixed syntax that
won't drift is fine hard-coded (Jeremy, 2026-08-06).

The reason is the relief valve: a user must be able to repair their own compiler
with nobody upstream.

## 9. SEARCH BEFORE YOU WRITE
**(Jeremy, 2026-08-01, and broken repeatedly on 2026-08-06)**

Before adding any table, mapping, or helper, grep the WHOLE compiler for one
that already does that job — then USE it. If it's wrong, fix it in place; never
route around it with a copy. Include the JSON and templates in that grep.

Extends to the whole repo: on 2026-08-06 PyScript's source was downloaded from
GitHub while `reference/pyscript-source` held the identical version, and two
questions were asked of Jeremy that CLAUDE.md and HA_LIMITATIONS.md already
answered. Read what is here first.

## 10. THE PISTON AS A WHOLE IS THE INTENT — AND ORDER IS INTENT
**(Jeremy, 2026-08-07)**

Asked "one HA automation per piston, or several?", the answer is **BOTH**, and
the rule for choosing is:

- **Default: the whole piston is ONE intent.** Read it as one thing the user
  wanted to happen. Do not chop a piston into pieces because the pieces are
  easier to compile.
- **Exception: obviously stacked automations for an area.** A kitchen-sink
  piston holding several genuinely separate jobs (a common authoring style —
  Jeremy writes one-piston-one-job, *"most do not"*) reads as several intents.
- **Exception: HA cannot run it otherwise.** Some shapes MUST be split to work
  in HA at all. Finding which, and why, is compiler research — not a question
  for Jeremy.

**"IN THIS ORDER" IS INTENT, NOT SYNTAX.** If the user wanted things to happen
in a given order, that ordering is part of what they wanted and must survive
compilation. This is the line between intent and transcoding: a transcoder
preserves order by accident, an intent compiler preserves it *on purpose* and
must still preserve it when a piston is split.

**Split pistons stay CONNECTED.** They are not independent automations that
happen to come from one file — they share state and sequence. Whatever splits
them owes the connection between them.

Jeremy's own automations are complex and he *"has no idea how you could break
them up"* — so a split that only works on tidy pistons is not a solution.

### 10a. INTENT DOES NOT COME FROM THE VOCABULARY ALONE
**(Jeremy, 2026-08-07: "the intent is not just from the vocab that only gives
you a part of the picture")**

The vocabulary is the bounded list of webCoRE's WORDS, and classifying every
word by the outcome it expresses (`shim/compiler/intent.py`, gated by
`test_intent_probe.py --section intent`) is the **atom** layer. It is
necessary, it is provably complete, and **it is not intent.**

Intent lives in the SHAPE: "motion light with a timeout" is one thing the user
wanted, not `on` + `wait` + `off`. The rest of the picture comes from how
statements RELATE (trigger → wait → re-check), the ORDER, the devices
involved, the user's own naming, and what webCoRE's engine actually does with
it (COMPILER_SPEC §2.5).

A gate proving every word is accounted for says NOTHING about whether the
piston's purpose was understood. Do not present the atom layer as the intent
engine.

### 10b. RUN-ON AUTOMATIONS CARRY MULTIPLE INTENTS
**(Jeremy, 2026-08-07)**

A single piston can hold several unrelated intents — the kitchen-sink style,
which is the COMMON one (§12). So "the piston as a whole is the intent" is the
DEFAULT reading, not a guarantee of one.

The pattern layer must therefore be able to find **more than one** intent in a
piston, and having found them, still owes §10's obligations: the ones that
belong together stay together, ordering that the user meant survives, and the
pieces stay connected. Splitting a run-on piston into its real intents is the
same problem as §10's forced splits arriving from the other direction.

## 10c. "HA CAN'T DO THIS" IS ALMOST ALWAYS WRONG
**(Jeremy, 2026-08-07: "there is no way that ha doesnt do a capability in vocab
or mimic it somehow")**

**Home Assistant can achieve, or mimic, every capability webCoRE has.** Treat
`"ha": "n/a"` as a claim that must be PROVEN, never as a fact to build on.
Jeremy's own examples: **IFTTT = a webhook. HSM = an alarm panel.** HA controls
IR and Bluetooth. Nothing is simply absent.

**The failure mode has a name (Jeremy, 2026-08-07): "the classic AI mistake of
being byte identical and not the intent or what it means."** Searching for a
service SHAPED like webCoRE's, not finding one, and writing off the capability.
It is §2 again, at the vocabulary level instead of the statement level.

**Evidence this went wrong at scale** (all sourced from THIS repo, per §10e):
`git log` shows 0 `n/a` entries before 2026-07-12, then 46 injected in ONE
commit; 11 corrected 2026-07-24; 35 untouched since.

Checked directly against Home Assistant's own source on the bench, 2026-08-07 —
every one of these is currently marked `n/a` or unmapped, and every one exists:
`remote.current_activity` + `remote.activity_list` (vs `getCurrentActivity` /
`getAllActivities`), `light.effect` + `effect_list` (vs `startLoop`/`stopLoop`),
`number.set_value` and `select.select_option` (vs `setInfraredLevel`), the
`schedule` domain (vs `setSchedule`), `image` + `camera.snapshot` (vs `image`),
`FloorRegistry` (vs `floor`), and core `gps_accuracy` — **a core HA constant,
in metres** — against `horizontalAccuracyMetric` = "no HA equivalent".

That last one needs no outside document at all: the CURRENT vocab maps
`horizontalAccuracy` to `attr:gps_accuracy` tagged **verified**, while its
metric twin — the same HA attribute, in HA's own native unit — is marked
impossible. The contradiction is internal to the file.

## 10f. THE VOCAB'S `ha` TAGS ARE AI-GENERATED, NOT CHECKED
**(found 2026-08-07, from the repo's own record)**

Asked where the `verified` tags came from, the answer is in this repo:

- commit `32bfea1` (2026-07-12): the `ha` arrays were *"merged in from the
  **validated Fable5/Grok candidate vocab**"*.
- `COMPILER_DECISIONS_HOLDING.md` §I: each entry is *"one candidate HA
  mapping ... a `tag` of verified/assumed"*, and `"ha": "n/a"` is written up as
  *"confirmed no HA equivalent"*.

So **`verified` means the model that generated the line labelled it verified.**
It does not mean anyone compared it to Home Assistant. The only mapping in that
record noted as actually confirmed against reality is `level`/`setLevel`
("confirmed via live device comparison, not a research error") — and the fact
that one entry needed saying tells you the rest did not get it.

**Consequence, and it is wider than the `n/a` problem: no tag in
`webcore_vocab.json` is evidence.** Much of it is surely right (`lock` ->
`lock.lock`), 84 pistons compile, and some behaviour is now device-proven. But
"it's tagged verified" must never again end an investigation. Re-check against
HA's source or a bench device, and when you do, say so with the specific
constant/service you checked.

**What the harm actually is — CORRECTED 2026-08-07 after checking the code.**
The vocab's contract text says `"ha": "n/a"` means "never offered in the
picker", and an earlier draft of this rule repeated that and claimed each wrong
mark DELETES a capability from the editor. **That is not what the code does.**
`device_pipeline.py` falls unmatched attributes through to the raw
custom-attribute path (~line 548) and leaves unmapped services uncovered so
they surface as custom commands (~line 985) — exactly the hybrid rule Jeremy
had already stated: *"webcore can feed raw info in and make it through the
picker"* ([[hybrid_vocab_plus_raw_feed]]).

So the real damage is narrower and worth stating precisely:

- **Discovery survives** — the user can still see and use the thing, in raw HA
  terms (the entity attribute, the service name).
- **MIGRATION BREAKS** — a piston arriving from webCoRE that uses
  `setInfraredLevel` has no mapping, so it will not compile, even though the
  same user could hand-build it from the raw service sitting right there.

That is still a real bug and still worth fixing. It is not the catastrophe the
first draft claimed, and overstating it is the same failure as understating it:
asserting instead of checking.

**And it is the wrong SHAPE of answer.** Whether an IR level is settable
depends on whether THAT camera exposes it — a per-device fact known when the
device payload is built, not a constant. This contradicts the standing hybrid
rule ([[hybrid_vocab_plus_raw_feed]]): webCoRE can carry raw HA info through
the picker, so **missing from the vocab never meant unavailable.** The honest
values are "here is how to reach it when the device offers it" or "not mapped
yet" — never "impossible."

## 10e. NEVER GO INTO v1 — AND NEVER TREAT ITS TAGS AS EVIDENCE
**(Jeremy, standing; reason given 2026-08-07)**

Do not read, grep or copy from the v1 pistoncore repo without asking first and
naming the exact file and what you are looking for.

**The reason is not tidiness — it is that v1 is actively misleading.** Jeremy:
*"v1 was plagued by untagged assumptions in the original documents. For you it
is a literal field of land mines. It looks good but it's not."*

So a v1 document that says **verified** is NOT evidence. Its confidence labels
were applied without the discipline this repo now requires (VERIFIED with
source/line, ASSUMED, TO VERIFY), so a confident-looking v1 row may be someone's
guess from years ago. Importing those tags into v2 launders a guess into a fact.

**Therefore v1 is a source of LEADS, never of answers.** Every entry gets
checked against Home Assistant's own source or a real device on the bench, and
gets a tag naming that evidence. A lead from v1 that cannot be confirmed
against HA stays untagged and unmapped — it does not become "verified" because
a v1 table said so.

**Worked example of getting this wrong, 2026-08-07:** a v1 attribute map was
pasted into chat and used to "prove" that 16 of the vocab's `n/a` attributes
were regressions. That analysis was VOID — it measured the current vocab
against a v1 document, i.e. against the minefield. Findings that survived were
only the ones sourced from THIS repo (§10f) or checked directly against HA.
Do not repeat it: a v1 doc cannot be the yardstick for a v2 file.

## 10d. THE REPO IS THE AUTHORITY — JEREMY DOES NOT HAND-EDIT
**(Jeremy, 2026-08-07: "i dont add shit, all of it is in the chat or the repo")**

**Jeremy NEVER edits JSON or code** (his words, 2026-08-07). Not the vocab, not
the routing table, not the templates, not Python. Every byte of JSON and code
in this repo was written by an assistant in a chat session.

**He MAY edit `.md` and plain text** — so the prose docs can carry his own
words and edits, and a wording change there with no matching code change is
normal, not a mystery. JSON and code, never.

**So never explain a gap by guessing he fixed it somewhere else.** There is no
private corrected copy and no hand-patched instance. So:

- The repo's `webcore_vocab.json` IS the current state. If it says `n/a`,
  nothing anywhere says otherwise.
- When he remembers correcting something, look in `git log` — that is where it
  went. (The vocab's `ha` mappings were populated wholesale in `6fb9a97`, which
  is most likely what he is remembering; it also cut the `n/a` count 46 -> 35.)
- An unfixed thing is simply unfixed. Do not invent a stranded-corrections
  story to explain it — that was done on 2026-08-07 and it was wrong.

SEPARATE and still true: `shim/customize.py` only flows repo -> user
(`_fetch`/`stage`/`apply_staged`, no export). That is a real architectural gap
for OTHER users repairing their own installs
([[overlay_merge_relief_valve]]) — but it is NOT the explanation for anything
missing here, because Jeremy works through the repo.

## 10g. A MISSING DEVICE IS NOT AN ERROR — STOP REDISCOVERING THIS
**(Jeremy, 2026-08-07, for at least the SIXTH time across sessions:
*"this fucking problem has come up so many times that i know exactly what
happens... i told you what webcore already does"*)**

If you are about to report "pistons break when a device is deleted" as a
finding: **it is not one, and it has already been answered.** Read this instead
of raising it again.

**What webCoRE does** (VERIFIED — `reference/webcore_source_reference.groovy:1757`,
`listAvailableDevices`), and PistonCore shares the design:

- Piston JSON stores **hashed device ids**. The editor resolves hash -> friendly
  name against the **live** device list.
- A deleted device is not in that list, so it has no name and **the editor shows
  the hash**. That IS the notification. Nothing else raises it.
- **Editing and saving that statement removes the dead device by itself** — the
  picker only offers devices that exist. webCoRE does it for the user; there is
  no pruning code.
- **Untouched, the reference stays.** Correct, not a leak.
- **HA fails safe anyway** — entities go up and down under native automations
  constantly. That is ordinary HA life, not something to engineer around.

**Therefore, never build:** a registry scanner, a periodic sweep, an
`entity_missing` flag, a piston-list warning, or a guided repair wizard. That
design is written up in HA_LIMITATIONS.md and is **stale v1** — its own wording
gives it away ("Entity IDs are stored directly on condition, action, and
for_each nodes. There is no device_map"), and that file is **not in the
authority chain** at all.

**And never fail a compile over it — THIS IS ALREADY BUILT, do not "fix" it.**
`resolve.py:685` compiles and flags: an unknown hash or name keeps its
reference, resolves to an inert placeholder, and is recorded in
`self.unresolved` for the UI. Ruled 2026-08-01, and unknown hashes have worked
this way since 2026-07-19. `resolve.py:700` `remembered_entity()` even lets a
device that has TEMPORARILY left HA keep its place in the compiled automation.

On 2026-08-07 this was written up as an OPEN question needing Jeremy's ruling —
it was neither open nor unruled, and "fixing" it would have meant rewriting
working code. The `UnresolvableDevice` raises that remain are vocab mapping
gaps and empty globals, which ARE real errors. Do not confuse the two.

## 10h. WALK THE AUTHORITY CHAIN BEFORE CALLING ANYTHING OPEN
**(pattern named 2026-08-07 after three in one session)**

Non-device globals, device globals, and missing devices were each filed as
"unknown / needs a decision" in a single session. All three were already
decided. The cause each time: reaching for whatever was easiest to grep instead
of walking the chain in order.

**The order is:** HARD_RULES -> **the webCoRE sources** -> the four specs
(SHIM_API, DEVICE_PAYLOAD, PISTON_JSON_REFERENCE, COMPILER_DECISIONS_HOLDING)
-> code.

`reference/webcore_source_reference.groovy` and the Hubitat engine are **TIER
ONE**, not a last resort. Most "how should this behave" questions are answered
there, because the answer is almost always *what webCoRE already does*.

## 10i. NEVER HAND JEREMY A TECHNICAL QUESTION THE SOURCES DECIDE
**(Jeremy, 2026-08-08: *"im getting tired of you leaving things undecided on
technical questions that i have no idea how to answer"*)**

He does not code. A question like *"should cancelTasks cancel every timer the
piston owns or only its condition scope?"* is **not answerable by him and never
was** — it is answerable by reading the engine, which is exactly what an
assistant is for. Handing it to him converts work into a blocker and leaves him
holding a decision he has no basis to make.

**Before writing any question for Jeremy, ask: does a SOURCE decide this?**

- webCoRE behaviour -> the groovy (TIER ONE, §10h). Nearly always decides it.
- HA behaviour -> HA's own source or docs, or the bench.
- Already-ruled policy -> HARD_RULES.

**Worked example, same day:** three items were listed as "OPEN FOR JEREMY" in a
handoff. All three were already decided — the cancelTasks scope was in the
engine (and had been quoted EARLIER IN THE SAME SESSION), the restart question
was engine research, and the third was already settled by §10c. None should have
been asked.

**What IS legitimately his:** what he wants the product to DO, trade-offs
between behaviours a user would notice, and anything touching his house or the
public repo. Never how a mechanism works.

If a source genuinely does not decide it, say what you searched and what you
would do by default — then proceed on that default rather than blocking.

## 11. HOW A COMPILE DECISION IS ANNOUNCED
**(Jeremy, 2026-08-07 — extends §UI-split in CLAUDE.md, does not replace it)**

When the compiler decides what a piston is FOR, it says so in exactly two
places:

1. **A banner on the landing page, the FIRST time** — not every visit.
2. **A comment at the top of the emitted YAML itself.**

The YAML comment matters beyond convenience: it travels with the automation and
survives PistonCore being deleted ([[no_runtime_pistoncore_dependency]]), so the
reasoning is readable by whoever owns the file later, with no tooling.

## 12a. THE INTENT ENGINE LANDS AS A WHOLE, ON A BRANCH
**(Jeremy, 2026-08-07)**

**Nothing from the intent-engine work is pushed until it works as a whole.**
Partial intent work does not go to `main`.

If it takes a while, it goes on a **new branch**, and the mostly-working `main`
**stays live for people to pull and check out**. The public repo keeps a working
compiler at all times ([[repo_is_public_others_use_it]]).

So: no "half of stage 1 is in" pushes, and no recommending a push because the
harnesses are green. Green harnesses are not "works as a whole" — see §7.

## 12. THIS IS NOT BEING BUILT FOR JEREMY
**(Jeremy, 2026-08-07: "im not going to be the only one using this")**

Design for the authoring styles OTHER people have, not the one Jeremy has. He
writes one-piston-one-job; the common style is the kitchen sink. Anything that
only works on well-organised pistons is not finished.

Corollary on where knowledge comes from: **everything Jeremy knows is already in
the documents or the chat.** He is new to HA (his words, 2026-08-07). HA
research is the compiler's job to do — do not ask him HA questions he would have
to go and look up himself.

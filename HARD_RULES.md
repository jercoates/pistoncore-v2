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

## 2g. MEASURE IT BY WHAT A PERSON INHERITS — RUN IT, DO NOT QUOTE IT
**(Jeremy, 2026-08-15)**

**Could someone keep these automations working if PistonCore vanished?** That is
what the output is finally judged on — *"working automations that dont rely
hevily on blobs people cant keep up without pistoncore"*.

```
python test_intent_probe.py --section maintainability
```

It counts what a human inherits: how much lands on the readable band rather than
PyScript, how many conditions are editable rows in HA's own editor rather than
Jinja blobs, how many helper entities the automations cannot run without, and
how many branches only make sense next to their siblings.

**NEVER QUOTE A FIGURE FROM THIS FILE FOR IT.** This section used to state "0 of
75" as current fact. It was true when measured, nothing re-measured it, and it
was wrong within days — while still being read as authoritative by every session
that opened this file, because HARD_RULES is mandated reading. A count in prose
rots; a check re-measures and can be run by anyone in one command.

**Why these and not the obvious measures.** Band split alone proves nothing.
"It compiled / routed / HA accepted it" is not behaviour (§7). Matching the
previous output only proves the old bug was faithfully reproduced (§2c). These
need no device, count in one pass, and move only when the compiler starts
CHOOSING an HA idiom instead of translating an expression.

**Not cosmetic, and one of them is not even about looks.** A native condition is
an editable row in HA's visual editor and a template is a blob needing Jinja —
but a missing helper entity does not just read badly, it stops the automation
working. The emitted YAML must outlive PistonCore being deleted.

**It reports rather than gates, on purpose.** Nobody yet knows what these numbers
*should* be: some templates are the only honest way to say a thing, and some
pistons belong on PyScript. A threshold set today would lock in a decision
before the how is known. Make it a gate once a baseline is agreed — and record
that as a decision with a date when you do.

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

## 12d. ACT-THEN-VERIFY NEEDS TIME, AND THE TIMEOUT IS THE FAILURE
**(Jeremy, 2026-08-27: *"a delay for things to happen in this type of
automation is usualy going to be a good thing"*.)**

When a piston ACTS on a device and then CHECKS that same device to see whether
it worked, Home Assistant must be given time before the check. A service call
returns before the hardware answers, so an immediate re-check reads the state
from BEFORE the action — the verification is not merely racy, it is
meaningless.

**`01_Alarm_Arming_checks` is the worked example, and the piston SAYS SO** —
this is not inferred from hardware knowledge, it is written in the message
text, which is why reading the whole piston matters:

     9  "...Attempting to lock door(s)"
    17  lock
    18  "🚨 Unable to Lock Door(s) 🚨"
    20  notify "...Please Return Home and Manually Lock Door(s)"
    21  notify "🚪🔒 Door(s) Locked 🔒🚪"

"Unable to lock" is only true if the lock was GIVEN TIME TO TRY. Emitting the
re-check immediately does not just risk a false alarm — it makes the piston's
own sentence untrue.

**Jeremy's hardware, which the code cannot tell you:** the deadbolts are motor
driven with force sensing. A door that is not shut tight stalls the motor and
the bolt does not throw. The second check is reporting a REAL PHYSICAL
CONDITION, not a timing artifact, and it is why the piston is worth its
complexity.

**HA's form, and the timeout IS the fault signal** — not a guessed delay:

    - action: lock.lock
      target: {entity_id: "{{ ...the unlocked ones... }}"}
    - wait_template: "{{ ...none still unlocked... }}"
      timeout: "00:00:30"
      continue_on_timeout: true
    - if: <any still unlocked> -> "Unable to Lock"
      else:                    -> "Doors Locked"

**⛔ SCOPE — DO NOT GENERALISE THIS INTO "ADD DELAYS".** It applies ONLY where
the piston acts and then verifies the same device. It must NEVER be added to an
announce path: the CO alarm's whole safety gain is re-triggering in 12 seconds
instead of 30 (§14, and Jeremy: *"waiting gets people dead"*).

**STILL UNKNOWN, do not guess either:** how long to wait (a number Jeremy's
hardware knows, not the piston), and whether a partial result — three locked,
one stalled — should send both messages or only the failure.

**The detector is NOT built and NOT proven.** A first crude attempt matched 41
pistons and was plainly over-counting (it matched promises in unrelated
branches, with negative gaps). The shape is real and visible in the arming
pistons; its frequency is unmeasured.

## 12c. A PISTONCORE VARIABLE IS NOT A HOME ASSISTANT VARIABLE
**(Jeremy, 2026-08-26: *"those are a veriable in pistoncore not ha. do you get
the distiction yet?"*)**

Two different things wear the word "variable" and confusing them has now cost
time twice:

- **A PISTONCORE variable** is a value the compiler KNOWS. Jeremy's define
  block — `Repeat_Time_Sec = 30`, `Speaker_Vol = 100`, `Night_Time_Begin` — is
  this. Nothing in the piston assigns it, so its value is whatever the piston
  was last saved with, the compiler substitutes it, and **Home Assistant never
  sees a variable at all**. Editing it in webCoRE saves, a save recompiles, and
  the new number is written into the YAML. That IS the workflow he built the
  define block for: *"adjust things like volume devices, pauses without going
  through the statements"*.
- **A HOME ASSISTANT variable** is a runtime value — `variables:` in a
  sequence, or a helper entity when it has to outlive the run.

**Treating the first as the second is always wrong**, and it does not fail
loudly. `a12`/`a66` (named *"Repeat 30sec"*) had their cadence read as UNKNOWN
and were refused as "not a fixed number of seconds", when the answer was
sitting in their own define block. Same class as the earlier bug where a named
threshold reached the emitter as None and HA silently disabled the automation.

**The tool already exists: `resolve.unassigned_locals()`.** The transcoder has
used it since 2026-08-21 (`analyze._resolve_named_thresholds`). Ask it — never
write a second answer, and never route a compile-time constant through a
helper.

## 12b. THE SWITCH IS FLIPPED — INTENT IS THE DEFAULT
**(Jeremy, 2026-08-26: *"lets flip the switch"*. SUPERSEDES §12a's default-off
half; the rest of §12a still stands.)**

`emit_intent.enabled()` now defaults **ON**. `PISTONCORE_INTENT_EMIT=0` turns
it off per process, and the stored setting per install.

**Why it is safe, in his words: *"the fact it will fall back to the transpiler
anyway is a plus not a negative."*** He is right, and this was the argument
against it until he reframed it. `plan()` returns None for anything the intent
reader cannot express and compilation falls through to the transcoder
unchanged — so flipping the default can only move pistons the intent path does
BETTER, and leaves every other one byte-identical to today. That was measured,
not assumed: after the 2026-08-26 work the transcoder's output for all 154
corpus pistons was unchanged.

**What §12a asked for has been met.** It held the default off because the
engine "has never passed a §7 device test". It has now — three of Jeremy's own
pistons, driven end to end on real devices through PistonCore, no hand-editing:
the carbon-monoxide alarm (speaks, names the right detector, clears), the
low-battery report (which HA had been silently refusing outright), and the door
chime (both the night branch at 0.7 and the `else` day branch at 0.9, with the
sentence intact).

**Corpus, both paths:** intent 124 yaml / 25 pyscript / 5 errors; transcoder
120 / 26 / 8.

**⛔ DO NOT LIFT THE "inside a loop" REFUSAL UNTIL THE UNTIL-CONDITION IS
FIXED (found 2026-08-26, by doing the reading check Jeremy has been asking
for).** The intent reader turns a `repeat ... UNTIL <cond>` into a GATE on the
body promises, so `11_Carbon_Monoxide_detected` reads as:

    setVolume / playText / lights on / notify
      ONLY IF: All of {@Smoke_Detectors}'s carbonMonoxide are CLEAR

webCoRE runs that body **while the detectors are NOT clear**. The reader has
recorded the EXIT condition as an ENTRY condition — an exact inversion, which
would make a carbon-monoxide alarm announce only once the danger had passed.
§6's worst class, on the worst possible piston.

**7 corpus pistons carry a repeat-UNTIL and every one is a safety piston** —
11 and a12 (CO), 63 and a66 (smoke), 29 (gas), 70 and a77 (water). All 7
currently fall back to the transcoder, which is the ONLY reason this has never
shipped. The fallback is doing exactly the job Jeremy said it would.

**THE READING IS CHECKED BEFORE THE OUTPUT IS (Jeremy, 2026-08-26: *"i keep
forgetting to have you check the intent for a correct reading of the pistons
and then after running them correctly through pistoncore to check if it
reproduced the intent of the original webcore piston"*).** Two stages, in this
order, and the first is not optional:

1. **Does `spec.read()` say what the piston MEANS?** Print the promises with
   their WHEN / ONLY IF / AFTER and read them as English against the piston.
   This is what caught the inversion above — no amount of output testing would
   have, because those pistons do not use the intent path yet.
2. **Does the emitted automation reproduce that**, driven for real through
   PistonCore on the bench.

**The next question, and it is open:** ~20 pistons still fall back. That is a
safety net doing its job, not a failure — but each fallback is a piece of the
engine that is not finished, so the reasons are worth knowing one by one.

## 12a. THE INTENT ENGINE LANDS AS A WHOLE, ON A BRANCH
**(Jeremy, 2026-08-07 — default-off half superseded by §12b, 2026-08-26)**

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

## 13. SYNTHETIC IS FOR PARTS. A SAFETY RUN GOES THROUGH PISTONCORE, WHOLE
**(Jeremy, 2026-08-22)**

Testing a PIECE against a synthetic map or a hand-written script is fine — it
answers a mechanical question quickly.

**It is never acceptable for "does this piston work", and never for a safety
piston.** That run goes through PistonCore end to end: real devices made by the
factory, the real compiler, a real deploy, a real trigger, and the real
outcome read back. **No hand-written YAML, no hand-made devices, no hand-built
resolution map.**

**Why, measured the same day.** `test_compile_snapshots._synthetic_maps`
fabricates ONE device per reference. A per-device loop built over it emitted a
condition pinned to a literal entity, and with a single fabricated device
"the first device" and "the correct device" are the same thing — so it passed.
Three real detectors on the bench, with the SECOND one alarming, showed the
truth immediately: the emitted automation announced **nothing**. A
carbon-monoxide alarm that stays silent, which every synthetic check called a
pass. See COMPILER_TODO, the for_each condition entry.

**And hand-made devices are their own trap** (Jeremy, 2026-08-22: the previous
session "hand made the devices wrong and it chased its tail for a half hour").
Create devices through PistonCore's factory using its BUILT-IN types. Five
devices hand-made on 2026-08-21 were built on the wrong platform — binary
sensors under the sensor platform, a fan as a light — and HA warns they stop
working entirely in 2027.5.

## 14. ACTIONS INSIDE A LOOP RUN INSIDE THE LOOP — AND ON A SAFETY PISTON THAT IS THE WHOLE POINT
**(Jeremy, 2026-08-22: *"this is a safety thing asshat waiting gets people
dead"*)**

A per-device loop in a smoke/CO/gas piston is **collection** — it keeps finding
devices that go into alarm instead of stopping at the first. The speak sitting
INSIDE that loop is deliberate: the house is warned the moment the first
detector is found, and warned again as more are found.

It was proposed to collect every alarming device first and announce once, on
the grounds that announcing twice looked like an accident of where the
statement landed. **That puts a delay in front of a carbon-monoxide alarm to
make the emitted YAML tidier.** Do not do it, and do not re-derive it.

**The rule, generally:** actions inside a loop run inside the loop. Order and
repetition are intent (§10). **The only loop that may collapse into a single
expression is one that does nothing but collect** — which is exactly what
`_accumulate_loop`'s existing guard checks. That guard is correct; leave it.

## 15. THE VOCAB IS webCoRE'S WORDS. NO webCoRE SIDE = A TEMPLATE
**(Jeremy, 2026-08-22)**

`webcore_vocab.json` maps **a webCoRE word** to how HA achieves it. A thing
webCoRE cannot say has no entry to make — it is a **compiler artifact**, and it
lives in `templates/compiler/…` where it is still user-editable (§8) but sits
with the compiler's own constructs instead of the translation table.

Worked example, same day: "when did this device last report" has no webCoRE
word at all — 92 attributes, 99 system variables, nothing. It was about to be
added to the vocab. It belongs in a template.

## 16. DEVICE VARIABLES ARE SETTLED — THE FALLOUT IS IN THE OTHER TYPES
**(Jeremy, 2026-08-22)**

**A device variable, local or global, is ONE thing: a named list of the devices
the statements act on**, resolved to entity ids at compile time. Jeremy specced
these deliberately, understands them on both platforms, and they work. 369 of
the corpus's 561 declarations are these. **Do not re-derive or "improve" them.**

**Every other variable type is underspecced, and that is where the bugs are** —
his words: *"I do not know the rest of the veriable types well so they got
underspecked and this is the fallout from that."*

**The reason the gap exists, and it is worth keeping:** he underspecced them
because *"in essence they match across between hubitat and ha"* — which is TRUE
of the values (a string is a string) and FALSE of where they live. webCoRE
gives every piston a persistent variable store for free. HA has no such thing
for an automation: a `variables:` block lasts one run, and anything longer has
to become a real entity in the user's HA. **webCoRE has one answer; HA has
four.** From the webCoRE side there was nothing visible to specify.

Corollary: **the 255-character ceiling is a limit on ENTITY STATE, not on
YAML.** A run-scoped variable is not an entity — a `variables:` block holds
native lists, numbers and strings of any length. "Lists blow the cap" was used
to argue lists could not work in YAML; it is wrong.

## 17. WHAT "IT WORKS" MEANS — AND THE THIRD TEST IS THE PROJECT
**(Jeremy, 2026-08-22: *"it needs to 1 compile 2 not error 3 most important
match the intent of the webcore json. untill all are met it does not work"*)**

1. **it compiles**
2. **it does not error**
3. **it matches the INTENT of the webCoRE JSON**

**All three, or it does not work.** 1 and 2 are cheap and are what every
session reports. 3 is the entire reason this project exists, and it is the one
that gets skipped — because 1 and 2 produce output that looks like success.

**"The device did the thing" is still not enough.** It has to do the thing the
piston MEANT. A carbon-monoxide piston that speaks, but names the wrong
detector, passes 1 and 2, does something observable, and is still wrong. So the
question is never "did HA do something" but **"did HA achieve what the piston
intended"** — the right device, the right values, the right message, in the
right order.

**Intent, NOT the previous compiled output** (§2c): matching what the old
compiler produced proves the old bug was reproduced. The intent is read from
the piston JSON and from what the automation does in the house.

**How to report:** say which of the three you reached. Never write "verified",
"works" or "done" without 3.

### 13a. ONE HAND-BUILT PART VOIDS THE WHOLE RUN — THERE IS NO PARTIAL CREDIT
**(Jeremy, 2026-08-22: *"if you cheat on 1 thing IT IS WRONG and proves not a
god damned thing"*)**

A verification run with ANY hand-substituted part — a hand-built resolution
map, a hand-patched device list, YAML copied into the config folder by hand,
a hand-made device — **proves nothing at all.** Not "partial evidence", not
"the mechanism at least works". Zero.

**The reason is not purity, it is that the hand-built part is exactly where the
bug hides.** The same day this was written: a fabricated one-device map hid a
carbon-monoxide alarm compiling to silence, and then a hand-assembled run of
the "fix" was reported as progress. Both looked like passes.

If the app cannot do a step yet, **that is the finding** — say so and fix the
app. Do not fill the gap by hand and call the result a test.

Corollary: **use the user's OWN pistons.** An `a`-prefixed piston is Albert's;
its intent is not Jeremy's to recognise.

## 18. A DEVICE THAT CANNOT DO THE COMMAND FALLS OUT AT COMPILE — IT DOES NOT ERROR
**(Jeremy, 2026-08-22: *"incorrect device types should fall out at compile from
variables not error"*)**

A variable or global holds a LIST of devices. If one of them cannot perform the
command being asked of it, **that device is dropped from that command's targets
at compile time.** The piston still compiles, and every device that CAN do the
thing still does it.

**It must not fail the piston.** Today `@Alert_Lights` contained a speaker and
the whole piston died with *"no HA service mapping for command 'on' on domain
'unknown'"* — one wrong member took down every light in the list.

This is the same ruling as the battery report: **drop what cannot answer,
never invent, never take the working ones down with it** (§ the null-battery
entry — "they should drop not make shit up, ha has it correct"). It is also the
same shape as HARD_RULES §10g: one bad device reference never fails the piston.

**Still say so.** Dropping silently is the other failure (§6). The dropped
device is a compile-time fact and belongs on the two announcement surfaces
(§11), naming the device and the command it could not do.

**Only an EMPTY result is an error** — if no device in the list can do the
command, there is nothing to emit and that is worth failing on.

## 19. WHEN THE INTENT PATH CANNOT DO SOMETHING, LOOK AT THE TRANSPILER FIRST
**(Jeremy, 2026-08-22: *"i went through a lot fixing these problems in the
transpiler untill i found out it was a transpiler."*)**

The transpiler holds TWO different things, and only one of them is being
replaced:

- **How the structure is decided** — statement in, branch out. That is the part
  that was wrong, and the intent path replaces it.
- **How Home Assistant actually achieves each thing** — which service, which
  field, which template function, which guard. **Jeremy drove that out problem
  by problem over months.** The intent path does not replace one line of it;
  `emit_intent`'s own docstring says translation fills the slots afterwards.

**So a thing the intent path cannot do is usually SOLVED ALREADY, a few files
away.** Compile the same piston with `PISTONCORE_INTENT_EMIT=0` and read what
the transpiler emits before concluding anything is missing or broken.

**Worked example, the day this was written.** A speak on the intent path
resolved to `unknown.pistoncore_unresolved_…`, and that was written up as
"PistonCore uses Hubitat's TTS model, every speak in every piston is a
placeholder" — in TWO documents, as fact. One command against the transpiler
disproved it: `media_player_entity_id: ['media_player.dev0']`, resolved
correctly all along. The real fault was a test device built from the factory's
plainest `"Speaker"` type, which advertises no speech capability.

One unrepresentative input, generalised into a compiler-wide claim — the same
failure as trusting a one-device synthetic map (§13). **Check the transpiler.
It is not the old path; it is the answer key.**

## 20. NEVER WRITE A PLACEHOLDER ENTITY INTO HOME ASSISTANT — FLAG IT AND LEAVE IT OUT
**(Jeremy, 2026-08-22: *"dont write the placeholder in ha just trigger the flag.
the placeholder is for a missing device and it will be the real device hash in
webcore."*)**

When a device reference cannot be resolved to a real HA entity, the compiler
today invents one — `unknown.pistoncore_unresolved_…` — and writes it into the
YAML, on the reasoning that an inert placeholder is gentler than failing the
piston (ruled 2026-08-01).

**IT IS NOT INERT. `unknown` is not a real domain and that is not a real
entity, so Home Assistant validates the automation, REJECTS IT, and disables
THE WHOLE THING** — every trigger and every action, not just the bad
reference. Measured 2026-08-22 on `38_Low_Battery_Check`:
`state: unavailable`, `last_triggered: None`, HA logging *"Entity
unknown.pistoncore_unresolved_… is neither a valid entity ID nor a valid
UUID"* — while PistonCore reported `deployed`. The fail-soft design fails
HARD, one layer down, in silence.

**THE RULE:**

- **The piston keeps the hash.** That is webCoRE's business and it is correct —
  the editor shows the hash, and editing the statement drops the dead device by
  itself (§10g). Nothing changes on the webCoRE side.
- **Home Assistant gets NOTHING for that device.** No invented entity id. It
  simply is not in the emitted list.
- **The flag still fires**, so the two announcement surfaces can say which
  piston references a device that no longer exists (§11).

Same principle as §18 — a device that cannot do the job falls out at compile,
the ones that can still do it, and only an EMPTY result is worth failing on.

**There is no such thing as a harmless invalid entity id in HA.** Anything the
compiler writes into an `entity_id` must be an entity that exists.

### 20a. WHERE UNRESOLVED DEVICES ACTUALLY COME FROM — scope for §20
**(Jeremy, 2026-08-22: *"the devices not resolving on creation will be rare and
probably only on globals. you cant pick whats not there."*)**

**It cannot happen while authoring.** The picker only offers devices that
exist, so a freshly written statement always resolves. Unresolvable references
appear AFTER the fact:

- a device is **deleted** from HA after the piston was written (§10g — webCoRE
  shows the hash and carries on; that behaviour is correct and stays);
- a **GLOBAL** points at a device that is gone, is empty, or was never created
  in this instance. This is the main source, because a global is shared and can
  be edited or emptied independently of every piston using it.

Seen the same day: the corpus errors were `@Night_Time_Begin not found` and
similar — globals, not picked devices.

**Two consequences:**

1. **It is rare, which makes it worse, not better.** A failure mode that fires
   occasionally is one nobody notices is broken — and today it takes the ENTIRE
   automation down while reporting `deployed` (§20).
2. **Look at globals first.** When a piston deploys dead, the odds are a global
   is empty or missing, not that the author picked something impossible.

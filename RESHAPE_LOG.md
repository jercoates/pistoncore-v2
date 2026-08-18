# RESHAPE LOG — observations only

A running record of cases where the intent path produces a **different shape**
than the transcoder, or declines to produce one at all.

## What this file is for

Not the fixes. **The signature behind the fixes.** Any single case looks like a
one-off; the pattern only shows up across a handful of them. The expectation is
that somewhere around the fifth or sixth entry these stop looking like
individual cases and start looking like a small number of families — which is
what turns "check all 154 pistons" into "check for these four signatures."

(Origin: Jeremy, 2026-08-17, carrying over a suggestion from another session.)

## The rule this file lives or dies by

**PURELY DESCRIPTIVE. No "and here's how to emit that."**

The moment an entry says how the compiler should handle a case, this stops
being a record and becomes a spec — and a spec written from three examples will
steer the compiler before anyone has seen enough cases to know what the
families actually are. That has already cost this project real time: a spec
based on too few cases is how §3.0 came to be written for a layer that was
never built (see `pattern_recovered.md`, which reads as law and describes code
that does not exist).

Observations now. Generalization when the entries earn it. If you catch
yourself writing an imperative verb, you are writing the wrong file — put it in
`COMPILER_TODO.md` instead.

## Entry format

Three fields, nothing else:

- **SIGNATURE** — what identified this case. The property that would let you
  spot the next one *without* already knowing the answer. This is the field
  that generalizes; everything else is context.
- **RESHAPE** — what actually changed shape. What collapsed, what moved, what
  merged. Stated as observation, not instruction.
- **SURFACED BY** — the piston(s) it appeared in.

A worked example of the intended grain, from the session this idea came out of:

> **SIGNATURE** — a variable written and read entirely within one execution
> path, never crossing a wake.
> **RESHAPE** — the variable collapses to nothing; the string moves inline into
> the action argument.

Note what that does *not* say: anything about how to emit it.

---

## Entries

### 1 — the wait stays in the action list

- **SIGNATURE** — an intent-produced branch whose action list still contains a
  `delay` node when emission reaches it. Detectable without knowing the piston:
  `action node 'delay' not compiled yet` raised while the intent flag is on,
  for a piston the transcoder emits as YAML.
- **RESHAPE** — the wait survives as one inline node inside a single branch's
  actions. On the transcoder the same piston never presents a node of that kind
  to the emitter at all.
- **SURFACED BY** — 16 pistons. `07_Basement_motion_Light`,
  `12_Cave_motion_V2`, `33_Hall_motion`, `35_Kitchen_Motion`, `36_Laundry_Light`
  and 11 more; almost all are motion-lights-with-a-timeout.

### 2 — the condition becomes the wake

- **SIGNATURE** — an intent-derived wake whose comparison is instantaneous
  (`is`, `is_less_than`, `was`) rather than change-shaped (`changes_to`,
  `rises_above`). Detectable as `trigger comparison '<op>' not compiled yet`
  where `<op>` is one the emitter accepts perfectly well as a *condition*.
- **RESHAPE** — the same test occupies both roles: it is what wakes the
  automation and what the automation then checks. The two are one node rather
  than a change-shaped wake paired with a separate test.
- **SURFACED BY** — 11 pistons. `is_less_than` ×5
  (`a23_Downstairs_Hallway_Night_Light`, `a40_Kitchen_Night_Light`,
  `a47_Master_Bathroom_Night_Light`, `a76_Upstairs_Hallway_Night_Light`,
  `16_Chicken_lights_Lumen_sensor` — every one a lux-gated night light), `is` ×5,
  `was` ×1.

---

## First clustering — 2026-08-17

**27 cases, 2 signatures.** The prediction that these would turn out to be a
small number of families rather than individual cases held on the first pass,
and earlier than expected — it did not take five or six entries, because the
compiler's own exception text already carried the signature.

That is the reusable part: **the signatures were not something to invent, they
were already being raised and thrown away.** No new diagnostic was needed to
find them; the failures had been naming themselves into a routing decision that
discarded the message.

Consequence worth keeping in view: 27 pistons is not 27 problems. Checking a
new piston against these two signatures is cheap; auditing it case by case is
not.

### What happened when both families were addressed — 2026-08-17

Recorded here as an OUTCOME, not as a method. Both turned out to be answerable
with machinery that already existed, which is worth noting because it is now
the third time in one session that the missing piece was already in the repo:

| family | pistons recovered | what already existed |
|---|---|---|
| 1 — inline `delay` node | 17 | the node shape and its renderer; only the input path rejected it |
| 2 — instantaneous comparison as wake | 10 | `_promote`, built for condition-only pistons |

Intent band before: 91 YAML / 54 PyScript / 9 errors.
Intent band after: **117 YAML / 32 PyScript / 5 errors** — identical to the
transcoder, with the same 5 remaining failures and none of them intent-specific.

Not verified: behaviour. Every number above is "compiles", which this project
has repeatedly found is not the same thing.

---

## Superseded — 2026-08-17 (kept for the correction it records)

**The first reading of this was wrong, and the error is instructive.**

I assumed the 27 were cases where `emit_intent.plan()` *declined*, and that the
fix was to instrument its refusal paths. It does not decline: it returns
branches, emission continues, and the failure happens downstream while emitting
those branches. So the signature was never a refusal — it was the emission
error, which was already being raised.

The note below is what that wrong reading looked like. The lesson it carries:
before adding a diagnostic, check whether the thing already says what it is
doing and something downstream is dropping it.

**Zero entries, and that is a measurement, not an omission.**

27 pistons compile to YAML on the transcoder but not on the intent path (23
fall through to PyScript, 4 error). Every one of the 27 declines **silently** —
`emit_intent.last_refusal` is unset for all of them, so the compiler cannot say
why it declined even once.

The `_refuse()` diagnostic exists and works, but only four call sites use it,
and none of those is on the path these 27 take. Across the whole corpus only 15
declines record a reason at all:

| count | recorded reason |
|---|---|
| 7 | inside a loop |
| 6 | per-device fan-out |
| 2 | nothing wakes it and no wake could be derived |

None of those 15 overlaps the 27.

So the sequence has to be: **make the declines speak first, then log what they
say.** Guessing at signatures from the outside would produce exactly the
premature generalization this file is meant to prevent — the entries would
record my theory of the cases rather than the cases.

Nothing about the 27 should be written here until the compiler itself reports
why it turned each one down.

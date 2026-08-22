# HOW TO ASK HOME ASSISTANT HOW IT DOES THINGS

**Claude help file 00. Self-contained — assumes you have read nothing else.**

Jeremy points a session at the help files it needs for the problem in hand.
This one is in almost every set, because almost every compiler question ends up
being an HA question.

---

## THE RULE

**Never answer an HA question from memory, and never from another document.
Ask Home Assistant.** Your training data is older than the HA the user runs,
`HA_LIMITATIONS.md` is unaudited, and this file's own answers are dated for
exactly that reason.

The cost of asking is about a minute. The cost of guessing has been, on
separate occasions: a carbon-monoxide alarm that compiled to an automation
which announced nothing, four night-lights that HA silently disabled, and a
piston that woke a household at 5:20am on Saturdays.

## ASK THE RIGHT QUESTION

> **WRONG: "can HA do what webCoRE does here?"**
> **RIGHT: "what does the user want to happen, and how does HA say that?"**

The wrong question is the transcoder's, and it only ever produces walls.
`HA_LIMITATIONS.md` is what that question produces at scale — it was written by
Claude, for Claude, from the wrong starting point, and Jeremy (2026-08-22)
*"would not necessarily know good from bad"* in it. **Treat every entry there
as an unverified LEAD, never as a fact.** Some are certainly still valid; none
has been checked. If you use one, verify it by the method below and move the
verified answer into the table at the bottom of this file.

The right question has an answer that stays true, and it usually turns out HA
has a native way that is *shorter* than the translation. Worked example: a
webCoRE loop that walks detectors and appends each alarming one to a string
became a single HA template — no loop, no accumulator, no helper — and it
announced *sooner* than the loop did.

## THE FOUR MOVES, cheapest first

### 1. Ask the template API (seconds — do this first, always)

Any Jinja question — does this function exist, what does it return, what shape
is that value:

```bash
curl -s -X POST -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{"template":"{{ device_name(\"sensor.x\") }} | {{ states[\"sensor.x\"].last_reported }}"}' \
  http://localhost:8124/api/template
```

This answered, in one afternoon: that `device_name()` exists and `device_id()`
returns a hex id; that `last_reported` and `last_changed` are 14 hours apart on
a healthy battery; and that `selectattr('state','is_number')` drops a
non-existent entity for free.

### 2. Drive a real device (the only thing that proves BEHAVIOUR)

"It compiled", "it routed", "HA accepted it" are not behaviour. Build the
device, deploy, fire the trigger, read the result.

Build devices through PistonCore's factory using its **built-in types** —
hand-written entity lists get the platform wrong (a fan created as a light, a
binary sensor under the sensor platform) and that has cost half a day.

```bash
curl -X POST .../api/test-devices/setup
curl -X POST .../api/test-devices/create -d '{"type":"...","name":"..."}'
curl .../api/test-devices/debug-library     # what types exist
```

Driving them: binary sensors use `virtual.turn_on` / `virtual.turn_off`.
**`virtual.set` is the SENSOR service** and 500s with a misleading
"entity not found" that reads like the device is missing.

Reading a probe script's output: `system_log.write` then `GET /api/error_log`.
`persistent_notification.create` did not surface reliably.

### 3. Read HA's own source, or an integration that already solves it

When the question is "what does HA consider the normal way to do this", find
something in HA that already does it. Jeremy's steer that produced the best
result all afternoon: *"look at how the alarm panels handle it."* An alarm
panel takes a LIST of sensors and asks the set which are tripped — it does not
loop. That reframed the whole emission.

Blueprints and the official docs' tutorials count too — HA's own battery-alert
tutorial is where the `namespace`/`for`/`join` shape in `accumulate.j2` came
from, and it is cited in that file.

### 4. Ask the user — LAST, and only for what is genuinely his

He does not code and is newer to HA than to webCoRE. **A question HA's source,
the bench, or the groovy can answer is not his** — handing it over converts
work into a blocker. What IS his: what he wants the product to DO, and
trade-offs a user would notice.

## THE TRAPS THAT MAKE A WRONG ANSWER LOOK RIGHT

- **One device hides bugs.** The synthetic test map fabricates ONE device per
  reference, which makes "the first device" and "the correct device" the same
  thing. A loop whose condition was pinned to the first device passed every
  synthetic check and went silent on a real second detector. **Use two or more
  real devices, and make the one that matters NOT be the first.**
- **"Nothing happened" is not evidence.** For any "it must NOT happen" test,
  run the same rig with the condition inverted and prove it DOES happen.
- **The bench clock is UTC and the host is not** (6 hours apart, measured). A
  time trigger computed from the host clock lands in the past, never fires, and
  the test "passes". Get HA's time from
  `POST /api/template {"template":"{{ now().isoformat() }}"}`.
- **A dead entity looks like a compiler bug.** Check the entity is actually
  alive before concluding anything — a heavily-used bench fills with
  `unavailable` registry rows that respond to nothing.
- **Check the port is yours.** A failed bind still gets a 200 from whatever
  else is listening, and you read another app's answer as your result.
- **Check the HA version matches what the user runs.** Verifying on an older
  HA than his proves nothing about his install.

## WHEN YOU FIND AN ANSWER, IT LANDS HERE

Add a row below: the question in plain words, the working expression, and the
date. Each row costs ~20 minutes of bench work and takes ten seconds to read —
that difference is the entire point of this file, and it is what stops the next
session paying for it again.

Only **bench-verified** answers. Not a spec, not a translation table. The vocab
maps webCoRE's words to HA; this holds the things webCoRE has no word for.

## VERIFIED ANSWERS

| the question | HA's answer | verified |
|---|---|---|
| which of these are tripped / match | `expand(list) \| selectattr('state','eq','on') \| map(attribute='entity_id') \| map('device_name') \| join(', ')` — filter the SET, no loop | 2026-08-22, 3 real detectors |
| when did this device last check in | `states[e].last_reported`. **Never `last_changed`**, which only moves when the VALUE changes | 2026-08-22, battery steady at 17%: last_changed 14h, last_reported 36s |
| skip devices that cannot answer | `selectattr('state','is_number')` — fail-closed and free; an absent entity is simply not in the list | 2026-08-22, 3 in / 2 out, no phantom row |
| the DEVICE's name, not the entity's | `device_name(entity_id)`. `device_id()` returns a hex id — that is the trap | 2026-08-22 |
| does a variable accumulate across `repeat` iterations | **yes** — `START+one+two+three` | 2026-08-22 |
| a templated `entity_id` on `condition: state` | **NO.** Inside a loop the test must be `condition: template` | 2026-08-22, both directions |
| do several sensors need a loop at all | **no.** Trigger on ANY of them and rebuild from current state — a newly-tripped sensor re-triggers, so it announces sooner than a repeat loop | 2026-08-22 |
| "do this to every one of these" | `repeat: for_each:` — items may be **dicts**, so one iteration can carry several of a device's entities (`repeat.item.battery`) | 2026-08-22 |
| create a helper entity from the API | **you cannot** — `/api/config/input_boolean/config/<id>` is 404. Write a YAML package file, then call `<domain>.reload` | 2026-08-03 |

## WHAT THIS FILE DOES NOT COVER

The compiler's own structure, the variable lifetime decision, the recognised
piston patterns, and what a piston creates inside HA. Those are separate help
files. Standing decisions are in `HARD_RULES.md`; the open work list is in
`COMPILER_TODO.md`. This file never restates either.

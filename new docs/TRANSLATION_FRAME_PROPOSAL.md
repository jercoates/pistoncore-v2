# TRANSLATION FRAME — PROPOSAL, AND HOW IT LINES UP WITH THE CODE

**DRAFT for Jeremy's review.** From the chat of 2026-10-25. Code references are
VERIFIED against the public repo at commit `2fe3c03` (2026-09-03) only. Anything
done locally or since then is not reflected here.

This is a frame for the open question in HARD_RULES §2a ("i know they are patterns
but how to use them is the question"). It is not a ruling and not a design spec.

---

## 1. THE IDEA IN ONE PARAGRAPH

Don't map webCoRE to HA directly; that's the transcoder. Map **both** to one short
list of questions about behaviour. A webCoRE form fills in some answers. An HA idiom
needs certain answers before it applies. A **pattern** is just a combination of
answers that has been shown, on the bench, to compile to a given HA idiom and do what
the piston meant. The catalog only ever records proven matches; nobody writes a
pattern ahead of time.

## 2. THE QUESTIONS

| question | what it asks |
|---|---|
| WHEN | which devices, which attribute, **edge or state** (§2e), any or all |
| ONLY IF | gates and restrictions |
| DO | what happens to which devices, with what values |
| AFTER | waits, timeouts, "stays for" |
| ON RE-FIRE | if it fires again mid-run: cancel, restart, queue or ignore |
| REPEAT / UNTIL | loops and their exit condition (the CO-inversion trap, §12b) |
| ORDER | what must happen before what (§10) |
| REMEMBER | does a value outlive the run, or cross to another statement? |

**Nesting:** the questions apply at every level, not just the top. A nested block
inherits its parent's answers and adds its own. An answer always carries WHERE it
sits, so a wait inside a loop is a different fact from a wait after it. A pattern
therefore matches a small tree of answers, not a flat list.

**The whole piston:** a piston is its blocks PLUS the links between them. Block A
sets a flag that block B reads; A must run before B. Those links are part of the
intent and have to be recorded explicitly, or a split piston loses its connections
(§10, §10b).

## 3. HOW THIS LINES UP WITH WHAT EXISTS (as of `2fe3c03`)

Most of the questions are already carried. `shim/compiler/spec.py` describes itself
almost word for word as this frame: *"what wakes it · what must hold · what happens to
which devices · with what values · after what delay · how often · in what order"*.

| question | where it lives now | status |
|---|---|---|
| WHEN | `Promise.wakes_on`, `Block.wakes` | carried |
| ONLY IF | `Promise.gated_by`, `Block.gate`, `Block.restrictions` | carried |
| DO | `Promise.command / devices / values / params` | carried |
| AFTER | `Promise.after` | carried |
| ON RE-FIRE | `_cancel_pending()` → `cancel_pending` on the tree reader | **carried on the tree, not on the flat promises emission uses** |
| REPEAT / UNTIL | `Promise.loop` `{id, until, cadence}` | carried; the until-inversion is the open §12b hazard |
| ORDER | `Promise.order` | carried |
| REMEMBER | `Promise.writes / reads`, "the thread between statements" | carried; used by `report_groups` |
| nesting | `spec.read_tree()` → `Block` tree, "nothing is copied downward" | **built, but only `test_intent_probe.py` uses it** |
| links between blocks | writes/reads per promise | partial: shared variables, nothing else |
| choosing the HA idiom | `emit_intent.plan()` and its helpers (`daily_time`, `set_questions`, `report_groups`) | **hand-written code, not a catalog** |

### The three real gaps this exposes

1. **Emission reads the flat list, not the tree.** `emit_intent.plan()` starts from
   `spec.read(piston)`, the flat promise list. The tree reader that keeps nesting
   (and that `spec.py`'s own `Block` docstring says previous attempts lacked) exists
   but isn't wired into emission. That matches your point that it's "breaking down
   sections, not the whole." **Check whether this changed after September 3 before
   acting on it.**
2. **ON RE-FIRE never reaches emission.** It's read on the tree, and the tree isn't
   used. This is exactly webCoRE's task cancellation policy vs HA's `mode:`, the
   thing that decides one notification vs several. (Also note the `tcp` "Never"
   misread flagged inside `_cancel_pending()`.)
3. **The patterns are code, not data.** Each idiom `plan()` knows is a function.
   Under HARD_RULES §8 (nothing that tracks HA is hard-coded), the idiom choice
   belongs in an editable table, keyed by combinations of answers.

## 4. WHAT A CATALOG ENTRY WOULD LOOK LIKE

```
pattern:   motion light with a re-arming timeout
answers:   WHEN motion changes to active (any of)
           DO light on
           AFTER motion inactive N, DO light off
           ON RE-FIRE restart the pending off
HA idiom:  state trigger + wait_for_trigger (for: N) + mode: restart
proven:    <piston>, bench, <date>, device-driven (§7)
```

Entries are added only after a device test passes (§7, §17). A combination with no
proven entry falls through to the transcoder or PyScript, exactly as `plan()`
returning None does today. So the catalog can grow one entry at a time without ever
making anything worse (§12b's reasoning).

## 5. SUGGESTED FIRST STEPS (small, each checkable)

1. **Seed the catalog from pistons already device-proven:** CO alarm, low-battery
   report, door chime, `a03_Alarm_Not_Set`. For each, write its answers to the §2
   questions (tree form, with links) and the HA idiom that worked. Gaps in those write-
   ups show which questions are missing.
2. **Check gap 1:** does emission use the tree yet? If not, what would it take for
   `plan()` to read `read_tree()` instead of `read()`?
3. **Check gap 2:** carry `cancel_pending` into what emission reads, and map it to
   `mode:`. Device-test it with a double trigger, counting the virtual notifier.
4. **Maintenance test** (the selling point): deploy a piston using a device global,
   swap a test device in that global, accept the recompile, fire again, and confirm
   the new device acts and the old one doesn't.

## 6. HOW TO TELL IF IT'S PUSHING CLOSER

Not by output matching (§2c). By:
- more pistons on the intent path that pass all three of §17, on the bench
- `python test_intent_probe.py --section maintainability` trending the right way (§2g)
- the PyScript band shrinking (§3)
- the fall-back reasons list getting shorter, one reason at a time (§12b)

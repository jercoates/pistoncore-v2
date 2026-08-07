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

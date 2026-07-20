# Whole-project review prompt

Paste the block below into a fresh chat (VS Code chat, a cheap model is fine —
this is reading and judging, not building) to get a project-wide review.

**Why it's worth keeping:** an untargeted "review my project" gets you generic
advice that contradicts this project's own rules — suggestions to add a
frontend framework, to "improve" the sealed dashboard, to have the compiler
tidy up piston JSON. Pointing the reviewer at the authority chain FIRST is what
makes the findings usable.

**Track record:** the 2026-07-19 run using this prompt correctly flagged the
JSON stores as a structural risk. Investigating that found a worse bug than
reported — non-atomic writes plus intolerant reads meant one truncated file
bricked the whole app (fixed the same day: atomic writes + corruption
quarantine). It also correctly found no spec drift and no rule violations.

**Use it when:** after a big session, before a release, or when you want an
outside opinion without spending premium tokens. It is deliberately a
READ-ONLY review — the "do not write code, do not propose features"
constraint keeps a review session from drifting into building things.

---

```
Review the PistonCore v2 project as a whole. Read these first, in order —
they are the authority chain and they override any general best practice:

  1. CLAUDE.md  (project rules — sealed dashboard, UI split, no frameworks,
     read-only compiler, the piston JSON is law)
  2. COMPILER_DECISIONS_HOLDING.md  (session status notes at the top —
     current state of both compiler bands, decisions with who/when)
  3. SHIM_API_SPEC.md, DEVICE_PAYLOAD_SPEC.md, PISTON_JSON_REFERENCE.md,
     COMPILER_SPEC.md, COMPILER_DECISIONS_DEPLOY.md
  4. The open session briefs: SESSION_BRIEF_YAML_BAND_EXPANSION.md and
     anything else at the repo root named SESSION_BRIEF_*

Then review the code against them and report:

  A. DRIFT — anywhere code contradicts a spec. The spec wins; list the file,
     the rule it breaks, and the smallest fix.
  B. RULE VIOLATIONS — specifically: anything writing into piston JSON, any
     device id or hash reachable by a UI surface, edits under dashboard/
     beyond the SHIM_API_SPEC §9 neutralizations, any third place compile
     errors announce themselves, any frontend framework or build step.
  C. STRUCTURAL RISK — duplicated logic, things that will break on the next
     Home Assistant or webCoRE change, error paths that can fail silently,
     anything where a failure would be invisible to the user.
  D. DEAD OR STALE — code, docs or data files that no longer match reality.
  E. TEST GAPS — behaviour that would break without any test failing.
     (Existing: test_compile_fixtures.py, and a corpus of ~98 real pistons
     under test-pistons/ used as the acceptance measure.)

Rules for you: do not write or change code. Do not propose new features.
Rank findings by real user impact, not by tidiness. For each finding give
file:line, why it matters, and the smallest change that fixes it. If
something looks wrong but you can't verify it from the sources, say so
rather than guessing.
```

---

## Variants worth having

**Narrow it to one area** — replace the "Then review the code against them"
paragraph with one of these:

- *Compiler only:* "Review only shim/compiler/ and templates/compiler/. The
  acceptance measure is test-pistons/ (~98 real pistons); the goal is that
  every piston compiles to a NATIVE HA automation, with PyScript as the
  fallback, not the plan."
- *Shim/API only:* "Review only shim/routes/ and shim/*.py against
  SHIM_API_SPEC.md and DEVICE_PAYLOAD_SPEC.md. The vendored dashboard is the
  client and cannot be changed — the shim must fit it, never the reverse."
- *UI only:* "Review only templates/ and static/pistoncore/ against CLAUDE.md's
  UI split. Check that compile errors appear on exactly two surfaces, that no
  device id or hash can render, and that no page needs a build step."

**After a specific session** — add at the end: "Focus on what changed in the
last commit; treat everything older as already reviewed."

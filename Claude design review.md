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
PistonCore Design System (design system)
This project doesn't contain the codebase you're describing — no CLAUDE.md, compiler specs, session briefs, dashboard/, or test-pistons/ corpus. All I have is a design-system-bound single-page project (PistonCore V2 Main Page.dc.html, the design system bundle, and two uploads: front_door.js and a pasted screenshot).

I can't review architecture, compiler bands, or the piston JSON contract that don't exist here. If that codebase lives in another project or repo, point me to it (a project path or GitHub link) and I'll do the authority-chain review as specified.

how do i change folder access
PistonCore Design System (design system)
Folder access isn't something I control from inside a design conversation — it's a project/workspace permissions setting in the app around this chat, not part of the file tools I have here.

Check the project settings menu (usually near the project title or a share/collaborators icon) for access or sharing controls. If you don't see one, let me know what you're trying to accomplish (share with someone, connect a local folder, etc.) and I can point you to the right feature name.

i want to give you acess to my files
Two options:

GitHub repo — paste the github.com URL for the repo and I'll pull the files directly.
Local folder — if there's an attach/connect option in your message box for a local folder, use that; it'll expose local_* tools to me here.
Which do you have — GitHub or local folder?
# SESSION BRIEF — Post-review fixes: Speak first, virtual devices, save-flow checks

Source: external review (Grok) + Jeremy/Fable5 session, 2026-07-10. Standard rules apply
(CLAUDE.md): plan first with a hard stop before code, no new files without approval,
behavioral verification instructions at the end of every change.

## Priority order (Jeremy)
1. Speak — used constantly; must feed the editor correctly. FIX NOW.
2. webCoRE built-in virtual devices (Time / Date & Time / Location Mode) — used in almost
   every real piston. FIX SOON (this session if it fits).
3. Save-flow verification items — cheap checks, do alongside.
4. Notify — DO NOT BUILD YET. Blocked on Jeremy setting up a phone on the test HA and on
   the C2/C2b target-mapping decision. The design data already exists
   (NOTIFY_ACTION_SPEC.md + COMPILER_DECISIONS_HOLDING.md C1/C2/C2b) — read, don't
   implement.

## 1. Speak (priority fix)

Goal: a speak-capable media_player offers Speak-type tasks in the editor; a non-capable
one doesn't; the TTS engine setting has real data behind it.

a) **Author-time gate:** verify the Stage 3.3 command-only lane actually fires for
   media_player + PLAY_MEDIA `supported_features` bit → speech capability set
   (DEVICE_PAYLOAD_SPEC Stage 3.3; COMPILER_DECISIONS_HOLDING B6). If the lane exists but
   the media_player rule isn't wired, wire it. Data-driven per the spec — rule lives in
   the map file(s), not Python.
b) **tts.* enumeration (confirmed missing — Grok + B6):** ha_client currently doesn't
   enumerate `tts.*` entities. Add it: tts engines are NOT devices (never in the device
   payload); they feed the global default-TTS-engine setting the compiler will read.
   Store/serve however fits the existing settings storage; propose placement in the plan.
c) **Behavioral test (Jeremy will click):** a known speech-capable media_player (e.g.
   a ReSpeaker satellite / Piper-backed player) shows Speak commands in the task dialog;
   a media_player without PLAY_MEDIA does not; sensors never do.

## 2. webCoRE built-in virtual devices (Time / Date & Time / Location Mode)

These are the editor's built-in pseudo-devices powering time-based conditions ("time is
between", "every day at"). Currently `instance.virtualDevices` is served as `{}` so they
likely don't appear at all.

a) Serve the definitions: `webcore_vocab.json` has a `virtualDevices` section — this is
   the seed. Cross-check the expected entry shape against the Hubitat reference groovy
   (`reference/webCoRE-hubitat-patches-extracted/.../webcore.groovy` — look for how
   virtual devices are listed/served) before serving; tag findings VERIFIED-HE-GROOVY in
   the spec.
b) Populate `instance.virtualDevices` with the standard set (stock behavior ≈ standard
   set enabled). Determine from source whether definitions belong in the db payload, the
   instance, or both.
c) Location Mode needs real data: wire `location.mode` (hashed id) + `location.modes`
   to actual HA source per SHIM_API_SPEC §5.3 — this also fixes the "(unknown)" hexagon
   tiles on the dashboard main page. If Jeremy hasn't designated an HA modes source yet,
   STOP and ask him which entity to use rather than inventing one.
d) NO live feed needed for Time/Date — the dashboard uses the clock at render time;
   runtime matching is a compiler problem, out of scope.
e) **Behavioral test:** new condition → the compare picker offers Time / Date & Time /
   Location Mode; a "time is between X and Y" condition builds, saves, reopens correctly.
   Jeremy should keep this piston — it exercises the `v` operand path for the acceptance
   test.

## 3. Save-flow verification (cheap, do alongside)

a) **`$` id assignment:** confirm the save path implements PISTON_JSON_REFERENCE §8 —
   walk the piston on save, assign incremental `$` ids to nodes missing one AND to
   duplicate ids (the Hubitat-verified nuance); never renumber valid existing ids. If not
   implemented, implement — this is a MUST before the acceptance test, or every capture
   will be id-less.
b) **Resolution-map persistence:** confirm the hash ↔ entity binding map survives a shim
   restart (rebuild-on-start from HA is fine — it's specced as a rebuildable cache; just
   verify it actually rebuilds). Foreign/unknown hashes must produce a clear error, never
   a silent skip.
c) **Phantom device fields:** remove the unused `o`/`an` keys from physical device
   objects (mining session confirmed real devices carry exactly n/cn/a/c — SHIM_API_SPEC
   §5.1 was corrected).

## 4. Read-only notes (no action this session)
- Notify: the plumbing this session must NOT add — service-registry fetch and target
  mapping wait for the C2b translation-file design + Jeremy's phone on test HA.
- PISTON_JSON_REFERENCE gets a notify-task-params section only after C2b is decided
  (noted there as pending).
- Compile targets: YAML-native is the primary path, PyScript is the forced exception per
  the routing table (holding doc §E) — if any code comment or doc line reads
  PyScript-forward, fix the wording when touching that file anyway.
- HA_LIMITATIONS.md still needs carrying over from the v1 repo (Jeremy's task); the db
  pruning pass against it is a future session.

## End-of-session output
Plain-language summary in behavior terms: what Jeremy should click for Speak, for time
conditions, and confirmation of the three save-flow checks (implemented / already fine /
deferred with reason). Update spec TO VERIFY tags for anything this session verifies.

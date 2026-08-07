# Handoff — 2026-08-06

Written at the end of the 2026-08-05 session. **Facts and their evidence only.**
Where something was not verified, it says so. Do not treat anything here as a
conclusion unless it names how it was checked.

## State

- Working tree **clean**, everything committed and pushed. HEAD = `781edaa`.
- `python test_compile_snapshots.py` → **84 compiled, 0 errored, 71 yaml / 13
  pyscript, NO DRIFT.**
- `python test_intent_probe.py` → comparison collisions **1** (`changed ==
  is_any`, yaml band). Commands failing on both bands **40 of 137**.

## What landed this session (newest first)

| commit | what | how it was verified |
|---|---|---|
| `781edaa` | Raw HA attributes typed from HA instead of guessed; new `ha_device_classes.json` | 219 real devices: 154 → datetime, 27 → enum, 1 → integer, 27 gained a value list, 0 enums left without values. Compile harness unchanged. |
| `346d8aa` | Corrected an overstated claim in COMPILER_TODO.md | — |
| `1d9ecbb` | `picker_capability_map.json` folded into the vocab as `_picker_rules`; file deleted | `domains` block byte-identical to the deleted file; device payload identical across 219 devices / 1705 attributes incl. types and bindings |
| `80a7f49` | System variables into the vocab; two hardcoded per-band tables deleted; `webcore_system_vars.json` deleted | move proved byte-identical BEFORE any semantic change; then 3 real per-band mismatches fixed (`$hour`, `$dayOfWeek`, `$currentEventDevice`) |
| `6043954` | `pausePiston`/`resumePiston` compile on PyScript; shared lookup in `resolve.py` | both bands emit equivalent targeting; 13 PyScript pistons parse |
| `0e2504b` | `setHue`/`setSaturation` preserve the other half | both bands, both commands; PyScript previously emitted a bare number where HA needs a pair |

Earlier in the same session: `remains_*` quarantine + throttle, the same fix for
the range/parity families, `was_*` given real duration semantics on both bands,
piston-level restrictions on PyScript, fade commands, one duration converter.
All are recorded with their evidence in `COMPILER_TODO.md`.

## Verification tools

- **`test_compile_snapshots.py`** — the golden snapshot for compiler output. Run
  before and after any change; `--update` re-records. Re-recording is a
  deliberate step: say what changed and why.
- **`test_intent_probe.py`** — walks the vocabulary rather than the corpus.
  Finds things no piston exercises. Every collision fixed this session was found
  here, not by a failing piston.
- **Device-payload harness — NOT IN THE REPO.** It was built in the session
  scratchpad (`payload_snap.py` + registry snapshots pulled from the dev bench
  and the test HA) because a registry snapshot contains real device and room
  names. That directory is session-scoped temp and **is probably gone**. To
  redo it: fetch registries exactly as `shim/ha_client.fetch_registries` does,
  call `device_pipeline.build_device_payload`, and snapshot the full device
  objects plus the resolution map — not just attribute names, which was a real
  weakness in the first version.
- PyScript output is text, so the compile harness cannot catch a syntax error in
  it. Parse the emitted code with `ast.parse` as a separate check.

## Open, with what is and isn't known

Everything is written up in `COMPILER_TODO.md`. The largest items:

- **40 of 137 commands compile on neither band.** The list is in the probe
  output. Not analysed as a group.
- **60 of 99 system variables have no HA expression.** They are all in
  `webcore_vocab.json` `systemVariables`; adding one is a vocab edit, no code.
  Unimplemented ones carry a research `ha_lead` that is **not wired up**.
- **`_picker_rules` and the per-attribute `ha` arrays state the domain
  condition twice.** MEASURED: 17 domains appear in both, 13 differ. **No
  ruling has been made on any of the 13** — either side may be the loose one; a
  real Sonos shows `volume` (webCoRE's own name) from the picker rules while the
  vocab maps `level` → media_player. webCoRE's own naming is the authority.
- **`remains_*` advisory is not surfaced.** The throttle exists; nothing tells a
  user their piston wakes on every update.
- **Throttle interval is hardcoded** (`_NOISY_THROTTLE`, 1s) and was promised as
  a Settings knob.
- **`smartDetectType` dropdown** — discussed, not built. HA publishes no options
  for it on Jeremy's BRIDGED cameras (verified: `device_class=None`,
  `options=None`). **UNVERIFIED:** whether a native HA UniFi Protect integration
  publishes options for the equivalent sensor — Jeremy believes it does. If a
  vocab entry is added, the real value list should come from a live instance,
  not be invented.

## Constraints stated by Jeremy this session

- **Never leave dead code.** Two orphans were left mid-session by my own
  refactors and removed. Grep every symbol touched before reporting done; a
  reference count of 1 means definition only. Note that a caller can now live in
  the vocab, so include the JSON in that grep.
- **`/help/limitations`** (`templates/help_limitations.html`) is where every HA
  fidelity gap lands, in the same change that finds it. `HA_LIMITATIONS.md` is
  the separate ENGINEERING reference — "ha limitations is for coding not a help
  file". Do not merge them.
- **File-split rule, applied by Jeremy 2026-08-05:** split by *why something
  changes*. The vocab changes when HA RENAMES something and webCoRE's own side
  is frozen. `ha_device_classes.json` changes when HA ADDS a device class — a
  faster, growing clock — so it is its own file. `routing_table.json` changes
  when HA GAINS an ability. Lookup tables go in JSON, never templates, because
  templates cannot be safely overlay-merged onto an existing install.
- **The hybrid is deliberate.** The vocab curates common attributes for a clean
  editor and a working import path from other hubs; HA feeds everything else in
  raw. MEASURED: 759 of 1500 attributes on the test HA arrive raw. Absence from
  the vocab is the NORMAL case, never "unavailable".

## Process notes for whoever picks this up

Three times this session I started building something that already existed or
was already solved — `pausePiston` (fully implemented, including the
multi-automation case I spent a while re-deriving), a markdown help file when
PistonCore has a help system, and a duplicate table. **Grep before analysing,
not after.** CLAUDE.md's search-before-you-write rule is there because of this
exact failure mode.

Two findings of mine dissolved once Jeremy explained intent — "not selectable"
(wrong; the raw feed covers it) and the picker map being "the unfinished half of
the one-source decision" (wrong; it was never in that scope). Both times the
tell was measuring before understanding what was being measured.

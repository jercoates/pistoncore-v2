# RECONCILIATION — load-bearing decisions vs. actual code

**Why this exists (Jeremy, 2026-07-20):** the compiler was spec'd heavily, then
a context-overload episode had an implementation pass drop the YAML-first rule
and forget helpers; it was correction-coded back. That left an honest gap
between "what I designed" and "what's actually running." This doc closes it —
each locked decision checked against the CURRENT code with file:line evidence,
verified-with-source style. Re-run this check after any future context-overload
episode; it converts "I don't know where it landed" into a finite list.

**Verified 2026-07-20 against the working tree.** Every item below was read in
the code, not remembered.

## The load-bearing rules — all CONFIRMED

| # | Locked decision | State | Evidence |
|---|---|---|---|
| 1 | **YAML-first is the default emit path.** PyScript is the routed exception, not the primary. | ✅ CONFIRMED, and now decisively true | `shim/compiler/__init__.py` `compile_piston`: band "auto" = routing table → **YAML first** → fall through to PyScript only on `NotYetImplemented`. Real-piston corpus (98): **62 automations + 11 scripts native / 5 PyScript**. YAML-first is not just intact — it's dominant. |
| 2 | **Location mode → an `input_select` helper**, auto-created. | ✅ CONFIRMED | `shim/fixtures.py:38,81` `input_select.pistoncore_location_mode`, `create_input_select`; compiler reads it as `MODE_ENTITY`. |
| 3 | **Alarm/HSM status → `alarm_control_panel`**, bound only when unambiguous. | ✅ CONFIRMED | `shim/device_pipeline.py:577-579` binds `alarmSystemStatus` only when exactly ONE panel exists; `setAlarmSystemStatus` compiles to `alarm_control_panel.*` on both bands. |
| 4 | **Reverse resolution consults entity context** (not a blind name map). | ✅ CONFIRMED | `shim/compiler/resolve.py`: `$system` entity map + per-device `attr_bindings`/`cmd_bindings` from the device pipeline; unresolved devices are KEPT (A1 ruling), remembered across HA outages. |
| 5 | **Devices GROUPED, one per HA device_id; multi-name keys disambiguated by entity.** | ✅ CONFIRMED | `shim/device_pipeline.py`: one device per registry `device_id`; first contributor (entity_id sort) wins a shared attribute/command slot, never split. |
| 6 | **Compiler knowledge is EDITABLE DATA, additive-only, no hardcoded strings.** | ✅ CONFIRMED (and hardened 2026-07-20) | Maps + both bands' templates + routing table + vocab load via `shim/customize.py` from the `/data` volume, seeded from the image, live-editable, per-file fallback. Was image-baked; fixed this session. COMPILER_SPEC §1a locks it with a regression guard. |
| 7 | **PyScript over-built during recovery — is it a peer or did it become primary?** | ✅ PEER, not primary | The band split answers it: YAML/script win 73/98, PyScript takes 5. The PyScript path is capable (good for the forced-PyScript trace toggle), but it is the exception in practice, not the default. The recovery's over-build did NOT come at the YAML path's expense. |

**Bottom line:** the correction-coding worked. Every rule a context overload
is known to drop is present and, in the YAML-first case, stronger than before.
Nothing on this list is drifted. You are not building on a cracked foundation.

## Roadmap position (his "after compiler → virtual devices → trace")

| Stage | State |
|---|---|
| **Debug/help screen** — link on errors + from Settings | ✅ BUILT. `/diagnostics` (Settings → Diagnostics button) + the piston-status error banner links to `/help/compiler-debug`. Drill-in only, never a third announcement surface. |
| **Compiler (YAML + PyScript bands)** | ✅ BUILT. 73/98 real pistons native, 0 crashes, fixtures + regression green. Remaining gaps are named data-file additions (device commands) + the deprecation-scanner brief. |
| **Virtual devices for testing** | ⏳ STUB. `/test-devices` returns a "not built yet" page (`shim/routes/pages.py:101`). This is the next build — and the strongest one, because behavioral testing against faithful twins is exactly what surfaces any remaining spec-drift. |
| **Trace / activity console** | 📋 SPEC-READY, not built. `TRACE_ACTIVITY_CONTRACT.md` is Draft 2 — every data shape verified with citations. Cheap implementation session; its default-vs-forced behavior assumes YAML-primary, which item #1 confirms holds. |

## The reframe worth keeping

The gap was never in the code — it does a lot right and this check proves the
load-bearing rules survived. The gap was in KNOWING where it landed, and that
is answered by reading, not remembering. Two things guard against the next
context-overload episode: this doc (re-check the table), and the
virtual-device behavioral pass (a piston that should fire but doesn't is
spec-drift made visible). Do the behavioral pass before stacking trace on top,
and the reconciliation keeps paying off.

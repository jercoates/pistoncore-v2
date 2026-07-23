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
| **Virtual devices for testing** | ✅ BUILT (2026-07-22/23, supersedes the STUB entry). `/test-devices` serves the real page (`shim/routes/pages.py:107`). Forked `twrecked/hass-virtual` at `test-devices-integration/custom_components/virtual/` (FORK_NOTES.md records provenance), added platforms alarm_control_panel/climate/media_player/siren/humidifier/vacuum/button/event, `pistoncore_manage` create/remove services, gated installer + updater, a searchable clone list (real-device twins) and the 67-capability debug library for device types the user does NOT own. Spec: `VIRTUAL_DEVICES_SPEC.md` (through §5.8). |
| **Trace / activity console** | ⏳ PARTIALLY BUILT (2026-07-22). Steps 1+3 done: `intf/dashboard/piston/activity` is implemented (was a 404) and returns live state + `lastExecuted` — PyScript `_state` entity, YAML band's `last_triggered`. **Still to build:** step 4 logs and step 5 the per-statement trace overlay. Contract: `TRACE_ACTIVITY_CONTRACT.md` (Draft 2). |

## Second pass — 2026-07-23 (what landed since the 07-20 check)

| Change | State | Evidence |
|---|---|---|
| **`else` on a promoted condition now fires** | ✅ FIXED + verified | A condition promoted to a directional wake (`below:N` / `to:X`) only woke on ONE transition, so the else could never run — light turned on when dark, never off when bright. `emit_yaml.py` `_emit_branch` now tracks a `promoted` flag and emits the OPPOSITE-direction companion: numeric `below:N`→`above:N`, state `to:X`→`from:X`. Covers every sensor attribute and every equality condition, not just lights. **Level of the fix is the compiler, never a hand-written second `if`** (Jeremy: that defeats the purpose of `else`). |
| **Media file playback (Play track)** | ✅ BUILT (SMB read untested vs a live share) | Routing is **per URL, by format — never a mode toggle** (Jeremy, firm: "all or none is not a good choice"). `/local/…`, `http(s)://`, `media-source://` pass through to HA natively; `x-file-cifs://` / `smb://` flags an old-school Hubitat path and streams through PistonCore's media server. `emit_yaml.py` `_rewrite_media_url`; endpoint `pages.py` `/media/proxy` (HMAC-signed so it is not an open relay, host/share/path parsed **from the URL itself** — no share is ever configured by hand); PistonCore's own address is auto-captured from the browser Host header (`_capture_media_base`). Trade-off recorded: share files play only while PistonCore runs. Help: `/help/media-files`. |
| **Expression function coverage** | ✅ 51/109 → 93/109 | Coverage audit found 58 webCoRE functions implemented in NEITHER band (hard fail, not a PyScript fallback). 42 added to `expr_runtime.py.j2` + `_FUNCTIONS`. |
| **Settings/first-run parity** | ✅ RULE + verified | **HARD RULE (Jeremy):** every setting in first-run must also be editable on the Settings page, same store. Sole exception: the HA-config **write permission** (a one-time consent action, not a stored value). Audited: all nine first-run settings present in `settings.html`. |
| **Help is now searchable** | ✅ BUILT | `help_index.html` has a search box filtering title/summary/`data-keywords`; new article `/help/media-files`. Intended to grow into a searchable help database. |

### Audit gaps found 2026-07-23 (logged, NOT yet fixed — Jeremy ruled "implement")

The `else` bug prompted a full coverage audit. Presence-checked against `webcore_vocab.json`:

| Axis | Covered | Gap |
|---|---|---|
| Functions | 93/109 | 6 group-H (ruled OUT: need history HA doesn't keep; workarounds die with PistonCore) + 10 ambiguous semantics (need real webCoRE source) |
| Comparisons | 76/79 | `does_not_drop`, `does_not_rise`, `stays_away_from_any_of` |
| Commands | 80/135 | **55 unmapped** — implement all except the SmartThings/platform group (`indicator*`, `lifx*`, `writeToFuelStream`, `storeMedia`, `setTileFooter`, `executeRoutine`, `iftttMaker`, `saveState*`/`loadState*`), which is documented as "does not work" |
| Statement types | 9/12 | **`on`** (on-events-do block), **`each`** (for-each device), **`break`** |

⚠️ **All four axes are PRESENCE checks, not correctness checks.** The `else` bug was a correctness bug that presence-checking cannot catch — a correctness spot-check of condition/trigger emission is still outstanding (starting with the known `≤`/`≥` boundary miss, where a value landing exactly on N wakes nothing).

## The reframe worth keeping

The gap was never in the code — it does a lot right and this check proves the
load-bearing rules survived. The gap was in KNOWING where it landed, and that
is answered by reading, not remembering. Two things guard against the next
context-overload episode: this doc (re-check the table), and the
virtual-device behavioral pass (a piston that should fire but doesn't is
spec-drift made visible). Do the behavioral pass before stacking trace on top,
and the reconciliation keeps paying off.

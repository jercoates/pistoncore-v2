# VERIFIED PISTONS

A piston is listed here ONLY after it has been driven end to end on real devices
through PistonCore — imported, bound, saved, compiled, deployed, the trigger
fired, and the result read back. Compiling is not verifying. A docstring or a
previous session's claim is not verifying.

**Why this file exists:** drift on a piston listed here is an ALARM. Drift on any
other piston is only blast radius. `test_compile_snapshots.py` reports both the
same way, which is why the distinction has to be written where a human can audit
it (Jeremy, 2026-08-29).

Started EMPTY on purpose. Nothing inherited from earlier claims.

| piston | verified | band | what was proven | not proven |
|---|---|---|---|---|
| `12_Cave_motion_V2` | 2026-08-29 | yaml | lux 250 + motion on the SECOND sensor turns the light ON; lux 5000 leaves it OFF; clearing motion turns it off after **125s** (asks 2 min) | — |
| `12_Cave_motion_V2` | 2026-10-12 | yaml | rebuilt bench, bound to virtual devices only. lux 250 + motion -> light ON; lux 5000 + motion -> stays OFF (control); motion clears -> still on at 90s, OFF by 135s (asks 2 min); **motion returning at 45s cancels the turn-off and the light stays on** -- same result as webCoRE's running wait, reached by HA's `for: 00:02:00` trigger instead | nothing outstanding |
| `25_Entry_Motion_V2` | 2026-08-29 | yaml | lux 200 + motion ON; lux 3000 stays OFF; off after **62s** (asks 1 min). Single sensor, `for:` on the entity not a group | — |
| `33_Hall_motion` | 2026-08-29 | yaml | lux 200 + motion ON; lux 3000 stays OFF; off after **301s** (asks 5 min). Own sensor, no cross-fire | — |
| `35_Kitchen_Motion` | 2026-08-29 | yaml | lux 200 + motion ON; lux 3000 stays OFF; off after **301s** (asks 5 min). Own sensor and light | — |
| `24_Entertainment_alarm` | 2026-08-29 | yaml | door opens: volume **0.25 -> 0.9** and the TTS clip carries the piston's exact words. Control: door shut, nothing moved | audible sound (virtual speaker); the `notify.send_message` leg |
| `41_New_Door___Window_chime` | 2026-08-29 | yaml | opening the **2nd** then the **4th** contact each spoke that sensor's own name; SSML stripped; night branch at 23:25 gave volume **0.7**. Control: closing a contact did not fire | the day branch (else, volume 0.9) — needs the time window moved on a throwaway copy |

| `38_Low_Battery_Check` | 2026-08-29 | yaml | smoke battery crossing below 80 fires the report; it lists only the detector that is low, names it with `device_name()` and carries the real value (`Smoke LR - 38%`), with the header on its own lines and the blank line intact. | the daily 16:30 door-battery branch (time trigger not reached); audible/push delivery beyond `notify.send_message` |
| `11_Carbon_Monoxide_detected` | 2026-08-29 | yaml | CO on the **3rd** detector: notification names it with its battery (`PC Kitchen Detector - 63%`), blank line intact; alert light on; speech names the detector; clearing fires the Cleared branch | audible sound; speech says "detected fromPC" — a missing space |
| `63_Smoke_Detected` | 2026-08-29 | yaml | smoke on the **2nd** detector: `PC Basement Smoke - 55%`, blank line intact, speech names it, Cleared branch fires | same missing space in speech |
| `70_Water_Leak_Notification_and_shutt_off` | 2026-08-29 | yaml | wetting the **2nd** leak sensor closed the valve (`switch.test_shuttoff_valve` on -> off), spoke naming that sensor, and notified | the `Water_Status` report text (a later notification overwrote it); the away/home branches |

## Not testable on this bench — device not available

| piston | why |
|---|---|
| `a77_Water_Leak_Detected_Repeat_60sec` | Albert's. Drives `@Sirens` with `strobe`, `siren`, `off`, `stop`. Jeremy has **no siren**: his Chime does the job but under a different command (Hubitat `Chime` capability, not `Alarm`). Confirmed 2026-08-29 by Jeremy after checking his devices. Removing `strobe` on a throwaway copy just moved the failure to `siren`, so it is the whole Alarm family, not one command. |

**Also relevant, and separate:** a Hubitat-BRIDGED siren does not arrive as HA's
`siren` domain. Jeremy's Chime, which on Hubitat has Alarm + Chime + AudioVolume,
comes across as `light.chime` + `switch.chime_alarm` plus read-only sensors
(`sensor.chime_volume`, `sensor.chime_sound_name`, `sensor.chime_status`). So
even with the right device, Alarm commands have nothing to bind to while it is
bridged, and volume/sound are read-only. Bridged-vs-native shape change, same
class as the UniFi cameras.

## Devices used

`Test — Bench Multi`, `Test — Bench Motion 2/3/4`, `Test — Bench Lux`,
`Test — Master Light`, `Test — Bathroom Light`, `Test — Porch Color`,
`Test — Bench Light 4`, `Test — Front Door`, `Test — Pauls door`,
`Test — Basement Window`, `Test — Master South Window`,
`Test — Family Room` (CLONE — the only speaker with `PLAY_MEDIA`).
Globals created for testing: `@Light_Sensor`; `@Speakers` repointed at the clone.

## What made these valid

- **Two devices where the piston has a group, and fire the one that is NOT first.**
  One device makes "the first" and "the correct" the same thing.
- **Run the control.** Every ON above is only meaningful because the same rig with
  the condition inverted did nothing.
- **Reset to a known state first.** A light already on reads as a pass.
- **Do not touch the piston mid-test.** Redeploying during a timing run reloads the
  automation and kills the pending wait — it cost two invalid runs.
- **Check the entities are alive.** After the add-on stranded the bench, every
  trigger fired into `unavailable` entities and nothing happened, which looks
  exactly like a compiler bug.

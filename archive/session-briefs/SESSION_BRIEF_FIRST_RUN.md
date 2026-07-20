# SESSION BRIEF — First-Run Setup Wizard

One-time session instructions (move to archive/session-briefs/ when executed).
Approved by Jeremy 2026-07-19. Does NOT need a top-tier model — this is
assembly of existing pieces behind a stepper UI.

## Goal

Replace "first run = Settings page with a welcome banner" with a guided
stepper at `/setup`, reached by the existing first-run redirect
(pages.py front_door: `is_configured()` false → currently /settings?first_run=1
→ becomes /setup). NOT a new settings store: every control the wizard shows
REMAINS in Settings, wizard is re-runnable from a Settings link ("Run setup
again"). Every step has a "do this later" skip. (Jeremy: "settings staying
in settings, things change.")

## Step 0 (silent) — deployment detection ladder

Run before showing anything; picks defaults, never final answers:
1. `SUPERVISOR_TOKEN` env present → HA ADD-ON: connection auto-configured
   (ha_client._load_auth already prefers it, http://supervisor/core). Step 1
   renders as "Connected as Home Assistant add-on ✓" (no URL/token inputs).
   Write mode preset local with the add-on mount path.
2. Else → Docker. After step 1 saves creds: sniff candidate local mounts for
   a configuration.yaml (read-only Test-Path style check — e.g. /ha-config,
   /config, /homeassistant, plus whatever ha_config_path is already set).
   Found → preset write mode local + detected path.
3. No mount found → preset SMB, host prefilled from the HA URL's hostname.

## Step 1 — HA connection

Existing fields (ha_url/ha_token, pages.py /api/settings). Verify with
ha_client.check_connection() before advancing; failure shows the error and
allows retry or skip. Add-on mode: auto-pass.

## Step 2 — write target + runtime checks

a. Write target (local/SMB per ladder defaults; same fields as Settings).
   GATE: the existing probe (/api/settings/test-write, write/read-back/
   delete). **The probe passing — not the mode choice — is what unlocks
   step 3.** (Jeremy's hole #1: config.yaml editing goes THROUGH the write
   target; consent before a working target = confusing plumbing failure.)
b. PyScript detection: websocket get_services → does domain "pyscript"
   exist? If NOT installed, show the limits notice honestly: pistons using
   formulas/expressions, switch/loops/variables, on-events, computed
   messages will not run until PyScript is installed (HACS); simple pistons
   compile to plain YAML regardless. Link to install instructions. Not a
   blocker — inform and continue.
c. Optional extras, skippable: TTS engine dropdown (exists), location-mode
   note.

## Step 3 — configuration.yaml consent

Existing analyze → show-exact-changes → consent-click → apply flow
(/api/config-yaml + /apply), locked until step 2a probe passed. After apply,
the existing reload prompt (/api/ha/reload-yaml) so HA actually loads the
include folders before the wizard ends. Skippable (Settings keeps the
button, existing pattern).

## Step 4 — finish

Link to a "best practices" help article (new page under /help — write it:
import order, globals population, pausing, what the status pills mean,
PyScript recommendation) OR "Start using PistonCore →" straight to the
front door.

## Rules that bind this session

- Vanilla JS/HTML/CSS + Jinja2, no framework (CLAUDE.md). Reuse
  settings.html field markup + settings.js patterns; style with existing
  tokens (row lists, never tiles).
- New files: templates/setup.html, static/pistoncore/setup.js, one help
  article template — name them to Jeremy before writing (house rule).
- No sealed-dashboard changes. No third error surface.
- Behavioral verification list at the end: fresh data dir → / redirects to
  /setup; add-on env var simulation skips step 1; bad SMB creds fail the
  probe loudly and block step 3; skip-all still lands on a working front
  door; every wizard control also present in Settings.

## Pointers (all existing)

- Redirect: shim/routes/pages.py front_door (is_configured check)
- Connection check: ha_client.check_connection(); supervisor mode
  _load_auth
- Probe: shim/deploy_writer.probe() via /api/settings/test-write
- PyScript presence: ha_client.get_services() (used by deploy verification)
- config.yaml: shim/config_yaml.py analyze()/apply(), routes in pages.py
- TTS engines: device_pipeline.extract_tts_engines; setting tts_engine in
  storage.load_settings()
- Settings save: /api/settings (keeps owning everything the wizard touches)

# Handoff — virtual test devices work (written 2026-10-27)

For a new Claude chat taking over from the chat that rebuilt the test-devices add-on.
Read it top to bottom once. It assumes you know nothing else about this work.

**Read first, in this order:** `CLAUDE.md`, `HARD_RULES.md`, `DEV_BENCH.local.md`
(gitignored; names Jeremy's machines and network; ask him for it if it is missing),
then the auto-memory files `virtual_test_devices_chat_2026_10_26.md` and
`dishwasher_doc_run_2026_10_26.md` (the dishwasher run is another chat's work on the
same device the open job below is about).

This repo is PUBLIC. Do not put addresses, tokens or Jeremy's machine names in files.

---

## 1. Who you are working for, and how

- Jeremy is the sole director. He does not code. He verifies by behaviour, so explain
  in what-happens terms, never in code terms.
- **Plan first, hard stop.** Present the plan and wait for his go before code or files.
  New files need his approval (he approved this handoff file).
- **No PowerShell.** Use Bash and the dedicated tools. (The previous chat slipped once
  with a read-only command and admitted it.)
- **No multiple-choice question widgets.** Ask in one plain sentence, or decide.
- **Push back on bad ideas.** He said: "you are welcome and required to push back, I
  don't need a mindless do what I say AI." He thinks out loud.
- **Work on `main` only.** No branches. He pushes through GitHub Desktop himself and
  makes the version/release change himself. Claude never deploys, commits only if asked.
- **Check the remote, not local git** before saying anything is released or pushed
  (`git ls-remote`). Earlier chats got this wrong three times from stale local tags.
- **Never leave dead code.** Grep every symbol you add at the end of a change; a count
  of 1 is an orphan.
- **Search the whole compiler for an existing tool before writing a new one.**
- **Do not claim things you did not check.** This chat wrongly said the export was
  "left out as agreed" (he had told it to add it) and that DevLn was credited when it
  was only in FORK_NOTES. Both were corrected.

## 2. State of the two repos RIGHT NOW (checked 2026-10-27)

Both are clean and level with their remotes. Nothing is waiting to be committed.

- **Add-on repo** `C:\Users\Jeremy\Documents\GitHub\ha-virtual-test-devices`
  - `44c8a2a` "Export a real Home Assistant as stand-ins, clone a device so it can
    receive a push or a text, and add select and text (0.14.0)". Tag **0.14.0** on the
    remote points at exactly this commit. Jeremy published the release.
  - `7f1f1e0` "Credit DevLn's fork for the export idea". README only. It is AFTER the
    tag, so the published 0.14.0 release does not contain it. He decided not to cut a
    new release for it. It ships with the next release. He MAY edit the 0.14.0 release
    notes on GitHub to add the credit paragraph; never move the tag.
- **PistonCore repo** `pistoncore-v2`
  - `c3e2646` "The Test Devices page works beside an imported group, and the bundled
    test-devices add-on becomes 0.14.0". Pushed.
  - Untracked drafts under `new docs/` (`01_USING_PISTONCORE_DRAFT.md`,
    `ENGINE_DIRECTION_DRAFT.md`, `SESSION_BRIEF_EDITOR_DRIVING_DRAFT.md`,
    `TRANSLATION_FRAME_PROPOSAL.md`) belong to other chats. Leave them alone.

When Jeremy deploys PistonCore he must press **"Install / update the test-devices
add-on"** on the Test Devices page so Home Assistant gets 0.14.0.

## 3. The two-repos / one-add-on rule (HARD)

- Source of truth: `ha-virtual-test-devices\custom_components\virtual\`.
- Bundled copy: `pistoncore-v2\test-devices-integration\custom_components\virtual\`.
- They are **ONE add-on, never two.** The PistonCore UI decides what is offered; the
  add-on does not branch on who is calling it. Jeremy repeated this several times.
- After ANY add-on change: copy source -> bundled copy, then `diff -rq` both
  `custom_components/virtual` trees, plus `README.md`, `FORK_NOTES.md` and `tests/`.
- Anonymity/privacy: PistonCore owns data safety (it builds the reports sent to
  Jeremy using the clone tool). The standalone add-on carries no warnings or
  anonymity switches. Lock/alarm codes and text passwords stay excluded everywhere.
- The standalone UI for running the add-on is a future roadmap item, not now.

## 4. What the add-on does now (0.14.0), so you do not re-derive it

Files in `custom_components/virtual/` and what they own:

- `clone.py` — `virtual.clone_device` and `virtual.describe_device`.
  `entity_spec(hass, domain, entry, attrs)` is shared by clone and export.
  Options `notify_as` (`"app"` or `"sms"`) and `add_notifier` (bool). `notify_as`
  alone only relabels notifiers that already exist; adding a notifier needs
  `add_notifier: true` or a phone from the `mobile_app` integration. A phone
  (config entry domain in `PUSH_CONFIG_DOMAINS`) gets a push notifier automatically.
  `_notifier_spec(kind)` yields `{"platform":"notify","name":"Notification","class":kind}`
  and goes through `unique_in_device` so names never collide. Errors are
  `ServiceValidationError`. `REPRODUCIBLE_DOMAINS` and `CLONE_ATTRS` include `select`
  (options) and `text` (min, max, pattern, mode).
  `add_notifier` is deliberately NOT in `services.yaml`; it is a PistonCore-UI-only
  option, the UI decides when to offer it. `describe_device` has no services.yaml entry
  by design.
- `export.py` (new) — `virtual.export_devices`. Fields: `file`,
  `exclude_integrations` (default `["hassio","backup","sun","hacs","virtual"]`),
  `exclude_entities`, `exclude_devices`, `include_domains`, `persistent`,
  `skip_hidden`. Writes a YAML devices file atomically (`cfg._atomic_write`).
  Devices are keyed by the live registry device id and carry `name`, manufacturer,
  model, sw_version, area (no MAC, no configuration_url). Light keeps brightness,
  colour, effect (not colour temperature). Stateless domains (button, camera, event,
  notify) carry no state; a password text carries no value. Schemas for each platform
  are loaded lazily in the executor (`load_platform_schemas`) because importing the
  platform modules inside `async_setup` caused "blocking call" warnings.
- `select.py`, `text.py` (new) — `VirtualSelect` (menu falls back to first option),
  `VirtualText` (value that does not fit becomes None; password keeps no value; max
  raised to min).
- `cfg.py` — reads the devices file. `_explicit_identity`: an entity may carry an
  explicit `entity_id` (wrong domain or duplicate is skipped with ERROR, capitals
  lowered with WARNING); unique_id is `entity.get(ATTR_UNIQUE_ID) or
  f"{entity_id}.virtual"`. `_async_read_user_file(file_name)` returns
  `(devices, trustworthy)`. `BlendedCfg.trusted` is false if the file was unreadable,
  blank, not a mapping, or had a rejected entry.
- `__init__.py` — `export_only` in `configuration.yaml` stops the integration
  importing or creating anything; on an HA with no groups that leaves only the export
  action; an already-set-up group keeps running. `_async_remove_orphans` removes an
  entity row one at a time, and a device only when the file no longer lists it, and
  **does nothing (with a warning) when `vcfg.trusted` is false.** This was the fix for
  "a blank file or a typo deletes real registry rows." `__version__` is read from the
  manifest.
- `entity.py` — `DeviceInfo` uses identifiers only; a WARNING is logged if HA changes
  an entity id that came from the file; `entity_category` is allowed.
- `manifest.json` — version `0.14.0`.

Docs in the add-on repo: `README.md` (notifier and export sections, Credit section
naming twrecked and DevLn), `FORK_NOTES.md` (design, trust rule, measured results,
known limits), `tests/README.md` (table of tests; "Expect `186 passed`").

Tests (186 pass on the bundled copy): `test_notifier_clone.py`, `test_explicit_ids.py`,
`test_orphans.py`, `test_export.py`, `test_select_text.py`, `test_version.py`, and
`test_capability_capture.py` (extended for select/text).

## 5. What PistonCore does for it now

- `shim/routes/pages.py`:
  - `_group_present()` finds PistonCore's own group (title `"<TEST_DEVICES_GROUP> -
    virtual"`, state `loaded`) among all `virtual` entries, so a second imported group
    no longer stops PistonCore creating its own.
  - `_ensure_group` returns "created" / "exists" / "not_installed" / "failed" and
    falls back to a file of its own (`pistoncore_test_devices.yaml`) if the default
    file is taken. It copes with either path separator.
  - The create-twin route sends the push/text choice (`notify_as`, whitespace
    trimmed, must be `app` or `sms`) with `add_notifier: True`. A missing clone action
    (`service_not_found`) gives the "your add-on is older" message; any other failure
    shows what Home Assistant actually said, via `_clean_ha_error` (parses HA's dict
    wrapper with `ast.literal_eval` and strips "Validation error: ").
- `static/pistoncore/test_devices.js` — per-row selector for push or text
  (has an `aria-label`). `templates/test_devices.html` — style for `.td-clone-notify`.
- The Test Devices page currently lists EVERY virtual device, including imported
  stand-ins, not only PistonCore's own (see open questions).

## 6. THE OPEN JOB — wrong attribute name when triggering a piston

Jeremy's words: "it sends the wrong state name when you send the change to trigger
the piston." Another chat found it with the dishwasher.

**Symptom.** A cloned dishwasher offers its job state in the editor as a custom
attribute named after the entity (shown as `⌂ test_dishwasher_job_state`) instead of
`jobState`. A piston written against `jobState` never fires from the clone, and the
change goes out under the wrong name.

**Root cause (found by reading code, NOT yet changed).**
`shim/device_pipeline.py`:
- `_custom_attribute_key(entity, entity_id)` at line 110 recovers the original Hubitat
  attribute name only when `entity.get("platform") == "hubitat"` and the unique_id
  splits on `::` into four parts `hub::device::sensor::attrName`.
- `_custom_attribute(entity_id, entity, state)` at line 131 uses that key; it is
  called at line 615.
- For a virtual clone or an exported stand-in the platform is `virtual` and the
  unique_id is a UUID or `<entity_id>.virtual`, so the name falls back to the entity's
  object_id.

**Jeremy's two ideas** ("use the export of the real HA" or "a special clone for the
bridge") do NOT fix it alone: both produce `virtual` entities that lose the original
name. He does not code and was inferring this from other chats, so say plainly what
is true.

**Proposed plan (Jeremy has NOT given the go; present it and wait):**
1. The add-on's `clone_device` and `export_devices` record the SOURCE entity's
   original unique_id as a generic `source_unique_id`, exposed as a state attribute.
   Generic on purpose: no Hubitat knowledge in the add-on.
2. PistonCore's `_custom_attribute_key` / `_custom_attribute` read it for `virtual`
   entities and parse it the same way they already parse hubitat ones. Hubitat-format
   knowledge stays in PistonCore.
3. Keep that attribute out of the editor's pick list; it is bookkeeping.
4. **Privacy first.** The unique_id contains the hub and device identifiers. Check what
   PistonCore's reports already hide. If the rest is not hidden, carry only the
   attribute name, not the whole id.
5. Tests for the add-on (clone and export both carry it) and for PistonCore (a stand-in
   with a Hubitat-shaped source id offers `jobState`). Remember the add-on rule:
   one add-on, copy + `diff -rq`.
6. Verdict: a whole-piston run through PistonCore end to end against a real
   bridged device. Synthetic Hubitat-shaped data is fine for parts only. The real
   bridged device lives on the shared bench; ask Jeremy before touching it, or ask him
   to do the final click-through.

Why Jeremy cares: he runs Hubitat and does not want to adopt everything native in HA.
He wants to export his main HA and clone it to see "what it WILL use" if it became
the hub. "This is priceless for my troubleshooting." The bridge causes him many
problems, and the bridge is test scaffolding (native resolution always outranks it).

## 7. Other open questions and roadmap (none started)

- Should the Test Devices page list only PistonCore's own devices? It currently lists
  all virtual devices, including imported stand-ins. Ask him in one plain sentence.
- Roadmap he raised: camera stream support in the virtual camera; as much parity with
  real HA as possible (valve abilities, media_player browse and search, camera
  state); a UI to run the standalone add-on.
- A compiled push/text piston actually firing at a clone has NOT been verified.
- Not verified at all: the page in a real browser, HA beta, a real Hubitat-bridged setup.
- One unexplained single 400 on a 1200-entity `create_device` was not reproduced in 4
  attempts. Mentioned for honesty; do not chase it without cause.

## 8. Bench and safety (read DEV_BENCH.local.md for the actual addresses)

- There are three Home Assistants: Jeremy's own test HA, the house (production), and
  the container you run yourself. **Never touch the production one.** Reading the test
  HA is standing permission; writing to a real device there needs a question first.
  Virtual devices are free to drive. A deploy can silently wipe other pistons'
  helpers, and checking only the devices you drive has armed his real alarm twice, so
  check every entity before a deploy.
- `pc-testha` (a container) is Jeremy's. Ask before even reading it. Run your OWN
  throwaway containers for tests.
- Do not read or write outside the repo, and never touch the v1 PistonCore repo,
  without asking and naming the exact file and what you want from it.
- The add-on repo is a different repo; its parent folder is outside this one, but
  Jeremy put it in scope for this work.

## 9. How the previous chat tested (so you can repeat it)

- A throwaway Home Assistant container, with the add-on copied into
  `/config/custom_components/virtual` and `tests/` into `/config/tests`, then from
  `/config`: `python -m pytest /config/tests -q -p no:cacheprovider`. Expect 186 passed
  on the current bundled copy. Container name used was `pc-unit`.
- **Tamper verification:** break the code on purpose in the container (one change at a
  time), confirm a test fails, restore. A test that cannot fail proves nothing.
- A driver script that talks to a throwaway HA over its API (`HA_BASE` env var)
  checked round trips live: export -> import, restart stability, re-import cleanup,
  broken-entry handling, blank-file and typo safety, export-only beside an existing
  group, PistonCore creating its group beside another, error messages.
- **Gotchas:**
  - Git Bash mangles Docker paths. Use `MSYS_NO_PATHCONV=1`, and with it set use
    `taskkill /F` NOT `taskkill //F`. A stale PistonCore from the earlier run kept
    serving old code and invalidated several results until the bind error exposed it.
  - Bash heredocs collapse `\\n`. Write any script containing escapes with the Write
    tool.
  - HA registry writes are debounced (~10 s), so `.storage` reads lag.
  - Mixed line endings: `cfg.py`, `entity.py`, `const.py`, `config_flow.py` are CRLF;
    `__init__.py`, `clone.py` are LF. Edit with line-ending-aware helpers.
  - Do not name a script after a stdlib module (`dis.py` shadowed `dis` and crashed a
    test).
  - Import platform modules lazily, not in `async_setup`.
- Documented rule: every divergence from webCoRE is written down as a fair-warning
  trade-off, and every HA fidelity gap goes to `/help/limitations` in the same change
  that finds it (`HA_LIMITATIONS.md` is the coding doc, not user help).

## 10. Facts about Jeremy's setup worth knowing

- His phone is tied to Hubitat, so cloning it does not bring over a push notifier.
  That is why "add a notifier" exists in the PistonCore UI. On plain HA a real phone
  clones with its notifier automatically.
- He keeps two copies of this folder (a spin-off), which is how an earlier chat was
  lost. Chat retention is now set to 3650 days.
- Credit: twrecked/hass-virtual (the original), and DevLn's fork (`ha-test-sim`
  branch) for the export idea and several traps found first. Our code is our own; their
  repo was reviewed, never cloned or merged. Keep the credit visible wherever users
  read about the add-on.

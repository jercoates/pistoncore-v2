# COMPILER_DECISIONS_DEPLOY.md — Deployment & lifecycle decisions
**(Jeremy, 2026-07-12. Feeds the v2 compiler spec. Merge into
COMPILER_DECISIONS_HOLDING.md or carry into the spec directly.)**

Tagging: DECISION = Jeremy's call. VERIFIED = checked against HA docs, 2026-07-12.
ASSUMED = needs a dev-HA test.

---

## 1. Compile timing & piston state mirroring

**DECISION:** Compile happens automatically after a successful piston JSON save. No
separate compile button; no separate deploy step. This matches webCoRE (save = live).

**Piston state mirrors, never invents:**
- A piston's `active`/paused state is owned by the piston (webCoRE's own status page owns
  the pause/resume UI). New pistons land paused by default (build 0) — the compiler simply
  reflects that; it is not a PistonCore-invented state.
- Paused piston → deployed automation is disabled (`initial_state: false` / not enabled).
  Active piston → enabled. Set at compile; updated on pause/resume.
- **One direction only: PistonCore → HA.** If a user toggles the automation in HA's UI,
  PistonCore overwrites it on next compile. Predictable beats clever.

**Compile failure → the previously deployed artifact is LEFT RUNNING, untouched.** A failed
compile means "couldn't build the new version," NOT "the old version is bad." Never
silently break a working automation. Failure surfaces as: banner on the piston status page
(with a link to the debug page), plus a flag on the PistonCore front door.

## 2. Device resolution failure (refines A6)

- **Unavailable** (entity known, currently offline/dead): PASS THROUGH. HA handles it —
  service calls skip unavailable entities and continue. Do not block compile.
- **Unresolvable** (hashed id with no entity behind it — e.g. foreign/imported piston):
  compile-time ERROR. Non-negotiable: an HA trigger referencing a nonexistent entity_id
  **silently never fires**, and templates on missing entities throw at runtime. Silent dead
  automations are the worst failure mode. [VERIFIED — HA trigger/template behavior]
- **Multi-device statement** with some devices unresolvable: skip the bad ones, compile the
  rest, and FLAG the skips on the debug page. Never silently drop.
- **Single-device statement** whose only device is unresolvable: that statement errors →
  piston flagged/paused, surfaced on the debug page.

## 2.5 Write transport — HOW compiled files reach HA's `/config`

**THE GAP THIS CLOSES (flagged by Jeremy 2026-07-15; a v1→v2 port omission — v1 had worked
this out).** PistonCore's process has no inherent access to HA's `/config`. Every "write"
in §3-§9 below (automation YAML, pyscript `.py`, the configuration.yaml backup+edit) needs
a transport. The **control path stays the HA API** (`automation.reload`/`script.reload`,
§5 — already has its token, no filesystem access needed); only the **write path** varies.

**END GOAL: PistonCore ships as a HOME ASSISTANT ADD-ON (Jeremy, 2026-07-15).** That is
the primary intended distribution, and it's the simplest write case — an add-on's manifest
declares `map: [homeassistant_config:rw]` (or `config:rw`) and the supervisor mounts HA's
`/config` into the add-on at a local path. No SMB, no user config, no credentials. Auth is
`SUPERVISOR_TOKEN` (already handled in `ha_client.py`). **The compiler's write layer must
be built so the add-on case is plain local file ops.**

**DECISION (Jeremy, 2026-07-15): two write-path implementations, chosen by install
topology. The real distinction is LOCAL-PATH vs IN-APP-SMB:**

**Path 1 — LOCAL PATH (`deploy_writer` does plain file ops to a mounted directory).**
Covers the majority of installs:
- **HA add-on** [END GOAL] — supervisor-mapped `/config`. No config beyond the mapped path.
- **Standalone Docker where HA's config is mounted into PistonCore's container** — either a
  co-located Docker HA sharing a volume, OR a host-level SMB mount bind-mounted in. **This
  is Jeremy's current Unraid test setup:** Unraid's Unassigned Devices already mounts the
  HA VM's Samba share (`//192.168.1.65/config` → a host path); PistonCore's container just
  bind-mounts that host path (`-v …:/ha-config`) and writes locally — the SMB lives at the
  Unraid layer, invisible to PistonCore.

  Settings field: `ha_config_path` (default `/ha-config`, the in-container mount point).
  The mount itself is a `docker run`/add-on-manifest concern, documented in the install
  guide like the existing `-v …:/data` line.

**Path 2 — IN-APP SMB (`deploy_writer` speaks SMB directly).** For standalone Docker where
the user has NOT mounted the share at the host/Docker layer — PistonCore connects to HA's
Samba share add-on itself using an SMB client (`pysmb`/`smbprotocol`). Settings fields:
| field | default | notes |
|---|---|---|
| `smb_host` | derived from `ha_url` host | the HA host, unless the share lives elsewhere |
| `smb_share` | `config` | the Samba add-on's config share = HA's `/config` root |
| `smb_username` | — | Samba add-on credential |
| `smb_password` | — | stored like `ha_token` (write-only in UI: "already set", never echoed) |

**Common to both paths:**
- **A `write_mode` selector on Settings** (`"local" | "smb"`; add-on install defaults to
  `local` and hides the selector). `deploy_writer.py` exposes ONE interface
  (write/read/delete/backup) with the two backends behind it — the compiler never knows
  which is active.
- **A "Test write target" check on Settings** — write + read-back + delete a probe file —
  so a bad mount/share fails VISIBLY at setup, not silently at first compile (same
  philosophy as testing the HA connection). A deploy that can't reach its write target is
  an environmental error naming the target, never a silent drop.

## 3. Deploy layout — labeled includes, NOT packages

**DECISION (revised after research):** compiled artifacts live in PistonCore's own folder,
loaded via HA **labeled include blocks**:

```yaml
# configuration.yaml
automation ui: !include automations.yaml                      # HA's UI keeps this, untouched
automation pistoncore: !include_dir_merge_list pistoncore/automations/
script pistoncore: !include_dir_merge_named pistoncore/scripts/
```
- PyScript target: `/config/pyscript/scripts/pistoncore/` **[VERIFIED — PyScript only
  autoloads `pyscript/*.py`, `pyscript/scripts/**`, `pyscript/apps/`; an arbitrary
  `pyscript/pistoncore/` would never load.]** (PYSCRIPT_COMPILER_RESEARCH §0.1)
- **Packages were REJECTED:** (a) open HA bug — editing a package-loaded automation in the
  UI silently writes a duplicate into automations.yaml with the same id, corrupting the
  package; (b) package filenames must be globally unique across all subdirectories.
  Labeled includes avoid both. [VERIFIED — HA docs + core issue #155519]
- User's existing UI automations are never touched; they remain fully UI-editable.
- Uninstall = delete the folder + the include lines. Nothing else to unwind.

**Compiled automations WILL appear in HA's automation list but are YAML-only (not
UI-editable).** Expected and correct — PistonCore is the editor. Every emitted file carries
a header: `# Generated by PistonCore — do not edit; changes are overwritten on recompile.`
Document in the "what's different from webCoRE" help file.

## 4. Artifact naming
**DECISION:** `<slugified-piston-name>_<short-piston-id>.yaml` — readable (findable and
hand-editable if the user ever leaves PistonCore) AND rename-safe (id is the identity).
On rename, the compiler deletes the old file and writes the new one. Id is authoritative;
name is convenience.

## 5. Reload
**DECISION:** call HA's `automation.reload` + `script.reload` after writing. No HA restart.
**ASSUMED — verify on dev HA:** whether newly *added* files under an
`!include_dir_merge_list` are picked up by `automation.reload` alone, or whether a first-
time file addition needs `homeassistant.reload_all` / restart. Test before shipping.

## 6. Routing table
**DECISION:** `routing_table.json` = a list of webCoRE-JSON signatures that FORCE PyScript.
YAML is the default; the exceptions are the finite, enumerable thing. Machine-readable and
edit-friendly matters more than human-prose readability (an AI will read it more often than
Jeremy will). Source content: COMPILER_DECISIONS_HOLDING §E + HA_LIMITATIONS §6.
**Plus a user override (settings):** allow a user to force PyScript output as a preference
— e.g. "prefer PyScript for fidelity" — since PYSCRIPT_COMPILER_RESEARCH shows PyScript
reproduces webCoRE semantics nearly verbatim (`stays`=`state_hold`, `was`=`.old`, etc.).
YAML-first remains the default (zero dependencies).

## 7. Execution mode
**DECISION:** not an editor concern. A **first-run prompt** asks the user's preferred
default piston execution mode; changeable later in PistonCore settings. Where webCoRE's own
piston settings express an equivalent, honor them per-piston. All four HA modes are
reproducible on the PyScript path (PYSCRIPT_COMPILER_RESEARCH §6).

## 8. Recompile All
**DECISION:** manual "Recompile all" button in PistonCore settings, PLUS a front-door
banner when deployed artifacts were built with an older template set ("compiled with older
templates — recompile recommended"). Compiled artifacts therefore record the template-set
version they were built with. This is the breaking-change insurance: when HA changes YAML
syntax, update templates → recompile all → zero manual automation edits.

## 9. First-run wizard (new requirement, from #3 and #7)

PistonCore's first run must present, with explanation:
1. **HA connection** (URL/token, or supervisor token on the add-on).
1a. **Write transport** (§2.5): pick Samba (HA in a VM/HAOS/remote) or shared-volume/local
   (co-located Docker HA), enter that mode's fields, and run the "Test write target" probe
   before proceeding. The compiler cannot deploy anything until this passes.
2. **configuration.yaml edit consent.** PistonCore can add the include lines itself, but
   ONLY safely: (a) write a timestamped backup of configuration.yaml first; (b) SHOW the
   exact lines to be added and the exact rename (`automation:` → `automation ui:`) needed
   for labeled blocks to work; (c) apply only on explicit consent; (d) if the file looks
   non-standard/unparseable, REFUSE to auto-edit and show copy-paste instructions instead.
   Never a blind write. Same treatment for the `pyscript:` config block.
3. **PyScript notice + link to the help doc.** Wording must make clear it is OPTIONAL:
   most pistons compile to native YAML with zero dependencies; only pistons using
   semantics HA YAML can't express (loop breaks, in-flight task cancellation, etc.) need
   PyScript (a free HACS install). Link to PistonCore's install-help doc.
4. **Default execution mode** (#7).
All four changeable later in settings.

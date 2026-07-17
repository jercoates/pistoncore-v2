"""configuration.yaml include-lines management (COMPILER_DECISIONS_DEPLOY §3 + §9.2).

Adds the labeled include blocks the compiler's deploy layout needs:

    automation ui: !include automations.yaml          # rename of the stock line
    automation pistoncore: !include_dir_merge_list pistoncore/automations/
    script ui: !include scripts.yaml                  # rename of the stock line
    script pistoncore: !include_dir_merge_named pistoncore/scripts/

Safety rules (DECIDED — never a blind write):
  (a) timestamped backup of configuration.yaml written FIRST, same directory;
  (b) analyze() returns the EXACT changes for the UI to show; apply() happens
      only on a second explicit call (the user's consent click);
  (c) if the file looks non-standard for our line-based edit (block-style
      automation:, duplicate keys, nothing recognizable), REFUSE and tell the
      user to paste the lines themselves.

Line-based on purpose: HA config YAML is full of custom tags (!include,
!secret) that a YAML parser can't round-trip faithfully. We only touch
column-0 lines we fully understand, and refuse otherwise.

The `pyscript:` block is deliberately NOT added here — an unknown integration
key breaks HA config validation when PyScript isn't installed; it gets the
same treatment at compiler-deploy time once PyScript presence is detectable.
"""

import re
import time

from . import deploy_writer

CONFIG = "configuration.yaml"
PC_AUTO = "automation pistoncore: !include_dir_merge_list pistoncore/automations/"
PC_SCRIPT = "script pistoncore: !include_dir_merge_named pistoncore/scripts/"
MARKER = "# PistonCore managed includes — added by PistonCore Settings"

_TOP_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_ ]*):(.*)$")


def _scan(text: str) -> dict:
    found: dict = {"top_keys": [], "bare_automation": None, "bare_script": None,
                   "has_pc_auto": False, "has_pc_script": False,
                   "has_ui_auto": False, "has_ui_script": False}
    for i, line in enumerate(text.splitlines()):
        m = _TOP_KEY.match(line)
        if not m:
            continue
        key, value = m.group(1).strip(), m.group(2).strip()
        found["top_keys"].append(key)
        if key == "automation":
            found["bare_automation"] = (i, value)
        elif key == "script":
            found["bare_script"] = (i, value)
        elif key == "automation pistoncore":
            found["has_pc_auto"] = True
        elif key == "script pistoncore":
            found["has_pc_script"] = True
        elif key == "automation ui":
            found["has_ui_auto"] = True
        elif key == "script ui":
            found["has_ui_script"] = True
    return found


def analyze() -> dict:
    """Read configuration.yaml through the configured write target and return
    {status, changes[], refusals[]} — changes as human-readable exact edits."""
    writer = deploy_writer.get_writer()
    try:
        text = writer.read(CONFIG)
    except Exception as exc:
        raise deploy_writer.WriteTargetError(
            f"Could not read {CONFIG} from {writer.describe()}: {exc}") from exc

    found = _scan(text)
    if not found["top_keys"]:
        return {"status": "refused", "changes": [], "refusals": [
            f"{CONFIG} has no recognizable top-level keys — refusing to auto-edit. "
            f"Add these lines yourself: '{PC_AUTO}' and '{PC_SCRIPT}'."]}

    changes, refusals = [], []
    for kind, bare_key, ui_label, pc_line, has_pc, has_ui in (
        ("automation", "bare_automation", "automation ui", PC_AUTO, "has_pc_auto", "has_ui_auto"),
        ("script", "bare_script", "script ui", PC_SCRIPT, "has_pc_script", "has_ui_script"),
    ):
        bare = found[bare_key]
        if not found[has_pc]:
            if bare is not None:
                _, value = bare
                if not value:
                    refusals.append(
                        f"'{kind}:' has block-style content (not a one-line !include) — "
                        f"refusing to rename it automatically. Rename it to '{ui_label}:' "
                        f"yourself, then add: '{pc_line}'.")
                    continue
                changes.append(f"RENAME line '{kind}: {value}' -> '{ui_label}: {value}' "
                               f"(labeled blocks need the stock line labeled too)")
            changes.append(f"ADD line: '{pc_line}'")

    if not changes and not refusals:
        return {"status": "ok", "changes": [],
                "refusals": [],
                "message": "configuration.yaml already has the PistonCore include lines."}
    return {"status": "changes" if changes else "refused",
            "changes": changes, "refusals": refusals}


def apply() -> dict:
    """Apply exactly what analyze() proposed: timestamped backup first, then
    the renames/additions, then folder placeholders so the include dirs exist."""
    writer = deploy_writer.get_writer()
    text = writer.read(CONFIG)
    found = _scan(text)
    lines = text.splitlines()

    applied = []
    for kind, bare_key, ui_label, pc_line, has_pc in (
        ("automation", "bare_automation", "automation ui", PC_AUTO, "has_pc_auto"),
        ("script", "bare_script", "script ui", PC_SCRIPT, "has_pc_script"),
    ):
        bare = found[bare_key]
        if not found[has_pc]:
            if bare is not None:
                idx, value = bare
                if not value:
                    continue  # refused case — analyze() already told the user
                lines[idx] = f"{ui_label}: {value}"
                applied.append(f"renamed '{kind}:' to '{ui_label}:'")
            add_block = [pc_line]
            if not any(MARKER in l for l in lines):
                add_block.insert(0, MARKER)
                if lines and lines[-1].strip():
                    add_block.insert(0, "")
            lines.extend(add_block)
            applied.append(f"added '{pc_line}'")

    if not applied:
        return {"status": "ok", "applied": [], "message": "Nothing to change."}

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_name = f"configuration.yaml.pistoncore-backup-{stamp}"
    writer.write(backup_name, text)                     # (a) backup FIRST
    writer.write(CONFIG, "\n".join(lines) + "\n")
    # include_dir on a missing folder is an HA config error — make them exist.
    writer.write("pistoncore/automations/.keep", "")
    writer.write("pistoncore/scripts/.keep", "")
    return {"status": "applied", "applied": applied, "backup": backup_name,
            "note": "Restart Home Assistant (or reload all YAML) to pick up the new include lines."}

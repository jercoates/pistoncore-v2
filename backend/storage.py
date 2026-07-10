# pistoncore/backend/storage.py
#
# Piston JSON file storage.
# Pistons are stored as individual JSON files in /pistoncore-userdata/pistons/
# One file per piston: <piston_id>.json
#
# This is the only layer that touches the filesystem.
# The API layer calls storage functions — it never reads/writes files directly.

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Base directory — overridden by PISTONCORE_DATA_DIR env var for testing
DATA_DIR = Path(os.environ.get("PISTONCORE_DATA_DIR", "/pistoncore-userdata"))
PISTONS_DIR = DATA_DIR / "pistons"
GLOBALS_FILE = DATA_DIR / "globals.json"
CONFIG_FILE = DATA_DIR / "config.json"


def _ensure_dirs():
    PISTONS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Piston CRUD
# ---------------------------------------------------------------------------

def list_pistons() -> list[dict]:
    """
    Return all pistons as a list of dicts, sorted by name.
    Each dict is the full piston JSON with metadata.
    """
    _ensure_dirs()
    pistons = []
    for path in PISTONS_DIR.glob("*.json"):
        try:
            with open(path) as f:
                pistons.append(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass  # Skip corrupt files silently — log in future
    return sorted(pistons, key=lambda p: p.get("name", "").lower())


def get_piston(piston_id: str) -> dict | None:
    """Return a single piston by ID, or None if not found."""
    path = PISTONS_DIR / f"{piston_id}.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def save_piston(piston: dict) -> dict:
    """
    Write a piston to disk. Generates an ID if not present.
    Updates modified_at timestamp.
    Returns the saved piston dict.
    """
    _ensure_dirs()
    if "id" not in piston or not piston["id"]:
        piston["id"] = str(uuid.uuid4()).replace("-", "")[:8]
    piston["modified_at"] = datetime.now(timezone.utc).isoformat()
    if "created_at" not in piston:
        piston["created_at"] = piston["modified_at"]

    path = PISTONS_DIR / f"{piston['id']}.json"
    with open(path, "w") as f:
        json.dump(piston, f, indent=2)
    return piston


def delete_piston(piston_id: str) -> bool:
    """Delete a piston file. Returns True if deleted, False if not found."""
    path = PISTONS_DIR / f"{piston_id}.json"
    if not path.exists():
        return False
    path.unlink()
    return True


def get_all_slugs() -> dict[str, str]:
    """
    Return a dict of {piston_id: slug} for all pistons.
    Used by the compiler for slug collision detection and call_piston resolution.
    Uses utils.slugify — no Compiler instantiation needed.
    """
    from utils import slugify
    result = {}
    for piston in list_pistons():
        result[piston["id"]] = slugify(piston["name"])
    return result


# ---------------------------------------------------------------------------
# Globals store
# ---------------------------------------------------------------------------

def load_globals() -> dict:
    """
    Load the globals store from disk.
    Returns {} if the file doesn't exist yet.
    Format: {
      "global_id": {
        "id":          str,
        "name":        str,
        "var_type":    str,   # "text" | "number" | "boolean" | "datetime" | "device"
        "value":       str | list[str],  # list of entity_id strings for device type,
                                         # plain string for all other types
        "description": str
      }
    }
    """
    if not GLOBALS_FILE.exists():
        return {}
    with open(GLOBALS_FILE) as f:
        return json.load(f)


def save_globals(globals_store: dict):
    """Write the globals store to disk."""
    _ensure_dirs()
    with open(GLOBALS_FILE, "w") as f:
        json.dump(globals_store, f, indent=2)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """
    Load PistonCore runtime config.
    Returns defaults if config file doesn't exist.
    """
    defaults = {
        "ha_url": "http://homeassistant.local:8123",
        "ha_token": "",
        "ha_config_path": "",          # path to HA config dir — set by user in settings
        "ha_restart_required": False,  # True after configuration.yaml is modified on startup
        "app_version": "0.9",
        "run_timeout_minutes": 5,
        "template_dir": "/pistoncore-customize/compiler-templates/native-script/",
    }
    if not CONFIG_FILE.exists():
        return defaults
    with open(CONFIG_FILE) as f:
        stored = json.load(f)
    return {**defaults, **stored}


def save_config(config: dict):
    """Write config to disk."""
    _ensure_dirs()
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

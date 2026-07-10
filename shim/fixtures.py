"""Hardcoded fixture data for the spike milestone (SHIM_API_SPEC.md §10.5).

Fake devices/instance/location so the dashboard renders a piston list and
device picker without a real Home Assistant connection. Replaced by the
real DEVICE_PAYLOAD_SPEC.md pipeline in milestone 2.
"""

import itertools
import json
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# The dashboard's own version() (app.js:2524). Echoing it back as
# instance.coreVersion silences the "newer version available" nag banner
# (SHIM_API_SPEC.md §5.2).
CORE_VERSION = "v0.3.114.20220203"

FAKE_DEVICES = {
    ":fakeswitch1:": {
        "n": "Fake Switch",
        "cn": ["Switch"],
        "a": [{"n": "switch", "t": "enum"}],
        "c": ["on", "off"],
        "o": {},
        "an": "Fake Switch",
    },
    ":fakecontact1:": {
        "n": "Fake Contact Sensor",
        "cn": ["Contact Sensor"],
        "a": [{"n": "contact", "t": "enum"}],
        "c": [],
        "o": {},
        "an": "Fake Contact Sensor",
    },
    ":fakedimmer1:": {
        "n": "Fake Dimmer",
        "cn": ["Switch", "Switch Level"],
        "a": [{"n": "switch", "t": "enum"}, {"n": "level", "t": "integer"}],
        "c": ["on", "off", "setLevel"],
        "o": {},
        "an": "Fake Dimmer",
    },
}

FAKE_LOCATION = {
    "id": "fake-location",
    "name": "Fake Home",
    # dashboard.module.js:1088-1103 — getLocationMode() matches location.mode
    # against location.modes[].id (not a display string), and getSHMModeName()
    # only recognizes the literal strings 'away'/'stay'/'off' — anything else
    # (including the more descriptive 'disarmed' this had) renders "(unknown)".
    "mode": "home",
    "modes": [
        {"id": "home", "name": "Home"},
        {"id": "away", "name": "Away"},
        {"id": "night", "name": "Night"},
    ],
    "shm": "off",
    "temperatureScale": "F",
    "timeZone": "America/Denver",
}


def fake_instance(base_uri: str) -> dict:
    # dataService.setSI() (app.js:663) keys its client-side session cache on
    # instance.uri/.token — without them, store[instance.id] comes back null
    # and any later re-init (e.g. periodic refresh) bounces to /register
    # because it can't recover the session. Must be present.
    # deviceVersion=1 vs. the client's initial dev=0 forces the dashboard to
    # call intf/dashboard/devices on first load (SHIM_API_SPEC.md §4.1).
    return {
        "id": "fake-instance",
        "name": "PistonCore Spike",
        "uri": base_uri,
        "token": "pistoncore-spike",
        "deviceVersion": 1,
        "pistons": piston_list(),
        "globalVars": {},
        "coreVersion": CORE_VERSION,
        "settings": {},
        "lifx": {},
        "contacts": [],
        "virtualDevices": {},
    }


_vocab_cache: dict | None = None


def get_db() -> dict:
    """webCoRE vocabulary (capabilities/attributes/commands/...) — seed for piston/getDb."""
    global _vocab_cache
    if _vocab_cache is None:
        with open(_REPO_ROOT / "webcore_vocab.json", encoding="utf-8") as f:
            _vocab_cache = json.load(f)
    return _vocab_cache


# In-memory piston store for the spike (piston.new/create/get — SHIM_API_SPEC.md
# §4.5/§4.6). Resets on server restart; the real chunked save flow that persists
# pistons to disk is milestone 3.
_pistons: dict[str, dict] = {}
_piston_id_counter = itertools.count(1)

BLANK_PISTON = {"o": {"cto": 0, "ced": 0}, "r": [], "s": [], "v": [], "z": ""}


def new_piston_name() -> dict:
    return {"name": "New Piston"}


def create_piston(name: str, author: str) -> dict:
    piston_id = f"pistoncore-spike-{next(_piston_id_counter)}"
    now_ms = int(time.time() * 1000)
    _pistons[piston_id] = {
        "name": name or "New Piston",
        "piston": dict(BLANK_PISTON),
        "meta": {
            # meta.a (active) keeps a piston out of dashboard.module.js's
            # paused-pistons bucket (dashboard.module.js:78-100).
            "a": True,
            "c": "0",
            "m": now_ms,
            # piston.module.html:416-417 reads meta.created/meta.modified
            # (full names) for the editor header comment, separate from the
            # abbreviated "m" the list view reads.
            "created": now_ms,
            "modified": now_ms,
            "author": author,
        },
    }
    return {"id": piston_id}


def get_piston_entry(piston_id: str) -> dict:
    entry = _pistons.get(piston_id)
    if entry is None:
        return {"piston": dict(BLANK_PISTON), "meta": {}}
    return entry


def piston_list() -> list:
    return [
        {"id": pid, "name": entry["name"], "meta": entry["meta"]}
        for pid, entry in _pistons.items()
    ]

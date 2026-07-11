"""Fixture data still standing in for real HA integration.

Devices (milestone 2) and pistons/globals (milestone 3, shim/storage.py)
are real now. Location is still fake — no HA location/mode/HSM pipeline
built yet.
"""

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# The dashboard's own version() (app.js:2524). Echoing it back as
# instance.coreVersion silences the "newer version available" nag banner
# (SHIM_API_SPEC.md §5.2).
CORE_VERSION = "v0.3.114.20220203"

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
    # pistons/globalVars are populated by the /load route from shim/storage.py
    # (real persistence, milestone 3) — left out here, not fixture data.
    return {
        "id": "fake-instance",
        "name": "PistonCore Spike",
        "uri": base_uri,
        "token": "pistoncore-spike",
        "deviceVersion": 1,
        "coreVersion": CORE_VERSION,
        "settings": {},
        "lifx": {},
        "contacts": [],
        "virtualDevices": {},
    }


_db_cache: dict | None = None


def get_db() -> dict:
    """
    webCoRE vocabulary — seed for piston/getDb. webcore_vocab.json has
    "commands" and "virtualCommands" as two separate flat top-level keys,
    but piston.module.js reads db.commands as a NESTED {physical, virtual}
    object everywhere it looks up a command (VERIFIED — 10+ call sites,
    e.g. piston.module.js:2394,2619,2840,2865 all read db.commands.physical/
    db.commands.virtual; found via the "add a new task" crash,
    TypeError on db.commands.physical being undefined, 2026-07-10).
    db.capabilities/db.attributes ARE read flat (piston.module.js:2606,2637)
    — this reshape is scoped to commands only, not applied blindly.
    """
    global _db_cache
    if _db_cache is None:
        with open(_REPO_ROOT / "webcore_vocab.json", encoding="utf-8") as f:
            vocab = json.load(f)
        _db_cache = dict(vocab)
        _db_cache["commands"] = {
            "physical": vocab["commands"],
            "virtual": vocab["virtualCommands"],
        }
    return _db_cache


def new_piston_name() -> dict:
    return {"name": "New Piston"}

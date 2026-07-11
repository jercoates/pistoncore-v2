"""Fixture data still standing in for real HA integration.

Devices (milestone 2), pistons/globals (milestone 3, shim/storage.py), and
location/virtualDevices (SHIM_API_SPEC.md §5.3, decision Jeremy 2026-07-11)
are real now.
"""

import json
import logging
from pathlib import Path

from . import ha_client, storage, device_pipeline

_REPO_ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger("fixtures")

# The dashboard's own version() (app.js:2524). Echoing it back as
# instance.coreVersion silences the "newer version available" nag banner
# (SHIM_API_SPEC.md §5.2).
CORE_VERSION = "v0.3.114.20220203"

# Zero-setup default Location Mode source (SHIM_API_SPEC.md §5.3 decision,
# item 1). A PistonCore-designated override lives in storage.settings under
# "location_mode_entity" — hand-edited in settings.json until a real
# Settings page exists (memory: pistoncore_settings_page_ha_creds).
DEFAULT_MODE_NAME = "PistonCore Location Mode"
DEFAULT_MODE_ENTITY = "input_select.pistoncore_location_mode"
DEFAULT_MODE_OPTIONS = ["Day", "Evening", "Night", "Away"]

# dashboard.module.js:1088-1103 — getSHMModeName() only recognizes the
# literal strings 'stay'/'away'/'off'/'night'; anything else renders
# "(unknown)". HSM and Location Mode are independent states (decision doc) —
# never derive one from the other.
SHM_STATE_MAP = {
    "disarmed": "off",
    "armed_home": "stay",
    "armed_away": "away",
    "armed_night": "night",
}


async def _resolve_mode_entity(registries: dict) -> tuple[dict, bool]:
    """
    Returns (state, helper_just_created). state is a get_states-shaped dict
    for whichever entity backs Location Mode. Resolution order: an explicit
    settings.json override -> the auto-created default helper (created once,
    then remembered in settings so this is self-healing and never creates a
    second one) -> auto-create. A designated override that no longer exists
    in HA is a clear error, never a silent fallback (SESSION_BRIEF item 3b's
    "never silently skip" principle applied here too).
    """
    settings = storage.load_settings()
    entity_id = settings.get("location_mode_entity")
    state_map = {s["entity_id"]: s for s in registries["states"]}

    if entity_id:
        state = state_map.get(entity_id)
        if state is None:
            raise ha_client.HAClientError(
                f"location_mode_entity {entity_id!r} (settings.json) does not exist in HA."
            )
        return state, False

    default_state = state_map.get(DEFAULT_MODE_ENTITY)
    if default_state is not None:
        settings["location_mode_entity"] = DEFAULT_MODE_ENTITY
        storage.save_settings(settings)
        return default_state, False

    created = await ha_client.create_input_select(DEFAULT_MODE_NAME, DEFAULT_MODE_OPTIONS)
    created_entity_id = f"input_select.{created['id']}"
    settings["location_mode_entity"] = created_entity_id
    storage.save_settings(settings)
    logger.info("Auto-created Location Mode helper %s", created_entity_id)
    synthesized_state = {
        "entity_id": created_entity_id,
        "state": created["options"][0],
        "attributes": {"options": created["options"], "friendly_name": created["name"]},
    }
    return synthesized_state, True


def _build_shm(registries: dict) -> str:
    alarm_states = [s for s in registries["states"] if s["entity_id"].startswith("alarm_control_panel.")]
    if not alarm_states:
        logger.info("No alarm_control_panel entity in HA; serving location.shm = 'off'.")
        return "off"
    if len(alarm_states) > 1:
        # TO VERIFY: which one Jeremy wants if this ever applies to him —
        # first alphabetically for now, logged so it's never a silent guess.
        logger.warning(
            "Multiple alarm_control_panel entities found (%s); using %s for location.shm.",
            sorted(s["entity_id"] for s in alarm_states), sorted(alarm_states, key=lambda s: s["entity_id"])[0]["entity_id"],
        )
    chosen = sorted(alarm_states, key=lambda s: s["entity_id"])[0]
    return SHM_STATE_MAP.get(chosen["state"], "off")


async def build_location(registries: dict) -> tuple[dict, bool]:
    """
    Real location payload (SHIM_API_SPEC.md §5.3). Returns
    (location_dict, helper_just_created); the caller should drop its
    registries cache when helper_just_created is True so the NEXT fetch
    naturally includes the new entity — this response is already correct
    without waiting, built from the create call's own result.
    """
    mode_state, created = await _resolve_mode_entity(registries)
    options = mode_state["attributes"].get("options", [])
    current = mode_state["state"]

    config = registries["config"]
    temp_scale = config["unit_system"]["temperature"].replace("°", "")

    location = {
        "id": "pistoncore-location",
        "name": config.get("location_name", "Home"),
        "mode": device_pipeline.hash_id("locationMode." + current) if current in options else None,
        "modes": [{"id": device_pipeline.hash_id("locationMode." + opt), "name": opt} for opt in options],
        "shm": _build_shm(registries),
        "temperatureScale": temp_scale,
        "timeZone": config.get("time_zone", "UTC"),
        "latitude": config.get("latitude"),
        "longitude": config.get("longitude"),
    }
    return location, created


def build_virtual_devices(mode_options: list[str]) -> dict:
    """
    instance.virtualDevices — VERIFIED-HE-GROOVY webcore.groovy:1840 &
    6032-6063 (virtualDevices()): served on the INSTANCE, not the db payload.
    Serves webcore_vocab.json's virtualDevices seed as-is except "mode",
    whose enum options come from the live Location Mode source entity
    instead of the seed's [] placeholder. No live feed needed for
    date/datetime/time (SESSION_BRIEF item 2d) — the dashboard uses the
    clock at render time.
    """
    vocab = get_db()
    virtual_devices = json.loads(json.dumps(vocab["virtualDevices"]))
    if "mode" in virtual_devices:
        virtual_devices["mode"]["o"] = mode_options
    return virtual_devices


def fake_instance(base_uri: str, virtual_devices: dict) -> dict:
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
        "virtualDevices": virtual_devices,
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

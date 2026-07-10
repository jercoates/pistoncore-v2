# pistoncore/backend/context_builder.py
#
# Assembles the fat compiler context object before every compile.
# The compiler receives this — it makes no HA calls of its own.
#
# Entry point: build_compiler_context(piston) -> dict
#
# Failure model:
#   entity_states fetch fails → raises ContextBuildError (abort deploy)
#   services / ha_version / areas fail → degrade gracefully (compiler warns)
#   globals / piston_variables → local reads, always succeed
#
# See COMPILER_SPEC.md Section 7 for the full context object schema.

import logging

import ha_client
import storage

logger = logging.getLogger("context_builder")


class ContextBuildError(Exception):
    """Raised when context assembly fails in a way that must abort the deploy."""
    pass


def build_compiler_context(piston: dict) -> dict:
    """
    Build the fat compiler context object for a piston.
    Fetches all data the compiler needs from HA and local storage.

    Raises ContextBuildError if entity_states cannot be fetched —
    the compiler cannot function without entity states.

    All other HA fetch failures degrade gracefully.
    """

    # --- Entity states (required — abort if unavailable) ---
    try:
        entity_states = ha_client.get_all_states()
    except ha_client.HAClientError as e:
        raise ContextBuildError(
            f"Could not fetch entity states from HA: {e}. "
            f"Check your HA connection and token in PistonCore settings."
        ) from e

    # --- Zones — filtered from entity_states, no extra HA call ---
    zones = [
        {"entity_id": eid, **data}
        for eid, data in entity_states.items()
        if eid.startswith("zone.")
    ]

    # --- Services — domains referenced in this piston's device_map ---
    device_map = piston.get("device_map", {})
    domains = {
        entity_id.split(".")[0]
        for entity_ids in device_map.values()
        for entity_id in entity_ids
        if "." in entity_id
    }
    services = ha_client.get_services_for_domains(domains)

    # --- HA version ---
    ha_version = ha_client.get_ha_version()

    # --- Areas ---
    areas = ha_client.get_areas()

    # --- Global variables — local read, convert dict to list ---
    # storage.load_globals() returns {id: {...}} — compiler expects a list
    globals_dict = storage.load_globals()
    global_variables = list(globals_dict.values())

    # --- Piston variables — pass-through ---
    piston_variables = piston.get("variables", [])

    # --- PistonCore version ---
    pistoncore_version = storage.load_config().get("app_version", "1.0")

    return {
        "piston":             piston,
        "entity_states":      entity_states,
        "services":           services,
        "ha_version":         ha_version,
        "pistoncore_version": pistoncore_version,
        "global_variables":   global_variables,
        "piston_variables":   piston_variables,
        "areas":              areas,
        "zones":              zones,
    }

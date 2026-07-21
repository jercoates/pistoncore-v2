"""
Virtual vacuum — PistonCore addition to hass-virtual (FORK_NOTES.md).

A settable vacuum for testing. Driven via the native `vacuum.start/stop/pause/
return_to_base` services (standalone-controllable; PistonCore uses the same).
State uses HA's VacuumActivity enum.
"""

import logging
import voluptuous as vol
from collections.abc import Callable
from typing import Any

from homeassistant.components.vacuum import (
    DOMAIN as PLATFORM_DOMAIN,
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.config_validation import PLATFORM_SCHEMA
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import get_entity_configs
from .const import *
from .entity import VirtualEntity, virtual_schema


_LOGGER = logging.getLogger(__name__)

DEPENDENCIES = [COMPONENT_DOMAIN]

DEFAULT_VACUUM_VALUE = "docked"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(virtual_schema(DEFAULT_VACUUM_VALUE, {}))
VACUUM_SCHEMA = vol.Schema(virtual_schema(DEFAULT_VACUUM_VALUE, {}))

# initial_value string -> VacuumActivity (e.g. "cleaning", "docked", "returning")
_STATES = {a.value: a for a in VacuumActivity}


async def async_setup_platform(
        hass: HomeAssistant, config: ConfigType,
        async_add_entities: AddEntitiesCallback,
        _discovery_info: DiscoveryInfoType | None = None) -> None:
    if hass.data[COMPONENT_CONFIG].get(CONF_YAML_CONFIG, False):
        async_add_entities([VirtualVacuum(config, True)], True)


async def async_setup_entry(
        hass: HomeAssistant, entry: ConfigEntry,
        async_add_entities: Callable[[list], None]) -> None:
    entities = []
    for entity in get_entity_configs(hass, entry.data[ATTR_GROUP_NAME], PLATFORM_DOMAIN):
        entities.append(VirtualVacuum(VACUUM_SCHEMA(entity), False))
    async_add_entities(entities)


class VirtualVacuum(VirtualEntity, StateVacuumEntity):
    """Representation of a Virtual vacuum."""

    _attr_supported_features = (
        VacuumEntityFeature.START
        | VacuumEntityFeature.STOP
        | VacuumEntityFeature.PAUSE
        | VacuumEntityFeature.RETURN_HOME
        | VacuumEntityFeature.STATE
    )

    def __init__(self, config, old_style: bool):
        super().__init__(config, PLATFORM_DOMAIN, old_style)
        _LOGGER.info(f"VirtualVacuum: {self.name} created")

    def _create_state(self, config):
        super()._create_state(config)
        self._attr_activity = _STATES.get(
            config.get(CONF_INITIAL_VALUE, DEFAULT_VACUUM_VALUE).lower(),
            VacuumActivity.DOCKED)

    def _restore_state(self, state, config):
        super()._restore_state(state, config)
        self._attr_activity = _STATES.get(state.state, VacuumActivity.DOCKED)

    def _set(self, activity: VacuumActivity) -> None:
        self._attr_activity = activity
        self.async_write_ha_state()

    async def async_start(self) -> None:
        self._set(VacuumActivity.CLEANING)

    async def async_stop(self, **kwargs: Any) -> None:
        self._set(VacuumActivity.IDLE)

    async def async_pause(self) -> None:
        self._set(VacuumActivity.PAUSED)

    async def async_return_to_base(self, **kwargs: Any) -> None:
        self._set(VacuumActivity.RETURNING)

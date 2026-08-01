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

import homeassistant.helpers.config_validation as cv
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
from .entity import (
    FEATURES_SCHEMA,
    VirtualEntity,
    feature_flags,
    optional_list,
    virtual_schema,
)


_LOGGER = logging.getLogger(__name__)

DEPENDENCIES = [COMPONENT_DOMAIN]

DEFAULT_VACUUM_VALUE = "docked"

CONF_FAN_SPEED_LIST = "fan_speed_list"

# What the vacuum could always do, before cloning existed.
DEFAULT_FEATURES = (
    VacuumEntityFeature.START
    | VacuumEntityFeature.STOP
    | VacuumEntityFeature.PAUSE
    | VacuumEntityFeature.RETURN_HOME
    | VacuumEntityFeature.STATE
)

BASE_SCHEMA = virtual_schema(DEFAULT_VACUUM_VALUE, {
    **FEATURES_SCHEMA,
    vol.Optional(CONF_FAN_SPEED_LIST): vol.All(cv.ensure_list, [cv.string]),
})

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(BASE_SCHEMA)
VACUUM_SCHEMA = vol.Schema(BASE_SCHEMA)

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
    """Representation of a Virtual vacuum.

    Jeremy owns no vacuum, so this platform IS the only vacuum PistonCore's
    mappings can ever be checked against — which is the whole reason the bench
    exists. It therefore implements every ability it can advertise, and a clone
    from someone else's bug report can turn each one on.
    """

    def __init__(self, config, old_style: bool):
        super().__init__(config, PLATFORM_DOMAIN, old_style)

        self._attr_supported_features = feature_flags(
            config, VacuumEntityFeature, DEFAULT_FEATURES)
        self._attr_fan_speed_list = optional_list(config, CONF_FAN_SPEED_LIST) or []
        if not self._attr_fan_speed_list:
            self._attr_supported_features &= ~VacuumEntityFeature.FAN_SPEED

        _LOGGER.info(f"VirtualVacuum: {self.name} created")

    def _create_state(self, config):
        super()._create_state(config)
        self._attr_activity = _STATES.get(
            config.get(CONF_INITIAL_VALUE, DEFAULT_VACUUM_VALUE).lower(),
            VacuumActivity.DOCKED)
        if self._attr_fan_speed_list:
            self._attr_fan_speed = self._attr_fan_speed_list[0]

    def _restore_state(self, state, config):
        super()._restore_state(state, config)
        self._attr_activity = _STATES.get(state.state, VacuumActivity.DOCKED)
        if self._attr_fan_speed_list:
            self._attr_fan_speed = (state.attributes.get("fan_speed")
                                    or self._attr_fan_speed_list[0])

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

    async def async_clean_spot(self, **kwargs: Any) -> None:
        self._set(VacuumActivity.CLEANING)

    async def async_locate(self, **kwargs: Any) -> None:
        _LOGGER.info(f"{self.name} asked to locate itself")

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        self._attr_fan_speed = fan_speed
        self.async_write_ha_state()

    async def async_send_command(self, command: str, params=None, **kwargs: Any) -> None:
        """Record vendor commands rather than ignoring them — `send_command` is
        how webCoRE pistons reach a vacuum's non-standard functions, so the
        bench has to show that the call arrived and with what."""
        _LOGGER.info(f"{self.name} send_command {command} params={params}")

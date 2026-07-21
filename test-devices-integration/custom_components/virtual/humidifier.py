"""
Virtual humidifier — PistonCore addition to hass-virtual (FORK_NOTES.md).

A settable humidifier for testing. On/off via `humidifier.turn_on/off`, target via
`humidifier.set_humidity` (native services; standalone-controllable, and PistonCore
uses the same). Modelled on switch.py with a target-humidity value added.
"""

import logging
import voluptuous as vol
from collections.abc import Callable
from typing import Any

import homeassistant.helpers.config_validation as cv
from homeassistant.components.humidifier import (
    DOMAIN as PLATFORM_DOMAIN,
    HumidifierEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.config_validation import PLATFORM_SCHEMA
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import get_entity_configs
from .const import *
from .entity import VirtualEntity, virtual_schema


_LOGGER = logging.getLogger(__name__)

DEPENDENCIES = [COMPONENT_DOMAIN]

DEFAULT_HUMIDIFIER_VALUE = "off"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(virtual_schema(DEFAULT_HUMIDIFIER_VALUE, {
    vol.Optional(CONF_CLASS): cv.string,
}))
HUMIDIFIER_SCHEMA = vol.Schema(virtual_schema(DEFAULT_HUMIDIFIER_VALUE, {
    vol.Optional(CONF_CLASS): cv.string,
}))


async def async_setup_platform(
        hass: HomeAssistant, config: ConfigType,
        async_add_entities: AddEntitiesCallback,
        _discovery_info: DiscoveryInfoType | None = None) -> None:
    if hass.data[COMPONENT_CONFIG].get(CONF_YAML_CONFIG, False):
        async_add_entities([VirtualHumidifier(config, True)], True)


async def async_setup_entry(
        hass: HomeAssistant, entry: ConfigEntry,
        async_add_entities: Callable[[list], None]) -> None:
    entities = []
    for entity in get_entity_configs(hass, entry.data[ATTR_GROUP_NAME], PLATFORM_DOMAIN):
        entities.append(VirtualHumidifier(HUMIDIFIER_SCHEMA(entity), False))
    async_add_entities(entities)


class VirtualHumidifier(VirtualEntity, HumidifierEntity):
    """Representation of a Virtual humidifier."""

    _attr_min_humidity = 0
    _attr_max_humidity = 100

    def __init__(self, config, old_style: bool):
        super().__init__(config, PLATFORM_DOMAIN, old_style)
        self._attr_device_class = config.get(CONF_CLASS)
        _LOGGER.info(f"VirtualHumidifier: {self.name} created")

    def _create_state(self, config):
        super()._create_state(config)
        self._attr_is_on = config.get(CONF_INITIAL_VALUE).lower() == STATE_ON
        self._attr_target_humidity = 50

    def _restore_state(self, state, config):
        super()._restore_state(state, config)
        self._attr_is_on = state.state.lower() == STATE_ON
        self._attr_target_humidity = state.attributes.get("humidity", 50)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()

    async def async_set_humidity(self, humidity: int) -> None:
        self._attr_target_humidity = humidity
        self.async_write_ha_state()

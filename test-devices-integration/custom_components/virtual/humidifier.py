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
    HumidifierEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
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

DEFAULT_HUMIDIFIER_VALUE = "off"

CONF_AVAILABLE_MODES = "available_modes"
CONF_MIN_HUMIDITY = "min_humidity"
CONF_MAX_HUMIDITY = "max_humidity"
CONF_TARGET_HUMIDITY_STEP = "target_humidity_step"

# What the humidifier could always do, before cloning existed: on/off and a
# target, and no mode menu.
DEFAULT_FEATURES = HumidifierEntityFeature(0)

BASE_SCHEMA = virtual_schema(DEFAULT_HUMIDIFIER_VALUE, {
    **FEATURES_SCHEMA,
    vol.Optional(CONF_CLASS): cv.string,
    vol.Optional(CONF_AVAILABLE_MODES): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_MIN_HUMIDITY): vol.Coerce(float),
    vol.Optional(CONF_MAX_HUMIDITY): vol.Coerce(float),
    vol.Optional(CONF_TARGET_HUMIDITY_STEP): vol.Coerce(float),
})

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(BASE_SCHEMA)
HUMIDIFIER_SCHEMA = vol.Schema(BASE_SCHEMA)


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
    """Representation of a Virtual humidifier / dehumidifier."""

    _attr_min_humidity = 0
    _attr_max_humidity = 100

    def __init__(self, config, old_style: bool):
        super().__init__(config, PLATFORM_DOMAIN, old_style)

        self._attr_device_class = config.get(CONF_CLASS)
        self._attr_supported_features = feature_flags(
            config, HumidifierEntityFeature, DEFAULT_FEATURES)
        self._attr_available_modes = optional_list(config, CONF_AVAILABLE_MODES)
        if not self._attr_available_modes:
            self._attr_supported_features &= ~HumidifierEntityFeature.MODES

        for attr, key in (("_attr_min_humidity", CONF_MIN_HUMIDITY),
                          ("_attr_max_humidity", CONF_MAX_HUMIDITY),
                          ("_attr_target_humidity_step", CONF_TARGET_HUMIDITY_STEP)):
            if (value := config.get(key)) is not None:
                setattr(self, attr, value)

        _LOGGER.info(f"VirtualHumidifier: {self.name} created")

    def _create_state(self, config):
        super()._create_state(config)
        self._attr_is_on = config.get(CONF_INITIAL_VALUE).lower() == STATE_ON
        self._attr_target_humidity = 50
        self._attr_current_humidity = 50
        if self._attr_available_modes:
            self._attr_mode = self._attr_available_modes[0]

    def _restore_state(self, state, config):
        super()._restore_state(state, config)
        self._attr_is_on = state.state.lower() == STATE_ON
        self._attr_target_humidity = state.attributes.get("humidity", 50)
        self._attr_current_humidity = state.attributes.get("current_humidity", 50)
        if self._attr_available_modes:
            self._attr_mode = (state.attributes.get("mode")
                               or self._attr_available_modes[0])

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()

    async def async_set_humidity(self, humidity: int) -> None:
        self._attr_target_humidity = humidity
        self.async_write_ha_state()

    async def async_set_mode(self, mode: str) -> None:
        self._attr_mode = mode
        self.async_write_ha_state()

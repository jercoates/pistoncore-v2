"""
Virtual siren — PistonCore addition to hass-virtual (FORK_NOTES.md).

A settable siren for testing. On/off via the native `siren.turn_on/off/toggle`
services (standalone-controllable; PistonCore uses the same). Modelled on switch.py.
"""

import logging
import voluptuous as vol
from collections.abc import Callable
from typing import Any

from homeassistant.components.siren import (
    DOMAIN as PLATFORM_DOMAIN,
    SirenEntity,
    SirenEntityFeature,
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

DEFAULT_SIREN_VALUE = "off"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(virtual_schema(DEFAULT_SIREN_VALUE, {}))
SIREN_SCHEMA = vol.Schema(virtual_schema(DEFAULT_SIREN_VALUE, {}))


async def async_setup_platform(
        hass: HomeAssistant, config: ConfigType,
        async_add_entities: AddEntitiesCallback,
        _discovery_info: DiscoveryInfoType | None = None) -> None:
    if hass.data[COMPONENT_CONFIG].get(CONF_YAML_CONFIG, False):
        async_add_entities([VirtualSiren(config, True)], True)


async def async_setup_entry(
        hass: HomeAssistant, entry: ConfigEntry,
        async_add_entities: Callable[[list], None]) -> None:
    entities = []
    for entity in get_entity_configs(hass, entry.data[ATTR_GROUP_NAME], PLATFORM_DOMAIN):
        entities.append(VirtualSiren(SIREN_SCHEMA(entity), False))
    async_add_entities(entities)


class VirtualSiren(VirtualEntity, SirenEntity):
    """Representation of a Virtual siren."""

    _attr_supported_features = SirenEntityFeature.TURN_ON | SirenEntityFeature.TURN_OFF

    def __init__(self, config, old_style: bool):
        super().__init__(config, PLATFORM_DOMAIN, old_style)
        _LOGGER.info(f"VirtualSiren: {self.name} created")

    def _create_state(self, config):
        super()._create_state(config)
        self._attr_is_on = config.get(CONF_INITIAL_VALUE).lower() == STATE_ON

    def _restore_state(self, state, config):
        super()._restore_state(state, config)
        self._attr_is_on = state.state.lower() == STATE_ON

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()

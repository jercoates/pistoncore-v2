"""
Virtual select — PistonCore addition to hass-virtual (FORK_NOTES.md).

A select is a setting with a fixed menu: an ESPHome log level, a thermostat
schedule, a washer cycle. Real devices expose a lot of them, and without this
platform a clone or an export dropped every one as "not reproducible".

The menu is `options`; the starting choice is `initial_value`. Driven by Home
Assistant's own `select.select_option` action, like the real thing. A starting
or restored value that is not on the menu falls back to the first option (with a
warning) rather than leaving the entity in a state HA itself would never report.
"""

import logging
from collections.abc import Callable

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.components.select import (
    DOMAIN as PLATFORM_DOMAIN,
    SelectEntity,
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

CONF_OPTIONS = "options"

# An empty initial value means "the first option": virtual_schema wants a default
# string and a menu is rarely known when the schema is built.
BASE_SCHEMA = virtual_schema("", {
    vol.Optional(CONF_OPTIONS, default=list): vol.All(cv.ensure_list, [cv.string]),
})

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(BASE_SCHEMA)
SELECT_SCHEMA = vol.Schema(BASE_SCHEMA)


async def async_setup_platform(
        hass: HomeAssistant, config: ConfigType,
        async_add_entities: AddEntitiesCallback,
        _discovery_info: DiscoveryInfoType | None = None) -> None:
    if hass.data[COMPONENT_CONFIG].get(CONF_YAML_CONFIG, False):
        async_add_entities([VirtualSelect(config, True)], True)


async def async_setup_entry(
        hass: HomeAssistant, entry: ConfigEntry,
        async_add_entities: Callable[[list], None]) -> None:
    entities = []
    for entity in get_entity_configs(hass, entry.data[ATTR_GROUP_NAME], PLATFORM_DOMAIN):
        entities.append(VirtualSelect(SELECT_SCHEMA(entity), False))
    async_add_entities(entities)


class VirtualSelect(VirtualEntity, SelectEntity):
    """Representation of a Virtual select."""

    def __init__(self, config, old_style: bool):
        super().__init__(config, PLATFORM_DOMAIN, old_style)
        self._attr_options = list(config.get(CONF_OPTIONS) or [])
        self._attr_current_option = None
        _LOGGER.info(f"VirtualSelect: {self.name} created")

    def _choose(self, wanted):
        """`wanted` if it is on the menu, else the first option, else nothing."""
        if wanted in self._attr_options:
            return wanted
        if wanted not in (None, "", "unknown", "unavailable"):
            _LOGGER.warning("virtual: %s: %r is not one of its options, using the "
                            "first", self.name, wanted)
        return self._attr_options[0] if self._attr_options else None

    def _create_state(self, config):
        super()._create_state(config)
        self._attr_current_option = self._choose(config.get(CONF_INITIAL_VALUE))

    def _restore_state(self, state, config):
        super()._restore_state(state, config)
        self._attr_current_option = self._choose(state.state)

    async def async_select_option(self, option: str) -> None:
        # SelectEntity's own service handler has already refused an option that
        # is not on the menu, exactly as it does for a real device.
        self._attr_current_option = option
        self._update_attributes()

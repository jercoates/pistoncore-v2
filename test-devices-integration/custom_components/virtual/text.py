"""
Virtual text — PistonCore addition to hass-virtual (FORK_NOTES.md).

A text entity is a free-text setting: a device name, a message, a schedule
string. Real devices expose a few, and without this platform a clone or an export
dropped them as "not reproducible".

Home Assistant's TextEntity RAISES when its value breaks its own length limits,
so a starting or restored value that does not fit becomes "no value" with a
warning, rather than an entity that errors every time its state is read.
A `password` text keeps no value at all: it is a secret, and this integration's
rule (see clone.py) is that nothing which could be one is copied.
"""

import logging
import re
from collections.abc import Callable

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.components.text import (
    DOMAIN as PLATFORM_DOMAIN,
    TextEntity,
    TextMode,
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

CONF_PATTERN = "pattern"
CONF_MODE = "mode"

BASE_SCHEMA = virtual_schema("", {
    vol.Optional(CONF_MIN, default=0): vol.All(vol.Coerce(int), vol.Range(min=0)),
    vol.Optional(CONF_MAX, default=100): vol.All(vol.Coerce(int), vol.Range(min=1)),
    vol.Optional(CONF_PATTERN): cv.string,
    vol.Optional(CONF_MODE, default=TextMode.TEXT.value): vol.In([m.value for m in TextMode]),
})

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(BASE_SCHEMA)
TEXT_SCHEMA = vol.Schema(BASE_SCHEMA)


async def async_setup_platform(
        hass: HomeAssistant, config: ConfigType,
        async_add_entities: AddEntitiesCallback,
        _discovery_info: DiscoveryInfoType | None = None) -> None:
    if hass.data[COMPONENT_CONFIG].get(CONF_YAML_CONFIG, False):
        async_add_entities([VirtualText(config, True)], True)


async def async_setup_entry(
        hass: HomeAssistant, entry: ConfigEntry,
        async_add_entities: Callable[[list], None]) -> None:
    entities = []
    for entity in get_entity_configs(hass, entry.data[ATTR_GROUP_NAME], PLATFORM_DOMAIN):
        entities.append(VirtualText(TEXT_SCHEMA(entity), False))
    async_add_entities(entities)


class VirtualText(VirtualEntity, TextEntity):
    """Representation of a Virtual text."""

    def __init__(self, config, old_style: bool):
        super().__init__(config, PLATFORM_DOMAIN, old_style)
        self._attr_native_min = config.get(CONF_MIN)
        self._attr_native_max = max(config.get(CONF_MAX), self._attr_native_min)
        self._attr_pattern = config.get(CONF_PATTERN)
        self._attr_mode = TextMode(config.get(CONF_MODE))
        self._attr_native_value = None
        _LOGGER.info(f"VirtualText: {self.name} created")

    def _fits(self, value) -> bool:
        if not isinstance(value, str):
            return False
        if not self._attr_native_min <= len(value) <= self._attr_native_max:
            return False
        return self._attr_pattern is None or re.fullmatch(self._attr_pattern, value) is not None

    def _accept(self, value):
        """`value` if it is something this entity could hold, else no value."""
        if self._attr_mode is TextMode.PASSWORD:
            return None
        if value in (None, "", "unknown", "unavailable"):
            return None
        if self._fits(value):
            return value
        _LOGGER.warning("virtual: %s: %r does not fit its own limits, so it starts "
                        "with no value", self.name, value)
        return None

    def _create_state(self, config):
        super()._create_state(config)
        self._attr_native_value = self._accept(config.get(CONF_INITIAL_VALUE))

    def _restore_state(self, state, config):
        super()._restore_state(state, config)
        self._attr_native_value = self._accept(state.state)

    async def async_set_value(self, value: str) -> None:
        # TextEntity's own service handler has already enforced min/max/pattern.
        self._attr_native_value = value
        self._update_attributes()

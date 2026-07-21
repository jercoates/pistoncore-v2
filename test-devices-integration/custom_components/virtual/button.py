"""
Virtual button — PistonCore addition to hass-virtual (FORK_NOTES.md).

A pressable button for testing. Press via the native `button.press` service
(standalone-controllable; PistonCore uses the same). A button is momentary: Home
Assistant records the press timestamp as its state; there is no on/off to restore.
"""

import logging
import voluptuous as vol
from collections.abc import Callable

from homeassistant.components.button import (
    DOMAIN as PLATFORM_DOMAIN,
    ButtonEntity,
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

# Buttons are stateless; initial_value is unused but virtual_schema wants a default.
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(virtual_schema("", {}))
BUTTON_SCHEMA = vol.Schema(virtual_schema("", {}))


async def async_setup_platform(
        hass: HomeAssistant, config: ConfigType,
        async_add_entities: AddEntitiesCallback,
        _discovery_info: DiscoveryInfoType | None = None) -> None:
    if hass.data[COMPONENT_CONFIG].get(CONF_YAML_CONFIG, False):
        async_add_entities([VirtualButton(config, True)], True)


async def async_setup_entry(
        hass: HomeAssistant, entry: ConfigEntry,
        async_add_entities: Callable[[list], None]) -> None:
    entities = []
    for entity in get_entity_configs(hass, entry.data[ATTR_GROUP_NAME], PLATFORM_DOMAIN):
        entities.append(VirtualButton(BUTTON_SCHEMA(entity), False))
    async_add_entities(entities)


class VirtualButton(VirtualEntity, ButtonEntity):
    """Representation of a Virtual button."""

    def __init__(self, config, old_style: bool):
        super().__init__(config, PLATFORM_DOMAIN, old_style)
        _LOGGER.info(f"VirtualButton: {self.name} created")

    async def async_press(self) -> None:
        # HA records the press timestamp as the entity state automatically.
        _LOGGER.debug(f"{self.name} pressed")

"""
Virtual siren — PistonCore addition to hass-virtual (FORK_NOTES.md).

A settable siren for testing. On/off via the native `siren.turn_on/off/toggle`
services (standalone-controllable; PistonCore uses the same). Modelled on switch.py.
"""

import logging
import voluptuous as vol
from collections.abc import Callable
from typing import Any

import homeassistant.helpers.config_validation as cv
from homeassistant.components.siren import (
    DOMAIN as PLATFORM_DOMAIN,
    SirenEntity,
    SirenEntityFeature,
)
# from .const, where they are defined — the package re-export has moved before.
from homeassistant.components.siren.const import (
    ATTR_DURATION,
    ATTR_TONE,
    ATTR_VOLUME_LEVEL,
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

DEFAULT_SIREN_VALUE = "off"

CONF_AVAILABLE_TONES = "available_tones"

# What the siren could always do, before cloning existed.
DEFAULT_FEATURES = SirenEntityFeature.TURN_ON | SirenEntityFeature.TURN_OFF

BASE_SCHEMA = virtual_schema(DEFAULT_SIREN_VALUE, {
    **FEATURES_SCHEMA,
    vol.Optional(CONF_AVAILABLE_TONES): vol.All(cv.ensure_list, [cv.string]),
})

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(BASE_SCHEMA)
SIREN_SCHEMA = vol.Schema(BASE_SCHEMA)


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
    """Representation of a Virtual siren.

    Real sirens differ mostly in whether they take a tone, a volume and a
    duration — which is exactly what a webCoRE siren/chime piston sets. The
    clone records whatever it was asked for so the bench can show what the
    compiler actually sent.
    """

    def __init__(self, config, old_style: bool):
        super().__init__(config, PLATFORM_DOMAIN, old_style)

        self._attr_supported_features = feature_flags(
            config, SirenEntityFeature, DEFAULT_FEATURES)
        self._attr_available_tones = optional_list(config, CONF_AVAILABLE_TONES)
        if not self._attr_available_tones:
            self._attr_supported_features &= ~SirenEntityFeature.TONES

        _LOGGER.info(f"VirtualSiren: {self.name} created")

    def _create_state(self, config):
        super()._create_state(config)
        self._attr_is_on = config.get(CONF_INITIAL_VALUE).lower() == STATE_ON
        self._last_call = {}

    def _restore_state(self, state, config):
        super()._restore_state(state, config)
        self._attr_is_on = state.state.lower() == STATE_ON
        self._last_call = {}

    def _update_attributes(self):
        super()._update_attributes()
        # Show the last tone/volume/duration asked for, so a piston's siren
        # command can be verified without owning a siren.
        self._attr_extra_state_attributes.update(getattr(self, "_last_call", {}))

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._last_call = {
            key: kwargs[key]
            for key in (ATTR_TONE, ATTR_VOLUME_LEVEL, ATTR_DURATION)
            if key in kwargs
        }
        if self._last_call:
            _LOGGER.info(f"{self.name} on with {self._last_call}")
        self._attr_is_on = True
        self._update_attributes()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()

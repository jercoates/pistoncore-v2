"""
This component provides support for a virtual cover.

"""

import logging
import voluptuous as vol
from typing import Any
from collections.abc import Callable

import homeassistant.helpers.config_validation as cv
from homeassistant.components.cover import (
    CoverEntity,
    CoverEntityFeature,
    DOMAIN as PLATFORM_DOMAIN
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.config_validation import PLATFORM_SCHEMA

from . import get_entity_configs
from .const import *
from .entity import (
    FEATURES_SCHEMA,
    VirtualOpenableEntity,
    feature_flags,
    virtual_schema,
    positive_tick,
)


_LOGGER = logging.getLogger(__name__)

DEPENDENCIES = [COMPONENT_DOMAIN]

DEFAULT_COVER_VALUE = "open"

# What the cover could always do, before cloning existed. A real garage door
# usually reports only OPEN|CLOSE|STOP with no position control — cloning that
# matters, because a piston that sets a position on it is a piston that will
# fail in the house and must fail on the bench too.
DEFAULT_FEATURES = (
    CoverEntityFeature.OPEN
    | CoverEntityFeature.CLOSE
    | CoverEntityFeature.STOP
    | CoverEntityFeature.SET_POSITION
)

BASE_SCHEMA = virtual_schema(DEFAULT_COVER_VALUE, {
    **FEATURES_SCHEMA,
    vol.Optional(CONF_CLASS): cv.string,
    vol.Optional(CONF_OPEN_CLOSE_DURATION, default=10): cv.positive_int,
    vol.Optional(CONF_OPEN_CLOSE_TICK, default=1): positive_tick,
})

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(BASE_SCHEMA)
COVER_SCHEMA = vol.Schema(BASE_SCHEMA)


async def async_setup_platform(hass, config, async_add_entities, _discovery_info=None):
    if hass.data[COMPONENT_CONFIG].get(CONF_YAML_CONFIG, False):
        _LOGGER.debug("setting up old config...")

        sensors = [VirtualCover(config, True)]
        async_add_entities(sensors, True)


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: Callable[[list], None],
) -> None:
    _LOGGER.debug("setting up the entries...")

    entities = []
    for entity in get_entity_configs(hass, entry.data[ATTR_GROUP_NAME], PLATFORM_DOMAIN):
        entity = COVER_SCHEMA(entity)
        entities.append(VirtualCover(entity, False))
    async_add_entities(entities)


class VirtualCover(VirtualOpenableEntity, CoverEntity):
    """Representation of a Virtual cover."""

    def __init__(self, config, old_style : bool):
        """Initialize the Virtual cover device."""
        super().__init__(config, PLATFORM_DOMAIN, old_style)

        self._attr_supported_features = feature_flags(
            config, CoverEntityFeature, DEFAULT_FEATURES)
        self._attr_current_cover_tilt_position = 0

        _LOGGER.info(f"VirtualCover: {self.name} created")

    @property
    def current_cover_position(self) -> int | None:
        return self._current_position

    @property
    def current_cover_tilt_position(self) -> int | None:
        if self._attr_supported_features & CoverEntityFeature.SET_TILT_POSITION:
            return self._attr_current_cover_tilt_position
        return None

    def _set_tilt(self, position: int) -> None:
        self._attr_current_cover_tilt_position = max(0, min(100, int(position)))
        self.async_write_ha_state()

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:
        self._set_tilt(100)

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:
        self._set_tilt(0)

    async def async_stop_cover_tilt(self, **kwargs: Any) -> None:
        self.async_write_ha_state()

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        self._set_tilt(kwargs["tilt_position"])

    async def async_open_cover(self, **kwargs: Any) -> None:
        _LOGGER.info(f"opening {self.name}")
        self._set_position(100)

    async def async_close_cover(self, **kwargs: Any) -> None:
        _LOGGER.info(f"closing {self.name}")
        self._set_position(0)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        _LOGGER.info(f"stopping {self.name}")
        self._stop()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        _LOGGER.info(f"setting {self.name} position {kwargs['position']}")
        self._set_position(kwargs['position'])

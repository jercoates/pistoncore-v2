"""
Virtual media_player (speaker) — PistonCore addition to hass-virtual (FORK_NOTES.md).

A settable media player for testing webCoRE speaker pistons. State and volume are
driven through native `media_player.*` services (media_play/pause/stop,
volume_set, volume_mute, turn_on/off) — standalone-controllable, and PistonCore
uses the same. Modelled on switch.py with a richer state model.
"""

import logging
import voluptuous as vol
from collections.abc import Callable
from typing import Any

from homeassistant.components.media_player import (
    DOMAIN as PLATFORM_DOMAIN,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
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

DEFAULT_MEDIA_VALUE = "idle"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(virtual_schema(DEFAULT_MEDIA_VALUE, {}))
MEDIA_SCHEMA = vol.Schema(virtual_schema(DEFAULT_MEDIA_VALUE, {}))

_STATES = {s.value: s for s in MediaPlayerState}


async def async_setup_platform(
        hass: HomeAssistant, config: ConfigType,
        async_add_entities: AddEntitiesCallback,
        _discovery_info: DiscoveryInfoType | None = None) -> None:
    if hass.data[COMPONENT_CONFIG].get(CONF_YAML_CONFIG, False):
        async_add_entities([VirtualMediaPlayer(config, True)], True)


async def async_setup_entry(
        hass: HomeAssistant, entry: ConfigEntry,
        async_add_entities: Callable[[list], None]) -> None:
    entities = []
    for entity in get_entity_configs(hass, entry.data[ATTR_GROUP_NAME], PLATFORM_DOMAIN):
        entities.append(VirtualMediaPlayer(MEDIA_SCHEMA(entity), False))
    async_add_entities(entities)


class VirtualMediaPlayer(VirtualEntity, MediaPlayerEntity):
    """Representation of a Virtual media player."""

    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
    )

    def __init__(self, config, old_style: bool):
        super().__init__(config, PLATFORM_DOMAIN, old_style)
        _LOGGER.info(f"VirtualMediaPlayer: {self.name} created")

    def _create_state(self, config):
        super()._create_state(config)
        self._attr_state = _STATES.get(
            config.get(CONF_INITIAL_VALUE, DEFAULT_MEDIA_VALUE).lower(), MediaPlayerState.IDLE)
        self._attr_volume_level = 0.5
        self._attr_is_volume_muted = False

    def _restore_state(self, state, config):
        super()._restore_state(state, config)
        self._attr_state = _STATES.get(state.state, MediaPlayerState.IDLE)
        self._attr_volume_level = state.attributes.get("volume_level", 0.5)
        self._attr_is_volume_muted = state.attributes.get("is_volume_muted", False)

    def _set_state(self, new_state: MediaPlayerState) -> None:
        self._attr_state = new_state
        self.async_write_ha_state()

    async def async_media_play(self) -> None:
        self._set_state(MediaPlayerState.PLAYING)

    async def async_media_pause(self) -> None:
        self._set_state(MediaPlayerState.PAUSED)

    async def async_media_stop(self) -> None:
        self._set_state(MediaPlayerState.IDLE)

    async def async_turn_on(self) -> None:
        self._set_state(MediaPlayerState.ON)

    async def async_turn_off(self) -> None:
        self._set_state(MediaPlayerState.OFF)

    async def async_set_volume_level(self, volume: float) -> None:
        self._attr_volume_level = volume
        self.async_write_ha_state()

    async def async_mute_volume(self, mute: bool) -> None:
        self._attr_is_volume_muted = mute
        self.async_write_ha_state()

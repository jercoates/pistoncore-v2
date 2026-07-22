"""
Virtual event — PistonCore addition to hass-virtual (FORK_NOTES.md).

A momentary EVENT entity for testing button / scene / multi-tap pistons — the
Inovelli & Zooz double-tap / held / pushed controllers, and webCoRE's Button /
Holdable Button capabilities (which read HA's `event` domain). Fire a chosen
event type with `virtual.fire_event` — usable standalone from Developer Tools,
and PistonCore's panel drives the same service.

Events are momentary: HA records the last fired event type + a timestamp; there
is no on/off state to restore.
"""

import logging
import voluptuous as vol
from collections.abc import Callable

import homeassistant.helpers.config_validation as cv
from homeassistant.components.event import (
    DOMAIN as PLATFORM_DOMAIN,
    EventEntity,
    EventDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers.config_validation import PLATFORM_SCHEMA
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import get_entity_configs, get_entity_from_domain
from .const import *
from .entity import VirtualEntity, virtual_schema


_LOGGER = logging.getLogger(__name__)

DEPENDENCIES = [COMPONENT_DOMAIN]

# Common controller event types; ad-hoc ones are accepted at fire time too.
DEFAULT_EVENT_TYPES = ["press", "double_press", "triple_press", "hold", "release"]

_EXTRA = {
    vol.Optional(CONF_CLASS): cv.string,
    vol.Optional("types"): vol.All(cv.ensure_list, [cv.string]),
}
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(virtual_schema("", _EXTRA))
EVENT_SCHEMA = vol.Schema(virtual_schema("", _EXTRA))

SERVICE_FIRE_EVENT = "fire_event"
FIRE_SCHEMA = vol.Schema({
    vol.Required(ATTR_ENTITY_ID): cv.comp_entity_ids,
    vol.Required("event_type"): cv.string,
})


def setup_services(hass: HomeAssistant) -> None:
    async def _fire(call):
        for entity_id in call.data[ATTR_ENTITY_ID]:
            get_entity_from_domain(hass, PLATFORM_DOMAIN, entity_id).fire(call.data["event_type"])

    if not hass.services.has_service(COMPONENT_DOMAIN, SERVICE_FIRE_EVENT):
        hass.services.async_register(COMPONENT_DOMAIN, SERVICE_FIRE_EVENT, _fire, schema=FIRE_SCHEMA)


async def async_setup_platform(
        hass: HomeAssistant, config: ConfigType,
        async_add_entities: AddEntitiesCallback,
        _discovery_info: DiscoveryInfoType | None = None) -> None:
    if hass.data[COMPONENT_CONFIG].get(CONF_YAML_CONFIG, False):
        async_add_entities([VirtualEvent(config, True)], True)
        setup_services(hass)


async def async_setup_entry(
        hass: HomeAssistant, entry: ConfigEntry,
        async_add_entities: Callable[[list], None]) -> None:
    entities = []
    for entity in get_entity_configs(hass, entry.data[ATTR_GROUP_NAME], PLATFORM_DOMAIN):
        entities.append(VirtualEvent(EVENT_SCHEMA(entity), False))
    async_add_entities(entities)
    setup_services(hass)


class VirtualEvent(VirtualEntity, EventEntity):
    """Representation of a Virtual event (button/scene controller)."""

    def __init__(self, config, old_style: bool):
        super().__init__(config, PLATFORM_DOMAIN, old_style)
        self._attr_event_types = list(config.get("types") or DEFAULT_EVENT_TYPES)
        dc = config.get(CONF_CLASS)
        if dc:
            try:
                self._attr_device_class = EventDeviceClass(dc)
            except ValueError:
                pass
        _LOGGER.info(f"VirtualEvent: {self.name} created")

    def fire(self, event_type: str) -> None:
        """PistonCore extension: fire a chosen event type (for tests)."""
        if event_type not in self._attr_event_types:
            # accept ad-hoc types so a piston expecting an integration-specific
            # value (e.g. Z2M vs ZHA) can still be exercised.
            self._attr_event_types = self._attr_event_types + [event_type]
        _LOGGER.debug(f"{self.name} fire {event_type!r}")
        self._trigger_event(event_type)
        self.async_write_ha_state()

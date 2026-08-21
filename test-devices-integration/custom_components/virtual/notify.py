"""
Virtual notifier — PistonCore addition to hass-virtual (FORK_NOTES.md).

Somewhere for a piston's notifications to LAND, so "did it notify, and with what"
is a thing you can check instead of infer.

SMS AND APP ARE THE MINIMUM (Jeremy, 2026-08-13). Those are the two a webCoRE
piston actually reaches for, so a bench without both cannot test the notify path
at all. Make them with `class: sms` and `class: app`; the class is free text, so
any other notifier a piston targets can be added the same way without code.

WHAT IT RECORDS
Each entity keeps the last message, the last title, and a COUNT. The count is
what distinguishes "notified once" from "notified twice" — the same reason the
camera cycles frames. It also fires `virtual_notify_sent` on the event bus with
the same detail plus a sequence number.

ASSERT ON THE EVENT, NOT THE ATTRIBUTES, when testing pistons that can fire in
quick succession: attribute reads race against a second notification, while the
event stream keeps them in order and keeps both.

A NOTE ON WHAT THE COMPILER CURRENTLY SENDS
PistonCore's vocab sends most notification commands to `notify.notify` (a
service, not an entity), and only `sendEmail` to `notify.send_message`. A notify
ENTITY only ever receives `send_message` aimed at it. So pointing a piston at one
of these tests the entity path; the `notify.notify` path is a separate question
recorded in the compiler notes, not something this platform can answer.
"""

import logging
from collections.abc import Callable

import voluptuous as vol

import homeassistant.helpers.config_validation as cv

from homeassistant.components.notify import (
    DOMAIN as PLATFORM_DOMAIN,
    NotifyEntity,
    NotifyEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.config_validation import PLATFORM_SCHEMA
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import get_entity_configs
from .const import *
from .entity import FEATURES_SCHEMA, VirtualEntity, feature_flags, virtual_schema


_LOGGER = logging.getLogger(__name__)

DEPENDENCIES = [COMPONENT_DOMAIN]

EVENT_SENT = "virtual_notify_sent"

# A notifier has no state to restore; initial_value is unused but virtual_schema
# wants a default, same as button and camera.
BASE_SCHEMA = virtual_schema("", {
    **FEATURES_SCHEMA,
    vol.Optional(CONF_CLASS): cv.string,
})

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(BASE_SCHEMA)
NOTIFY_SCHEMA = vol.Schema(BASE_SCHEMA)


async def async_setup_platform(
        hass: HomeAssistant, config: ConfigType,
        async_add_entities: AddEntitiesCallback,
        _discovery_info: DiscoveryInfoType | None = None) -> None:
    if hass.data[COMPONENT_CONFIG].get(CONF_YAML_CONFIG, False):
        async_add_entities([VirtualNotify(config, True)], True)


async def async_setup_entry(
        hass: HomeAssistant, entry: ConfigEntry,
        async_add_entities: Callable[[list], None]) -> None:
    entities = []
    for entity in get_entity_configs(hass, entry.data[ATTR_GROUP_NAME], PLATFORM_DOMAIN):
        entities.append(VirtualNotify(NOTIFY_SCHEMA(entity), False))
    async_add_entities(entities)


class VirtualNotify(VirtualEntity, NotifyEntity):
    """Representation of a Virtual notifier."""

    def __init__(self, config, old_style: bool):
        super().__init__(config, PLATFORM_DOMAIN, old_style)
        # A real notifier may or may not take a title; a clone must say what the
        # original said rather than always claiming it does.
        self._attr_supported_features = feature_flags(
            config, NotifyEntityFeature, NotifyEntityFeature.TITLE)
        self._kind = config.get(CONF_CLASS) or "generic"
        self._count = 0
        self._last_message = None
        self._last_title = None
        _LOGGER.info(f"VirtualNotify: {self.name} created ({self._kind})")

    def _create_state(self, config):
        super()._create_state(config)
        self._count = 0

    def _restore_state(self, state, config):
        super()._restore_state(state, config)
        # The count is deliberately NOT restored: it answers "how many times did
        # this test run notify", which starts again with the run.
        self._count = 0

    def _update_attributes(self):
        super()._update_attributes()
        self._attr_extra_state_attributes.update({
            "target_key": self._kind,
            "sequence": self._count,
            "last_message": self._last_message,
            "last_title": self._last_title,
        })

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        self._count += 1
        self._last_message = message
        self._last_title = title
        self._update_attributes()
        # NotifyEntity's own machinery writes state after this returns (it also
        # stamps the last-notified timestamp), so writing here would push a state
        # update carrying a stale timestamp. Verified on 2026.7.4 and 2026.8.0b3
        # by watching the attributes land without an explicit write.
        self.hass.bus.async_fire(EVENT_SENT, {
            "entity_id": self.entity_id,
            "target_key": self._kind,
            "message": message,
            "title": title,
            "sequence": self._count,
        })
        _LOGGER.info(f"{self.name} notified ({self._kind}) #{self._count}: {message!r}")

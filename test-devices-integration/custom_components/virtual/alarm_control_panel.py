"""
Virtual alarm_control_panel — PistonCore addition to hass-virtual (FORK_NOTES.md).

A settable alarm panel for testing webCoRE HSM / alarm pistons. Arming and
disarming go through the NATIVE `alarm_control_panel.*` services (alarm_arm_away,
alarm_arm_home, alarm_disarm, ...), so it is fully controllable standalone from
Home Assistant, and PistonCore drives the same services. No code required.

Modelled on switch.py; only the state model differs (arm states instead of on/off).
"""

import logging
import voluptuous as vol
from collections.abc import Callable

from homeassistant.components.alarm_control_panel import (
    DOMAIN as PLATFORM_DOMAIN,
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
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

DEFAULT_ALARM_VALUE = "disarmed"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(virtual_schema(DEFAULT_ALARM_VALUE, {}))
ALARM_SCHEMA = vol.Schema(virtual_schema(DEFAULT_ALARM_VALUE, {}))

# initial_value string -> AlarmControlPanelState (e.g. "armed_away", "disarmed")
_STATES = {s.value: s for s in AlarmControlPanelState}


async def async_setup_platform(
        hass: HomeAssistant,
        config: ConfigType,
        async_add_entities: AddEntitiesCallback,
        _discovery_info: DiscoveryInfoType | None = None,
) -> None:
    if hass.data[COMPONENT_CONFIG].get(CONF_YAML_CONFIG, False):
        async_add_entities([VirtualAlarmControlPanel(config, True)], True)


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: Callable[[list], None],
) -> None:
    entities = []
    for entity in get_entity_configs(hass, entry.data[ATTR_GROUP_NAME], PLATFORM_DOMAIN):
        entity = ALARM_SCHEMA(entity)
        entities.append(VirtualAlarmControlPanel(entity, False))
    async_add_entities(entities)


class VirtualAlarmControlPanel(VirtualEntity, AlarmControlPanelEntity):
    """Representation of a Virtual alarm control panel."""

    _attr_code_arm_required = False
    _attr_code_format = None
    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_HOME
        | AlarmControlPanelEntityFeature.ARM_AWAY
        | AlarmControlPanelEntityFeature.ARM_NIGHT
        | AlarmControlPanelEntityFeature.ARM_VACATION
        | AlarmControlPanelEntityFeature.ARM_CUSTOM_BYPASS
        | AlarmControlPanelEntityFeature.TRIGGER
    )

    def __init__(self, config, old_style: bool):
        """Initialize the Virtual alarm control panel."""
        super().__init__(config, PLATFORM_DOMAIN, old_style)
        _LOGGER.info(f"VirtualAlarmControlPanel: {self.name} created")

    def _create_state(self, config):
        super()._create_state(config)
        self._attr_alarm_state = _STATES.get(
            config.get(CONF_INITIAL_VALUE, DEFAULT_ALARM_VALUE).lower(),
            AlarmControlPanelState.DISARMED)

    def _restore_state(self, state, config):
        super()._restore_state(state, config)
        self._attr_alarm_state = _STATES.get(state.state, AlarmControlPanelState.DISARMED)

    def _set(self, new_state: AlarmControlPanelState) -> None:
        _LOGGER.debug(f"{self.name} -> {new_state}")
        self._attr_alarm_state = new_state
        self.async_write_ha_state()

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        self._set(AlarmControlPanelState.DISARMED)

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        self._set(AlarmControlPanelState.ARMED_HOME)

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        self._set(AlarmControlPanelState.ARMED_AWAY)

    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        self._set(AlarmControlPanelState.ARMED_NIGHT)

    async def async_alarm_arm_vacation(self, code: str | None = None) -> None:
        self._set(AlarmControlPanelState.ARMED_VACATION)

    async def async_alarm_arm_custom_bypass(self, code: str | None = None) -> None:
        self._set(AlarmControlPanelState.ARMED_CUSTOM_BYPASS)

    async def async_alarm_trigger(self, code: str | None = None) -> None:
        self._set(AlarmControlPanelState.TRIGGERED)

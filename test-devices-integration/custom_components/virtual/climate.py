"""
Virtual climate (thermostat) — PistonCore addition to hass-virtual (FORK_NOTES.md).

A settable thermostat for testing webCoRE thermostat pistons.
- Target temperature: native `climate.set_temperature`.
- Mode: native `climate.set_hvac_mode` (and `climate.turn_on/off`).
- CURRENT temperature: there is no native HA service to set a thermostat's current
  temperature, but testing "if temp drops below X" needs it — so this platform adds
  `virtual.set_current_temperature` (an HA service, usable standalone and by
  PistonCore). Modelled on sensor.py's `virtual.set` pattern.
"""

import logging
import voluptuous as vol
from collections.abc import Callable
from typing import Any

import homeassistant.helpers.config_validation as cv
from homeassistant.components.climate import (
    DOMAIN as PLATFORM_DOMAIN,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.config_validation import PLATFORM_SCHEMA
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import get_entity_configs, get_entity_from_domain
from .const import *
from .entity import VirtualEntity, virtual_schema


_LOGGER = logging.getLogger(__name__)

DEPENDENCIES = [COMPONENT_DOMAIN]

DEFAULT_CLIMATE_VALUE = "heat"  # initial hvac mode

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(virtual_schema(DEFAULT_CLIMATE_VALUE, {}))
CLIMATE_SCHEMA = vol.Schema(virtual_schema(DEFAULT_CLIMATE_VALUE, {}))

SERVICE_SET_CURRENT_TEMPERATURE = "set_current_temperature"
SET_CURRENT_TEMP_SCHEMA = vol.Schema({
    vol.Required(ATTR_ENTITY_ID): cv.comp_entity_ids,
    vol.Required(ATTR_VALUE): vol.Coerce(float),
})

_HVAC_MODES = {m.value: m for m in HVACMode}


def setup_services(hass: HomeAssistant) -> None:
    async def _set_current_temperature(call):
        for entity_id in call.data[ATTR_ENTITY_ID]:
            get_entity_from_domain(hass, PLATFORM_DOMAIN, entity_id) \
                .set_current_temperature(call.data[ATTR_VALUE])

    if not hass.services.has_service(COMPONENT_DOMAIN, SERVICE_SET_CURRENT_TEMPERATURE):
        hass.services.async_register(
            COMPONENT_DOMAIN, SERVICE_SET_CURRENT_TEMPERATURE,
            _set_current_temperature, schema=SET_CURRENT_TEMP_SCHEMA)


async def async_setup_platform(
        hass: HomeAssistant, config: ConfigType,
        async_add_entities: AddEntitiesCallback,
        _discovery_info: DiscoveryInfoType | None = None) -> None:
    if hass.data[COMPONENT_CONFIG].get(CONF_YAML_CONFIG, False):
        async_add_entities([VirtualClimate(config, True)], True)
        setup_services(hass)


async def async_setup_entry(
        hass: HomeAssistant, entry: ConfigEntry,
        async_add_entities: Callable[[list], None]) -> None:
    entities = []
    for entity in get_entity_configs(hass, entry.data[ATTR_GROUP_NAME], PLATFORM_DOMAIN):
        entities.append(VirtualClimate(CLIMATE_SCHEMA(entity), False))
    async_add_entities(entities)
    setup_services(hass)


class VirtualClimate(VirtualEntity, ClimateEntity):
    """Representation of a Virtual thermostat."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [
        HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.HEAT_COOL, HVACMode.AUTO,
    ]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, config, old_style: bool):
        super().__init__(config, PLATFORM_DOMAIN, old_style)
        _LOGGER.info(f"VirtualClimate: {self.name} created")

    def _create_state(self, config):
        super()._create_state(config)
        self._attr_hvac_mode = _HVAC_MODES.get(
            config.get(CONF_INITIAL_VALUE, DEFAULT_CLIMATE_VALUE).lower(), HVACMode.HEAT)
        self._attr_target_temperature = 21.0
        self._attr_current_temperature = 20.0

    def _restore_state(self, state, config):
        super()._restore_state(state, config)
        self._attr_hvac_mode = _HVAC_MODES.get(state.state, HVACMode.HEAT)
        self._attr_target_temperature = state.attributes.get(ATTR_TEMPERATURE, 21.0)
        self._attr_current_temperature = state.attributes.get("current_temperature", 20.0)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self._attr_target_temperature = temp
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        self._attr_hvac_mode = HVACMode.HEAT
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        self._attr_hvac_mode = HVACMode.OFF
        self.async_write_ha_state()

    def set_current_temperature(self, value: float) -> None:
        """PistonCore extension: set the reported current temperature (for tests)."""
        _LOGGER.debug(f"{self.name} current_temperature -> {value}")
        self._attr_current_temperature = float(value)
        self.async_schedule_update_ha_state()

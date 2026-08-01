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
# from .const, where they are defined — the package re-export has moved before.
from homeassistant.components.climate.const import (
    ATTR_HVAC_MODE,
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.config_validation import PLATFORM_SCHEMA
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import get_entity_configs, get_entity_from_domain
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

DEFAULT_CLIMATE_VALUE = "heat"  # initial hvac mode

CONF_HVAC_MODES = "hvac_modes"
CONF_PRESET_MODES = "preset_modes"
CONF_FAN_MODES = "fan_modes"
CONF_SWING_MODES = "swing_modes"
CONF_SWING_HORIZONTAL_MODES = "swing_horizontal_modes"
CONF_MIN_TEMP = "min_temp"
CONF_MAX_TEMP = "max_temp"
CONF_TARGET_TEMP_STEP = "target_temp_step"
CONF_TEMPERATURE_UNIT = "temperature_unit"
CONF_MIN_HUMIDITY = "min_humidity"
CONF_MAX_HUMIDITY = "max_humidity"
CONF_TARGET_HUMIDITY_STEP = "target_humidity_step"

# What the thermostat could always do, before cloning existed.
DEFAULT_FEATURES = (
    ClimateEntityFeature.TARGET_TEMPERATURE
    | ClimateEntityFeature.TURN_ON
    | ClimateEntityFeature.TURN_OFF
)
DEFAULT_HVAC_MODES = [
    HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.HEAT_COOL, HVACMode.AUTO,
]

BASE_SCHEMA = virtual_schema(DEFAULT_CLIMATE_VALUE, {
    **FEATURES_SCHEMA,
    vol.Optional(CONF_HVAC_MODES): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_PRESET_MODES): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_FAN_MODES): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_SWING_MODES): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_SWING_HORIZONTAL_MODES): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_MIN_TEMP): vol.Coerce(float),
    vol.Optional(CONF_MAX_TEMP): vol.Coerce(float),
    vol.Optional(CONF_TARGET_TEMP_STEP): vol.Coerce(float),
    vol.Optional(CONF_TEMPERATURE_UNIT): cv.string,
    vol.Optional(CONF_MIN_HUMIDITY): vol.Coerce(float),
    vol.Optional(CONF_MAX_HUMIDITY): vol.Coerce(float),
    vol.Optional(CONF_TARGET_HUMIDITY_STEP): vol.Coerce(float),
})

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(BASE_SCHEMA)
CLIMATE_SCHEMA = vol.Schema(BASE_SCHEMA)

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
    """Representation of a Virtual thermostat.

    Everything a real thermostat advertises — its mode list, its fan and preset
    menus, its temperature limits and whether it takes a single setpoint or a
    heat/cool range — is taken from the clone config when present. Jeremy's
    ecobee reports supported_features=155 (single setpoint AND range, fan modes,
    preset modes); before this the virtual thermostat could only ever be a
    plain single-setpoint heater, so a clone of it was not a clone.
    """

    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, config, old_style: bool):
        super().__init__(config, PLATFORM_DOMAIN, old_style)

        self._attr_supported_features = feature_flags(
            config, ClimateEntityFeature, DEFAULT_FEATURES)

        modes = optional_list(config, CONF_HVAC_MODES)
        if modes:
            # Keep only modes HA actually knows, but never end up with an empty
            # list — an entity with no hvac_modes cannot be set at all.
            known = [_HVAC_MODES[m] for m in (s.lower() for s in modes) if m in _HVAC_MODES]
            self._attr_hvac_modes = known or list(DEFAULT_HVAC_MODES)
        else:
            self._attr_hvac_modes = list(DEFAULT_HVAC_MODES)

        self._attr_preset_modes = optional_list(config, CONF_PRESET_MODES)
        self._attr_fan_modes = optional_list(config, CONF_FAN_MODES)
        self._attr_swing_modes = optional_list(config, CONF_SWING_MODES)
        self._attr_swing_horizontal_modes = optional_list(
            config, CONF_SWING_HORIZONTAL_MODES)

        # A menu the device doesn't have must not be advertised as a feature,
        # or HA offers a dropdown with nothing in it.
        for feature, menu in (
                (ClimateEntityFeature.PRESET_MODE, self._attr_preset_modes),
                (ClimateEntityFeature.FAN_MODE, self._attr_fan_modes),
                (ClimateEntityFeature.SWING_MODE, self._attr_swing_modes),
                (ClimateEntityFeature.SWING_HORIZONTAL_MODE,
                 self._attr_swing_horizontal_modes)):
            if not menu:
                self._attr_supported_features &= ~feature

        if (unit := config.get(CONF_TEMPERATURE_UNIT)) is not None:
            # Cloned limits arrive in whatever unit HA reports them in, so the
            # clone has to declare that same unit or HA converts them twice.
            self._attr_temperature_unit = (
                UnitOfTemperature.FAHRENHEIT if "F" in unit.upper()
                else UnitOfTemperature.CELSIUS)
        for attr, key in (("_attr_min_temp", CONF_MIN_TEMP),
                          ("_attr_max_temp", CONF_MAX_TEMP),
                          ("_attr_target_temperature_step", CONF_TARGET_TEMP_STEP),
                          ("_attr_min_humidity", CONF_MIN_HUMIDITY),
                          ("_attr_max_humidity", CONF_MAX_HUMIDITY),
                          ("_attr_target_humidity_step", CONF_TARGET_HUMIDITY_STEP)):
            if (value := config.get(key)) is not None:
                setattr(self, attr, value)

        _LOGGER.info(f"VirtualClimate: {self.name} created")

    @property
    def _has(self) -> ClimateEntityFeature:
        return self._attr_supported_features

    def _midpoint(self) -> float:
        """A starting setpoint inside this thermostat's own limits — 21°C is
        outside the range of a Fahrenheit clone."""
        low, high = self.min_temp, self.max_temp
        default = 21.0 if self.temperature_unit == UnitOfTemperature.CELSIUS else 70.0
        return default if low <= default <= high else round((low + high) / 2, 1)

    def _create_state(self, config):
        super()._create_state(config)
        mode = _HVAC_MODES.get(
            config.get(CONF_INITIAL_VALUE, DEFAULT_CLIMATE_VALUE).lower(), HVACMode.HEAT)
        # Don't start in a mode this thermostat doesn't have.
        self._attr_hvac_mode = mode if mode in self._attr_hvac_modes else self._attr_hvac_modes[0]

        mid = self._midpoint()
        self._attr_current_temperature = mid - 1
        self._attr_target_temperature = mid
        if self._has & ClimateEntityFeature.TARGET_TEMPERATURE_RANGE:
            self._attr_target_temperature_low = mid - 1
            self._attr_target_temperature_high = mid + 1
        if not (self._has & ClimateEntityFeature.TARGET_TEMPERATURE):
            self._attr_target_temperature = None
        if self._attr_preset_modes:
            self._attr_preset_mode = self._attr_preset_modes[0]
        if self._attr_fan_modes:
            self._attr_fan_mode = self._attr_fan_modes[0]
        if self._attr_swing_modes:
            self._attr_swing_mode = self._attr_swing_modes[0]
        if self._attr_swing_horizontal_modes:
            self._attr_swing_horizontal_mode = self._attr_swing_horizontal_modes[0]
        if self._has & ClimateEntityFeature.TARGET_HUMIDITY:
            self._attr_target_humidity = 50
        self._attr_current_humidity = 50

    def _restore_state(self, state, config):
        super()._restore_state(state, config)
        mode = _HVAC_MODES.get(state.state, HVACMode.HEAT)
        self._attr_hvac_mode = mode if mode in self._attr_hvac_modes else self._attr_hvac_modes[0]
        mid = self._midpoint()
        attrs = state.attributes
        self._attr_target_temperature = attrs.get(ATTR_TEMPERATURE, mid)
        self._attr_current_temperature = attrs.get("current_temperature", mid - 1)
        if self._has & ClimateEntityFeature.TARGET_TEMPERATURE_RANGE:
            self._attr_target_temperature_low = attrs.get("target_temp_low", mid - 1)
            self._attr_target_temperature_high = attrs.get("target_temp_high", mid + 1)
        if self._attr_preset_modes:
            self._attr_preset_mode = attrs.get("preset_mode") or self._attr_preset_modes[0]
        if self._attr_fan_modes:
            self._attr_fan_mode = attrs.get("fan_mode") or self._attr_fan_modes[0]
        if self._attr_swing_modes:
            self._attr_swing_mode = attrs.get("swing_mode") or self._attr_swing_modes[0]
        if self._attr_swing_horizontal_modes:
            self._attr_swing_horizontal_mode = (
                attrs.get("swing_horizontal_mode")
                or self._attr_swing_horizontal_modes[0])
        if self._has & ClimateEntityFeature.TARGET_HUMIDITY:
            self._attr_target_humidity = attrs.get("humidity", 50)
        self._attr_current_humidity = attrs.get("current_humidity", 50)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self._attr_target_temperature = temp
        if (low := kwargs.get(ATTR_TARGET_TEMP_LOW)) is not None:
            self._attr_target_temperature_low = low
        if (high := kwargs.get(ATTR_TARGET_TEMP_HIGH)) is not None:
            self._attr_target_temperature_high = high
        if (mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            await self.async_set_hvac_mode(mode)
            return
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        self._attr_preset_mode = preset_mode
        self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        self._attr_fan_mode = fan_mode
        self.async_write_ha_state()

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        self._attr_swing_mode = swing_mode
        self.async_write_ha_state()

    async def async_set_swing_horizontal_mode(self, swing_horizontal_mode: str) -> None:
        self._attr_swing_horizontal_mode = swing_horizontal_mode
        self.async_write_ha_state()

    async def async_set_humidity(self, humidity: int) -> None:
        self._attr_target_humidity = humidity
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        # "On" means whatever running mode this thermostat actually has — a
        # cool-only clone has no HEAT to switch to.
        for mode in (HVACMode.HEAT, HVACMode.HEAT_COOL, HVACMode.AUTO, HVACMode.COOL):
            if mode in self._attr_hvac_modes:
                self._attr_hvac_mode = mode
                break
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        if HVACMode.OFF in self._attr_hvac_modes:
            self._attr_hvac_mode = HVACMode.OFF
            self.async_write_ha_state()

    def set_current_temperature(self, value: float) -> None:
        """PistonCore extension: set the reported current temperature (for tests)."""
        _LOGGER.debug(f"{self.name} current_temperature -> {value}")
        self._attr_current_temperature = float(value)
        self.async_schedule_update_ha_state()

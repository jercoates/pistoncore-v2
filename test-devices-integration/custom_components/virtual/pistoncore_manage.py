"""
PistonCore addition to hass-virtual: HA-native services to create and remove a
virtual (test) DEVICE live, without hand-editing the group's yaml file.

This is an ADDITIVE PistonCore layer (see FORK_NOTES.md). It reuses the base
integration's own file helpers and reload path: it edits the group's yaml file
and reloads the config entry, which async_setup_entry already handles as
"create new devices + delete orphaned ones". Kept in its own module (with only a
tiny hook in __init__.py) so pulling upstream fixes stays easy.

Standalone self-sufficiency (VIRTUAL_DEVICES_SPEC.md §5.6): both services are
plain HA services, so a user WITHOUT PistonCore can call them from
Developer Tools -> Actions. PistonCore's control panel calls the same services.

Service: virtual.create_device
  group_name:  (optional) which virtual group's file to write; omit if only one.
  device_name: (required) the device this becomes — its entities are grouped
               under one device-registry entry (the "one device, many
               capabilities" shape).
  entities:    (required) list of entity dicts, each with a 'platform' key plus
               that platform's normal virtual options (name, class, initial_value,
               unit_of_measurement, ...). Same shape as a device block in
               virtual.yaml.

Service: virtual.remove_device
  group_name:  (optional) as above.
  device_name: (required) the device to remove. Its entities are removed and the
               device is deleted from the registry on reload (no orphans).
"""

import logging
import voluptuous as vol

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

from .const import COMPONENT_DOMAIN, ATTR_GROUP_NAME, ATTR_FILE_NAME
from .cfg import _load_user_data, _save_user_data

_LOGGER = logging.getLogger(__name__)

SERVICE_CREATE_DEVICE = "create_device"
SERVICE_REMOVE_DEVICE = "remove_device"

CONF_DEVICE_NAME = "device_name"
CONF_ENTITIES = "entities"

# Each entity needs at least a platform; the base validates the rest on reload,
# so keep this permissive rather than duplicating every platform schema here.
_ENTITY_SCHEMA = vol.Schema({
    vol.Required("platform"): cv.string,
}, extra=vol.ALLOW_EXTRA)

CREATE_DEVICE_SCHEMA = vol.Schema({
    vol.Optional(ATTR_GROUP_NAME): cv.string,
    vol.Required(CONF_DEVICE_NAME): cv.string,
    vol.Required(CONF_ENTITIES): vol.All(cv.ensure_list, [_ENTITY_SCHEMA]),
})

REMOVE_DEVICE_SCHEMA = vol.Schema({
    vol.Optional(ATTR_GROUP_NAME): cv.string,
    vol.Required(CONF_DEVICE_NAME): cv.string,
})


def _find_entry(hass: HomeAssistant, group_name):
    """Find the config entry for group_name, or the only one if omitted."""
    entries = list(hass.config_entries.async_entries(COMPONENT_DOMAIN))
    if not entries:
        raise HomeAssistantError("virtual: no configured group to modify")
    if group_name is None:
        if len(entries) > 1:
            names = ", ".join(e.data.get(ATTR_GROUP_NAME, "?") for e in entries)
            raise HomeAssistantError(
                f"virtual: multiple groups exist ({names}); pass group_name")
        return entries[0]
    for e in entries:
        if e.data.get(ATTR_GROUP_NAME) == group_name:
            return e
    raise HomeAssistantError(f"virtual: no group named '{group_name}'")


async def _async_create_device(hass: HomeAssistant, call) -> None:
    entry = _find_entry(hass, call.data.get(ATTR_GROUP_NAME))
    file_name = entry.data[ATTR_FILE_NAME]
    devices = await _load_user_data(file_name)
    if not isinstance(devices, dict):
        devices = {}
    devices[call.data[CONF_DEVICE_NAME]] = call.data[CONF_ENTITIES]
    await _save_user_data(file_name, devices)
    _LOGGER.info("virtual: created test device '%s' in group '%s'",
                 call.data[CONF_DEVICE_NAME], entry.data.get(ATTR_GROUP_NAME))
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_remove_device(hass: HomeAssistant, call) -> None:
    entry = _find_entry(hass, call.data.get(ATTR_GROUP_NAME))
    file_name = entry.data[ATTR_FILE_NAME]
    devices = await _load_user_data(file_name)
    if isinstance(devices, dict):
        devices.pop(call.data[CONF_DEVICE_NAME], None)
    await _save_user_data(file_name, devices)
    _LOGGER.info("virtual: removed test device '%s' from group '%s'",
                 call.data[CONF_DEVICE_NAME], entry.data.get(ATTR_GROUP_NAME))
    await hass.config_entries.async_reload(entry.entry_id)


@callback
def async_register_manage_services(hass: HomeAssistant) -> None:
    """Register create_device/remove_device once (idempotent)."""
    if hass.services.has_service(COMPONENT_DOMAIN, SERVICE_CREATE_DEVICE):
        return

    async def create_device(call):
        await _async_create_device(hass, call)

    async def remove_device(call):
        await _async_remove_device(hass, call)

    hass.services.async_register(
        COMPONENT_DOMAIN, SERVICE_CREATE_DEVICE, create_device,
        schema=CREATE_DEVICE_SCHEMA)
    hass.services.async_register(
        COMPONENT_DOMAIN, SERVICE_REMOVE_DEVICE, remove_device,
        schema=REMOVE_DEVICE_SCHEMA)
    _LOGGER.debug("virtual: registered create_device/remove_device services")

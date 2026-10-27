"""
Full-fidelity device cloning — PistonCore addition to hass-virtual (FORK_NOTES.md).

Service: virtual.clone_device
  device_id:   (required) the REAL device to copy. An entity_id is also accepted,
               for entities that have no device-registry entry of their own.
  group_name:  (optional) which virtual group to create it in; omit if only one.
  device_name: (optional) what to call the copy; defaults to "Test — <original>".
  notify_as:   (optional) "app" (push) or "sms" (text). Labels the notifier(s) the
               source device already has, so a piston that sends a push or a text
               finds them. A companion-app phone also gets one if it has none.
  add_notifier: (optional, FOR UIs — deliberately NOT in services.yaml, so it is
               not offered on Home Assistant's Actions screen) true = if the
               source has no notifier, add one of the kind `notify_as` names.
               Whether that makes sense for a device (a phone that arrives through
               a bridge looks like a handful of sensors) is a decision for the UI
               calling this, which knows more than this integration can.

WHY THIS LIVES HERE AND NOT IN THE CALLER (VIRTUAL_DEVICES_SPEC §5.7a).
The platforms in this integration validate against CLOSED schemas: hand one a
config key it does not declare and entity creation fails outright. So the list of
attributes a clone copies and the schemas that accept them are a single contract.
Keeping them in one place makes it impossible for them to disagree. When the
capture list lived in PistonCore, every schema change here needed a matching
change in another project on another release cycle — guaranteed drift.

WHERE THE CAPTURE LIST COMES FROM — read this before adding to it.
Every entry is taken from HOME ASSISTANT's own `capability_attributes` property on
the matching entity base class, which is HA's definition of "the attributes that
describe what this entity can DO". It must NOT be derived by looking at whatever
devices happen to be on one install: an earlier pass did exactly that and silently
dropped `target_humidity_step` and `swing_horizontal_modes`, because the install it
was written against had no device reporting them.

WHAT THIS DELIBERATELY DOES NOT COPY — this is a privacy boundary, not an omission.
Bridged devices carry driver-level extras beyond anything HA defines, and some are
secrets: a Hubitat-bridged alarm panel exposes `codes` containing plaintext PINs
with the names they belong to, and locks expose household member names via `codes`
and `last_code_name`. Sticking to HA's capability attributes keeps all of it out.
A clone is meant to be shareable in a bug report; widening this list past HA's
capability attributes would publish somebody's alarm code.

KNOWN LIMIT: this clones SHAPE, not BEHAVIOUR. It reproduces what a device says it
can do; it does not reproduce how that device's own integration mangles values in
flight. Capability bugs are catchable on a clone, integration-behaviour bugs are not.
"""

import logging
from enum import Enum

import voluptuous as vol

from homeassistant.core import HomeAssistant, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import homeassistant.helpers.config_validation as cv
import homeassistant.helpers.device_registry as dr
import homeassistant.helpers.entity_registry as er

from .cfg import unique_in_device
from .const import COMPONENT_DOMAIN, ATTR_GROUP_NAME
from .pistoncore_manage import _find_entry, _mutate_and_reload

_LOGGER = logging.getLogger(__name__)

SERVICE_CLONE_DEVICE = "clone_device"
SERVICE_DESCRIBE_DEVICE = "describe_device"

CONF_DEVICE_ID = "device_id"
CONF_DEVICE_NAME = "device_name"
CONF_NOTIFY_AS = "notify_as"
CONF_ADD_NOTIFIER = "add_notifier"

# The two kinds of notification a piston can send to a person. These are the
# `target_key` values the notifier platform labels itself with, and the ones the
# caller binds a push / a text to — keep them in step with notify.py.
NOTIFY_KINDS = ("app", "sms")

# A phone registers its push as a notify SERVICE, never as a notify entity, so a
# phone has nothing for a clone to copy. Cloning one therefore adds a push
# notifier. Config-entry domains that mean "this device is a phone running the
# companion app".
PUSH_CONFIG_DOMAINS = {"mobile_app"}

CLONE_DEVICE_SCHEMA = vol.Schema({
    vol.Required(CONF_DEVICE_ID): cv.string,
    vol.Optional(ATTR_GROUP_NAME): cv.string,
    vol.Optional(CONF_DEVICE_NAME): cv.string,
    vol.Optional(CONF_NOTIFY_AS): vol.In(NOTIFY_KINDS),
    vol.Optional(CONF_ADD_NOTIFIER): cv.boolean,
})

# describe_device takes the same two so a preview can never disagree with the
# clone it previews.
DESCRIBE_DEVICE_SCHEMA = vol.Schema({
    vol.Required(CONF_DEVICE_ID): cv.string,
    vol.Optional(CONF_NOTIFY_AS): vol.In(NOTIFY_KINDS),
    vol.Optional(CONF_ADD_NOTIFIER): cv.boolean,
})

# Domains this integration can reproduce as a settable test entity.
REPRODUCIBLE_DOMAINS = {
    "alarm_control_panel", "binary_sensor", "button", "camera", "climate",
    "cover", "device_tracker", "event", "fan", "humidifier", "light", "lock",
    "media_player", "notify", "number", "select", "sensor", "siren", "switch",
    "text", "vacuum", "valve",
}

# (domain) -> the capability attributes to copy verbatim. See the module docstring
# for where this list comes from and what must never be added to it.
CLONE_ATTRS: dict[str, tuple[str, ...]] = {
    "climate": ("hvac_modes", "preset_modes", "fan_modes", "swing_modes",
                "swing_horizontal_modes", "min_temp", "max_temp",
                "target_temp_step", "min_humidity", "max_humidity",
                "target_humidity_step"),
    "media_player": ("source_list", "sound_mode_list"),
    "vacuum": ("fan_speed_list",),
    "siren": ("available_tones",),
    "humidifier": ("available_modes", "min_humidity", "max_humidity",
                   "target_humidity_step"),
    # lock/cover/alarm_control_panel use HA's default (empty) capability
    # attributes; what distinguishes them is supported_features plus these
    # ordinary state attributes.
    "lock": ("code_format",),
    "alarm_control_panel": ("code_format", "code_arm_required"),
    "light": ("supported_color_modes", "effect_list",
              "min_color_temp_kelvin", "max_color_temp_kelvin"),
    "sensor": ("state_class", "options"),
    "number": ("min", "max", "step", "mode"),
    "select": ("options",),
    "text": ("min", "max", "pattern", "mode"),
}

# Domains whose platform here accepts `supported_features`. Deliberately not all
# of them: switch/binary_sensor/button have no feature flags to copy.
CLONE_FEATURES = {
    "alarm_control_panel", "camera", "climate", "cover", "fan", "humidifier",
    "light", "lock", "media_player", "notify", "siren", "vacuum",
}


def _plain(value):
    """Reduce a value to something yaml can store.

    The captured config is written to the group's yaml file, so it must contain
    ONLY plain types. HA hands out enum members in places (`temperature_unit` is
    a UnitOfTemperature, colour modes are ColorMode), and a single enum in here
    used to blow up the save — which, before the atomic-write fix in cfg.py,
    truncated the device file to zero and destroyed every test device on this
    bench. Keep everything primitive on the way in as well.
    """
    # Enum first: StrEnum/IntEnum are also str/int, so this must come before the
    # primitive check or they slip through as enum members.
    if isinstance(value, Enum):
        return _plain(value.value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    return str(value)


def capability_config(hass: HomeAssistant, domain: str, attrs: dict) -> dict:
    """The config that makes a copy of this entity a real copy.

    Only what the original actually reported: an absent attribute stays absent so
    the platform keeps its own default rather than being pinned to a guess.
    """
    spec: dict = {}

    if domain in CLONE_FEATURES and isinstance(attrs.get("supported_features"), int):
        spec["supported_features"] = int(attrs["supported_features"])

    for key in CLONE_ATTRS.get(domain, ()):
        value = attrs.get(key)
        if value is not None:
            spec[key] = _plain(value)

    if domain == "climate":
        # Cloned limits arrive in whatever unit HA reports them in, so the copy
        # must declare that same unit or HA converts them a second time.
        spec["temperature_unit"] = _plain(hass.config.units.temperature_unit)

    elif domain == "notify":
        # `target_key` is this integration's own label for what a notifier stands
        # in for ("sms", "app"). A REAL notifier has no such attribute, so this
        # does nothing when cloning one — it only keeps the label when cloning a
        # test notifier, which would otherwise come back as "generic".
        if attrs.get("target_key"):
            spec["class"] = _plain(attrs["target_key"])

    elif domain == "media_player":
        if attrs.get("device_class"):
            spec["class"] = _plain(attrs["device_class"])

    elif domain == "fan":
        # The fan platform predates cloning and speaks its own dialect: a speed
        # COUNT rather than HA's percentage step, and `modes` for preset_modes.
        if attrs.get("preset_modes"):
            spec["modes"] = _plain(attrs["preset_modes"])
        step = attrs.get("percentage_step")
        if isinstance(step, (int, float)) and 0 < step <= 100:
            spec["speed_count"] = max(1, round(100 / step))

    elif domain == "number":
        # min/max are REQUIRED by the number platform — without them a copy
        # containing a number entity can never be created at all.
        spec.setdefault("min", 0)
        spec.setdefault("max", 100)

    return spec


def entity_spec(hass: HomeAssistant, domain: str, entry, attrs: dict) -> dict:
    """What makes a copy of ONE entity a real copy: its class, its unit (sensor and
    number only) and capability_config().

    `entry` is the entity-registry row, or None for an entity that has none.
    Shared by clone_device and export_devices on purpose: two capture routines
    would drift, and the thing they must agree on most is what a copy must NEVER
    carry (lock and alarm codes).
    """
    spec: dict = {}
    device_class = attrs.get("device_class") or (
        entry and (entry.device_class or entry.original_device_class))
    if device_class:
        spec["class"] = _plain(device_class)
    unit = attrs.get("unit_of_measurement")
    if unit and domain in ("sensor", "number"):
        spec["unit_of_measurement"] = _plain(unit)
    spec.update(capability_config(hass, domain, attrs))
    return spec


def _capability_name(entity_entry, attrs: dict, device_label: str) -> str:
    """The entity's CAPABILITY part, with the device's own name stripped off, so a
    camera's "Driveway Motion Smart Detect Type" reduces to "Smart Detect Type".

    Returns "" when nothing is left — a single-entity device whose entity is just
    named after the device. The caller re-attaches the device name, so an empty
    result means "call it after the device and nothing more".
    """
    name = (getattr(entity_entry, "original_name", None)
            or attrs.get("friendly_name")
            or entity_entry.entity_id.split(".", 1)[1])
    label = (device_label or "").strip().lower()
    if label and name.lower().startswith(label):
        name = name[len(label):].strip(" -—:")
        return name
    return name


def _is_phone(hass: HomeAssistant, device) -> bool:
    """Is this a phone running the companion app? Decided by which integration
    owns the device, which is the one thing a phone cannot be mistaken for."""
    if device is None:
        return False
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is not None and entry.domain in PUSH_CONFIG_DOMAINS:
            return True
    return False


def _notifier_spec(kind: str) -> dict:
    """A notifier entity that stands in for a push (`app`) or a text (`sms`).

    This is what lets a piston's "send a push" / "send a text" land on a copy.
    A REAL notifier carries no label saying which kind it is, so without this a
    clone comes back "generic" and nothing aimed at push or text finds it. The
    entity name is capability-only, like every other spec: the caller prefixes
    the device name."""
    return {"platform": "notify", "name": "Notification", "class": kind}


def build_clone_spec(hass: HomeAssistant, device_id: str,
                     notify_as: str | None = None,
                     add_notifier: bool = False) -> tuple[str, list[dict]]:
    """(source device name, entity specs) for a real device — the whole capture
    half, with no network round trip because everything is local to HA.

    notify_as: "app" or "sms" — label the notifier(s) the source already has.
    add_notifier: also ADD one when the source has none (a UI's decision, see the
    module docstring). A companion-app phone always gets a push notifier, because
    its push is a service rather than an entity so there is nothing to copy, and
    that is a fact about the owning integration rather than a guess."""
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)

    device = dev_reg.async_get(device_id)
    if device is not None:
        label = device.name_by_user or device.name or "Device"
        entries = er.async_entries_for_device(
            ent_reg, device_id, include_disabled_entities=False)
    else:
        # Not a device id — accept an entity_id, for entities that have no
        # device-registry entry of their own (PistonCore groups those as
        # singletons and passes the entity_id through as the group key).
        entry = ent_reg.async_get(device_id)
        if entry is None:
            raise ServiceValidationError(
                f"virtual: no device or entity known as '{device_id}'")
        state = hass.states.get(entry.entity_id)
        label = (entry.original_name
                 or (state.attributes.get("friendly_name") if state else None)
                 or entry.entity_id)
        entries = [entry]

    specs: list[dict] = []
    seen: dict[str, int] = {}
    for entry in entries:
        domain = entry.entity_id.split(".", 1)[0]
        if domain not in REPRODUCIBLE_DOMAINS:
            continue  # image/select/update etc. not reproducible yet
        state = hass.states.get(entry.entity_id)
        attrs = dict(state.attributes) if state else {}

        unique = unique_in_device(seen, _capability_name(entry, attrs, label))

        # Capability part only. The DEVICE name is prepended by the caller — see
        # _async_clone_device for why that is not cosmetic.
        spec = {"platform": domain, "name": unique}
        spec.update(entity_spec(hass, domain, entry, attrs))
        specs.append(spec)

    # A real notifier clones as "generic" (it has no label), so a kind chosen at
    # clone time labels it. Adding one to a device that has none is only done
    # when asked (add_notifier) or for a companion-app phone.
    phone = _is_phone(hass, device)
    if notify_as is None and phone:
        notify_as = "app"
    if notify_as:
        notifiers = [sp for sp in specs if sp["platform"] == "notify"]
        for sp in notifiers:
            sp["class"] = notify_as
        if not notifiers:
            if add_notifier or phone:
                spec = _notifier_spec(notify_as)
                # Through the same de-duplicator as every other entity: a source
                # entity already called "Notification" must not be duplicated.
                spec["name"] = unique_in_device(seen, spec["name"])
                specs.append(spec)
            else:
                _LOGGER.warning(
                    "virtual: '%s' has no notifier, so notify_as was ignored", label)

    if not specs:
        raise ServiceValidationError(
            f"virtual: '{label}' has nothing this integration can reproduce")
    return label, specs


async def _async_clone_device(hass: HomeAssistant, call) -> None:
    entry = _find_entry(hass, call.data.get(ATTR_GROUP_NAME))
    label, specs = build_clone_spec(
        hass, call.data[CONF_DEVICE_ID], call.data.get(CONF_NOTIFY_AS),
        call.data.get(CONF_ADD_NOTIFIER, False))

    name = call.data.get(CONF_DEVICE_NAME) or (
        label if label.lower().startswith("test") else f"Test — {label}")

    # QUALIFY EVERY ENTITY WITH THE DEVICE NAME. This is not cosmetic: this
    # integration keys an entity's identity by its NAME within the group, so two
    # devices carrying an identically-named entity fight over one identity and
    # HA re-registers the loser on EVERY restart. Measured on a clean HA
    # 2026-07-31: cloning one device twice produced five colliding names and
    # five brand-new entities per restart, growing without limit.
    # Capability-only names collide easily ("Battery", "Automatic backup"),
    # so the device name has to be part of it — which is also what the base
    # integration does when it names entities itself.
    for spec in specs:
        capability = spec["name"]
        spec["name"] = f"{name} {capability}".strip() if capability else name

    def _add(devices):
        devices[name] = specs

    _LOGGER.info("virtual: cloning '%s' as '%s' (%d entities)",
                 label, name, len(specs))
    await _mutate_and_reload(hass, entry, f"cloned '{label}' as '{name}'", _add)


async def _async_describe_device(hass: HomeAssistant, call) -> dict:
    """The clone spec for a device, WITHOUT creating anything.

    Exists so a bug report can carry enough to REBUILD the reporter's device on
    someone else's bench: paste the returned `entities` straight into
    virtual.create_device. It deliberately reuses build_clone_spec rather than
    describing devices a second way — one capture implementation, so a described
    device and a cloned device can never disagree.
    """
    label, specs = build_clone_spec(
        hass, call.data[CONF_DEVICE_ID], call.data.get(CONF_NOTIFY_AS),
        call.data.get(CONF_ADD_NOTIFIER, False))
    return {"device_name": label, "entities": specs}


@callback
def async_register_clone_service(hass: HomeAssistant) -> None:
    """Register clone_device / describe_device once (idempotent)."""
    if hass.services.has_service(COMPONENT_DOMAIN, SERVICE_CLONE_DEVICE):
        return

    async def clone_device(call):
        await _async_clone_device(hass, call)

    async def describe_device(call):
        return await _async_describe_device(hass, call)

    hass.services.async_register(
        COMPONENT_DOMAIN, SERVICE_CLONE_DEVICE, clone_device,
        schema=CLONE_DEVICE_SCHEMA)
    hass.services.async_register(
        COMPONENT_DOMAIN, SERVICE_DESCRIBE_DEVICE, describe_device,
        schema=DESCRIBE_DEVICE_SCHEMA,
        supports_response=SupportsResponse.ONLY)
    _LOGGER.debug("virtual: registered clone_device/describe_device")

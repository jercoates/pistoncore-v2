"""HA -> webCoRE grouped device payload pipeline (DEVICE_PAYLOAD_SPEC.md).

Implements Stages 1, 3, 4, 6, 7, 8 literally from the documented source
files (picker_capability_map.json, webcore_vocab.json) and HA's own
registry fields. Stage 5 (live attribute values) is deliberately deferred —
not blocked on data anymore (webcore_vocab.json's "ha" arrays are now a
structured, machine-executable read rule per attribute), just not yet
built — so attributes are emitted with their static {n,t,o} definition
from vocab.attributes and no "v" (SHIM_API_SPEC.md §5.1 /
DEVICE_PAYLOAD_SPEC.md Stage 5: dashboard tolerates missing v).

Stage 1 groups by HA's device-registry device_id (confirmed against
Jeremy's real data, 2026-07-09 — HA's own "Device" column in the states
table is this exact entity->device_id->device_registry lookup; verified
correct for Keypad/Chime/ecobee/OwnTracks).

Duplicate attributes within one device (Stage 3 open item 1): ONE device
per HA device_id, always — never split into multiple picker devices
(Jeremy, 2026-07-09: splitting a device like room2's ReSpeaker into pieces
is not acceptable, for any device found this way, not just his). Handling
by attribute type:
- Sub-device attributes (button, lock — vocab.attributes[key].s names a
  companion count attribute): never dropped. Every contributing entity is
  kept, in order, as a sub-device index (piston.module.js:3703-3739).
- Everything else (e.g. two independent "switch" entities on one device):
  first contributor (by entity_id sort) wins the attribute/command slot.
  Nothing is spun into a separate device. A second entity offering the same
  generic command name (e.g. a second "on"/"off") is a real, known
  limitation — webCoRE's c[].n must be a real vocab.commands key for the
  editor to render it, and there is no sub-device mechanism for "switch"
  the way there is for "button" — so it isn't independently reachable yet.
  Not hidden, just not solved here; would need either a vocab addition or
  webCoRE's custom-command mechanism (PISTON_JSON_REFERENCE.md §5 "cm").
"""

import hashlib
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger("device_pipeline")

_REPO_ROOT = Path(__file__).resolve().parent.parent

_EXCLUDED_ENTITY_CATEGORIES = {"diagnostic", "config"}

# Declaration attributes picker_capability_map.json's by_declaration_attr
# rules check for (climate/device_tracker/person domains) — read straight
# off the entity's state.attributes dict.
_DECLARATION_ATTR_KEYS = [
    "current_temperature", "fan_mode", "target_temp_high", "target_temp_low",
    "temperature", "latitude", "zone_id",
]


def _load_json(filename: str) -> dict:
    with open(_REPO_ROOT / filename, encoding="utf-8") as f:
        return json.load(f)


def hash_id(value: str) -> str:
    """Stock webCoRE hashId format (DEVICE_PAYLOAD_SPEC.md Stage 7, VERIFIED-GROOVY)."""
    return ":" + hashlib.md5(("core." + value).encode("utf-8")).hexdigest() + ":"


def _friendly_name(entity_id: str, state_map: dict) -> str:
    state = state_map.get(entity_id)
    return (state["attributes"].get("friendly_name") if state else None) or entity_id


def _trailing_number(entity_id: str) -> int:
    """For sub-device ordering (button_1, button_2, ..., button_10) — plain
    lexicographic sort puts button_10 before button_2, which would make the
    editor's "button 2" resolve to the wrong physical button."""
    match = re.search(r"(\d+)$", entity_id)
    return int(match.group(1)) if match else 0


def _custom_attribute_key(entity: dict, entity_id: str) -> str:
    """Key for an entity that matched no picker_capability_map rule.

    Prefer the original Hubitat attribute name, recovered from the entity's
    own unique_id (format hub::device::sensor::attrName — confirmed against
    Jeremy's real HA data, 2026-07-09: sensor.doorbell_pro_motion_smart_
    detect_type's unique_id is "3c8e8863::927::sensor::smartDetectType",
    byte-for-byte the attribute name his old Hubitat webCoRE piston used).
    piston.module.js:3688-3701 falls back to a device's own a[] entries by
    name when a key isn't in the central vocab, so this doesn't need a
    vocab or picker_capability_map entry to work in the editor. Falls back
    to the entity's own object_id when the pattern doesn't match (non-
    Hubitat platforms, or Hubitat entities that aren't a single passthrough
    attribute)."""
    unique_id = entity.get("unique_id") or ""
    parts = unique_id.split("::")
    if entity.get("platform") == "hubitat" and len(parts) == 4 and parts[2] == "sensor":
        return parts[3]
    return entity_id.split(".", 1)[1]


def _custom_attribute(entity_id: str, entity: dict, state: dict | None) -> dict | None:
    """Generic fallback attribute for an entity with live data but no
    picker_capability_map rule — never silently drop what HA exposes."""
    if state is None:
        return None
    value = state.get("state")
    if value in (None, "unknown", "unavailable"):
        return None
    key = _custom_attribute_key(entity, entity_id)
    try:
        float(value)
        attr_type = "decimal"
    except (TypeError, ValueError):
        attr_type = "string"
    return {"n": key, "t": attr_type}


# ---------------------------------------------------------------------------
# Stage 1 — grouping
# ---------------------------------------------------------------------------

def group_entities(registries: dict) -> list[dict]:
    """
    Group entities by their HA device-registry device_id — this is the same
    lookup HA's own "Device" column in Developer Tools > States uses.
    Entities with no registry device become singleton groups of one.

    Returns a list of:
      { "group_key": <registry device_id or entity_id>,
        "display_name": <name_by_user, else name, else entity friendly_name>,
        "member_entity_ids": [entity_id, ...] }
    """
    device_map = {d["id"]: d for d in registries["devices"]}
    state_map = {s["entity_id"]: s for s in registries["states"]}

    groups: dict[str, dict] = {}
    excluded = []

    for entity in registries["entities"]:
        if entity.get("disabled_by") is not None:
            excluded.append((entity["entity_id"], "disabled"))
            continue
        if entity.get("entity_category") in _EXCLUDED_ENTITY_CATEGORIES:
            excluded.append((entity["entity_id"], f"entity_category={entity['entity_category']}"))
            continue

        device_id = entity.get("device_id")
        entity_id = entity["entity_id"]

        if device_id and device_id in device_map:
            group_key = device_id
            device = device_map[device_id]
            display_name = device.get("name_by_user") or device.get("name") or device_id
        else:
            group_key = entity_id
            display_name = _friendly_name(entity_id, state_map)

        group = groups.setdefault(group_key, {
            "group_key": group_key,
            "display_name": display_name,
            "member_entity_ids": [],
        })
        group["member_entity_ids"].append(entity_id)

    logger.info("Stage 1 grouping: %d groups from %d entities, %d excluded",
                len(groups), len(registries["entities"]), len(excluded))
    for entity_id, reason in excluded:
        logger.debug("Stage 1 excluded %s: %s", entity_id, reason)

    return list(groups.values())


# ---------------------------------------------------------------------------
# Stage 3 — picker_capability_map.json rule evaluator
# ---------------------------------------------------------------------------

def _entity_signals(entity_id: str, state: dict | None) -> dict:
    domain = entity_id.split(".", 1)[0]
    attrs = state["attributes"] if state else {}
    return {
        "domain": domain,
        "device_class": attrs.get("device_class"),
        "supported_color_modes": attrs.get("supported_color_modes"),
        "supported_features": attrs.get("supported_features"),
        "unit_of_measurement": attrs.get("unit_of_measurement"),
        "declaration_attrs": {k: attrs.get(k) for k in _DECLARATION_ATTR_KEYS if attrs.get(k) is not None},
    }


def attribute_keys_for_entity(signals: dict, capability_map: dict) -> set[str]:
    """
    Evaluate picker_capability_map.json's rule types for one entity's
    signals, per the file's own documented algorithm (_meta.usage):
    always -> by_device_class -> by_supported_color_modes ->
    by_supported_features (or legacy_by_supported_features when
    supported_color_modes is absent, light-only) -> by_declaration_attr ->
    by_unit_fallback. Union of all matching rules' attributes.
    """
    domain_rules = capability_map["domains"].get(signals["domain"])
    if not domain_rules:
        return set()

    keys: set[str] = set()

    if "always" in domain_rules:
        keys.update(domain_rules["always"]["attributes"])

    if signals["device_class"] and "by_device_class" in domain_rules:
        rule = domain_rules["by_device_class"].get(signals["device_class"])
        if rule:
            keys.update(rule["attributes"])

    if signals["supported_color_modes"] and "by_supported_color_modes" in domain_rules:
        for mode in signals["supported_color_modes"]:
            rule = domain_rules["by_supported_color_modes"].get(mode)
            if rule:
                keys.update(rule["attributes"])
    elif "legacy_by_supported_features" in domain_rules and signals["supported_features"] is not None:
        for key, rule in domain_rules["legacy_by_supported_features"].items():
            if key.startswith("_"):
                continue
            if signals["supported_features"] & rule["bit"]:
                keys.update(rule["attributes"])

    if signals["supported_features"] is not None and "by_supported_features" in domain_rules:
        for key, rule in domain_rules["by_supported_features"].items():
            if key.startswith("_"):
                continue
            if signals["supported_features"] & rule["bit"]:
                keys.update(rule["attributes"])

    if "by_declaration_attr" in domain_rules:
        for attr_name, rule in domain_rules["by_declaration_attr"].items():
            if attr_name.startswith("_"):
                continue
            if attr_name in signals["declaration_attrs"]:
                keys.update(rule["attributes"])

    if signals["device_class"] is None and "by_unit_fallback" in domain_rules:
        for key, rule in domain_rules["by_unit_fallback"].items():
            if key.startswith("_"):
                continue
            if signals["unit_of_measurement"] == rule["unit_match"]:
                keys.update(rule["attributes"])

    return keys


# ---------------------------------------------------------------------------
# Stage 3.3 — command-only capability lane (DEVICE_PAYLOAD_SPEC.md Stage 3.3)
# ---------------------------------------------------------------------------

def capability_keys_for_entity(signals: dict, capability_map: dict) -> set[str]:
    """
    Mirrors attribute_keys_for_entity's rule dispatch but reads a domain's
    optional "capabilities" branch and returns capability keys directly —
    for capabilities with commands but no primary attribute (speechSynthesis
    and similar), which the attribute->capability bridge (Stage 4) can never
    reach since there is no attribute to bridge from. Data-driven per house
    style; only by_supported_features exists as a seed rule today, but this
    walks whatever rule types are present so new ones need no code change.
    """
    domain_rules = capability_map["domains"].get(signals["domain"], {})
    cap_rules = domain_rules.get("capabilities")
    if not cap_rules:
        return set()

    keys: set[str] = set()

    if "always" in cap_rules:
        keys.update(cap_rules["always"]["capabilities"])

    if signals["device_class"] and "by_device_class" in cap_rules:
        rule = cap_rules["by_device_class"].get(signals["device_class"])
        if rule:
            keys.update(rule["capabilities"])

    if signals["supported_features"] is not None and "by_supported_features" in cap_rules:
        for key, rule in cap_rules["by_supported_features"].items():
            if key.startswith("_"):
                continue
            if signals["supported_features"] & rule["bit"]:
                keys.update(rule["capabilities"])

    if "by_declaration_attr" in cap_rules:
        for attr_name, rule in cap_rules["by_declaration_attr"].items():
            if attr_name.startswith("_"):
                continue
            if attr_name in signals["declaration_attrs"]:
                keys.update(rule["capabilities"])

    return keys


# ---------------------------------------------------------------------------
# Stage 4 — attribute -> capability bridge (VERIFIED-FILES, overlaps expected)
# ---------------------------------------------------------------------------

def build_attr_to_capabilities_index(vocab: dict) -> dict[str, list[str]]:
    """Invert vocab.capabilities[*].a once: attribute key -> [capability keys]."""
    index: dict[str, list[str]] = {}
    for cap_key, cap in vocab["capabilities"].items():
        attr_key = cap.get("a")
        if attr_key:
            index.setdefault(attr_key, []).append(cap_key)
    return index


# ---------------------------------------------------------------------------
# One HA device_id group -> one webCoRE device object, always. No splitting.
# ---------------------------------------------------------------------------

def _process_group(group: dict, state_map: dict, entity_map: dict, picker_map: dict, vocab: dict, attr_to_caps: dict):
    member_ids_sorted = sorted(group["member_entity_ids"])

    attr_bindings: dict[str, str] = {}
    sub_device_members: dict[str, list[str]] = {}
    cmd_bindings: dict[str, str] = {}
    capability_keys: set[str] = set()
    direct_cap_contributors: dict[str, str] = {}
    custom_attrs: list[dict] = []

    for entity_id in member_ids_sorted:
        state = state_map.get(entity_id)
        signals = _entity_signals(entity_id, state)
        entity_attr_keys = attribute_keys_for_entity(signals, picker_map)

        # Stage 3.3 — command-only capabilities, evaluated independently of
        # the attribute lane above (a capability here has no attribute to
        # bridge from). First entity to offer a given capability wins its
        # command bindings, same first-contributor-wins rule as attributes.
        for cap_key in capability_keys_for_entity(signals, picker_map):
            if cap_key not in capability_keys:
                capability_keys.add(cap_key)
                direct_cap_contributors[cap_key] = entity_id

        if not entity_attr_keys:
            # No picker_capability_map rule matched this entity at all —
            # don't silently drop it (hard requirement 1, DEVICE_PAYLOAD_SPEC
            # §0). Falls through as a device-local custom attribute instead.
            entity = entity_map.get(entity_id, {})
            custom_attr = _custom_attribute(entity_id, entity, state)
            if custom_attr and custom_attr["n"] not in attr_bindings:
                custom_attrs.append(custom_attr)
                attr_bindings[custom_attr["n"]] = entity_id
            continue

        for attr_key in entity_attr_keys:
            vocab_attr = vocab["attributes"].get(attr_key, {})

            if "s" in vocab_attr:
                sub_device_members.setdefault(attr_key, []).append(entity_id)
                if attr_key not in attr_bindings:
                    attr_bindings[attr_key] = entity_id
                    capability_keys.update(attr_to_caps.get(attr_key, []))
                continue

            if attr_key not in attr_bindings:
                attr_bindings[attr_key] = entity_id
                capability_keys.update(attr_to_caps.get(attr_key, []))
            # else: another entity already won this attribute key. Its own
            # commands are still considered below (via capability_keys built
            # from ITS attribute keys too, through attr_to_caps) as long as
            # at least one of its OTHER attribute keys is unclaimed; a command
            # that only two entities could ever offer under the same name
            # keeps routing to whichever entity won that name first.

    # Sub-device members were accumulated in member_ids_sorted (lexicographic)
    # order — re-sort numerically so index N actually means physical button N.
    for attr_key in sub_device_members:
        sub_device_members[attr_key].sort(key=_trailing_number)

    # Stage 6 — commands: union of vocab.capabilities[k].c across this
    # group's capability keys, bound to whichever member contributed that
    # capability's attribute (commands route to that member).
    for cap_key in capability_keys:
        cap = vocab["capabilities"].get(cap_key, {})
        contributing_entity = attr_bindings.get(cap.get("a")) or direct_cap_contributors.get(cap_key)
        for command_key in cap.get("c", []):
            if command_key not in cmd_bindings and contributing_entity:
                cmd_bindings[command_key] = contributing_entity

    # cn — capability display names (Stage 4)
    cn = sorted({vocab["capabilities"][k]["n"] for k in capability_keys if k in vocab["capabilities"]})

    # a — attribute array, static {n,t,o} from vocab, no v yet (Stage 5 deferred).
    # Sub-device attrs also get a synthetic count attribute (e.g.
    # "numberOfButtons") so the editor offers the right number of indexes
    # instead of falling back to a generic 32 (piston.module.js:3729).
    a = []
    for attr_key in sorted(attr_bindings):
        vocab_attr = vocab["attributes"].get(attr_key)
        if not vocab_attr:
            continue
        entry = {"n": attr_key, "t": vocab_attr["t"]}
        if "o" in vocab_attr:
            entry["o"] = vocab_attr["o"]
        a.append(entry)

        if attr_key in sub_device_members:
            count_attr_name = vocab_attr["s"].split(",")[0]
            a.append({"n": count_attr_name, "t": "integer", "v": len(sub_device_members[attr_key])})

    # Custom attributes (no vocab entry — piston.module.js's device.a[]
    # fallback lookup handles these fine without one) appended last, sorted
    # for stable output.
    a.extend(sorted(custom_attrs, key=lambda entry: entry["n"]))

    # c — command array (Stage 6)
    c = []
    for command_key in sorted(cmd_bindings):
        command = vocab["commands"].get(command_key, {})
        c.append({"n": command_key, "p": command.get("p", [])})

    hashed_id = hash_id(group["group_key"])

    # Real Hubitat-fork getDevDetails() returns exactly n/cn/a/c — no o/an on a
    # physical device (o is only real on virtualDevices entries; an was never
    # real at all) — verified against source, 2026-07-10.
    device_obj = {
        "n": group["display_name"],
        "cn": cn,
        "a": a,
        "c": c,
    }

    resolution_entry = {
        "registry_device_id": group["group_key"],
        "name": group["display_name"],
        "members": member_ids_sorted,
        "attr_bindings": attr_bindings,
        "sub_device_bindings": sub_device_members,
        "cmd_bindings": cmd_bindings,
    }

    return hashed_id, device_obj, resolution_entry


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def extract_tts_engines(registries: dict) -> list[dict]:
    """
    tts.* entities (SESSION_BRIEF_SPEAK_VIRTUALS.md item 1b). VERIFIED live
    (HA 2026.7.2): modern HA exposes TTS engines as entities in the same
    get_states call already fetched for devices — no second HA round trip
    needed. These are NOT devices (never merged into the devices payload);
    they feed a future default-TTS-engine setting the compiler will read.
    entity state ("unknown"/"unavailable"/etc.) is the engine's own status,
    not a webCoRE-shaped value — left out here, this is enumeration only.
    """
    return [
        {"entity_id": s["entity_id"], "name": s["attributes"].get("friendly_name", s["entity_id"])}
        for s in registries["states"]
        if s["entity_id"].startswith("tts.")
    ]


def extract_notify_target_services(registries: dict) -> list[str]:
    """
    notify.mobile_app_* service keys (VERIFIED live get_services, HA 2026.7.2)
    -- the legacy per-target services real webCoRE-style device notification
    tasks resolve to (COMPILER_DECISIONS_HOLDING.md C2, corrected 2026-07-12:
    Jeremy's real pistons use a plain device-type variable + deviceNotification
    command for this, e.g. "@Notifications_Push" -- not a separate picker
    section or a Contact-Book-style target). Generic/non-target notify
    services (notify.notify, persistent_notification, send_message) are
    excluded -- they broadcast or aren't a single destination.
    """
    notify_services = registries.get("services", {}).get("notify", {})
    return sorted(key for key in notify_services if key.startswith("mobile_app_"))


def _build_notify_device(service_key: str, vocab: dict) -> tuple[str, dict, dict]:
    """
    One synthetic picker device per notify target service -- same shape as
    any other device (n/cn/a/c), just sourced from the service registry
    instead of an HA entity. Hashed from the service name itself, same as
    every other device hash; if the underlying service name ever changes
    (phone replaced/re-registered), the old hash simply stops resolving and
    the piston shows broken in the editor -- the same "honest breakage,
    re-pick in the UI" rule as any other device (DEVICE_PAYLOAD_SPEC Stage 7),
    not a special case needing its own rebind mechanism.

    Display name is a de-slugified guess (mobile_app_jeremy_s_s25 -> "Jeremy
    S S25") -- TO VERIFY once a real mobile_app device exists to cross-
    reference against its device-registry name (name_by_user), which would
    give a truer display name than de-slugifying the service key.
    """
    entity_id_like = f"notify.{service_key}"
    hashed_id = hash_id(entity_id_like)
    display_name = service_key.removeprefix("mobile_app_").replace("_", " ").title()

    cap = vocab["capabilities"].get("notification", {})
    command_keys = cap.get("c", [])
    cn = [cap["n"]] if cap else []
    c = [{"n": ck, "p": vocab["commands"].get(ck, {}).get("p", [])} for ck in command_keys]

    device_obj = {"n": display_name, "cn": cn, "a": [], "c": c}
    resolution_entry = {
        "registry_device_id": entity_id_like,
        "name": display_name,
        "members": [entity_id_like],
        "attr_bindings": {},
        "sub_device_bindings": {},
        "cmd_bindings": {ck: entity_id_like for ck in command_keys},
    }
    return hashed_id, device_obj, resolution_entry


def build_device_payload(registries: dict) -> dict:
    """
    Run Stages 1, 3, 4, 6, 7, 8. One device per HA device_id, always.
    Returns:
      { "devices": {hashedId: device_object, ...},
        "resolution_map": {hashedId: {...}, ...},
        "tts_engines": [ {entity_id, name}, ... ] }
    """
    picker_map = _load_json("picker_capability_map.json")
    vocab = _load_json("webcore_vocab.json")
    attr_to_caps = build_attr_to_capabilities_index(vocab)

    state_map = {s["entity_id"]: s for s in registries["states"]}
    entity_map = {e["entity_id"]: e for e in registries["entities"]}
    groups = group_entities(registries)

    devices: dict[str, dict] = {}
    resolution_map: dict[str, dict] = {}

    for group in groups:
        hashed_id, device_obj, resolution_entry = _process_group(
            group, state_map, entity_map, picker_map, vocab, attr_to_caps
        )
        devices[hashed_id] = device_obj
        resolution_map[hashed_id] = resolution_entry

    for service_key in extract_notify_target_services(registries):
        hashed_id, device_obj, resolution_entry = _build_notify_device(service_key, vocab)
        devices[hashed_id] = device_obj
        resolution_map[hashed_id] = resolution_entry

    return {
        "devices": devices,
        "resolution_map": resolution_map,
        "tts_engines": extract_tts_engines(registries),
    }

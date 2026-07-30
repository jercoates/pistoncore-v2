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
import os
import re
from pathlib import Path

logger = logging.getLogger("device_pipeline")

_REPO_ROOT = Path(__file__).resolve().parent.parent

_EXCLUDED_ENTITY_CATEGORIES = {"diagnostic", "config"}


def _is_battery(entity: dict, state_map: dict) -> bool:
    """A battery level, whatever HA filed it under.

    HA tags battery sensors entity_category=diagnostic by convention, so
    excluding diagnostics wholesale made batteries invisible on every NATIVE
    integration (found 2026-07-29 on Jeremy's YoLink sensors: 4 entities on
    his install, but most batteries for anyone not coming through a bridge —
    his Hubitat ones are plain sensors and were fine). "Low battery" is about
    the most common piston there is, and Jeremy uses it, so battery is carved
    out of the exclusion. Nothing else is: config entities and other
    diagnostics stay out."""
    state = state_map.get(entity["entity_id"]) or {}
    if (state.get("attributes") or {}).get("device_class") == "battery":
        return True
    return entity.get("original_device_class") == "battery"

# Declaration attributes picker_capability_map.json's by_declaration_attr
# rules check for (climate/device_tracker/person domains) — read straight
# off the entity's state.attributes dict.
def _declaration_attr_keys(capability_map: dict) -> list[str]:
    """Which HA fields count as declaration signals — read from the picker
    map's OWN by_declaration_attr rules.

    This used to be a hardcoded list, and it drifted (2026-07-30): the map
    grew rules for media_player.media_title and climate.current_humidity that
    the pipeline never evaluated, because their keys weren't in the list. A
    rule nobody reads looks exactly like a rule that doesn't match — the
    editor just quietly offered `⌂ media_title` instead of webCoRE's
    trackDescription. Deriving it means adding a rule to the map is enough to
    make it live, which is what anyone editing that file would expect."""
    keys = set()
    for rules in (capability_map.get("domains") or {}).values():
        keys.update((rules or {}).get("by_declaration_attr") or {})
    return sorted(keys)


def _load_json(filename: str) -> dict:
    from . import customize
    with open(customize.path(filename), encoding="utf-8") as f:
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
    """Generic fallback attribute for an entity with no picker_capability_map
    rule — never silently drop what HA exposes.

    Binds on EXISTENCE (loaded entity), not on current value: an entity whose
    state happens to read unknown/unavailable at scan time is still real and
    will produce values (found live 2026-07-19 — a camera's smart_detect_type
    sensor read 'unknown' because it hadn't detected anything recently, and
    the whole attribute vanished from that camera's bindings while its twin
    on another camera worked). Type falls back to string when there's no
    numeric value to sniff."""
    if state is None:
        return None
    value = state.get("state")
    key = _custom_attribute_key(entity, entity_id)
    try:
        float(value)
        attr_type = "decimal"
    except (TypeError, ValueError):
        attr_type = "string"
    return {"n": key, "t": attr_type}


# HA fields that describe the entity rather than report a reading. Offering
# these as pickable attributes would be noise — nobody writes "if the light's
# supported_color_modes changes".
_PLUMBING_FIELDS = frozenset({
    "friendly_name", "icon", "entity_picture", "device_class", "state_class",
    "unit_of_measurement", "supported_features", "supported_color_modes",
    "attribution", "assumed_state", "editable", "restored", "hidden_by",
    "id", "options", "min", "max", "step", "mode", "pattern",
    "device_trackers", "entity_id",
    # Lists of what the device COULD do — the same kind of thing as
    # supported_features above, just spelled per-domain. Nobody writes "if the
    # thermostat's hvac_modes changes"; the reading is `hvac_mode`, singular,
    # which the vocab already owns.
    "source_list", "hvac_modes", "fan_modes", "preset_modes", "swing_modes",
    "effect_list", "event_types", "operation_list", "available_tones",
    "sound_mode_list", "swing_horizontal_modes",
    # Range/step declarations: the device's limits, not its state.
    "min_temp", "max_temp", "min_humidity", "max_humidity", "target_temp_step",
    "min_color_temp_kelvin", "max_color_temp_kelvin", "min_mireds",
    "max_mireds", "percentage_step", "code_format", "code_arm_required",
    # Unit declarations. The reading is the number next to them.
    "temperature_unit", "precipitation_unit", "pressure_unit",
    "visibility_unit", "wind_speed_unit",
})


def _field_type(value) -> str:
    """webCoRE attribute type for a raw HA field value.

    Types are the vocab's own vocabulary (enum/decimal/integer/string/...);
    piston.module.js:3234 lowercases whatever we send and maps number ->
    decimal, so anything outside that set degrades to a text comparison
    rather than breaking."""
    if isinstance(value, bool):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "decimal"
    if isinstance(value, (dict, list)):
        return "object"
    return "string"


def _vocab_covered_fields(attr_bindings: dict, entity_id: str, vocab: dict) -> set[str]:
    """The HA fields on this entity that a vocab attribute already reads.

    The vocab's `read: "attr:current_temperature"` rules say exactly which HA
    field each webCoRE attribute comes from, so a device whose `temperature`
    is already bound must not ALSO sprout a raw `current_temperature` — the
    user would see the same reading twice under two names. Mirror of
    services_covered_by_vocab on the command side: vocab wins where it has a
    rule, raw fills the gaps (Jeremy, 2026-07-29)."""
    domain = entity_id.split(".", 1)[0]
    covered: set[str] = set()
    for attr_key, bound_entity in attr_bindings.items():
        if bound_entity != entity_id:
            continue
        for rule in (vocab["attributes"].get(attr_key, {}).get("ha") or []):
            if not isinstance(rule, dict):
                continue
            if rule.get("domain") not in (domain, "*", "_any", None):
                continue
            read = str(rule.get("read") or "")
            if read.startswith("attr:"):
                covered.add(read[5:].split("[", 1)[0])
    return covered


def _entity_field_attributes(entity_id: str, state: dict | None,
                             attr_bindings: dict, vocab: dict) -> list[tuple[dict, str]]:
    """Readings that live INSIDE an entity, offered as custom attributes.

    WHY (Jeremy, 2026-07-29, found chasing a lock's `last_code_name`): HA
    reports a device's readings in two shapes — some are their own entity
    (sensor.front_lock_battery, state "97.0"), others ride as fields on
    another entity (lock.front_lock carries last_code_name, codes,
    max_codes). This pipeline only ever walked the entity list, so the second
    shape was invisible end to end: the editor never offered it and the
    compiler had nothing to read. Nothing was lost by the Hubitat bridge —
    the data was there the whole time, one level down.

    Custom attributes are a first-class webCoRE path, not a workaround:
    piston.module.js:3217-3236 has an explicit branch for an attribute the
    central vocab doesn't know, renders it with a ⌂ prefix, and keeps every
    field we send (so `t` and `o` still drive the editor's input type).
    VERIFIED 2026-07-29 by reading that branch, plus the two other places an
    attribute is looked up (the [device : attr] expression autocomplete at
    845-847 and the operand fallback at 3689-3701) — none of the three drops
    an unknown name.

    Returns (attribute_object, ha_field_name) pairs; the field name is what
    the compiler needs to emit state_attr(entity, field) instead of reading
    the entity's state."""
    if state is None:
        return []
    covered = _vocab_covered_fields(attr_bindings, entity_id, vocab)
    out = []
    for field, value in sorted((state.get("attributes") or {}).items()):
        if field in _PLUMBING_FIELDS or field.startswith("_") or field in covered:
            continue
        if value is None:
            # Nothing to type-sniff and nothing to compare against. Unlike an
            # entity (which is real even when its state reads unknown), a
            # null field is usually one the integration simply doesn't fill.
            continue
        out.append(({"n": field, "t": _field_type(value)}, field))
    return out


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
        "member_entity_ids": [entity_id, ...],
        "area_name": <HA Area name, or None if unassigned> }
    """
    device_map = {d["id"]: d for d in registries["devices"]}
    state_map = {s["entity_id"]: s for s in registries["states"]}
    area_map = {a["area_id"]: a["name"] for a in registries["areas"]}

    groups: dict[str, dict] = {}
    excluded = []

    for entity in registries["entities"]:
        if entity.get("disabled_by") is not None:
            excluded.append((entity["entity_id"], "disabled"))
            continue
        if entity.get("entity_category") in _EXCLUDED_ENTITY_CATEGORIES \
                and not _is_battery(entity, state_map):
            excluded.append((entity["entity_id"], f"entity_category={entity['entity_category']}"))
            continue

        device_id = entity.get("device_id")
        entity_id = entity["entity_id"]

        if device_id and device_id in device_map:
            group_key = device_id
            device = device_map[device_id]
            display_name = device.get("name_by_user") or device.get("name") or device_id
            # Entity-level area_id overrides the device's own, same precedence
            # HA itself uses (Settings > Areas resolves entity override first).
            area_id = entity.get("area_id") or device.get("area_id")
        else:
            group_key = entity_id
            display_name = _friendly_name(entity_id, state_map)
            area_id = entity.get("area_id")

        group = groups.setdefault(group_key, {
            "group_key": group_key,
            "display_name": display_name,
            "member_entity_ids": [],
            "area_name": None,
        })
        group["member_entity_ids"].append(entity_id)
        # First contributing member's area wins, same rule as attribute/
        # capability binding below — a group's members rarely disagree on
        # area in practice, but don't let a later member silently override.
        if group["area_name"] is None and area_id:
            group["area_name"] = area_map.get(area_id)

    logger.info("Stage 1 grouping: %d groups from %d entities, %d excluded",
                len(groups), len(registries["entities"]), len(excluded))
    for entity_id, reason in excluded:
        logger.debug("Stage 1 excluded %s: %s", entity_id, reason)

    return list(groups.values())


# ---------------------------------------------------------------------------
# Stage 3 — picker_capability_map.json rule evaluator
# ---------------------------------------------------------------------------

def _entity_signals(entity_id: str, state: dict | None, capability_map: dict | None = None) -> dict:
    domain = entity_id.split(".", 1)[0]
    attrs = state["attributes"] if state else {}
    keys = _declaration_attr_keys(capability_map or {})
    return {
        "domain": domain,
        "device_class": attrs.get("device_class"),
        "supported_color_modes": attrs.get("supported_color_modes"),
        "supported_features": attrs.get("supported_features"),
        "unit_of_measurement": attrs.get("unit_of_measurement"),
        "declaration_attrs": {k: attrs.get(k) for k in keys if attrs.get(k) is not None},
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
    # attribute name -> the HA FIELD inside that entity holding the value.
    # Only populated for readings that aren't the entity's own state; absence
    # means "read the state", which keeps every existing binding unchanged.
    attr_field_bindings: dict[str, str] = {}
    sub_device_members: dict[str, list[str]] = {}
    cmd_bindings: dict[str, str] = {}
    capability_keys: set[str] = set()
    direct_cap_contributors: dict[str, str] = {}
    custom_attrs: list[dict] = []

    for entity_id in member_ids_sorted:
        state = state_map.get(entity_id)
        signals = _entity_signals(entity_id, state, picker_map)
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

    # Readings that live inside an entity rather than as one of their own.
    # Runs after the loop above so the vocab-covered check sees this group's
    # FINAL bindings — otherwise a field would be offered raw just because
    # its vocab attribute happened to bind on a later member entity.
    for entity_id in member_ids_sorted:
        for field_attr, ha_field in _entity_field_attributes(
                entity_id, state_map.get(entity_id), attr_bindings, vocab):
            if field_attr["n"] in attr_bindings:
                continue        # first contributor wins, as everywhere else
            custom_attrs.append(field_attr)
            attr_bindings[field_attr["n"]] = entity_id
            attr_field_bindings[field_attr["n"]] = ha_field

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

    # HA Area name, standing in for Hubitat's roomNameWC (no roomIdWC — HA
    # Areas have no numeric id, Jeremy 2026-07-12: skip rather than fabricate
    # one). Always known at grouping time (registry data, not a live HA
    # state), so v is populated immediately unlike the Stage-5-deferred
    # attributes above. Omitted entirely when the device has no HA Area
    # assigned — never emit an attribute with no real value.
    if group.get("area_name"):
        a.append({"n": "roomNameWC", "t": "string", "v": group["area_name"]})

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
        "attr_field_bindings": attr_field_bindings,
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


def extract_notify_entities(registries: dict) -> list[dict]:
    """notify.* entities that are candidate email/message notifiers for the
    sendEmail 'email notifier' setting. Excludes persistent_notification (HA's
    own dashboard toast, not a real destination) and mobile_app_* (those are
    push targets already surfaced as picker devices). HA can't flag WHICH of
    the rest is email, so the user picks — this only supplies the candidate
    list for that selection."""
    out = []
    for s in registries["states"]:
        eid = s["entity_id"]
        if not eid.startswith("notify."):
            continue
        tail = eid.split(".", 1)[1]
        if tail == "persistent_notification" or tail.startswith("mobile_app_"):
            continue
        out.append({"entity_id": eid,
                    "name": s["attributes"].get("friendly_name", eid)})
    return out


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


def describe_domain_services(services: dict, domain: str, limit: int = 60) -> list[dict]:
    """What THIS install can actually do in one HA domain: every service the
    user's integrations register there, with its fields.

    WHY (Jeremy, 2026-07-26 — "feeding the new things into webcore is a huge
    fix and a key to unlocking ha"): a Hubitat DRIVER exposes custom commands
    and webCoRE simply offers them, which is why pistons contain things like
    clearImages or searchAmazonMusic that appear in no webCoRE source. HA
    integrations do the same thing through the service registry, so the same
    trick works from the HA side — instead of asking someone to invent a
    mapping for an unknown command, show them the services their own install
    provides and let them (or an AI) pick. An AI cannot hallucinate a service
    that isn't in this list, which is the real value.

    Shape per HA's get_services: {domain: {service: {name, description,
    fields, target}}}. Read defensively — integrations vary in what they fill
    in, and HA has changed field metadata across versions."""
    found = (services or {}).get(domain) or {}
    out = []
    for name in sorted(found):
        spec = found.get(name) or {}
        fields = spec.get("fields") or {}
        required = sorted(f for f, meta in fields.items()
                          if isinstance(meta, dict) and meta.get("required"))
        out.append({
            "service": f"{domain}.{name}",
            "name": spec.get("name") or name,
            "description": (spec.get("description") or "").strip(),
            "fields": sorted(fields),
            "required": required,
        })
        if len(out) >= limit:
            break
    return out


def domains_offering(services: dict, service_name: str) -> list[str]:
    """Which domains register a service of this name — for the case where the
    piston's command is known but the right domain isn't."""
    return sorted(d for d, entries in (services or {}).items()
                  if isinstance(entries, dict) and service_name in entries)


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


def _field_applies(meta: dict, features: int, attributes: dict) -> bool:
    """Does this service FIELD apply to this entity?

    HA declares field-level applicability the same way it declares
    service-level: a `filter` carrying either `supported_features` bits or an
    `attribute` requirement (VERIFIED live 2026-07-27 — light.turn_on's
    rgb_color needs supported_color_modes in hs/xy/rgb/…, effect needs feature
    bit 4, transition needs 32).

    Without this a plain "turn the light on" offers fifteen fields including
    colour options a brightness-only bulb cannot use — unusable, and Jeremy
    said so on sight. With it, HA itself says which ones are real."""
    filt = meta.get("filter")
    if not isinstance(filt, dict):
        return True
    required = filt.get("supported_features")
    if required:
        bits = required if isinstance(required, list) else [required]
        if not any(isinstance(b, int) and features & b for b in bits):
            return False
    attr_filter = filt.get("attribute")
    if isinstance(attr_filter, dict):
        for attr_name, allowed in attr_filter.items():
            have = attributes.get(attr_name)
            allowed_list = allowed if isinstance(allowed, list) else [allowed]
            if isinstance(have, list):
                if not set(have) & set(allowed_list):
                    return False
            elif have not in allowed_list:
                return False
    return True


def _service_params(spec: dict, features: int = 0,
                    attributes: dict | None = None) -> list[dict]:
    """An HA service's fields as a webCoRE command parameter list.

    Hubitat built `p` from the DRIVER's own parameter metadata, never from
    webCoRE's dictionary (webcore.groovy:3604 getDevDetails) — name, a `*`
    prefix for mandatory, type, description, constraints. HA's service fields
    carry the same information under different keys, so this is a rename, not
    a design."""
    out = []
    attributes = attributes or {}

    def _flatten(fields: dict) -> list[tuple[str, dict]]:
        """HA groups fields into containers — an entry with its own nested
        `fields`, often `collapsed: true` (light.turn_on hides rgbw_color,
        brightness, profile and friends that way).

        The container itself is UI structure, never a parameter — emitting it
        would put a field literally named 'additional_fields' in front of the
        user. A COLLAPSED group is dropped entirely: Home Assistant hides those
        by default precisely because they're rarely wanted, and reproducing its
        judgement keeps the list short. A non-collapsed group is flattened in.
        """
        flat = []
        for name, meta in sorted((fields or {}).items()):
            if not isinstance(meta, dict):
                continue
            nested = meta.get("fields")
            if isinstance(nested, dict):
                if not meta.get("collapsed"):
                    flat.extend(_flatten(nested))
                continue
            flat.append((name, meta))
        return flat

    for field, meta in _flatten(spec.get("fields") or {}):
        if not _field_applies(meta, features, attributes):
            continue
        param = {"n": field, "t": "string"}
        selector = meta.get("selector") or {}
        if "number" in selector:
            param["t"] = "integer"
        elif "boolean" in selector:
            param["t"] = "boolean"
        elif "select" in selector:
            options = (selector.get("select") or {}).get("options") or []
            param["t"] = "enum"
            param["o"] = [o.get("value", o) if isinstance(o, dict) else o
                          for o in options]
        if meta.get("required"):
            param["m"] = 1          # Hubitat's '*' mandatory marker
        if meta.get("description"):
            param["h"] = str(meta["description"])[:200]
        out.append(param)
    return out


def detect_passthroughs(services: dict) -> dict:
    """Services that take a COMMAND NAME as data — an integration's own escape
    hatch for driver commands Home Assistant has no vocabulary for.

    Detected by SHAPE, not by a list of integrations: any service with a field
    whose name contains "command" is passing a command through rather than
    doing one specific thing. VERIFIED live 2026-07-29 — this finds
    `hubitat.send_command` (entity_id/command/args), the CORE
    `remote.send_command` (device/command/...) which is how Harmony activities
    are driven, and the CORE `vacuum.send_command` (command/params).

    Returns {key: spec} where key is the entity domain it serves ("remote",
    "vacuum") or, for integration-level passthroughs, the platform name
    ("hubitat"). spec names which field carries the command, which carries the
    arguments, and which carries the target.
    """
    out = {}
    for domain in sorted(services):
        for name, spec in (services.get(domain) or {}).items():
            fields = list((spec.get("fields") or {}).keys())
            command_field = next((f for f in fields if "command" in f), None)
            if not command_field or not name.endswith("send_command"):
                continue
            args_field = next((f for f in fields if f in ("args", "params")), None)
            target_field = next((f for f in fields if f in ("entity_id", "device")), None)
            out[domain] = {
                "service": f"{domain}.{name}",
                "command_field": command_field,
                "args_field": args_field,
                "target_field": target_field,
            }
    return out


def passthrough_for(passthroughs: dict, members: list, entity_platforms: dict) -> dict | None:
    """Which passthrough can drive this device's driver commands.

    Entity DOMAIN wins first — a `remote.` entity is driven by
    remote.send_command, a `vacuum.` by vacuum.send_command. Otherwise fall
    back to the INTEGRATION that supplied the entity, which is how a bridged
    device reaches its hub (hubitat.send_command). Returns the spec plus the
    entity to aim it at."""
    for entity_id in members or []:
        domain = entity_id.split(".", 1)[0]
        if domain in passthroughs:
            return {**passthroughs[domain], "entity_id": entity_id}
    for entity_id in members or []:
        platform = entity_platforms.get(entity_id)
        if platform and platform in passthroughs:
            return {**passthroughs[platform], "entity_id": entity_id}
    return None


def services_covered_by_vocab(cmd_bindings: dict, vocab: dict) -> set:
    """The HA services this device already reaches through webCoRE's own
    commands.

    THE HYBRID RULE (Jeremy, firm 2026-07-28): "simpler setup for lights etc is
    worth keeping the json hands down. it's the things that map cleaner as raw
    because they don't fit in or are not in it." So the vocab wins wherever it
    covers the same service, and the raw feed fills only the gaps — otherwise
    the editor lists `Turn on` and `light.turn_on` side by side, which is the
    duplication Jeremy objected to on sight.

    Derived, never a maintained list: the vocab already says what each command
    compiles to, so the set of already-covered services falls out of the
    device's own command bindings.
    """
    commands = {**vocab.get("commands", {}), **vocab.get("virtualCommands", {})}
    covered = set()
    for command, entity in (cmd_bindings or {}).items():
        domain = str(entity).split(".", 1)[0]
        for rule in (commands.get(command, {}) or {}).get("ha") or []:
            if not isinstance(rule, dict):
                continue
            if rule.get("domain") not in (domain, "*", "_any"):
                continue
            service = rule.get("service")
            if service:
                covered.add(service)
            break
    return covered


def _service_allowed(spec: dict, domain: str, features: int) -> bool:
    """Can THIS entity actually run this service?

    HA's service registry declares its own requirements — a service's
    `target.entity[]` carries `supported_features` bitmasks (VERIFIED live
    2026-07-27: fan.set_preset_mode requires [8], fan.oscillate [2],
    siren.turn_on [1]). So the filter is read from Home Assistant rather than
    maintained by hand, and it updates itself when HA does.

    Without this, the registry is per-DOMAIN and every fan gets offered
    oscillate and set_direction whether it can do them or not — measurably
    worse than the hand-built picker map it would otherwise replace. Hubitat
    asked the DEVICE what it supported; this is how the same question gets a
    true answer out of HA.

    An entry with no supported_features requirement is unrestricted. Multiple
    entries are alternatives — matching any one is enough.
    """
    entries = (spec.get("target") or {}).get("entity") or []
    if not entries:
        return True
    for entry in entries:
        domains = entry.get("domain")
        if domains and domain not in (domains if isinstance(domains, list) else [domains]):
            continue
        required = entry.get("supported_features")
        if not required:
            return True
        for bit in (required if isinstance(required, list) else [required]):
            if isinstance(bit, int) and features & bit:
                return True
    return False


def entity_features(states: dict, entity_ids: list[str], domain: str) -> int:
    """Union of supported_features across this device's entities in a domain —
    a device offers a capability if any of its entities in that domain has it."""
    total = 0
    for entity_id in entity_ids:
        if not entity_id.startswith(domain + "."):
            continue
        state = states.get(entity_id) or {}
        value = (state.get("attributes") or {}).get("supported_features")
        if isinstance(value, int):
            total |= value
    return total


def entity_attributes(states: dict, entity_ids: list[str], domain: str) -> dict:
    """Merged attributes of this device's entities in a domain — what the
    field-level filters test against (supported_color_modes and friends).
    List-valued attributes are unioned, the same first-wins rule as elsewhere."""
    merged: dict = {}
    for entity_id in entity_ids:
        if not entity_id.startswith(domain + "."):
            continue
        for key, value in ((states.get(entity_id) or {}).get("attributes") or {}).items():
            if isinstance(value, list) and isinstance(merged.get(key), list):
                merged[key] = sorted(set(merged[key]) | set(value))
            else:
                merged.setdefault(key, value)
    return merged


def ha_service_commands(services: dict, domains: set[str],
                        states: dict | None = None,
                        members: list[str] | None = None) -> list[dict]:
    """Every HA service for these domains, as webCoRE command entries.

    EXPERIMENT (Jeremy, 2026-07-27): feed HA in the way Hubitat fed drivers —
    all of them, unfiltered, parameters from the source rather than the vocab.
    Names stay DOMAIN-QUALIFIED (`light.turn_on`), which removes the name
    collisions Hubitat needed commandOverrides() for, and makes the command
    self-describing: the name IS the service, so nothing needs translating.

    ON BY DEFAULT since 2026-07-30 (Jeremy: "there is no reason to gate it").
    Set PISTONCORE_FEED_HA_SERVICES=0 to turn it back off without a rebuild."""
    out = []
    live = states is not None and members is not None
    for domain in sorted(domains):
        features = entity_features(states, members, domain) if live else 0
        attributes = entity_attributes(states, members, domain) if live else {}
        for name in sorted((services.get(domain) or {})):
            spec = (services[domain] or {}).get(name) or {}
            if live and not _service_allowed(spec, domain, features):
                continue
            entry = {"n": f"{domain}.{name}"}
            params = _service_params(spec, features, attributes) if live \
                else _service_params(spec)
            if params:
                entry["p"] = params
            out.append(entry)
    return out


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
    _passthroughs = detect_passthroughs(registries.get("services") or {})
    _entity_platforms = {e["entity_id"]: e.get("platform") for e in registries["entities"]}

    devices: dict[str, dict] = {}
    resolution_map: dict[str, dict] = {}
    skipped: list[dict] = []

    for group in groups:
        # One malformed device must NOT take down the whole dashboard (a fresh
        # user's varied HA is exactly where an unhandled shape shows up). Skip it,
        # record why, and keep every other device working.
        try:
            hashed_id, device_obj, resolution_entry = _process_group(
                group, state_map, entity_map, picker_map, vocab, attr_to_caps
            )
        except Exception as exc:
            logger.exception("device pipeline skipped group %s", group.get("display_name"))
            skipped.append({
                "device": group.get("display_name"),
                "group_key": group.get("group_key"),
                "entities": group.get("member_entity_ids"),
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue
        # Append every HA service for the domains this device actually has
        # entities in, as extra commands — the Hubitat model (all of them,
        # params from source). The editor treats anything it doesn't recognise
        # as a custom command (piston.module.js:2840, cm/$custom), so this
        # needs no vocab entry.
        #
        # ON BY DEFAULT (Jeremy, 2026-07-30). It was opt-in while unproven;
        # it has since been verified end to end on real hardware (`take` via
        # hubitat.send_command produced a picture, 2026-07-29) and the
        # attribute feed already shipped on, so the gate was just
        # inconsistency. PISTONCORE_FEED_HA_SERVICES=0 disables it without a
        # rebuild, for an install where the extra commands cause trouble.
        if os.environ.get("PISTONCORE_FEED_HA_SERVICES", "1") != "0":
            try:
                domains = {e.split(".", 1)[0]
                           for e in resolution_entry.get("members") or []}
                known = {c.get("n") for c in device_obj.get("c") or []}
                # HYBRID: don't offer a raw service the vocab already reaches
                # on this device — the friendly command is better (it reads
                # properly and stays correct if the device type changes).
                known |= services_covered_by_vocab(
                    resolution_entry.get("cmd_bindings") or {}, vocab)
                members = resolution_entry.get("members") or []
                extra = [c for c in ha_service_commands(
                    registries.get("services") or {}, domains,
                    states=state_map, members=members)
                    if c["n"] not in known]
                device_obj["c"] = (device_obj.get("c") or []) + extra
            except Exception:
                logger.exception("HA-service feed skipped for %s",
                                 group.get("display_name"))

        # How this device's DRIVER commands can be reached — the integration's
        # own command passthrough, if it has one. Recorded here because the
        # compiler has no access to the service registry, only this map.
        through = passthrough_for(_passthroughs, resolution_entry.get("members") or [],
                                 _entity_platforms)
        if through:
            resolution_entry["passthrough"] = through

        devices[hashed_id] = device_obj
        resolution_map[hashed_id] = resolution_entry

    for service_key in extract_notify_target_services(registries):
        try:
            hashed_id, device_obj, resolution_entry = _build_notify_device(service_key, vocab)
        except Exception as exc:
            logger.exception("device pipeline skipped notify %s", service_key)
            skipped.append({"device": f"notify:{service_key}", "error": f"{type(exc).__name__}: {exc}"})
            continue
        devices[hashed_id] = device_obj
        resolution_map[hashed_id] = resolution_entry

    # "$system" — webCoRE system variables that resolve to HA entities.
    # Reserved key, can't collide with device hashes (those are :hex:).
    # alarmSystemStatus binds only when exactly ONE alarm panel exists —
    # ambiguity is a settings question, never a guess.
    system_entities = {"mode": "input_select.pistoncore_location_mode"}
    alarm_panels = [s["entity_id"] for s in registries["states"]
                    if s["entity_id"].startswith("alarm_control_panel.")]
    if len(alarm_panels) == 1:
        system_entities["alarmSystemStatus"] = alarm_panels[0]
        # webCoRE's "alarm system alert" is the same panel reporting triggered
        system_entities["alarmSystemAlert"] = alarm_panels[0]
    # $hsmStatus — Hubitat Safety Monitor, the HUB's own armed state, which is
    # not the same thing as a keypad. Jeremy's setup has both: the keypad is
    # the input device ("Arm/Disarm with Keypad"), while HSM holds the status
    # pistons actually read (VERIFIED live 2026-07-29 — sensor.hub_hsm_status
    # reads 'disarmed' while alarm_control_panel.keypad exists separately).
    # The Hubitat integration publishes it as a plain sensor whose STATE is
    # the status string, so values pass through as webCoRE already spells
    # them; nothing to translate.
    hsm = [s["entity_id"] for s in registries["states"]
           if s["entity_id"].startswith("sensor.") and s["entity_id"].endswith("hsm_status")]
    if len(hsm) == 1:
        system_entities["hsmStatus"] = hsm[0]
    # TTS engine for Speak (SPEAK_ACTION_SPEC §5.4: engine resolved at compile
    # time from a global setting; auto-pick only when unambiguous)
    from . import storage as _storage
    engines = extract_tts_engines(registries)
    configured = _storage.load_settings().get("tts_engine")
    if configured and any(e["entity_id"] == configured for e in engines):
        system_entities["tts"] = configured
    elif len(engines) == 1:
        system_entities["tts"] = engines[0]["entity_id"]
    # Email notifier for sendEmail (Jeremy 2026-07-24, Hubitat model: the email
    # INTEGRATION is set up in HA — 2026.7+ SMTP creates a notify entity — and
    # sendEmail routes through it). Bound by EXPLICIT selection, never an
    # auto-guess: HA cannot tell an SMTP notifier from a Telegram/Slack one at
    # the entity level, so picking "the email one" is a deliberate setting, the
    # same override shape as tts above. Unset -> sendEmail raises a clear,
    # actionable compile error (emit_yaml._send_email) rather than mis-routing.
    email_notifier = _storage.load_settings().get("email_notify_entity")
    if email_notifier:
        system_entities["email"] = email_notifier
    resolution_map["$system"] = system_entities

    if skipped:
        logger.warning("device pipeline skipped %d device(s): %s",
                       len(skipped), [s["device"] for s in skipped])

    return {
        "devices": devices,
        "resolution_map": resolution_map,
        "tts_engines": extract_tts_engines(registries),
        "skipped": skipped,
    }

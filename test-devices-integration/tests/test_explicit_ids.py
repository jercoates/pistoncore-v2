"""Stand-ins keep the identity they were given.

REGRESSION GUARD for what lets one Home Assistant stand in for another. An entry
in the devices file may name its own `entity_id`; it then keeps exactly that id,
and its `unique_id` is DERIVED from the id rather than invented, so a regenerated
file maps onto the same registry rows instead of creating a second set.

Also holds down the other half: entries that do NOT name an id still get a
generated one exactly as they always did, because every existing virtual.yaml
depends on that.
"""

import logging

import pytest
import voluptuous as vol

from conftest import FakeEntry, FakeHass, run

from custom_components.virtual.cfg import BlendedCfg, _save_user_data
from custom_components.virtual.entity import VirtualEntity, virtual_schema


def _load(tmp_path, devices):
    hass = FakeHass(config_dir=tmp_path)
    entry = FakeEntry(tmp_path / "virtual.yaml")
    run(_save_user_data(str(tmp_path / "virtual.yaml"), devices))
    cfg = BlendedCfg(hass, entry.data)
    run(cfg.async_load())
    return cfg


def _entities(cfg):
    return {e["entity_id"]: e for group in cfg.entities.values() for e in group}


def test_an_entry_keeps_the_entity_id_it_names(tmp_path):
    cfg = _load(tmp_path, {"Hall": [
        {"platform": "light", "name": "Hall Light", "entity_id": "light.hall_ceiling"}]})
    assert list(_entities(cfg)) == ["light.hall_ceiling"]


def test_unique_id_comes_from_the_id_not_from_chance_or_the_name(tmp_path):
    first = _load(tmp_path, {"Hall": [
        {"platform": "light", "name": "Hall Light", "entity_id": "light.hall_ceiling"}]})
    second = _load(tmp_path, {"Hall": [
        {"platform": "light", "name": "A Different Name", "entity_id": "light.hall_ceiling"}]})
    a = _entities(first)["light.hall_ceiling"]["unique_id"]
    b = _entities(second)["light.hall_ceiling"]["unique_id"]
    assert a == b and "hall_ceiling" in a  # stable across loads and renames


def test_an_explicit_unique_id_in_the_file_is_honoured(tmp_path):
    cfg = _load(tmp_path, {"Hall": [
        {"platform": "light", "name": "L", "entity_id": "light.l", "unique_id": "mine"}]})
    assert _entities(cfg)["light.l"]["unique_id"] == "mine"


def test_named_entries_need_no_row_in_the_meta_file(tmp_path):
    """Their identity is in the file, so they can never be 'orphaned' through the
    name-keyed meta data, and cannot collide with name-keyed entries."""
    cfg = _load(tmp_path, {"Hall": [
        {"platform": "light", "name": "Hall Light", "entity_id": "light.hall_ceiling"}]})
    assert cfg._meta_data == {}
    assert cfg.trusted


def test_entries_without_an_id_are_generated_exactly_as_before(tmp_path):
    """The control. If this changed, every existing virtual.yaml would be orphaned."""
    cfg = _load(tmp_path, {"Hall": [
        {"platform": "switch", "name": "Old Style"},
        {"platform": "switch", "name": "New Style", "entity_id": "switch.new_style"}]})
    by_id = _entities(cfg)
    assert "switch.old_style" in by_id and "switch.new_style" in by_id
    assert by_id["switch.old_style"]["unique_id"].endswith(".virtual")
    assert "Old Style" in cfg._meta_data and "New Style" not in cfg._meta_data


def test_an_id_in_the_wrong_domain_is_skipped_and_reported(tmp_path, caplog):
    with caplog.at_level(logging.ERROR):
        cfg = _load(tmp_path, {"Hall": [
            {"platform": "switch", "name": "X", "entity_id": "light.not_a_switch"},
            {"platform": "switch", "name": "Fine", "entity_id": "switch.fine"}]})
    assert list(_entities(cfg)) == ["switch.fine"]
    assert "light.not_a_switch" in caplog.text


def test_a_repeated_id_keeps_the_first(tmp_path, caplog):
    with caplog.at_level(logging.ERROR):
        cfg = _load(tmp_path, {
            "A": [{"platform": "switch", "name": "First", "entity_id": "switch.same"}],
            "B": [{"platform": "switch", "name": "Second", "entity_id": "switch.same"}]})
    assert _entities(cfg)["switch.same"]["name"] == "First"
    assert len(cfg.entities["switch"]) == 1


def test_capitals_are_lowered_with_a_warning_not_refused(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        cfg = _load(tmp_path, {"A": [
            {"platform": "switch", "name": "Caps", "entity_id": "Switch.Caps_Test"}]})
    assert list(_entities(cfg)) == ["switch.caps_test"]
    assert "capitals" in caplog.text


def test_a_missing_name_is_made_from_the_id(tmp_path):
    cfg = _load(tmp_path, {"A": [{"platform": "switch", "entity_id": "switch.no_name_given"}]})
    assert _entities(cfg)["switch.no_name_given"]["name"] == "No Name Given"


# ── devices that say what they are ──────────────────────────────────────────

def test_a_device_can_say_what_it_is(tmp_path):
    cfg = _load(tmp_path, {"abc123": {
        "name": "Hall Plug", "manufacturer": "Acme", "model": "P1",
        "sw_version": "2.0", "area": "Hall",
        "entities": [{"platform": "switch", "name": "Power", "entity_id": "switch.hall_plug"}]}})
    device = cfg.devices[0]
    assert device["device_id"] == "abc123"
    assert (device["name"], device["manufacturer"], device["model"],
            device["sw_version"], device["area"]) == ("Hall Plug", "Acme", "P1", "2.0", "Hall")
    assert list(_entities(cfg)) == ["switch.hall_plug"]


def test_the_shorthand_device_form_still_works_and_adds_no_metadata(tmp_path):
    cfg = _load(tmp_path, {"Hall Plug": [{"platform": "switch", "name": "Power"}]})
    device = cfg.devices[0]
    assert device["name"] == "Hall Plug"
    assert not {"manufacturer", "model", "sw_version", "area"} & set(device)


def test_unknown_device_keys_are_ignored_not_fatal(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        cfg = _load(tmp_path, {"d": {"name": "D", "wat": 1, "entities": [
            {"platform": "switch", "name": "S", "entity_id": "switch.s"}]}})
    assert list(_entities(cfg)) == ["switch.s"]
    assert "wat" in caplog.text


def test_a_device_with_no_entities_loads_as_an_empty_device(tmp_path):
    cfg = _load(tmp_path, {"d": {"name": "Empty", "entities": []}})
    assert cfg.devices[0]["name"] == "Empty" and not cfg.entities


# ── the entity itself ───────────────────────────────────────────────────────

def _entity(**extra):
    schema = vol.Schema(virtual_schema("off", {}))
    config = schema({"name": "Thing", **extra})
    return VirtualEntity(config, "switch", False)


def test_the_entity_takes_the_id_it_was_given():
    assert _entity(entity_id="switch.exactly_this").entity_id == "switch.exactly_this"


def test_entity_category_is_carried_to_the_entity():
    assert _entity(entity_category="diagnostic").entity_category.value == "diagnostic"


def test_an_entity_with_no_category_has_none():
    assert _entity().entity_category is None


def test_an_unknown_category_is_refused_by_the_schema():
    with pytest.raises(vol.Invalid):
        _entity(entity_category="decorative")


def test_the_entity_does_not_overwrite_the_devices_maker_and_model():
    """The device is created in full first; repeating the constants on every
    entity add would write them back over what the file said."""
    info = _entity(device_id="d1").device_info
    assert info["identifiers"] == {("virtual", "d1")}
    assert "manufacturer" not in info and "model" not in info


# ── when may a load be believed enough to remove things? ────────────────────

def _load_text(tmp_path, text):
    """Load a group whose file contains exactly `text` (or no file when None)."""
    hass = FakeHass(config_dir=tmp_path)
    path = tmp_path / "virtual.yaml"
    if text is not None:
        path.write_text(text, encoding="utf-8")
    cfg = BlendedCfg(hass, FakeEntry(path).data)
    run(cfg.async_load())
    return cfg


def test_a_missing_file_is_a_new_group_and_is_trusted(tmp_path):
    assert _load_text(tmp_path, None).trusted


EMPTY_BUT_VALID = """version: 1
devices: {}
"""
NORMAL_FILE = """version: 1
devices:
  A:
  - {platform: switch, name: S}
"""
BLANK = ""
SPACES = "   "
WORDS = "just some words"
A_LIST = """- a
- list
"""
UNCLOSED = "key: [unclosed"


def test_a_file_that_says_it_has_no_devices_is_trusted(tmp_path):
    """The control: removing the last device leaves exactly this, and the registry
    rows for it must then be cleaned up."""
    assert _load_text(tmp_path, EMPTY_BUT_VALID).trusted


def test_a_normal_file_is_trusted(tmp_path):
    assert _load_text(tmp_path, NORMAL_FILE).trusted


@pytest.mark.parametrize("text", [BLANK, SPACES, WORDS, A_LIST, UNCLOSED])
def test_a_blank_or_unreadable_file_is_not_trusted(tmp_path, text):
    """A copy still being written looks exactly like this, and treating it as 'the
    file lists nothing' would remove every entity in the group."""
    assert not _load_text(tmp_path, text).trusted


def test_a_rejected_entry_stops_the_load_being_trusted(tmp_path):
    """A typo in a regenerated file must not delete the existing row for the entity
    it was meant to be: its history and its area would go with it."""
    cfg = _load(tmp_path, {"A": [{"platform": "switch", "name": "X", "entity_id": "light.typo"}]})
    assert not cfg.trusted

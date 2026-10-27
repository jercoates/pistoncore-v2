"""Exporting a Home Assistant's devices as stand-ins.

REGRESSION GUARD for three things that are easy to get quietly wrong:

* WHAT A COPY MAY CARRY. Lock and alarm codes and text-field passwords never
  reach the file, however the source device reports them.
* WHAT IT SKIPS AND WHY. Every skipped entity is accounted for, so a stand-in
  missing from the test Home Assistant is explained rather than mysterious.
* THAT IT LOADS BACK. The file is checked against each platform's own closed
  schema before it is written, and a full round trip (export, then load) must give
  the same entity ids.

Real names and ids are kept on purpose — that is what makes a stand-in a stand-in.
"""

import json
import pathlib
import types

import pytest
import yaml

from conftest import FakeEntry, FakeHass, run

from custom_components.virtual import export
from custom_components.virtual.cfg import BlendedCfg
from custom_components.virtual.clone import REPRODUCIBLE_DOMAINS


class Units:
    temperature_unit = "°C"


class Config:
    units = Units()


def ns(**kw):
    return types.SimpleNamespace(**kw)


def state(entity_id, value, **attrs):
    return ns(entity_id=entity_id, state=value, attributes=attrs)


def row(entity_id, **kw):
    base = dict(entity_id=entity_id, platform="demo", disabled=False, hidden=False,
                device_id=None, area_id=None, name=None, original_name=None,
                device_class=None, original_device_class=None, entity_category=None)
    base.update(kw)
    return ns(**base)


HASS = ns(config=Config())


def entry_for(entity_id, value="on", persistent=None, **attrs):
    return export._entity_entry(HASS, row(entity_id), state(entity_id, value, **attrs), persistent)


# ── one entity's entry ──────────────────────────────────────────────────────

def test_the_live_state_becomes_the_starting_state():
    e = entry_for("switch.plug", "on")
    assert e["entity_id"] == "switch.plug" and e["initial_value"] == "on"


def test_the_friendly_name_is_kept_as_the_name():
    assert entry_for("switch.plug", friendly_name="Hall Plug")["name"] == "Hall Plug"


def test_an_unavailable_entity_starts_unavailable_with_no_value():
    e = entry_for("switch.plug", "unavailable")
    assert e["initial_availability"] is False and "initial_value" not in e


def test_an_unknown_state_gives_no_starting_value_and_does_not_claim_unavailable():
    e = entry_for("sensor.x", "unknown")
    assert "initial_value" not in e and "initial_availability" not in e


@pytest.mark.parametrize("domain", ["button", "camera", "event", "notify"])
def test_stateless_domains_carry_no_starting_value(domain):
    """Their 'state' is a timestamp or a stream status, not a setting."""
    assert "initial_value" not in entry_for(f"{domain}.x", "2026-10-26T10:00:00")


def test_a_password_text_carries_no_value():
    assert "initial_value" not in entry_for("text.pin", "hunter2", mode="password")


def test_an_ordinary_text_keeps_its_value():
    assert entry_for("text.name", "Hello", mode="text")["initial_value"] == "Hello"


def test_a_light_keeps_brightness_colour_and_effect_but_not_colour_temperature():
    e = entry_for("light.lamp", "on", brightness=128, hs_color=(10.0, 50.0),
                  effect="rainbow", color_temp_kelvin=3000)
    assert (e["initial_brightness"], e["initial_color"], e["initial_effect"]) == (
        128, [10.0, 50.0], "rainbow")
    assert not any("temp" in key for key in e)


def test_entity_category_is_carried():
    from homeassistant.const import EntityCategory
    e = export._entity_entry(
        HASS, row("sensor.rssi", entity_category=EntityCategory.DIAGNOSTIC),
        state("sensor.rssi", "-60"), None)
    assert e["entity_category"] == "diagnostic"


def test_persistent_is_only_written_when_it_was_asked_for():
    assert "persistent" not in entry_for("switch.plug")
    assert entry_for("switch.plug", persistent=False)["persistent"] is False


# ── what a copy must NEVER carry ────────────────────────────────────────────

SECRETS = {"codes": {"1": {"name": "Bob", "code": "4821"}}, "last_code_name": "Bob",
           "code": "4821", "pin": "4821", "changed_by": "Bob"}


@pytest.mark.parametrize("domain", ["lock", "alarm_control_panel"])
def test_no_code_name_or_pin_survives_for_locks_and_alarm_panels(domain):
    e = entry_for(f"{domain}.front", "locked", supported_features=1,
                  code_format="number", **SECRETS)
    text = json.dumps(e)
    assert "4821" not in text and "Bob" not in text
    assert not {"codes", "last_code_name", "code", "pin", "changed_by"} & set(e)


# ── the file must load ──────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def schemas():
    return export.load_platform_schemas()


def test_every_reproducible_domain_has_a_schema_to_check_against(schemas):
    """Adding a domain to clone.py without a schema here would let its entries be
    written unchecked."""
    assert set(schemas) == set(REPRODUCIBLE_DOMAINS)


@pytest.mark.parametrize("domain", sorted(REPRODUCIBLE_DOMAINS))
def test_every_platform_accepts_the_shape_the_export_writes(domain, schemas):
    entry = {"platform": domain, "name": "X", "entity_id": f"{domain}.x",
             "initial_value": "on", "entity_category": "diagnostic", "persistent": True}
    if domain == "number":
        entry.update(min=0, max=10, initial_value="1")
    assert export._problem(entry, schemas) is None


def test_an_entry_the_platform_would_refuse_is_reported_not_written(schemas):
    assert export._problem({"platform": "switch", "name": "X", "bogus_key": 1}, schemas)


# ── collecting from the registries ──────────────────────────────────────────

class Registries:
    def __init__(self, rows, states, devices=(), areas=None):
        self.entities = {r.entity_id: r for r in rows}
        self._states = {s.entity_id: s for s in states}
        self._devices = {d.id: d for d in devices}
        self._areas = areas or {}

    # entity registry
    def async_get(self, key):
        return self.entities.get(key) or self._devices.get(key)

    # area registry
    def async_get_area(self, area_id):
        name = self._areas.get(area_id)
        return ns(name=name) if name else None


def device(ident, name, **kw):
    base = dict(id=ident, name=name, name_by_user=None, manufacturer=None, model=None,
                sw_version=None, area_id=None)
    base.update(kw)
    return ns(**base)


def collect(monkeypatch, schemas, rows, states, devices=(), areas=None, **options):
    regs = Registries(rows, states, devices, areas)
    monkeypatch.setattr(export.er, "async_get", lambda hass: type(
        "E", (), {"entities": regs.entities,
                  "async_get": lambda s, eid: regs.entities.get(eid)})())
    monkeypatch.setattr(export.dr, "async_get", lambda hass: type(
        "D", (), {"async_get": lambda s, did: regs._devices.get(did)})())
    monkeypatch.setattr(export.ar, "async_get", lambda hass: regs)
    hass = ns(config=Config(), states=ns(
        get=lambda eid: regs._states.get(eid), async_all=lambda: list(regs._states.values())))
    data = export.EXPORT_SCHEMA(options)
    return export._collect(hass, data, schemas)


def ids(devices):
    return sorted(e["entity_id"] for d in devices.values() for e in d["entities"])


def reasons(skipped):
    return {item.get("entity_id") or item.get("device"): item["reason"] for item in skipped}


def test_a_device_is_keyed_by_its_live_id_and_carries_what_it_says_about_itself(
        monkeypatch, schemas):
    dev = device("devid1", "Hall Plug", manufacturer="Acme", model="P1",
                 sw_version="2.0", area_id="a1")
    devices, _ = collect(
        monkeypatch, schemas, [row("switch.plug", device_id="devid1")],
        [state("switch.plug", "on")], [dev], {"a1": "Hall"})
    body = devices["devid1"]
    assert (body["name"], body["manufacturer"], body["model"],
            body["sw_version"], body["area"]) == ("Hall Plug", "Acme", "P1", "2.0", "Hall")


def test_two_devices_with_the_same_name_stay_two_devices(monkeypatch, schemas):
    devs = [device("d1", "Access Point"), device("d2", "Access Point")]
    devices, _ = collect(
        monkeypatch, schemas,
        [row("switch.a", device_id="d1"), row("switch.b", device_id="d2")],
        [state("switch.a", "on"), state("switch.b", "off")], devs)
    assert sorted(devices) == ["d1", "d2"]
    assert {d["name"] for d in devices.values()} == {"Access Point"}


def test_an_entity_with_no_device_is_keyed_by_its_entity_id(monkeypatch, schemas):
    devices, _ = collect(monkeypatch, schemas, [row("switch.lonely")],
                         [state("switch.lonely", "on", friendly_name="Lonely")])
    assert list(devices) == ["switch.lonely"] and devices["switch.lonely"]["name"] == "Lonely"


def test_the_default_exclusions_leave_out_what_a_test_ha_already_has(monkeypatch, schemas):
    rows = [row("sensor.sun_next_dawn", platform="sun"), row("sensor.kitchen_temp")]
    states = [state("sensor.sun_next_dawn", "x"), state("sensor.kitchen_temp", "20")]
    devices, skipped = collect(monkeypatch, schemas, rows, states)
    assert ids(devices) == ["sensor.kitchen_temp"]
    assert "sun excluded" in reasons(skipped)["sensor.sun_next_dawn"]


def test_entity_patterns_leave_matching_entities_out(monkeypatch, schemas):
    rows = [row("sensor.a_power"), row("sensor.b_power"), row("sensor.keep")]
    states = [state(r.entity_id, "1") for r in rows]
    devices, _ = collect(monkeypatch, schemas, rows, states, exclude_entities=["sensor.*_power"])
    assert ids(devices) == ["sensor.keep"]


def test_a_whole_device_out_is_one_report_line_not_one_per_entity(monkeypatch, schemas):
    dev = device("d1", "aa:bb:cc:dd:ee:ff")
    rows = [row(f"sensor.client_{i}", device_id="d1") for i in range(5)] + [row("sensor.keep")]
    states = [state(r.entity_id, "1") for r in rows]
    devices, skipped = collect(monkeypatch, schemas, rows, states, [dev],
                               exclude_devices=["??:??:??:??:??:??"])
    assert ids(devices) == ["sensor.keep"]
    assert [i for i in skipped if "device" in i] == [
        {"device": "aa:bb:cc:dd:ee:ff", "reason": "matched exclude_devices (5 entities)"}]


def test_disabled_entities_are_left_out_and_hidden_ones_only_when_asked(monkeypatch, schemas):
    rows = [row("sensor.off", disabled=True), row("sensor.hid", hidden=True), row("sensor.ok")]
    states = [state(r.entity_id, "1") for r in rows]
    devices, skipped = collect(monkeypatch, schemas, rows, states)
    assert ids(devices) == ["sensor.hid", "sensor.ok"] and reasons(skipped)["sensor.off"] == "disabled"
    devices, _ = collect(monkeypatch, schemas, rows, states, skip_hidden=True)
    assert ids(devices) == ["sensor.ok"]


def test_domains_that_cannot_be_reproduced_are_counted_per_domain(monkeypatch, schemas):
    rows = [row(f"weather.w{i}") for i in range(3)] + [row("calendar.c")]
    states = [state(r.entity_id, "x") for r in rows]
    _, skipped = collect(monkeypatch, schemas, rows, states)
    report = export._report(skipped)
    assert {"domain": "weather", "count": 3, "reason": export.NOT_REPRODUCIBLE} in report
    assert {"domain": "calendar", "count": 1, "reason": export.NOT_REPRODUCIBLE} in report
    assert not any(i.get("entity_id", "").startswith("weather") for i in report)


def test_an_entity_with_no_registry_row_is_still_exported(monkeypatch, schemas):
    """YAML-defined entities have no unique id and so no registry row."""
    devices, _ = collect(monkeypatch, schemas, [], [state("sensor.yaml_only", "5")])
    assert ids(devices) == ["sensor.yaml_only"]


def test_a_single_entity_that_fails_validation_is_reported_and_the_rest_still_go(
        monkeypatch, schemas):
    # A negative feature mask is something no platform accepts.
    devices, skipped = collect(
        monkeypatch, schemas, [row("light.bad"), row("switch.ok")],
        [state("light.bad", "on", supported_features=-5), state("switch.ok", "on")])
    assert ids(devices) == ["switch.ok"]
    assert "failed validation" in reasons(skipped)["light.bad"]


# ── the whole action: write a file, then load it back ───────────────────────

class WritingHass(FakeHass):
    """FakeHass plus what the action itself calls."""

    def __init__(self, config_dir):
        super().__init__(config_dir)
        self.config.is_allowed_path = lambda path: False

    async def async_add_executor_job(self, func, *args):
        return func(*args)


def call(**data):
    return ns(data=export.EXPORT_SCHEMA(data))


def test_the_file_loads_back_with_the_same_entity_ids(monkeypatch, tmp_path, schemas):
    dev = device("d1", "Hall Plug", manufacturer="Acme", area_id="a1")
    rows = [row("switch.plug", device_id="d1"), row("sensor.lonely"), row("light.lamp")]
    states = [state("switch.plug", "on", friendly_name="Hall Plug"),
              state("sensor.lonely", "7", friendly_name="Lonely", device_class="temperature",
                    unit_of_measurement="°C"),
              state("light.lamp", "on", brightness=200, friendly_name="Lamp",
                    supported_color_modes=["hs"])]
    regs = Registries(rows, states, [dev], {"a1": "Hall"})
    monkeypatch.setattr(export.er, "async_get", lambda hass: type(
        "E", (), {"entities": regs.entities, "async_get": lambda s, e: regs.entities.get(e)})())
    monkeypatch.setattr(export.dr, "async_get", lambda hass: type(
        "D", (), {"async_get": lambda s, d: regs._devices.get(d)})())
    monkeypatch.setattr(export.ar, "async_get", lambda hass: regs)
    hass = WritingHass(tmp_path)
    hass.states = ns(get=lambda e: regs._states.get(e), async_all=lambda: list(regs._states.values()))
    hass.config.units = Units()

    result = run(export._async_export_devices(hass, call()))
    out = pathlib.Path(result["file"])
    assert out == tmp_path / "virtual_export.yaml" and result["entities"] == 3

    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Exported by Virtual Test Devices")
    assert yaml.safe_load(text)["devices"]["d1"]["area"] == "Hall"

    loader = BlendedCfg(FakeHass(config_dir=tmp_path), FakeEntry(out).data)
    run(loader.async_load())
    loaded = sorted(e["entity_id"] for group in loader.entities.values() for e in group)
    assert loaded == ["light.lamp", "sensor.lonely", "switch.plug"]


def test_a_path_outside_the_config_folder_is_refused(tmp_path, schemas):
    from homeassistant.exceptions import ServiceValidationError
    config = tmp_path / "config"
    config.mkdir()
    hass = WritingHass(config)
    with pytest.raises(ServiceValidationError):
        run(export._async_export_devices(hass, call(file=str(tmp_path / "elsewhere.yaml"))))
    assert not (tmp_path / "elsewhere.yaml").exists()


AWKWARD = ["yes", "no", "null", "NO", "off", "on", "0123", "1e3", "- dash", "#hash",
           "colon: here", "quote's \"both\"", "日本語 🚪", "  padded  ", "~", "true"]


def test_awkward_names_and_states_survive_the_file_unchanged(monkeypatch, tmp_path, schemas):
    """YAML turns `off` into a boolean and `null` into nothing. The names and the
    starting states that go through the file must come back exactly as they went."""
    dev = device("devid", "yes")
    rows = [row(f"sensor.t{i}", device_id="devid") for i in range(len(AWKWARD))]
    states = [state(f"sensor.t{i}", value, friendly_name=value) for i, value in enumerate(AWKWARD)]
    regs = Registries(rows, states, [dev])
    monkeypatch.setattr(export.er, "async_get", lambda hass: type(
        "E", (), {"entities": regs.entities, "async_get": lambda s, e: regs.entities.get(e)})())
    monkeypatch.setattr(export.dr, "async_get", lambda hass: type(
        "D", (), {"async_get": lambda s, d: regs._devices.get(d)})())
    monkeypatch.setattr(export.ar, "async_get", lambda hass: regs)
    hass = WritingHass(tmp_path)
    hass.states = ns(get=lambda e: regs._states.get(e), async_all=lambda: list(regs._states.values()))
    hass.config.units = Units()

    result = run(export._async_export_devices(hass, call()))
    loader = BlendedCfg(FakeHass(config_dir=tmp_path), FakeEntry(result["file"]).data)
    run(loader.async_load())
    loaded = {e["entity_id"]: e for group in loader.entities.values() for e in group}
    for i, value in enumerate(AWKWARD):
        got = loaded[f"sensor.t{i}"]
        assert got["name"] == value, (value, got["name"])
        assert got["initial_value"] == value, (value, got["initial_value"])
    assert loader.devices[0]["name"] == "yes"

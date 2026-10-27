"""Cloning a device so a piston's push or text has somewhere to land.

REGRESSION GUARD. A real notifier carries no label saying whether it stands for a
push or a text, so a clone used to come back "generic" and a piston that sends a
push or a text found nothing to send to. A phone is worse: it registers its push
as a notify SERVICE, never an entity, so a cloned phone had no notifier at all.

Both directions are tested on purpose. A suite that only proves "the notifier
was added" passes just as happily if EVERY clone grows a notifier.
"""

import pytest

from custom_components.virtual import clone


class Device:
    def __init__(self, name, entries=()):
        self.name = name
        self.name_by_user = None
        self.config_entries = list(entries)


class Entry:
    def __init__(self, entity_id, original_name=None):
        self.entity_id = entity_id
        self.original_name = original_name
        self.name = None
        self.device_class = None
        self.original_device_class = None


class FakeConfigEntries:
    def __init__(self, domains):
        self._domains = domains

    def async_get_entry(self, entry_id):
        domain = self._domains.get(entry_id)
        return type("CE", (), {"domain": domain})() if domain else None


class FakeStates:
    def get(self, _entity_id):
        return None


class FakeUnits:
    temperature_unit = "°C"


class FakeConfig:
    units = FakeUnits()


class FakeHass:
    config = FakeConfig()
    states = FakeStates()

    def __init__(self, domains):
        self.config_entries = FakeConfigEntries(domains)


def build(monkeypatch, device, entities, domains, notify_as=None):
    monkeypatch.setattr(clone.er, "async_get", lambda hass: object())
    monkeypatch.setattr(clone.dr, "async_get",
                        lambda hass: type("R", (), {"async_get": lambda s, i: device})())
    monkeypatch.setattr(clone.er, "async_entries_for_device",
                        lambda reg, device_id, include_disabled_entities=False: entities)
    return clone.build_clone_spec(FakeHass(domains), "dev", notify_as)[1]


def notifiers(specs):
    return [s for s in specs if s["platform"] == "notify"]


SWITCH = Entry("switch.plug", "Power")


def test_phone_clone_gets_a_push_notifier_without_being_asked(monkeypatch):
    phone = Device("Pixel", ["ce1"])
    specs = build(monkeypatch, phone, [Entry("sensor.batt", "Battery")], {"ce1": "mobile_app"})
    found = notifiers(specs)
    assert len(found) == 1 and found[0]["class"] == "app"


def test_phone_can_be_made_to_receive_text_instead(monkeypatch):
    phone = Device("Pixel", ["ce1"])
    specs = build(monkeypatch, phone, [Entry("sensor.batt", "Battery")],
                  {"ce1": "mobile_app"}, notify_as="sms")
    assert [s["class"] for s in notifiers(specs)] == ["sms"]


def test_ordinary_device_gets_no_notifier_unless_asked(monkeypatch):
    """The control. Without it, 'a notifier was added' proves nothing."""
    plug = Device("Plug", ["ce2"])
    specs = build(monkeypatch, plug, [SWITCH], {"ce2": "hue"})
    assert notifiers(specs) == []


@pytest.mark.parametrize("kind", ["app", "sms"])
def test_ordinary_device_can_be_asked_to_receive_either_kind(monkeypatch, kind):
    plug = Device("Plug", ["ce2"])
    specs = build(monkeypatch, plug, [SWITCH], {"ce2": "hue"}, notify_as=kind)
    assert [s["class"] for s in notifiers(specs)] == [kind]
    assert any(s["platform"] == "switch" for s in specs)  # nothing else was lost


def test_an_existing_notifier_is_relabelled_not_duplicated(monkeypatch):
    dev = Device("Relay", ["ce3"])
    specs = build(monkeypatch, dev, [Entry("notify.sms_relay", "Relay")],
                  {"ce3": "twilio"}, notify_as="sms")
    found = notifiers(specs)
    assert len(found) == 1 and found[0]["class"] == "sms"


def test_a_phone_that_already_has_a_notifier_does_not_get_a_second(monkeypatch):
    phone = Device("Pixel", ["ce1"])
    specs = build(monkeypatch, phone, [Entry("notify.pixel", "Pixel")], {"ce1": "mobile_app"})
    assert len(notifiers(specs)) == 1


def test_unknown_kind_is_refused_by_the_service_schema():
    with pytest.raises(Exception):
        clone.CLONE_DEVICE_SCHEMA({"device_id": "x", "notify_as": "carrier_pigeon"})

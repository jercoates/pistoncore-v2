"""Cloning a device so a piston's push or text has somewhere to land.

REGRESSION GUARD. A real notifier carries no label saying whether it stands for a
push or a text, so a clone used to come back "generic" and a piston that sends a
push or a text found nothing to send to. A phone is worse: it registers its push
as a notify SERVICE, never an entity, so a cloned phone had no notifier at all.

A notifier is only ADDED to a device that has none when a UI asks for it
(add_notifier), or for a companion-app phone. Both directions are tested on
purpose. A suite that only proves "the notifier
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


class NoRow:
    def async_get(self, _entity_id):
        return None


def build(monkeypatch, device, entities, domains, notify_as=None, add=False):
    monkeypatch.setattr(clone.er, "async_get", lambda hass: NoRow())
    monkeypatch.setattr(clone.dr, "async_get",
                        lambda hass: type("R", (), {"async_get": lambda s, i: device})())
    monkeypatch.setattr(clone.er, "async_entries_for_device",
                        lambda reg, device_id, include_disabled_entities=False: entities)
    return clone.build_clone_spec(FakeHass(domains), "dev", notify_as, add)[1]


def notifiers(specs):
    return [s for s in specs if s["platform"] == "notify"]


SWITCH = Entry("switch.plug", "Power")
BATTERY = Entry("sensor.batt", "Battery")


def test_phone_clone_gets_a_push_notifier_without_being_asked(monkeypatch):
    phone = Device("Pixel", ["ce1"])
    specs = build(monkeypatch, phone, [BATTERY], {"ce1": "mobile_app"})
    found = notifiers(specs)
    assert len(found) == 1 and found[0]["class"] == "app"


def test_phone_can_be_made_to_receive_text_instead(monkeypatch):
    phone = Device("Pixel", ["ce1"])
    specs = build(monkeypatch, phone, [BATTERY], {"ce1": "mobile_app"}, notify_as="sms")
    assert [s["class"] for s in notifiers(specs)] == ["sms"]


def test_ordinary_device_gets_no_notifier_unless_asked(monkeypatch):
    """The control. Without it, 'a notifier was added' proves nothing."""
    plug = Device("Plug", ["ce2"])
    specs = build(monkeypatch, plug, [SWITCH], {"ce2": "hue"})
    assert notifiers(specs) == []


@pytest.mark.parametrize("kind", ["app", "sms"])
def test_a_ui_can_add_either_kind_to_a_device_with_none(monkeypatch, kind):
    plug = Device("Plug", ["ce2"])
    specs = build(monkeypatch, plug, [SWITCH], {"ce2": "hue"}, notify_as=kind, add=True)
    assert [s["class"] for s in notifiers(specs)] == [kind]
    assert any(s["platform"] == "switch" for s in specs)  # nothing else was lost


def test_choosing_a_kind_alone_does_not_add_one(monkeypatch):
    """What keeps the standalone Actions screen honest: notify_as labels
    notifiers a device HAS, and only add_notifier makes one appear."""
    plug = Device("Plug", ["ce2"])
    specs = build(monkeypatch, plug, [SWITCH], {"ce2": "hue"}, notify_as="app")
    assert notifiers(specs) == []


def test_add_without_a_kind_adds_nothing(monkeypatch):
    plug = Device("Plug", ["ce2"])
    specs = build(monkeypatch, plug, [SWITCH], {"ce2": "hue"}, add=True)
    assert notifiers(specs) == []


def test_an_existing_notifier_is_relabelled_not_duplicated(monkeypatch):
    dev = Device("Relay", ["ce3"])
    specs = build(monkeypatch, dev, [Entry("notify.sms_relay", "Relay")],
                  {"ce3": "twilio"}, notify_as="sms")
    found = notifiers(specs)
    assert len(found) == 1 and found[0]["class"] == "sms"


def test_adding_does_not_duplicate_an_existing_notifier(monkeypatch):
    dev = Device("Relay", ["ce3"])
    specs = build(monkeypatch, dev, [Entry("notify.sms_relay", "Relay")],
                  {"ce3": "twilio"}, notify_as="sms", add=True)
    assert len(notifiers(specs)) == 1


def test_a_phone_that_already_has_a_notifier_does_not_get_a_second(monkeypatch):
    phone = Device("Pixel", ["ce1"])
    specs = build(monkeypatch, phone, [Entry("notify.pixel", "Pixel")], {"ce1": "mobile_app"})
    assert len(notifiers(specs)) == 1


def test_the_added_notifier_never_takes_an_existing_entitys_name(monkeypatch):
    """A source entity already called 'Notification' used to collide with the
    added one, giving two entities with one name and one identity."""
    plug = Device("Plug", ["ce2"])
    specs = build(monkeypatch, plug, [Entry("sensor.n", "Notification")],
                  {"ce2": "hue"}, notify_as="app", add=True)
    names = [s["name"] for s in specs]
    assert len(names) == 2 and len(set(names)) == 2


def test_unknown_device_is_a_polite_refusal_not_a_server_error(monkeypatch):
    from homeassistant.exceptions import ServiceValidationError
    with pytest.raises(ServiceValidationError):
        build(monkeypatch, None, [], {})


def test_nothing_to_copy_is_a_polite_refusal(monkeypatch):
    from homeassistant.exceptions import ServiceValidationError
    with pytest.raises(ServiceValidationError):
        build(monkeypatch, Device("Empty", []), [], {})


@pytest.mark.parametrize("bad", ["APP", "", 5, ["app"], None, "carrier_pigeon"])
def test_unknown_kind_is_refused_by_the_service_schema(bad):
    with pytest.raises(Exception):
        clone.CLONE_DEVICE_SCHEMA({"device_id": "x", "notify_as": bad})


def test_the_schemas_agree_so_a_preview_matches_its_clone():
    ok = {"device_id": "x", "notify_as": "app", "add_notifier": True}
    clone.CLONE_DEVICE_SCHEMA(ok)
    clone.DESCRIBE_DEVICE_SCHEMA(ok)


def test_add_notifier_is_not_advertised_on_the_actions_screen():
    """It is for UIs. Listing it in services.yaml would offer it to everyone."""
    import pathlib
    text = (pathlib.Path(clone.__file__).parent / "services.yaml").read_text(encoding="utf-8")
    assert "add_notifier" not in text

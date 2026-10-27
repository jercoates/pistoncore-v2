"""The select and text platforms.

REGRESSION GUARD. Real devices expose a lot of settings as selects (a log level, a
cycle) and a few as text, and before these platforms existed a clone or an export
dropped every one as "not reproducible". The points that are easy to get wrong:

* Home Assistant's TextEntity RAISES when its value breaks its own limits, so a
  starting value that does not fit has to become "no value", not an entity that
  errors whenever its state is read.
* A value off a select's menu must fall back to the first option, not leave the
  entity in a state a real select never reports.
* A password text keeps NO value. It is a secret, like a lock code.
"""

import pytest
import voluptuous as vol

from custom_components.virtual import clone
from custom_components.virtual.select import SELECT_SCHEMA, VirtualSelect
from custom_components.virtual.text import TEXT_SCHEMA, VirtualText
from conftest import run


class Units:
    temperature_unit = "°C"


class Config:
    units = Units()


class Hass:
    config = Config()


def select(options, initial="", **extra):
    return VirtualSelect(SELECT_SCHEMA(
        {"name": "Mode", "options": options, "initial_value": initial, **extra}), False)


def text(initial="", **extra):
    return VirtualText(TEXT_SCHEMA({"name": "Label", "initial_value": initial, **extra}), False)


def started(entity):
    entity._create_state(entity._config)
    return entity


# ── select ──────────────────────────────────────────────────────────────────

def test_a_select_starts_on_its_initial_option():
    assert started(select(["a", "b", "c"], "b")).current_option == "b"


def test_a_select_starts_on_the_first_option_when_none_is_given():
    assert started(select(["a", "b"])).current_option == "a"


def test_a_value_off_the_menu_falls_back_to_the_first_option():
    assert started(select(["a", "b"], "zzz")).current_option == "a"


def test_a_select_with_no_options_has_no_current_option():
    assert started(select([])).current_option is None


def test_choosing_an_option_changes_it():
    entity = started(select(["a", "b"]))
    run(entity.async_select_option("b"))
    assert entity.current_option == "b"


def test_a_restored_value_off_the_menu_also_falls_back():
    entity = select(["a", "b"])
    entity._restore_state(type("S", (), {"state": "gone", "attributes": {}})(), entity._config)
    assert entity.current_option == "a"


def test_a_clone_carries_the_menu():
    assert clone.capability_config(Hass, "select", {"options": ["x", "y"]}) == {"options": ["x", "y"]}


def test_the_schema_accepts_what_a_clone_produces():
    SELECT_SCHEMA({"name": "M", "options": ["x", "y"], "entity_id": "select.m",
                   "entity_category": "config"})


# ── text ────────────────────────────────────────────────────────────────────

def test_a_text_starts_with_its_initial_value():
    assert started(text("Hello")).native_value == "Hello"


def test_an_empty_initial_value_is_no_value():
    assert started(text("")).native_value is None


def test_a_value_longer_than_the_limit_becomes_no_value_not_an_error():
    entity = started(text("far too long", max=5))
    assert entity.native_value is None
    entity.state  # must not raise: this is what a bad value used to do


def test_a_value_shorter_than_the_minimum_becomes_no_value():
    assert started(text("ab", min=5)).native_value is None


def test_a_value_that_breaks_the_pattern_becomes_no_value():
    assert started(text("abc", pattern=r"\d+")).native_value is None
    assert started(text("123", pattern=r"\d+")).native_value == "123"


def test_a_password_text_never_keeps_a_value():
    assert started(text("hunter2", mode="password")).native_value is None


def test_a_restored_password_is_not_kept_either():
    entity = text(mode="password")
    entity._restore_state(type("S", (), {"state": "hunter2", "attributes": {}})(), entity._config)
    assert entity.native_value is None


def test_setting_a_value_changes_it():
    entity = started(text())
    run(entity.async_set_value("new"))
    assert entity.native_value == "new"


def test_the_limits_are_reported():
    entity = text(min=2, max=9, pattern="[a-z]+")
    assert (entity.native_min, entity.native_max, entity.pattern) == (2, 9, "[a-z]+")


def test_a_maximum_below_the_minimum_is_raised_to_it():
    assert text(min=8, max=3).native_max == 8


def test_an_unknown_mode_is_refused_by_the_schema():
    with pytest.raises(vol.Invalid):
        TEXT_SCHEMA({"name": "L", "mode": "shouting"})


def test_a_clone_carries_the_limits():
    assert clone.capability_config(
        Hass, "text", {"min": 1, "max": 20, "pattern": "[a-z]+", "mode": "text"}) == {
        "min": 1, "max": 20, "pattern": "[a-z]+", "mode": "text"}

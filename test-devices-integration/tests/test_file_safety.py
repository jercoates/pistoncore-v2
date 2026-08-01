"""Saving and loading the group's device file.

REGRESSION GUARD. The savers used to open the real file in 'w' — which truncates
it to zero — and only THEN serialize, swallowing any failure at debug level. One
value yaml couldn't represent therefore emptied the file, destroyed every test
device, and left the integration unable to load, silently. It happened for real
on the bench.

These tests fail if a save can ever damage an existing file, or if an unreadable
file can take the integration down again.
"""

import pytest

from conftest import run

from custom_components.virtual.cfg import (
    _async_load_yaml,
    _async_save_yaml,
    _load_user_data,
    _save_user_data,
)


class Unserialisable:
    """yaml has no representer for this."""


def test_failed_save_leaves_the_existing_file_intact(tmp_path):
    """THE data-loss bug: a bad value must not destroy what's already there."""
    path = str(tmp_path / "virtual.yaml")
    good = {"version": 1, "devices": {"Keep Me": [{"platform": "switch", "name": "Keep Me"}]}}
    run(_async_save_yaml(path, good))
    before = open(path, encoding="utf-8").read()
    assert before.strip()

    with pytest.raises(Exception):
        run(_async_save_yaml(path, {"version": 1, "devices": {"Bad": Unserialisable()}}))

    after = open(path, encoding="utf-8").read()
    assert after == before, "a failed save damaged the existing file"
    assert run(_async_load_yaml(path)) == good


def test_failed_save_raises_rather_than_going_quiet(tmp_path):
    """It used to be swallowed at debug level, so nothing reported the loss."""
    path = str(tmp_path / "virtual.yaml")
    with pytest.raises(Exception):
        run(_async_save_yaml(path, {"devices": {"Bad": Unserialisable()}}))


def test_empty_file_degrades_to_no_devices(tmp_path):
    """An empty file parses to None, and `.get` on it used to kill setup."""
    path = tmp_path / "virtual.yaml"
    path.write_text("", encoding="utf-8")
    assert run(_load_user_data(str(path))) == {}


def test_unparseable_file_degrades_to_no_devices(tmp_path):
    path = tmp_path / "virtual.yaml"
    path.write_text("devices:\n  - [unclosed\n   bad: : :\n", encoding="utf-8")
    assert run(_load_user_data(str(path))) == {}


def test_non_mapping_file_degrades_to_no_devices(tmp_path):
    path = tmp_path / "virtual.yaml"
    path.write_text("just a bare string\n", encoding="utf-8")
    assert run(_load_user_data(str(path))) == {}


def test_missing_file_degrades_to_no_devices(tmp_path):
    assert run(_load_user_data(str(tmp_path / "does-not-exist.yaml"))) == {}


def test_round_trip_preserves_devices(tmp_path):
    path = str(tmp_path / "virtual.yaml")
    devices = {
        "Thermostat": [{"platform": "climate", "name": "Thermostat",
                        "supported_features": 155,
                        "hvac_modes": ["off", "heat", "cool"],
                        "min_temp": 4.4, "max_temp": 95.0}],
        "Speaker": [{"platform": "media_player", "name": "Speaker",
                     "source_list": ["Line-in", "Radio"]}],
    }
    run(_save_user_data(path, devices))
    assert run(_load_user_data(path)) == devices


def test_no_temp_file_is_left_behind(tmp_path):
    """The atomic write uses a .tmp alongside; it must not survive."""
    path = tmp_path / "virtual.yaml"
    run(_save_user_data(str(path), {"A": [{"platform": "switch", "name": "A"}]}))
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert not leftovers, leftovers

"""The create/remove queue.

REGRESSION GUARD. Before this was fixed, create_device and remove_device did
read-modify-write on one yaml file and then reloaded the config entry. Called
concurrently, every caller loaded the file before ANY caller saved it, so all but
the last were silently erased — measured on a clean HA: six concurrent creates
produced ONE device and reported no error at all.

If either test here fails, that data loss is back.
"""

import asyncio

from conftest import run

from custom_components.virtual.cfg import _load_user_data
from custom_components.virtual.pistoncore_manage import _mutate_and_reload


def _add(name):
    def mutate(devices):
        devices[name] = [{"platform": "switch", "name": name}]
    return mutate


def _drop(name):
    def mutate(devices):
        devices.pop(name, None)
    return mutate


def test_concurrent_creates_all_survive(hass, entry, device_file):
    """Ten at once must produce ten. This is the lost update."""
    names = [f"Device {i}" for i in range(10)]

    async def go():
        await asyncio.gather(*(
            _mutate_and_reload(hass, entry, f"created {n}", _add(n)) for n in names))
        return await _load_user_data(str(device_file))

    devices = run(go())
    missing = [n for n in names if n not in devices]
    assert not missing, f"silently lost: {missing}"
    assert len(devices) == len(names)


def test_concurrent_removes_all_applied(hass, entry, device_file):
    """Remove has the identical shape and had the identical bug."""
    names = [f"Device {i}" for i in range(10)]

    async def go():
        await asyncio.gather(*(
            _mutate_and_reload(hass, entry, "create", _add(n)) for n in names))
        await asyncio.gather(*(
            _mutate_and_reload(hass, entry, "remove", _drop(n)) for n in names[:6]))
        return await _load_user_data(str(device_file))

    devices = run(go())
    assert sorted(devices) == sorted(names[6:]), devices


def test_creates_do_not_clobber_existing_devices(hass, entry, device_file):
    """A burst must not eat devices that were already there."""
    async def go():
        await _mutate_and_reload(hass, entry, "seed", _add("Keep Me"))
        await asyncio.gather(*(
            _mutate_and_reload(hass, entry, "create", _add(f"New {i}")) for i in range(8)))
        return await _load_user_data(str(device_file))

    devices = run(go())
    assert "Keep Me" in devices, "a concurrent burst erased a pre-existing device"
    assert len(devices) == 9


def test_burst_costs_one_reload(hass, entry):
    """Reloading per call is what made the race window wide enough to hit.

    A burst should collapse to a single reload — whoever finds nobody else
    waiting does it.
    """
    async def go():
        await asyncio.gather(*(
            _mutate_and_reload(hass, entry, "create", _add(f"Device {i}"))
            for i in range(8)))

    run(go())
    assert hass.config_entries.reloads < 8, (
        f"{hass.config_entries.reloads} reloads for 8 creates — not coalescing")
    assert hass.config_entries.reloads >= 1, "never reloaded, so nothing would appear"


def test_single_change_still_reloads(hass, entry):
    """Coalescing must not swallow the ONLY reload — one change, one reload."""
    run(_mutate_and_reload(hass, entry, "create", _add("Solo")))
    assert hass.config_entries.reloads == 1

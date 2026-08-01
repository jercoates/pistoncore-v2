"""Shared fixtures.

These tests run against a REAL Home Assistant install, because the integration's
behaviour depends on HA's own enums and yaml handling — the bugs these tests
exist to prevent were all in that seam. The easy way to get one is the HA
container itself:

    docker cp test-devices-integration/tests pc-testha:/config/tests
    docker exec pc-testha python -m pytest /config/tests -q

Deliberately NO pytest-asyncio: async cases call `asyncio.run` directly, so the
only requirements are HA and pytest, both of which any HA install already has.
"""

import asyncio
import pathlib
import sys

import pytest

# The integration is imported as `custom_components.virtual.*`, so its PARENT
# must be importable.
INTEGRATION_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(INTEGRATION_ROOT) not in sys.path:
    sys.path.insert(0, str(INTEGRATION_ROOT))


def run(coro):
    """Run one coroutine to completion — replaces pytest-asyncio."""
    return asyncio.run(coro)


class FakeConfigEntries:
    """Counts reloads, so a test can prove a burst collapses into one."""

    def __init__(self):
        self.reloads = 0

    async def async_reload(self, entry_id):
        self.reloads += 1
        # Yield, so a reload genuinely interleaves with other waiting callers —
        # without this the race being tested cannot occur.
        await asyncio.sleep(0)


class FakeHass:
    def __init__(self):
        self.data = {}
        self.config_entries = FakeConfigEntries()


class FakeEntry:
    def __init__(self, file_name, group_name="Test Group", entry_id="entry-1"):
        self.entry_id = entry_id
        self.data = {"file_name": str(file_name), "group_name": group_name}


@pytest.fixture
def hass():
    return FakeHass()


@pytest.fixture
def device_file(tmp_path):
    """An empty path where the group's device yaml will be written."""
    return tmp_path / "virtual.yaml"


@pytest.fixture
def entry(device_file):
    return FakeEntry(device_file)

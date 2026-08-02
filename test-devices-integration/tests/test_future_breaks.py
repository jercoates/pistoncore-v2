"""Dated obligations that will break this integration if nobody acts.

WHY THIS FILE EXISTS. Home Assistant deprecates things with a removal date years
out. A note in a chat log, an issue, or somebody's memory does not survive that
long — and whoever is maintaining this in 2027 may not be the person who wrote
it. So each known future break is encoded as a test that **starts failing well
before the deadline**, explains itself, and **clears itself automatically once
the code is fixed**.

Nobody has to remember. Anyone who runs the tests gets told, including a person
or an AI picking this repo up cold.

To add one: copy the pattern below — a WARN_FROM date, a REMOVED_IN date, a check
that returns True once the problem is gone, and a message saying what to do.
"""

from datetime import date
import pathlib

import pytest

INTEGRATION = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "virtual"


def _obligation(name, warn_from, removed_in, still_broken, what_to_do):
    """Fail from `warn_from` onward while `still_broken` is true."""
    if not still_broken():
        return  # fixed — this obligation is discharged and never nags again
    if date.today() < warn_from:
        return  # known, dated, not yet urgent
    pytest.fail(
        f"\n\n{name}\n"
        f"Home Assistant removes this in {removed_in}. It is still present in this "
        f"integration.\n\n{what_to_do}\n"
        f"(This test starts failing at {warn_from} on purpose, to give lead time. "
        f"It will pass again by itself once the code no longer does this — nothing "
        f"to remember and nothing to delete.)\n")


def test_device_tracker_location_name_is_migrated():
    """`TrackerEntity.location_name` is deprecated; HA removes it in 2027.7.

    Not a rename. The replacement is `in_zones`, a list of zones that must
    actually EXIST in HA, whereas this integration lets you set an arbitrary
    place name ("school") with no matching zone. Migrating means deciding what a
    free-text location means in a zone-only world.

    CHECK UPSTREAM FIRST: this is inherited from twrecked/hass-virtual and was
    still unmigrated there as of 2026-08-02. If upstream has since solved it,
    take their answer rather than inventing a second one and diverging.
    """
    def still_broken():
        source = (INTEGRATION / "device_tracker.py").read_text(encoding="utf-8")
        return "def location_name" in source

    _obligation(
        name="device_tracker.py still overrides the deprecated `location_name`",
        warn_from=date(2027, 1, 1),          # ~6 months of lead time
        removed_in="Home Assistant 2027.7",
        still_broken=still_broken,
        what_to_do=(
            "  1. Check whether twrecked/hass-virtual has migrated it — if so, use theirs.\n"
            "  2. Otherwise replace the `location_name` property with `_attr_in_zones`\n"
            "     (a list of zone names), and decide what happens to a location that\n"
            "     matches no existing zone — that is the actual design question.\n"
            "  3. Delete nothing here; this test clears itself once `def location_name`\n"
            "     is gone from device_tracker.py."
        ),
    )


def test_no_deprecated_multi_config_entry_device_helpers():
    """HA 2026.8 restricted a device to ONE config entry; the compatibility
    helpers for the old behaviour go away in 2027.8.

    This integration creates its own devices under its own entry and never used
    those helpers — VERIFIED on 2026.8.0b3, where an upgraded bench kept every
    entity and simply split one deliberately-merged device in two. This test
    exists so that stays true if someone reaches for them later.
    """
    offenders = []
    for path in sorted(INTEGRATION.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for helper in ("async_get_or_create_from_config_entry",
                       "add_config_entry_id", "config_entry_ids"):
            if helper in source:
                offenders.append(f"{path.name}: {helper}")
    assert not offenders, (
        "\n\nThese use device helpers tied to the pre-2026.8 multi-config-entry "
        f"model, which HA removes in 2027.8:\n  " + "\n  ".join(offenders) +
        "\n\nA device should belong to exactly one config entry. Create devices "
        "under this integration's own entry via DeviceInfo, as entity.py does.\n")

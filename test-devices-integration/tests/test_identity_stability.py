"""An entity's identity must not move when nothing about it changed.

REGRESSION GUARD. An entity's identity (`unique_id`) is filed under its NAME
within its group. Two entities in one device that ended up with the same name —
easily done, since an entity you don't name is called after its device and its
sensor type — filed under one key. On every load the second one looked itself up,
found nothing, decided it was new, and was registered all over again.

Measured on a clean HA 2026-08-19, a device with three unnamed motion sensors:

    load 1:  motion, motion_2, motion_3        6 registry rows
    load 2:  + motion_4, motion_5              8
    load 3:  + motion_6, motion_7             10

Two dead rows per restart, for ever, until the install hits HA's 10,000-entity
ceiling — which one bench did. Entities named uniquely were byte-stable across
the same restarts, which is the other half of the story and is why the fix must
NOT be "derive identity from the name": that would change the identity of every
entity that works today and orphan the lot on upgrade. These tests hold both
halves down.
"""

import json

from conftest import FakeEntry, FakeHass, run

from custom_components.virtual.cfg import BlendedCfg, _save_user_data


def _ids_after_load(hass, entry):
    """Load the group the way setting up the config entry does, return identities."""
    cfg = BlendedCfg(hass, entry.data)
    run(cfg.async_load())
    return {
        entity["name"]: entity["unique_id"]
        for entities in cfg.entities.values()
        for entity in entities
    }


def _bench(tmp_path, devices):
    hass = FakeHass(config_dir=tmp_path)
    entry = FakeEntry(tmp_path / "virtual.yaml")
    run(_save_user_data(str(tmp_path / "virtual.yaml"), devices))
    return hass, entry


DUPLICATES = {
    # Three unnamed motion sensors: all three are called "Kitchen Motion motion".
    "Kitchen Motion": [
        {"platform": "binary_sensor", "class": "motion"},
        {"platform": "binary_sensor", "class": "motion"},
        {"platform": "binary_sensor", "class": "motion"},
    ],
}


def test_duplicate_names_keep_separate_identities(tmp_path):
    """Three colliding entities must be three entities, not one plus two ghosts."""
    hass, entry = _bench(tmp_path, DUPLICATES)

    ids = _ids_after_load(hass, entry)

    assert len(ids) == 3, f"expected three entities, got {sorted(ids)}"
    assert len(set(ids.values())) == 3, (
        "colliding entities share an identity — HA would drop all but one "
        f"({ids})"
    )


def test_reloading_does_not_move_identities(tmp_path):
    """THE bug: loading twice with nothing changed must change nothing."""
    hass, entry = _bench(tmp_path, DUPLICATES)

    first = _ids_after_load(hass, entry)
    second = _ids_after_load(hass, entry)
    third = _ids_after_load(hass, entry)

    assert first == second == third, (
        "identities moved across reloads — every restart orphans the old rows "
        f"and registers new ones\n first={first}\n second={second}\n third={third}"
    )


def test_named_entities_keep_the_identity_they_already_have(tmp_path):
    """The upgrade guard.

    A user's existing entities are already filed under their names. Whatever the
    fix for duplicates is, it must leave these untouched — if these move, every
    dashboard and automation pointing at them breaks on upgrade.
    """
    hass, entry = _bench(tmp_path, {
        "Ctrl Device": [
            {"platform": "binary_sensor", "name": "Ctrl One", "class": "motion"},
            {"platform": "binary_sensor", "name": "Ctrl Two", "class": "motion"},
            {"platform": "binary_sensor", "name": "Ctrl Three", "class": "motion"},
        ],
    })

    first = _ids_after_load(hass, entry)
    assert sorted(first) == ["Ctrl One", "Ctrl Three", "Ctrl Two"]

    # The identities on disk are the contract. Read them straight from the meta
    # file rather than trusting the object we just built.
    meta = json.load(open(hass.config.path(".storage/virtual.meta.json")))
    stored = {
        name: values["unique_id"]
        for name, values in meta["devices"][entry.data["group_name"]].items()
    }
    assert stored == first

    assert _ids_after_load(hass, entry) == first, "a reload rewrote settled identities"


def test_the_first_of_a_colliding_pair_keeps_the_bare_name(tmp_path):
    """Why the fix is safe to ship.

    Numbering repeats only ever adds a suffix to the SECOND one onwards. The
    first keeps the name it always had, so it keeps the identity it always had —
    that is what makes this an additive fix rather than a migration.
    """
    hass, entry = _bench(tmp_path, DUPLICATES)

    names = sorted(_ids_after_load(hass, entry))

    assert names == [
        "Kitchen Motion motion",
        "Kitchen Motion motion 2",
        "Kitchen Motion motion 3",
    ], names

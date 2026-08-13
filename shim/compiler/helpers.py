"""HELPER ENTITIES — the HA side of persistent piston variables.

A webCoRE variable whose reads cross the statement that wrote it cannot live in
an HA `variables:` block: PistonCore compiles each top-level statement into a
SEPARATE automation, and that block lives for one run of one automation. It
needs a real entity (VARIABLES_SPEC §4). That is what makes the manual-override
pattern work — set a flag when the light is switched on by hand, read it back on
a later trigger to skip the timer.

CREATION, verified 2026-08-03 against a live HA:
  * The REST config API does NOT create helpers — `/api/config/input_boolean/
    config/<id>` returns 404. That path exists for automations, scripts and
    scenes only. (Jeremy called this before the test: "i doubt it autocreats
    i had to do it when i made the yaml by hand.")
  * Writing a YAML file and calling `<domain>.reload` DOES work, with no
    restart. Proven end to end: file written, reload called, entity appeared.

So helpers deploy exactly the way automations already do — write a file, reload
— and need no new mechanism.

THE INCLUDE. HA only reads the file if configuration.yaml points at it. A
PACKAGES directory is used rather than four `!include` lines because a package
MERGES: an install that already defines `input_boolean:` would be broken by a
second `input_boolean:` key, and that failure lands at HA startup rather than at
our compile. One packages line covers every helper type and cannot collide the
same way.
"""

import re

from .. import deploy_writer

PACKAGE_DIR = "pistoncore_packages"
PACKAGE_FILE = f"{PACKAGE_DIR}/pistoncore_variables.yaml"
INCLUDE_MARKER = "packages: !include_dir_named pistoncore_packages"

# webCoRE type -> (helper domain, extra config the domain requires)
#
# input_number REQUIRES min and max (VARIABLES_SPEC §7.3) and webCoRE numbers
# are unbounded, so the spec's chosen bounds are used for every numeric
# variable. They sit inside the range where integers stay exactly
# representable in a 64-bit float, so nothing rounds silently.
NUMBER_MIN = -999999999999
NUMBER_MAX = 999999999999



# Deleting a file is not something Home Assistant offers as an action, but
# `shell_command` is a first-class integration and a package can declare one.
# webCoRE's clearImages() genuinely deletes; refusing to implement it because
# there is no ready-made service would be giving up on something that works
# (Jeremy, 2026-08-04: "if we can make it work we should").
#
# The command is TEMPLATED so one declaration serves every camera — the path
# arrives as service data rather than being baked in per piston.
# CONSTRAINED on purpose. Home Assistant provides no delete action at all —
# camera.snapshot and image.snapshot write files, file.read_file reads them,
# and nothing removes them (verified against a live HA service registry,
# 2026-08-04). shell_command is the only mechanism, which means the workaround
# is a raw `rm` unless we bound it.
#
# So the caller passes the CAMERA, not a path, and the folder is fixed in the
# command itself. An automation calling this cannot reach outside
# /media/pistoncore/, and cannot walk out of it: `..`, `/` and quotes would
# have to survive an entity object_id, which they cannot.
SHELL_COMMANDS = {
    "pistoncore_delete_snapshot":
        'rm -f "/media/pistoncore/{{ camera }}/{{ camera }}.jpg"',
}


def shell_command_block() -> dict:
    """The `shell_command:` section for the package file.

    NOT opt-in, and the test is Jeremy's (2026-08-04): "if it can work without
    pistoncore working it can stand with a note on what it does. if pistoncore
    has to be there to do it that is opt in." This is written into Home
    Assistant's own config once and runs on its own — deleting PistonCore does
    not stop it, the same standing rule the emitted automations follow.

    It is also not a general capability: the folder is fixed inside the command
    and the caller passes only a camera, so it cannot reach outside
    /media/pistoncore/. What it DOES gets documented in INSTALL.md rather than
    hidden behind a switch."""
    return dict(SHELL_COMMANDS)


def helper_config(domain: str, name: str) -> dict:
    """The YAML body for one helper, keyed by its object_id."""
    cfg: dict = {"name": name}
    if domain == "input_number":
        cfg.update({"min": NUMBER_MIN, "max": NUMBER_MAX,
                    "step": 0.001, "mode": "box"})
    elif domain == "input_text":
        # 255 is the cap on ANY entity state, not a property of input_text
        # (VARIABLES_SPEC §7.2) — declared here so the limit is visible.
        cfg.update({"max": 255})
    elif domain == "input_datetime":
        cfg.update({"has_date": True, "has_time": True})
    elif domain == "timer":
        # A timer standing in for a cancellable wait (route D). No duration is
        # declared: every `timer.start` passes its own, so one declaration
        # serves a statement whose wait length is a variable.
        #
        # `restore: true` survives an HA restart — but only the TIMER does. A
        # timer that expires while HA is down does NOT fire `finished` on the
        # way back up, so the continuation is silently lost. Bench-measured
        # 2026-08-08 (30s timer, ~45s outage: idle on boot, no event, the work
        # never ran). Written up as a divergence in /help/limitations rather
        # than left as a surprise.
        cfg.update({"duration": "00:00:00", "restore": True})
    return cfg


def group_sensor(piston_id: str, group_name: str, entities: list,
                 device_class: str | None = None) -> dict:
    """A binary_sensor GROUP standing in for one piston's device group.

    WHY IT EXISTS. `for:` on a state trigger is tracked PER ENTITY, so a
    trigger listing five motion sensors fires when ANY ONE of them has been
    clear for the window — device-proven 2026-08-08 to turn the lights off
    while another sensor in the same room was still detecting. A GROUP entity
    has one combined state, so `for:` on it means "the whole group has been
    clear", which is what the piston actually said. Proven both directions on
    the bench: one sensor quiet while the other kept firing left the light ON;
    both clear turned it OFF.

    NAMED PER PISTON PER VARIABLE, never by device class (Jeremy, 2026-08-08:
    *"we have to make uniq ones not a broad motion because i have many not just
    1"*). Jeremy's Cave sensors and Hall sensors must not share a group, and
    neither may collide with a group he made himself.

    device_class is carried so the group reports as the same kind of thing its
    members are; a group of motion sensors that reports as a generic binary
    sensor reads wrong in the UI and in any condition keyed on class."""
    slug = re.sub(r"[^a-z0-9_]+", "_", str(group_name).lower()).strip("_")
    object_id = f"pistoncore_{piston_id}_{slug}"
    return {"object_id": object_id,
            "entity": f"binary_sensor.{object_id}",
            # THE ENTITY_ID COMES FROM THE NAME, not from unique_id — measured
            # on the bench 2026-08-08: `name: "PistonCore Cave_motion"` became
            # `binary_sensor.pistoncore_cave_motion`, dropping the piston
            # entirely. Two pistons each with a `Motion_sensor` variable would
            # then both claim the same entity_id and HA would silently suffix
            # the second `_2` — the same alias collision that fills the
            # registry with corpses, and the automation would reference the
            # wrong group. The piston id has to be IN THE NAME.
            "name": f"PistonCore {piston_id} {group_name}",
            "device_class": device_class,
            "entities": sorted(set(entities))}


def render_package(helpers: list, group_sensors: list | None = None) -> str:
    """helpers: [{entity, name}] -> the package YAML.

    `group_sensors` are device-group binary sensors (see group_sensor above) —
    the same package, because they are the same kind of thing: config the
    piston needs in order to mean what it says.

    The SHAPE lives in helpers_package.yaml.j2, not here — it is HA config
    schema and therefore user-editable (COMPILER_SPEC "Jinja2 everywhere").
    Python only decides which helpers exist and what each domain requires."""
    from .emit_yaml import _env

    rows = []
    groups = list(group_sensors or [])
    for h in helpers:
        if h.get("kind") == "group":
            groups.append({"object_id": h["entity"].split(".", 1)[1],
                           "entity": h["entity"], "name": h["name"],
                           "device_class": h.get("device_class"),
                           "entities": h.get("members") or []})
            continue
        domain, _, object_id = h["entity"].partition(".")
        cfg = helper_config(domain, h.get("name") or object_id)
        rows.append({"domain": domain, "object_id": object_id,
                     "name": cfg.pop("name"), "config": cfg})
    rows.sort(key=lambda r: (r["domain"], r["object_id"]))
    return _env.get_template("helpers_package.yaml.j2").render(
        helpers=rows, group_sensors=groups,
        shell_commands=shell_command_block())


def include_present(config_text: str) -> bool:
    """Is the packages directory already wired into configuration.yaml?

    Matches the directive rather than our exact line, so a user who wrote their
    own packages include by hand is not given a duplicate."""
    return bool(re.search(r"packages:\s*!include_dir_named\s+\S+", config_text))


def ensure_include(writer=None) -> dict:
    """Add the packages include to configuration.yaml if it is not there.

    Returns {"changed": bool, "reason": str}. Never raises for the ordinary
    "already fine" case — this runs at startup as well as from Settings.

    Careful about `homeassistant:`: `packages` is a KEY UNDER it, so if that
    block already exists the line goes inside it rather than starting a second
    one, which would be a duplicate-key failure at HA startup.
    """
    writer = writer or deploy_writer.get_writer()
    try:
        text = writer.read("configuration.yaml")
    except Exception as exc:                                    # noqa: BLE001
        return {"changed": False, "reason": f"could not read configuration.yaml: {exc}"}

    if include_present(text):
        return {"changed": False, "reason": "already present"}

    lines = text.splitlines()
    out, inserted = [], False
    for i, line in enumerate(lines):
        out.append(line)
        if not inserted and re.match(r"^homeassistant:\s*$", line):
            out.append(f"  {INCLUDE_MARKER}")
            inserted = True
    if not inserted:
        out.append("")
        out.append("# Added by PistonCore — lets it create the helper entities that hold")
        out.append("# piston variables. A packages directory MERGES with your existing")
        out.append("# config, so it cannot collide with helpers you already define.")
        out.append("homeassistant:")
        out.append(f"  {INCLUDE_MARKER}")

    writer.write("configuration.yaml", "\n".join(out) + "\n")
    return {"changed": True, "reason": "packages include added"}


def write_helpers(helpers: list, writer=None) -> dict:
    """Write the package file. Returns the domains that need reloading.

    A DEVICE GROUP IS NOT A HELPER DOMAIN. `input_boolean`, `timer` and friends
    each have a `reload` service; a `binary_sensor: platform: group` does NOT —
    binary_sensor has no reload service at all, so deriving the call from the
    entity's domain made deploy fail with "Service binary_sensor.reload not
    found" and the group was never picked up. YAML platforms come back with
    `homeassistant.reload_all`. Measured on the bench 2026-08-09."""
    writer = writer or deploy_writer.get_writer()
    writer.write(PACKAGE_FILE, render_package(helpers))
    domains = set()
    for h in helpers:
        if h.get("kind") == "group":
            domains.add("homeassistant")
        else:
            domains.add(h["entity"].split(".", 1)[0])
    return {"domains": sorted(domains)}


def reload_services(domains) -> list:
    """The reload calls that make HA pick the file up without a restart.

    `homeassistant` has no plain `reload` — its call is `reload_all`, which is
    what a YAML platform (a device group) needs."""
    return [(d, "reload_all" if d == "homeassistant" else "reload")
            for d in sorted(set(domains))]

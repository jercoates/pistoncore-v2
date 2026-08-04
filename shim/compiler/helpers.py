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
    return cfg


def render_package(helpers: list) -> str:
    """helpers: [{entity, name}] -> the package YAML.

    The SHAPE lives in helpers_package.yaml.j2, not here — it is HA config
    schema and therefore user-editable (COMPILER_SPEC "Jinja2 everywhere").
    Python only decides which helpers exist and what each domain requires."""
    from .emit_yaml import _env

    rows = []
    for h in helpers:
        domain, _, object_id = h["entity"].partition(".")
        cfg = helper_config(domain, h.get("name") or object_id)
        rows.append({"domain": domain, "object_id": object_id,
                     "name": cfg.pop("name"), "config": cfg})
    rows.sort(key=lambda r: (r["domain"], r["object_id"]))
    return _env.get_template("helpers_package.yaml.j2").render(helpers=rows)


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
    """Write the package file. Returns the domains that need reloading."""
    writer = writer or deploy_writer.get_writer()
    writer.write(PACKAGE_FILE, render_package(helpers))
    return {"domains": sorted({h["entity"].split(".", 1)[0] for h in helpers})}


def reload_services(domains) -> list:
    """The reload calls that make HA pick the file up without a restart."""
    return [(d, "reload") for d in sorted(set(domains))]

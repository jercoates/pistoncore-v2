"""RESOLVE — device refs / values / commands -> real HA entities & services
(COMPILER_SPEC §3.1). The hash<->entity resolution map is INJECTED: production
passes the device pipeline's map (DEVICE_PAYLOAD_SPEC §8), tests pass a
fixture map — that's how golden-fixture placeholder entity_ids stay honest.

d-array entries resolve as: hashed id | local device-variable name | @global
name (PISTON_JSON_REFERENCE §4 — never assume already-a-hash)."""

import json
from pathlib import Path

from .errors import UnresolvableDevice

_BAND = Path(__file__).resolve().parent.parent.parent / "templates" / "compiler" / "yaml" / "classic"


def _load_band_json(name: str) -> dict:
    with open(_BAND / name, encoding="utf-8") as f:
        return json.load(f)


class Resolver:
    def __init__(self, piston: dict, resolution_map: dict, globals_map: dict | None = None):
        self.resolution_map = resolution_map
        self.globals_map = globals_map if globals_map is not None else {}
        self.local_device_vars = {
            v["n"]: ((v.get("v") or {}).get("d") or [])
            for v in piston.get("v", []) if v.get("t") == "device"
        }
        maps = _load_band_json("value_maps.json")
        self.value_maps = maps["attribute_values"]
        self.binary_opposites = maps["binary_opposites"]
        self.system_values = maps.get("system_values", {})
        self.alarm_commands = maps.get("alarm_commands", {})
        self.command_maps = _load_band_json("command_maps.json")
        self.local_var_names = {v.get("n") for v in piston.get("v", [])}
        self.unresolved: list[dict] = []   # devices kept but not currently in HA
        sys_ent = resolution_map.get("$system")
        self.system_entities = sys_ent if isinstance(sys_ent, dict) else {}

    def system_entity(self, var: str) -> str | None:
        """HA entity backing a webCoRE system variable ($mode,
        $alarmSystemStatus, ...) — from the resolution map's $system entry."""
        v = self.system_entities.get(var)
        return v if isinstance(v, str) else None

    def system_value(self, var: str, value):
        return self.system_values.get(var, {}).get(value, value)

    def _hashes(self, dref: str, ctx: dict) -> list[str]:
        if dref.startswith(":") and dref.endswith(":"):
            return [dref]
        if dref.startswith("@"):
            g = self.globals_map.get(dref)
            if not g:
                # exact-name miss: help the user spot case mismatches
                # (@Speakers_All vs @speakers_all are different globals)
                close = [n for n in self.globals_map if n.lower() == dref.lower()]
                hint = f" (did you mean '{close[0]}'? names are case-sensitive)" if close else \
                       " — create it in the Global variables panel"
                raise UnresolvableDevice(
                    f"global device variable '{dref}' not found{hint}", **ctx)
            v = g.get("v")
            hashes = v if isinstance(v, list) else ((v or {}).get("d") or g.get("d") or [])
            if not hashes:
                raise UnresolvableDevice(
                    f"global device variable '{dref}' has no devices assigned — "
                    f"click it in the Global variables panel and add devices", **ctx)
            return hashes
        if dref in self.local_device_vars:
            return self.local_device_vars[dref]
        raise UnresolvableDevice(f"device reference '{dref}' is neither a hash, a local "
                                 f"device variable, nor a global", **ctx)

    def remembered_entity(self, h: str, attr_or_cmd: str) -> str | None:
        """Last entity this device hash resolved to, from PistonCore's own
        memory. Lets a device that has temporarily left Home Assistant keep
        its place in the compiled automation (Jeremy's ruling 2026-07-19)."""
        from .. import storage
        return storage.remembered_binding(h, attr_or_cmd)

    def _device_label(self, h: str) -> str:
        """A user-facing name for a device reference. NEVER the raw hash —
        error messages land on the front-door pill and the piston banner, and
        the standing rule is that device ids appear nowhere in PistonCore
        (Jeremy, hard rule). An unknown hash is an imported device this
        instance has never seen."""
        entry = self.resolution_map.get(h) or {}
        if entry.get("name"):
            return entry["name"]
        from .. import storage
        known = storage.remembered_device_name(h)
        if known:
            return f"{known} (not in Home Assistant right now)"
        return "a device from another hub (not in this Home Assistant)"

    def _unresolved(self, h: str, what: str, kind: str, ctx: dict) -> str:
        """A device that isn't in this Home Assistant right now.

        RULING (Jeremy, 2026-07-19), overriding COMPILER_DECISIONS_DEPLOY §2's
        skip-and-flag: keep the reference in the emitted automation. Rationale
        in his words — a device that is just out of service "will just work
        when they come back up"; dropping it silently shrinks the automation,
        and failing the piston takes the working devices down too. The dangling
        entity is visible in HA, the only surface where device ids belong.
        The compile record carries a warning so the UI can say so in names."""
        remembered = self.remembered_entity(h, what)
        self.unresolved.append({"label": self._device_label(h), "for": what,
                                "kind": kind, "entity": remembered})
        if remembered:
            return remembered
        # never seen here: a stable, obviously-inert placeholder. HA loads the
        # automation and simply finds nothing to act on until it appears.
        return f"unknown.pistoncore_unresolved_{h.strip(':')[:8]}"

    def entities_for_attr(self, drefs: list[str], attr: str, ctx: dict) -> list[str]:
        out = []
        for dref in drefs:
            for h in self._hashes(dref, ctx):
                entry = self.resolution_map.get(h)
                ent = (entry or {}).get("attr_bindings", {}).get(attr) if entry else None
                if ent:
                    from .. import storage
                    storage.remember_binding(h, attr, ent, entry.get("name"))
                else:
                    ent = self._unresolved(h, attr, "attribute", ctx)
                out.append(ent)
        return out

    def entities_for_command(self, drefs: list[str], command: str, ctx: dict) -> list[str]:
        out = []
        for dref in drefs:
            for h in self._hashes(dref, ctx):
                entry = self.resolution_map.get(h)
                ent = (entry or {}).get("cmd_bindings", {}).get(command) if entry else None
                if ent:
                    from .. import storage
                    storage.remember_binding(h, command, ent, entry.get("name"))
                else:
                    ent = self._unresolved(h, command, "command", ctx)
                out.append(ent)
        return out

    def ha_state_value(self, attr: str, value):
        return self.value_maps.get(attr, {}).get(value, value)

    def opposite_state(self, value: str) -> str | None:
        return self.binary_opposites.get(value)

    def speaker_targets(self, drefs: list[str], ctx: dict) -> list[str] | None:
        """If these devices are media_players that can speak, return their
        entities; else None. A webCoRE deviceNotification on a speaker is a
        spoken message, not a push — both bands need this test, so it lives
        here rather than copy-pasted (review 2026-07-20 finding C)."""
        if not drefs:
            return None
        try:
            ents = self.entities_for_command(drefs, "speak", ctx)
        except Exception:
            return None
        return ents if ents and all(e.startswith("media_player.") for e in ents) else None

    def service_for(self, command: str, entity_id: str, ctx: dict) -> str:
        service, _ = self.service_spec(command, entity_id, ctx)
        return service

    def service_spec(self, command: str, entity_id: str, ctx: dict) -> tuple[str, dict | None]:
        """(service, data-template-or-None). command_maps.json values are a
        plain service string or {service, data} — data values carry $1/$2
        param tokens the emitter substitutes (see the map's _comment)."""
        domain = entity_id.split(".", 1)[0]
        per_domain = self.command_maps.get(command) or {}
        # "_any": commands that work on any entity (refresh/poll -> update_entity)
        spec = per_domain.get(domain) or per_domain.get("_any")
        if not spec:
            raise UnresolvableDevice(
                f"no HA service mapping for command '{command}' on domain '{domain}' "
                f"(command_maps.json)", ha_domain=domain, **ctx)
        if isinstance(spec, str):
            return spec, None
        return spec["service"], spec.get("data")

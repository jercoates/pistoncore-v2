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
        self.globals_map = globals_map or {}
        self.local_device_vars = {
            v["n"]: ((v.get("v") or {}).get("d") or [])
            for v in piston.get("v", []) if v.get("t") == "device"
        }
        maps = _load_band_json("value_maps.json")
        self.value_maps = maps["attribute_values"]
        self.binary_opposites = maps["binary_opposites"]
        self.system_values = maps.get("system_values", {})
        self.command_maps = _load_band_json("command_maps.json")
        self.local_var_names = {v.get("n") for v in piston.get("v", [])}
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
                raise UnresolvableDevice(f"global device variable '{dref}' not found", **ctx)
            v = g.get("v")
            if isinstance(v, list):
                return v
            return (v or {}).get("d") or g.get("d") or []
        if dref in self.local_device_vars:
            return self.local_device_vars[dref]
        raise UnresolvableDevice(f"device reference '{dref}' is neither a hash, a local "
                                 f"device variable, nor a global", **ctx)

    def entities_for_attr(self, drefs: list[str], attr: str, ctx: dict) -> list[str]:
        out = []
        for dref in drefs:
            for h in self._hashes(dref, ctx):
                entry = self.resolution_map.get(h)
                if entry is None:
                    raise UnresolvableDevice(
                        f"no resolution-map entry for device {h} (attribute '{attr}')", **ctx)
                ent = (entry.get("attr_bindings") or {}).get(attr)
                if not ent:
                    raise UnresolvableDevice(
                        f"device {entry.get('name', h)} has no binding for attribute '{attr}'", **ctx)
                out.append(ent)
        return out

    def entities_for_command(self, drefs: list[str], command: str, ctx: dict) -> list[str]:
        out = []
        for dref in drefs:
            for h in self._hashes(dref, ctx):
                entry = self.resolution_map.get(h)
                if entry is None:
                    raise UnresolvableDevice(
                        f"no resolution-map entry for device {h} (command '{command}')", **ctx)
                ent = (entry.get("cmd_bindings") or {}).get(command)
                if not ent:
                    raise UnresolvableDevice(
                        f"device {entry.get('name', h)} has no binding for command '{command}'", **ctx)
                out.append(ent)
        return out

    def ha_state_value(self, attr: str, value):
        return self.value_maps.get(attr, {}).get(value, value)

    def opposite_state(self, value: str) -> str | None:
        return self.binary_opposites.get(value)

    def service_for(self, command: str, entity_id: str, ctx: dict) -> str:
        service, _ = self.service_spec(command, entity_id, ctx)
        return service

    def service_spec(self, command: str, entity_id: str, ctx: dict) -> tuple[str, dict | None]:
        """(service, data-template-or-None). command_maps.json values are a
        plain service string or {service, data} — data values carry $1/$2
        param tokens the emitter substitutes (see the map's _comment)."""
        domain = entity_id.split(".", 1)[0]
        spec = (self.command_maps.get(command) or {}).get(domain)
        if not spec:
            raise UnresolvableDevice(
                f"no HA service mapping for command '{command}' on domain '{domain}' "
                f"(command_maps.json)", ha_domain=domain, **ctx)
        if isinstance(spec, str):
            return spec, None
        return spec["service"], spec.get("data")

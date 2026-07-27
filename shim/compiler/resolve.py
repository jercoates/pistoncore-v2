"""RESOLVE — device refs / values / commands -> real HA entities & services
(COMPILER_SPEC §3.1). The hash<->entity resolution map is INJECTED: production
passes the device pipeline's map (DEVICE_PAYLOAD_SPEC §8), tests pass a
fixture map — that's how golden-fixture placeholder entity_ids stay honest.

d-array entries resolve as: hashed id | local device-variable name | @global
name (PISTON_JSON_REFERENCE §4 — never assume already-a-hash)."""

import json
from pathlib import Path

from .errors import UnresolvableDevice

from .. import customize

# The opposite of a binary webCoRE value, used to emit a reverse trigger.
# NOT translation and deliberately not in the vocab: no Home Assistant name
# appears here, so no HA rename can break it. "off" is the opposite of "on"
# in webCoRE's own vocabulary, which is frozen (Jeremy's file-split rule
# 2026-07-26: split by why something changes; this never does).
_BINARY_OPPOSITES = {"on": "off", "off": "on"}




_vocab_cache: tuple | None = None


def _load_vocab() -> dict:
    """The vocab, cached but NEVER stale.

    It's read on every transform, every value lookup and every service
    resolution, and it's a big file — re-parsing it each time made a compile
    thousands of file reads. Cached on (path, mtime, size) instead of blindly,
    so the standing promise still holds: edit the file, next compile uses it,
    no restart (COMPILER_DECISIONS_HOLDING §E1)."""
    global _vocab_cache
    path = customize.path("webcore_vocab.json")
    try:
        stat = path.stat()
        stamp = (str(path), stat.st_mtime_ns, stat.st_size)
    except OSError:
        stamp = None
    if _vocab_cache is not None and stamp is not None and _vocab_cache[0] == stamp:
        return _vocab_cache[1]
    with open(path, encoding="utf-8") as f:
        vocab = json.load(f)
    _vocab_cache = (stamp, vocab)
    return vocab


def _load_command_ha(vocab: dict) -> dict:
    """Command -> HA-service translation, read from the VOCAB's per-command
    "ha" arrays (the one translation source). Returns {command: [ha entry, ...]}
    where each entry is {domain?, service, data?}. Band-agnostic — the vocab
    knows nothing about yaml vs pyscript."""
    out = {}
    for section in ("commands", "virtualCommands"):
        for name, d in vocab.get(section, {}).items():
            ha = d.get("ha")
            if isinstance(ha, list):
                out[name] = ha
    return out


def _attribute_value_maps(vocab: dict) -> dict:
    """webCoRE value -> HA value, per attribute, DERIVED by flipping the
    vocab's own read rules.

    The vocab stores HA->webCoRE because that's the direction the device
    payload needs ("this sensor says on, show it as active"). Writing needs
    the reverse ("the piston says active, emit on"). It is the same table, so
    it is stored once and flipped here rather than kept twice — keeping both
    directions on disk is what let the old value_maps.json drift.

    FIRST LISTED WINS. Several HA states can collapse to one webCoRE word
    (a lock reports jammed/locking/unlocking and all mean 'unknown'), so the
    flip is ambiguous by nature; rule order in the vocab picks the canonical
    one to write. The '*' catch-all is skipped — it is a read-side wildcard
    and means nothing when writing."""
    out: dict = {}
    for attr, entry in vocab.get("attributes", {}).items():
        for rule in (entry.get("ha") or []):
            if not isinstance(rule, dict):
                continue
            for ha_value, wc_value in (rule.get("map") or {}).items():
                if ha_value == "*":
                    continue
                out.setdefault(attr, {}).setdefault(str(wc_value), ha_value)
    return out


def _system_value_maps(vocab: dict) -> dict:
    """webCoRE value -> HA value for the stand-in entities behind system
    variables ($alarmSystemStatus and friends)."""
    out = {}
    for name, entry in vocab.get("virtualDevices", {}).items():
        ha = entry.get("ha")
        if isinstance(ha, dict) and isinstance(ha.get("state_map"), dict):
            out[name] = ha["state_map"]
    return out


def _alarm_service_map(vocab: dict) -> dict:
    """Requested alarm status -> the service that puts the panel in it."""
    for rule in (vocab.get("virtualCommands", {})
                 .get("setAlarmSystemStatus", {}).get("ha") or []):
        by_value = rule.get("service_by_value")
        if isinstance(by_value, dict):
            return by_value
    return {}


def value_map(name: str) -> dict:
    """A shared webCoRE->HA value table from the vocab's "_value_maps"
    (thermostat modes, fan speeds). Shared by several commands, so filed once
    rather than repeated on each."""
    table = (_load_vocab().get("_value_maps") or {}).get(name) or {}
    return {k: v for k, v in table.items() if not k.startswith("_")}


def rescale(name: str, value):
    """Convert a number between webCoRE's scale and HA's, using the ranges in
    the vocab's _value_maps.scales.

    The arithmetic is here and the numbers are in the vocab, deliberately
    (Jeremy, 2026-07-26). What can change is the RANGE — if HA moved volume to
    0-100 the fix is one number in a JSON file someone can read; a division
    stays a division forever, so moving it into a template would put the fixed
    part where it is hardest to read and leave the changeable part in code."""
    spec = (_load_vocab().get("_value_maps") or {}).get("scales", {}).get(name)
    if not isinstance(spec, dict):
        raise KeyError(f"vocab _value_maps.scales has no entry '{name}'")
    src, dst = float(spec["from"]), float(spec["to"])
    digits = int(spec.get("round", 2))
    # Multiply by the ratio rather than dividing then multiplying. Dividing
    # first perturbs the float and changes the answer at exact .5 boundaries —
    # with equal scales, 0.85/100*100 rounds to 0.9 where plain 0.85 rounds to
    # 0.8. Caught by comparing against the previous arithmetic across the whole
    # input range; equal scales now short-circuit to no arithmetic at all.
    if src == dst:
        return round(float(value), digits)
    return round(float(value) * dst / src, digits)


def color_hex(name: str) -> str | None:
    """A webCoRE colour name -> hex, from the vocab's own colour list (the
    full webCoRE set), plus the few spellings webCoRE itself doesn't use."""
    vocab = _load_vocab()
    wanted = str(name).strip().lower()
    for colour in (vocab.get("colors", {}).get("standard") or []):
        if str(colour.get("n", "")).lower() == wanted:
            return colour.get("rgb")
    aliases = (vocab.get("_value_maps") or {}).get("color_aliases") or {}
    value = aliases.get(wanted)
    return value if isinstance(value, str) else None


def ha_name(key: str) -> str:
    """An HA name that no webCoRE word maps to, read from the vocab's
    "_ha_names" section.

    Most HA names are filed under the webCoRE word that causes them, because
    webCoRE's vocabulary is frozen and HA's is not — the frozen word makes a
    stable handle to look the changing one up by (Jeremy, 2026-07-26). A few
    names have no webCoRE counterpart at all, because webCoRE never had to do
    the thing (reloading HA's config after a deploy). Having no CAUSE in
    webCoRE and having no NAME are different problems: these still get renamed
    by HA, so they still live in the vocab where a non-programmer can fix them,
    just in their own labelled section rather than under a command."""
    names = _load_vocab().get("_ha_names") or {}
    value = names.get(key)
    if not isinstance(value, str):
        raise KeyError(f"vocab '_ha_names' has no entry '{key}'")
    return value


class Resolver:
    def __init__(self, piston: dict, resolution_map: dict, globals_map: dict | None = None):
        self.resolution_map = resolution_map
        self.globals_map = globals_map if globals_map is not None else {}
        self.local_device_vars = {
            v["n"]: ((v.get("v") or {}).get("d") or [])
            for v in piston.get("v", []) if v.get("t") == "device"
        }
        # ONE read, one source. Commands AND values both come from the vocab;
        # the per-band command_maps.json and value_maps.json were deleted
        # 2026-07-26 (memory: one_translation_source_decision).
        # Attribute states are not stored twice either — the vocab holds
        # HA->webCoRE for reading, and _attribute_value_maps flips it for
        # writing.
        vocab = _load_vocab()
        self.value_maps = _attribute_value_maps(vocab)
        self.system_values = _system_value_maps(vocab)
        self.alarm_commands = _alarm_service_map(vocab)
        self.command_ha = _load_command_ha(vocab)
        self.virtual_devices = vocab.get("virtualDevices", {})
        self.local_var_names = {v.get("n") for v in piston.get("v", [])}
        self.unresolved: list[dict] = []   # devices kept but not currently in HA
        self.media_warnings: list[dict] = []   # Play-track URLs HA can't play as typed
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
        return _BINARY_OPPOSITES.get(value)

    def speaker_targets(self, drefs: list[str], ctx: dict) -> list[str] | None:
        """If these devices are media_players that can speak, return their
        entities; else None. A webCoRE deviceNotification on a speaker is a
        spoken message, not a push — both bands need this test, so it lives
        here rather than copy-pasted (review 2026-07-20 finding C)."""
        if not drefs:
            return None
        try:
            ents = self.entities_for_command(drefs, "speak", ctx)
        except UnresolvableDevice:
            # the device reference can't be resolved as a speaker — the
            # expected "this isn't a media_player" signal. Any OTHER error is a
            # real bug and must surface, not be swallowed (review 2026-07-20).
            return None
        return ents if ents and all(e.startswith("media_player.") for e in ents) else None

    def command_ha_entry(self, command: str, ctx: dict) -> dict:
        """The HA translation for a command that ISN'T aimed at a device the
        user picked (wake a LAN device, set location mode, pause another
        piston) — the vocab entry with no `domain` key.

        The caller is already inside the branch that handles this one command,
        so it knows perfectly well there's no device involved; it doesn't need
        the vocab to tell it that. It needs the NAME, which is the thing HA
        renames. Mechanism stays in code, names stay in the vocab (Jeremy,
        2026-07-26)."""
        for entry in self.command_ha.get(command, []):
            if not entry.get("domain"):
                return entry
        raise UnresolvableDevice(
            f"no HA name for command '{command}' in the vocab — add an 'ha' "
            f"entry to webcore_vocab.json", **ctx)

    def ha_spec(self, command: str, ctx: dict) -> dict:
        """The vocab's HA translation for a command the emitter handles with
        its own code path (speak, the notification family, setHSLColor).

        Those paths can't go through service_spec because the service isn't
        aimed at the piston's devices — Speak targets the TTS engine and puts
        the speakers in the data; a notification targets nothing at all. They
        still need the NAMES, which is all this returns. Which command it is
        is already known by the caller, so the first entry is the answer."""
        for entry in self.command_ha.get(command, []):
            return entry
        raise UnresolvableDevice(
            f"no HA name for command '{command}' in the vocab — add an 'ha' "
            f"entry to webcore_vocab.json", **ctx)

    def virtual_device_ha(self, name: str) -> dict:
        """HA names standing in for a webCoRE concept HA has no equivalent of
        ($mode -> an input_select helper, $alarmSystemStatus -> an
        alarm_control_panel). Keys: entity and/or domain."""
        ha = (self.virtual_devices.get(name) or {}).get("ha")
        return ha if isinstance(ha, dict) else {}

    def service_for(self, command: str, entity_id: str, ctx: dict) -> str:
        service, _ = self.service_spec(command, entity_id, ctx)
        return service

    def service_spec(self, command: str, entity_id: str, ctx: dict) -> tuple[str, dict | None]:
        """(service, data-template-or-None) for a command aimed at a device,
        picked by that device's domain. data values carry $1/$2 param tokens
        the emitter substitutes.

        The vocab is now the ONLY source: command_maps.json was deleted
        2026-07-26 once the golden-snapshot harness showed no drift with it
        emptied. A permanent fallback would have been two sources again — the
        exact thing this consolidation existed to kill (Jeremy: "leaving it
        after testing is just lazy").

        Entries whose data still uses the vocab's older DECLARATIVE spelling
        ({0} rather than $1) are skipped rather than emitted wrong. Nothing in
        the shipped vocab is written that way any more, but a hand-edit or an
        imported fix could be, and a skipped entry fails loudly here instead of
        producing a broken service call."""
        domain = entity_id.split(".", 1)[0]

        def _executable(entry: dict) -> bool:
            data = entry.get("data")
            if not data:
                return True
            return not any("{" in str(v) for v in data.values())

        for entry in self.command_ha.get(command, []):
            if entry.get("domain") in (domain, "_any", "*") and _executable(entry):
                return entry["service"], entry.get("data")

        raise UnresolvableDevice(
            f"no HA service mapping for command '{command}' on domain '{domain}' "
            f"— add an 'ha' entry for it in webcore_vocab.json",
            ha_domain=domain, **ctx)

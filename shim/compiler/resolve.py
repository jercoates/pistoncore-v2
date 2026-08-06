"""RESOLVE — device refs / values / commands -> real HA entities & services
(COMPILER_SPEC §3.1). The hash<->entity resolution map is INJECTED: production
passes the device pipeline's map (DEVICE_PAYLOAD_SPEC §8), tests pass a
fixture map — that's how golden-fixture placeholder entity_ids stay honest.

d-array entries resolve as: hashed id | local device-variable name | @global
name (PISTON_JSON_REFERENCE §4 — never assume already-a-hash)."""

import hashlib
import json
import re
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



# webCoRE type -> the HA helper that holds it (VARIABLES_SPEC §4).
# `device` is out of scope here: device variables resolve to entities directly.
_HELPER_DOMAIN = {
    "boolean": "input_boolean",
    "integer": "input_number",
    "long": "input_number",
    "decimal": "input_number",
    "string": "input_text",
    "dynamic": "input_text",
    "time": "input_datetime",
    "date": "input_datetime",
    "datetime": "input_datetime",
}


# ── the `was_*` family ────────────────────────────────────────────────────
#
# webCoRE evaluates these by walking the device's state history BACKWARDS,
# accumulating time while each past state satisfies an ordinary instantaneous
# comparison and stopping at the first that does not
# (webcore-piston.groovy:8255-8300, `valueWas`). So `was_less_than N` is not
# "is below N" — it is "has been CONTINUOUSLY below N for [at least|less than]
# T". Only the sustained part is special; the inner test is a normal
# comparison, which is what this table names.
#
# It lives here, not in either emitter, because both bands have to answer the
# SAME question. PyScript previously reached the answer by lumping was_* into
# the is_* branches, which silently dropped the duration entirely.
WAS_TO_IS = {
    "was": "is",
    "was_not": "is_not",
    "was_equal_to": "is_equal_to",
    "was_different_than": "is_different_than",
    "was_less_than": "is_less_than",
    "was_less_than_or_equal_to": "is_less_than_or_equal_to",
    "was_greater_than": "is_greater_than",
    "was_greater_than_or_equal_to": "is_greater_than_or_equal_to",
    "was_any_of": "is_any_of",
    "was_not_any_of": "is_not_any_of",
    "was_inside_of_range": "is_inside_of_range",
    "was_outside_of_range": "is_outside_of_range",
    "was_even": "is_even",
    "was_odd": "is_odd",
}

# HA has no "this numeric predicate has held for T" primitive: the
# `numeric_state` CONDITION takes no `for:`, and `last_changed` resets on every
# update, so a sensor that reports while staying below its threshold would
# never accumulate. Instead a helper records WHEN the predicate became true and
# the test becomes "true now, and has been since >= T".
#
# This sentinel means "not currently satisfied". input_datetime always holds a
# value, so there is no empty state to mean it — and without an explicit
# not-satisfied marker, an unset helper would read as an enormous duration and
# the comparison would answer TRUE. Fail closed, deliberately.
WAS_SENTINEL = "1970-01-01 00:00:00"


# webCoRE stores every duration the same way — a number in `c` and its unit in
# `vt` — whether it is a comparison's hold time, a `wait`, or a fade's length.
# ONE converter, because the copies drifted: the wait-command copy was missing
# "d", so a wait authored in days silently became that many seconds.
_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def duration_seconds(op) -> int | None:
    """A webCoRE duration operand in whole seconds; None if not a fixed number."""
    if not isinstance(op, dict):
        return None
    n = op.get("c")
    if not isinstance(n, (int, float)) or isinstance(n, bool):
        return None
    return int(n * _DURATION_UNITS.get(op.get("vt", "s"), 1))


def last_changed_is_exact(cond: dict) -> bool:
    """True when HA's own `last_changed` already answers "for how long".

    Exact for ONE predicate: "the state has been this single value". Then any
    change to the state is also a change to the answer, the two clocks agree,
    and no watcher is needed — the cheap path most real pistons take.

    Wrong for anything that stays true ACROSS a value change: a numeric bound
    (a fridge going 11° -> 12° is still above 10, but last_changed restarts),
    `is_not` (changing between two values that are both "not X"), or a list of
    accepted values. Those need a watcher.

    Shared by both bands so they cannot disagree about which comparisons are
    cheap and which need tracking.
    """
    return cond.get("co") == "was" and not isinstance(cond.get("value"), list)


def was_watcher_entity(piston_id: str, entities, attr, co: str,
                       value, value2=None) -> str:
    """Deterministic entity id for the helper behind one `was_*` comparison.

    Keyed by everything that changes the question being asked, so two pistons
    watching the same device for the same thing share one helper, and
    recompiling reuses it instead of orphaning it — same rule as
    helper_entity_id above."""
    key = "|".join([",".join(sorted(entities or [])), str(attr), str(co),
                    str(value), str(value2)])
    slug = hashlib.md5(key.encode("utf-8")).hexdigest()[:8]
    return f"input_datetime.pistoncore_{piston_id}_was_{slug}".lower()


def helper_entity_id(piston_id: str, name: str, vtype: str) -> str | None:
    """Deterministic entity id for a variable's backing helper.

    Deterministic so recompiling reuses the same helper rather than orphaning
    it — the same reason auto_ids are derived rather than generated."""
    domain = _HELPER_DOMAIN.get(str(vtype).rstrip("[]"))
    if domain is None:
        return None
    if str(vtype).endswith("]"):
        domain = "input_text"        # lists serialise to JSON in a text helper
    slug = re.sub(r"[^a-z0-9_]+", "_", str(name).lower()).strip("_")
    return f"{domain}.pistoncore_{piston_id}_{slug}".lower()


def variables_needing_helpers(piston: dict) -> dict:
    """{name: {type, entity, reason}} for locals that cannot live in a YAML
    `variables:` block — see this module's stage-3a note."""
    decls = {v.get("n"): str(v.get("t") or "dynamic")
             for v in (piston.get("v") or []) if v.get("n")}
    if not decls:
        return {}
    written, read = {}, {}

    def walk(node, stmt):
        if isinstance(node, list):
            for x in node:
                walk(x, stmt)
            return
        if not isinstance(node, dict):
            return
        for task in (node.get("k") or []):
            if task.get("c") == "setVariable":
                prm = (task.get("p") or [{}])[0]
                nm = prm.get("x") or prm.get("c")
                if nm in decls:
                    written.setdefault(nm, set()).add(stmt)
        blob = json.dumps({k: v for k, v in node.items() if k != "k"})
        for nm in decls:
            if re.search(r"\b" + re.escape(nm) + r"\b", blob):
                read.setdefault(nm, set()).add(stmt)
        for key in ("s", "e", "ei", "ts", "fs", "c", "cs"):
            if node.get(key):
                walk(node[key], stmt)

    for stmt in piston.get("s", []):
        walk(stmt, stmt.get("$"))

    out = {}
    for nm, vtype in decls.items():
        if vtype == "device":
            continue
        w = written.get(nm, set())
        if not w:
            continue                      # never assigned: nothing to persist
        r = read.get(nm, set())
        crosses = bool(r - w) or len(w) > 1
        if not crosses:
            continue                      # lives and dies inside one statement
        if _HELPER_DOMAIN.get(str(vtype).rstrip("[]")) is None:
            continue
        # The entity id needs the piston id, which the Resolver does not
        # receive — the emitters build it with helper_entity_id().
        out[nm] = {"type": vtype,
                   "written_in": sorted(x for x in w if x is not None),
                   "read_in": sorted(x for x in r if x is not None)}
    return out

def typed_value(value_op: dict, declared: dict | None):
    """A constant coerced to its DECLARED type, or None to leave it alone.

    ONE decision, used by BOTH bands — each formats the result its own way
    (`true` in YAML/Jinja, `True` in Python). Sharing the decision but not the
    formatting is deliberate: the last time a band borrowed the other's
    formatter it emitted a Jinja template into a PyScript module.

    webCoRE stores every constant as text, so the declared type is the only
    thing that says what it means. Booleans matter most — the string "false"
    is TRUTHY in both Jinja and Python, so leaving it as text silently inverts
    `if <var>` (VARIABLES_SPEC §4)."""
    if not declared or value_op.get("t") != "c":
        return None
    raw = value_op.get("c")
    if raw is None or isinstance(raw, (list, dict)):
        return None
    kind = (declared.get("type") or "").rstrip("[]")
    text = str(raw).strip()
    if kind == "boolean":
        low = text.lower()
        return True if low == "true" else False if low == "false" else None
    if kind in ("integer", "long"):
        try:
            return int(float(text))
        except (TypeError, ValueError):
            return None
    if kind == "decimal":
        try:
            return float(text)
        except (TypeError, ValueError):
            return None
    return None


def rescale_template(name: str, expr: str) -> str:
    """rescale() for a value only known at RUNTIME (a variable or expression).

    Same ranges, same rounding, read from the vocab exactly as rescale does —
    the template twin, not a second set of numbers."""
    spec = (_load_vocab().get("_value_maps") or {}).get("scales", {}).get(name)
    if not isinstance(spec, dict):
        raise KeyError(f"vocab _value_maps.scales has no entry '{name}'")
    src, dst = float(spec["from"]), float(spec["to"])
    digits = int(spec.get("round", 2))
    if src == dst:
        return f"({expr}) | float(0) | round({digits})"
    return f"((({expr}) | float(0)) * {dst / src!r}) | round({digits})"


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
        self.vocab = vocab
        self.value_maps = _attribute_value_maps(vocab)
        self.system_values = _system_value_maps(vocab)
        self.alarm_commands = _alarm_service_map(vocab)
        self.command_ha = _load_command_ha(vocab)
        self.virtual_devices = vocab.get("virtualDevices", {})
        self.local_var_names = {v.get("n") for v in piston.get("v", [])}
        # The DECLARATION, not just the name. Collected but not yet consumed
        # (stage 1 of the variables work) — see VARIABLES_SPEC §4 for what the
        # type governs and §5 for what the initial value governs.
        #
        # `has_initial` is the persistence test: webCoRE re-initializes a
        # variable that HAS an initial value on every run, and persists one
        # that does not. A list type cannot be given an initial value at all
        # (the editor hides the field), so lists are always persistent.
        # Locals that need a real HA helper because their reads cross the
        # statement that wrote them (stage 3a). Keyed by variable name.
        self.helper_vars = variables_needing_helpers(piston)
        self.local_var_decls = {}
        for v in piston.get("v", []):
            name = v.get("n")
            if not name:
                continue
            vtype = str(v.get("t") or "dynamic")
            init = v.get("v")
            has_initial = isinstance(init, dict) and init.get("c") is not None
            self.local_var_decls[name] = {
                "type": vtype,
                "is_list": vtype.endswith("]"),
                "has_initial": has_initial and not vtype.endswith("]"),
                "initial": init.get("c") if isinstance(init, dict) else None,
            }
        self.unresolved: list[dict] = []   # devices kept but not currently in HA
        self.media_warnings: list[dict] = []   # Play-track URLs HA can't play as typed
        # Things that COMPILED but a user needs told about — an HA
        # limitation the piston has walked into. Not errors: the output
        # is correct as far as HA can go. Surfaced on the front-door
        # indicator and the piston's status banner, never a third place.
        self.warnings: list[str] = []
        sys_ent = resolution_map.get("$system")
        self.system_entities = sys_ent if isinstance(sys_ent, dict) else {}
        # (entity_id, webCoRE attribute) -> the HA FIELD inside that entity,
        # for readings the device pipeline fed in raw. Flattened from each
        # device's attr_field_bindings so read_field() needs only what the
        # emitters already have in hand (an entity and an attribute name).
        self._raw_fields: dict[tuple[str, str], str] = {}
        for entry in resolution_map.values():
            if not isinstance(entry, dict):
                continue
            binds = entry.get("attr_bindings") or {}
            for attr, field in (entry.get("attr_field_bindings") or {}).items():
                ent = binds.get(attr)
                if ent:
                    self._raw_fields[(ent, attr)] = field

    def read_field(self, entity: str, attr: str) -> str | None:
        """The HA field holding this reading, or None to read the entity state.

        WHY (Jeremy, 2026-07-29): HA reports a device's readings in two shapes.
        Some are their own entity, whose STATE is the value
        (sensor.front_lock_battery -> "97.0"). Others ride as a FIELD on
        another entity — a thermostat's current temperature is inside
        climate.x, whose state is "heat". The compiler read the state for
        both, so every field-shaped reading silently compared against the
        wrong thing (a thermostat condition tested "heat" > 72 and never
        fired). The vocab has said which is which all along, in `read`:
        "state" vs "attr:current_temperature", 30 of them tagged verified —
        nothing had ever consumed the field.

        Two sources, checked in that order:
          1. attr_field_bindings, for readings the pipeline fed in raw
             (last_code_name, media_title) — the pipeline knows the field
             because it read it off the entity itself.
          2. the vocab's own `read` rule for the entity's DOMAIN, since one
             webCoRE name covers several (level is attr:brightness on a
             light, attr:volume_level on a media_player, attr:percentage on
             a fan, and the state on a dimmer sensor).

        Returns the field name, possibly with a `[n]` index suffix for the
        packed ones (hue is hs_color[0])."""
        raw = self._raw_fields.get((entity, attr))
        if raw:
            return raw
        rule = self._read_rule(entity, attr)
        read = str((rule or {}).get("read") or "")
        return read[5:] if read.startswith("attr:") else None

    def _read_rule(self, entity: str, attr: str) -> dict | None:
        """The vocab `ha` rule governing how this entity's reading is read."""
        domain = entity.split(".", 1)[0]
        exact = wildcard = None
        for rule in ((self.vocab.get("attributes", {}).get(attr) or {}).get("ha") or []):
            if not isinstance(rule, dict):
                continue
            rule_domain = rule.get("domain")
            # An EXACT domain match wins whatever it says, including "state" —
            # a wildcard rule must never override it. battery is the case that
            # proved this: sensor/state (verified) alongside */attr:battery_level
            # (a guess for entities that carry the field). Preferring the
            # wildcard made every battery sensor read a field it doesn't have.
            if rule_domain == domain and exact is None:
                exact = rule
            elif rule_domain in ("*", "_any", None) and wildcard is None:
                wildcard = rule
        return exact if exact is not None else wildcard

    @staticmethod
    def _scale_read(expr: str, formula: str, entity: str, attr: str) -> str:
        """Apply a vocab read `scale` to a Jinja read expression.

        webCoRE and HA disagree on units for the same reading: a light's level
        is 0-100 in webCoRE and 0-255 in HA, a volume is 0-100 vs 0.0-1.0. The
        vocab records the conversion next to the field it belongs to
        ("scale": "round(x*100/255)"). Only the two shapes the vocab actually
        uses are accepted — an unrecognised formula raises rather than
        silently emitting an unscaled comparison, because a level test that is
        wrong by 2.55x looks plausible and fails quietly."""
        m = re.fullmatch(r"round\(\s*x\s*\*\s*([0-9.]+)\s*(?:/\s*([0-9.]+)\s*)?\)",
                         (formula or "").replace(" ", ""))
        if not m:
            raise UnresolvableDevice(
                f"vocab scale '{formula}' on {attr} ({entity}) isn't a form the "
                f"compiler knows how to apply when reading")
        mult, div = m.group(1), m.group(2)
        arith = f"({expr} | float(0)) * {mult}" + (f" / {div}" if div else "")
        return f"(({arith}) | round(0) | int)"

    def ha_field_name(self, attr: str) -> str:
        """Best guess at the HA field name for a webCoRE attribute, when the
        entity ISN'T known at compile time ($currentEventDevice).

        Three sources, in order: the vocab's own `attr:` rule; the pipeline's
        raw feed, where the attribute name IS the HA field; otherwise
        camelCase -> snake_case, which is the convention both Hubitat's
        bridge and HA itself follow (lastCodeName -> last_code_name,
        VERIFIED against Jeremy's lock 2026-07-29). Pistons imported from
        Hubitat webCoRE carry the Hubitat spelling, so this is the bridge
        between a piston written years ago and the entity in front of us."""
        for rule in ((self.vocab.get("attributes", {}).get(attr) or {}).get("ha") or []):
            if isinstance(rule, dict) and str(rule.get("read") or "").startswith("attr:"):
                return rule["read"][5:].split("[", 1)[0]
        if attr in {f for f in self._raw_fields.values()}:
            return attr
        out = []
        for i, ch in enumerate(attr):
            if ch.isupper() and i:
                out.append("_")
            out.append(ch.lower())
        return "".join(out)

    def read_spec(self, entity: str, attr: str) -> tuple[str | None, str | None]:
        """(field, scale) for this reading — the BAND-AGNOSTIC decision.

        `field` is the HA field holding the value, or None to read the
        entity's state. `scale` is the vocab conversion formula, or None.

        This is the one place either band asks "where does this reading live
        and what units is it in" (Jeremy, 2026-07-29: one translation source,
        routing separate). YAML spells the answer as state_attr(); PyScript
        spells it as _sa(). Neither decides anything."""
        return self.read_field(entity, attr), (self._read_rule(entity, attr) or {}).get("scale")

    @staticmethod
    def scale_factors(formula: str, where: str = "") -> tuple[float, float]:
        """A vocab read `scale` -> (multiplier, divisor).

        Only the two shapes the vocab actually uses are accepted; anything
        else raises rather than silently emitting an unscaled comparison,
        because a level test wrong by 2.55x looks plausible and fails quietly."""
        m = re.fullmatch(r"round\(\s*x\s*\*\s*([0-9.]+)\s*(?:/\s*([0-9.]+)\s*)?\)",
                         (formula or "").replace(" ", ""))
        if not m:
            raise UnresolvableDevice(
                f"vocab scale '{formula}'{where} isn't a form the compiler "
                f"knows how to apply when reading")
        return float(m.group(1)), float(m.group(2) or 1)

    def read_expr(self, entity: str, attr: str) -> str:
        """Jinja that yields this reading — the ONE place a read is spelled.

        Every emitter goes through here rather than writing states() inline,
        so the state-vs-field decision is made once (compiler policy: one
        canonical function per job, COMPILER_DECISIONS_HOLDING §A)."""
        field = self.read_field(entity, attr)
        if not field:
            return f"states('{entity}')"
        if field.endswith("]") and "[" in field:
            name, _, idx = field[:-1].partition("[")
            # `or [0,0]` keeps an unset packed value from raising on the
            # subscript — same fail-closed spirit as the numeric guards.
            expr = f"(state_attr('{entity}','{name}') or [0,0])[{idx}]"
        else:
            expr = f"state_attr('{entity}','{field}')"
        scale = (self._read_rule(entity, attr) or {}).get("scale")
        return self._scale_read(expr, scale, entity, attr) if scale else expr

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
        # COMPILE AND FLAG (Jeremy, 2026-08-01). An unknown NAME is the same
        # situation as an unknown HASH, which has been handled this way since
        # 2026-07-19: keep the reference, let it resolve to an inert
        # placeholder entity, record it as unresolved so the UI can say so.
        # Failing the whole piston over one stale reference takes the working
        # devices down with it — and a leftover reference is common, because
        # people copy pistons and forget to delete a device.
        #
        # Note the shape of the risk, which the warning must convey: in an OR
        # this is harmless (that branch simply never fires); in an AND it can
        # silently disable the statement.
        self.unresolved.append({"label": str(dref), "for": "device reference",
                                "kind": "name", "entity": None})
        return [dref]

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

    def has_command_binding(self, drefs: list[str], command: str, ctx: dict) -> bool:
        """Does any of these devices actually offer this webCoRE command?

        A command can exist in the vocab and still be unreachable on a given
        device — `take` is in the vocab, but a camera arriving through a bridge
        has no camera entity to call it on. That is the difference between "use
        the vocab" and "fall back to the driver passthrough"."""
        for dref in drefs:
            for h in self._hashes(dref, ctx):
                entry = self.resolution_map.get(h) or {}
                if (entry.get("cmd_bindings") or {}).get(command):
                    return True
        return False

    def passthrough(self, drefs: list[str], ctx: dict) -> dict | None:
        """The integration's own command passthrough for this device, if it has
        one — how a DRIVER command (a webCoRE task naming something only the
        device's driver knows, like `clearImages`) reaches the device.

        Recorded per device by the payload builder, which is the only place with
        the service registry. See device_pipeline.detect_passthroughs."""
        for dref in drefs:
            for h in self._hashes(dref, ctx):
                spec = (self.resolution_map.get(h) or {}).get("passthrough")
                if isinstance(spec, dict) and spec.get("service"):
                    return spec
        return None

    def field_order(self, drefs: list[str], service: str, ctx: dict) -> list | None:
        """The parameter boxes the editor offered for this service on this
        device, in order, as recorded when the piston was saved.

        Read-only — the SAVE path writes it (storage.record_ha_field_order).
        Tried against every device the task targets; the first recorded order
        wins, which is right because a task's devices all had to offer the same
        command for the editor to show it."""
        from .. import storage
        for dref in drefs:
            for h in self._hashes(dref, ctx):
                order = storage.ha_field_order(h, service)
                if order is not None:
                    return order
        return None

    def entities_for_domain(self, drefs: list[str], domain: str, ctx: dict) -> list[str]:
        """This device's entities in a given HA domain.

        Custom (`cm`) commands name an HA service directly — `light.turn_on` —
        so there is no webCoRE command to look up in cmd_bindings. The target
        is simply whichever of the device's entities lives in that service's
        domain. A device with several (a fan hub with a fan and a light) can
        legitimately return more than one; the emitter targets them all, which
        is what webCoRE does for any multi-entity device."""
        out = []
        for dref in drefs:
            for h in self._hashes(dref, ctx):
                entry = self.resolution_map.get(h) or {}
                members = [e for e in (entry.get("members") or [])
                           if e.split(".", 1)[0] == domain]
                if members:
                    out.extend(members)
                else:
                    raise UnresolvableDevice(
                        f"'{self._device_label(h)}' has no {domain} entity, so it "
                        f"cannot run a {domain} service", ha_domain=domain, **ctx)
        return out

    def command_is_noop(self, command: str) -> bool:
        """Does this command deliberately compile to nothing?

        Marked `"ha": "noop"` in the vocab. Distinct from an UNMAPPED command,
        which is an error the user should see — this is "webCoRE has it, HA
        needs nothing done", with the reason in the vocab entry's note."""
        vocab = _load_vocab()
        for section in ("commands", "virtualCommands"):
            entry = (vocab.get(section) or {}).get(command)
            if entry and entry.get("ha") == "noop":
                return True
        return False

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

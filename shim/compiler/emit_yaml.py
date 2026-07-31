"""EMIT (YAML/classic band) — branch IR -> HA automation YAML via the Jinja2
band templates (COMPILER_SPEC §3.3). One automation per top-level statement
(§2.5 point 4 TCP scoping).

Session-3 coverage: if-branches with else / else-if / nested ifs (emitted as
HA's native if/then/else action blocks), `every` timers (time / time_pattern
triggers), trigger promotion for condition-only pistons, equality + between +
numeric comparisons with any/all aggregation, the $time is_between window
(HA time condition), and command data params (setLevel/setColor via
vocab $-tokens). TCP-default branches emit mode: restart +
auxiliary cancel-triggers gated by `condition: trigger`; `queued` (Jeremy's
default) governs where TCP doesn't force restart."""

import json as _json_mod
import re
from pathlib import Path


def _json_dumps(v):
    return _json_mod.dumps(v)

from jinja2 import ChoiceLoader, Environment, FileSystemLoader

from .. import customize

from .analyze import analyze
from .errors import NotYetImplemented, PistonDefect
from .expression import JinjaTranspiler
from .resolve import Resolver
from . import routing as _routing

_BAND_REL = "templates/compiler/yaml/classic"
_env = Environment(
    loader=ChoiceLoader([FileSystemLoader(d) for d in customize.search_dirs(_BAND_REL)]),
    trim_blocks=False, lstrip_blocks=False)


# the piston currently being compiled — the text/expression helpers need its
# variable declarations, and threading it through every call site would touch
# a dozen signatures for one read-only lookup.
_PISTON: dict = {"cur": None}

# Media-file playback config (from settings.json "media"), loaded per compile.
# Lets a piston's old Hubitat "Play track" URL (x-file-cifs://...) reach HA:
# rewritten to where HA itself can read it (native mode), or routed through the
# PistonCore media server when the user opted in (server mode). See the
# "Playing media files" help article.
_MEDIA_CFG: dict = {}
_MEDIA_OLD_SCHEMES = ("x-file-cifs://", "smb://", "cifs://")


def _rewrite_media_url(url, resolver, ctx):
    """Route a media_content_id by its FORMAT — no mode toggle, both coexist:
      - a local / HA URL (/local/..., /media/..., http(s)://, media-source://)
        passes straight through; HA plays it. The /local/Music/x.mp3 form is how
        the user says "this file lives in HA's own media folder."
      - a Hubitat share URL (x-file-cifs://, smb://, cifs://) is streamed through
        the PistonCore media server IF the user set it up (Settings); if not, a
        warning — either move the file into HA and use a /local/ URL, or turn the
        media server on.
    The user picks per file just by how the URL is written — "change the URL,
    change the path." (Jeremy 2026-07-23: never a toggle.)"""
    if not isinstance(url, str) or not url:
        return url
    for rw in _MEDIA_CFG.get("rewrites", []):        # explicit override, rare
        frm = rw.get("from") or ""
        if frm and url.startswith(frm):
            return (rw.get("to") or "") + url[len(frm):]
    if not url.startswith(_MEDIA_OLD_SCHEMES):        # local/HA URL -> HA plays it
        return url
    server_base = _MEDIA_CFG.get("server_base")       # share URL -> PistonCore proxy
    if server_base:
        from urllib.parse import quote
        base = server_base.rstrip("/")
        return f"{base}/media/proxy?src={quote(url, safe='')}&sig={_media_sig(url)}"
    resolver.media_warnings.append({
        "url": url,
        "message": ("This Play track points at a network share. Either put the file "
                    "in HA's media folder and use a /local/ URL, or turn on the "
                    "PistonCore media server in Settings."),
    })
    return url


def _media_sig(url: str) -> str:
    """HMAC so the media-server proxy only serves URLs the compiler signed —
    not an open relay. Secret lives in settings; absent -> '' (unsigned)."""
    secret = _MEDIA_CFG.get("server_secret") or ""
    if not secret:
        return ""
    import hmac, hashlib
    return hmac.new(secret.encode(), url.encode(), hashlib.sha256).hexdigest()[:32]


_NUMERIC_OPS = {"is_less_than": "<", "is_less_than_or_equal_to": "<=",
                "is_greater_than": ">", "is_greater_than_or_equal_to": ">="}
_EQUALITY_OPS = {"is": "==", "is_equal_to": "==",
                 "is_not": "!=", "is_not_equal_to": "!="}


def _hex_rgb(value):
    v = str(value)
    if not v.startswith("#"):
        from .resolve import color_hex
        v = color_hex(v) or v
    v = v.lstrip("#")
    try:
        return [int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)]
    except ValueError:
        raise NotYetImplemented(
            f"colour value {value!r} isn't a hex code or a known colour name — "
            f"add it to webcore_vocab.json under _value_maps.color_aliases")


def _mode_value(kind):
    """webCoRE mode word -> HA mode word, from the vocab's _value_maps."""
    def xform(v):
        from .resolve import value_map
        table = value_map(kind)
        key = str(v).strip()
        return table.get(key, table.get(key.lower(), v))
    return xform


def _rescaled(name):
    """Scale conversions whose RANGES live in the vocab (_value_maps.scales),
    so an HA scale change is a number edit rather than a code change."""
    def xform(v):
        from .resolve import rescale
        if v is None or (isinstance(v, str) and not v.strip()):
            # A parameter the piston left empty. Scaling it raised a raw
            # TypeError out of the compiler (2026-07-29, surfaced once
            # 19_Claude_Alarm_checks got far enough to reach it); a missing
            # value is a piston problem to report, not a crash.
            #
            # PistonDefect, not NotYetImplemented, so the driver-passthrough
            # fallback can't swallow it (2026-07-30): a blank volume briefly
            # started "compiling" into hubitat.send_command.
            raise PistonDefect(
                f"a '{name}' parameter has no value to convert — set it in "
                f"the editor, or remove the command")
        return rescale(name, v)
    return xform


# hue_hs / sat_hs pad out to HA's [hue, saturation] pair. The padding values
# are NOT scales — setting hue alone can't know the saturation, so it assumes
# full, and vice versa. That's a modelling compromise and stays in code.
_PARAM_TRANSFORMS = {"hex_rgb": _hex_rgb,
                     "pct_float": _rescaled("pct_float"),
                     "hue_hs": lambda v: [_rescaled("hue_hs")(v), 100],
                     "sat_hs": lambda v: [0, _rescaled("sat_hs")(v)],
                     "hvac_mode": _mode_value("hvac_mode"),
                     "fan_mode": _mode_value("fan_mode"),
                     "speed_pct": _mode_value("fan_speed")}


def _delay_hms(params: list) -> str:
    p = params[0] if params else {}
    n = p.get("c", 0)
    unit = p.get("vt", "s")
    seconds = {"s": n, "m": n * 60, "h": n * 3600}.get(unit, n)
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def _minutes_hms(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}:00"


def _duration_hms(op) -> str | None:
    """The `to` operand on stays/remains/was comparisons — a hold time.
    Returns HH:MM:SS or None when it isn't a fixed number."""
    if not isinstance(op, dict):
        return None
    n = op.get("c")
    if not isinstance(n, (int, float)) or isinstance(n, bool):
        return None
    secs = int(n * {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(op.get("vt", "s"), 1))
    return f"{secs // 3600:02d}:{(secs % 3600) // 60:02d}:{secs % 60:02d}"


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _num_str(v) -> bool:
    """True if v is a number OR a string that parses as one. webCoRE stores
    comparison values as strings ("50"), so a value guard needs this, not
    _is_number — which requires a real int/float and is relied on ELSEWHERE to
    mean exactly that (e.g. distinguishing a numeric time bound from a sunrise
    preset), so it must not be loosened globally."""
    if v is None or isinstance(v, bool):
        return False
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def compile_yaml(piston: dict, piston_id: str, piston_name: str,
                 resolution_map: dict, globals_map: dict | None = None) -> dict:
    """Returns {"target": "yaml", "yaml": str, "reasons": [], "auto_ids": [...]}.
    Routing lives in the package dispatcher (__init__.compile_piston) — a
    NotYetImplemented raised here falls through to the PyScript band there."""
    _PISTON["cur"] = piston
    global _MEDIA_CFG
    from .. import storage
    _MEDIA_CFG = storage.load_settings().get("media", {}) or {}
    branches = analyze(piston, piston_id, piston_name)
    resolver = Resolver(piston, resolution_map, globals_map)
    blocks = []
    auto_ids = []
    header = (f"# Generated by PistonCore — piston \"{piston_name}\" ({piston_id})\n"
              f"# DO NOT EDIT — changes are overwritten on recompile. Template band: yaml/classic\n")

    # A piston that subscribes to nothing is not an automation — it is a
    # runnable sequence. HA's word for that is a script, which is also what
    # webCoRE's Test button and executePiston target
    # (HA_YAML_COMPILER_RESEARCH §2).
    if _has_no_subscriptions(branches):
        return _compile_script(branches, resolver, piston_id, piston_name, header)

    try:
        for br in branches:
            _emit_branch(br, resolver, piston_id, piston_name, blocks, auto_ids)
    except _NoSubscriptions:
        # promotion found nothing subscribable after all — same conclusion,
        # reached later: this piston is a script.
        return _compile_script(branches, resolver, piston_id, piston_name, header)
    except Exception as exc:
        # Half-finished output holds clues to compiler bugs (Jeremy, 2026-07-18:
        # the compiler, not the battle-tested webCoRE JSON, is the likely
        # suspect) — hand back whatever was built before dying so deploy can
        # preserve it in the debug folder.
        exc.partial_yaml = header + "\n".join(blocks) + "\n" if blocks else None
        raise

    return {"target": "yaml", "yaml": header + "\n".join(blocks) + "\n", "reasons": [],
            "auto_ids": auto_ids, "media_warnings": resolver.media_warnings}


class _NoSubscriptions(Exception):
    """Internal signal: nothing in this piston can wake it, so it compiles to
    a script rather than an automation."""


def _has_no_subscriptions(branches: list) -> bool:
    """True when nothing in this piston can wake it: no trigger comparisons,
    no timers, and no conditions that promotion could subscribe to."""
    for br in branches:
        if br["kind"] == "timer" or br["triggers"]:
            return False
        for cond in br["conditions"]:
            if cond.get("lo_type") == "p" and cond.get("devices"):
                return False
    return True


def _compile_script(branches: list, resolver: Resolver, piston_id: str,
                    piston_name: str, header: str) -> dict:
    """Emit the whole piston as one HA script."""
    ctx = {"piston_id": piston_id, "piston_name": piston_name, "stmt_id": None}
    actions = []
    for br in branches:
        body = _resolve_actions(br["then"], resolver, ctx)
        cond_nodes = [_condition(c, resolver, ctx) for c in br["conditions"]]
        els = _resolve_actions(br["else"], resolver, ctx)
        if cond_nodes:
            stmt = [{"kind": "if", "conditions": cond_nodes,
                     "then": body, "else": els}]
        else:
            stmt = body
        # RESTRICTIONS on the script path. A script has no automation-level
        # conditions to hang these on, so the restriction wraps the WHOLE
        # statement — its else included — in a gate with no else of its own:
        # a failed restriction runs nothing at all. Omitting this silently
        # dropped the gate, the same failure the restriction work exists to
        # prevent (found 2026-07-23 while auditing the automation-path fix).
        rest_nodes = [_condition(r, resolver, ctx)
                      for r in (br.get("restrictions") or [])]
        if rest_nodes:
            stmt = [{"kind": "if", "conditions": rest_nodes,
                     "then": stmt, "else": []}]
        actions.extend(stmt)
    script_id = f"pistoncore_{piston_id}"
    block = _env.get_template("script.yaml.j2").render(
        script_id=script_id,
        alias=f"PistonCore: {piston_name}",
        mode="restart" if (branches and branches[0]["tcp"] == "c") else "queued",
        actions=actions,
    )
    return {"target": "yaml", "kind": "script", "yaml": header + block,
            "reasons": [], "auto_ids": [], "script_ids": [script_id],
            "unresolved": resolver.unresolved, "media_warnings": resolver.media_warnings}


# ── conditions ──────────────────────────────────────────────────────────────

_SUN_EVENTS = {"sunrise": "sunrise", "sunset": "sunset"}


def _sun_bound(cond, which):
    """A time bound that is a sun preset (sunrise/sunset), possibly with the
    piston's own offset. Returns (event, offset_hms) or None."""
    preset = cond.get("value_preset") if which == 1 else cond.get("value2_preset")
    if not preset:
        expr = cond.get("value_expr") if which == 1 else cond.get("value2_expr")
        if isinstance(expr, str) and expr.strip().lower().lstrip("$") in ("sunrise", "sunset"):
            preset = expr.strip().lower().lstrip("$")
    if not preset:
        return None
    key = str(preset).strip().lower()
    for name, event in _SUN_EVENTS.items():
        if key.startswith(name):
            return event
    return None


def _num_cmp(read: str, op: str, value) -> str:
    """A numeric comparison that is FALSE when the sensor is unavailable, for
    ANY operator (fail-closed). `x | is_number` is false for
    unknown/unavailable, so the `and` short-circuits.

    Takes the READ EXPRESSION, not an entity — some readings are the entity's
    state and some are a field inside it (Resolver.read_expr decides which)."""
    return (f"{read} | is_number and "
            f"{read} | float(0) {op} {value}")


def _num_between(read: str, lo, hi, negate: bool = False) -> str:
    inside = f"{lo} <= {read} | float(0) <= {hi}"
    body = f"not ({inside})" if negate else f"({inside})"
    return f"{read} | is_number and {body}"


def _condition(cond: dict, resolver: Resolver, ctx: dict) -> dict:
    """Condition IR node -> template/time/sun condition dict for the template."""
    co = cond["co"]

    # nested condition group -> HA's and/or condition blocks
    if co == "_group":
        kids = [_condition(c, resolver, ctx) for c in cond["children"]]
        return {"kind": "or" if cond["group_op"] == "or" else "and",
                "conditions": kids}

    if cond.get("lo_type") == "v":
        var = cond.get("lo_var")
        # $time is_any -> no operand, always true (webCoRE's own "matches any time")
        if var == "time" and co == "is_any":
            return {"kind": "template", "template": "{{ true }}"}
        # $time between-window -> HA's native time condition
        if (var == "time" and co == "is_between"
                and cond.get("value_vt") == "time" and cond.get("value2_vt") == "time"
                and _is_number(cond["value"]) and _is_number(cond["value2"])):
            return {"kind": "time",
                    "after": _minutes_hms(int(cond["value"])),
                    "before": _minutes_hms(int(cond["value2"]))}
        # $time between sunset and X (or any sun preset bound) -> sun condition
        if var == "time" and co in ("is_between", "is_not_between"):
            a_sun, b_sun = _sun_bound(cond, 1), _sun_bound(cond, 2)
            if a_sun or b_sun:
                node = {"kind": "sun"}
                if a_sun:
                    node["after"] = a_sun
                elif _is_number(cond["value"]):
                    node["after_time"] = _minutes_hms(int(cond["value"]))
                if b_sun:
                    node["before"] = b_sun
                elif _is_number(cond["value2"]):
                    node["before_time"] = _minutes_hms(int(cond["value2"]))
                if node.get("after_time") or node.get("before_time"):
                    # mixed clock+sun bound: HA can't express it in one node —
                    # a template using the sun entity's next event does
                    return _sun_mixed_template(node, cond)
                return node
        # $time before/after -> HA time condition (one-sided window)
        if var == "time" and co in ("is_before", "is_after") and _is_number(cond["value"]):
            hms = _minutes_hms(int(cond["value"]))
            return {"kind": "time", "before" if co == "is_before" else "after": hms}
        # entity-backed system variables ($alarmSystemStatus, $mode, ...)
        sysent = resolver.system_entity(var) if var else None
        if sysent and co in _EQUALITY_OPS:
            mapped = resolver.system_value(var, cond["value"])
            return {"kind": "template", "template":
                    f"{{{{ states('{sysent}') {_EQUALITY_OPS[co]} '{mapped}' }}}}"}
        if var in ("time", "datetime") and co in ("is_between", "is_not_between"):
            # a computed bound (sunrise variable, expression) — compare
            # minutes-since-midnight in a template rather than giving up
            jt = _jinja(resolver, ctx, _PISTON.get("cur"))

            def _bound(num, expr):
                if _is_number(num):
                    return str(int(num))
                if not expr:
                    raise NotYetImplemented("time bound is not expressible", **ctx)
                return ("((" + jt.transpile_operand({"e": str(expr).rstrip("; ")})
                        + ") | int)")

            lo_b = _bound(cond.get("value"), cond.get("value_expr"))
            hi_b = _bound(cond.get("value2"), cond.get("value2_expr"))
            mins = "(now().hour * 60 + now().minute)"
            body = (f"({lo_b} <= {mins} <= {hi_b}) if {lo_b} <= {hi_b} "
                    f"else ({mins} >= {lo_b} or {mins} <= {hi_b})")
            if co == "is_not_between":
                body = "not (" + body + ")"
            return {"kind": "template", "template": "{{ " + body + " }}"}
        raise NotYetImplemented(
            f"condition on variable '{var}' ({co}) requires PyScript", **ctx)

    entities = resolver.entities_for_attr(cond["devices"], cond["attr"], ctx)
    # How each reading is actually spelled: states('x') when the value IS the
    # entity's state, state_attr('x','field') when it rides inside the entity
    # (Resolver.read_expr — the one place that decision is made).
    reads = [resolver.read_expr(e, cond["attr"]) for e in entities]
    # A duration condition ("stays above 72 for 5 minutes") needs a timestamp
    # for when the reading last moved. HA tracks last_changed per ENTITY state
    # only — there is no per-attribute timestamp — so a field-backed reading
    # uses last_updated, which at least moves when the attributes do. Exact
    # per-attribute timing needs PyScript; this is the honest YAML answer.
    stamps = [f"states.{e}.{'last_changed' if r.startswith('states(') else 'last_updated'}"
              for e, r in zip(entities, reads)]
    joiner = " and " if cond.get("aggregation") == "all" else " or "

    if co in _NUMERIC_OPS:
        op = _NUMERIC_OPS[co]
        parts = [_num_cmp(e, op, cond["value"]) for e in reads]
    elif co == "is_between" and _num_str(cond["value"]) and _num_str(cond["value2"]):
        # webCoRE stores bounds as strings; _is_number rejected every real case,
        # so numeric is_between silently routed to PyScript instead of compiling
        # to a native YAML template like its siblings is_not_between /
        # is_inside_of_range do. (Round E, 2026-07-23 — same string-vs-number
        # class as the boundary "=" fix.)
        parts = [_num_between(e, cond["value"], cond["value2"]) for e in reads]
    elif co in _EQUALITY_OPS:
        op = _EQUALITY_OPS[co]
        value = cond["value"]
        if _is_number(value):
            parts = [_num_cmp(e, op, value) for e in reads]
        else:
            mapped = resolver.ha_state_value(cond["attr"], value)
            parts = [f"{e} {op} '{mapped}'" for e in reads]
    elif co in ("is_any_of", "is_not_any_of", "is_any"):
        vals = cond["value"] if isinstance(cond["value"], list) else [cond["value"]]
        mapped = [str(resolver.ha_state_value(cond["attr"], v)) for v in vals]
        neg = "not " if co == "is_not_any_of" else ""
        parts = [f"{neg}{e} in {mapped!r}" for e in reads]
    elif co in ("is_even", "is_odd"):
        want = 0 if co == "is_even" else 1
        parts = [f"{e} | int(default=-1) % 2 == {want}" for e in reads]
    elif co == "is_not_between":
        parts = [_num_between(e, cond["value"], cond["value2"], negate=True)
                 for e in reads]
    elif co in ("is_inside_of_range",):
        parts = [_num_between(e, cond["value"], cond["value2"]) for e in reads]
    elif co in ("is_outside_of_range",):
        parts = [_num_between(e, cond["value"], cond["value2"], negate=True)
                 for e in reads]
    elif co in ("stays_greater_than", "stays_greater_than_or_equal_to",
                "stays_less_than", "stays_less_than_or_equal_to",
                "remains_above", "remains_below"):
        OPS = {"stays_greater_than": ">", "stays_greater_than_or_equal_to": ">=",
               "stays_less_than": "<", "stays_less_than_or_equal_to": "<=",
               "remains_above": ">", "remains_below": "<"}
        op = OPS[co]
        hold = _duration_hms(cond.get("duration")) or "00:00:00"
        h, m, sec = (int(x) for x in hold.split(":"))
        secs = h * 3600 + m * 60 + sec
        parts = [f"({_num_cmp(r, op, cond['value'])} and "
                 f"(as_timestamp(now()) - as_timestamp({s})) >= {secs})"
                 for r, s in zip(reads, stamps)]
    elif co in ("stays", "stays_equal_to", "stays_any_of", "was", "was_not"):
        vals = cond["value"] if isinstance(cond["value"], list) else [cond["value"]]
        mapped = [str(resolver.ha_state_value(cond["attr"], v)) for v in vals]
        hold = _duration_hms(cond.get("duration")) or "00:00:00"
        h, m, sec = (int(x) for x in hold.split(":"))
        secs = h * 3600 + m * 60 + sec
        neg = "not " if co == "was_not" else ""
        parts = [f"({neg}{r} in {mapped!r} and "
                 f"(as_timestamp(now()) - as_timestamp({s})) >= {secs})"
                 for r, s in zip(reads, stamps)]
    elif co in ("changes_to", "gets", "arrives", "stays", "stays_equal_to"):
        mapped = resolver.ha_state_value(cond["attr"], cond["value"])
        parts = [f"{e} == '{mapped}'" for e in reads]
    elif co in ("changes_away_from", "stays_away_from"):
        mapped = resolver.ha_state_value(cond["attr"], cond["value"])
        parts = [f"{e} != '{mapped}'" for e in reads]
    elif co in ("changes_to_any_of", "stays_any_of"):
        vals = cond["value"] if isinstance(cond["value"], list) else [cond["value"]]
        mapped = [str(resolver.ha_state_value(cond["attr"], v)) for v in vals]
        parts = [f"{e} in {mapped!r}" for e in reads]
    elif co in ("changes", "changed"):
        parts = ["true"]      # the automation only ran because something changed
    elif co in ("rises_above", "rises", "rises_to_or_above"):
        parts = [f"{e} | float(default=-1.0e9) > {cond['value']}"
                 for e in reads]
    elif co in ("drops_below", "drops", "drops_to_or_below"):
        parts = [_num_cmp(e, "<", cond["value"]) for e in reads]
    elif co in ("was_greater_than", "was_greater_than_or_equal_to",
                "was_less_than", "was_less_than_or_equal_to"):
        OPS = {"was_greater_than": ">", "was_greater_than_or_equal_to": ">=",
               "was_less_than": "<", "was_less_than_or_equal_to": "<="}
        parts = [_num_cmp(e, OPS[co], cond["value"]) for e in reads]
    elif co in ("was_equal_to", "was_any_of"):
        vals = cond["value"] if isinstance(cond["value"], list) else [cond["value"]]
        mapped = [str(resolver.ha_state_value(cond["attr"], v)) for v in vals]
        parts = [f"{e} in {mapped!r}" for e in reads]
    elif co == "is_different_than":
        mapped = resolver.ha_state_value(cond["attr"], cond["value"])
        parts = [f"{e} != '{mapped}'" for e in reads]
    else:
        raise NotYetImplemented(f"condition comparison '{co}' not compiled yet", **ctx)

    body = parts[0] if len(parts) == 1 else "(" + joiner.join(parts) + ")"
    return {"kind": "template", "template": "{{ " + body + " }}"}


# HA's sun entity spells these next_rising / next_setting. It has NO
# next_sunrise or next_sunset attribute — building the name from webCoRE's
# word produced state_attr(...) -> None, and `None | as_datetime` raises, so
# the whole condition errored at runtime and the piston never ran. Two of
# Jeremy's chicken-coop pistons were silently broken this way; found
# 2026-07-30 by rendering every emitted template through HA's own engine,
# which is the only thing that could have caught it. expression.py already
# had the right names — this path just never used them.
_SUN_ATTR = {"sunrise": "next_rising", "sunset": "next_setting",
             "dawn": "next_dawn", "dusk": "next_dusk",
             "noon": "next_noon", "midnight": "next_midnight"}


def _sun_mixed_template(node: dict, cond: dict) -> dict:
    """One bound is a sun event, the other a clock time — HA's sun condition
    can't mix them, so compare against the sun entity's timestamp attribute."""
    parts = []
    if node.get("after"):
        attr = _SUN_ATTR.get(node["after"], f"next_{node['after']}")
        parts.append(f"now() >= (state_attr('sun.sun', '{attr}') | "
                     f"as_datetime | as_local)")
    if node.get("before"):
        attr = _SUN_ATTR.get(node["before"], f"next_{node['before']}")
        parts.append(f"now() <= (state_attr('sun.sun', '{attr}') | "
                     f"as_datetime | as_local)")
    if node.get("after_time"):
        parts.append(f"now().strftime('%H:%M:%S') >= '{node['after_time']}'")
    if node.get("before_time"):
        parts.append(f"now().strftime('%H:%M:%S') <= '{node['before_time']}'")
    return {"kind": "template", "template": "{{ " + " and ".join(parts) + " }}"}


# ── triggers ────────────────────────────────────────────────────────────────

_BARE_DIRECTION_OPS = {"rises": ">", "drops": "<",
                       "does_not_rise": "<=", "does_not_drop": ">="}


def _direction_condition(trig: dict, ctx: dict) -> dict | None:
    """Companion condition for the bare direction ops (see _BARE_DIRECTION_OPS
    and _trigger's "bare direction" branch). The trigger wakes on ANY change
    to the entity; this evaluates the actual direction using trigger.to_state/
    from_state, which HA exposes to automation-level conditions (not to a
    template TRIGGER's own value_template — there's no "previous value" inside
    that). Intent replicated: "did the reading move up/down from what it just
    was," same idiom already used for $currentEventValue/$previousEventValue
    (expression.py:578-579). Fail-closed: a non-numeric or missing from/to
    state (piston just started, entity unavailable) reads as false, never a
    stray match."""
    op = _BARE_DIRECTION_OPS.get(trig.get("co"))
    if op is None or trig.get("lo_type") == "v":
        return None
    body = ("trigger.from_state is not none and trigger.to_state is not none and "
            "trigger.from_state.state | is_number and trigger.to_state.state | is_number and "
            f"trigger.to_state.state | float(0) {op} trigger.from_state.state | float(0)")
    return {"kind": "template", "template": "{{ " + body + " }}"}


# Every trigger-classified node's own HA filter (to:/above:/below:) already
# proves its truth just by firing — that's why _condition() is never called on
# them normally. It stops being true the moment there's an ELSE: webCoRE
# subscribes to the whole ATTRIBUTE and re-decides the SAME comparison on
# every change, both directions, so an else needs the compiler to replicate
# both halves of that: a condition that re-checks the comparison right now
# (routes then vs else), and a mirrored wake for the direction the primary
# trigger's filter can't see (so else is ever actually reached, not just
# skipped until some unrelated event). _TRIGGER_RECHECK_OP reuses
# _condition()'s existing dispatch instead of duplicating boolean logic per
# operator — the trigger op and its "is the comparison true right now"
# sibling differ only in name, not in what they test.
_TRIGGER_RECHECK_OP = {
    "changes_to": "is",
    "changes_away_from": "is_different_than",
    "changes_to_any_of": "is_any_of",
    "changes_away_from_any_of": "is_not_any_of",
    "stays": "is", "stays_equal_to": "is_equal_to",
    "stays_any_of": "is_any_of",
    "stays_away_from": "is_different_than",
    "stays_away_from_any_of": "is_not_any_of",
    "stays_different_than": "is_different_than",
    "rises_above": "is_greater_than", "rises_to_or_above": "is_greater_than_or_equal_to",
    "drops_below": "is_less_than", "drops_to_or_below": "is_less_than_or_equal_to",
    "remains_above": "is_greater_than", "remains_above_or_equal_to": "is_greater_than_or_equal_to",
    "remains_below": "is_less_than", "remains_below_or_equal_to": "is_less_than_or_equal_to",
    "stays_greater_than": "is_greater_than", "stays_greater_than_or_equal_to": "is_greater_than_or_equal_to",
    "stays_less_than": "is_less_than", "stays_less_than_or_equal_to": "is_less_than_or_equal_to",
    "enters_range": "is_inside_of_range", "remains_inside_of_range": "is_inside_of_range",
    "stays_inside_of_range": "is_inside_of_range",
    "exits_range": "is_outside_of_range", "remains_outside_of_range": "is_outside_of_range",
    "stays_outside_of_range": "is_outside_of_range",
    "becomes_even": "is_even", "remains_even": "is_even", "stays_even": "is_even",
    "becomes_odd": "is_odd", "remains_odd": "is_odd", "stays_odd": "is_odd",
}

# The mirrored wake for ops whose HA shape can't be flipped by swapping a
# built node's to:/from:/above:/below: (that generic swap, in _emit_branch,
# covers the equality/numeric-bound families) — these need the SIBLING op
# recompiled through _trigger() itself, since the opposite direction is a
# differently-shaped construct (template vs numeric_state) or a different
# named comparison, not just a flipped field.
_OPPOSITE_TRIGGER_OP = {
    "becomes_even": "becomes_odd", "becomes_odd": "becomes_even",
    "remains_even": "remains_odd", "remains_odd": "remains_even",
    "stays_even": "stays_odd", "stays_odd": "stays_even",
    "enters_range": "exits_range", "exits_range": "enters_range",
    "remains_inside_of_range": "remains_outside_of_range",
    "remains_outside_of_range": "remains_inside_of_range",
    "stays_inside_of_range": "stays_outside_of_range",
    "stays_outside_of_range": "stays_inside_of_range",
}


def _recheck_condition(trig: dict, resolver: Resolver, ctx: dict) -> dict | None:
    """See _TRIGGER_RECHECK_OP. Builds a synthetic condition node from the
    trigger's own IR (same shape _cond_node already produces, co swapped to
    its instantaneous-check sibling) and runs it through the real _condition()
    dispatch — zero new boolean logic, just borrowing what's already there."""
    mapped = _TRIGGER_RECHECK_OP.get(trig.get("co"))
    if mapped is None or trig.get("lo_type") == "v":
        return None
    synthetic = dict(trig, co=mapped)
    return _condition(synthetic, resolver, ctx)


def _trigger(trig: dict, resolver: Resolver, ctx: dict, trig_id=None) -> dict:
    """Wrapper over _trigger_node that tags field-backed readings.

    HA's state and numeric_state triggers take a native `attribute:` key, so a
    reading that lives inside an entity (a thermostat's current_temperature, a
    lock's last_code_name) fires correctly without leaving YAML. Applied here
    rather than at the twenty-odd return sites below, so every trigger shape
    gets it and none can be forgotten."""
    node = _trigger_node(trig, resolver, ctx, trig_id)
    if not isinstance(node, dict) or node.get("kind") not in ("state", "numeric_state"):
        return node
    attr = trig.get("attr")
    entities = node.get("entities") or []
    if not attr or not entities:
        return node
    fields = {resolver.read_field(e, attr) for e in entities}
    if fields == {None}:
        return node                       # every one is a plain state read
    if len(fields) > 1:
        # One webCoRE name reaching different HA fields across the devices in
        # this trigger (a light's `level` is brightness, a fan's is
        # percentage). One YAML trigger can carry one attribute, so this needs
        # the band that can branch per device.
        raise NotYetImplemented(
            f"'{attr}' reads from a different field on each of these devices "
            f"({', '.join(sorted(str(f) for f in fields))}) — needs PyScript", **ctx)
    field = fields.pop()
    if field and field.endswith("]") and "[" in field:
        raise NotYetImplemented(
            f"triggering on '{attr}' means watching one slot of HA's "
            f"{field.split('[')[0]} list, which a YAML trigger can't express "
            f"— needs PyScript", **ctx)
    node["attribute"] = field
    return node


def _trigger_node(trig: dict, resolver: Resolver, ctx: dict, trig_id=None) -> dict:
    co = trig["co"]
    if trig.get("lo_type") == "v":
        var = trig.get("lo_var")
        # "happens daily at ..." -> HA time trigger, or sun trigger when the
        # time is a sunrise/sunset preset
        if var == "time" and trig["co"] in ("happens_daily_at", "happens_at"):
            sun_ev = _sun_bound(trig, 1)
            if sun_ev:
                return {"kind": "sun", "event": sun_ev, "id": trig_id}
            if _is_number(trig["value"]):
                return {"kind": "time", "at": _minutes_hms(int(trig["value"])),
                        "id": trig_id}
        sysent = resolver.system_entity(var) if var else None
        if sysent and co in ("executes", "changes_to_any_of", "is_any_of"):
            raw = trig["value"]
            vals = raw if isinstance(raw, list) else [raw]
            mapped = [str(resolver.system_value(var, v)) for v in vals]
            return {"kind": "state", "entities": [sysent],
                    "to": mapped if len(mapped) > 1 else mapped[0], "id": trig_id}
        if sysent and co == "changes_to":
            return {"kind": "state", "entities": [sysent],
                    "to": resolver.system_value(var, trig["value"]), "id": trig_id}
        if sysent and co == "changes":
            return {"kind": "state", "entities": [sysent], "id": trig_id}
        raise NotYetImplemented(
            f"trigger on variable '{var}' ({co}) requires PyScript", **ctx)
    entities = resolver.entities_for_attr(trig["devices"], trig["attr"], ctx)
    attr, value = trig["attr"], trig["value"]
    hold = _duration_hms(trig.get("duration"))

    def mapped(v):
        return resolver.ha_state_value(attr, v)

    def as_list(v):
        return [mapped(x) for x in v] if isinstance(v, list) else [mapped(v)]

    # ── state (equality) family ──
    if co in ("changes_to", "gets", "arrives"):
        return {"kind": "state", "entities": entities, "to": mapped(value), "id": trig_id}
    if co == "changes":
        return {"kind": "state", "entities": entities, "id": trig_id}
    if co == "changes_away_from":
        return {"kind": "state", "entities": entities, "from": mapped(value), "id": trig_id}
    if co == "changes_to_any_of":
        return {"kind": "state", "entities": entities, "to": as_list(value), "id": trig_id}
    if co == "changes_away_from_any_of":
        return {"kind": "state", "entities": entities, "from": as_list(value), "id": trig_id}
    # "stays X for N" -> HA's native `for:` on a state trigger
    if co in ("stays", "stays_equal_to") and hold:
        return {"kind": "state", "entities": entities, "to": mapped(value),
                "for": hold, "id": trig_id}
    if co == "stays_any_of" and hold:
        return {"kind": "state", "entities": entities, "to": as_list(value),
                "for": hold, "id": trig_id}
    if co in ("stays_away_from", "stays_different_than") and hold:
        return {"kind": "state", "entities": entities, "from": mapped(value),
                "for": hold, "id": trig_id}
    if co == "stays_away_from_any_of" and hold:
        return {"kind": "state", "entities": entities, "from": as_list(value),
                "for": hold, "id": trig_id}
    if co == "stays_unchanged" and hold:
        return {"kind": "state", "entities": entities, "for": hold, "id": trig_id}

    # ── bare direction (no threshold) ── rises/drops = "the reading moved up/
    # down from whatever it just was", not a bound to cross, so unlike
    # rises_above/drops_below this can't be a numeric_state trigger — there is
    # nothing to compare a single current value against. Wakes on ANY change;
    # the companion condition _direction_condition (wired in _emit_branch)
    # gates on the actual direction via trigger.to_state/from_state, the same
    # idiom already used for $currentEventValue/$previousEventValue
    # (expression.py:578-579).
    if co in _BARE_DIRECTION_OPS:
        return {"kind": "state", "entities": entities, "id": trig_id}

    # ── numeric family ──
    NUM_ABOVE = ("rises_above", "rises_to_or_above", "becomes_greater_than")
    NUM_BELOW = ("drops_below", "drops_to_or_below", "becomes_less_than")
    if co in NUM_ABOVE:
        return {"kind": "numeric_state", "entities": entities,
                "above": value, "id": trig_id}
    if co in NUM_BELOW:
        return {"kind": "numeric_state", "entities": entities,
                "below": value, "id": trig_id}
    if co in ("enters_range", "remains_inside_of_range", "stays_inside_of_range"):
        node = {"kind": "numeric_state", "entities": entities,
                "above": value, "below": trig.get("value2"), "id": trig_id}
        if hold and co != "enters_range":
            node["for"] = hold
        return node
    if co in ("exits_range", "remains_outside_of_range", "stays_outside_of_range"):
        # the negation of enters_range: HA's numeric_state with above+below
        # only fires on ENTERING the window (both bounds newly satisfied at
        # once) — there's no native trigger for "value LEFT the range," so
        # this needs a template that's true exactly when the value sits
        # outside [value, value2], firing on the false->true transition.
        joiner = " and " if trig.get("aggregation") == "all" else " or "
        parts = [_num_between(e, value, trig.get("value2"), negate=True) for e in entities]
        body = parts[0] if len(parts) == 1 else "(" + joiner.join(parts) + ")"
        node = {"kind": "template", "template": "{{ " + body + " }}", "id": trig_id}
        if hold and co != "exits_range":
            node["for"] = hold
        return node
    # "remains above N for T" -> numeric_state with `for:` (HA native)
    REMAIN_ABOVE = ("remains_above", "remains_above_or_equal_to",
                    "stays_greater_than", "stays_greater_than_or_equal_to")
    REMAIN_BELOW = ("remains_below", "remains_below_or_equal_to",
                    "stays_less_than", "stays_less_than_or_equal_to")
    if co in REMAIN_ABOVE:
        node = {"kind": "numeric_state", "entities": entities, "above": value,
                "id": trig_id}
        if hold:
            node["for"] = hold
        return node
    if co in REMAIN_BELOW:
        node = {"kind": "numeric_state", "entities": entities, "below": value,
                "id": trig_id}
        if hold:
            node["for"] = hold
        return node

    # ── parity family ── (becomes_even/odd = edge into that parity;
    # remains_even/odd, stays_even/odd = same edge held for a duration —
    # PyScript treats stays_* as a synonym of remains_*, emit_pyscript.py:535)
    PARITY = ("becomes_even", "becomes_odd", "remains_even", "remains_odd",
              "stays_even", "stays_odd")
    if co in PARITY:
        want = 0 if co.endswith("even") else 1
        joiner = " and " if trig.get("aggregation") == "all" else " or "
        parts = [f"states('{e}') | is_number and states('{e}') | int(0) % 2 == {want}"
                 for e in entities]
        body = parts[0] if len(parts) == 1 else "(" + joiner.join(parts) + ")"
        node = {"kind": "template", "template": "{{ " + body + " }}", "id": trig_id}
        if hold and co not in ("becomes_even", "becomes_odd"):
            node["for"] = hold
        return node

    # ── time ──
    if co == "happens_daily_at" and _is_number(value):
        return {"kind": "time", "at": _minutes_hms(int(value)), "id": trig_id}

    raise NotYetImplemented(f"trigger comparison '{co}' not compiled yet", **ctx)


_INCLUSIVE_BOUNDARY_OPS = {
    # conditions that get promoted to a wake
    "is_less_than_or_equal_to", "is_greater_than_or_equal_to",
    # explicit trigger comparisons with the same "or equal to" edge
    "drops_to_or_below", "rises_to_or_above",
}


def _boundary_trigger(node: dict, resolver: Resolver, ctx: dict, trig_id=None):
    """The "or equal to" edge of an inclusive numeric comparison.

    HA's `numeric_state` `above:`/`below:` are STRICT, so a webCoRE `<= N` / `>= N`
    loses its equal case: a value landing EXACTLY on N crosses neither bound and
    wakes nothing. That failure is SILENT — the automation simply never runs and
    nothing reports it, the same shape as the else bug. Emit a companion template
    trigger that fires the moment the value becomes N, so the equal edge has its
    own wake (Jeremy 2026-07-22: "the = could be a separate line as well").

    A `state` trigger on the literal value would be fragile — "200" vs "200.0" —
    so this compares numerically, and is fail-closed on unavailable sensors."""
    if node.get("co") not in _INCLUSIVE_BOUNDARY_OPS:
        return None
    value = node.get("value")
    # webCoRE stores comparison values as STRINGS ("200"), so _is_number (which
    # requires a real int/float, and is relied on elsewhere to mean exactly that)
    # would reject every genuine case. Accept anything numerically parseable.
    if value is None or isinstance(value, bool):
        return None
    try:
        float(value)
    except (TypeError, ValueError):
        return None
    if not node.get("devices") or not node.get("attr"):
        return None
    entities = resolver.entities_for_attr(node["devices"], node["attr"], ctx)
    if not entities:
        return None
    joiner = " and " if node.get("aggregation") == "all" else " or "
    parts = [f"states('{e}') | is_number and states('{e}') | float(0) == {value}"
             for e in entities]
    body = parts[0] if len(parts) == 1 else "(" + joiner.join(parts) + ")"
    return {"kind": "template", "template": "{{ " + body + " }}", "id": trig_id}


def _promote(cond: dict, resolver: Resolver, ctx: dict, trig_id=None) -> dict | None:
    """Condition-only piston: webCoRE subscribes to its conditions (promotion,
    webcore-piston.groovy :9242) — the HA equivalent is a trigger built from
    the condition itself. Unpromotable shapes (time windows, variables)
    contribute no trigger; they stay as conditions."""
    co = cond["co"]
    if cond.get("lo_type") == "v":
        return None
    if co in ("is", "is_equal_to"):
        value = cond["value"]
        if _is_number(value):
            return None
        entities = resolver.entities_for_attr(cond["devices"], cond["attr"], ctx)
        return {"kind": "state", "entities": entities,
                "to": resolver.ha_state_value(cond["attr"], value), "id": trig_id}
    if co in ("is_less_than", "is_less_than_or_equal_to"):
        entities = resolver.entities_for_attr(cond["devices"], cond["attr"], ctx)
        return {"kind": "numeric_state", "entities": entities,
                "below": cond["value"], "id": trig_id}
    if co in ("is_greater_than", "is_greater_than_or_equal_to"):
        entities = resolver.entities_for_attr(cond["devices"], cond["attr"], ctx)
        return {"kind": "numeric_state", "entities": entities,
                "above": cond["value"], "id": trig_id}
    return None


# ── actions ─────────────────────────────────────────────────────────────────

def _has_wait(nodes: list) -> bool:
    for n in nodes:
        if n["kind"] == "task" and n["command"] in ("wait", "waitForTime", "waitRandom"):
            return True
        if n["kind"] == "if" and (_has_wait(n["then"]) or _has_wait(n["else"])):
            return True
    return False


def _resolve_actions(nodes: list, resolver: Resolver, ctx: dict) -> list:
    out = []
    for n in nodes:
        if n["kind"] == "task":
            # A CUSTOM (`cm`) task whose name is an HA service. The dot is the
            # discriminator, NOT the cm flag: webCoRE also sets cm on commands
            # its own dictionary DOES know, when the original hub's driver
            # advertised them (found via 79_sound_Test_2, where `playText` is
            # flagged custom). Those must keep their normal translation.
            if n.get("custom"):
                cmd = str(n["command"])
                if "." in cmd:
                    # an HA service the editor offered directly
                    out.append(_custom_service(n, resolver, ctx))
                    continue
                if not resolver.has_command_binding(n["devices"], cmd, ctx):
                    # A driver command. Either webCoRE has no word for it at all
                    # (clearImages), or it has one the device can't reach here
                    # (`take` on a camera arriving through a bridge, which has no
                    # camera entity). Route it to the integration's passthrough.
                    out.append(_driver_command(n, resolver, ctx))
                    continue
                # otherwise it IS a normal command on this device — webCoRE also
                # flags cm when the hub's driver advertised something it knows
                # (playText) — so fall through to normal translation.
            if n["command"] == "wait":
                out.append({"kind": "delay", "delay": _delay_hms(n["params"])})
                continue
            if n["command"] == "setSwitch":
                # "Set switch to on/off" — a constant on/off value is just the
                # on/off command, resolved through the same on/off mapping any
                # other device command uses. A NON-constant value (variable/
                # expression) would need a choose: picking turn_on vs turn_off
                # at runtime — routed to PyScript for now (it evaluates the
                # value and calls the service directly), an honest band choice,
                # never a dropped action.
                p0 = n["params"][0] if n["params"] else {}
                val = str(p0.get("c") or "").strip().lower()
                if val not in ("on", "off"):
                    raise NotYetImplemented(
                        "setSwitch with a non-constant on/off value requires PyScript", **ctx)
                entities = resolver.entities_for_command(n["devices"], val, ctx)
                service, _ = resolver.service_spec(val, entities[0], ctx)
                out.append({"kind": "service", "service": service,
                            "entities": entities, "data": None})
                continue
            if n["command"] == "setLocationMode":
                mode = (n["params"][0] or {}).get("c") if n["params"] else None
                if not isinstance(mode, str):
                    raise NotYetImplemented("setLocationMode with a computed mode", **ctx)
                spec = resolver.command_ha_entry("setLocationMode", ctx)
                ent = resolver.system_entity("mode") or _mode_entity(resolver)
                field = next(iter(spec["data"]))
                out.append({"kind": "service", "service": spec["service"],
                            "entities": [ent], "data": {field: _json_dumps(mode)}})
                continue
            if n["command"] == "sendNotificationToContacts":
                out.append(_send_notification(n["params"], resolver, ctx,
                                              _PISTON.get("cur")))
                continue
            if n["command"] in ("setAlarmSystemStatus", "setHSMStatus"):
                alarm = resolver.system_entity("alarmSystemStatus")
                if not alarm:
                    raise NotYetImplemented(
                        "setting the alarm needs exactly one alarm_control_panel "
                        "in HA (none found, or several — ambiguous)", **ctx)
                status = (n["params"][0] or {}).get("c") if n["params"] else None
                service = resolver.alarm_commands.get(str(status))
                if not service:
                    raise NotYetImplemented(
                        f"alarm status '{status}' has no service mapping "
                        f"(add it under setAlarmSystemStatus in webcore_vocab.json)", **ctx)
                svc_domain = resolver.command_ha_entry(
                    "setAlarmSystemStatus", ctx)["service_domain"]
                out.append({"kind": "service",
                            "service": f"{svc_domain}.{service}",
                            "entities": [alarm], "data": None})
                continue
            if n["command"] == "setVariable":
                out.append(_set_variable(n, resolver, ctx))
                continue
            if n["command"] == "noop":
                # "No operation" (vocab: no parameters). Emitting nothing is the
                # whole behaviour — webCoRE uses it as a deliberate placeholder.
                continue
            if n["command"] in ("cancelTasks", "cancelPendingTasks"):
                # mode: restart already cancels this automation's pending
                # delays when it retriggers — same effect webCoRE's
                # cancel-pending-tasks has. Nothing to emit.
                continue
            if n["command"] == "sendNotification":
                out.append(_send_notification(n["params"], resolver, ctx, _PISTON.get("cur")))
                continue
            if n["command"] in ("sendPushNotification", "sendSMSNotification",
                                "deviceNotification"):
                out.append(_push_notification(n, resolver, ctx))
                continue
            if n["command"] in ("speak", "playText", "playTextAndResume", "playTextAndRestore"):
                out.append(_speak(n, resolver, ctx))
                continue
            if n["command"] in ("pausePiston", "resumePiston"):
                out.append(_piston_pause_resume(n, resolver, ctx))
                continue
            if n["command"] in ("flashLevel", "flashColor"):
                out.append(_flash(n, resolver, ctx))
                continue
            if n["command"] in ("fadeLevel", "fadeColorTemperature", "fadeHue", "fadeSaturation"):
                out.extend(_fade(n, resolver, ctx))
                continue
            if n["command"] == "setHSLColor":
                out.append(_set_hsl(n, resolver, ctx))
                continue
            if n["command"] == "sendEmail":
                out.append(_send_email(n, resolver, ctx))
                continue
            if n["command"] == "toggleLevel":
                out.append(_toggle_level(n, resolver, ctx))
                continue
            if n["command"] == "toggleRandom":
                out.append(_toggle_random(n, resolver, ctx))
                continue
            if n["command"] == "waitRandom":
                out.append(_wait_random(n, ctx))
                continue
            if n["command"] == "waitForTime":
                # "Wait until <time-of-day>" -> HA wait_for_trigger on a time
                # trigger, which resolves at the NEXT occurrence of that time
                # (within 24h) — exactly webCoRE's "wait until 11pm" semantics
                # (it waits for the next 11pm). A safety timeout is still emitted
                # per the standing hard rule (every wait carries timeout +
                # continue_on_timeout, HA_LIMITATIONS §9), sized past a full day
                # so the trigger always wins in practice, never truncating the
                # wait. A non-constant time (sunrise/variable/expression) routes
                # to PyScript rather than guessing.
                p0 = n["params"][0] if n["params"] else {}
                val = p0.get("c")
                if not isinstance(val, (int, float)) or isinstance(val, bool):
                    raise NotYetImplemented(
                        "waitForTime with a non-constant time (sunrise/variable) "
                        "requires PyScript", **ctx)
                out.append({"kind": "wait_for_time", "at": _minutes_hms(int(val))})
                continue
            if n["command"] == "wolRequest":
                # no device target at all — a pure data call. The service and
                # field names come from the vocab (VERIFIED against
                # home-assistant.io/actions/wake_on_lan.send_magic_packet/: mac
                # required, secure code optional 6-byte hex "00:aa:22:bb:33:cc").
                params = n["params"]
                mac = (params[0] or {}).get("c") if params else None
                if not isinstance(mac, str) or not mac.strip():
                    raise NotYetImplemented("wolRequest without a MAC address", **ctx)
                spec = resolver.command_ha_entry("wolRequest", ctx)
                field = {tok: name for name, tok in spec["data"].items()}
                data = {field["$1"]: _json_dumps(mac)}
                secure = (params[1] or {}).get("c") if len(params) > 1 else None
                if isinstance(secure, str) and secure.strip():
                    data[field["$2"]] = _json_dumps(secure)
                out.append({"kind": "service", "service": spec["service"],
                            "entities": [], "data": data})
                continue
            if not n["devices"] or n["command"] in _routing.piston_scope_commands():
                # piston-scope command (setVariable, log, setState, tiles, ...)
                # — piston state has no YAML equivalent, whatever devices the
                # surrounding action block targets.
                raise NotYetImplemented(
                    f"piston-scope command '{n['command']}' requires PyScript", **ctx)
            # A command this device doesn't offer as a webCoRE capability. The
            # vocab route cannot work — there's no binding to resolve — so if
            # the device's integration has a command passthrough, send it there.
            # That covers a command webCoRE never knew (allOff, playSound,
            # searchAmazonMusic) and one it knows but this device can't serve
            # (`take` on a camera arriving through a bridge).
            #
            # NOT gated on the `cm` flag: webCoRE sets it inconsistently — the
            # same driver command is flagged in one piston and not in another
            # (VERIFIED across the corpus), so it cannot be trusted to decide
            # this. "The device doesn't bind it" is the reliable signal.
            #
            # Where there's no passthrough, nothing changes: the clear
            # "no HA service mapping" error still comes out below.
            if not resolver.has_command_binding(n["devices"], n["command"], ctx) \
                    and resolver.passthrough(n["devices"], ctx):
                out.append(_driver_command(n, resolver, ctx))
                continue
            try:
                entities = resolver.entities_for_command(n["devices"], n["command"], ctx)
                service, data_spec = resolver.service_spec(n["command"], entities[0], ctx)
                data = None
                if data_spec:
                    # Inside the try on purpose: a data spec that can't be
                    # filled (`take` asks for a $1 the command has no
                    # parameter for) IS the "vocab mapping unusable here"
                    # signal, and the driver route is the right answer. A
                    # blank value raises PistonDefect instead, which this
                    # except deliberately does not catch.
                    data = {k: _param_value(v, n["params"], ctx)
                            for k, v in data_spec.items()}
            except NotYetImplemented:
                # The vocab claims to know this command but its mapping cannot
                # be used here — a broken data spec (`take` asks for a $1 the
                # command has no parameter for), or a service this device
                # can't take. If the integration has a command passthrough,
                # the device's own driver still knows the command, so send it
                # there rather than failing.
                if resolver.passthrough(n["devices"], ctx):
                    out.append(_driver_command(n, resolver, ctx))
                    continue
                raise
            # "is this the play-a-file service?" — the name it compares
            # against comes from the vocab, so an HA rename doesn't silently
            # stop media URLs being rewritten.
            if data and service == resolver.ha_spec("playTrack", ctx)["service"] \
                    and data.get("media_content_id"):
                data["media_content_id"] = _rewrite_media_url(
                    data["media_content_id"], resolver, ctx)
            out.append({"kind": "service", "service": service,
                        "entities": entities, "data": data})
        elif n["kind"] == "switch":
            # HA's choose: first matching branch wins, then the sequence exits
            # (HA_YAML_COMPILER_RESEARCH §2). Fall-through is refused upstream.
            lo = n["lo"]
            subject = _switch_subject(lo, resolver, ctx)
            options = []
            for case in n["cases"]:
                value = (case["ro"] or {}).get("c")
                options.append({
                    "conditions": [{"kind": "template", "template":
                                    "{{ " + subject + " == " + _lit(value) + " }}"}],
                    "sequence": _resolve_actions(case["body"], resolver, ctx)})
            out.append({"kind": "choose", "options": options,
                        "default": _resolve_actions(n["default"], resolver, ctx)})
        elif n["kind"] == "loop":
            node = {"kind": "repeat",
                    "body": _resolve_actions(n["body"], resolver, ctx)}
            if n.get("count") is not None:
                node["count"] = int(n["count"])
            elif n["conditions"]:
                key = "until" if n.get("until") else "while"
                node[key] = [_condition(c, resolver, ctx) for c in n["conditions"]]
            else:
                raise NotYetImplemented(
                    "loop with neither a count nor a condition", **ctx)
            out.append(node)
        elif n["kind"] == "stop":
            out.append({"kind": "stop"})
        elif n["kind"] == "foreach":
            # HA's repeat/for_each can iterate a list, but the loop VARIABLE here
            # is used as a device reference inside the body, which YAML can't
            # bind the way webCoRE does. PyScript does it naturally — route.
            raise NotYetImplemented(
                "for-each over a device list requires PyScript", **ctx)
        elif n["kind"] == "break":
            # HA's `stop` ends the whole sequence, not just the enclosing loop —
            # not the same thing. PyScript has a real `break`.
            raise NotYetImplemented(
                "break out of a loop requires PyScript", **ctx)
        elif n["kind"] == "if":
            out.append({"kind": "if",
                        "conditions": [_condition(c, resolver, ctx) for c in n["conditions"]],
                        "then": _resolve_actions(n["then"], resolver, ctx),
                        "else": _resolve_actions(n["else"], resolver, ctx)})
        else:
            raise NotYetImplemented(f"action node '{n['kind']}' not compiled yet", **ctx)
    return out


def _flash_delay_ms(op: dict, ctx: dict) -> int:
    """A flash half-duration -> whole milliseconds. Flashes run on sub-second
    times, so unlike the coarse _delay_hms (whole seconds, for `wait`) this
    keeps millisecond resolution — HA `delay:` takes a `milliseconds:` mapping."""
    op = op or {}
    n = op.get("c")
    if not isinstance(n, (int, float)) or isinstance(n, bool):
        raise NotYetImplemented("flash duration must be a fixed number", **ctx)
    unit = op.get("vt", "s")
    ms = {"ms": n, "s": n * 1000, "m": n * 60000, "h": n * 3600000}.get(unit, n * 1000)
    return int(ms)


def _duration_seconds(op: dict, ctx: dict, what: str = "duration"):
    """A duration operand -> seconds, for HA's `transition:` (fade time).
    transition takes a number of seconds and tolerates fractions."""
    op = op or {}
    n = op.get("c")
    if not isinstance(n, (int, float)) or isinstance(n, bool):
        raise NotYetImplemented(f"{what} must be a fixed number", **ctx)
    unit = op.get("vt", "s")
    secs = {"ms": n / 1000, "s": n, "m": n * 60, "h": n * 3600}.get(unit, n)
    return int(secs) if float(secs).is_integer() else round(secs, 3)


# fade<X> -> the base set<X> command whose service/data it ramps. HA
# `light.turn_on` carries a general `transition:` (seconds) that smoothly ramps
# ANY of its target attributes — brightness, color_temp, hs_color — so every
# fade is the same shape: the base command's data spec + transition. (The
# adjust<X> family is NOT here: only brightness has a native step field
# (brightness_step_pct); color-temp/hue/saturation adjust-by-delta has no
# confirmed HA field and stays research-gated.)
_FADE_BASE = {"fadeLevel": "setLevel", "fadeColorTemperature": "setColorTemperature",
              "fadeHue": "setHue", "fadeSaturation": "setSaturation"}


def _fade(n: dict, resolver: Resolver, ctx: dict) -> list:
    """fade<X> -> HA's native `transition:` ramp on light.turn_on. Params:
    [0] starting value (optional — omit to fade from the current value),
    [1] final value, [2] duration, [3] optional 'only if switch is …'. A
    starting value is set instantly first, then the fade to final runs over
    `transition`. Reuses the base set<X> service/data mapping (the vocab)
    so the attribute key + any transform stay data-driven."""
    cmd = n["command"]
    base = _FADE_BASE[cmd]
    params = n["params"]
    if len(params) < 3:
        raise NotYetImplemented(f"{cmd} needs a final value and a duration", **ctx)
    if len(params) > 3 and params[3] and (params[3] or {}).get("c") is not None:
        raise NotYetImplemented(
            f"{cmd} with an 'only if switch is …' guard is not compiled yet", **ctx)
    entities = resolver.entities_for_command(n["devices"], base, ctx)
    service, data_spec = resolver.service_spec(base, entities[0], ctx)
    if not data_spec:
        raise NotYetImplemented(f"{cmd}: '{base}' has no data mapping on this device", **ctx)
    nodes = []
    start = (params[0] or {}).get("c")
    if isinstance(start, (int, float)) and not isinstance(start, bool):
        nodes.append({"kind": "service", "service": service, "entities": entities,
                      "data": {k: _param_value(v, [params[0]], ctx) for k, v in data_spec.items()}})
    final = (params[1] or {}).get("c")
    if not isinstance(final, (int, float)) or isinstance(final, bool):
        raise NotYetImplemented(f"{cmd} with a non-constant final value", **ctx)
    data = {k: _param_value(v, [params[1]], ctx) for k, v in data_spec.items()}
    data["transition"] = _duration_seconds(params[2], ctx, "fade duration")
    nodes.append({"kind": "service", "service": service, "entities": entities, "data": data})
    return nodes


def _set_hsl(n: dict, resolver: Resolver, ctx: dict) -> dict:
    """setHSLColor -> HA `light.turn_on` with hs_color + brightness. webCoRE's
    hue/saturation are 0-100 (same convention as the hue_hs/sat_hs transforms
    the plain setHue/setSaturation use — HA hue is 0-360, so ×3.6; saturation
    stays 0-100), and its L is a brightness percent -> brightness_pct.
    Params: [0] hue, [1] saturation, [2] level, [3] optional 'only if switch'."""
    params = n["params"]
    if len(params) < 3:
        raise NotYetImplemented("setHSLColor needs hue, saturation and level", **ctx)
    if len(params) > 3 and params[3] and (params[3] or {}).get("c") is not None:
        raise NotYetImplemented(
            "setHSLColor with an 'only if switch is …' guard is not compiled yet", **ctx)
    entities = resolver.entities_for_command(n["devices"], "setColor", ctx)
    service, _ = resolver.service_spec("setColor", entities[0], ctx)

    def num(p, label):
        v = (p or {}).get("c")
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise NotYetImplemented(f"setHSLColor with a non-constant {label}", **ctx)
        return v

    hue, sat, level = num(params[0], "hue"), num(params[1], "saturation"), num(params[2], "level")
    # webCoRE hue is 0-100, HA's is 0-360 — the conversion is compiler work and
    # stays here. The two FIELD names it fills come from the vocab.
    colour_field, level_field = list(resolver.ha_spec("setHSLColor", ctx)["data"])
    data = {colour_field: _json_dumps([round(float(hue) * 3.6, 1), round(float(sat), 1)]),
            level_field: level}
    return {"kind": "service", "service": service, "entities": entities, "data": data}


def _toggle_level(n: dict, resolver: Resolver, ctx: dict) -> dict:
    """toggleLevel -> "toggle between 0% and N%": if the light is currently on,
    turn it off; else set it to N%. A STATEFUL toggle, so it reads the light's
    own current on/off state in an inline template condition — self-contained
    (survives PistonCore removal, reads only HA's own state)."""
    params = n["params"]
    level = (params[0] or {}).get("c") if params else None
    if not isinstance(level, (int, float)) or isinstance(level, bool):
        raise NotYetImplemented("toggleLevel with a non-constant level", **ctx)
    ents = resolver.entities_for_command(n["devices"], "setLevel", ctx)
    off_service, _ = resolver.service_spec("off", ents[0], ctx)
    on_service, data_spec = resolver.service_spec("setLevel", ents[0], ctx)
    on_data = {k: _param_value(v, [params[0]], ctx) for k, v in (data_spec or {}).items()}
    cond = {"kind": "template", "template": "{{ is_state('" + ents[0] + "', 'on') }}"}
    return {"kind": "if", "conditions": [cond],
            "then": [{"kind": "service", "service": off_service, "entities": ents, "data": None}],
            "else": [{"kind": "service", "service": on_service, "entities": ents, "data": on_data}]}


def _toggle_random(n: dict, resolver: Resolver, ctx: dict) -> dict:
    """toggleRandom -> "random toggle with P% probability for on": pick on with
    probability P, off otherwise. HA has no random-set service, so a template
    condition rolls the die (range(1,101)|random <= P) at RUN time — computed
    per fire, not fixed at compile, which is the point of a random toggle."""
    params = n["params"]
    prob = (params[0] or {}).get("c") if params else None
    if not isinstance(prob, (int, float)) or isinstance(prob, bool):
        raise NotYetImplemented("toggleRandom with a non-constant probability", **ctx)
    on_ents = resolver.entities_for_command(n["devices"], "on", ctx)
    off_ents = resolver.entities_for_command(n["devices"], "off", ctx)
    on_service, _ = resolver.service_spec("on", on_ents[0], ctx)
    off_service, _ = resolver.service_spec("off", off_ents[0], ctx)
    cond = {"kind": "template",
            "template": "{{ range(1, 101) | random <= " + str(int(prob)) + " }}"}
    return {"kind": "if", "conditions": [cond],
            "then": [{"kind": "service", "service": on_service, "entities": on_ents, "data": None}],
            "else": [{"kind": "service", "service": off_service, "entities": off_ents, "data": None}]}


def _wait_random(n: dict, ctx: dict) -> dict:
    """waitRandom -> "wait randomly between A and B": a delay whose seconds are
    rolled at RUN time (range(min, max+1)|random), which is what a random wait
    means — a fixed compile-time pick would defeat it. HA `delay:` renders its
    seconds from a template."""
    params = n["params"]
    if len(params) < 2:
        raise NotYetImplemented("waitRandom needs a minimum and a maximum duration", **ctx)
    lo = _duration_seconds(params[0], ctx, "minimum wait")
    hi = _duration_seconds(params[1], ctx, "maximum wait")
    lo_i, hi_i = int(lo), int(hi)
    if hi_i < lo_i:
        lo_i, hi_i = hi_i, lo_i
    expr = "{{ range(" + str(lo_i) + ", " + str(hi_i + 1) + ") | random }}"
    return {"kind": "delay", "delay_seconds": expr}


def _flash(n: dict, resolver: Resolver, ctx: dict) -> dict:
    """flashLevel/flashColor -> a counted `repeat:` alternating two light states.

    HA's own light `flash:` param is only `short`/`long` — a fixed
    notification blink with no count and no custom levels/colors (VERIFIED,
    home-assistant.io/actions/light.turn_on/), so webCoRE's "flash A for t1 /
    B for t2, N times" has no single-call equivalent. The faithful
    reproduction is a counted repeat whose body sets state A, waits, sets
    state B, waits — the exact shape of HA's own flashing-light example in the
    scripts docs.

    Params (vocab): [0] level/color A, [1] duration A, [2] level/color B,
    [3] duration B, [4] flash count, [5] optional "only if switch is on/off".
    The level/color halves reuse the SAME setLevel/setColor service+data spec
    the plain commands compile through (the vocab), so an edit to
    those maps carries into flash for free.

    Deliberately does NOT restore prior state afterward (leaves the light in
    state B): HA has no auto-restore, and a scene snapshot/restore around the
    block would make the compiled automation carry hidden state — documented
    in the help file, not silently approximated."""
    params = n["params"]
    if len(params) < 5:
        raise NotYetImplemented(
            f"{n['command']} needs five parameters (two states, two durations, "
            f"a count)", **ctx)
    base = "setLevel" if n["command"] == "flashLevel" else "setColor"
    entities = resolver.entities_for_command(n["devices"], base, ctx)
    service, data_spec = resolver.service_spec(base, entities[0], ctx)
    if not data_spec:
        raise NotYetImplemented(
            f"{n['command']}: '{base}' has no data mapping on this device", **ctx)
    raw_count = (params[4] or {}).get("c")
    try:
        count = int(float(raw_count))
    except (TypeError, ValueError):
        raise NotYetImplemented(f"{n['command']} with a non-constant flash count", **ctx)
    if params[5] and (params[5] or {}).get("c") is not None:
        # "only if switch is on/off" gate — deliberately unhandled for now
        # rather than silently dropped; it needs a condition wrapping the whole
        # repeat, and no corpus piston exercises it. Honest NYI (routes to
        # PyScript), never a quiet omission of the guard.
        raise NotYetImplemented(
            f"{n['command']} with an 'only if switch is …' guard is not compiled "
            f"yet", **ctx)

    def half(value_param, dur_param):
        data = {k: _param_value(v, [value_param], ctx) for k, v in data_spec.items()}
        return [
            {"kind": "service", "service": service, "entities": entities, "data": data},
            {"kind": "delay", "delay_ms": _flash_delay_ms(dur_param, ctx)},
        ]

    body = half(params[0], params[1]) + half(params[2], params[3])
    return {"kind": "repeat", "count": count, "body": body}


def _driver_command(n: dict, resolver: Resolver, ctx: dict) -> dict:
    """A DRIVER command — a task naming something only the device's own driver
    knows (`clearImages`, `take`, `selectLiveview`). webCoRE offered it because
    the hub advertised it; Home Assistant has no vocabulary for it.

    Routed through the integration's own command passthrough, detected by shape
    from the service registry (device_pipeline.detect_passthroughs): a bridged
    device goes via `hubitat.send_command`, a `remote.` entity via the CORE
    `remote.send_command` (which is how Harmony activities work for everyone),
    a vacuum via `vacuum.send_command`.

    VERIFIED WORKING 2026-07-29 on Jeremy's real hardware: `take` through
    hubitat.send_command produced a picture and populated the camera's image
    attribute.

    KNOWN LIMITATION, deliberately accepted (Jeremy 2026-07-29 — "we can only do
    so much"): a passthrough accepts any command name and fails at RUNTIME, not
    at compile. A command the driver doesn't have will silently do nothing. The
    name came from the device's own advertised list when the piston was written,
    so it is right for the device it was authored against — but a device swapped
    for a different model will fail quietly. Documented in HA_LIMITATIONS."""
    command = n["command"]
    spec = resolver.passthrough(n["devices"], ctx)
    if not spec:
        raise NotYetImplemented(
            f"'{command}' is a command only the device's own driver knows, and "
            f"this device's integration offers no way to pass one through — "
            f"there is no Home Assistant equivalent to compile it to", **ctx)

    data = {spec["command_field"]: _json_dumps(command)}
    if spec.get("target_field"):
        data[spec["target_field"]] = _json_dumps(spec["entity_id"])
    args = [p for p in (n.get("params") or [])
            if (p or {}).get("c") not in (None, "")]
    if args:
        if not spec.get("args_field"):
            raise NotYetImplemented(
                f"'{command}' was given values, but "
                f"{spec['service']} takes no arguments field", **ctx)
        values = [(p or {}).get("c") for p in args]
        data[spec["args_field"]] = _json_dumps(
            values[0] if len(values) == 1 else values)
    return {"kind": "service", "service": spec["service"],
            "entities": [], "data": data}


def _custom_service(n: dict, resolver: Resolver, ctx: dict) -> dict:
    """A CUSTOM (`cm`) task — an HA service the editor offered directly.

    webCoRE has always let a hub advertise commands its own dictionary doesn't
    know (Hubitat driver commands); PistonCore uses the same door to offer HA
    services (piston.module.js:2840). The command name IS the service, so
    there is nothing to translate — no vocab entry, no mapping table.

    PARAMETERS ARE NOT SUPPORTED YET and that is deliberate. webCoRE stores
    task parameters POSITIONALLY, with no field names, and resolves them
    against the command's parameter list. For a vocab command that is safe
    because the list is frozen; for an HA service the list is live, so a field
    added by an HA update would shift positions and land a value in the wrong
    field silently. The fix is a per-service record of the advertised field
    order (decided 2026-07-27, unbuilt). Until then a parameterised custom
    command fails LOUDLY here rather than compiling to something wrong."""
    service = n["command"]
    if "." not in service:
        return _driver_command(n, resolver, ctx)
    domain = service.split(".", 1)[0]
    entities = resolver.entities_for_domain(n["devices"], domain, ctx)
    params = n.get("params") or []
    if not params:
        return {"kind": "service", "service": service, "entities": entities, "data": None}

    # Parameters are matched back to FIELD NAMES from the order recorded when
    # the piston was saved, never by counting along today's field list — that
    # list is live and filtered, so counting would put values in the wrong
    # fields after any HA change (storage.record_ha_field_order).
    order = resolver.field_order(n["devices"], service, ctx)
    if order is None:
        raise NotYetImplemented(
            f"'{service}' has parameters but PistonCore has no record of which "
            f"fields the editor offered for it — open the piston and save it "
            f"again so the field names are recorded, then recompile", **ctx)
    if len(params) > len(order):
        raise NotYetImplemented(
            f"'{service}' was saved with {len(params)} values but only "
            f"{len(order)} fields are recorded for it — open the piston, check "
            f"the command's values, and save it again", **ctx)

    data = {}
    for index, param in enumerate(params):
        value = (param or {}).get("c")
        if value is None:
            value = (param or {}).get("s")
        if value is None or value == "":
            continue                      # an untouched optional box
        data[order[index]] = _json_dumps(value) if isinstance(value, str) else value
    return {"kind": "service", "service": service, "entities": entities,
            "data": data or None}


def _piston_pause_resume(n: dict, resolver: Resolver, ctx: dict) -> dict:
    """pausePiston/resumePiston target ANOTHER piston by reference (webCoRE's
    "piston" param type — same colon-wrapped id convention the PyScript band's
    executePiston already assumes, emit_pyscript.py "target.strip(':')").
    Native pause/resume IS automation.turn_off/turn_on (the native-pause
    decision — file stays, only the automation's enabled state changes).

    The wrinkle this needs to solve: one piston can compile to SEVERAL
    automations (one per top-level if — TCP scoping, COMPILER_SPEC §2.5 point
    4), so "pause piston X" isn't a single entity_id. The target list is read
    from piston X's own last recorded auto_ids (deploy.py's compile-status
    store — a legitimate compile-time lookup, same class as the device
    resolution map) and matched at HA's OWN runtime by the STABLE `id:`
    attribute every compiled automation carries — never by entity_id, which
    isn't deterministic from the id alone (HA derives it from the alias,
    de-duplicated on collision; that's why deploy.py's own _automation_entities
    matches the same way instead of guessing the slug)."""
    params = n["params"]
    target = (params[0] or {}).get("c") if params else None
    if not isinstance(target, str) or not target.strip(":"):
        raise NotYetImplemented(f"{n['command']} without a piston target", **ctx)
    target_id = target.strip(":")
    from .deploy import load_statuses
    rec = load_statuses().get(target_id)
    if not rec:
        raise NotYetImplemented(
            f"{n['command']} targets a piston (id {target_id}) that hasn't been "
            f"compiled/deployed yet — deploy it first, then this piston", **ctx)
    auto_ids = rec.get("auto_ids") or []
    if not auto_ids:
        raise NotYetImplemented(
            f"{n['command']} targets a piston (id {target_id}) that compiled to "
            f"a script, not an automation — scripts have no enabled/disabled "
            f"state to pause", **ctx)
    # pausePiston and resumePiston each carry their own HA name in the vocab,
    # so picking one is just a lookup on the command already in hand.
    service = resolver.command_ha_entry(n["command"], ctx)["service"]
    # single-quoted Python/Jinja list literal, not _json_dumps — the whole
    # expression gets wrapped in DOUBLE quotes by the template (matching every
    # other value_template in this codebase), so nothing inside may use them.
    id_list = "[" + ", ".join(repr(str(i)) for i in auto_ids) + "]"
    template = ("{{ states.automation | selectattr('attributes.id', 'in', "
                + id_list + ") | map(attribute='entity_id') | list }}")
    return {"kind": "service", "service": service, "target_template": template, "data": None}


def _set_variable(n: dict, resolver: Resolver, ctx: dict) -> dict:
    """setVariable -> HA's `variables:` action (docs /docs/scripts/, Variables).

    FIDELITY LIMIT, deliberate: HA sequence variables live for ONE run, while
    webCoRE piston variables persist between runs. That difference only bites
    when a piston READS the variable it is writing (an accumulator such as
    `count = count + 1`), so that exact shape is detected and routed to
    PyScript, where the value genuinely persists. Everything else — compute a
    value, use it later in the same run, which is the common case — is
    expressed natively here."""
    params = n["params"]
    p0 = params[0] if params else {}
    name = p0.get("x") or p0.get("c")
    if not name or str(name).startswith("@"):
        raise NotYetImplemented(
            "setting a global variable needs PyScript (its value lives in a "
            "pyscript entity so other pistons can read it)", **ctx)
    if p0.get("xi"):
        raise NotYetImplemented("setting one element of an array needs PyScript", **ctx)
    value_op = params[1] if len(params) > 1 else {"t": "c", "c": ""}
    source = str(value_op.get("e") or value_op.get("x") or "")
    # only a WHOLE-WORD self-reference means an accumulator (count = count+1);
    # word boundaries stop `count` matching inside `mycount`/`count2`,
    # which would over-route unrelated pistons (review 2026-07-20).
    if re.search(r"\b" + re.escape(str(name)) + r"\b", source):
        raise NotYetImplemented(
            f"'{name}' is built from its own previous value, which only "
            f"persists between runs under PyScript", **ctx)
    return {"kind": "variables",
            "vars": {str(name): _text_param(value_op, resolver, ctx)}}


def _send_email(n: dict, resolver: Resolver, ctx: dict) -> dict:
    """sendEmail -> HA notify.send_message against the configured email notifier.

    The Hubitat model (Jeremy 2026-07-24): the EMAIL INTEGRATION is set up in HA
    (the 2026.7+ SMTP config-flow integration creates a notify.<name> entity),
    not in PistonCore — sendEmail just routes through it, exactly as it "shows
    up" in webCoRE once the email app exists. VERIFIED (HA SMTP docs, 2026.7.3):
    notify.send_message with target.entity_id = the notifier entity, data
    {title, message}, and a per-call data.target overriding the recipient — the
    same stable-target-reference shape (C1/C2) as the push/SMS notify work.

    The notifier entity is resolved from $system['email'], which the shim binds
    to the user's email notifier. Unset -> a clear, actionable error (never a
    guess about WHICH notify entity is email — HA can't distinguish an SMTP
    notifier from a Telegram/Slack one at the entity level, so that binding is
    a deliberate selection, not an auto-guess).

    Params (vocab): [0] recipient, [1] subject, [2] message body."""
    entity = resolver.system_entity("email")
    if not entity:
        raise NotYetImplemented(
            "Send email needs an email notifier — set up an email integration in "
            "HA (e.g. the SMTP integration, which creates a notify entity) and "
            "select it as PistonCore's email notifier", **ctx)
    params = n["params"]
    piston = n.get("_piston")
    # field names by the webCoRE param they carry ($1 recipient, $2 subject,
    # $3 body); which ones get sent is compiler logic and stays here.
    spec = resolver.ha_spec("sendEmail", ctx)
    field = {tok: name for name, tok in spec["data"].items()}
    body = params[2] if len(params) > 2 else {}
    data = {field["$3"]: _text_param(body or {}, resolver, ctx, piston)}
    subject = params[1] if len(params) > 1 else None
    if subject and (subject or {}).get("c") not in (None, ""):
        data[field["$2"]] = _text_param(subject, resolver, ctx, piston)
    recipient = params[0] if len(params) > 0 else None
    if recipient and (recipient or {}).get("c") not in (None, ""):
        # per-call recipient override; a single address as a scalar is valid,
        # HA also accepts a list.
        data[field["$1"]] = _text_param(recipient, resolver, ctx, piston)
    return {"kind": "service", "service": spec["service"],
            "entities": [entity], "data": data}


def _text_param(op: dict, resolver: Resolver, ctx: dict, piston: dict | None = None) -> str:
    """A user-facing text parameter (notification body, spoken message) as a
    YAML scalar. Constants pass through; anything computed goes through the
    Jinja backend so the YAML band can express it natively instead of routing
    the whole piston to PyScript. Unsupported expressions raise
    NotYetImplemented and the dispatcher falls back, exactly as before."""
    import json as _json
    piston = piston if piston is not None else _PISTON.get("cur")
    if op.get("t") == "c":
        text = op.get("c")
        if isinstance(text, str) and "{" in text:
            jt = _jinja(resolver, ctx, piston)
            # a bare {{ }} is a YAML flow mapping — templates must be quoted
            return _json.dumps("{{ " + jt.transpile_string(text) + " }}")
        return _json.dumps("" if text is None else str(text))
    jt = _jinja(resolver, ctx, piston)
    if op.get("t") == "u":
        # raw user-entered expression text; the trailing ';' is editor noise
        op = {"e": str(op.get("u", "")).rstrip("; ")}
    return _json.dumps("{{ " + jt.transpile_operand(op) + " }}")


def _mode_entity(resolver: Resolver) -> str:
    """The helper entity standing in for webCoRE's location mode, named in the
    vocab under virtualDevices.mode — HA has no location mode of its own."""
    return resolver.virtual_device_ha("mode").get("entity")


def _jinja(resolver: Resolver, ctx: dict, piston: dict | None) -> JinjaTranspiler:
    locals_ = set(getattr(resolver, "local_var_names", set()) or set())
    arrays = {v.get("n") for v in (piston or {}).get("v", [])
              if str(v.get("t", "")).endswith("]")}
    return JinjaTranspiler(locals_, resolver.globals_map, resolver, ctx,
                           _mode_entity(resolver), array_vars=arrays)


def _push_notification(n: dict, resolver: Resolver, ctx: dict) -> dict:
    """Push / SMS / device notification -> HA notify. webCoRE's push went to
    the SmartThings/Hubitat app; HA's equivalent is the notify service (the
    companion app registers itself there). notify.notify fans out to every
    configured notifier — the honest general mapping. deviceNotification on a
    media_player is a spoken message, so that routes to Speak instead."""
    import json as _json
    if n["command"] == "deviceNotification" and resolver.speaker_targets(n["devices"], ctx):
        return _speak(n, resolver, ctx)
    p0 = n["params"][0] if n["params"] else {}
    spec = resolver.ha_spec(n["command"], ctx)
    return {"kind": "service", "service": spec["service"], "entities": [],
            "data": {next(iter(spec["data"])):
                     _text_param(p0, resolver, ctx, n.get("_piston"))}}


def _speak(n: dict, resolver: Resolver, ctx: dict) -> dict:
    """SPEAK_ACTION_SPEC §5.4: tts.speak — target = the engine entity (global
    setting / sole engine), media players + message + cache in data. Constant
    messages only on this band; computed messages route to PyScript."""
    import json as _json
    engine = resolver.system_entity("tts")
    if not engine:
        raise NotYetImplemented(
            "Speak needs a TTS engine — pick one in PistonCore Settings "
            "(several tts.* engines exist in HA)", **ctx)
    if not n["devices"]:
        raise NotYetImplemented("Speak with no speaker devices", **ctx)
    players = resolver.entities_for_command(n["devices"], n["command"], ctx)
    p0 = n["params"][0] if n["params"] else {}
    # $target = the speakers the piston picked, $1 = the message. Anything else
    # in the vocab's data is a literal. Field NAMES come from the vocab; which
    # value belongs in each is the compiler's business.
    spec = resolver.ha_spec(n["command"], ctx)
    slots = {"$target": players,
             "$1": _text_param(p0, resolver, ctx, n.get("_piston"))}
    data = {k: slots.get(v, "true" if v is True else v)
            for k, v in spec["data"].items()}
    return {"kind": "service", "service": spec["service"], "entities": [engine],
            "data": data}


def _send_notification(params: list, resolver: Resolver, ctx: dict,
                       piston: dict | None = None) -> dict:
    """webCoRE 'Send notification' == Hubitat's in-app notification, not push
    — HA's exact equivalent is the notifications panel (persistent
    notification), which exists in every HA with zero setup
    (NOTIFY_ACTION_SPEC: notify.persistent_notification). Push
    (sendPushNotification) stays NotYetImplemented until real mobile targets
    exist. Message must be a constant — expressions need the expression
    engine."""
    import json as _json
    p = params[0] if params else {}
    spec = resolver.ha_spec("sendNotification", ctx)
    return {"kind": "service", "service": spec["service"],
            "entities": [],
            "data": {next(iter(spec["data"])):
                     _text_param(p, resolver, ctx, piston)}}


def _lit(value) -> str:
    """A webCoRE case value as a Jinja literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _switch_subject(lo: dict, resolver: Resolver, ctx: dict) -> str:
    """The value a switch statement compares its cases against."""
    t = lo.get("t")
    if t == "p" and lo.get("d"):
        entities = resolver.entities_for_attr(lo["d"], lo.get("a"), ctx)
        return "states('" + entities[0] + "')"
    if t == "x" and lo.get("x") == "$currentEventDevice":
        return "trigger.entity_id"
    if t == "v":
        sysent = resolver.system_entity(lo.get("v"))
        if sysent:
            return "states('" + sysent + "')"
    if t == "c":
        return _lit(lo.get("c"))
    raise NotYetImplemented(
        f"switch on operand type '{t}' not compiled yet", **ctx)


def _param_value(token: str, params: list, ctx: dict):
    """$1/$2 (+|transform) tokens from the vocab's data specs."""
    raw = str(token)
    transform = None
    if "|" in raw:
        raw, tname = raw.split("|", 1)
        transform = _PARAM_TRANSFORMS.get(tname)
        if transform is None:
            raise NotYetImplemented(f"unknown command param transform '{tname}'", **ctx)
    if raw.startswith("$"):
        idx = int(raw[1:]) - 1
        if idx >= len(params):
            raise NotYetImplemented(f"command param {raw} missing", **ctx)
        prm = params[idx]
        value = prm.get("c") if prm.get("c") is not None else prm.get("s")
    else:
        value = raw
    return transform(value) if transform else value


# ── branch emission ─────────────────────────────────────────────────────────

def _emit_branch(br: dict, resolver: Resolver, piston_id: str, piston_name: str,
                 blocks: list, auto_ids: list) -> None:
    ctx = {"piston_id": piston_id, "piston_name": piston_name, "stmt_id": br["stmt_id"]}
    has_wait = _has_wait(br["then"]) or _has_wait(br["else"])
    trig_id = "fire" if has_wait else None

    triggers = []
    cancel_triggers = []
    conditions = []
    direction_conds = []

    if br["kind"] == "timer":
        t = dict(br["timer"])
        t["id"] = trig_id
        triggers.append(t)
    else:
        for trig in br["triggers"]:
            node = _trigger(trig, resolver, ctx, trig_id)
            triggers.append(node)
            edge = _boundary_trigger(trig, resolver, ctx, trig_id)
            if edge:
                triggers.append(edge)   # the "or equal to" edge; see _boundary_trigger
            dc = _direction_condition(trig, ctx)
            if dc:
                # the bare-direction trigger above wakes on ANY change; this
                # gates on the actual direction, same as every other
                # trigger-classified node's filter (to:/above:/below:) does
                # inherently — rises/drops just has no filter to encode it in.
                direction_conds.append(dc)
            if has_wait and br["tcp"] == "c" and node["kind"] == "state" and node.get("to"):
                opposite = resolver.opposite_state(node["to"])
                if opposite is not None:
                    cancel_triggers.append({"kind": "state", "entities": node["entities"],
                                            "to": opposite, "id": "tcp_cancel",
                                            **({"attribute": node["attribute"]} if node.get("attribute") else {})})
        if not triggers:
            # condition-only statement -> promote (subscription equivalence)
            for cond in br["conditions"]:
                node = _promote(cond, resolver, ctx, trig_id)
                if node:
                    triggers.append(node)
                    edge = _boundary_trigger(cond, resolver, ctx, trig_id)
                    if edge:
                        triggers.append(edge)   # the "or equal to" edge
            if not triggers:
                # nothing here can wake the piston: it is a runnable sequence,
                # not an automation. Signal the script path.
                raise _NoSubscriptions()

    if cancel_triggers:
        conditions.append({"kind": "trigger", "id": "fire"})

    # RESTRICTIONS ("only when ...") gate the whole statement, ELSE INCLUDED, so
    # they belong at AUTOMATION-condition level — never folded in with the
    # branch's own conditions, which move inside the if/else action below. If a
    # restriction fails the automation simply does not run: no then, no else.
    # (analyze._restriction_nodes carries the full reasoning.)
    for r in br.get("restrictions") or []:
        conditions.append(_condition(r, resolver, ctx))

    cond_nodes = [_condition(c, resolver, ctx) for c in br["conditions"]] + direction_conds
    then_actions = _resolve_actions(br["then"], resolver, ctx)
    else_actions = _resolve_actions(br["else"], resolver, ctx)

    if else_actions:
        # EXPLICIT trigger-classified nodes (ct:"t" straight from the JSON —
        # the shim stamps this on almost every real save, so this is the
        # COMMON case, unlike the promoted-only fix below which only covers
        # triggerless pistons). br["triggers"] here is still the raw IR
        # (_cond_node shape), never the built HA node — that's exactly what
        # _recheck_condition/_OPPOSITE_TRIGGER_OP need. See their docstrings
        # for why both a re-check and a mirrored wake are required.
        for trig in br["triggers"]:
            rc = _recheck_condition(trig, resolver, ctx)
            if rc:
                cond_nodes.append(rc)
            opp_co = _OPPOSITE_TRIGGER_OP.get(trig.get("co"))
            if opp_co:
                triggers.append(_trigger(dict(trig, co=opp_co), resolver, ctx, trig_id))

    if else_actions and cond_nodes:
        # else must NOT run on a cancel-trigger pass, so the template
        # conditions move inside an if-action; only the trigger gate stays
        # at automation level.
        #
        # A directional numeric/state trigger (below:N / above:N, to:X / from:X —
        # promoted OR explicit, same shape either way) only wakes on ONE crossing,
        # so the else could never run — webCoRE instead subscribes to the ATTRIBUTE
        # and re-decides on ANY change, both directions. The compiler honors the
        # else by emitting the OPPOSITE-direction trigger itself (Jeremy 2026-07-22:
        # the user writes one if/else; the compiler keeps the promise — never a
        # hand-written second if). The inner if/else below then re-evaluates on
        # each wake and routes then vs else correctly.
        for node in list(triggers):
            kind = node.get("kind")
            if kind == "numeric_state":
                # level comparison (temp/humidity/battery/lux/... any sensor):
                # below:N wakes on the down-crossing, add above:N for the up.
                # `attribute` rides along: the opposite-direction twin has to
                # watch the same field, or the else wakes on the entity's
                # state instead of the reading it was written about.
                if "below" in node and "above" not in node:
                    triggers.append({"kind": "numeric_state", "entities": node["entities"],
                                     "above": node["below"], "id": node.get("id"),
                                     **({"attribute": node["attribute"]} if node.get("attribute") else {})})
                elif "above" in node and "below" not in node:
                    triggers.append({"kind": "numeric_state", "entities": node["entities"],
                                     "below": node["above"], "id": node.get("id"),
                                     **({"attribute": node["attribute"]} if node.get("attribute") else {})})
            elif kind == "state" and (node.get("to") is not None or node.get("from") is not None):
                # equality/change trigger (switch, contact, presence, lock, mode)
                # with an ELSE: webCoRE subscribes to the whole ATTRIBUTE and
                # re-decides on ANY change. A to:X + from:X pair only catches
                # transitions involving X — correct for a binary attribute, but
                # for a multi-value attribute a change between two OTHER values
                # never wakes it and the else silently can't run. So collapse to
                # ONE bare any-change state trigger (drop to/from); the re-check
                # condition (cond_nodes) then routes then vs else on every change.
                # YAML-FIRST: this is fully faithful in YAML — no PyScript needed
                # (that's the whole point; PyScript is the valve, not the answer).
                node.pop("to", None)
                node.pop("from", None)
        actions = [{"kind": "if", "conditions": cond_nodes,
                    "then": then_actions, "else": else_actions}]
    elif else_actions:
        # Trigger-only if WITH an else: webCoRE subscribes to the ATTRIBUTE,
        # so the opposite transition wakes the piston and runs the else —
        # a to:-filtered trigger can't express that (semantic-audit find,
        # 2026-07-19). PyScript band handles it faithfully.
        raise NotYetImplemented(
            "else-branch on a trigger-only if needs any-change wake — "
            "requires PyScript", **ctx)
    else:
        conditions.extend(cond_nodes)
        actions = then_actions

    # De-dup triggers: collapsing to bare any-change (else path) can produce
    # identical triggers when two conditions target the same entity — one wake
    # is enough, the re-check decides.
    all_triggers = []
    seen = set()
    for t in triggers + cancel_triggers:
        key = _json_dumps(t)
        if key not in seen:
            seen.add(key)
            all_triggers.append(t)

    auto_id = f"pistoncore_{piston_id}_s{br['stmt_id']}"
    auto_ids.append(auto_id)
    block = _env.get_template("automation.yaml.j2").render(
        auto_id=auto_id,
        alias=f"PistonCore: {piston_name} — ${br['stmt_id']}",
        mode="restart" if br["tcp"] == "c" else "queued",
        triggers=all_triggers,
        conditions=conditions,
        actions=actions,
    )
    blocks.append(block)

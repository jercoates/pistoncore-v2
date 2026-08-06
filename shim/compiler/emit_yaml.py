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
from .errors import CompilerError, NotYetImplemented, PistonDefect
from .expression import _EQUALITY_OPS, _NUMERIC_OPS, JinjaTranspiler
from .resolve import (Resolver, WAS_TO_IS, WAS_SENTINEL,
                      was_watcher_entity, last_changed_is_exact,
                      duration_seconds)
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
# When not None, compile_yaml uses this INSTEAD of reading settings from
# disk. Only tests set it — it keeps emitted output independent of the
# machine running them.
_MEDIA_CFG_OVERRIDE: dict | None = None
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
# Transforms that need the whole PARAMETER, not just its value — a duration
# carries its unit in `vt` alongside the number in `c`, so the value alone
# cannot be converted.
_WHOLE_PARAM_TRANSFORMS = {"duration_secs"}


def _duration_secs_param(prm: dict):
    """A webCoRE duration parameter as whole seconds.

    HA expresses a fade as `transition:` in seconds, so this is the bridge from
    "2 minutes" as the editor stores it. The SERVICE and the FIELD NAME live in
    webcore_vocab.json where they can be edited; only this arithmetic — which
    is webCoRE's side of the conversion and does not move when HA changes —
    stays here.
    """
    secs = _duration_secs(prm if isinstance(prm, dict) else {})
    if secs is None:
        raise PistonDefect(
            "a fade/duration parameter has no fixed value — set it in the "
            "editor, or remove the command")
    return secs


_PARAM_TRANSFORMS = {"duration_secs": _duration_secs_param,
                     "hex_rgb": _hex_rgb,
                     "pct_float": _rescaled("pct_float"),
                     "hue_hs": lambda v: [_rescaled("hue_hs")(v), 100],
                     "sat_hs": lambda v: [0, _rescaled("sat_hs")(v)],
                     "hvac_mode": _mode_value("hvac_mode"),
                     "fan_mode": _mode_value("fan_mode"),
                     "speed_pct": _mode_value("fan_speed")}


def _delay_hms(params: list) -> str:
    """A `wait` command's duration parameter as HH:MM:SS.

    Reads the shared duration converter rather than keeping its own unit table
    — this one used to be a second copy that was missing "d" (days), so a wait
    authored in days silently became that many SECONDS.
    """
    return _duration_hms(params[0] if params else {}) or "00:00:00"


def _minutes_hms(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}:00"


def _duration_secs(op) -> int | None:
    """The shared converter — see resolve.duration_seconds."""
    return duration_seconds(op)


def _duration_hms(op) -> str | None:
    """Same operand as HH:MM:SS, which is what HA's `for:` takes."""
    secs = _duration_secs(op)
    if secs is None:
        return None
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
    # _MEDIA_CFG_OVERRIDE lets a caller pin the media config instead of
    # reading this machine's settings. The snapshot harness needs it: it was
    # setting _MEDIA_CFG = {} before each compile, and this line silently
    # overwrote that, so emitted output depended on whoever ran the tests.
    # Caught 2026-07-30 when a snapshot picked up a real installation's proxy
    # address and signing signature and was about to be committed as test
    # data — someone else's setup baked into the repo (Jeremy: "hard coding
    # to my setup only is a bug").
    if _MEDIA_CFG_OVERRIDE is not None:
        _MEDIA_CFG = dict(_MEDIA_CFG_OVERRIDE)
    else:
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

    # webCoRE's hasTriggers is per PISTON (:8771-8772, :9296). If anything in
    # this piston subscribes, the whole piston runs on that event and nothing
    # is promoted — so it compiles to ONE automation, not one per statement.
    # Read from the IR, not re-derived here — analyze() owns this fact.
    piston_has_triggers = bool(branches and branches[0].get("piston_has_triggers"))
    collect: list | None = [] if piston_has_triggers else None
    try:
        for br in branches:
            _emit_branch(br, resolver, piston_id, piston_name, blocks, auto_ids,
                         collect=collect, piston_has_triggers=piston_has_triggers)
        if collect is not None:
            _merge_branches(collect, piston_id, piston_name, blocks, auto_ids)
        # After the branches, because a was_* watcher is only known once the
        # condition that needs it has been built.
        _was_watcher_blocks(resolver, piston_id, piston_name, blocks, auto_ids)
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
            "auto_ids": auto_ids, "media_warnings": resolver.media_warnings,
            "helpers": _helpers_for(resolver, piston_id, piston_name)}


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
    # NOT a ctx key: ctx is splatted into CompilerError, so anything added
    # there has to be a field it accepts.
    resolver.script_band = True
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
            "unresolved": resolver.unresolved, "media_warnings": resolver.media_warnings,
            "warnings": resolver.warnings,
            "helpers": _helpers_for(resolver, piston_id, piston_name)}


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


def _was_condition(cond: dict, resolver: Resolver, ctx: dict) -> dict:
    """`was_X for T` -> "X is true now, and has been for at least/less than T".

    HA cannot look backwards: the `numeric_state` condition takes no `for:`,
    and `last_changed` resets on EVERY update, so a sensor reporting while it
    stays below its threshold would never accumulate and the answer would be
    permanently false. Instead a helper records WHEN the inner test became
    true — maintained by the watcher automation in _was_watcher_blocks — and
    the elapsed time is read from that.
    """
    inner = _condition(dict(cond, co=WAS_TO_IS[cond["co"]], duration={}),
                       resolver, ctx)
    secs = _duration_secs(cond.get("duration"))
    if not secs or not cond.get("devices"):
        # webCoRE's own threshold of 0 makes this the instantaneous test, and a
        # left side with no device has no history to look back through.
        return inner
    if getattr(resolver, "script_band", False):
        # A subscription-less piston compiles to a SCRIPT, and deploy writes
        # exactly one file per piston — so there is nowhere to put the watcher
        # AUTOMATION this needs. Emitting the helper without its watcher would
        # leave the helper permanently at its sentinel and the condition
        # permanently false: silently broken, which is worse than not
        # compiling. PyScript owns its whole file and has no such limit.
        raise NotYetImplemented(
            f"'{cond['co']}' needs to track how long a condition has held, "
            f"which requires a companion automation this piston has no file "
            f"for — needs PyScript", **ctx)
    if inner.get("kind") != "template":
        raise NotYetImplemented(
            f"'{cond['co']}' wraps a comparison that isn't a plain template "
            f"({inner.get('kind')}), so its 'has held for' test can't be "
            f"built — needs PyScript", **ctx)

    entities = resolver.entities_for_attr(cond["devices"], cond["attr"], ctx)
    entity = was_watcher_entity(ctx.get("piston_id") or "", entities,
                                cond.get("attr"), cond["co"],
                                cond.get("value"), cond.get("value2"))
    store = getattr(resolver, "was_watchers", None)
    if store is None:
        store = {}
        setattr(resolver, "was_watchers", store)
    store.setdefault(entity, {"entity": entity, "entities": entities,
                              "attr": cond.get("attr"),
                              "template": inner["template"]})

    # 'g' = "for at least T" (the default), 'l' = "for less than T"
    # — webcore-piston.groovy:8288, `fisg ? duration>=threshold : duration<threshold`.
    op = "<" if str((cond.get("duration") or {}).get("f") or "g") == "l" else ">="
    held = (f"states('{entity}') not in ['unknown', 'unavailable', "
            f"'{WAS_SENTINEL}'] and "
            f"as_timestamp(now()) - as_timestamp(states('{entity}'), 0) "
            f"{op} {secs}")
    return {"kind": "and", "conditions": [
        inner,
        {"kind": "template", "template": "{{ " + held + " }}"},
    ]}


def _condition(cond: dict, resolver: Resolver, ctx: dict) -> dict:
    """Condition IR node -> template/time/sun condition dict for the template."""
    co = cond["co"]

    # ── the was_* family ── handled AHEAD of every other dispatch, because
    # was_* is not a family of comparisons: it WRAPS one. The inner test can be
    # any ordinary comparison, and only the "has held for T" part is special.
    if co in WAS_TO_IS and not last_changed_is_exact(cond):
        return _was_condition(cond, resolver, ctx)

    # nested condition group -> HA's and/or condition blocks
    if co == "_group":
        kids = [_condition(c, resolver, ctx) for c in cond["children"]]
        return {"kind": "or" if cond["group_op"] == "or" else "and",
                "conditions": kids}

    # A piston VARIABLE on the left ("Motion_Triggered is true"). The variable
    # is carried as an automation-level `variables:` entry, so the template
    # reads it by name. Without this the whole comparison rendered as "{{ () }}".
    if cond.get("lo_type") == "x" and cond.get("lo_var_name"):
        name = cond["lo_var_name"]
        value = cond.get("value")
        # A helper-backed variable is READ from its entity, not from a YAML
        # `variables:` block that the writing automation never shared with
        # this one (stage 3b). This is what makes the manual-override pattern
        # work across separate automations.
        hread = helper_read_expr(name, resolver, ctx.get("piston_id") or "")
        if hread is not None:
            op = _EQUALITY_OPS.get(co) or _NUMERIC_OPS.get(co)
            if op is None:
                raise NotYetImplemented(
                    f"comparison '{co}' on a variable is not compiled yet", **ctx)
            spec = resolver.helper_vars.get(str(name)) or {}
            if str(spec.get("type", "")).rstrip("[]") == "boolean":
                # the read is already a boolean test; compare against the
                # webCoRE word rather than HA's on/off
                want = str(value).strip().lower() == "true"
                if op == "!=":
                    want = not want
                return {"kind": "template",
                        "template": "{{ " + (hread if want
                                             else f"not {hread}") + " }}"}
            if _num_str(value):
                return {"kind": "template",
                        "template": "{{ " + _num_cmp(hread, op, value) + " }}"}
            return {"kind": "template",
                    "template": "{{ " + f"{hread} {op} {str(value)!r}" + " }}"}
        op = _EQUALITY_OPS.get(co) or _NUMERIC_OPS.get(co)
        if op is None:
            raise NotYetImplemented(
                f"comparison '{co}' on a variable is not compiled yet", **ctx)
        if _num_str(value):
            return {"kind": "template",
                    "template": "{{ " + _num_cmp(name, op, value) + " }}"}
        # The COMPARISON must match how the value was WRITTEN (_typed_literal).
        # Stage 2 made a boolean a real boolean, so comparing it to the string
        # 'true' is always false — fix both halves or neither.
        declared = getattr(resolver, "local_var_decls", {}).get(str(name))
        lit = _typed_literal({"t": "c", "c": value}, declared)
        if lit is not None:
            return {"kind": "template",
                    "template": "{{ " + f"{name} {op} {lit}" + " }}"}
        # single quotes: the template itself is emitted inside a DOUBLE-quoted
        # YAML scalar, so a double-quoted value here produces invalid YAML.
        return {"kind": "template",
                "template": "{{ " + f"{name} {op} {str(value)!r}" + " }}"}

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


# How long a quarantined `remains_*` automation stays busy after a run, which
# is what drops the flood from a fast driver. One second is the deliberate
# default: an MQTT sensor reporting many times a second collapses to one run,
# and nothing observable is lost because a `remains_*` action re-asserts
# something that is already true. Rendered by the template as a plain HA delay
# so it stays editable in the emitted YAML.
# TODO: promote to a Settings knob (all first-run settings must be editable
# there too) — COMPILER_TODO.md.
_NOISY_THROTTLE = "00:00:01"

_REMAIN_ABOVE = ("remains_above", "remains_above_or_equal_to",
                 "stays_greater_than", "stays_greater_than_or_equal_to")
_REMAIN_BELOW = ("remains_below", "remains_below_or_equal_to",
                 "stays_less_than", "stays_less_than_or_equal_to")

# Every "was and still is" operator, across all three families that have one.
# Their crossing twins — enters_range, exits_range, becomes_even, becomes_odd —
# are deliberately absent: a crossing is exactly what HA triggers do natively,
# so those are already correct and cheap.
_HELD_OPS = _REMAIN_ABOVE + _REMAIN_BELOW + (
    "remains_inside_of_range", "stays_inside_of_range",
    "remains_outside_of_range", "stays_outside_of_range",
    "remains_even", "stays_even", "remains_odd", "stays_odd",
)


def _is_noisy_trigger(trig: dict) -> bool:
    """A trigger that must wake on EVERY change of the value it watches.

    Only the "was and still is" family, and only when authored WITHOUT a
    duration. With one it compiles to a native trigger plus `for:` — fires
    once, silent — so `stays_*` (which declares a duration in the vocab) is
    normally not noisy at all. This is the small remainder that is.
    """
    return (trig.get("co") in _HELD_OPS
            and not _duration_hms(trig.get("duration")))


def _noisy_state_trigger(entities, trig_id) -> dict:
    """The wake for a held comparison authored without a duration.

    "Was and still is" needs the OLD and the NEW value (webcore-piston.groovy
    :8461), and every native HA trigger fires on the TRANSITION into a state —
    which is the one case these operators exclude. So there is nothing to
    subscribe to but the change itself; the value test moves to the re-check
    condition, and the cost of waking constantly is paid for by the quarantine
    and throttle in _merge_branches.
    """
    return {"kind": "state", "entities": entities, "id": trig_id,
            "_noisy": True}


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
        if co != "enters_range" and not hold:
            # Held, but no duration: "was inside and still is", which is NOT
            # the entering that numeric_state fires on. Same split as the
            # numeric family below.
            return _noisy_state_trigger(entities, trig_id)
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
        if co != "exits_range" and not hold:
            # A template trigger fires on its result going false->true, which
            # is the LEAVING — the one case "was outside and still is"
            # excludes. Same split as the numeric family.
            return _noisy_state_trigger(entities, trig_id)
        joiner = " and " if trig.get("aggregation") == "all" else " or "
        parts = [_num_between(e, value, trig.get("value2"), negate=True) for e in entities]
        body = parts[0] if len(parts) == 1 else "(" + joiner.join(parts) + ")"
        node = {"kind": "template", "template": "{{ " + body + " }}", "id": trig_id}
        if hold and co != "exits_range":
            node["for"] = hold
        return node
    # "remains above N for T" -> numeric_state with `for:` (HA native)
    if co in _REMAIN_ABOVE or co in _REMAIN_BELOW:
        key = "above" if co in _REMAIN_ABOVE else "below"
        if hold:
            return {"kind": "numeric_state", "entities": entities,
                    key: value, "for": hold, "id": trig_id}
        # WITHOUT a duration this is webCoRE's "was and still is": the engine
        # requires the OLD and the NEW value to satisfy it
        # (webcore-piston.groovy:8461), which is the opposite of the crossing
        # `numeric_state` fires on — the crossing is the one case it excludes.
        # No HA trigger expresses that, so wake on any change and let the
        # re-check condition below decide. That firing rate is why the owning
        # statement is quarantined and throttled in _merge_branches.
        return _noisy_state_trigger(entities, trig_id)

    # ── parity family ── (becomes_even/odd = edge into that parity;
    # remains_even/odd, stays_even/odd = same edge held for a duration —
    # PyScript treats stays_* as a synonym of remains_*, emit_pyscript.py:535)
    PARITY = ("becomes_even", "becomes_odd", "remains_even", "remains_odd",
              "stays_even", "stays_odd")
    if co in PARITY:
        if co not in ("becomes_even", "becomes_odd") and not hold:
            # "was even and still is" — not the becoming that a template
            # trigger's false->true fires on. Same split as the numeric family.
            return _noisy_state_trigger(entities, trig_id)
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
    # HELD comparisons with the same edge. These were missed when the boundary
    # fix went in for `is_<=`: without them `stays_less_than` and
    # `stays_less_than_or_equal_to` emit IDENTICAL code, so the "or equal to"
    # is silently lost and a value sitting exactly on N never triggers.
    "stays_less_than_or_equal_to", "stays_greater_than_or_equal_to",
    "remains_below_or_equal_to", "remains_above_or_equal_to",
    "was_less_than_or_equal_to", "was_greater_than_or_equal_to",
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
    # Nothing to subscribe to: a virtual device (time/date), a piston VARIABLE,
    # or any operand that resolved to no devices at all. Promoting one of these
    # produced `entity_id:` null, which Home Assistant rejects outright.
    if cond.get("lo_type") in ("v", "x") or not cond.get("devices"):
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

def _has_wait(nodes) -> bool:
    """Does anything in here wait?

    Walks the WHOLE subtree, not just if/then/else. A wait hiding in a loop
    body, a switch case, or a condition's attached actions still needs its own
    cancellation scope — missing one puts a statement into the merged
    automation where an unrelated trigger can restart it and kill the wait.
    Two pistons slipped through when this only recursed into `if`."""
    if isinstance(nodes, dict):
        if (nodes.get("kind") == "task"
                and nodes.get("command") in ("wait", "waitForTime", "waitRandom")):
            return True
        return any(_has_wait(v) for k, v in nodes.items()
                   if k in ("then", "else", "body", "conditions", "children",
                            "cases", "default", "true_actions", "false_actions"))
    if isinstance(nodes, list):
        return any(_has_wait(n) for n in nodes)
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
            if n["command"] == "cancelPendingTasks":
                # Scope:enum[Local,Global] (webcore.groovy:2827). LOCAL is this
                # piston's own pending work, which is this run — `stop:` ends
                # it, same as cancelTasks. GLOBAL reaches OTHER pistons, and
                # one automation cannot halt another's in-flight run, so that
                # scope is refused loudly rather than silently doing the local
                # thing and looking like it worked.
                scope = ((n.get("params") or [{}])[0] or {}).get("c")
                if str(scope or "Local").strip().lower() == "global":
                    raise NotYetImplemented(
                        "cancelPendingTasks with GLOBAL scope stops tasks in "
                        "OTHER pistons, which one automation cannot do to "
                        "another", **ctx)
                out.append({"kind": "stop", "reason": "cancelPendingTasks"})
                continue
            if n["command"] == "cancelTasks":
                # "Cancel all pending tasks" — vcmd_cancelTasks sets
                # cancellations[ALL]=true (webcore-piston.groovy:7321), and
                # Jeremy describes the effect as "stops the automation at that
                # line". Everything still pending in this run IS this run, so
                # HA's `stop:` expresses it exactly. YAML can do this reliably,
                # so it stays in YAML.
                #
                # It was previously a silent no-op on the claim that
                # mode: restart covers it. It does not — restart only fires on
                # RE-TRIGGER, while this cancels on demand mid-run.
                out.append({"kind": "stop", "reason": "cancelTasks"})
                continue

            # Commands that compile to NOTHING. Which ones those are is
            # DATA — `"ha": "noop"` in the vocab, with the reason in its note —
            # not a list of names in here. The names were hardcoded, which is
            # the same duplicate-source problem as everything else: the vocab
            # is where "this command has no HA action" belongs, and a user can
            # add one without touching the compiler.
            if resolver.command_is_noop(n["command"]):
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
                # `fade_from` is the vocab saying "this command may jump to a
                # starting value before it fades". HA cannot express a start
                # and an end in one turn_on, so it becomes a second call placed
                # ahead of the fade. Declared in the vocab rather than a list
                # of command names in here, so a user adding a fade for another
                # attribute gets the behaviour without touching Python.
                # READ, never popped: service_spec hands back the vocab's own
                # dict, cached for the whole process — mutating it would strip
                # fade_from for every piston compiled after this one.
                fade_from = (data_spec or {}).get("fade_from")
                data_spec = {k: v for k, v in (data_spec or {}).items()
                             if k != "fade_from"}
                data = None
                if data_spec:
                    # Inside the try on purpose: a data spec that can't be
                    # filled (`take` asks for a $1 the command has no
                    # parameter for) IS the "vocab mapping unusable here"
                    # signal, and the driver route is the right answer. A
                    # blank value raises PistonDefect instead, which this
                    # except deliberately does not catch.
                    data = _spec_data(data_spec, n["params"], ctx, resolver,
                                      entities[0] if entities else None)
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
            if fade_from and data:
                # The target field is whatever the fade sets — everything in
                # the spec except the transition. Jump there instantly (no
                # transition key at all), then let the fade below run.
                start = _param_value(fade_from, n["params"], ctx, resolver,
                                     entities[0] if entities else None)
                if start is not _UNSET_PARAM:
                    out.append({"kind": "service", "service": service,
                                "entities": entities,
                                "data": {k: start for k in data
                                         if k != "transition"}})
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
            # The accumulate-and-announce shape resolves to ONE template
            # (accumulate.j2). Anything else routes to PyScript.
            node = _accumulate_loop(n, resolver, ctx)
            if node is None:
                raise NotYetImplemented(
                    "for-each over a device list requires PyScript", **ctx)
            out.append(node)
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
                      "data": _spec_data(data_spec, [params[0]], ctx, resolver)})
    final = (params[1] or {}).get("c")
    if not isinstance(final, (int, float)) or isinstance(final, bool):
        raise NotYetImplemented(f"{cmd} with a non-constant final value", **ctx)
    data = _spec_data(data_spec, [params[1]], ctx, resolver)
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
    on_data = _spec_data(data_spec, [params[0]], ctx, resolver)
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
        data = _spec_data(data_spec, [value_param], ctx, resolver)
        return [
            {"kind": "service", "service": service, "entities": entities, "data": data},
            {"kind": "delay", "delay_ms": _flash_delay_ms(dur_param, ctx)},
        ]

    body = half(params[0], params[1]) + half(params[2], params[3])
    return {"kind": "repeat", "count": count, "body": body}


def _passthrough_arg(value, spec: dict, command: str = "",
                     resolver: "Resolver | None" = None, ctx: dict | None = None):
    """A value on its way through an integration's command passthrough.

    Most passthroughs take their arguments in the service payload and the
    value goes through untouched.

    Hubitat's Maker API is a GET whose URL PATH holds the argument, so a
    value containing "/" is read as further URL segments and 404s. Percent-
    encoding it fixes that, and Hubitat DECODES it before handing it on.

    PROVEN END TO END on Jeremy's hardware, 2026-07-30, playing a real file
    from a live share to a Sonos that can play files:
        raw      -> HTTP 404 "Not Found"
        encoded  -> HTTP 200, status "playing", and the speaker reported
                    uri: x-file-cifs://192.168.1.10/Hubitat/HoistTheColours.mp3
                    i.e. correctly UNescaped by Hubitat on the way through.

    A cautionary note for anyone changing this: the same pair was tested
    earlier against a different speaker and "proved" the opposite — encoded
    was accepted and silent, which looked like the encoding arriving
    unescaped. That speaker was a gen 1 Sonos Amp which cannot play file
    URIs at all, so the test could not have succeeded by any route. The
    conclusion was drawn anyway and was wrong. Test device capability
    before drawing conclusions about transport.

    Only for a passthrough that says it needs it (detect_passthroughs sets
    encode_args) — remote./vacuum.send_command take their arguments in the
    service payload, where encoding would corrupt them."""
    # A share URL going to a DRIVER command gets the same media treatment a
    # vocab Play track does. It didn't before (found 2026-07-30): the rewrite
    # was wired only into the vocab path, so a speaker with no controllable
    # entity — Jeremy's Hubitat-bridged Sonos — sent the raw x-file-cifs://
    # URL no matter what the media server was set to. Turning the media
    # server on appeared to do nothing.
    if isinstance(value, str) and value.startswith(("x-file-cifs://", "smb://")) \
            and resolver is not None:
        value = _rewrite_media_url(value, resolver, ctx or {})
    if not spec.get("encode_args") or not isinstance(value, str) or "/" not in value:
        return value
    from urllib.parse import quote
    return quote(value, safe=":")


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
        values = [_passthrough_arg(p.get("c"), spec, command, resolver, ctx) for p in args]
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
    template = _env.get_template("piston_automations.j2").render(
        auto_ids=[str(i) for i in auto_ids]).strip()
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
    # Helper-backed variables are written through their entity so the value
    # survives to the other automations that read it (stage 3b).
    hw = _helper_write(name, value_op, resolver, ctx,
                       ctx.get("piston_id") or "")
    if hw is not None:
        return hw
    # Honour the declared type for constants — see _typed_literal.
    declared = getattr(resolver, "local_var_decls", {}).get(str(name))
    literal = _typed_literal(value_op, declared)
    if literal is not None:
        return {"kind": "variables", "vars": {str(name): literal}}
    return {"kind": "variables",
            "vars": {str(name): _text_param(value_op, resolver, ctx)}}



def _typed_literal(value_op: dict, declared: dict | None):
    """The declared-type constant as a YAML/Jinja literal (`true`, `90`).

    The DECISION is resolve.typed_value — shared with the PyScript band. Only
    the FORMATTING is here, because the two bands spell literals differently."""
    from .resolve import typed_value
    val = typed_value(value_op, declared)
    if val is None:
        return None
    if isinstance(val, bool):
        return "true" if val else "false"
    return repr(val)


def _helper_write(name: str, value_op: dict, resolver: Resolver, ctx: dict,
                  piston_id: str):
    """setVariable on a helper-backed variable -> a service call on the helper.

    Returns None when this variable is not helper-backed, so the caller falls
    through to the ordinary YAML `variables:` path."""
    from .resolve import helper_entity_id
    spec = getattr(resolver, "helper_vars", {}).get(str(name))
    if not spec:
        return None
    entity = helper_entity_id(piston_id, name, spec["type"])
    if entity is None:
        return None
    domain = entity.split(".", 1)[0]
    declared = getattr(resolver, "local_var_decls", {}).get(str(name))
    literal = _typed_literal(value_op, declared)

    if domain == "input_boolean":
        # A constant we can read now picks the service outright; anything
        # computed needs the value at runtime, which input_boolean cannot take
        # — so choose between the two services with a condition instead.
        if literal in ("true", "false"):
            return {"kind": "service",
                    "service": f"input_boolean.turn_{'on' if literal == 'true' else 'off'}",
                    "entities": [entity]}
        expr = _text_param(value_op, resolver, ctx)
        return {"kind": "if",
                "conditions": [{"kind": "template",
                                "template": "{{ " + _json_loads_inner(expr) + " }}"}],
                "then": [{"kind": "service", "service": "input_boolean.turn_on",
                          "entities": [entity]}],
                "else": [{"kind": "service", "service": "input_boolean.turn_off",
                          "entities": [entity]}]}

    service = ("input_number.set_value" if domain == "input_number"
               else "input_datetime.set_datetime" if domain == "input_datetime"
               else "input_text.set_value")
    field = ("value" if domain in ("input_number", "input_text")
             else "datetime")
    val = literal if literal is not None else _text_param(value_op, resolver, ctx)
    return {"kind": "service", "service": service, "entities": [entity],
            "data": {field: val}}


def _json_loads_inner(quoted: str) -> str:
    """_text_param returns a JSON-quoted scalar or a quoted "{{ ... }}".
    Strip back to the bare expression for embedding in a condition."""
    import json as _j
    try:
        raw = _j.loads(quoted)
    except Exception:                                          # noqa: BLE001
        return str(quoted)
    raw = str(raw).strip()
    if raw.startswith("{{") and raw.endswith("}}"):
        return raw[2:-2].strip()
    return _j.dumps(raw)


def helper_read_expr(name: str, resolver: Resolver, piston_id: str):
    """Jinja that reads a helper-backed variable, or None if not helper-backed."""
    from .resolve import helper_entity_id
    spec = getattr(resolver, "helper_vars", {}).get(str(name))
    if not spec:
        return None
    entity = helper_entity_id(piston_id, name, spec["type"])
    if entity is None:
        return None
    domain = entity.split(".", 1)[0]
    if domain == "input_boolean":
        return f"is_state('{entity}', 'on')"
    if domain == "input_number":
        return f"states('{entity}') | float(0)"
    return f"states('{entity}')"


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


# An operand the editor never filled in: no type, no value. Distinct from an
# operand that IS set but empty, which stays a PistonDefect.
_UNSET_PARAM = object()


# Transform names that are SCALE conversions (vocab _value_maps.scales), i.e.
# the ones with a runtime template twin. The rest (colour packing, mode maps)
# need a literal and still say so.
_SCALE_TRANSFORMS = {"pct_float", "hue_hs", "sat_hs"}


def _spec_data(data_spec: dict, params: list, ctx: dict,
               resolver=None, entity: str | None = None) -> dict:
    """Build a service-data dict from the vocab spec, DROPPING any key whose
    parameter the piston left unset — webCoRE just doesn't apply an optional
    parameter, so neither should the emitted call."""
    out = {}
    for k, v in (data_spec or {}).items():
        val = _param_value(v, params, ctx, resolver, entity)
        if val is not _UNSET_PARAM:
            out[k] = val
    return out


def _param_value(token: str, params: list, ctx: dict, resolver=None,
                 entity: str | None = None):
    """$1/$2 (+|transform) tokens from the vocab's data specs."""
    raw = str(token)
    transform = None
    tname = None
    if "|" in raw:
        raw, tname = raw.split("|", 1)
        transform = _PARAM_TRANSFORMS.get(tname)
        if transform is None:
            raise NotYetImplemented(f"unknown command param transform '{tname}'", **ctx)
    # $object_id / $entity_id — the DEVICE this command is aimed at, for specs
    # that need to build a path or an id rather than take a piston parameter.
    # webCoRE's `take` has NO parameters, so a snapshot filename cannot come
    # from one; it has to be derived from the camera. Keeping the PATH in the
    # vocab and only the substitution here is the split the moving-target rule
    # asks for (MEDIA_FILES_SPEC §2.3 fixes the filename per camera).
    if entity and ("$object_id" in raw or "$entity_id" in raw):
        # SUBSTITUTED, not matched: the token is embedded in a longer string
        # (a path), so an equality test never fires.
        return (raw.replace("$object_id", entity.split(".", 1)[1])
                   .replace("$entity_id", entity))
    if raw.startswith("$") and "$object_id" not in raw and "$entity_id" not in raw:
        idx = int(raw[1:]) - 1
        if idx >= len(params):
            raise NotYetImplemented(f"command param {raw} missing", **ctx)
        prm = params[idx]
        # UNSET optional parameter: the editor writes an operand with no type
        # and no value when the user leaves the field alone. Omit the key.
        if (not prm.get("t") and prm.get("c") is None and prm.get("s") is None
                and not prm.get("e") and not prm.get("x")):
            return _UNSET_PARAM
        # A parameter whose value is a VARIABLE or an EXPRESSION rather than a
        # literal. Emit a template so the value — and any scale conversion —
        # resolves at runtime. Reading only `c`/`s` made a volume set from a
        # declared variable arrive as None and blow up the whole piston.
        if prm.get("t") in ("x", "e") and (prm.get("x") or prm.get("e")):
            if resolver is None:
                raise NotYetImplemented(
                    "a variable command parameter needs the resolver", **ctx)
            jt = _jinja(resolver, ctx, _PISTON.get("cur"))
            inner = jt.transpile_operand(prm)
            if tname in _SCALE_TRANSFORMS:
                from .resolve import rescale_template
                inner = rescale_template(tname, inner)
            elif transform is not None:
                raise NotYetImplemented(
                    f"a '{tname}' parameter given as a variable is not "
                    f"compiled yet", **ctx)
            return _json_dumps("{{ " + inner + " }}")
        if tname in _WHOLE_PARAM_TRANSFORMS:
            return transform(prm)
        value = prm.get("c") if prm.get("c") is not None else prm.get("s")
    else:
        value = raw
    return transform(value) if transform else value


# ── branch emission ─────────────────────────────────────────────────────────

def _was_watcher_blocks(resolver: Resolver, piston_id: str, piston_name: str,
                        blocks: list, auto_ids: list) -> None:
    """One small automation per `was_*` comparison, keeping its helper current.

    It records WHEN the inner test became true, and clears the helper the
    moment it stops being true — so the elapsed time read in _was_condition is
    always "how long this has held continuously", which is what webCoRE
    accumulates by walking state history.

    The triggers are TEMPLATE triggers on the predicate and its negation. A
    template trigger fires when its result goes false->true, so these fire only
    on the two flips — not on every update of the underlying sensor. That is
    what keeps the watcher cheap enough to exist per comparison.
    """
    for w in sorted((getattr(resolver, "was_watchers", {}) or {}).values(),
                    key=lambda x: x["entity"]):
        inner = w["template"].strip()
        body = inner[2:-2].strip() if inner.startswith("{{") else inner
        auto_id = f"pistoncore_{piston_id}_watch_{w['entity'].split('_')[-1]}"
        auto_ids.append(auto_id)
        blocks.append(_env.get_template("was_watcher.yaml.j2").render(
            auto_id=auto_id,
            alias=f"PistonCore: {piston_name} — tracks how long a condition holds",
            entity=w["entity"],
            predicate="{{ " + body + " }}",
            negated="{{ not (" + body + ") }}",
            sentinel=WAS_SENTINEL,
        ))


def _helpers_for(resolver: Resolver, piston_id: str, piston_name: str) -> list:
    """The helper entities this piston's variables need (stage 3a/3b).

    Reported in the compile result so DEPLOY can create them — the compiler
    stays read-only and never touches Home Assistant itself (locked policy §1)."""
    from .resolve import helper_entity_id
    out = []
    for name, spec in (getattr(resolver, "helper_vars", {}) or {}).items():
        entity = helper_entity_id(piston_id, name, spec["type"])
        if entity:
            out.append({"entity": entity, "variable": name,
                        "type": spec["type"],
                        "name": f"{piston_name}: {name}"})
    # was_* watchers need a helper too, created the same way and reported
    # through the same list so DEPLOY has one thing to create and one thing to
    # clean up when the piston is deleted.
    for w in (getattr(resolver, "was_watchers", {}) or {}).values():
        out.append({"entity": w["entity"], "type": "datetime",
                    "name": f"{piston_name}: since '{w['attr']}' condition held"})
    return sorted(out, key=lambda h: h["entity"])


def _has_attached(conds: list) -> bool:
    """True when any condition in the tree hangs statements off itself."""
    for c in conds or []:
        if c.get("true_actions") or c.get("false_actions"):
            return True
        if _has_attached(c.get("children") or []):
            return True
    return False


def _attached_chain(conds: list, then_actions: list, else_actions: list,
                    resolver: Resolver, ctx: dict) -> list:
    """webCoRE's evaluation order as a nested HA if-chain.

    Attached statements CANNOT live at automation-condition level: HA's
    `conditions:` block is a pure test with no way to call a service partway
    through deciding. So the whole test moves into the actions block, and each
    condition's attached statements run at the point that condition is
    evaluated — BEFORE the owning if's body, which is where webCoRE runs them
    (VERIFIED webcore-piston.groovy:7882-7886).

    SHORT-CIRCUIT is preserved by NESTING rather than listing: in "A and B",
    B's test — and so B's attached statements — sits inside A's true branch, so
    a false A means B never runs (:7452-7456)."""
    if not conds:
        return then_actions
    head, rest = conds[0], conds[1:]
    ts = _resolve_actions(head.get("true_actions") or [], resolver, ctx)
    fs = _resolve_actions(head.get("false_actions") or [], resolver, ctx)
    inner = _attached_chain(rest, then_actions, else_actions, resolver, ctx)
    return [{"kind": "if",
             "conditions": [_condition(head, resolver, ctx)],
             "then": ts + inner,
             "else": fs + else_actions}]


def _assert_no_orphan_attached(br: dict, handled: bool, ctx: dict) -> None:
    """Refuse to emit if anything carrying attached statements went unhandled.

    Attached statements can hang off a TRIGGER, off a condition nested in a
    GROUP, or off a condition inside a nested if — each would sail through
    emitting nothing, which is the exact failure being fixed. Silence is the
    bug; never soften this to a pass."""
    def scan(node) -> bool:
        if isinstance(node, list):
            return any(scan(x) for x in node)
        if not isinstance(node, dict):
            return False
        if node.get("true_actions") or node.get("false_actions"):
            return True
        return any(scan(v) for k, v in node.items()
                   if k in ("children", "conditions", "then", "else",
                            "cases", "body", "default"))

    unhandled = scan(br.get("triggers") or [])
    unhandled = scan(br.get("then") or []) or unhandled
    unhandled = scan(br.get("else") or []) or unhandled
    if handled:
        for c in br.get("conditions") or []:
            unhandled = scan(c.get("children") or []) or unhandled
    else:
        unhandled = scan(br.get("conditions") or []) or unhandled
    if unhandled:
        raise NotYetImplemented(
            "actions are attached to a condition in a place the YAML band "
            "cannot express (a trigger, a condition group, or a nested if)",
            **ctx)


def _finish_branch(br: dict, conditions: list, triggers: list,
                   cancel_triggers: list, actions: list, piston_id: str,
                   piston_name: str, blocks: list, auto_ids: list) -> None:
    """De-dup the wakes and render the automation block."""
    all_triggers = []
    seen = set()
    for t in triggers + cancel_triggers:
        key = _json_dumps(t)
        if key not in seen:
            seen.add(key)
            all_triggers.append(t)
    auto_id = f"pistoncore_{piston_id}_s{br['stmt_id']}"
    auto_ids.append(auto_id)
    blocks.append(_env.get_template("automation.yaml.j2").render(
        auto_id=auto_id,
        alias=f"PistonCore: {piston_name} — ${br['stmt_id']}",
        mode="restart" if br["tcp"] == "c" else "queued",
        triggers=all_triggers,
        conditions=conditions,
        actions=actions,
    ))


def _accumulate_loop(n: dict, resolver: Resolver, ctx: dict):
    """`each device: if <test>: X = X + <text>` -> ONE HA template.

    Transliterating the loop means unrolling it once per device — 61 copies for
    a whole-house battery report. This is an INTENT-based compiler, and HA's
    own documented answer is a single template (namespace + for + join), so
    that is what gets emitted. The HA-facing shape lives in accumulate.j2, not
    here, so a user can fix it when HA moves.

    Returns a `variables` action node, or None when the shape isn't recognised
    — the caller routes to PyScript rather than guessing.

    Detection is the SELF-REFERENCING assignment (`X = X + …`): 9-of-9 across
    the corpus, no false positives. Keying on notify/speak was tested and is
    wrong both ways (32 pistons notify without this; one real case never does)."""
    body = n.get("body") or []
    if len(body) != 1:
        return None
    inner = body[0]
    test_cond, tasks = None, None
    if inner.get("kind") == "if":
        conds = inner.get("conditions") or []
        if len(conds) != 1 or conds[0].get("co") == "_group":
            return None
        test_cond = conds[0]
        tasks = (test_cond.get("true_actions") or []) + (inner.get("then") or [])
    elif inner.get("kind") == "task":
        tasks = [inner]
    else:
        return None

    setvars = [t for t in tasks or []
               if t.get("kind") == "task" and t.get("command") == "setVariable"]
    if len(setvars) != 1:
        return None
    params = setvars[0].get("params") or []
    if len(params) < 2:
        return None
    var = params[0].get("x") or params[0].get("c")
    src = params[1]
    if not var or not isinstance(src.get("e"), str):
        return None
    if not re.search(r"\b" + re.escape(str(var)) + r"\b", src["e"]):
        return None

    attr = (test_cond or {}).get("attr")
    if not attr:
        m = re.search(r"\[\s*\$device\s*:\s*([A-Za-z_][\w]*)\s*\]", src["e"])
        attr = m.group(1) if m else None
    if not attr:
        return None
    # Resolution failures mean "not the shape we recognise", not "broken
    # piston" — return None so the caller can route, never escape.
    try:
        hashes = []
        for dref in n.get("devices") or []:
            hashes.extend(resolver._hashes(str(dref), ctx))
        if not hashes:
            return None
        entities = []
        for h in hashes:
            ents = resolver.entities_for_attr([h], attr, ctx)
            if len(ents) != 1:
                return None
            entities.append(ents[0])
    except CompilerError:
        return None

    sample = entities[0]
    shape = resolver.read_expr(sample, attr)
    for ent in entities[1:]:
        if resolver.read_expr(ent, attr) != shape.replace(f"'{sample}'", f"'{ent}'"):
            return None

    loopvar = "_pc_dev"
    jt = _jinja(resolver, ctx, _PISTON.get("cur"))
    jt.loop_entity, jt.loop_sample = loopvar, sample
    try:
        text = jt.transpile_operand({"e": _strip_accumulator(src["e"], var)})
        test = None
        if test_cond is not None:
            # CANONICAL operator tables and comparison builder — never a local
            # copy. A hand-written subset here missed `is`/`is_not`, the
            # commonest shape in a safety piston, and lost _num_cmp's
            # fail-closed guard.
            co = test_cond.get("co")
            num_op, enum_op = _NUMERIC_OPS.get(co), _EQUALITY_OPS.get(co)
            value = test_cond.get("value")
            if (num_op is None and enum_op is None) or value is None:
                return None
            reading = shape.replace(f"'{sample}'", loopvar)
            if enum_op is not None:
                mapped = resolver.ha_state_value(attr, value)
                test = f"{reading} {enum_op} {_json_dumps(str(mapped))}"
            else:
                test = _num_cmp(reading, num_op, value)
    except CompilerError:
        return None
    finally:
        jt.loop_entity = jt.loop_sample = None

    rendered = _env.get_template("accumulate.j2").render(
        var=var, loopvar=loopvar, entities=repr(entities),
        test=test, text=text, joiner=repr(""))
    return {"kind": "variables", "vars": {str(var): _json_dumps(rendered.strip())}}


def _strip_accumulator(expr: str, var: str) -> str:
    """`X = X + <text>` carries the variable at the front; the loop template
    re-adds the prior value, so emit only the appended part."""
    stripped = re.sub(r"^\s*" + re.escape(var) + r"\b", "", expr, count=1)
    return stripped.strip() or '""'


def _merge_branches(parts: list, piston_id: str, piston_name: str,
                    blocks: list, auto_ids: list) -> None:
    """Statements -> automations, grouped so CANCELLATION stays per-statement.

    webCoRE runs every statement on every piston event, so each automation
    subscribes to the UNION of the piston's triggers and each statement's body
    sits behind its own gate.

    But a statement carrying a WAIT keeps its own automation. `mode: restart`
    cancels a whole in-flight run, and webCoRE cancels a statement's pending
    tasks only when THAT statement's condition changes — so putting two waits,
    or a wait and an unrelated trigger, in one automation lets one cancel the
    other. That is the "run-on sentence" piston failure (Jeremy, 2026-08-03:
    a floor-wide piston where hall motion must not cancel a pending kitchen
    timer).

    Statements without waits have nothing to cancel, so they merge freely.
    """
    # A NOISY trigger is deliberately kept OUT of the shared union. Every
    # automation subscribes to that union, so letting one in would wake the
    # whole piston on every sensor update — the exact harm the quarantine
    # exists to prevent (Jeremy, 2026-08-04: "it constantly triggering events
    # as the value changes is a major problem"). DIVERGENCE, documented:
    # webCoRE re-runs every statement on every event, so statements other than
    # the one that asked for `remains_*` no longer get woken by it.
    all_triggers, seen = [], set()
    for part in parts:
        for t in part["triggers"]:
            if t.get("_noisy"):
                continue
            key = _json_dumps(t)
            if key not in seen:
                seen.add(key)
                all_triggers.append(t)

    def gated(part):
        body = part["actions"]
        return ([{"kind": "if", "conditions": part["conditions"],
                  "then": body, "else": []}] if part["conditions"] else body)

    noisy = [p for p in parts if any(t.get("_noisy") for t in p["triggers"])]
    waiting = [p for p in parts if p not in noisy
               and (_has_wait(p["br"]["then"]) or _has_wait(p["br"]["else"]))]
    plain = [p for p in parts if p not in noisy and p not in waiting]

    def emit(suffix, chunk, mode, triggers=None, throttle=None):
        if not chunk:
            return
        actions = []
        for part in chunk:
            actions.extend(gated(part))
        auto_id = f"pistoncore_{piston_id}{suffix}"
        auto_ids.append(auto_id)
        blocks.append(_env.get_template("automation.yaml.j2").render(
            auto_id=auto_id,
            alias=f"PistonCore: {piston_name}"
                  + (f" — ${chunk[0]['br']['stmt_id']}" if suffix else ""),
            mode=mode,
            max_exceeded="silent" if throttle else None,
            throttle_seconds=throttle,
            triggers=all_triggers if triggers is None else triggers,
            conditions=[],
            actions=actions,
        ))

    emit("", plain, "restart" if any(p["br"]["tcp"] == "c" for p in plain)
         else "queued")
    for part in waiting:
        emit(f"_s{part['br']['stmt_id']}", [part],
             "restart" if part["br"]["tcp"] == "c" else "queued")
    for part in noisy:
        # QUARANTINE. Its own automation, so waking on every update can only
        # ever restart ITS OWN run — which is what webCoRE does under
        # TCP=restart anyway — and can never cancel another statement's
        # pending timer.
        #
        # `single` + the trailing delay is the throttle. It cannot be used when
        # the statement holds a wait of its own: `single` would drop the
        # re-trigger that TCP=restart requires, so that combination keeps its
        # real mode and runs unthrottled.
        has_wait = _has_wait(part["br"]["then"]) or _has_wait(part["br"]["else"])
        emit(f"_s{part['br']['stmt_id']}", [part],
             ("restart" if part["br"]["tcp"] == "c" else "queued")
             if has_wait else "single",
             triggers=all_triggers + [t for t in part["triggers"]
                                      if t.get("_noisy")],
             throttle=None if has_wait else _NOISY_THROTTLE)


def _emit_branch(br: dict, resolver: Resolver, piston_id: str, piston_name: str,
                 blocks: list, auto_ids: list, collect: list | None = None,
                 piston_has_triggers: bool = False) -> None:
    """Emit one statement.

    `collect` is not None when the piston is TRIGGER-DRIVEN: the statement's
    parts are appended to it instead of becoming their own automation, so the
    caller can merge every statement into one. See _merge_branches for why.

    `piston_has_triggers` gates promotion — webCoRE promotes conditions only
    when the WHOLE piston has none (:9296), never per statement."""
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
        if triggers is not None and piston_has_triggers and not triggers:
            # The piston has a trigger elsewhere, so this statement is NOT
            # promoted (webcore-piston.groovy:9296) — but a condition carrying
            # a DURATION still needs something to wake the piston when the time
            # elapses. webCoRE schedules that itself (requestWakeUp /
            # scheduleTimeCondition, :5205 / :7895); the HA equivalent is a
            # trigger with `for:`. Without it a "was X for 5 minutes" statement
            # is only ever evaluated when some OTHER trigger happens to fire,
            # so a motion light would never turn off.
            for cond in br["conditions"]:
                if not (cond.get("duration") or {}).get("c"):
                    continue
                hold = _duration_hms(cond.get("duration"))
                if not hold:
                    continue
                node = _promote(cond, resolver, ctx, trig_id)
                if node is None and cond.get("lo_type") == "p" and cond.get("devices"):
                    # `was X for N` / `stays X for N`: _promote only knows the
                    # instantaneous comparisons. The HA idiom for a held value
                    # is a state trigger with `for:` — became X and stayed X.
                    co = cond.get("co") or ""
                    value = cond.get("value")
                    if co.startswith(("was", "stays", "remains")) and value is not None:
                        try:
                            entities = resolver.entities_for_attr(
                                cond["devices"], cond["attr"], ctx)
                        except CompilerError:
                            continue
                        if entities:
                            node = {"kind": "state", "entities": entities,
                                    "to": resolver.ha_state_value(cond["attr"], value),
                                    "id": trig_id}
                if node:
                    node["for"] = hold
                    triggers.append(node)

        if not triggers and not piston_has_triggers:
            # CONDITION-ONLY PISTON -> promote (subscription equivalence,
            # webcore-piston.groovy:9296). Per PISTON, never per statement: a
            # piston that has a trigger anywhere runs all of its statements on
            # that trigger, so promoting here would invent an automation
            # webCoRE never has.
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

    if _has_attached(br["conditions"]):
        _assert_no_orphan_attached(br, True, ctx)
        actions = _attached_chain(br["conditions"], then_actions,
                                  else_actions, resolver, ctx)
        conditions.extend(direction_conds)
        if collect is not None:
            collect.append({"br": br, "conditions": conditions,
                            "triggers": triggers + cancel_triggers,
                            "actions": actions})
            return
        _finish_branch(br, conditions, triggers, cancel_triggers, actions,
                       piston_id, piston_name, blocks, auto_ids)
        return
    _assert_no_orphan_attached(br, False, ctx)

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

    # A noisy trigger fires on every change, satisfied or not, so its check
    # CANNOT be optional the way the else-branch re-check above is — without it
    # the body would run on every update. Appended unconditionally, and guarded
    # so a piston carrying both an else-branch and a noisy trigger does not get
    # the same condition twice.
    for _trig in br["triggers"]:
        if not _is_noisy_trigger(_trig):
            continue
        _rc = _recheck_condition(_trig, resolver, ctx)
        if _rc and _rc not in cond_nodes:
            cond_nodes.append(_rc)

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

    if collect is not None:
        # MERGING: this statement's body is about to sit in ONE automation
        # alongside every other statement, woken by the union of all their
        # triggers. A statement whose only gate WAS its trigger would then run
        # on somebody else's trigger too — turning a flag off in the same run
        # that set it. webCoRE re-evaluates the trigger as a condition on every
        # run, so add that re-check here.
        # Gate on the TRIGGER ID, which is webCoRE's rule stated exactly: a
        # trigger comparison is true only for its OWN event. A re-check
        # condition cannot express that — a bare "switch changed" has no state
        # to re-check — and without a gate this statement would run on every
        # other statement's trigger too, turning a flag off in the run that set
        # it. A statement with only CONDITIONS gets no such gate, because a
        # condition is meant to be evaluated on any event.
        gates = list(conditions)
        if br["triggers"]:
            stmt_key = f"stmt{br['stmt_id']}"
            for t in all_triggers:
                if not t.get("id"):
                    t["id"] = stmt_key
            ids = sorted({t.get("id") for t in all_triggers if t.get("id")})
            if ids:
                gates.append({"kind": "trigger", "id": ids})
        collect.append({"br": br, "conditions": gates,
                        "triggers": all_triggers, "actions": actions})
        return
    _finish_branch(br, conditions, all_triggers, [], actions,
                   piston_id, piston_name, blocks, auto_ids)

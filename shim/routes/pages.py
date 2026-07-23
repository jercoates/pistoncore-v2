"""PistonCore's own pages (CLAUDE.md UI split): the front door landing page,
and stub routes for pages not built yet. Distinct from shim/routes/dashboard.py,
which answers the vendored webCoRE dashboard's own intf/dashboard/* API calls.
Vanilla HTML/CSS/JS + Jinja2, no frontend framework, no build step (CLAUDE.md).
"""

import asyncio
import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from html import escape

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import deploy_writer, ha_client, storage

router = APIRouter()

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(REPO_ROOT / "templates"))


def _tile_view(entry: dict) -> dict:
    """
    Front-door tile view-model. Compile/deploy status are honest placeholders
    -- there is no compiler yet (CLAUDE.md milestone 5), so every tile says
    so plainly rather than fabricating a status. Once the compiler exists,
    this is where its real per-piston result gets read and surfaced.
    """
    meta = entry["meta"]
    modified = datetime.fromtimestamp(meta["m"] / 1000).strftime("%Y-%m-%d %H:%M") if meta["m"] else "never"
    return {
        "id": entry["id"],
        "name": entry["name"],
        "active": meta["a"],
        "description": meta["z"],
        "modified": modified,
        "category": str(meta.get("c", "0") or "0"),
    }


def _folder_name(category: str) -> str:
    # Category NAMES aren't served by the shim yet (webCoRE's are instance
    # settings) — "0" is webCoRE's own Uncategorized; others get a plain
    # numbered label until real names are wired.
    return "Uncategorized" if category == "0" else f"Category {category}"


@router.get("/")
async def front_door(request: Request):
    # First-run: nobody's entered HA credentials yet at all -- send them to
    # Settings instead of a front door stuck permanently on "HA Unreachable"
    # with no obvious next step. Once configured (even if currently wrong/
    # unreachable), this never fires again -- that's what the badge is for.
    if not ha_client.is_configured():
        return RedirectResponse(url="/setup")

    _capture_media_base(request)   # learn our own address for the media proxy

    from ..compiler import deploy as compiler_deploy
    statuses = compiler_deploy.load_statuses()
    tiles = sorted((_tile_view(entry) for entry in storage.list_pistons()),
                   key=lambda t: t["name"].lower())
    for t in tiles:
        t["compile"] = statuses.get(t["id"]) or {
            "status": "pending", "message": "not compiled yet — save the piston to compile"}
    counts: dict[str, int] = {}
    for t in tiles:
        counts[t["category"]] = counts.get(t["category"], 0) + 1
    folders = [{"id": c, "name": _folder_name(c), "count": n}
               for c, n in counts.items()]
    # named categories first (alphabetical), Uncategorized last — mockup order
    folders.sort(key=lambda f: (f["id"] == "0", f["name"].lower()))
    ha_ok, ha_message = await ha_client.check_connection()
    return templates.TemplateResponse(request, "front_door.html", {
        "tiles": tiles,
        "folders": folders,
        "total": len(tiles),
        "ha_ok": ha_ok,
        "ha_message": ha_message,
    })


@router.post("/api/new-piston")
def new_piston(name: str = "New Piston"):
    """
    Plain-JSON piston creation for the front door's own "New Piston" button.
    Distinct from intf/dashboard/piston/create (shim/routes/dashboard.py),
    which is JSONP-wrapped for the vendored Angular dashboard's $http calls
    -- this page is vanilla JS/fetch, so it gets its own plain endpoint
    rather than parsing a callback(...) wrapper client-side.
    """
    entry = storage.create_piston(name, author="")
    return {"id": entry["id"]}


def _stub(request: Request, title: str, message: str):
    return templates.TemplateResponse(request, "stub.html", {"title": title, "message": message})


@router.get("/test-devices")
async def test_devices_page(request: Request):
    # Data loads client-side from /api/test-devices/* (test_devices.js); this
    # just serves the shell so the panel reflects HA's live truth on every action.
    return templates.TemplateResponse(request, "test_devices.html", {})


@router.get("/test-devices/debug")
async def debug_devices_page(request: Request):
    """Developer debug library (VIRTUAL_DEVICES_SPEC §5.8) — every capability as a
    single test type, for troubleshooting other people's pistons. Separate from
    the user clone panel; reached from Diagnostics and a Developer link."""
    return templates.TemplateResponse(request, "debug_devices.html", {})


# ---------------------------------------------------------------------------
# Test devices panel (VIRTUAL_DEVICES_SPEC.md Stage 4). PistonCore ties into the
# forked `virtual` integration (test-devices-integration/): it CREATES and
# CONTROLS devices via that integration's HA services and reads current state
# from HA's API to display (Jeremy 2026-07-21). PistonCore keeps no device state
# of its own. The integration must be installed on the connected HA; if it isn't,
# the panel says so and points at the install help.
# ---------------------------------------------------------------------------

TEST_DEVICES_GROUP = "PistonCore Test Devices"

# The catalog of addable test-device TYPES = the device kinds the compiler targets
# (VIRTUAL_DEVICES_SPEC §1.5/§5.2), not just what Jeremy owns — this is the
# maintenance bench. Each value is the entity list for `virtual.create_device`.
# (Candidate to become editable data later, like the compiler maps.)
TEST_DEVICE_TEMPLATES: dict[str, list[dict]] = {
    "Motion sensor": [{"platform": "binary_sensor", "class": "motion"}],
    "Contact sensor": [{"platform": "binary_sensor", "class": "door"}],
    "Smoke detector": [{"platform": "binary_sensor", "class": "smoke"}],
    "Water/leak sensor": [{"platform": "binary_sensor", "class": "moisture"}],
    "Switch": [{"platform": "switch"}],
    "Light / dimmer": [{"platform": "light"}],
    "Lock": [{"platform": "lock"}],
    "Cover / shade": [{"platform": "cover", "class": "shade"}],
    "Fan": [{"platform": "fan"}],
    "Temperature sensor": [{"platform": "sensor", "class": "temperature", "unit_of_measurement": "°C"}],
    "Illuminance sensor": [{"platform": "sensor", "class": "illuminance", "unit_of_measurement": "lx"}],
    "Humidity sensor": [{"platform": "sensor", "class": "humidity", "unit_of_measurement": "%"}],
    "Alarm panel (HSM)": [{"platform": "alarm_control_panel"}],
    "Thermostat": [{"platform": "climate"}],
    "Speaker": [{"platform": "media_player"}],
    "Siren": [{"platform": "siren"}],
    "Humidifier": [{"platform": "humidifier"}],
    "Vacuum": [{"platform": "vacuum"}],
    "Button": [{"platform": "button"}],
    "Multi-sensor (motion + lux + temp)": [
        {"platform": "binary_sensor", "class": "motion"},
        {"platform": "sensor", "class": "illuminance", "unit_of_measurement": "lx"},
        {"platform": "sensor", "class": "temperature", "unit_of_measurement": "°C"},
    ],
}


# Domains the virtual integration can reproduce as a settable test entity.
_VIRTUAL_PLATFORM_DOMAINS = {
    "alarm_control_panel", "binary_sensor", "button", "climate", "cover",
    "device_tracker", "event", "fan", "humidifier", "light", "lock",
    "media_player", "number", "sensor", "siren", "switch", "vacuum", "valve",
}


async def _discover_twin_types() -> list[dict]:
    """Read the user's REAL devices (device_pipeline grouping) and build a
    faithful test-twin spec for each distinct device TYPE: a grouped virtual
    device reproducing the same HA entities (domain + device_class + unit), so a
    piston can be tested against a twin of the ACTUAL gear — a UniFi camera's
    motion + smartDetectType, an ecobee, an alarm keypad, whatever the user has.
    This is the 'one of each of YOUR devices' the bench is for (VIRTUAL_DEVICES_
    SPEC §3), not a generic catalog."""
    from .. import device_pipeline

    import re

    regs = await ha_client.fetch_registries()
    states = {s["entity_id"]: s.get("attributes", {}) for s in regs.get("states", [])}
    ent_reg = {e["entity_id"]: e for e in regs.get("entities", [])}
    groups = device_pipeline.group_entities(regs)

    def _cap_name(eid: str, attrs: dict, device_label: str) -> str:
        # Prefer the entity's own capability name; strip the device label so a
        # camera's "Driveway Motion Smart Detect Type" reads as "Smart Detect Type".
        name = (ent_reg.get(eid, {}).get("original_name")
                or attrs.get("friendly_name") or eid.split(".", 1)[1])
        dl = device_label.strip().lower()
        if name.lower().startswith(dl):
            name = name[len(dl):].strip(" -—:")
        return name or eid.split(".", 1)[1]

    # Infrastructure, not test devices (Jeremy 2026-07-21): the Hubitat hub / HSM
    # (HSM is handled as the alarm binding), and PistonCore's own internals.
    _SKIP_LABEL = ("hubitat", "hsm", "pistoncore")

    types: dict = {}
    for g in groups:
        label = g["display_name"]
        if any(s in label.lower() for s in _SKIP_LABEL):
            continue
        # Don't offer to clone our OWN test devices (platform 'virtual') — the
        # clone list is for real gear you own, not copies you already made.
        if g["member_entity_ids"] and all(
                ent_reg.get(eid, {}).get("platform") == "virtual" for eid in g["member_entity_ids"]):
            continue
        ents = []
        for eid in g["member_entity_ids"]:
            dom = eid.split(".", 1)[0]
            if dom not in _VIRTUAL_PLATFORM_DOMAINS:
                continue  # image/select/event/update not reproducible YET (see spec §5.7)
            # Reproduce EVERYTHING in a reproducible domain — no trimming. A full
            # debug suite is large ON PURPOSE (Jeremy 2026-07-21): the "extra"
            # capabilities (YoLink alarm thresholds, Inovelli/Zooz double-tap,
            # held/pushed, mmWave, ...) are exactly what a piston might use, so a
            # faithful twin must carry them, not a tidied-down subset.
            reg = ent_reg.get(eid, {})
            attrs = states.get(eid, {})
            spec = {"platform": dom, "name": _cap_name(eid, attrs, label)}
            dc = attrs.get("device_class") or reg.get("device_class")
            if dc:
                spec["class"] = dc
            unit = attrs.get("unit_of_measurement")
            if unit and dom in ("sensor", "number"):
                spec["unit_of_measurement"] = unit
            ents.append(spec)
        if not ents:
            continue
        # Type signature keys on the SHAPE (platform+class+capname), so a
        # smartDetect camera is a distinct type from a plain motion sensor.
        sig = tuple(sorted(
            (e["platform"], e.get("class", ""), e["name"].lower()) for e in ents))
        rec = types.setdefault(sig, {"label": label, "entities": ents, "count": 0})
        rec["count"] += 1

    out = []
    for rec in sorted(types.values(), key=lambda r: -r["count"]):
        caps = [e.get("class") or e["name"] for e in rec["entities"]]
        out.append({"label": rec["label"], "count": rec["count"],
                    "caps": caps, "entities": rec["entities"]})
    return out


# Creation-only mappings for capabilities the vocab's MATCHING rules can't map
# (their attribute has no distinguishing HA device_class, so a forward rule would
# over-match every plain sensor/binary_sensor). These DO have a settable HA
# representation for a TEST device. (platform, device_class|None). This never
# touches the device pipeline — it's only used to CREATE debug devices.
_DEBUG_EXTRA: dict[str, tuple[str, str | None]] = {
    "consumable": ("sensor", None),
    "estimatedTimeOfArrival": ("sensor", "timestamp"),
    "indicator": ("sensor", None),
    "infraredLevel": ("number", None),
    "powerSource": ("sensor", None),
    "sensor": ("sensor", None),
    "sleepSensor": ("binary_sensor", None),
    "speechRecognition": ("sensor", None),
    "stepSensor": ("sensor", None),
    "threeAxis": ("sensor", None),
    "touchSensor": ("binary_sensor", None),
    "timedSession": ("sensor", None),          # HA `timer` proper; sensor stopgap
    "mediaController": ("media_player", None),  # HA `remote` proper; media_player is a real fallback
    # command-only speaker/action capabilities (no state attribute) — a device of
    # this kind IS a media_player / button / siren:
    "audioNotification": ("media_player", None),
    "speechSynthesis": ("media_player", None),
    "momentary": ("button", None),
    "tone": ("siren", None),
    "notification": ("sensor", None),          # last-message text as a sensor
}

# Genuinely not reproducible as a settable test device (honest, with the reason).
# (button/holdableButton now reproduce via the event platform — see event.py.)
_DEBUG_NEEDS_PLATFORM = {
    "imageCapture": "a camera snapshot — not settable as a test entity",
}
_DEBUG_MARKERS = {  # webCoRE capability markers, not device types
    "actuator", "configuration", "polling", "refresh",
}


def _debug_library() -> dict:
    """The DEVELOPER debug suite (VIRTUAL_DEVICES_SPEC §5.8): every webCoRE
    capability the vocab defines, as ONE single settable test type — so a piston
    someone sends you can be troubleshot against the exact device KIND it uses,
    even one you don't own. Grounded in the vocab's own capability + attribute
    rules, with a creation-only supplement (_DEBUG_EXTRA) for kinds whose HA rule
    is match-only. Returns {types: [...], unmappable: [{label, why}]}."""
    from .. import device_pipeline

    vocab = device_pipeline._load_json("webcore_vocab.json")
    caps = vocab.get("capabilities", {})
    attrs = vocab.get("attributes", {})

    def _first_supported_rule(attr_key):
        rules = (attrs.get(attr_key) or {}).get("ha")
        if not rules or rules == "n/a":
            return None
        rules = rules if isinstance(rules, list) else [rules]
        for r in rules:  # scan ALL rules, not just the first — a later one may be reproducible
            if isinstance(r, dict) and r.get("domain") in _VIRTUAL_PLATFORM_DOMAINS:
                return r
        return None

    types, unmappable = [], []
    for cap_key, cap in sorted(caps.items()):
        label = cap.get("n") or cap_key
        domain = dc = None
        rule = _first_supported_rule(cap.get("a")) if cap.get("a") else None
        if rule:
            domain = rule["domain"]
            rdc = rule.get("device_class")
            dc = rdc[0] if isinstance(rdc, list) and rdc else (rdc if isinstance(rdc, str) else None)
        elif cap_key in _DEBUG_EXTRA:
            domain, dc = _DEBUG_EXTRA[cap_key]

        if not domain:
            why = (_DEBUG_NEEDS_PLATFORM.get(cap_key)
                   or ("a webCoRE capability marker, not a device" if cap_key in _DEBUG_MARKERS
                       else "no HA equivalent"))
            unmappable.append({"label": label, "why": why})
            continue

        ent = {"platform": domain, "name": label}
        if dc:
            ent["class"] = dc
        types.append({"label": label, "key": cap_key, "domain": domain,
                      "device_class": dc, "entities": [ent]})
    return {"types": types, "unmappable": unmappable}


def _bust_device_cache() -> None:
    """Drop the dashboard's cached device snapshot so a just-added/removed test
    device shows up in the editor's picker immediately (no restart/reload)."""
    from .dashboard import reset_device_cache
    reset_device_cache()


async def _integration_present() -> bool:
    """Is the forked `virtual` test-device integration installed on the HA we're
    connected to? Detected by its create_device service being registered."""
    try:
        services = await ha_client.get_services()
    except Exception:
        return False
    return "create_device" in (services.get("virtual") or {})


async def _list_test_devices() -> list[dict]:
    """Every device the `virtual` integration owns on the connected HA, grouped,
    with each entity's live state read straight from HA."""
    regs = await ha_client.fetch_registries()
    states = {s["entity_id"]: s for s in regs.get("states", [])}
    devmap = {d["id"]: d for d in regs.get("devices", [])}
    groups: dict[str, dict] = {}
    for e in regs.get("entities", []):
        if e.get("platform") != "virtual":
            continue
        did = e.get("device_id")
        dev = devmap.get(did, {})
        g = groups.setdefault(did or e["entity_id"], {
            "device_name": dev.get("name_by_user") or dev.get("name") or "Test device",
            "entities": [],
        })
        st = states.get(e["entity_id"], {})
        g["entities"].append({
            "entity_id": e["entity_id"],
            "domain": e["entity_id"].split(".")[0],
            "name": e.get("name") or e.get("original_name") or e["entity_id"],
            "state": st.get("state"),
            "attributes": st.get("attributes", {}) or {},
        })
    return sorted(groups.values(), key=lambda g: g["device_name"].lower())


def _truthy(value) -> bool:
    return str(value).strip().lower() in ("on", "true", "1", "yes", "open", "unlocked", "active")


async def _set_capability(entity_id: str, value, sub: str | None = None) -> None:
    """Drive one test-device capability through the right NATIVE HA service
    (same services a standalone HA user would use). `sub` names which facet of a
    multi-facet device (climate: current_temperature|temperature|mode;
    media_player: volume|state; humidifier: humidity|onoff)."""
    domain = entity_id.split(".", 1)[0]
    ent = {"entity_id": entity_id}
    if domain == "binary_sensor":
        await ha_client.call_service("virtual", "turn_on" if _truthy(value) else "turn_off", ent)
    elif domain in ("switch", "light", "fan", "siren"):
        await ha_client.call_service(domain, "turn_on" if _truthy(value) else "turn_off", ent)
    elif domain == "lock":
        await ha_client.call_service("lock", "unlock" if _truthy(value) else "lock", ent)
    elif domain == "cover":
        await ha_client.call_service("cover", "open_cover" if _truthy(value) else "close_cover", ent)
    elif domain == "number":
        await ha_client.call_service("number", "set_value", {**ent, "value": value})
    elif domain == "sensor":
        await ha_client.call_service("virtual", "set", {**ent, "value": str(value)})
    elif domain == "alarm_control_panel":
        svc = {"disarmed": "alarm_disarm", "armed_away": "alarm_arm_away",
               "armed_home": "alarm_arm_home", "armed_night": "alarm_arm_night",
               "armed_vacation": "alarm_arm_vacation", "triggered": "alarm_trigger"}.get(str(value))
        if svc:
            await ha_client.call_service("alarm_control_panel", svc, ent)
    elif domain == "climate":
        if sub == "current_temperature":
            await ha_client.call_service("virtual", "set_current_temperature", {**ent, "value": value})
        elif sub == "temperature":
            await ha_client.call_service("climate", "set_temperature", {**ent, "temperature": value})
        else:
            await ha_client.call_service("climate", "set_hvac_mode", {**ent, "hvac_mode": str(value)})
    elif domain == "media_player":
        if sub == "volume":
            await ha_client.call_service("media_player", "volume_set", {**ent, "volume_level": value})
        else:
            svc = {"playing": "media_play", "paused": "media_pause", "idle": "media_stop",
                   "on": "turn_on", "off": "turn_off"}.get(str(value))
            if svc:
                await ha_client.call_service("media_player", svc, ent)
    elif domain == "humidifier":
        if sub == "humidity":
            await ha_client.call_service("humidifier", "set_humidity", {**ent, "humidity": value})
        else:
            await ha_client.call_service("humidifier", "turn_on" if _truthy(value) else "turn_off", ent)
    elif domain == "vacuum":
        svc = {"cleaning": "start", "idle": "stop", "paused": "pause",
               "returning": "return_to_base", "docked": "return_to_base"}.get(str(value))
        if svc:
            await ha_client.call_service("vacuum", svc, ent)
    elif domain == "button":
        await ha_client.call_service("button", "press", ent)
    elif domain == "event":
        await ha_client.call_service("virtual", "fire_event", {**ent, "event_type": str(value)})


async def _ensure_group() -> None:
    """Make sure the PistonCore test-devices group (a `virtual` config entry)
    exists, so devices can be added. Because HA only loads a config-flow
    integration once it has an entry, this doubles as the install check: if the
    integration isn't installed, HA's flow-init reports an invalid handler and we
    say so plainly. Uses HA's REST config-flow (the call the wizard makes),
    echoing HA's own default file path so we never guess HA's config dir."""
    import urllib.error
    import urllib.request

    # Already set up (its services are registered)? Nothing to do.
    if await _integration_present():
        return

    ha_url, token = ha_client._load_auth()
    if not (ha_url and token):
        raise ha_client.HAClientError("No HA credentials configured.")
    base = ha_url.rstrip("/")

    def _post(path: str, body: dict):
        req = urllib.request.Request(
            base + path, method="POST", data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError:
            return None

    def _work() -> bool:
        started = _post("/api/config/config_entries/flow", {"handler": "virtual"})
        if not started or not started.get("flow_id"):
            return False  # integration not installed / no config flow available
        default_file = None
        for field in started.get("data_schema", []):
            if field.get("name") == "file_name":
                default_file = field.get("default")
        _post(f"/api/config/config_entries/flow/{started['flow_id']}", {
            "group_name": TEST_DEVICES_GROUP,
            "file_name": default_file or "virtual.yaml",
        })
        return True

    if not await asyncio.to_thread(_work):
        raise ha_client.HAClientError(
            "The PistonCore Test Devices integration isn't installed on Home "
            "Assistant yet. Install it (the test-devices-integration folder) and "
            "restart Home Assistant, then try again.")

    # The entry sets up asynchronously; wait for its services to register.
    for _ in range(20):
        if await _integration_present():
            return
        await asyncio.sleep(0.5)
    raise ha_client.HAClientError(
        "Created the group, but Home Assistant hasn't finished loading it — "
        "reload this page in a moment.")


@router.get("/api/test-devices/list")
async def api_test_devices_list():
    if not ha_client.is_configured():
        return {"configured": False, "present": False, "devices": [], "types": list(TEST_DEVICE_TEMPLATES)}
    present = await _integration_present()
    devices = await _list_test_devices() if present else []
    return {"configured": True, "present": present, "devices": devices,
            "types": list(TEST_DEVICE_TEMPLATES)}


_INTEGRATION_SRC = REPO_ROOT / "test-devices-integration" / "custom_components" / "virtual"


def _integration_files() -> list:
    if not _INTEGRATION_SRC.exists():
        return []
    return [p for p in _INTEGRATION_SRC.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]


@router.post("/api/test-devices/install")
async def api_test_devices_install(request: Request):
    """Write the test-device integration into HA's custom_components and restart
    HA to load it. GATED: the caller MUST acknowledge that this writes into Home
    Assistant — enforced here server-side, so the warning can't be skipped by
    hitting the endpoint directly (Jeremy 2026-07-21)."""
    body = await request.json()
    if not body.get("acknowledged"):
        return JSONResponse(
            {"error": "This writes files into your Home Assistant and restarts it — "
                      "acknowledge the warning to proceed."}, status_code=400)
    files = _integration_files()
    if not files:
        return JSONResponse(
            {"error": "The integration files aren't bundled in this build."}, status_code=500)
    try:
        writer = deploy_writer.get_writer()
        for p in files:
            rel = p.relative_to(_INTEGRATION_SRC).as_posix()
            content = p.read_text(encoding="utf-8")
            await asyncio.to_thread(writer.write, f"custom_components/virtual/{rel}", content)
    except deploy_writer.WriteTargetError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    # Restart HA to load the new integration. HA drops the connection as it goes
    # down, so a failed call here just means the restart is under way.
    try:
        await ha_client.call_service("homeassistant", "restart", {})
    except Exception:
        pass
    return {"ok": True, "files": len(files), "restarting": True}


@router.post("/api/test-devices/setup")
async def api_test_devices_setup():
    """One-time: create the PistonCore test-devices group so devices can be added.
    Reports plainly if the integration isn't installed (see _ensure_group)."""
    try:
        await _ensure_group()
    except ha_client.HAClientError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return {"ok": True}


@router.post("/api/test-devices/create")
async def api_test_devices_create(request: Request):
    body = await request.json()
    type_name = body.get("type")
    device_name = (body.get("name") or "").strip()
    entities = TEST_DEVICE_TEMPLATES.get(type_name)
    if not entities or not device_name:
        return JSONResponse({"error": "Pick a type and a name."}, status_code=400)
    try:
        await _ensure_group()
    except ha_client.HAClientError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    # ALWAYS tag the HA name with "Test —" (VIRTUAL_DEVICES_SPEC §4.1): the device
    # and its entities must read as test gear inside Home Assistant itself
    # (dashboards, logbook, entity_ids), not only on this panel. Don't double-tag
    # if the user already typed "Test".
    tagged = device_name if device_name.lower().startswith("test") else f"Test — {device_name}"
    ents = []
    for e in entities:
        ent = dict(e)
        cls = ent.get("class", ent["platform"].replace("_", " "))
        ent["name"] = tagged if len(entities) == 1 else f"{tagged} {cls}"
        ents.append(ent)
    await ha_client.call_service("virtual", "create_device", {
        "group_name": TEST_DEVICES_GROUP, "device_name": tagged, "entities": ents})
    _bust_device_cache()
    return {"ok": True}


@router.get("/api/test-devices/debug-library")
async def api_debug_library():
    """The developer debug suite catalog: every capability as a single test type."""
    return _debug_library()


async def _create_single(label: str, entity: dict) -> None:
    tagged = label if label.lower().startswith("test") else f"Test — {label}"
    ent = {"platform": entity["platform"], "name": tagged}
    if entity.get("class"):
        ent["class"] = entity["class"]
    await ha_client.call_service("virtual", "create_device", {
        "group_name": TEST_DEVICES_GROUP, "device_name": tagged, "entities": [ent]})
    _bust_device_cache()


@router.post("/api/test-devices/debug-add")
async def api_debug_add(request: Request):
    """Add ONE debug-suite type (the common path: a piston needs a garage door
    you don't own — add just that)."""
    body = await request.json()
    label, entities = body.get("label"), body.get("entities") or []
    if not label or not entities:
        return JSONResponse({"error": "Nothing to add."}, status_code=400)
    try:
        await _ensure_group()
    except ha_client.HAClientError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    await _create_single(label, entities[0])
    return {"ok": True}


@router.post("/api/test-devices/debug-suite")
async def api_debug_suite():
    """Spin up the WHOLE suite — one device per mappable capability. Slower (a
    reload per device); the per-type add above is the everyday path."""
    try:
        await _ensure_group()
    except ha_client.HAClientError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    lib = _debug_library()
    for t in lib["types"]:
        await _create_single(t["label"], t["entities"][0])
    return {"ok": True, "created": len(lib["types"])}


@router.get("/api/test-devices/discover")
async def api_test_devices_discover():
    """The user's real device TYPES, each as a cloneable twin spec (clone panel)."""
    if not ha_client.is_configured():
        return {"types": []}
    try:
        return {"types": await _discover_twin_types()}
    except Exception as exc:
        # Never let a discovery failure silently hide the clone section — say why.
        return {"types": [], "error": f"Couldn't read your devices: {exc}"}


@router.post("/api/test-devices/create-twin")
async def api_test_devices_create_twin(request: Request):
    """Clone one discovered device type into a grouped test device."""
    body = await request.json()
    label = (body.get("label") or "").strip()
    entities = body.get("entities") or []
    if not label or not entities:
        return JSONResponse({"error": "Nothing to clone."}, status_code=400)
    try:
        await _ensure_group()
    except ha_client.HAClientError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    tagged = label if label.lower().startswith("test") else f"Test — {label}"
    seen: dict = {}
    ents = []
    for e in entities:
        plat = e.get("platform")
        if plat not in _VIRTUAL_PLATFORM_DOMAINS:
            continue
        base = (e.get("name") or plat).strip()
        seen[base] = seen.get(base, 0) + 1
        uniq = base if seen[base] == 1 else f"{base} {seen[base]}"  # de-dup within device
        ent = {"platform": plat, "name": f"Test — {uniq}"}
        if e.get("class"):
            ent["class"] = e["class"]
        if e.get("unit_of_measurement") and plat in ("sensor", "number"):
            ent["unit_of_measurement"] = e["unit_of_measurement"]
        ents.append(ent)
    if not ents:
        return JSONResponse({"error": "No reproducible capabilities on this device."}, status_code=400)
    await ha_client.call_service("virtual", "create_device", {
        "group_name": TEST_DEVICES_GROUP, "device_name": tagged, "entities": ents})
    _bust_device_cache()
    return {"ok": True}


@router.post("/api/test-devices/remove")
async def api_test_devices_remove(request: Request):
    body = await request.json()
    device_name = (body.get("name") or "").strip()
    if not device_name:
        return JSONResponse({"error": "No device named."}, status_code=400)
    await ha_client.call_service("virtual", "remove_device", {
        "group_name": TEST_DEVICES_GROUP, "device_name": device_name})
    _bust_device_cache()
    return {"ok": True}


@router.post("/api/test-devices/set")
async def api_test_devices_set(request: Request):
    body = await request.json()
    entity_id = body.get("entity_id")
    if not entity_id:
        return JSONResponse({"error": "No entity."}, status_code=400)
    await _set_capability(entity_id, body.get("value"), body.get("sub"))
    return {"ok": True}


async def _build_support_report() -> str:
    """One copyable text bundle a stuck user sends to Jeremy (or pastes to an AI)
    to get a problem fixed — HA connectivity, the last dashboard-load failure,
    skipped devices, and every piston's compile status, all in one place."""
    from .dashboard import LAST_LOAD_DIAG
    from ..compiler import deploy as _deploy

    out = [f"PistonCore Support Report — {datetime.utcnow().isoformat(timespec='seconds')}Z",
           "=" * 60]

    out.append("\n## Home Assistant")
    if ha_client.is_configured():
        ok, msg = await ha_client.check_connection()
        out.append(f"Configured: yes\nReachable: {'yes' if ok else 'NO'} — {msg}")
        cfg = ha_client.get_config_for_display()
        out.append(f"Write mode: {cfg.get('write_mode', '?')}")
    else:
        out.append("Configured: NO — first-run wizard not completed.")

    d = LAST_LOAD_DIAG
    out.append("\n## Last dashboard load")
    if not d.get("ok"):
        out.append(f"FAILED while: {d.get('stage')}")
        out.append(f"Error: {d.get('error')}")
        if d.get("traceback"):
            out.append("Traceback:\n" + str(d.get("traceback")).rstrip())
    else:
        out.append("OK (no load error captured this run).")
    if d.get("skipped"):
        out.append(f"Skipped devices ({len(d['skipped'])} — dashboard loads without them):")
        for s in d["skipped"]:
            out.append(f"  - {s.get('device')}: {s.get('error')}")

    out.append("\n## Pistons (compile status)")
    statuses = _deploy.load_statuses()
    pistons = storage.list_pistons()
    if not pistons:
        out.append("  (none)")
    for p in pistons:
        s = statuses.get(p["id"], {})
        line = f"  - {p['name']}: {s.get('status', 'not compiled')}"
        if s.get("message"):
            line += f" — {s['message']}"
        if s.get("band"):
            line += f" [band={s['band']}]"
        out.append(line)

    out.append("\n----\nSend this whole report to Jeremy, or paste it to an AI and ask it "
               "to help fix the problem.")
    return "\n".join(out)


@router.get("/api/support-report", response_class=PlainTextResponse)
async def api_support_report():
    return await _build_support_report()


@router.get("/whats-wrong")
async def whats_wrong(request: Request):
    """Plain diagnostic page a stuck user (or a remote friend) opens in the
    browser and screenshots — no server logs needed. Shows HA connectivity plus
    the last dashboard-load failure captured in shim/routes/dashboard.py."""
    from .dashboard import LAST_LOAD_DIAG as d

    if ha_client.is_configured():
        ha_ok, ha_msg = await ha_client.check_connection()
    else:
        ha_ok, ha_msg = False, "No Home Assistant URL/token set — finish the first-run wizard / Settings."

    _btn = ("padding:8px 14px;border-radius:6px;border:1px solid #3a3a5c;background:#2f7bd9;"
            "color:#fff;font:inherit;cursor:pointer;text-decoration:none;display:inline-block")
    parts = ["<h1>PistonCore — what's wrong</h1>",
             f"<p><b>Home Assistant:</b> {'✅ ' if ha_ok else '❌ '}{escape(str(ha_msg))}</p>",
             "<div style='background:#16213e;padding:1rem;border-radius:8px;margin:1rem 0'>"
             "<b>Stuck? Send this to Jeremy.</b>"
             "<p style='margin:.4rem 0;color:#9999bb'>Copy the full report and send it to Jeremy, "
             "or paste it to an AI and ask it to fix the problem — it has everything needed to "
             "diagnose (Home Assistant status, the load error, and every piston's compile status).</p>"
             f"<button id='cp' style='{_btn}'>Copy support report</button> "
             f"<a href='/api/support-report' download='pistoncore-report.txt' style='{_btn}'>Download</a>"
             "<span id='cpok' style='margin-left:.6rem;color:#4caf50'></span></div>"]
    if not d.get("ok"):
        parts.append(f"<h2>❌ The dashboard failed to load</h2>"
                     f"<p>It broke while <b>{escape(str(d.get('stage')))}</b>.</p>"
                     f"<pre>{escape(str(d.get('error')))}</pre>"
                     f"<details><summary>Full details (copy this to Jeremy)</summary>"
                     f"<pre>{escape(str(d.get('traceback')))}</pre></details>")
    elif not d.get("skipped"):
        parts.append("<p>✅ Last dashboard load was clean — no errors captured. "
                     "If it's still stuck, reload the dashboard once so this page can catch the error.</p>")
    if d.get("skipped"):
        parts.append(f"<h2>⚠️ {len(d['skipped'])} device(s) skipped</h2>"
                     "<p>The dashboard still loads without them — but these devices tripped the shim:</p><ul>")
        for s in d["skipped"]:
            parts.append(f"<li><b>{escape(str(s.get('device')))}</b> — {escape(str(s.get('error')))}"
                         f"<br><small>{escape(str(s.get('entities')))}</small></li>")
        parts.append("</ul>")
    style = ("<meta name=viewport content='width=device-width,initial-scale=1'>"
             "<style>body{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;"
             "padding:0 1rem;color:#e8e8f0;background:#1a1a2e}pre{white-space:pre-wrap;"
             "background:#16213e;padding:1rem;border-radius:8px;overflow:auto}"
             "a{color:#4a9eff}li{margin:.5rem 0}</style>")
    script = ("<script>document.getElementById('cp').onclick=async()=>{"
              "const t=await (await fetch('/api/support-report')).text();"
              "try{await navigator.clipboard.writeText(t);"
              "document.getElementById('cpok').textContent='copied ✓';}"
              "catch(e){document.getElementById('cpok').textContent='select the Download file instead';}"
              "};</script>")
    return HTMLResponse(style + "\n".join(parts)
                        + "<p><a href='/'>← back to PistonCore</a></p>" + script)


@router.get("/settings")
async def settings_page(request: Request):
    _capture_media_base(request)
    config = ha_client.get_config_for_display()
    config["first_run"] = request.query_params.get("first_run") == "1"
    config["saved"] = request.query_params.get("saved") == "1"
    # TTS engine picker (SPEAK_ACTION_SPEC: engine is a global setting) —
    # best-effort live enumeration; page still renders when HA is down
    config["tts_engine"] = storage.load_settings().get("tts_engine", "")
    config["default_band"] = storage.load_settings().get("default_band", "auto")
    config["media"] = storage.load_settings().get("media", {}) or {}
    try:
        regs = await ha_client.fetch_registries()
        from .. import device_pipeline
        config["tts_engines"] = device_pipeline.extract_tts_engines(regs)
    except Exception:
        config["tts_engines"] = []
    return templates.TemplateResponse(request, "settings.html", config)


@router.post("/api/settings")
async def save_settings(ha_url: str = "", ha_token: str = "", write_mode: str = "local",
                        ha_config_path: str = "", smb_host: str = "", smb_share: str = "config",
                        smb_username: str = "", smb_password: str = "", tts_engine: str = "",
                        media: str = ""):
    settings = storage.load_settings()
    settings["tts_engine"] = tts_engine.strip()
    # Media playback config (mode/map/server) — posted as a JSON blob by the
    # settings + first-run media panels. Merged, not clobbered, so a partial
    # save (e.g. first-run just flips the mode) keeps the rest.
    if media:
        import json
        try:
            incoming = json.loads(media)
            if isinstance(incoming, dict):
                cur = settings.get("media", {}) or {}
                cur.update(incoming)
                # the media server needs a signing secret so its proxy isn't an
                # open relay; mint one the first time a server address is set.
                if cur.get("server_base") and not cur.get("server_secret"):
                    import secrets
                    cur["server_secret"] = secrets.token_hex(16)
                settings["media"] = cur
        except (ValueError, TypeError):
            pass
    storage.save_settings(settings)
    ha_client.save_config(
        ha_url.strip(), ha_token.strip() or None,
        write_mode=write_mode.strip() or "local",
        ha_config_path=ha_config_path.strip(),
        smb_host=smb_host.strip(), smb_share=smb_share.strip() or "config",
        smb_username=smb_username.strip(),
        smb_password=smb_password.strip() or None,
    )
    return {"ok": True}


@router.get("/api/config-yaml")
async def config_yaml_analyze():
    """Show the EXACT configuration.yaml changes before consent (§9.2 rule b)."""
    from .. import config_yaml, deploy_writer
    try:
        return config_yaml.analyze()
    except deploy_writer.WriteTargetError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.post("/api/config-yaml/apply")
async def config_yaml_apply():
    """The consent click: timestamped backup, then apply (§9.2 rules a+c)."""
    from .. import config_yaml, deploy_writer
    try:
        return config_yaml.apply()
    except deploy_writer.WriteTargetError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.post("/api/ha/reload-yaml")
async def reload_ha_yaml():
    """homeassistant.reload_all — the gentle 'reload all YAML' (not a full
    restart). Offered as the post-Apply prompt after the configuration.yaml
    edit; whether a brand-new include line needs a FULL restart instead is the
    deploy spec's open dev-HA question — the UI says so if items don't appear."""
    try:
        await ha_client.call_service("homeassistant", "reload_all")
        return {"ok": True}
    except ha_client.HAClientError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.post("/api/settings/test-write")
async def test_write_target():
    """The §2.5 'Test write target' probe — write/read-back/delete against the
    configured transport so a bad mount/share fails HERE, not at first compile."""
    from .. import deploy_writer
    try:
        return deploy_writer.probe()
    except deploy_writer.WriteTargetError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.get("/setup")
async def setup_wizard(request: Request):
    """First-run setup wizard (SESSION_BRIEF_FIRST_RUN.md). Guided path over
    the SAME settings Settings owns — never a separate store, always
    re-runnable, every step skippable."""
    config = ha_client.get_config_for_display()
    config["is_addon"] = bool(os.environ.get("SUPERVISOR_TOKEN"))
    config["configured"] = ha_client.is_configured()
    return templates.TemplateResponse(request, "setup.html", config)


@router.get("/api/setup/detect")
async def setup_detect():
    """Step-0 deployment detection ladder (brief §Step 0): add-on ->
    mounted-config Docker -> SMB. Picks DEFAULTS only; the write probe is
    what actually gates progress."""
    if os.environ.get("SUPERVISOR_TOKEN"):
        return {"deployment": "addon", "write_mode": "local",
                "ha_config_path": "/homeassistant",
                "note": "Running as a Home Assistant add-on — connection and "
                        "config folder are handled automatically."}
    cfg = ha_client.get_config_for_display()
    candidates = [cfg.get("ha_config_path"), "/ha-config", "/config",
                  "/homeassistant", "/mnt/ha-config"]
    for path in [c for c in candidates if c]:
        try:
            if (Path(path) / "configuration.yaml").is_file():
                return {"deployment": "docker-mounted", "write_mode": "local",
                        "ha_config_path": path,
                        "note": f"Found Home Assistant's config folder mounted at {path}."}
        except OSError:
            continue
    host = ""
    url = cfg.get("ha_url") or ""
    if url:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
    return {"deployment": "docker-smb", "write_mode": "smb", "smb_host": host,
            "note": "No mounted Home Assistant config folder found — PistonCore "
                    "will write over the network using HA's Samba share add-on."}


@router.get("/api/setup/pyscript-check")
async def setup_pyscript_check():
    """Step-2b: is the PyScript integration installed? Informational only —
    never blocks setup (brief §Step 2b)."""
    try:
        services = await ha_client.get_services()
    except Exception as exc:
        return {"status": "unknown", "message": f"Could not ask HA: {exc}"}
    return {"status": "installed" if "pyscript" in services else "missing"}


@router.get("/diagnostics")
async def diagnostics_page(request: Request):
    """The compiler help/debug screen (CLAUDE.md UI split: drill-in only —
    reached from Settings or from an error surface, never a place errors
    announce themselves). A TOOL, not a document: live system checks, real
    per-piston errors, the generated code itself, and a one-click evidence
    bundle."""
    return templates.TemplateResponse(request, "diagnostics.html", {})


@router.get("/api/diagnostics")
async def diagnostics_data():
    """Everything the diagnostics page shows, computed live."""
    from ..compiler import deploy as compiler_deploy
    from .. import config_yaml, deploy_writer

    checks = []

    ok, msg = await ha_client.check_connection()
    checks.append({"name": "Home Assistant connection", "ok": ok,
                   "detail": msg,
                   "fix": "" if ok else "Settings → Home Assistant URL and token."})

    try:
        probe = deploy_writer.probe()
        checks.append({"name": "Write access to HA config", "ok": True,
                       "detail": probe.get("target", "ok"), "fix": ""})
    except Exception as exc:
        checks.append({"name": "Write access to HA config", "ok": False,
                       "detail": str(exc),
                       "fix": "Settings → Compiled-file write target, then Test write target."})

    try:
        services = await ha_client.get_services()
        has_py = "pyscript" in services
        checks.append({"name": "PyScript integration", "ok": has_py,
                       "detail": "installed" if has_py else "not installed",
                       "fix": "" if has_py else
                              "Install PyScript from HACS. Without it, pistons using "
                              "formulas, loops, switches, variables or computed text "
                              "cannot run (simple pistons are unaffected)."})
    except Exception as exc:
        checks.append({"name": "PyScript integration", "ok": None,
                       "detail": f"could not check: {exc}", "fix": ""})

    try:
        cy = config_yaml.analyze()
        cy_ok = cy.get("status") == "ok"
        checks.append({"name": "configuration.yaml include lines", "ok": cy_ok,
                       "detail": cy.get("message") or "changes needed",
                       "fix": "" if cy_ok else
                              "Settings → Check configuration.yaml, or re-run setup."})
    except Exception as exc:
        checks.append({"name": "configuration.yaml include lines", "ok": None,
                       "detail": f"could not check: {exc}", "fix": ""})

    from .. import customize
    customize.ensure_seeded()
    checks.append({"name": "Editable compiler files", "ok": True,
                   "detail": f"You can extend the compiler by editing the maps, "
                             f"templates and routing table under "
                             f"{customize.CUSTOMIZE_DIR} — changes take effect on "
                             f"the next compile, no rebuild.",
                   "fix": "How to (incl. AI instructions): /help/editing-compiler"})

    tts = storage.load_settings().get("tts_engine")
    checks.append({"name": "Speech engine", "ok": bool(tts) or None,
                   "detail": tts or "none picked (only needed for Speak pistons)",
                   "fix": "" if tts else "Settings → Speech (TTS)."})

    statuses = compiler_deploy.load_statuses()
    pistons = []
    for entry in sorted(storage.list_pistons(), key=lambda e: e["name"].lower()):
        rec = statuses.get(entry["id"]) or {}
        pistons.append({
            "id": entry["id"], "name": entry["name"],
            "active": entry["meta"]["a"],
            "status": rec.get("status", "pending"),
            "message": rec.get("message", "not compiled yet — save the piston to compile"),
            "file": rec.get("file"), "band": rec.get("band", "yaml" if rec.get("file") else ""),
            "code": rec.get("code"), "stmt_id": rec.get("stmt_id"),
            "band_pref": storage.compile_band(entry["id"]),
            "artifacts": _artifact_list(entry["id"]),
        })
    return {"checks": checks, "pistons": pistons,
            "default_band": storage.load_settings().get("default_band", "auto"),
            "band_prefs": [dict(v, id=k) for k, v in storage.band_prefs().items()]}


def _artifact_list(piston_id: str) -> list:
    from ..compiler import deploy as compiler_deploy
    d = compiler_deploy._DEBUG_DIR / piston_id
    if not d.is_dir():
        return []
    return sorted((f.name for f in d.iterdir() if f.is_file()), reverse=True)[:10]


@router.post("/api/diagnostics/default-band")
async def diagnostics_default_band(band: str = "auto"):
    """Instance-wide compile-target default. Lives on the compiler page, not
    in Settings (Jeremy 2026-07-19: this is an edge-case control for when the
    translation doesn't behave, so it belongs with the compiler tools)."""
    if band not in ("auto", "yaml", "pyscript"):
        return JSONResponse({"error": "bad band"}, status_code=400)
    s = storage.load_settings()
    s["default_band"] = band
    storage.save_settings(s)
    return {"ok": True, "band": band}


@router.post("/api/diagnostics/band/{piston_id}")
async def diagnostics_set_band(piston_id: str, band: str = "auto", why: str = ""):
    """Per-piston compile-target override (Jeremy 2026-07-19): force PyScript
    when the YAML translation misbehaves, or pin YAML. Recompiles immediately
    so the choice takes effect without a separate save."""
    if band not in ("auto", "yaml", "pyscript"):
        return JSONResponse({"error": "bad band"}, status_code=400)
    storage.set_compile_band(piston_id, band, why=why.strip())
    from ..compiler import deploy as compiler_deploy
    rec = await compiler_deploy.compile_and_deploy(piston_id)
    return {"ok": True, "band": band, "compile": rec}


@router.get("/api/diagnostics/artifact/{piston_id}/{name}")
async def diagnostics_artifact(piston_id: str, name: str):
    """One kept compile artifact, read in the browser — no file-share digging."""
    from ..compiler import deploy as compiler_deploy
    if "/" in name or "\\" in name or ".." in name or "/" in piston_id:
        return JSONResponse({"error": "bad path"}, status_code=400)
    path = compiler_deploy._DEBUG_DIR / piston_id / name
    if not path.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return {"name": name, "content": path.read_text(encoding="utf-8")}


@router.get("/api/diagnostics/bundle/{piston_id}")
async def diagnostics_bundle(piston_id: str):
    """The complete evidence package as ONE block of text: status record,
    newest generated artifact, and the piston's own JSON — the three things
    that make any compile problem diagnosable, assembled for pasting."""
    from ..compiler import deploy as compiler_deploy
    entry = storage.load_piston(piston_id)
    if entry is None:
        return JSONResponse({"error": "no such piston"}, status_code=404)
    rec = compiler_deploy.load_statuses().get(piston_id) or {}
    parts = [f"PistonCore debug bundle — \"{entry['name']}\" ({piston_id})",
             f"generated {datetime.now().isoformat(timespec='seconds')}",
             "", "== COMPILE STATUS ==", json.dumps(rec, indent=1)]
    pref = storage.band_prefs().get(piston_id) or {}
    if pref.get("band") in ("pyscript", "yaml"):
        parts += ["", "== COMPILE-TARGET OVERRIDE ==",
                  f"This piston is forced to: {pref['band']}",
                  f"Reason given: {pref.get('why') or '(none)'}",
                  "NOTE: the goal is for every piston to work as a native HA "
                  "automation. A piston needing this override is a gap in the "
                  "YAML compiler — worth reporting with this bundle."]
    names = _artifact_list(piston_id)
    if names:
        path = compiler_deploy._DEBUG_DIR / piston_id / names[0]
        parts += ["", f"== GENERATED OUTPUT ({names[0]}) ==",
                  path.read_text(encoding="utf-8")]
    else:
        parts += ["", "== GENERATED OUTPUT ==", "(none kept — this piston has not compiled)"]
    parts += ["", "== PISTON JSON ==", json.dumps(entry["piston"], indent=1)]
    return {"text": "\n".join(parts)}


# Which editable file governs which class of compile error. This is the
# self-repair surface (memory: user-maintainability goal — extend the compiler
# by editing DATA, not by a coding session). Order matters: first match wins.
_REPAIR_MAP = [
    ("no HA service mapping for command",
     "templates/compiler/yaml/classic/command_maps.json",
     "Add the missing webCoRE command -> HA service mapping for that device "
     "domain. Values are either a plain \"domain.service\" string, or "
     "{\"service\": \"domain.service\", \"data\": {...}} where data values may "
     "use $1/$2 for the task's parameters (optionally |hex_rgb or |pct_float)."),
    ("alarm status",
     "templates/compiler/yaml/classic/value_maps.json",
     "Add the webCoRE alarm status -> HA alarm_control_panel service under "
     "\"alarm_commands\"."),
    ("expression function",
     "templates/compiler/pyscript/2.x/expr_runtime.py.j2",
     "Implement the missing webCoRE function as a def _fn_<name>(...) in this "
     "runtime file, AND add its bare name to the _FUNCTIONS set at the bottom "
     "of shim/compiler/expression.py so the compiler knows it exists."),
    ("has no binding for attribute",
     "picker_capability_map.json",
     "This maps HA entity signals (domain, device_class, supported_features) "
     "to webCoRE attribute names. Add a rule so the entity that carries this "
     "attribute is recognised; check webcore_vocab.json for the attribute's "
     "canonical name and type."),
    ("requires PyScript",
     "routing_table.json",
     "This lists the webCoRE JSON signatures that force the PyScript band. "
     "Usually nothing to change — but if HA has since gained native support "
     "for the construct, removing its signature here lets it compile to YAML."),
    ("state value", "templates/compiler/yaml/classic/value_maps.json",
     "Add the webCoRE attribute value -> HA state value under "
     "\"attribute_values\"."),
]


def _repair_target(message: str):
    for needle, path, guidance in _REPAIR_MAP:
        if needle.lower() in (message or "").lower():
            return {"path": path, "guidance": guidance}
    return None


@router.get("/api/diagnostics/repair/{piston_id}")
async def diagnostics_repair(piston_id: str):
    """A ready-to-paste AI repair prompt: the failure, the compiler's input and
    output, AND the current contents of the data file that governs this class
    of error — so the answer can be an edit you apply, not a discussion."""
    from ..compiler import deploy as compiler_deploy
    entry = storage.load_piston(piston_id)
    if entry is None:
        return JSONResponse({"error": "no such piston"}, status_code=404)
    rec = compiler_deploy.load_statuses().get(piston_id) or {}
    message = rec.get("message", "")
    target = _repair_target(message)

    parts = [
        "I use PistonCore, which compiles webCoRE piston JSON into Home "
        "Assistant automations (YAML) or PyScript modules. A piston is failing "
        "to compile. Please fix it by giving me the exact edit to make.",
        "", "== THE FAILURE ==",
        f"Piston: {entry['name']}",
        f"Status: {rec.get('status', 'unknown')}",
        f"Message: {message}",
    ]
    if rec.get("stmt_id"):
        parts.append(f"Statement id: ${rec['stmt_id']}")

    if target:
        from .. import customize
        # read the LIVE editable copy (may hold the user's prior edits), and
        # point them at the editable /data location — never the image copy,
        # which is read-only and wiped on rebuild.
        path = customize.path(target["path"])
        parts += ["", "== THE FILE THAT GOVERNS THIS ==",
                  f"Edit this file (on your PistonCore data volume): "
                  f"{customize.editable_location(target['path'])}",
                  f"(bundled default: {target['path']})",
                  f"What to do: {target['guidance']}", "", "Current contents:"]
        try:
            text = path.read_text(encoding="utf-8")
            parts.append(text if len(text) < 20000 else text[:20000] + "\n…(truncated)")
        except OSError as exc:
            parts.append(f"(could not read: {exc})")
        parts += ["", "The full editing guide (rules + file shapes) is at "
                  "/help/editing-compiler on this PistonCore instance.",
                  "Please reply with the edited section of this file, "
                  "keeping its existing shape and style exactly. Data files are "
                  "plain JSON; template files are Jinja2/Python."]
    else:
        parts += ["", "== NO SINGLE DATA FILE GOVERNS THIS ONE ==",
                  "This error is not one of the data-file-fixable classes "
                  "(service mappings, value maps, expression functions, "
                  "attribute bindings, routing). It likely needs a change in "
                  "the compiler itself, or the piston uses something with no "
                  "Home Assistant equivalent. Explain what the piston is trying "
                  "to do and what the closest HA-native approach would be."]

    names = _artifact_list(piston_id)
    if names:
        art = compiler_deploy._DEBUG_DIR / piston_id / names[0]
        parts += ["", f"== WHAT THE COMPILER PRODUCED ({names[0]}) ==",
                  art.read_text(encoding="utf-8")]
    parts += ["", "== THE PISTON (compiler input) ==",
              json.dumps(entry["piston"], indent=1)]
    return {"text": "\n".join(parts), "target": target}


@router.get("/api/compile-status/{piston_id}")
async def compile_status(piston_id: str):
    """Latest compile/deploy record for one piston — the piston status
    screen's banner (announcement surface #2, CLAUDE.md UI split) polls this
    from dashboard/js/pistoncore-nav.js."""
    from ..compiler import deploy as compiler_deploy
    return compiler_deploy.load_statuses().get(piston_id) or {}


@router.get("/help")
async def help_index(request: Request):
    """Help index — articles listed in help_index.html. Per the CLAUDE.md UI
    split, help is drill-in only: linked from Settings and from error
    surfaces, never a place problems announce themselves."""
    return templates.TemplateResponse(request, "help_index.html", {})


@router.get("/help/compiler-debug")
async def help_compiler_debug(request: Request):
    return templates.TemplateResponse(request, "help_compiler_debug.html", {})


@router.get("/help/best-practices")
async def help_best_practices(request: Request):
    return templates.TemplateResponse(request, "help_best_practices.html", {})


@router.get("/help/editing-compiler")
async def help_editing_compiler(request: Request):
    return templates.TemplateResponse(request, "help_editing_compiler.html", {})


@router.get("/help/media-files")
async def help_media_files(request: Request):
    return templates.TemplateResponse(request, "help_media_files.html", {})


def _capture_media_base(request: Request):
    """Learn PistonCore's own LAN address from how the user reaches it. The
    speaker fetches proxied share files from here, and the browser's Host header
    is by definition an address that works on this network — so we never ask for
    it. Stored once as a default (editable in Settings). The x-file-cifs:// URL
    maps the file; this maps PistonCore. (Jeremy 2026-07-23: no setup.)"""
    try:
        settings = storage.load_settings()
        media = settings.get("media", {}) or {}
        if media.get("server_base"):
            return
        host = request.headers.get("host", "")
        if not host or host.split(":")[0] in ("localhost", "127.0.0.1", "::1"):
            return  # a speaker can't fetch from PistonCore via loopback
        scheme = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
        media["server_base"] = f"{scheme}://{host}"
        if not media.get("server_secret"):
            import secrets
            media["server_secret"] = secrets.token_hex(16)
        settings["media"] = media
        storage.save_settings(settings)
    except Exception:
        pass  # never break a page load over address capture


def _parse_share_url(url: str):
    """x-file-cifs://HOST/SHARE/Music/Siren.mp3 -> (HOST, SHARE, 'Music/Siren.mp3').
    The URL literally maps where the file is — nothing is pre-configured."""
    for scheme in ("x-file-cifs://", "smb://", "cifs://"):
        if url.startswith(scheme):
            parts = url[len(scheme):].split("/", 2)
            if len(parts) == 3 and parts[0] and parts[1] and parts[2]:
                return parts[0], parts[1], parts[2]
            return None, None, None
    return None, None, None


@router.get("/media/proxy")
@router.head("/media/proxy")
async def media_proxy(request: Request):
    """The PistonCore media server (Hubitat-hub role): stream a sound file off a
    network share straight to a speaker. The share is read from the x-file-cifs://
    URL itself as pistons run — no share is ever set up by hand. Only URLs the
    compiler SIGNED are served, so this is not an open relay. Speakers can't
    authenticate, so the signature in the query is the gate.

    NOTE: the SMB read path needs verifying against a real share on the test
    server — guest vs. credentialed access can't be exercised from dev."""
    import hmac, hashlib, mimetypes
    from fastapi.responses import StreamingResponse, Response

    src = request.query_params.get("src", "")
    sig = request.query_params.get("sig", "")
    media = storage.load_settings().get("media", {}) or {}
    secret = media.get("server_secret") or ""
    expect = (hmac.new(secret.encode(), src.encode(), hashlib.sha256).hexdigest()[:32]
              if secret else "")
    if not secret or not hmac.compare_digest(sig, expect):
        return JSONResponse({"error": "bad or missing signature"}, status_code=403)

    host, share, path = _parse_share_url(src)
    if not host:
        return JSONResponse({"error": "not a share URL"}, status_code=400)
    try:
        import smbclient
    except ImportError:
        return JSONResponse({"error": "SMB support not installed (rebuild image)"},
                            status_code=500)
    # Credentials only if this host actually needs them (lazy — most shares that
    # worked on Hubitat are guest-readable); host->{username,password} in settings.
    creds = (media.get("share_creds") or {}).get(host) or {}
    if creds.get("username"):
        smbclient.ClientConfig(username=creds["username"], password=creds.get("password") or "")
    unc = "\\\\" + host + "\\" + share + "\\" + path.replace("/", "\\")
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"

    try:
        size = smbclient.stat(unc).st_size
    except Exception as exc:
        return JSONResponse({"error": f"cannot open {share}/{path}: {exc}"}, status_code=404)

    start, end, status = 0, size - 1, 200
    headers = {"Accept-Ranges": "bytes", "Content-Type": ctype}
    rng = request.headers.get("range", "")
    if rng.startswith("bytes="):
        try:
            lo, _, hi = rng.split("=", 1)[1].partition("-")
            start = int(lo) if lo else 0
            end = int(hi) if hi else size - 1
            end = min(end, size - 1)
            status = 206
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        except ValueError:
            start, end, status = 0, size - 1, 200
    length = max(0, end - start + 1)
    headers["Content-Length"] = str(length)

    if request.method == "HEAD":
        return Response(status_code=status, headers=headers)

    def stream():
        with smbclient.open_file(unc, mode="rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                data = f.read(min(65536, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    return StreamingResponse(stream(), status_code=status, headers=headers, media_type=ctype)


@router.get("/backup")
async def import_export_page(request: Request):
    """The import/export page (CLAUDE.md UI split: paste-JSON in, pretty-print
    + copy out — also the AI-authoring door). Same URL the dashboard's
    backup/snapshot buttons redirect to. Duplicate / restore-by-code /
    import-backup-file are NOT here — they're webCoRE's own New-Piston dialog
    (front door + New Piston), per Jeremy 2026-07-17: link the native buttons
    for everything except JSON."""
    pistons = sorted(storage.list_pistons(), key=lambda e: e["name"].lower())
    return templates.TemplateResponse(request, "import_export.html", {
        "pistons": [{"id": e["id"], "name": e["name"]} for e in pistons],
    })


@router.get("/api/export/{piston_id}")
async def export_piston(piston_id: str):
    """Share-format export: the {name, meta, piston} wrapper, pretty-printed
    (the canonical PistonCore JSON share format)."""
    entry = storage.load_piston(piston_id)
    if entry is None:
        return JSONResponse({"error": "No such piston."}, status_code=404)
    wrapper = {
        "name": entry["name"],
        "meta": {"name": entry["name"],
                 "category": entry["meta"].get("category", "0"),
                 "build": entry["meta"].get("build", 1),
                 "active": entry["meta"].get("active", False)},
        "piston": entry["piston"],
    }
    return JSONResponse(wrapper)

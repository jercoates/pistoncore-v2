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

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import ha_client, storage

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
    # give each entity a friendly name derived from the device name
    ents = []
    for i, e in enumerate(entities):
        ent = dict(e)
        cls = ent.get("class", ent["platform"].replace("_", " "))
        ent["name"] = device_name if len(entities) == 1 else f"{device_name} {cls}"
        ents.append(ent)
    await ha_client.call_service("virtual", "create_device", {
        "group_name": TEST_DEVICES_GROUP, "device_name": device_name, "entities": ents})
    return {"ok": True}


@router.post("/api/test-devices/remove")
async def api_test_devices_remove(request: Request):
    body = await request.json()
    device_name = (body.get("name") or "").strip()
    if not device_name:
        return JSONResponse({"error": "No device named."}, status_code=400)
    await ha_client.call_service("virtual", "remove_device", {
        "group_name": TEST_DEVICES_GROUP, "device_name": device_name})
    return {"ok": True}


@router.post("/api/test-devices/set")
async def api_test_devices_set(request: Request):
    body = await request.json()
    entity_id = body.get("entity_id")
    if not entity_id:
        return JSONResponse({"error": "No entity."}, status_code=400)
    await _set_capability(entity_id, body.get("value"), body.get("sub"))
    return {"ok": True}


@router.get("/settings")
async def settings_page(request: Request):
    config = ha_client.get_config_for_display()
    config["first_run"] = request.query_params.get("first_run") == "1"
    config["saved"] = request.query_params.get("saved") == "1"
    # TTS engine picker (SPEAK_ACTION_SPEC: engine is a global setting) —
    # best-effort live enumeration; page still renders when HA is down
    config["tts_engine"] = storage.load_settings().get("tts_engine", "")
    config["default_band"] = storage.load_settings().get("default_band", "auto")
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
                        smb_username: str = "", smb_password: str = "", tts_engine: str = ""):
    settings = storage.load_settings()
    settings["tts_engine"] = tts_engine.strip()
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

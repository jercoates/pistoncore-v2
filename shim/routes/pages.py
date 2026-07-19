"""PistonCore's own pages (CLAUDE.md UI split): the front door landing page,
and stub routes for pages not built yet. Distinct from shim/routes/dashboard.py,
which answers the vendored webCoRE dashboard's own intf/dashboard/* API calls.
Vanilla HTML/CSS/JS + Jinja2, no frontend framework, no build step (CLAUDE.md).
"""

import json
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
        return RedirectResponse(url="/settings?first_run=1")

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
async def test_devices_stub(request: Request):
    return _stub(request, "Test Devices", (
        "Virtual test devices (switch/light/alarm/smoke/water, etc.) for "
        "quickly exercising compiler output without real hardware — not "
        "built yet. Planned alongside the compiler (milestone 5)."
    ))


@router.get("/settings")
async def settings_page(request: Request):
    config = ha_client.get_config_for_display()
    config["first_run"] = request.query_params.get("first_run") == "1"
    config["saved"] = request.query_params.get("saved") == "1"
    # TTS engine picker (SPEAK_ACTION_SPEC: engine is a global setting) —
    # best-effort live enumeration; page still renders when HA is down
    config["tts_engine"] = storage.load_settings().get("tts_engine", "")
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

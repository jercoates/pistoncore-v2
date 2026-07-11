"""PistonCore's own pages (CLAUDE.md UI split): the front door landing page,
and stub routes for pages not built yet. Distinct from shim/routes/dashboard.py,
which answers the vendored webCoRE dashboard's own intf/dashboard/* API calls.
Vanilla HTML/CSS/JS + Jinja2, no frontend framework, no build step (CLAUDE.md).
"""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
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
        "compile_status": "no compiler yet",
        "deploy_status": "no compiler yet",
    }


@router.get("/")
async def front_door(request: Request):
    tiles = [_tile_view(entry) for entry in storage.list_pistons()]
    ha_ok, ha_message = await ha_client.check_connection()
    return templates.TemplateResponse(request, "front_door.html", {
        "tiles": tiles,
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
async def settings_stub(request: Request):
    return _stub(request, "Settings", (
        "PistonCore settings (HA connection, default TTS engine, Location Mode "
        "source entity, dark/light default, import/export, backups) — not "
        "built yet. Currently hand-edited in data/config.json and "
        "data/settings.json."
    ))


@router.get("/help")
async def help_stub(request: Request):
    return _stub(request, "Help", "Documentation isn't written yet.")


@router.get("/backup")
async def backup_stub(request: Request):
    return _stub(request, "Backup", (
        "webCoRE's own Backup Piston(s) tool uses its cloud bins service, which "
        "PistonCore doesn't run — that button now lands here instead. "
        "PistonCore's own backup/restore isn't built yet; for now, piston JSON "
        "lives in data/pistons/ on disk."
    ))

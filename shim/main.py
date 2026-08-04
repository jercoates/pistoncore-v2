"""PistonCore v2 shim — FastAPI app.

Serves the vendored webCoRE dashboard (dashboard/, sealed — see CLAUDE.md)
and answers its intf/dashboard/* calls (SHIM_API_SPEC.md). No dashboard JS
is modified. Run from the repo root: uvicorn shim.main:app --reload
"""

import base64
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .routes.dashboard import router as dashboard_router
from .routes.pages import router as pages_router

REPO_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = REPO_ROOT / "dashboard"
INDEX_HTML = DASHBOARD_DIR / "index.html"

app = FastAPI(title="PistonCore v2 shim")

# Seed the editable compiler files (templates, maps, routing table, vocab)
# onto the /data volume at startup so they exist and are findable before the
# first compile — the compiler reads its knowledge from there, not the image,
# so it stays editable and survives rebuilds (COMPILER_SPEC §1).
from . import customize  # noqa: E402
customize.ensure_seeded()


@app.on_event("startup")
async def _ensure_variable_helpers_include() -> None:
    """Make sure HA is wired to load PistonCore's helper package.

    Piston variables that must survive between automations live in helper
    entities, and HA only reads them if configuration.yaml points at the
    packages folder (VARIABLES_SPEC §4; verified 2026-08-03 that the REST
    config API cannot create helpers, so a file plus reload is the route).

    Runs at startup so an install that has been updated picks it up without
    anyone visiting Settings. NEVER fatal: a read-only or unconfigured write
    target must not stop PistonCore booting — the Settings page carries the
    same action for when it does."""
    import asyncio as _asyncio
    import logging as _logging

    try:
        from . import deploy_writer
        from .compiler import helpers as helper_mod
        writer = deploy_writer.get_writer()
        result = await _asyncio.to_thread(helper_mod.ensure_include, writer)
        if result.get("changed"):
            _logging.getLogger(__name__).info(
                "PistonCore: added the variable-helper packages include to "
                "configuration.yaml")
    except Exception as exc:                                    # noqa: BLE001
        _logging.getLogger(__name__).info(
            "PistonCore: variable-helper include not applied (%s) — "
            "it can be added from Settings", exc)

# intf/dashboard/* and PistonCore's own pages (CLAUDE.md UI split) first so
# they aren't shadowed by the dashboard's SPA fallback below. "/" now serves
# the PistonCore front door, not the dashboard directly (CLAUDE.md: "Users
# live in PistonCore pages and visit the dashboard to author and inspect
# pistons") -- /connect remains the dashboard's own entry sequence.
app.include_router(dashboard_router)
app.include_router(pages_router)

app.mount("/static/pistoncore", StaticFiles(directory=str(REPO_ROOT / "static" / "pistoncore")), name="pistoncore-static")


@app.get("/connect")
def connect(request: Request):
    """Redirect to /init/<base64 of this shim's base URI> — SHIM_API_SPEC.md §3."""
    base_uri = str(request.base_url)  # already ends with '/'
    b64 = base64.b64encode(base_uri.encode("utf-8")).decode("ascii")
    return RedirectResponse(url=f"/init/{b64}")


# Static asset folders the dashboard's index.html references directly.
for _subdir in ("css", "js", "img", "fonts", "html"):
    app.mount(f"/{_subdir}", StaticFiles(directory=str(DASHBOARD_DIR / _subdir)), name=_subdir)


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    """Serve the dashboard shell for any non-file, non-intf/ path (Angular html5Mode SPA fallback)."""
    return FileResponse(INDEX_HTML)

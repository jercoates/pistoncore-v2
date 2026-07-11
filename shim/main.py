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

# pistoncore/backend/main.py
#
# PistonCore FastAPI application entry point.
# Run with: uvicorn main:app --host 0.0.0.0 --port 7777
#
# Docker mounts:
#   /pistoncore-userdata/     — piston JSON files, config, globals store
#   /pistoncore-customize/    — compiler templates, validation rules (user-editable)
#
# Frontend:
#   Served as static files from /frontend/ (relative to this file's parent directory).
#   In the Docker container this resolves to /app/frontend/.
#   The root URL (/) serves index.html.

import logging
import os
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse

import storage
from api import router
from error_logger import error_logger

# Central logging config (Gap E — Grok review)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("pistoncore")


# ---------------------------------------------------------------------------
# Startup — HA configuration.yaml setup
# DESIGN.md Section 19 exception: PistonCore appends its own include
# directives to configuration.yaml on startup if they are not present.
# ---------------------------------------------------------------------------

def _setup_ha_config():
    """
    Ensure PistonCore's include directives exist in HA's configuration.yaml.
    Appends them if missing. Sets ha_restart_required flag if lines were added.
    Creates pistoncore output subdirectories if they don't exist.
    Only runs if ha_config_path is configured in PistonCore config.
    Per DESIGN.md Section 19 exception.
    """
    config = storage.load_config()
    ha_config_path = config.get("ha_config_path", "").strip()
    if not ha_config_path:
        logger.info("ha_config_path not set — skipping configuration.yaml setup.")
        return

    config_yaml_path = os.path.join(ha_config_path, "configuration.yaml")
    if not os.path.isfile(config_yaml_path):
        logger.warning(
            f"configuration.yaml not found at {config_yaml_path} — "
            f"skipping setup. Check ha_config_path in PistonCore settings."
        )
        return

    AUTOMATION_LINE = "automation pistoncore: !include_dir_merge_list automations/pistoncore/"
    SCRIPT_LINE     = "script pistoncore: !include_dir_merge_named scripts/pistoncore/"
    COMMENT_LINE    = "# Added by PistonCore — required for deploy to work. Do not remove."

    with open(config_yaml_path, "r") as f:
        content = f.read()

    missing = []
    if AUTOMATION_LINE not in content:
        missing.append(AUTOMATION_LINE)
    if SCRIPT_LINE not in content:
        missing.append(SCRIPT_LINE)

    if not missing:
        logger.info("PistonCore configuration.yaml entries already present — no changes needed.")
    else:
        addition = f"\n{COMMENT_LINE}\n" + "\n".join(missing) + "\n"
        with open(config_yaml_path, "a") as f:
            f.write(addition)

        logger.warning(
            "PistonCore added include directives to configuration.yaml: %s. "
            "A one-time Home Assistant restart is required before script pistons "
            "can be deployed. Automation pistons work immediately.",
            ", ".join(missing),
        )

        config["ha_restart_required"] = True
        storage.save_config(config)

    # Ensure pistoncore output subdirectories exist
    # These must exist before the first deploy writes into them.
    for subdir in ["automations/pistoncore", "scripts/pistoncore", "pyscript/pistoncore"]:
        full_path = os.path.join(ha_config_path, subdir)
        os.makedirs(full_path, exist_ok=True)
        logger.info("Ensured directory exists: %s", full_path)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan — runs startup logic before serving requests."""
    _setup_ha_config()
    yield
    # Shutdown logic goes here when needed


app = FastAPI(
    title="PistonCore",
    description="WebCoRE-style visual automation builder for Home Assistant",
    version="0.9",
    lifespan=lifespan,
)

# CORS — kept permissive; tighten if exposing beyond LAN
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def _log_unhandled_exceptions(request: Request, call_next):
    """Auto-log any unhandled exception that escapes a route handler."""
    try:
        return await call_next(request)
    except Exception as exc:
        error_logger.log(
            level="error",
            code="UNHANDLED_EXCEPTION",
            message=str(exc),
            context=f"{request.method} {request.url.path}",
            stack_trace=traceback.format_exc(),
        )
        raise

app.include_router(router)


# ── Frontend static files ────────────────────────────────────────────────────
#
# The frontend/ folder lives one level up from backend/ in the repo:
#   /app/backend/main.py
#   /app/frontend/index.html
#   /app/frontend/css/style.css
#   /app/frontend/js/...
#
# Served at /frontend/* so index.html can reference /frontend/css/style.css
# and /frontend/js/*.js with absolute paths.

_HERE = Path(__file__).parent                   # /app (backend/ files land here)
_FRONTEND = _HERE / "frontend"                  # /app/frontend/

if _FRONTEND.exists():
    app.mount("/frontend", StaticFiles(directory=str(_FRONTEND)), name="frontend")

    @app.get("/", include_in_schema=False)
    def serve_index():
        """Serve the SPA shell with BASE_URL injected into <head> (GAP-S29-6)."""
        index_path = _FRONTEND / "index.html"
        html = index_path.read_text()
        # Read from env var so Unraid/remote deployments don't need localhost.
        # Set PISTONCORE_BASE_URL in docker-compose.yml, e.g. http://192.168.1.10:7777
        base_url = os.environ.get("PISTONCORE_BASE_URL", "http://localhost:7777")
        base_url_script = f'<script>window.PISTONCORE_BASE_URL = "{base_url}";</script>'
        html = html.replace("</head>", f"{base_url_script}\n</head>", 1)
        return HTMLResponse(content=html)

else:
    # Frontend not present — return JSON root for API-only mode
    @app.get("/")
    def root():
        return {"status": "ok", "app": "PistonCore", "version": "0.9", "frontend": "not found"}


# ── WebSocket stub ───────────────────────────────────────────────────────────
#
# Accepts connections and keeps them open. Full trace/log streaming in S2-x.
# Frontend connects on load — without this stub it gets an immediate 404 and
# may retry aggressively. (GAP-S29-7)

@app.websocket("/ws")
async def websocket_stub(websocket: WebSocket):
    """WebSocket stub — accepts and holds connections. Full impl in S2-x."""
    await websocket.accept()
    logger.info("WebSocket client connected")
    try:
        while True:
            await websocket.receive_text()  # stay alive, discard incoming messages
    except Exception:
        pass  # client disconnected — normal teardown

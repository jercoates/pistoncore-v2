# pistoncore/backend/api.py
#
# PistonCore REST API endpoints.
# All routes are collected in a single router included by main.py.
#
# Endpoint summary:
#   GET    /pistons                        — list all pistons
#   GET    /pistons/{id}                   — get one piston
#   POST   /pistons                        — create piston
#   PUT    /pistons/{id}                   — update piston
#   DELETE /pistons/{id}                   — delete piston
#   POST   /pistons/{id}/compile           — compile piston, return YAML strings
#   POST   /pistons/{id}/deploy            — compile + send to companion for HA write
#   GET    /globals                        — list global variables
#   POST   /globals                        — create global variable
#   PUT    /globals/{id}                   — update global variable
#   DELETE /globals/{id}                   — delete global variable
#   GET    /config                         — get runtime config
#   PUT    /config                         — update runtime config (clears HA cache)
#   GET    /health                         — health check
#   GET    /devices                        — all HA entities (cached 60s)
#   GET    /devices/refresh                — force cache refresh
#   GET    /device/{entity_id}/capabilities — capabilities with attribute_type detection
#   GET    /device/{entity_id}/services    — domain services with field schema

import hashlib
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Security, Body
from fastapi.security import APIKeyHeader

import storage
from compiler import Compiler
from ha_client import ha_client, HAClientError
import context_builder
from context_builder import ContextBuildError

# ---------------------------------------------------------------------------
# API key authentication
# Protects all endpoints with a shared secret.
# Set PISTONCORE_API_KEY in docker-compose.yml before exposing beyond localhost.
# Send as request header:  X-API-Key: <your-key>
# If the env var is not set, the check is skipped (dev/test convenience only).
# ---------------------------------------------------------------------------

_API_KEY = os.environ.get("PISTONCORE_API_KEY", "")
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _verify_api_key(key: str | None = Security(_api_key_header)) -> None:
    if not _API_KEY:
        return  # no key configured -- open access, dev/test only
    if key != _API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


router = APIRouter(dependencies=[Depends(_verify_api_key)])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_compiler() -> Compiler:
    config = storage.load_config()
    return Compiler(template_dir=config["template_dir"])


def _compile(piston: dict) -> dict:
    """
    Build fat compiler context and run the compiler against a piston.
    Returns a structured result with automation_yaml, script_yaml,
    warnings, errors, success.

    Aborts with a structured error if entity_states cannot be fetched
    (ContextBuildError). All other context fetch failures degrade gracefully.
    """
    try:
        context = context_builder.build_compiler_context(piston)
    except ContextBuildError as e:
        return {
            "automation_yaml": None,
            "script_yaml":     None,
            "warnings":        [],
            "errors":          [{"level": "error", "code": "CONTEXT_BUILD_ERROR", "message": str(e), "context": None}],
            "success":         False,
        }

    compiler = _get_compiler()

    try:
        result = compiler.compile_piston(context)
    except Exception as e:
        # compile_piston() catches CompilerError internally and never re-raises it.
        # This catches Jinja2 TemplateError and any other unexpected failure (GAP-S29-13).
        return {
            "automation_yaml": None,
            "script_yaml":     None,
            "warnings":        [],
            "errors":          [{"level": "error", "code": "COMPILER_INTERNAL_ERROR", "message": str(e), "context": None}],
            "success":         False,
        }

    return {
        "automation_yaml": result.automation_yaml,
        "script_yaml":     result.script_yaml,
        "warnings":        [{"level": m.level, "code": m.code, "message": m.message, "context": m.context} for m in result.warnings],
        "errors":          [{"level": m.level, "code": m.code, "message": m.message, "context": m.context} for m in result.errors],
        "success":         len(result.errors) == 0,
    }


# ---------------------------------------------------------------------------
# Piston helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Piston endpoints
# ---------------------------------------------------------------------------

@router.get("/pistons")
def list_pistons():
    """List all pistons. Returns name, id, mode, modified_at — not full JSON."""
    pistons = storage.list_pistons()
    return [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "description": p.get("description", ""),
            "mode": p.get("mode", "single"),
            "folder": p.get("folder", ""),
            "modified_at": p.get("modified_at"),
            "created_at": p.get("created_at"),
            "deployed": p.get("deployed", False),
            "stale": p.get("stale", False),
        }
        for p in pistons
    ]


CURRENT_LOGIC_VERSION = 2
CURRENT_UI_VERSION = 1


@router.get("/pistons/{piston_id}")
def get_piston(piston_id: str):
    """Get the full piston JSON for a single piston."""
    piston = storage.get_piston(piston_id)
    if piston is None:
        raise HTTPException(status_code=404, detail=f"Piston '{piston_id}' not found.")

    # Guard against pistons from a newer PistonCore than this instance.
    # Older/missing logic_version values load fine — the editor and wizard
    # write logic_version on save, so pistons self-upgrade on edit.
    logic_v = piston.get("logic_version")
    ui_v = piston.get("ui_version", CURRENT_UI_VERSION)

    if logic_v is not None and logic_v > CURRENT_LOGIC_VERSION:
        raise HTTPException(
            status_code=409,
            detail=f"Piston '{piston_id}' was created with a newer logic version "
                   f"({logic_v}) than this PistonCore supports ({CURRENT_LOGIC_VERSION}). "
                   f"Update PistonCore before opening this piston.",
        )

    if ui_v > CURRENT_UI_VERSION:
        raise HTTPException(
            status_code=409,
            detail=f"Piston '{piston_id}' was created with a newer UI version "
                   f"({ui_v}) than this PistonCore supports ({CURRENT_UI_VERSION}). "
                   f"Update PistonCore before opening this piston.",
        )

    return piston


@router.post("/pistons", status_code=201)
def create_piston(piston: dict = Body(...)):
    """
    Create a new piston. Assigns an ID and timestamps.
    Returns the saved piston.
    """
    # Don't allow the client to set an ID or compile_target on create
    piston.pop("id", None)
    piston.pop("compile_target", None)  # compiler owns this — never user-supplied

    # Apply spec-required defaults for any fields the client omitted
    piston.setdefault("name", "Untitled Piston")
    piston.setdefault("description", "")
    piston.setdefault("folder", None)
    piston.setdefault("mode", "single")
    piston.setdefault("enabled", True)
    piston.setdefault("logic_version", CURRENT_LOGIC_VERSION)
    piston.setdefault("ui_version", CURRENT_UI_VERSION)
    piston.setdefault("variables", [])
    piston.setdefault("triggers", [])
    piston.setdefault("conditions", [])
    piston.setdefault("restrictions", [])
    piston.setdefault("statements", [])
    saved = storage.save_piston(piston)
    return saved


@router.put("/pistons/{piston_id}")
def update_piston(piston_id: str, piston: dict = Body(...)):
    """
    Update an existing piston. The piston_id in the URL is authoritative.
    Does NOT compile on save — compile is a separate explicit action per
    DESIGN.md Section 18. Save is always fast and never blocked by compiler state.
    Returns the saved piston.
    """
    existing = storage.get_piston(piston_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Piston '{piston_id}' not found.")

    piston["id"] = piston_id  # enforce ID from URL
    piston.pop("compile_target", None)  # compiler owns this — never user-supplied
    saved = storage.save_piston(piston)
    return {"piston": saved}


@router.delete("/pistons/{piston_id}", status_code=204)
def delete_piston(piston_id: str):
    """
    Delete a piston from storage and remove its compiled HA files if present.
    Compiled file removal is best-effort — missing files are silently ignored.
    Only removes files that contain PistonCore's own signature header so we
    never touch files we didn't create (DESIGN.md Section 19).
    HA reload is called after removal so the automation/script stops running.
    """
    # Load piston before deleting so we have the id for file paths
    piston = storage.get_piston(piston_id)
    if piston is None:
        raise HTTPException(status_code=404, detail=f"Piston '{piston_id}' not found.")

    storage.delete_piston(piston_id)

    # Remove compiled HA files if ha_config_path is configured
    config = storage.load_config()
    ha_config_path = config.get("ha_config_path", "").strip()
    if ha_config_path:
        automation_path = os.path.join(
            ha_config_path, "automations", "pistoncore", f"pistoncore_{piston_id}.yaml"
        )
        script_path = os.path.join(
            ha_config_path, "scripts", "pistoncore", f"pistoncore_{piston_id}.yaml"
        )
        removed_any = False
        for path in [automation_path, script_path]:
            if os.path.isfile(path):
                # Safety check — only remove files PistonCore created
                try:
                    with open(path) as f:
                        header = f.read(200)
                    if "MANAGED BY PISTONCORE" in header:
                        os.remove(path)
                        removed_any = True
                except OSError:
                    pass  # Best-effort — log in future

        # Reload HA so the deleted automation/script stops running
        if removed_any:
            try:
                ha_client.call_service("automation", "reload")
            except ha_client.HAClientError:
                pass  # Best-effort — piston is deleted from PistonCore regardless
            try:
                ha_client.call_service("script", "reload")
            except ha_client.HAClientError:
                pass


# ---------------------------------------------------------------------------
# Compile endpoint
# ---------------------------------------------------------------------------

@router.post("/pistons/{piston_id}/compile")
def compile_piston(piston_id: str):
    """
    Compile a piston and return the YAML strings.
    Does NOT write anything to HA. Safe to call any time.
    Use this to preview compiled output before deploying.
    """
    piston = storage.get_piston(piston_id)
    if piston is None:
        raise HTTPException(status_code=404, detail=f"Piston '{piston_id}' not found.")

    result = _compile(piston)
    return result


# ---------------------------------------------------------------------------
# Deploy endpoint
# ---------------------------------------------------------------------------

@router.post("/pistons/{piston_id}/deploy")
def deploy_piston(piston_id: str, force: bool = False):
    """
    Compile a piston and write output files to HA, then call reload services.
    Implements the two-step save model per DESIGN.md Section 18:
      Step 1: PUT /pistons/{id}  — saves JSON to Docker volume (always fast)
      Step 2: POST /pistons/{id}/deploy  — compiles + writes to HA

    force=true skips the hash mismatch check (user confirmed overwrite).

    Returns structured result: deployed, written_paths, reload_errors,
    compile_result, message.

    Script pistons require ha_restart_required=false before deploying —
    set by _setup_ha_config() on startup after adding configuration.yaml lines.
    Automation pistons are unaffected by this flag.
    """
    config = storage.load_config()
    ha_config_path = config.get("ha_config_path", "").strip()

    if not ha_config_path:
        raise HTTPException(
            status_code=503,
            detail=(
                "ha_config_path is not configured. Set the path to your HA "
                "config directory in PistonCore settings before deploying."
            ),
        )

    piston = storage.get_piston(piston_id)
    if piston is None:
        raise HTTPException(status_code=404, detail=f"Piston '{piston_id}' not found.")

    # Compile in memory — never writes to HA (DESIGN.md Section 18 Stage 2)
    compile_result = _compile(piston)
    if not compile_result["success"]:
        return {
            "deployed": False,
            "reason": "compile_failed",
            "compile_result": compile_result,
        }

    piston_uuid     = piston["id"]
    automation_yaml = compile_result["automation_yaml"]
    script_yaml     = compile_result["script_yaml"]

    # Script pistons need a full HA restart after configuration.yaml was updated.
    # Automation pistons are unaffected — automation.reload is sufficient.
    # DESIGN.md Section 19 exception.
    if script_yaml and config.get("ha_restart_required"):
        return {
            "deployed": False,
            "reason": "ha_restart_required",
            "message": (
                "PistonCore updated your configuration.yaml on startup to register "
                "its script folder. A one-time Home Assistant restart is required "
                "before script pistons can be deployed. "
                "Automation pistons can be deployed immediately without a restart."
            ),
            "compile_result": compile_result,
        }

    # Resolve output paths — COMPILER_SPEC Section 5
    automation_dir  = os.path.join(ha_config_path, "automations", "pistoncore")
    script_dir      = os.path.join(ha_config_path, "scripts",     "pistoncore")
    automation_path = os.path.join(automation_dir, f"pistoncore_{piston_uuid}.yaml")
    script_path     = os.path.join(script_dir,     f"pistoncore_{piston_uuid}.yaml")

    os.makedirs(automation_dir, exist_ok=True)
    os.makedirs(script_dir,     exist_ok=True)

    # Hash mismatch check — DESIGN.md Section 13, COMPILER_SPEC Section 6.
    # If the deployed file was manually edited since last deploy, refuse to
    # overwrite unless force=true.
    if not force:
        for path, content in [
            (automation_path, automation_yaml),
            (script_path,     script_yaml),
        ]:
            if content and os.path.isfile(path):
                if _check_hash_mismatch(path):
                    return {
                        "deployed": False,
                        "reason": "hash_mismatch",
                        "path": path,
                        "message": (
                            f"The deployed file at {path} was manually edited "
                            f"since last deploy. Deploy with force=true to overwrite, "
                            f"or discard your manual changes."
                        ),
                        "compile_result": compile_result,
                    }

    # Write files to HA config directory — DESIGN.md Section 18 Stage 4
    written_paths = []
    try:
        if automation_yaml:
            with open(automation_path, "w") as f:
                f.write(automation_yaml)
            written_paths.append(automation_path)

        if script_yaml:
            with open(script_path, "w") as f:
                f.write(script_yaml)
            written_paths.append(script_path)

    except OSError as e:
        return {
            "deployed": False,
            "reason": "file_write_failed",
            "message": (
                f"Could not write to HA config directory: {e}. "
                f"Check that ha_config_path is correct and the directory is "
                f"writable (e.g. Samba share is mounted and accessible)."
            ),
            "compile_result": compile_result,
        }

    # Call HA reload services — DESIGN.md Section 18 Stage 4
    # automation.reload picks up new files immediately, no HA restart needed.
    # script.reload same — but only if configuration.yaml was already set up.
    reload_errors = []

    try:
        ha_client.call_service("automation", "reload")
    except ha_client.HAClientError as e:
        reload_errors.append(f"automation.reload failed: {e}")

    if script_yaml:
        try:
            ha_client.call_service("script", "reload")
            # First successful script deploy proves HA loaded the config —
            # clear the restart-required flag. DESIGN.md Section 19.
            if config.get("ha_restart_required"):
                config["ha_restart_required"] = False
                storage.save_config(config)
        except ha_client.HAClientError as e:
            reload_errors.append(f"script.reload failed: {e}")

    # Mark piston as deployed in storage
    piston["deployed"] = True
    storage.save_piston(piston)

    deployed = len(reload_errors) == 0
    return {
        "deployed": deployed,
        "written_paths": written_paths,
        "reload_errors": reload_errors,
        "compile_result": compile_result,
        "message": (
            "Deployed successfully."
            if deployed
            else "Files written but HA reload failed — see reload_errors."
        ),
    }


def _check_hash_mismatch(existing_path: str) -> bool:
    """
    Read the pc_hash from an existing deployed file's header.
    Recompute the hash of the file body and compare.
    Returns True if the file was manually edited since PistonCore last wrote it.
    Returns False if hashes match, file is unreadable, or no pc_hash found.
    COMPILER_SPEC Section 6 / DESIGN.md Section 13.
    """
    try:
        with open(existing_path, "r") as f:
            existing_content = f.read()
    except OSError:
        return False  # Can't read — allow overwrite

    # Extract pc_hash from the signature header line
    stored_hash = None
    for line in existing_content.splitlines():
        if "pc_hash:" in line:
            parts = line.split("pc_hash:")
            if len(parts) > 1:
                stored_hash = parts[1].strip().split()[0]
            break

    if stored_hash is None:
        return False  # No PistonCore signature — not our file, don't block

    # Recompute hash of the body (everything after the comment header lines)
    lines = existing_content.splitlines(keepends=True)
    body_start = 0
    in_header = True
    for i, line in enumerate(lines):
        if in_header and (line.strip().startswith("#") or line.strip() == ""):
            body_start = i + 1
        else:
            in_header = False
            break
    body = "".join(lines[body_start:])
    actual_hash = hashlib.sha256(body.encode()).hexdigest()

    # Mismatch means the body changed after PistonCore wrote it — manual edit
    return actual_hash != stored_hash


# ---------------------------------------------------------------------------
# Globals endpoints
# ---------------------------------------------------------------------------

@router.get("/globals")
def list_globals():
    """List all global variables."""
    return storage.load_globals()


@router.post("/globals", status_code=201)
def create_global(body: dict = Body(...)):
    """
    Create a global variable.
    Body: { "name": str, "var_type": str, "value": str|list[str], "description": str, "used_by": list }
    var_type values: string | integer | decimal | boolean | datetime | device | dynamic
    var_type "device": value is a list of friendly name strings (not entity IDs).
    All other types: value is a plain string.
    used_by: list of {uuid, name} objects — maintained by the frontend, stored here as-is.
    """
    globals_store = storage.load_globals()
    global_id = str(uuid.uuid4()).replace("-", "")[:8]
    var_type = body.get("var_type", "string")
    globals_store[global_id] = {
        "id":          global_id,
        "name":        body.get("name", "new_global"),
        "var_type":    var_type,
        "value":       body.get("value", [] if var_type == "device" else ""),
        "description": body.get("description", ""),
        "used_by":     body.get("used_by", []),
    }
    storage.save_globals(globals_store)
    return globals_store[global_id]


@router.put("/globals/{global_id}")
def update_global(global_id: str, body: dict = Body(...)):
    """
    Update an existing global variable.
    Body: { "name": str, "var_type": str, "value": str|list[str], "description": str, "used_by": list }
    Only fields present in the body are updated — missing fields are preserved.
    var_type "device": value is a list of friendly name strings (not entity IDs).
    used_by: list of {uuid, name} objects — frontend maintains this, backend stores as-is.
    Pistons referencing this global are marked stale if var_type or value changed.
    """
    globals_store = storage.load_globals()
    if global_id not in globals_store:
        raise HTTPException(status_code=404, detail=f"Global '{global_id}' not found.")

    existing = globals_store[global_id]
    value_changed = (
        body.get("var_type", existing["var_type"]) != existing["var_type"]
        or body.get("value", existing["value"]) != existing["value"]
    )

    existing["name"]        = body.get("name",        existing["name"])
    existing["var_type"]    = body.get("var_type",    existing["var_type"])
    existing["value"]       = body.get("value",       existing["value"])
    existing["description"] = body.get("description", existing["description"])
    if "used_by" in body:
        existing["used_by"] = body["used_by"]

    globals_store[global_id] = existing
    storage.save_globals(globals_store)

    if value_changed:
        _mark_pistons_stale_for_global(global_id)

    return globals_store[global_id]


@router.delete("/globals/{global_id}", status_code=204)
def delete_global(global_id: str):
    """
    Delete a global variable from the store.
    The companion removes the corresponding HA helper.
    Pistons referencing this global are marked stale.
    """
    globals_store = storage.load_globals()
    if global_id not in globals_store:
        raise HTTPException(status_code=404, detail=f"Global '{global_id}' not found.")
    del globals_store[global_id]
    storage.save_globals(globals_store)

    # Mark all pistons that reference this global as stale
    _mark_pistons_stale_for_global(global_id)


def _mark_pistons_stale_for_global(global_id: str):
    """Mark any piston referencing the deleted global as stale."""
    for piston in storage.list_pistons():
        piston_json = str(piston)
        # FRAGILE HEURISTIC: string scan of serialized piston dict.
        # Produces false positives if global_id appears in unrelated text fields.
        # Real fix: walk piston statement tree checking global_id references.
        # See GAP-S29-15 — full fix in S4-8.
        if global_id in piston_json:
            piston["stale"] = True
            storage.save_piston(piston)


# ---------------------------------------------------------------------------
# Config endpoints
# ---------------------------------------------------------------------------

@router.get("/config")
def get_config():
    """Get runtime config. Redacts the HA token."""
    config = storage.load_config()
    redacted = dict(config)
    if redacted.get("ha_token"):
        redacted["ha_token"] = "***"
    return redacted


@router.put("/config")
def update_config(body: dict = Body(...)):
    """Update runtime config. Merges with existing config."""
    config = storage.load_config()
    config.update(body)
    storage.save_config(config)
    # Invalidate HA cache — ha_url or ha_token may have changed
    ha_client.invalidate_cache()
    return {"saved": True}


# ---------------------------------------------------------------------------
# HA device endpoints
# ---------------------------------------------------------------------------

@router.get("/devices")
def list_devices():
    """
    Return all HA entities with friendly name, area, and domain.
    Result is cached for 60 seconds.

    Response: list of {
      entity_id, friendly_name, domain, area (nullable), device_id (nullable)
    }

    Raises 503 if HA is unreachable or token is not configured.
    """
    try:
        return ha_client.get_devices()
    except HAClientError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/devices/refresh")
def refresh_device_cache():
    """
    Invalidate the HA device/capability cache and force a fresh fetch.
    Call this after pairing new devices in HA or changing ha_url/ha_token.
    """
    ha_client.invalidate_cache()
    try:
        devices = ha_client.get_devices()
        return {"refreshed": True, "device_count": len(devices)}
    except HAClientError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/device/{entity_id:path}/capabilities")
def get_device_capabilities(entity_id: str):
    """
    Return capabilities for a single entity, with attribute_type detection
    per WIZARD_SPEC priority order.

    entity_id must be the full HA entity ID, e.g. "binary_sensor.front_door".
    Use entity_id:path to allow dots and slashes in the path segment.

    Response: {
      entity_id, state, domain, device_class,
      capabilities: [{ name, attribute_type, device_class, unit, options }]
    }
    """
    try:
        return ha_client.get_capabilities(entity_id)
    except HAClientError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/device/{entity_id:path}/services")
def get_device_services(entity_id: str):
    """
    Return all services available for a device's domain, with parameter schema.
    Used by the wizard action step to populate the service picker.

    Response: list of {
      service, label, description,
      fields: [{ name, label, description, type, required, min?, max?, unit?, options? }]
    }
    """
    try:
        return ha_client.get_services(entity_id)
    except HAClientError as e:
        raise HTTPException(status_code=503, detail=str(e))


# ---------------------------------------------------------------------------
# Piston duplicate / import / export stubs
# ---------------------------------------------------------------------------

@router.post("/pistons/{piston_id}/duplicate", status_code=501)
def duplicate_piston(piston_id: str):
    """Duplicate a piston. Not yet implemented — returns 501. See S2-x."""
    raise HTTPException(status_code=501, detail="Duplicate not yet implemented.")


@router.post("/pistons/import", status_code=201)
def import_piston(piston: dict = Body(...)):
    """
    Import a piston from Snapshot or Backup JSON (DESIGN.md Section 6.11).
    Assigns a fresh ID, applies v2 spec defaults, sets timestamps, and saves.
    Returns the saved piston.

    Role mapping — collecting unique roles and writing entity_ids onto matching
    nodes — is handled by the frontend import dialog before this call. The backend
    persists whatever it receives. Snapshots arrive with empty entity_ids; Backups
    arrive with entity_ids already populated. Either way the backend just saves.
    """
    # Always assign a fresh ID on import — DESIGN.md Section 6.11 Step 5
    piston.pop("id", None)
    piston.pop("compile_target", None)  # compiler owns this

    piston.setdefault("name", "Imported Piston")
    piston.setdefault("description", "")
    piston.setdefault("folder", None)
    piston.setdefault("mode", "single")
    piston.setdefault("enabled", True)
    piston.setdefault("logic_version", CURRENT_LOGIC_VERSION)
    piston.setdefault("ui_version", CURRENT_UI_VERSION)
    piston.setdefault("variables", [])
    piston.setdefault("triggers", [])
    piston.setdefault("conditions", [])
    piston.setdefault("restrictions", [])
    piston.setdefault("statements", [])

    now = datetime.now(timezone.utc).isoformat()
    piston["created_at"] = now
    piston["modified_at"] = now

    saved = storage.save_piston(piston)
    return saved


@router.get("/pistons/{piston_id}/export", status_code=501)
def export_piston(piston_id: str):
    """Export a piston as Snapshot JSON. Not yet implemented — returns 501. See S2-x."""
    raise HTTPException(status_code=501, detail="Export not yet implemented.")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@router.get("/health")
def health():
    """Health check endpoint. Returns ok if the backend is running."""
    return {"status": "ok"}

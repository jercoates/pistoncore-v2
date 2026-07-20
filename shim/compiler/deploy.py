"""DEPLOY + LIFECYCLE (COMPILER_DECISIONS_DEPLOY §1-§5): compile-on-save,
write through the configured write target, reload HA, record the result.

Rules honored here:
- A failed compile NEVER blocks the save and NEVER touches the previously
  deployed artifact (§1) — it only records the error for the two UI surfaces.
- Pause is HA-NATIVE (DECISION Jeremy 2026-07-18): automation.turn_off/turn_on,
  matching webCoRE semantics (pause = stop firing, piston persists) — the file
  stays deployed but disabled, entity + trace history survive, and it's the
  same mechanism a future in-piston "Pause piston" command must use anyway.
  Safety fallback (Jeremy's condition): if HA can't find/disable the
  automations (broken compile, dead connection), pause removes the file
  instead — Pause always works. File deletion otherwise remains only for
  piston deletion, pyscript routing, and rename cleanup.
- Rename-safe (§4): the deployed filename is recorded per piston; a rename
  deletes the old file before writing the new one.
- Reload (§5): automation.reload first, homeassistant.reload_all as fallback
  — this doubles as the open dev-HA test for new-file pickup.
- Debug evidence (Jeremy, 2026-07-18 — compiler-tuning infrastructure): every
  emitted artifact (including partial output from a mid-emit crash) is kept
  timestamped in data/compile_debug/<piston_id>/, and a deploy is only
  "deployed" once the emitted automations verifiably appear in HA after the
  reload — HA silently skips malformed files while its reload call still
  reports success, so absence => status "error: HA rejected the compiled
  YAML" with HA's own log lines attached.
"""

import asyncio
import json
import re
import time

from .. import deploy_writer, device_pipeline, ha_client, storage
from . import compile_piston
from .errors import CompilerError

_AUTOMATIONS_DIR = "pistoncore/automations"
_PYSCRIPT_DIR = "pyscript/scripts/pistoncore"  # research §2: only sanctioned autoload subdir
_STATUS_FILE = storage.DATA_DIR / "compile_status.json"
_DEBUG_DIR = storage.DATA_DIR / "compile_debug"
_DEBUG_KEEP = 25  # newest artifacts kept per piston


def _keep_artifact(piston_id: str, text: str, suffix: str) -> str:
    """Compiler-tuning evidence (Jeremy, 2026-07-18): EVERY output the
    compiler produces — good, malformed, or half-finished — is preserved
    here, timestamped, untouched by recompiles/pause/rename cleanup. When a
    compile misbehaves, the actual emitted code (and its history, for
    diffing good vs bad) is the primary clue."""
    d = _DEBUG_DIR / piston_id
    d.mkdir(parents=True, exist_ok=True)
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}{suffix}"
    (d / name).write_text(text, encoding="utf-8")
    for old in sorted(d.iterdir())[:-_DEBUG_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass
    return f"compile_debug/{piston_id}/{name}"


def _rollback(writer, prev: dict, filename: str) -> str:
    """A new file failed HA's config check AFTER overwriting the old one —
    restore the previous good compile from its kept debug artifact so the
    on-disk config is valid again (§1: a failed compile never costs the user
    the previously deployed artifact). No prior good version -> just retract
    the bad file."""
    try:
        prev_art = prev.get("artifact")
        if (prev.get("status") == "deployed" and prev.get("file") and prev_art
                and (storage.DATA_DIR / prev_art).exists()):
            writer.write(prev["file"],
                         (storage.DATA_DIR / prev_art).read_text(encoding="utf-8"))
            if filename != prev["file"]:
                writer.delete(filename)
            return f"previous good version restored ({prev['file']})"
        writer.delete(filename)
        return "bad file removed, no previous version to restore"
    except Exception as exc:
        return f"ROLLBACK FAILED: {exc} — fix {filename} by hand or re-save the piston"


async def _ha_log_excerpt(filename: str) -> str:
    """HA's own words about why it rejected our file — pulled from its
    system log right after a failed pickup."""
    try:
        entries = await ha_client.get_system_log()
    except Exception as exc:
        return f"(could not read HA's error log: {exc})"
    needle = filename.rsplit("/", 1)[-1]
    hits = []
    for e in entries:
        text = " ".join(str(m) for m in e.get("message", []))
        blob = f"{text} {e.get('source') or ''} {e.get('exception') or ''}"
        if needle in blob or "pistoncore" in blob.lower():
            hits.append(text[:300])
    return "; ".join(hits[-3:]) or "(no matching entries in HA's error log)"


def load_statuses() -> dict:
    """Per-piston compile/deploy status — its own store, NEVER written into
    the piston entry files (read-only-compiler rule, hard: the compiler and
    its lifecycle machinery do not touch piston JSON or its files at all)."""
    return storage.read_json_safe(_STATUS_FILE, dict, "compile_status.json")

_reg_cache: dict = {"t": 0.0, "map": None}


async def _resolution_map() -> dict:
    if _reg_cache["map"] is None or time.time() - _reg_cache["t"] > 60:
        registries = await ha_client.fetch_registries()
        payload = device_pipeline.build_device_payload(registries)
        _reg_cache["map"] = payload["resolution_map"]
        _reg_cache["t"] = time.time()
    return _reg_cache["map"]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40] or "piston"


def _record(piston_id: str, **fields) -> dict:
    statuses = load_statuses()
    rec = {"ts": int(time.time() * 1000), **fields}
    statuses[piston_id] = rec
    storage.write_json_atomic(_STATUS_FILE, statuses)
    return rec


async def _automation_entities(auto_ids: list) -> list[str]:
    """entity_ids HA assigned to our emitted automations — matched via each
    automation state's attributes.id (== the YAML `id:` field we emit),
    never by guessing the alias slug."""
    wanted = set(auto_ids)
    states = await ha_client.get_states()
    return [s["entity_id"] for s in states
            if s["entity_id"].startswith("automation.")
            and s.get("attributes", {}).get("id") in wanted]


async def _deploy_pyscript(piston_id: str, name: str, prev: dict, writer,
                           result: dict) -> dict:
    """PyScript-band deploy: write the module into pyscript's autoloaded
    scripts/pistoncore/ folder (research §2), reload just that piston's
    global context, then PROVE the module loaded by its @service registration
    (pyscript.pistoncore_<id>_execute) appearing — a module with a runtime
    load error is silently skipped otherwise, same trap as YAML reload."""
    filename = f"{_PYSCRIPT_DIR}/{_slug(name)}_{piston_id[:8]}.py"
    artifact = _keep_artifact(piston_id, result["code"], ".py")
    try:
        if prev.get("file") and prev["file"] != filename:
            writer.delete(prev["file"])  # rename- AND band-switch-safe cleanup
        writer.write(filename, result["code"])
    except Exception as exc:
        return _record(piston_id, status="error", artifact=artifact,
                       message=f"deploy write failed: {exc}")

    stem = filename.rsplit("/", 1)[-1][:-3]
    try:
        await ha_client.call_service(
            "pyscript", "reload", {"global_ctx": f"scripts.pistoncore.{stem}"})
    except Exception as exc:
        return _record(piston_id, status="error", file=filename, artifact=artifact,
                       message=("this piston needs PyScript, and reloading it failed — "
                                f"is the PyScript integration installed (HACS)? {exc}"))

    service_name = f"pistoncore_{piston_id}_execute"
    present = False
    try:
        for _ in range(4):
            services = await ha_client.get_services()
            if service_name in (services.get("pyscript") or {}):
                present = True
                break
            await asyncio.sleep(1)
    except Exception:
        pass  # verification unavailable is not proof of failure
    if not present:
        ha_says = await _ha_log_excerpt(filename)
        return _record(piston_id, status="error", file=filename, artifact=artifact,
                       message=f"PyScript did not load the module — HA's log: {ha_says}")

    return _record(piston_id, status="deployed", file=filename, band="pyscript",
                   reload="pyscript.reload", artifact=artifact, auto_ids=[],
                   config_check="n/a (pyscript module)",
                   reasons=result.get("reasons", [])[:3])


async def _verify_and_enable(auto_ids: list) -> tuple[str, str]:
    """After writing + reloading, PROVE HA actually swallowed the file —
    "reload succeeded" alone is a lie of omission: HA skips a malformed file,
    logs the problem, and the reload call still reports success. Returns
    (verdict, note): "ok" all automations present + turned on; "rejected"
    some/all missing after retries (compiled YAML presumed bad); "unverified"
    couldn't check (HA unreachable — NOT evidence the YAML is bad).
    turn_on is explicit because HA restores disabled state across reloads."""
    if not auto_ids:
        return "unverified", "no automation ids"
    entities: list = []
    try:
        for _ in range(4):
            entities = await _automation_entities(auto_ids)
            if len(entities) >= len(set(auto_ids)):
                break
            await asyncio.sleep(1)
    except Exception as exc:
        return "unverified", f"could not verify (HA states unavailable: {exc})"
    if len(entities) < len(set(auto_ids)):
        return "rejected", f"{len(entities)}/{len(set(auto_ids))} automations appeared after reload"
    try:
        await ha_client.call_service("automation", "turn_on", {"entity_id": entities})
    except Exception as exc:
        return "unverified", f"present but turn_on failed: {exc}"
    return "ok", "on"


async def _reload_ha() -> str:
    try:
        await ha_client.call_service("automation", "reload")
        return "automation.reload"
    except Exception:
        try:
            await ha_client.call_service("homeassistant", "reload_all")
            return "reload_all (automation.reload failed)"
        except Exception as exc:
            return f"reload FAILED: {exc}"


async def compile_and_deploy(piston_id: str) -> dict:
    """Runs after every successful save / pause / resume / import. Never
    raises — every outcome lands in meta.compile for the UI surfaces."""
    entry = storage.load_piston(piston_id)
    if entry is None:
        return {"status": "missing"}
    name = entry["name"]
    prev = load_statuses().get(piston_id, {})
    filename = f"{_AUTOMATIONS_DIR}/{_slug(name)}_{piston_id[:8]}.yaml"

    def _remove_deployed(writer, why: str):
        for f in {prev.get("file"), filename} - {None}:
            try:
                writer.delete(f)
            except Exception:
                pass
        return why

    # Paused -> HA-native disable first (see module docstring). No writer
    # needed on this path, so a broken write target can't block a pause.
    if not entry["meta"].get("active", True):
        auto_ids = prev.get("auto_ids") or []
        why = "no deployed automation on record"
        if auto_ids:
            try:
                entities = await _automation_entities(auto_ids)
                if entities:
                    await ha_client.call_service("automation", "turn_off",
                                                 {"entity_id": entities})
                    return _record(piston_id, status="paused",
                                   message="paused — automation disabled in HA",
                                   file=prev.get("file"), auto_ids=auto_ids)
                why = "automation entities not found in HA"
            except Exception as exc:
                why = str(exc)
        # Safety fallback: Pause must always work — remove the file instead.
        try:
            writer = deploy_writer.get_writer()
        except deploy_writer.WriteTargetError as exc:
            return _record(piston_id, status="error",
                           message=f"pause failed: {why}; file fallback also failed — write target: {exc}")
        _remove_deployed(writer, "paused")
        reload_note = await _reload_ha()
        return _record(piston_id, status="paused",
                       message=f"paused — automation removed from HA (disable unavailable: {why})",
                       reload=reload_note)

    try:
        writer = deploy_writer.get_writer()
    except deploy_writer.WriteTargetError as exc:
        return _record(piston_id, status="error", message=f"write target: {exc}")

    try:
        resolution_map = await _resolution_map()
        result = compile_piston(entry["piston"], piston_id, name, resolution_map,
                                storage.load_globals(),
                                band=storage.compile_band(piston_id))
    except CompilerError as exc:
        fields = exc.record()
        fields.pop("piston_id", None)  # already _record()'s key
        partial = getattr(exc, "partial_yaml", None)
        if partial:
            fields["partial_artifact"] = _keep_artifact(piston_id, partial, ".partial.yaml")
        return _record(piston_id, status="error", **fields)
    except Exception as exc:
        fields = {"message": f"internal compiler error: {exc}"}
        partial = getattr(exc, "partial_yaml", None)
        if partial:
            fields["partial_artifact"] = _keep_artifact(piston_id, partial, ".partial.yaml")
        return _record(piston_id, status="error", **fields)

    if result["target"] == "pyscript":
        return await _deploy_pyscript(piston_id, name, prev, writer, result)

    artifact = _keep_artifact(piston_id, result["yaml"], ".yaml")

    try:
        if prev.get("file") and prev["file"] != filename:
            writer.delete(prev["file"])
        writer.write(filename, result["yaml"])
    except Exception as exc:
        return _record(piston_id, status="error", artifact=artifact,
                       message=f"deploy write failed: {exc}")

    # Config-check gate (DECISION Jeremy 2026-07-18): before any reload, HA
    # validates its whole on-disk config without touching the running system.
    # check_config sees EVERYTHING, so an invalid verdict is only ours if the
    # errors mention our file/folder — a pre-existing problem elsewhere in the
    # user's config must not brick piston deploys. Check unreachable never
    # blocks either (the post-reload verify below stays as the backstop).
    check_note = "unavailable"
    try:
        check = await ha_client.check_config()
    except Exception as exc:
        check = None
        check_note = f"unavailable ({exc})"
    if check:
        check_note = check.get("result", "unknown")
        errors = str(check.get("errors") or "")
        ours = filename.rsplit("/", 1)[-1] in errors or "pistoncore" in errors.lower()
        if check_note == "invalid" and ours:
            rollback = _rollback(writer, prev, filename)
            return _record(piston_id, status="error", artifact=artifact,
                           message=f"HA config check rejected the compiled YAML — "
                                   f"{errors[:400]} ({rollback}; nothing was reloaded)")
        if check_note == "invalid":
            check_note = "invalid elsewhere in HA config (not this piston) — proceeding"

    reload_note = await _reload_ha()
    auto_ids = result.get("auto_ids", [])
    verdict, note = await _verify_and_enable(auto_ids)
    if verdict == "rejected":
        ha_says = await _ha_log_excerpt(filename)
        return _record(piston_id, status="error", file=filename, auto_ids=auto_ids,
                       artifact=artifact, reload=reload_note, config_check=check_note,
                       message=f"HA rejected the compiled YAML ({note}) — HA's log: {ha_says}")
    return _record(piston_id, status="deployed", file=filename, reload=reload_note,
                   auto_ids=auto_ids, enabled=note, artifact=artifact,
                   config_check=check_note)

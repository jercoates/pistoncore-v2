"""Editable compiler templates & data maps on the /data volume.

THE POINT (Jeremy, load-bearing): the compiler's knowledge lives in DATA
files — command/value maps, the emission templates, the vocab, the routing
table — so it can be extended by editing data, never by a code change or a
rebuild (COMPILER_DECISIONS_HOLDING §E1; the whole user-maintainability goal;
the Diagnostics AI-repair workflow literally hands the user the file to edit).

For that to be true in a container, those files CANNOT live only inside the
image — an edit there is wiped on the next rebuild and isn't reachable in the
add-on. So they live on the persistent /data volume and are loaded from there.

BASE + OVERLAY (Jeremy, 2026-07-26 — this replaced seed-once-and-shadow).
The old design copied each file to /data the first time and then NEVER touched
it again. That made the file editable but permanently STALE: a newer file
shipped in a later image could not reach an install that already had a copy,
so a translation fix Jeremy shipped simply never arrived, and the compiler
went on reading the old copy forever. He hit this as "I don't know how to
update my shit" — and he is right that it was unfixable from his side, since
the only workaround was hand-copying files into the data volume, which is not
something a user of an Unraid Community-Applications docker can or should do.

So each file now has three states, reconciled on every startup:

  bundled  <image>/<rel>                     the version this build ships
  baseline <data>/customize/.baseline/<rel>  what was shipped last time we synced
  live     <data>/customize/<rel>            what the compiler actually reads

- live == baseline  → nobody edited it → refresh live from bundled. THIS is
  what makes a rebuild actually update an install.
- live != baseline  → somebody edited it → their change is the overlay and it
  WINS. For JSON we deep-merge so the shipped update still flows into every
  key they did not touch. For templates we can't merge text safely, so their
  file is kept as-is and reported as needing attention.

Nothing is ever destroyed: anything we cannot reconcile is copied to
<data>/customize/.replaced/ first.

KNOWN LIMIT: the JSON overlay carries additions and changes, not deletions —
a key the user DELETED comes back on the next update. Deleting from the vocab
is not how anything is turned off (that's `"ha": "n/a"`), so this trades a
sharp edge for a safe one.
"""

import hashlib
import json
import logging
import os
import shutil
import time
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

# Where "get the latest official data" pulls from. main, not tagged releases:
# there is no release process today, and a project that has lost its maintainer
# will not grow one — a tag would just be another thing that stops being made
# (Jeremy, 2026-07-26). A push becomes available to every install immediately,
# with no rebuild and no docker commands on the user's side.
OFFICIAL_REPO = "jercoates/pistoncore-v2"
OFFICIAL_BRANCH = "main"
OFFICIAL_BASE = (f"https://raw.githubusercontent.com/{OFFICIAL_REPO}/"
                 f"{OFFICIAL_BRANCH}/")

# Templates are closer to program code than to data: they are rendered to
# produce what the compiler emits, so importing one from a stranger's link is
# running their code inside your compiler. NOT blocked — the whole point is
# that someone can keep this alive after there's no maintainer left, and a
# hard block would defeat that (Jeremy, 2026-07-26: "anything that can cause
# concern is a loud warn but let the user choose"). Warned about, loudly.
_RISKY_SUFFIX = ".j2"

_MAX_FETCH_BYTES = 8 * 1024 * 1024

# repo root inside the image (contains templates/ and the root JSON maps)
_BUNDLED = Path(__file__).resolve().parent.parent

_DATA_DIR = Path(os.environ.get("PISTONCORE_DATA_DIR", "/pistoncore-userdata"))
CUSTOMIZE_DIR = _DATA_DIR / "customize"
_BASELINE_DIR = CUSTOMIZE_DIR / ".baseline"
_REPLACED_DIR = CUSTOMIZE_DIR / ".replaced"
_PREVIOUS_DIR = CUSTOMIZE_DIR / ".previous"
_STATE_FILE = CUSTOMIZE_DIR / ".sync-state.json"
_IMPORTS_FILE = CUSTOMIZE_DIR / ".imports.json"

# everything the compiler reads that a user (or an AI) may edit. Paths are
# relative to the repo root; the same relative layout is mirrored under
# CUSTOMIZE_DIR so the editable copy is easy to find.
CUSTOMIZABLE = [
    "templates/compiler",          # emission templates + per-band JSON maps
    "webcore_vocab.json",
    "picker_capability_map.json",
    "routing_table.json",
]

_synced = False
_state: dict = {}


# ── file inventory ──────────────────────────────────────────────────────────

def _iter_rels():
    """Every customizable file as a repo-relative path, expanding directories.
    Enumerated from the BUNDLED side so a file the image no longer ships stops
    being managed, and so our own .baseline/.replaced dirs are never treated
    as customizable content."""
    for rel in CUSTOMIZABLE:
        src = _BUNDLED / rel
        if src.is_dir():
            for f in sorted(src.rglob("*")):
                if f.is_file():
                    yield f.relative_to(_BUNDLED).as_posix()
        elif src.is_file():
            yield rel


def _digest(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


def _same(a: Path, b: Path) -> bool:
    da, db = _digest(a), _digest(b)
    return da is not None and da == db


# ── JSON overlay ────────────────────────────────────────────────────────────

def _delta(base, cur):
    """What the user changed: the parts of `cur` that differ from `base`.
    Dicts recurse key-by-key so an edit to one command doesn't claim ownership
    of the whole file; anything else (lists, scalars) is taken whole, because
    a partial list merge would silently reorder rules that are match-ordered."""
    if isinstance(base, dict) and isinstance(cur, dict):
        out = {}
        for k, v in cur.items():
            if k not in base:
                out[k] = v
            elif base[k] != v:
                sub = _delta(base[k], v)
                if sub != {} or not isinstance(v, dict):
                    out[k] = sub if isinstance(v, dict) else v
        return out
    return cur


def _merge(base, overlay):
    """base updated by overlay; overlay wins on conflict."""
    if isinstance(base, dict) and isinstance(overlay, dict):
        out = dict(base)
        for k, v in overlay.items():
            out[k] = _merge(base[k], v) if k in base else v
        return out
    return overlay


def _load_json(p: Path):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# ── sync ────────────────────────────────────────────────────────────────────

def _backup(live: Path, rel: str) -> None:
    """Never overwrite something we couldn't reconcile without keeping a copy."""
    try:
        dst = _REPLACED_DIR / f"{rel}.{time.strftime('%Y%m%d-%H%M%S')}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(live, dst)
    except Exception:
        logger.warning("Could not back up %s before replacing it.", rel, exc_info=True)


def _install(src: Path, live: Path, baseline: Path) -> None:
    live.parent.mkdir(parents=True, exist_ok=True)
    baseline.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, live)
    shutil.copy2(src, baseline)


def _sync_one(rel: str, notes: dict) -> None:
    src = _BUNDLED / rel
    live = CUSTOMIZE_DIR / rel
    baseline = _BASELINE_DIR / rel

    if not src.is_file():
        return

    # never seen here: install it, and record what was shipped
    if not live.exists():
        _install(src, live, baseline)
        notes[rel] = "seeded"
        return

    # A copy from BEFORE base+overlay existed: there is no record of what was
    # shipped when it was made, so an edit and a stale seed look identical.
    # Treated as stale, because until now an edit here could not take effect
    # anyway (the compiler read a shadowed copy that nothing refreshed — the
    # very bug this replaces), so "stale" is overwhelmingly the likely case.
    # A copy is kept either way; nothing is lost.
    if not baseline.exists():
        if not _same(live, src):
            _backup(live, rel)
            notes[rel] = "reset-from-legacy-copy"
        _install(src, live, baseline)
        notes.setdefault(rel, "adopted")
        return

    edited = not _same(live, baseline)
    shipped_changed = not _same(baseline, src)

    if not edited:
        if shipped_changed:
            _install(src, live, baseline)
            notes[rel] = "updated"
        return

    if not shipped_changed:
        notes[rel] = "customized"
        return

    # edited AND shipped changed — the case the whole design exists for
    if rel.endswith(".json"):
        try:
            overlay = _delta(_load_json(baseline), _load_json(live))
            merged = _merge(_load_json(src), overlay)
            live.write_text(json.dumps(merged, indent=1, ensure_ascii=False),
                            encoding="utf-8")
            shutil.copy2(src, baseline)
            notes[rel] = "merged"
            return
        except Exception:
            logger.warning("Could not merge the update into %s; keeping your "
                           "version.", rel, exc_info=True)
    notes[rel] = "needs-attention"


def ensure_seeded() -> None:
    """Reconcile every customizable file against what this build ships.
    Idempotent, runs once per process, and NEVER crashes startup — a data
    volume that is read-only, full, or owned by another UID must degrade to
    "not user-editable this run", not take the app down."""
    global _synced, _state
    if _synced:
        return
    _synced = True
    notes: dict = {}
    try:
        CUSTOMIZE_DIR.mkdir(parents=True, exist_ok=True)
        for rel in _iter_rels():
            try:
                _sync_one(rel, notes)
            except Exception:
                logger.warning("Could not sync %s (using what's on disk).",
                               rel, exc_info=True)
                notes[rel] = "error"
        _state = {"synced_at": time.strftime("%Y-%m-%d %H:%M:%S"), "files": notes}
        try:
            _STATE_FILE.write_text(json.dumps(_state, indent=1), encoding="utf-8")
        except OSError:
            pass
    except Exception:
        logger.warning("Could not reconcile the editable compiler files; "
                       "using the versions built into this image.", exc_info=True)
        _state = {"synced_at": None, "files": notes}


# ── reads ───────────────────────────────────────────────────────────────────

def path(rel: str) -> Path:
    """The file to READ for `rel`: the user's editable copy on /data if it
    exists, else the bundled image copy. Per-file, so editing one map never
    forces copying the rest."""
    ensure_seeded()
    cust = CUSTOMIZE_DIR / rel
    return cust if cust.exists() else (_BUNDLED / rel)


def search_dirs(rel: str) -> list[str]:
    """[customize, bundled] search path for a Jinja ChoiceLoader — a template
    edited on /data overrides the bundled one; missing user templates (e.g. an
    include the user never copied) fall back to the image."""
    ensure_seeded()
    return [str(CUSTOMIZE_DIR / rel), str(_BUNDLED / rel)]


def editable_location(rel: str) -> str:
    """Human-facing path to the copy a user should edit (for help/repair
    text) — always the /data location, whether or not it's been created yet."""
    return str(CUSTOMIZE_DIR / rel)


# ── importing from a link ───────────────────────────────────────────────────

def _managed_by_basename() -> dict:
    """filename -> repo-relative path, for working out what a link points at.
    Every managed file has a distinct filename, so a bare link to one is
    unambiguous."""
    out = {}
    for rel in _iter_rels():
        out[rel.rsplit("/", 1)[-1]] = rel
    return out


def normalize_source(url: str) -> dict:
    """Work out what a pasted link means. Accepts the forms a person actually
    has in hand: a GitHub page URL, a folder inside a repo, a raw file link, or
    a plain directory URL. Returns {"base": url} to pull the whole set, or
    {"file": (rel, url)} for a single file."""
    url = (url or "").strip()
    if not url:
        raise ValueError("No link given.")
    if not url.startswith(("http://", "https://")):
        raise ValueError("That doesn't look like a link — it should start with https://")

    parts = urllib.parse.urlsplit(url)
    seg = [s for s in parts.path.split("/") if s]

    # github.com/<user>/<repo>[/blob|tree/<branch>/<path...>] -> raw
    if parts.netloc.lower().endswith("github.com") and len(seg) >= 2:
        user, repo = seg[0], seg[1]
        if len(seg) >= 4 and seg[2] in ("blob", "tree"):
            branch, rest = seg[3], seg[4:]
            raw = (f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/"
                   + "/".join(rest))
            if seg[2] == "blob":
                return _as_file(raw)
            return {"base": raw.rstrip("/") + "/"}
        return {"base": f"https://raw.githubusercontent.com/{user}/{repo}/"
                        f"{OFFICIAL_BRANCH}/"}

    name = seg[-1] if seg else ""
    if name in _managed_by_basename():
        return _as_file(url)
    return {"base": url.rstrip("/") + "/"}


def _as_file(url: str) -> dict:
    name = url.rsplit("/", 1)[-1].split("?")[0]
    rel = _managed_by_basename().get(name)
    if not rel:
        known = ", ".join(sorted(_managed_by_basename()))
        raise ValueError(f"'{name}' isn't one of the files PistonCore uses. "
                         f"Expected one of: {known}")
    return {"file": (rel, url)}


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "PistonCore"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read(_MAX_FETCH_BYTES + 1)
    if len(raw) > _MAX_FETCH_BYTES:
        raise ValueError("That file is far larger than any PistonCore data file.")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("That isn't a text file.") from None


def _validate(rel: str, text: str) -> None:
    """Never stage something that would break the compiler on next read."""
    if rel.endswith(".json"):
        try:
            json.loads(text)
        except ValueError as exc:
            raise ValueError(f"{rel} isn't valid JSON ({exc}).") from None
    if rel == "webcore_vocab.json":
        doc = json.loads(text)
        missing = [k for k in ("commands", "virtualCommands", "attributes")
                   if k not in doc]
        if missing:
            raise ValueError(f"That doesn't look like the vocab file — it has no "
                             f"{', '.join(missing)}.")


def stage(source: str, url: str = "") -> dict:
    """Fetch (but do not apply) a set of files. `source` is 'official' or
    'link'. Returns everything the preview needs, including which files are
    risky, so the user is told BEFORE anything is written."""
    ensure_seeded()
    if source == "official":
        spec, origin = {"base": OFFICIAL_BASE}, "official"
    else:
        spec, origin = normalize_source(url), (url or "").strip()

    fetched, problems = {}, []
    if "file" in spec:
        rel, furl = spec["file"]
        text = _fetch(furl)
        _validate(rel, text)
        fetched[rel] = text
    else:
        base = spec["base"]
        for rel in _iter_rels():
            # A link can point at a repo root (files sit at their full relative
            # path) or straight at a folder holding them (flat, just the
            # filenames) — someone sharing a fix is likely to do the latter.
            # Try both rather than making the user know the difference.
            last = None
            for candidate in (base + rel, base + rel.rsplit("/", 1)[-1]):
                try:
                    text = _fetch(candidate)
                    _validate(rel, text)
                    fetched[rel] = text
                    last = None
                    break
                except Exception as exc:
                    last = exc
            if last is not None:
                # a source that only carries some of the files is normal
                problems.append(f"{rel}: {last}")
    if not fetched:
        raise ValueError("Nothing usable was found at that link. "
                         + ("; ".join(problems[:3]) if problems else ""))

    changes = []
    for rel, text in sorted(fetched.items()):
        live = CUSTOMIZE_DIR / rel
        cur = live.read_text(encoding="utf-8") if live.exists() else None
        changes.append({
            "file": rel,
            "state": "unchanged" if cur == text else ("new" if cur is None else "changed"),
            "risky": rel.endswith(_RISKY_SUFFIX),
        })
    return {"source": source, "origin": origin, "changes": changes,
            "skipped": problems,
            "risky": any(c["risky"] and c["state"] != "unchanged" for c in changes),
            "any_change": any(c["state"] != "unchanged" for c in changes),
            "_files": fetched}


def apply_staged(staged: dict) -> dict:
    """Write a staged set, after snapshotting what's there now so it can be
    put back with one click."""
    ensure_seeded()
    files = staged.get("_files") or {}
    snapshot_previous(list(files))
    written = []
    for rel, text in sorted(files.items()):
        live = CUSTOMIZE_DIR / rel
        if live.exists() and live.read_text(encoding="utf-8") == text:
            continue
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_text(text, encoding="utf-8")
        written.append(rel)
    _record_imports(written, staged.get("origin") or staged.get("source", ""))
    return {"written": written}


# ── restore points ──────────────────────────────────────────────────────────

def snapshot_previous(rels: list[str]) -> None:
    """Copy the CURRENT files aside before changing them — the one-click undo.
    Also keeps a timestamped copy in .replaced/ as deeper history."""
    for rel in rels:
        live = CUSTOMIZE_DIR / rel
        if not live.exists():
            continue
        try:
            dst = _PREVIOUS_DIR / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(live, dst)
            _backup(live, rel)
        except Exception:
            logger.warning("Could not snapshot %s before changing it.", rel,
                           exc_info=True)


def _record_imports(rels: list[str], origin: str) -> None:
    try:
        cur = json.loads(_IMPORTS_FILE.read_text(encoding="utf-8")) if \
            _IMPORTS_FILE.exists() else {}
    except (OSError, ValueError):
        cur = {}
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    for rel in rels:
        cur[rel] = {"origin": origin, "at": stamp}
    try:
        _IMPORTS_FILE.write_text(json.dumps(cur, indent=1), encoding="utf-8")
    except OSError:
        pass


def _forget_imports(rels: list[str]) -> None:
    """A restored file is no longer 'imported from somewhere'."""
    try:
        cur = json.loads(_IMPORTS_FILE.read_text(encoding="utf-8")) if \
            _IMPORTS_FILE.exists() else {}
    except (OSError, ValueError):
        return
    for rel in rels:
        cur.pop(rel, None)
    try:
        _IMPORTS_FILE.write_text(json.dumps(cur, indent=1), encoding="utf-8")
    except OSError:
        pass


def restore_points() -> list[dict]:
    """What can be put back, most-trusted first. 'This build' needs no network
    and cannot go stale — the floor under everything else, and the one that
    still works when the repo, the link, and the maintainer are all gone."""
    ensure_seeded()
    build_n = sum(1 for rel in _iter_rels() if (_BASELINE_DIR / rel).exists()
                  or (_BUNDLED / rel).is_file())
    prev_n = sum(1 for rel in _iter_rels() if (_PREVIOUS_DIR / rel).exists())
    return [
        {"id": "build", "name": "Shipped with this build", "files": build_n,
         "needs_network": False,
         "detail": "The copies inside this image. Always available, even with no "
                   "internet."},
        {"id": "official", "name": "Latest official", "files": None,
         "needs_network": True,
         "detail": f"Fetched fresh from {OFFICIAL_REPO} ({OFFICIAL_BRANCH})."},
        {"id": "previous", "name": "Previous version", "files": prev_n,
         "needs_network": False,
         "detail": "What was in place just before the last change." if prev_n
                   else "Nothing to go back to yet — no change has been made."},
    ]


def restore(which: str) -> dict:
    """Put back a restore point. 'official' re-fetches; the others are local."""
    ensure_seeded()
    if which == "official":
        return apply_staged(stage("official"))
    if which == "build":
        src_dir, label = _BASELINE_DIR, "this build"
    elif which == "previous":
        src_dir, label = _PREVIOUS_DIR, "the previous version"
    else:
        raise ValueError(f"Unknown restore point '{which}'.")

    # READ FIRST, then snapshot. Restoring "previous" writes into the very
    # folder it reads from, so snapshotting first would overwrite the thing
    # being restored and turn the undo into a no-op. Holding the content in
    # memory also makes undo reversible: restore, then restore "previous"
    # again, and you're back where you started.
    content: dict[str, bytes] = {}
    for rel in _iter_rels():
        src = src_dir / rel
        if not src.exists() and which == "build":
            src = _BUNDLED / rel
        if src.is_file():
            content[rel] = src.read_bytes()
    if not content:
        raise ValueError(f"There is nothing saved for {label}.")

    snapshot_previous(list(content))
    written = []
    for rel, blob in sorted(content.items()):
        live = CUSTOMIZE_DIR / rel
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_bytes(blob)
        written.append(rel)
    _forget_imports(written)
    return {"written": written, "restored": label}


# ── status (Settings page) ──────────────────────────────────────────────────

def _version_of(which: str) -> str:
    """Short fingerprint over all customizable files — 'bundled' is what this
    build ships, 'live' is what the compiler will actually read."""
    h = hashlib.sha256()
    for rel in _iter_rels():
        p = (_BUNDLED / rel) if which == "bundled" else path(rel)
        h.update(rel.encode("utf-8"))
        h.update((_digest(p) or "").encode("utf-8"))
    return h.hexdigest()[:12]


def status() -> dict:
    """What Settings shows so Jeremy can SEE whether an update landed, instead
    of having to take anyone's word for it (his ask, 2026-07-26)."""
    ensure_seeded()
    files = (_state or {}).get("files", {})
    bundled_v = _version_of("bundled")
    live_v = _version_of("live")
    customized = sorted(r for r, s in files.items()
                        if s in ("customized", "merged", "needs-attention"))
    try:
        imports = json.loads(_IMPORTS_FILE.read_text(encoding="utf-8")) if \
            _IMPORTS_FILE.exists() else {}
    except (OSError, ValueError):
        imports = {}
    return {
        "imports": imports,
        "restore_points": restore_points(),
        "official_repo": f"{OFFICIAL_REPO} ({OFFICIAL_BRANCH})",
        "build_version": bundled_v,
        "live_version": live_v,
        "matches_build": bundled_v == live_v,
        "synced_at": (_state or {}).get("synced_at"),
        "updated": sorted(r for r, s in files.items() if s in ("updated", "merged")),
        "customized": customized,
        "needs_attention": sorted(r for r, s in files.items()
                                  if s in ("needs-attention", "error")),
        "reset": sorted(r for r, s in files.items() if s == "reset-from-legacy-copy"),
        "location": str(CUSTOMIZE_DIR),
        "backups": str(_REPLACED_DIR),
    }

"""Editable compiler templates & data maps on the /data volume.

THE POINT (Jeremy, load-bearing): the compiler's knowledge lives in DATA
files — command/value maps, the emission templates, the vocab, the routing
table — so it can be extended by editing data, never by a code change or a
rebuild (COMPILER_DECISIONS_HOLDING §E1; the whole user-maintainability goal;
the Diagnostics AI-repair workflow literally hands the user the file to edit).

For that to be true in a container, those files CANNOT live only inside the
image — an edit there is wiped on the next rebuild and isn't reachable in the
add-on. So they are SEEDED onto the persistent /data volume on first run and
loaded from there, with a per-file fallback to the bundled copy in the image.

- Edit a file under <data>/customize/… → it wins, persists across rebuilds.
- Delete/never-touch a file → the bundled image copy is used.
- A new file shipped in a later image (that the user's seed predates) → falls
  back to bundled automatically until re-seeded.
"""

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# repo root inside the image (contains templates/ and the root JSON maps)
_BUNDLED = Path(__file__).resolve().parent.parent

_DATA_DIR = Path(os.environ.get("PISTONCORE_DATA_DIR", "/pistoncore-userdata"))
CUSTOMIZE_DIR = _DATA_DIR / "customize"

# everything the compiler reads that a user (or an AI) may edit. Paths are
# relative to the repo root; the same relative layout is mirrored under
# CUSTOMIZE_DIR so the editable copy is easy to find.
CUSTOMIZABLE = [
    "templates/compiler",          # emission templates + per-band JSON maps
    "webcore_vocab.json",
    "picker_capability_map.json",
    "routing_table.json",
]

_seeded = False


def ensure_seeded() -> None:
    """Copy the bundled compiler files onto /data the first time. Idempotent
    and NON-destructive: an existing customize file/dir is never overwritten,
    so user edits always survive. Runs once per process."""
    global _seeded
    if _seeded:
        return
    for rel in CUSTOMIZABLE:
        src = _BUNDLED / rel
        dst = CUSTOMIZE_DIR / rel
        if dst.exists() or not src.exists():
            continue
        # A failed seed must NEVER crash startup: if /data is read-only, has a
        # container-vs-host UID mismatch, or is full, copying throws — and a hard
        # exception here (called at import time) takes the whole app down. It's
        # also non-fatal by design: customize.path() falls back to the bundled
        # copy when the /data copy is absent, so an unseeded file still WORKS,
        # it just isn't user-editable. So log and continue, per file.
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        except Exception:
            logger.warning("Could not seed editable copy of %s (using bundled "
                           "default; not user-editable this run).", rel, exc_info=True)
    _seeded = True


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

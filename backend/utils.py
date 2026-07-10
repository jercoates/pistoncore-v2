# pistoncore/backend/utils.py
#
# Shared utility functions used across backend modules.
# Keep this file free of imports from other PistonCore modules to avoid
# circular imports — it is safe to import from anywhere in the backend.

import re


def slugify(name: str) -> str:
    """
    Convert a piston name to a safe slug for use in HA entity IDs and
    the automation alias field. Pure string transformation — no state.

    Rules per COMPILER_SPEC Section 4:
    - Lowercase
    - Spaces and hyphens → underscores
    - Strip all non-alphanumeric/underscore characters
    - Strip leading/trailing underscores
    - Truncate to 50 characters

    Used by:
    - compiler.py — automation alias field (slug used ONLY for alias, never
      for entity IDs or filenames — those always use piston UUID)
    - storage.py — get_all_slugs() for slug collision detection
    """
    s = name.lower()
    s = s.replace(" ", "_").replace("-", "_")
    s = re.sub(r"[^a-z0-9_]", "", s)
    s = s.strip("_")
    s = s[:50]
    return s

"""There is ONE version, and it is the manifest's.

REGRESSION GUARD. `__version__` in the package used to be a separate literal that
drifted: it said 0.9.4 while the manifest said 0.13.x, so every device's
`sw_version` was wrong. It is now read from manifest.json, so changing the version
means editing one file, and this keeps it that way.
"""

import json
import pathlib

import custom_components.virtual as virtual


def test_the_package_version_is_the_manifests():
    manifest = pathlib.Path(virtual.__file__).with_name("manifest.json")
    assert virtual.__version__ == json.loads(manifest.read_text(encoding="utf-8"))["version"]


def test_it_is_a_real_version_not_the_fallback():
    assert virtual.__version__ != "unknown"

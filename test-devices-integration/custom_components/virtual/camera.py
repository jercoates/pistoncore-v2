"""
Virtual camera — PistonCore addition to hass-virtual (FORK_NOTES.md).

A camera that really does hand Home Assistant a picture, so camera pistons can
be tested without pointing a lens at anything.

WHY THIS IS A REAL CAMERA AND NOT A SIMULATION
----------------------------------------------
`camera.snapshot` is not implemented by the camera — Home Assistant's camera
component implements it. It asks the entity for image bytes and writes them to
the path the caller gave. So an entity that returns bytes gets the whole real
mechanism for free: a real file, at a real path, written by HA's own code,
subject to HA's own rules.

That matters, because those rules are what a camera piston actually trips over:

  * HA refuses to write outside `allowlist_external_dirs` or the media folder,
    so a piston asking for a snapshot somewhere HA won't write fails here
    exactly as it would on real hardware.
  * The file genuinely exists afterwards, so a notification attaching it, or a
    media player playing from it, behaves properly instead of "working" against
    a stub.

THE FRAME ADVANCES ON EVERY READ
--------------------------------
A real camera shows something different each time you look. This one cycles
through the bundled frames, one per request, which is what makes it useful as a
bench: a piston that takes two snapshots produces two visibly DIFFERENT
pictures, so you can tell it fired twice rather than once. A single fixed image
cannot distinguish "ran" from "ran twice" from "didn't run".

Frames live in `images/` next to this file and are read in sorted order. Drop
JPEGs in, remove ones you don't want — nothing here needs changing. See
images/CREDITS.md.
"""

import logging
from collections.abc import Callable
from pathlib import Path

import voluptuous as vol

from homeassistant.components.camera import (
    DOMAIN as PLATFORM_DOMAIN,
    Camera,
    CameraEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.config_validation import PLATFORM_SCHEMA
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import get_entity_configs
from .const import *
from .entity import VirtualEntity, virtual_schema, FEATURES_SCHEMA, feature_flags


_LOGGER = logging.getLogger(__name__)

DEPENDENCIES = [COMPONENT_DOMAIN]

IMAGE_DIR = Path(__file__).parent / "images"

# A camera has no on/off state to restore; initial_value is unused but
# virtual_schema wants a default, same as the button platform.
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(virtual_schema("", FEATURES_SCHEMA))
CAMERA_SCHEMA = vol.Schema(virtual_schema("", FEATURES_SCHEMA))


def _frames() -> list[Path]:
    """The bundled frames, sorted. Empty list if the folder is missing."""
    if not IMAGE_DIR.is_dir():
        return []
    return sorted(p for p in IMAGE_DIR.iterdir()
                  if p.suffix.lower() in (".jpg", ".jpeg", ".png"))


async def async_setup_platform(
        hass: HomeAssistant, config: ConfigType,
        async_add_entities: AddEntitiesCallback,
        _discovery_info: DiscoveryInfoType | None = None) -> None:
    if hass.data[COMPONENT_CONFIG].get(CONF_YAML_CONFIG, False):
        async_add_entities([VirtualCamera(config, True)], True)


async def async_setup_entry(
        hass: HomeAssistant, entry: ConfigEntry,
        async_add_entities: Callable[[list], None]) -> None:
    entities = []
    for entity in get_entity_configs(hass, entry.data[ATTR_GROUP_NAME], PLATFORM_DOMAIN):
        entities.append(VirtualCamera(CAMERA_SCHEMA(entity), False))
    async_add_entities(entities)


class VirtualCamera(VirtualEntity, Camera):
    """Representation of a Virtual camera."""

    def __init__(self, config, old_style: bool):
        # Camera has real initialisation of its own (image cache, stream
        # bookkeeping); VirtualEntity's __init__ doesn't chain to it, so it is
        # called explicitly. Omitting it leaves the entity half-built and it
        # fails on the first image request rather than at setup, which is a
        # miserable thing to debug.
        Camera.__init__(self)
        super().__init__(config, PLATFORM_DOMAIN, old_style)

        # No streaming: there is no video, only stills. A clone of a real
        # camera can still declare whatever that camera advertised.
        self._attr_supported_features = feature_flags(
            config, CameraEntityFeature, CameraEntityFeature(0))

        self._frames = _frames()
        self._index = 0
        if not self._frames:
            _LOGGER.warning(
                f"VirtualCamera: {self.name} has no frames — {IMAGE_DIR} is "
                f"empty or missing, so snapshots will fail")
        _LOGGER.info(f"VirtualCamera: {self.name} created with "
                     f"{len(self._frames)} frame(s)")

    async def async_camera_image(
            self, width: int | None = None,
            height: int | None = None) -> bytes | None:
        """The next frame.

        `width`/`height` are HA asking for a convenient size; returning the
        full frame is allowed and HA scales as it needs. The frames are small
        by design, so there is nothing to gain by resizing here.
        """
        if not self._frames:
            return None
        frame = self._frames[self._index % len(self._frames)]
        self._index += 1
        try:
            image = await self.hass.async_add_executor_job(frame.read_bytes)
        except OSError as exc:
            _LOGGER.error(f"{self.name} could not read {frame.name}: {exc}")
            return None
        # Say which frame was just served and which is next, so a test can
        # assert the camera actually moved rather than inferring it from the
        # image bytes.
        self._attr_extra_state_attributes.update({
            "frame_count": len(self._frames),
            "last_frame": frame.name,
            "next_frame": self._frames[self._index % len(self._frames)].name,
        })
        return image

"""
Pseudonymise a debug bundle so it can be shared without exposing the house.

THE RULE (Jeremy, firm — "i dont want it even in an email"): **pseudonymise, do
NOT delete.** ONE mapping across the whole bundle — status record, generated
code and piston JSON together — so `light.master_bedroom` becomes
`light.device_3` everywhere it appears and the cross-references still line up.
Deleting names instead would do exactly the damage his manual clean of the
test-pistons corpus caused: three pistons still broken by dangling hand-edited
references.

WHAT GETS A STAND-IN
  entity ids      light.master_bedroom  -> light.device_3
  friendly names  "Master Bedroom"      -> "Device 3"      (same number)
  areas           "Upstairs"            -> "Area 2"
  piston names    "Kids bedtime"        -> "Piston 4"
    Piston names get stand-ins too, on Jeremy's reasoning: a name is free text a
    human chose, and "human nature might cause a flag" — knowing what a piston
    does is helpful but "not worth the problems it could cause". The structure
    already shows the behaviour; the reporter can describe it in the issue.

WHAT IS REMOVED OUTRIGHT (no stand-in, because it is a secret, not a label)
  tokens, passwords, signing secrets
  device state that carries credentials — a Hubitat-bridged ALARM PANEL exposes
    `codes` containing plaintext PINs *with the names they belong to*, and LOCKS
    expose household member names via `codes` / `last_code_name` (found on the
    real bridge, 2026-07-31). No bundle may ever carry those.
  home coordinates

WHAT DELIBERATELY STAYS
  **Internal IPs.** Jeremy, explicit: private addresses "harm nothing as long as
  i dont get there wan ip". 192.168.x / 10.x / 172.16-31.x / 127.x / *.local /
  localhost are meaningless off-network and genuinely useful when reading a
  report. PUBLIC IPs and REMOTE HOSTNAMES (nabu.casa, DuckDNS, any off-network
  name) are redacted — a remote hostname is as exposing as the WAN IP.

  **Everything diagnostic**: structure, services called, attributes,
  supported_features, error text, the compiler's decisions. Redaction that ate
  the diagnosis would defeat the point.

THE ADMITTED LIMIT: free text a user typed inside a piston ("Front door opened",
a spoken message) cannot be reliably scrubbed — it is indistinguishable from any
other string. `header_note()` says so rather than over-promising.
"""

from __future__ import annotations

import ipaddress
import re

# ── what never survives, wherever it appears in structured data ─────────────
# Matched on the KEY, case-insensitively, as a substring.
SENSITIVE_KEY_PARTS = (
    "token", "password", "passwd", "secret", "api_key", "apikey",
    "access_code", "code_length",
    "latitude", "longitude",
)
# Keys whose whole value is a credential structure (lock/alarm user codes).
SENSITIVE_KEYS_EXACT = {
    "codes", "code", "user_codes", "last_code_name", "lock_codes",
}

_REDACTED = "<redacted>"

# Off-network hostnames worth naming explicitly: these appear in piston text and
# settings, not just URLs, and each one identifies a reachable front door.
_REMOTE_HOST_RE = re.compile(
    r"\b[\w.-]*\.(?:nabu\.casa|duckdns\.org|ui\.nabu\.casa|ngrok\.io|ngrok-free\.app"
    r"|no-ip\.(?:org|com|biz)|dyndns\.(?:org|com)|myfritz\.net|synology\.me)\b",
    re.IGNORECASE)

# Host inside a URL. Handled separately from bare hostnames so that ordinary
# dotted identifiers — `light.turn_on`, `sensor.foo` — are never touched.
_URL_RE = re.compile(r"\b(https?|wss?|smb|x-file-cifs)://([^\s/\"'<>\\]+)", re.IGNORECASE)

_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

# HA long-lived tokens are JWTs.
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]+")

# Named secrets, wherever they appear — a query string, a YAML mapping, a dict.
#
# ADDRESSES AND CODES ARE THE PRIORITY (Jeremy, 2026-08-01: "names of devices
# wil not tell me anything adresses and codes are the problem"). A piston can
# compile an alarm PIN straight into an emitted disarm action, so this has to
# work on emitted CODE, not just on structured data.
#
# The value may be QUOTED — and it usually is, because that is how yaml writes
# it. An earlier version excluded quotes from the value pattern, so
# `code: "2217"` sailed through untouched while `code: 2217` was caught. That is
# the single most important case there is.
#
# Trailing \b keeps `code_format` and `code_arm_required` intact: those are
# diagnostic, and `code` followed by `_` is not a word boundary.
_SECRET_KEY_WORDS = (
    r"access[_-]?tokens?|api[_-]?keys?|webhook[_-]?ids?|passwords?|passwd|"
    r"secrets?|tokens?|auth|bearer|pins?|codes?|keys?|credentials?"
)
_QS_SECRET_RE = re.compile(
    r"\b(" + _SECRET_KEY_WORDS + r")\b(\s*[=:]\s*)(['\"]?)([^\s&\"'<>,}\]]+)(['\"]?)",
    re.IGNORECASE)

# Credentials embedded in a URL — smb://user:pass@host, x-file-cifs://…
# These survive even when the host is private and therefore kept, which is
# exactly when they would otherwise slip out.
_URL_CREDS_RE = re.compile(
    r"\b([a-z][a-z0-9+.\-]*://)([^\s/@\"'<>]+):([^\s/@\"'<>]+)@", re.IGNORECASE)


# ── webCoRE's own anonymisation convention ─────────────────────────────────
#
# webCoRE ALREADY solves this and PistonCore adapts to it rather than inventing
# a scheme (CLAUDE.md: "for any design question, the answer is what webCoRE
# does"). Ground truth:
#   dashboard/js/modules/piston.module.js:4878  $scope.anonymizeDevices()
#   dashboard/js/app.js:1664                    dataService.determineDeviceType()
#
# A device's stand-in is its TYPE plus a per-type index — "Dimmer 1",
# "Motion Sensor 2", "RGB Bulb 1" — not a generic label. That is strictly more
# useful in a bug report: the reader knows it was a dimmer. Contacts become
# "John Doe N" (piston.module.js:4890).
#
# The ladder below is webCoRE's, order preserved (order matters: a Color Control
# device is an RGB Bulb before it is a Switch), reading the same `cn` capability
# display names PistonCore already builds (DEVICE_PAYLOAD_SPEC).

_TYPE_LADDER = [
    ("Water Sensor", "waterSensor"),
    ("Contact Sensor", "contactSensor"),
    ("Thermostat", "thermostat"),
    ("Garage Door Control", "garageDoor"),
    ("Music Player", "musicPlayer"),
    ("Door Control", "door"),
    ("Presence Sensor", "presenceSensor"),
    ("Motion Sensor", "motionSensor"),
    ("Color Control", "rgbBulb"),
    ("Color Temperature", "whiteBulb"),
]


def device_type_name(cn: list | None, name: str = "") -> str:
    """webCoRE's `determineDeviceType`, then its display formatting.

    camelCase -> spaced Title Case, with webCoRE's own "Rgb " -> "RGB " fix.
    """
    kind = "unknownDevice"
    caps = [str(c) for c in (cn or [])]
    joined = " | ".join(caps)
    for needle, result in _TYPE_LADDER:
        if needle in joined:
            kind = result
            break
    else:
        if "Switch Level" in joined:
            lowered = (name or "").lower()
            kind = ("whiteBulb" if "light" in lowered
                    else "vent" if ("keen" in lowered or "vent" in lowered)
                    else "dimmer")
        elif "Lock" in joined:
            kind = "lock"
        elif "Button" in joined:
            kind = "button"
        elif "Temperature Measurement" in joined:
            kind = "temperatureSensor"
        elif "Switch" in joined and "Power Meter" in joined:
            kind = "outlet"
        elif "Switch" in joined:
            kind = "switch"
        elif "Power Meter" in joined:
            kind = "powerMeter"

    spaced = re.sub(r"([A-Z])", r" \1", kind).strip()
    return (spaced[:1].upper() + spaced[1:]).replace("Rgb ", "RGB ")


def _is_private_host(host: str) -> bool:
    """True for anything meaningless outside the user's own network."""
    host = host.split("@")[-1].split(":")[0].strip("[]").lower()
    if host in ("localhost", "127.0.0.1", "::1", "homeassistant", "supervisor"):
        return True
    if host.endswith(".local") or host.endswith(".lan") or host.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # A bare hostname with no dots is a LAN name; anything dotted is not.
        return "." not in host
    return ip.is_private or ip.is_loopback or ip.is_link_local


class Redactor:
    """Builds one consistent mapping, then applies it to a whole bundle.

    Learn everything FIRST (`learn_*`), then call `text()` on the assembled
    bundle — one pass, one mapping, so the same device reads as the same
    stand-in in the status record, the generated YAML and the piston JSON.
    """

    def __init__(self) -> None:
        self._literal: dict[str, str] = {}     # exact string -> stand-in
        self._entity_n = 0
        self._area_n = 0
        self._piston_n = 0
        # webCoRE-shaped device stand-ins + the legend describing them.
        self._device_idx = 0
        self._type_counts: dict[str, int] = {}
        self.legend: dict[str, dict] = {}      # stand-in id -> {n, t, ...}
        self.resolution: dict[str, dict] = {}  # picker id -> HA registry facts

    # ── webCoRE-native device stand-ins ─────────────────────────────────────

    def learn_webcore_device(self, device_id: str, cn: list | None,
                             name: str = "", extra: dict | None = None) -> str:
        """Give a picker device webCoRE's OWN stand-in, and log it in the legend.

        The stand-in id copies webCoRE exactly (piston.module.js:4739):
        ':' + ('x'*32 + index)[-32:] + ':' — the same SHAPE as a real hashed id,
        which is why a redacted piston stays loadable in the editor instead of
        becoming unparseable. The user then attaches their own devices, exactly
        as they would to an AI-authored piston.

        `extra` carries whatever is needed to REBUILD the device on a bench
        (see the add-on's virtual.describe_device). webCoRE's legend already
        exists to say what a stand-in stood for; this puts the rebuild recipe in
        the same place.
        """
        if device_id in self._literal:
            return self._literal[device_id]
        stand_in = ":" + ("x" * 32 + str(self._device_idx))[-32:] + ":"
        self._device_idx += 1

        type_name = device_type_name(cn, name)
        self._type_counts[type_name] = self._type_counts.get(type_name, 0) + 1
        display = f"{type_name} {self._type_counts[type_name]}"

        self._literal[device_id] = stand_in
        if name and len(name.strip()) > 2:
            self._literal.setdefault(name.strip(), display)
        self.legend[stand_in] = {"n": display, "t": type_name, **(extra or {})}
        return stand_in

    # ── learning ────────────────────────────────────────────────────────────

    def learn_entity(self, entity_id: str, friendly_name: str | None = None) -> str:
        """Give one entity (and its friendly name) a single shared number."""
        if not entity_id or "." not in entity_id:
            return entity_id
        domain, _, object_id = entity_id.partition(".")
        if entity_id in self._literal:
            return self._literal[entity_id]
        self._entity_n += 1
        n = self._entity_n
        # Keep the DOMAIN — it is diagnostic (a light behaves unlike a lock) and
        # says nothing about the house.
        self._literal[entity_id] = f"{domain}.device_{n}"
        # The bare object_id shows up alone in templates and generated code.
        if len(object_id) > 3:
            self._literal.setdefault(object_id, f"device_{n}")
        if friendly_name and len(friendly_name.strip()) > 2:
            self._literal.setdefault(friendly_name.strip(), f"Device {n}")
        return self._literal[entity_id]

    def learn_area(self, name: str) -> None:
        if name and len(name.strip()) > 1 and name.strip() not in self._literal:
            self._area_n += 1
            self._literal[name.strip()] = f"Area {self._area_n}"

    def learn_piston(self, name: str) -> None:
        if name and len(name.strip()) > 1 and name.strip() not in self._literal:
            self._piston_n += 1
            self._literal[name.strip()] = f"Piston {self._piston_n}"

    def learn_device(self, name: str) -> None:
        """A device-registry name that isn't any single entity's friendly name."""
        if name and len(name.strip()) > 2 and name.strip() not in self._literal:
            self._entity_n += 1
            self._literal[name.strip()] = f"Device {self._entity_n}"

    # ── applying ────────────────────────────────────────────────────────────

    def text(self, value: str) -> str:
        """Apply every rule to a block of text. Safe to call on a whole bundle."""
        if not value:
            return value
        out = value

        # 1. Secrets first — before anything else can rewrite them into a
        #    shape the patterns no longer match.
        out = _JWT_RE.sub(_REDACTED, out)
        out = _URL_CREDS_RE.sub(lambda m: f"{m.group(1)}{_REDACTED}@", out)
        # Keep the surrounding quotes so the result is still valid yaml/json.
        out = _QS_SECRET_RE.sub(
            lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{_REDACTED}{m.group(5)}", out)

        # 2. Remote hostnames, then URLs whose host is off-network.
        out = _REMOTE_HOST_RE.sub("<remote-host-redacted>", out)
        out = _URL_RE.sub(self._url, out)

        # 3. Public IPs. Private ones stay, deliberately.
        out = _IPV4_RE.sub(self._ip, out)

        # 4. Learned names, in ONE pass. Two bugs made this non-negotiable
        #    (both seen on real data, 2026-08-01):
        #
        #    * Replacing one name at a time CASCADES — a stand-in produced by
        #      one rule was then chewed by the next.
        #    * Plain substring matching hits mid-word. HA had a person called
        #      "Dev", so "Device 10" became "Presence Sensor 1ice 10".
        #
        #    A single alternation, longest-first, with word boundaries on
        #    alphanumeric edges, fixes both: every position is consumed once,
        #    and "Dev" can no longer match inside "Device".
        pattern = self._pattern_for(out)
        if pattern is not None:
            out = pattern.sub(lambda m: self._literal[m.group(0)], out)
        return out

    def _pattern_for(self, value: str):
        """A single alternation over just the names that OCCUR in this text.

        Compiling all ~2000 learned names into one regex is correct but far too
        slow — 21s on a 109 KB bundle, because the engine tries every branch at
        every position. Pre-filtering with plain `in` first is a C-speed scan and
        cuts it to a handful of branches, so this keeps the single-pass
        guarantees (no cascading, word boundaries) at the original speed.
        """
        present = [k for k in self._literal if k in value]
        if not present:
            return None
        parts = []
        # Longest first: "Master Bedroom Light" must win over "Master Bedroom".
        for original in sorted(present, key=len, reverse=True):
            escaped = re.escape(original)
            if original[:1].isalnum():
                escaped = r"\b" + escaped
            if original[-1:].isalnum():
                escaped = escaped + r"\b"
            parts.append(escaped)
        return re.compile("|".join(parts))

    def data(self, obj):
        """Recursively pseudonymise a structure, dropping sensitive keys.

        Used for anything that is still JSON when redacted — device payloads,
        status records — where a key name tells us a value is a credential.
        """
        if isinstance(obj, dict):
            clean = {}
            for key, value in obj.items():
                lowered = str(key).lower()
                if lowered in SENSITIVE_KEYS_EXACT or any(
                        part in lowered for part in SENSITIVE_KEY_PARTS):
                    clean[key] = _REDACTED
                else:
                    clean[key] = self.data(value)
            return clean
        if isinstance(obj, list):
            return [self.data(v) for v in obj]
        if isinstance(obj, str):
            return self.text(obj)
        return obj

    # ── internals ───────────────────────────────────────────────────────────

    def _url(self, match: re.Match) -> str:
        scheme, host = match.group(1), match.group(2)
        if _is_private_host(host):
            return match.group(0)
        return f"{scheme}://<remote-host-redacted>"

    def _ip(self, match: re.Match) -> str:
        raw = match.group(0)
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            return raw                       # e.g. a version string like 1.2.3.4
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified:
            return raw                       # kept ON PURPOSE — see module docstring
        return "<public-ip-redacted>"

    # ── reporting ───────────────────────────────────────────────────────────

    def standin_for(self, device_id: str) -> str | None:
        """The webCoRE-shaped stand-in a picker device was given, if any."""
        value = self._literal.get(device_id)
        return value if value and value.startswith(":") else None

    def summary(self) -> str:
        return (f"{self._entity_n} device name(s), {self._area_n} area(s) and "
                f"{self._piston_n} piston name(s) replaced with stand-ins")

    @staticmethod
    def header_note() -> str:
        """Goes at the top of every shared bundle. Admits the limit rather than
        over-promising — Jeremy's instruction."""
        return (
            "PRIVACY: device names, entity ids, areas and piston names have been\n"
            "replaced with consistent stand-ins (Device 1, Area 2, Piston 3 — the\n"
            "same device reads the same everywhere, so this is still diagnosable).\n"
            "Tokens, passwords and any lock/alarm codes are removed. Public IPs and\n"
            "remote hostnames are removed; PRIVATE addresses (192.168.x, 10.x) are\n"
            "kept deliberately — they mean nothing off your network and help a lot\n"
            "when reading a report.\n"
            "LIMIT, stated honestly: free text YOU typed inside a piston — a spoken\n"
            "message, a notification body — cannot be reliably detected and may\n"
            "still appear below. Please skim before sending."
        )


async def build_from_ha(pistons: list | None = None,
                        with_devices: bool = True) -> Redactor:
    """A Redactor primed with everything this instance knows how to name.

    Best-effort: HA being unreachable must never stop a bug report being made,
    so the redactor degrades to whatever it could learn (patterns still apply).

    `with_devices` also builds the webCoRE-style device legend — the PICKER
    devices a piston actually references, each with its type stand-in and enough
    detail to rebuild it for testing.
    """
    red = Redactor()
    try:
        from . import ha_client
        regs = await ha_client.fetch_registries()
    except Exception:
        regs = {}

    # webCoRE-shaped picker devices FIRST: these are what piston JSON actually
    # references, so their stand-ins must be claimed before anything else.
    if with_devices and regs:
        try:
            from . import device_pipeline
            payload = device_pipeline.build_device_payload(regs)
            red.resolution = payload.get("resolution_map") or {}
            for device_id, device in (payload.get("devices") or {}).items():
                red.learn_webcore_device(
                    device_id, device.get("cn"), device.get("n") or "",
                    extra={"cn": list(device.get("cn") or [])})
        except Exception:
            pass                       # a bug report must still be producible

    # PISTONS FIRST. A name claims its stand-in on a first-come basis, and a
    # piston is often named after the device it controls ("Garage Door"). In a
    # PistonCore report that name means the piston, so it should read
    # "Piston 4", not "Device 1489" — which is what happened when devices were
    # learned first.
    for entry in (pistons or []):
        red.learn_piston(entry.get("name") or "")

    states = {s["entity_id"]: s.get("attributes", {})
              for s in (regs.get("states") or [])}
    for area in (regs.get("areas") or []):
        red.learn_area(area.get("name") or "")
    for entity in (regs.get("entities") or []):
        eid = entity.get("entity_id")
        if not eid:
            continue
        friendly = (entity.get("name") or entity.get("original_name")
                    or states.get(eid, {}).get("friendly_name"))
        red.learn_entity(eid, friendly)
    # Any entity that exists only as state (no registry entry).
    for eid, attrs in states.items():
        red.learn_entity(eid, attrs.get("friendly_name"))
    for device in (regs.get("devices") or []):
        red.learn_device(device.get("name_by_user") or device.get("name") or "")
    return red

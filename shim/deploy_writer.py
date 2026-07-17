"""Write transport: HOW compiled files reach HA's /config
(COMPILER_DECISIONS_DEPLOY.md §2.5 — two first-class modes, one interface).

- Mode "local": HA's config dir is reachable as a local path (add-on
  supervisor mapping, co-located Docker shared volume, or a host-level
  SMB/CIFS mount bind-mounted into the container — Jeremy's Unraid setup).
  Plain file ops.
- Mode "smb": PistonCore speaks SMB itself to HA's Samba-share add-on
  (HA in a VM/HAOS/remote box with nothing mounted at the host layer).
  Uses smbprotocol's smbclient high-level API.

The compiler/deploy flow only ever sees write()/read()/delete()/probe();
which backend runs is a Settings choice (config.json: write_mode + fields).
"""

import os
import time
from pathlib import Path

from . import ha_client


class WriteTargetError(Exception):
    """Environmental error — the write target is missing/unreachable/denied.
    Always names the target; never a silent drop (make-it-work rule: this is
    a missing dependency, not a feature cut)."""


def _config() -> dict:
    return ha_client._load_config()


class LocalWriter:
    def __init__(self, root: str):
        if not root:
            raise WriteTargetError("write_mode is 'local' but ha_config_path is not set (Settings).")
        self.root = Path(root)

    def _path(self, relpath: str) -> Path:
        return self.root / relpath

    def write(self, relpath: str, content: str) -> None:
        p = self._path(relpath)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def read(self, relpath: str) -> str:
        return self._path(relpath).read_text(encoding="utf-8")

    def delete(self, relpath: str) -> None:
        p = self._path(relpath)
        if p.exists():
            p.unlink()

    def describe(self) -> str:
        return f"local path {self.root}"


class SmbWriter:
    def __init__(self, host: str, share: str, username: str, password: str):
        if not (host and share and username):
            raise WriteTargetError(
                "write_mode is 'smb' but smb_host/smb_share/smb_username are not all set (Settings).")
        try:
            import smbclient  # smbprotocol package
        except ImportError as exc:
            raise WriteTargetError(
                "SMB mode needs the 'smbprotocol' package (pip install smbprotocol / rebuild the image).") from exc
        self._smbclient = smbclient
        self.host, self.share = host, share
        smbclient.ClientConfig(username=username, password=password)

    def _unc(self, relpath: str) -> str:
        rel = relpath.replace("/", "\\")
        return f"\\\\{self.host}\\{self.share}\\{rel}"

    def write(self, relpath: str, content: str) -> None:
        parts = relpath.split("/")[:-1]
        built = ""
        for part in parts:  # makedirs, tolerating pre-existing
            built = f"{built}/{part}" if built else part
            try:
                self._smbclient.mkdir(self._unc(built))
            except OSError:
                pass
        with self._smbclient.open_file(self._unc(relpath), mode="w", encoding="utf-8") as f:
            f.write(content)

    def read(self, relpath: str) -> str:
        with self._smbclient.open_file(self._unc(relpath), mode="r", encoding="utf-8") as f:
            return f.read()

    def delete(self, relpath: str) -> None:
        try:
            self._smbclient.remove(self._unc(relpath))
        except OSError:
            pass

    def describe(self) -> str:
        return f"SMB //{self.host}/{self.share}"


def get_writer():
    """Backend per Settings (config.json write_mode: 'local' | 'smb')."""
    cfg = _config()
    mode = cfg.get("write_mode", "local")
    if mode == "smb":
        return SmbWriter(cfg.get("smb_host", ""), cfg.get("smb_share", "config"),
                         cfg.get("smb_username", ""), cfg.get("smb_password", ""))
    return LocalWriter(cfg.get("ha_config_path", ""))


def probe() -> dict:
    """The Settings 'Test write target' check: write + read-back + delete a
    probe file so a bad share/mount fails VISIBLY at setup, not silently at
    first compile (COMPILER_DECISIONS_DEPLOY §2.5)."""
    writer = get_writer()
    relpath = "pistoncore/.pistoncore_write_probe"
    stamp = f"pistoncore probe {time.time()}"
    try:
        writer.write(relpath, stamp)
        back = writer.read(relpath)
        writer.delete(relpath)
    except WriteTargetError:
        raise
    except Exception as exc:
        raise WriteTargetError(f"Probe failed against {writer.describe()}: {exc}") from exc
    if back != stamp:
        raise WriteTargetError(f"Probe read-back mismatch against {writer.describe()}.")
    return {"ok": True, "target": writer.describe()}

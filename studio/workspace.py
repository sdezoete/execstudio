"""Short-lived storage for uploaded decks and generated files.

Files live in work/ next to server.py, under random ids, and are deleted after
`work_retention_hours`. Nothing here is a permanent record.
"""
import re
import secrets
import threading
import time
from pathlib import Path

_ID = re.compile(r"^[a-f0-9]{32}$")


class Workspace:
    def __init__(self, root, retention_hours=24):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.retention = retention_hours * 3600
        self._lock = threading.Lock()
        self._last_sweep = 0.0

    def _path(self, fid, suffix):
        if not _ID.match(fid or ""):
            raise KeyError(fid)
        return self.root / (fid + suffix)

    def put(self, data, name):
        self.sweep()
        fid = secrets.token_hex(16)
        self._path(fid, ".bin").write_bytes(data)
        self._path(fid, ".name").write_text(name, encoding="utf-8")
        return fid

    def get(self, fid):
        """Returns (bytes, original name); raises KeyError if unknown or expired."""
        p = self._path(fid, ".bin")
        if not p.exists():
            raise KeyError(fid)
        name_p = self._path(fid, ".name")
        name = name_p.read_text(encoding="utf-8") if name_p.exists() else "file"
        return p.read_bytes(), name

    def sweep(self, force=False):
        now = time.time()
        if not force and now - self._last_sweep < 600:
            return
        with self._lock:
            self._last_sweep = now
            for f in self.root.iterdir():
                try:
                    if f.is_file() and now - f.stat().st_mtime > self.retention:
                        f.unlink()
                except OSError:
                    pass  # file in use (Windows) – try again on the next sweep

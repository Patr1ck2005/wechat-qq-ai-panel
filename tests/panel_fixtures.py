"""Synthetic fixtures with recoverable Windows cleanup and no deletion fallback."""
from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile
import warnings


def _linked(path: Path) -> bool:
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & 0x400)


class RecycleFixture:
    def __init__(self, prefix="case-"):
        if not re.fullmatch(r"[A-Za-z0-9_-]{0,80}", prefix):
            raise ValueError("INVALID_FIXTURE_PREFIX")
        repo = Path(__file__).resolve().parents[1]
        self.base = repo / ".local" / "test-fixtures"
        for directory in (repo / ".local", self.base):
            if directory.exists() and _linked(directory):
                raise RuntimeError("LINKED_FIXTURE_ROOT")
            directory.mkdir(exist_ok=True)
        self.name = tempfile.mkdtemp(prefix=prefix, dir=self.base)
        self.cleanup_outcome = "pending"

    def __enter__(self):
        return self.name

    def __exit__(self, *_args):
        self.cleanup()

    def cleanup(self):
        target = Path(self.name)
        if self.cleanup_outcome != "pending":
            return
        try:
            if target.parent != self.base or not target.resolve().is_relative_to(self.base.resolve()):
                raise RuntimeError("FIXTURE_PATH_CHANGED")
            for directory in (self.base.parent, self.base, target):
                if _linked(directory):
                    raise RuntimeError("LINKED_FIXTURE")
            def fail(error):
                raise error
            for current, directories, files in os.walk(target, followlinks=False, onerror=fail):
                if any(_linked(Path(current) / name) for name in directories + files):
                    raise RuntimeError("LINKED_FIXTURE")
            if os.name != "nt":
                raise RuntimeError("WINDOWS_RECYCLE_REQUIRED")
            # Do not import the top-level dispatcher: only modern IFileOperation is permitted.
            from send2trash.win.modern import send2trash
            send2trash(str(target))
            if target.exists() or target.is_symlink():
                raise RuntimeError("FIXTURE_RECYCLE_INCOMPLETE")
            self.cleanup_outcome = "recycled"
        except Exception as error:
            self.cleanup_outcome = "retained"
            warnings.warn("Synthetic fixture retained; modern recycling unavailable (" +
                          type(error).__name__ + ").", RuntimeWarning, stacklevel=2)

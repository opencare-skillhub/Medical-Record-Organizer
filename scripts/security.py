"""Security helpers for private medical-data files."""
from __future__ import annotations

import os
from pathlib import Path


def ensure_private_dir(path: str | Path) -> Path:
    """Create a directory and restrict it to the current user on POSIX."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        try:
            p.chmod(0o700)
        except OSError:
            pass
    return p


def write_private_text(path: str | Path, text: str, *, encoding: str = "utf-8") -> Path:
    """Write text and restrict the file to the current user on POSIX."""
    p = Path(path)
    ensure_private_dir(p.parent)
    p.write_text(text, encoding=encoding)
    if os.name == "posix":
        try:
            p.chmod(0o600)
        except OSError:
            pass
    return p

"""forzeos_resources.py

Project-specific resource helper for ForzeOS.

This module provides small, safe helpers the rest of the ForzeOS code
expects when resolving assets and icons. It intentionally keeps heavy
dependencies optional so the runtime can import it in lightweight
environments (editors, CI) while providing useful runtime helpers when
Pillow/Tkinter are available.

Usage highlights the ForzeOS code expects:
- `RESOURCE_DIR` (base path for packaged assets)
- `get_resource_path(name)` -> Path
- `resolve_path(path_or_name)` -> Path (accepts absolute or resource-relative)
- `load_icon(...)` -> Tk PhotoImage or path fallback
- JSON helpers: `read_json`, `atomic_write_json`
"""
from __future__ import annotations
import os
import json
import shutil
from pathlib import Path
from typing import Optional, Any

try:
    from PIL import Image, ImageTk
    _PIL_AVAILABLE = True
except Exception:
    Image = None
    ImageTk = None
    _PIL_AVAILABLE = False

# Default resource directories used by ForzeOS
ROOT_DIR = Path(__file__).parent.resolve()
ASSETS_DIR = (ROOT_DIR / 'assets').resolve()
ICONS_DIR = (ASSETS_DIR / 'icons')
CONFIG_DIR = (ROOT_DIR / 'config')
USER_DATA_DIR = (ROOT_DIR / 'data')

# Ensure directories exist lazily
def ensure_dirs():
    for d in (ASSETS_DIR, ICONS_DIR, CONFIG_DIR, USER_DATA_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


ensure_dirs()


RESOURCE_DIR = ASSETS_DIR


def get_resource_path(name: str, ensure_exists: bool = False) -> Path:
    """Return a resolved Path for a resource name relative to `ASSETS_DIR`.

    If `name` is an absolute path it is returned as a Path. When
    `ensure_exists` is True a FileNotFoundError is raised if missing.
    """
    p = Path(name)
    if not p.is_absolute():
        p = (ASSETS_DIR / name).resolve()
    if ensure_exists and not p.exists():
        raise FileNotFoundError(p)
    return p


def resolve_path(path_or_name: str) -> Path:
    """Resolve a path that may be either absolute or relative to assets.

    This is handy because ForzeOS accepts both absolute user file paths
    (e.g. C:\...\icon.png) and resource-relative names (e.g. 'icons/x.png').
    """
    return get_resource_path(path_or_name, ensure_exists=False)


def load_image(path_or_name: str, max_size: Optional[tuple[int, int]] = None):
    """Return a PIL Image if Pillow is available, otherwise None."""
    if not _PIL_AVAILABLE:
        return None
    p = resolve_path(path_or_name)
    if not p.exists():
        raise FileNotFoundError(p)
    img = Image.open(p)
    if max_size:
        img.thumbnail(max_size)
    return img


def load_icon(path_or_name: str, size: Optional[tuple[int, int]] = None):
    """Return a Tk-compatible PhotoImage if possible, otherwise a str path.

    This mirrors the fallback semantics the ForzeOS code expects: if GUI
    imaging libs aren't available, callers receive a path and can handle
    loading/displaying it themselves.
    """
    p = resolve_path(path_or_name)
    if not p.exists():
        # If the passed value is absolute and missing, just return it.
        return str(p)
    if not _PIL_AVAILABLE or ImageTk is None:
        return str(p)
    img = load_image(p, max_size=size)
    if img is None:
        return str(p)
    try:
        return ImageTk.PhotoImage(img)
    except Exception:
        return str(p)


def atomic_write_json(path: Path | str, data: Any, encoding: str = 'utf-8') -> None:
    """Write JSON atomically (write .tmp then replace).

    Used by parts of ForzeOS to avoid partial writes on crash.
    """
    p = Path(path)
    tmp = p.with_suffix(p.suffix + '.tmp')
    with open(tmp, 'w', encoding=encoding) as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    try:
        os.replace(str(tmp), str(p))
    except Exception:
        shutil.move(str(tmp), str(p))


def read_json(path: Path | str, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        with open(p, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return default


def list_resource_icons() -> list[str]:
    """Return a list of filenames in the icons directory (if present)."""
    try:
        return [str(p.name) for p in ICONS_DIR.iterdir() if p.is_file()]
    except Exception:
        return []


# Convenience default icon lookup used in parts of ForzeOS
DEFAULT_ICONS = {
    'app': str((ICONS_DIR / 'app.png').resolve()),
    'folder': str((ICONS_DIR / 'folder.png').resolve()),
    'default': str((ICONS_DIR / 'default.png').resolve()),
}


__all__ = [
    'ROOT_DIR', 'ASSETS_DIR', 'ICONS_DIR', 'CONFIG_DIR', 'USER_DATA_DIR',
    'RESOURCE_DIR', 'get_resource_path', 'resolve_path', 'load_image',
    'load_icon', 'atomic_write_json', 'read_json', 'list_resource_icons',
    'ensure_dirs', 'DEFAULT_ICONS'
]

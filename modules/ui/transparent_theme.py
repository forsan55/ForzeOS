"""Transparent theme loader for ForzeOS
Provides: validate_theme(path), load_theme(path), apply_theme(forze_instance, theme_dict, live=True), revert_theme(forze_instance)
Theme files must be JSON with simple fields; no executable code allowed.
"""
import json
import os
from pathlib import Path
import datetime

SCHEMA_KEYS = {
    'engine',       # simple | acrylic | compositor (informational)
    'background',   # color hex or image path
    'alpha',        # 0.0 - 1.0
    'blur',         # false or int level
    'accent_colors',# dict with primary/secondary/text
    'ui_overrides'  # optional dict of widget style tweaks
}

DEFAULT_THEME = {
    'engine': 'simple',
    'background': None,
    'alpha': 0.9,
    'blur': False,
    'accent_colors': {'primary': '#1ABC9C','secondary':'#34495E','text':'#FFFFFF'},
    'ui_overrides': {}
}


def validate_theme_path(path: str, workspace_root: str = None) -> bool:
    """Ensure the path is a local file and within optional workspace_root sandbox."""
    try:
        p = Path(path).resolve()
        if workspace_root:
            root = Path(workspace_root).resolve()
            try:
                p.relative_to(root)
            except Exception:
                return False
        return p.is_file()
    except Exception:
        return False


def load_theme(path: str) -> dict:
    """Load and return theme dict. Raises ValueError on invalid format."""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError('Theme must be a JSON object')
    # Only keep whitelisted keys
    out = DEFAULT_THEME.copy()
    for k in SCHEMA_KEYS:
        if k in data:
            out[k] = data[k]
    # basic validation
    alpha = out.get('alpha')
    if alpha is None or not isinstance(alpha, (int, float)) or not (0.0 <= float(alpha) <= 1.0):
        out['alpha'] = DEFAULT_THEME['alpha']
    return out


def apply_theme(forze_instance, theme: dict, live: bool = True) -> None:
    """Apply theme to `forze_instance` (an instance of ForzeOS) safely.
    This updates `forze_instance.config['settings']['transparent_theme']` and
    attempts to apply non-destructive visual changes. Does not execute code
    from theme files and provides a fallback on error.
    """
    try:
        cfg = getattr(forze_instance, 'config', None)
        if cfg is None:
            return
        s = cfg.setdefault('settings', {})
        # create a safe backup of relevant settings so we can revert if something goes wrong
        try:
            root = Path(__file__).resolve().parents[2]
            backup_path = root / 'forzeos_transparent_theme_backup.json'
            prev_snapshot = {
                'timestamp': datetime.datetime.utcnow().isoformat() + 'Z',
                'transparent_theme': s.get('transparent_theme'),
                'wallpaper_color': s.get('wallpaper_color'),
                'global_opacity': s.get('global_opacity'),
                'taskbar_transparent': s.get('taskbar_transparent')
            }
            try:
                with open(backup_path, 'w', encoding='utf-8') as bf:
                    json.dump(prev_snapshot, bf, indent=2, ensure_ascii=False)
            except Exception:
                # if backup fails, continue without blocking theme application
                pass
        except Exception:
            pass
        # store theme and enable flag
        s['transparent_theme'] = {
            'enabled': True,
            'theme': theme
        }
        # attempt live application where possible
        if live:
            # update a few known runtime properties used elsewhere
            try:
                # set default wallpaper color/background if specified
                bg = theme.get('background')
                if isinstance(bg, str) and bg.startswith('#'):
                    s['wallpaper_color'] = bg
                # store alpha and taskbar transparency used by System
                s['global_opacity'] = float(theme.get('alpha', 0.9))
                s['taskbar_transparent'] = bool(theme.get('alpha', 1.0) < 1.0)
                # persist config if ForzeOS exposes save_config
                if hasattr(forze_instance, 'save_config'):
                    try:
                        forze_instance.save_config()
                    except Exception:
                        pass
                # call live settings applier if available
                try:
                    import forzeos_core
                    if hasattr(forze_instance, '__class__'):
                        # prefer a top-level helper if present
                        if hasattr(forzeos_core, 'apply_live_settings'):
                            forzeos_core.apply_live_settings(forze_instance)
                except Exception:
                    pass
            except Exception:
                pass
    except Exception:
        # fail silently to avoid breaking the host
        pass


def revert_theme(forze_instance) -> None:
    """Revert transparent theme to defaults (disables it in config).
    Does not remove user theme files.
    """
    try:
        cfg = getattr(forze_instance, 'config', None)
        if not cfg:
            return
        s = cfg.setdefault('settings', {})
        s.pop('transparent_theme', None)
        # optional: restore wallpaper_color default
        # do not aggressively modify other keys
        if hasattr(forze_instance, 'save_config'):
            try:
                forze_instance.save_config()
            except Exception:
                pass
        try:
            import forzeos_core
            if hasattr(forzeos_core, 'apply_live_settings'):
                forzeos_core.apply_live_settings(forze_instance)
        except Exception:
            pass
    except Exception:
        pass

import json
from pathlib import Path
import os

from modules.ui import transparent_theme as tt
import forzeos_core

class DummyForze:
    def __init__(self, cfg_path=None):
        self.config = {'settings': {}}
        self._cfg_path = cfg_path
    def save_config(self):
        if self._cfg_path:
            with open(self._cfg_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)


def run_test():
    root = Path(__file__).resolve().parents[2]
    theme_path = root / 'themes' / 'forze_hyprland.json'
    cfg_path = root / 'forzeos_config.json'
    df = DummyForze(cfg_path=str(cfg_path))
    print('Loading theme:', theme_path)
    theme = tt.load_theme(str(theme_path))
    print('Theme loaded:', theme.get('accent_colors'))
    print('Applying theme (live=False)')
    tt.apply_theme(df, theme, live=False)
    print('Config after apply (live=False):', df.config.get('settings', {}).get('transparent_theme', {}).keys())
    # now live apply
    print('Applying theme (live=True)')
    tt.apply_theme(df, theme, live=True)
    print('Config after apply (live=True):', df.config.get('settings', {}).get('transparent_theme', {}).keys())
    # call apply_live_settings (should not raise)
    try:
        forzeos_core.apply_live_settings(df)
        print('apply_live_settings passed without exception')
    except Exception as e:
        print('apply_live_settings raised:', e)

if __name__ == '__main__':
    run_test()

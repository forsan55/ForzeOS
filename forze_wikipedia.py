"""ForzeOS Wikipedia assistant module

Provides a safe, toggleable Wikipedia feature for the EnhancedAssistantAI.

Features:
- Commands: "wiki <topic>", "wikipedia <topic>", "nedir <topic>", "kimdir <topic>"
- Toggle: "wikipedia aç" / "wikipedia kapa"
- Integrates with assistant help output by appending a Wikipedia section
- Uses config key: assistant.modules.wikipedia.enabled (default True)
"""
from pathlib import Path
import json
import threading
import traceback
import random

try:
    import wikipedia
    WIKI_AVAILABLE = True
except Exception:
    WIKI_AVAILABLE = False

DEFAULT_CONFIG = {"assistant": {"modules": {"wikipedia": {"enabled": True}}}}


def _config_path_candidates():
    p1 = Path(__file__).with_name('forzeos_config.json')
    p2 = Path.cwd() / 'forzeos_config.json'
    return [p1, p2]


def _load_config():
    for p in _config_path_candidates():
        try:
            if p.exists():
                return json.loads(p.read_text(encoding='utf-8')), p
        except Exception:
            continue
    return {}, None


def _save_config(obj, path):
    try:
        path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding='utf-8')
        return True
    except Exception:
        return False


def ensure_setting_default():
    cfg, path = _load_config()
    if path is None:
        # no config file found; don't create one unexpectedly, but keep defaults in-memory
        return cfg, path
    changed = False
    cur = cfg
    # ensure nested keys
    if 'assistant' not in cur:
        cur['assistant'] = {}
        changed = True
    if 'modules' not in cur['assistant']:
        cur['assistant']['modules'] = {}
        changed = True
    if 'wikipedia' not in cur['assistant']['modules']:
        cur['assistant']['modules']['wikipedia'] = {'enabled': True}
        changed = True
    else:
        # if enabled missing, default to True
        if 'enabled' not in cur['assistant']['modules']['wikipedia']:
            cur['assistant']['modules']['wikipedia']['enabled'] = True
            changed = True
    if changed:
        _save_config(cur, path)
    return cur, path


def is_enabled_from_config():
    cfg, _ = _load_config()
    try:
        return bool(cfg.get('assistant', {}).get('modules', {}).get('wikipedia', {}).get('enabled', True))
    except Exception:
        return True


def _normalize_cmd(text: str):
    return (text or '').strip()


def handle_command(text: str) -> str:
    """Helper for testing: process a command using the same logic as the assistant wrapper."""
    # simple local invocation of the same matching logic
    t = _normalize_cmd(text)
    # reuse language-insensitive lowering for matching prefixes
    low = t.lower()
    # toggle
    if low in ('wikipedia aç', 'wikipedia ac'):
        cfg, path = _load_config()
        if path:
            cfg.setdefault('assistant', {}).setdefault('modules', {}).setdefault('wikipedia', {})['enabled'] = True
            _save_config(cfg, path)
        return 'Wikipedia özelliği açıldı.'
    if low in ('wikipedia kapa',):
        cfg, path = _load_config()
        if path:
            cfg.setdefault('assistant', {}).setdefault('modules', {}).setdefault('wikipedia', {})['enabled'] = False
            _save_config(cfg, path)
        return 'Wikipedia özelliği kapatıldı.'

    # If user just says 'wikipedia' or 'wiki', return a playful/random reply
    if low in ('wikipedia', 'wiki'):
        replies = [
            'Wikipedia mı? Hemen bir şeyler bulayım...',
            'Wikipedia modu: Hazır. Ne öğrenmek istiyorsun?',
            'Wikipedia deyince aklıma ansiklopedi geliyor — bir konu ver!',
            'Bir konu söyle, Wikipedia özetini getiririm.',
            'Wikipedia açık — aramak için "wiki <konu>" yaz.'
        ]
        return random.choice(replies)

    # delegate to search prefixes
    for prefix in ('wiki ', 'wikipedia ', 'nedir ', 'kimdir '):
        if low.startswith(prefix):
            # reuse main behavior by calling internal register-style handler
            # emulate by invoking the summary path
            if not is_enabled_from_config():
                return 'Wikipedia özelliği kapalı.'
            if not WIKI_AVAILABLE:
                return 'Wikipedia modülü kullanılamıyor (yüklü değil).'
            topic = t[len(prefix):].strip()
            if not topic:
                return 'Aranacak konu belirtilmedi.'
            try:
                try:
                    wikipedia.set_lang('tr')
                except Exception:
                    pass
                summary = wikipedia.summary(topic, sentences=3)
                return summary
            except wikipedia.exceptions.DisambiguationError as e:
                opts = e.options[:10]
                lines = ['Birden fazla anlam bulundu. Lütfen daha spesifik olun. Bazı seçenekler:']
                lines += [f"- {o}" for o in opts]
                return '\n'.join(lines)
            except wikipedia.exceptions.PageError:
                return 'Bu konu için sayfa bulunamadı.'
            except Exception:
                traceback.print_exc()
                return 'Wikipedia araması sırasında hata oluştu.'

    return ''


def register(forzeos_globals: dict = None):
    """Register wrappers on EnhancedAssistantAI if available in provided globals.

    This function is safe to call multiple times. If EnhancedAssistantAI is not
    yet available, it will retry once after a short delay.
    """
    try:
        _attempt_register(forzeos_globals)
    except Exception:
        # Try again shortly in case ForzeOS is still initializing
        timer = threading.Timer(1.0, lambda: _attempt_register(forzeos_globals))
        timer.daemon = True
        timer.start()


def _attempt_register(forzeos_globals: dict = None):
    # determine where EnhancedAssistantAI lives
    g = forzeos_globals if isinstance(forzeos_globals, dict) else globals()
    Enhanced = g.get('EnhancedAssistantAI') or g.get('EnhancedAssistant')
    if Enhanced is None:
        # try sys.modules
        import sys
        for m in list(sys.modules.values()):
            if not m:
                continue
            Enhanced = getattr(m, 'EnhancedAssistantAI', None)
            if Enhanced:
                break
    if Enhanced is None:
        return

    # wrap execute_command
    if hasattr(Enhanced, '_forze_wiki_wrapped') and getattr(Enhanced, '_forze_wiki_wrapped'):
        return

    orig_exec = getattr(Enhanced, 'execute_command', None)
    orig_reply = getattr(Enhanced, 'reply', None)

    def wiki_handle(self, text: str, session_id: str = None):
        t = _normalize_cmd(text).lower()
        # toggle commands
        if t in ('wikipedia aç', 'wikipedia ac'):
            cfg, path = _load_config()
            if path:
                cfg.setdefault('assistant', {}).setdefault('modules', {}).setdefault('wikipedia', {})['enabled'] = True
                _save_config(cfg, path)
            return 'Wikipedia özelliği açıldı.'
        if t in ('wikipedia kapa',):
            cfg, path = _load_config()
            if path:
                cfg.setdefault('assistant', {}).setdefault('modules', {}).setdefault('wikipedia', {})['enabled'] = False
                _save_config(cfg, path)
            return 'Wikipedia özelliği kapatıldı.'

        # search commands
        for prefix in ('wiki ', 'wikipedia ', 'nedir ', 'kimdir '):
            if t.startswith(prefix):
                if not is_enabled_from_config():
                    return 'Wikipedia özelliği kapalı.'
                if not WIKI_AVAILABLE:
                    return 'Wikipedia modülü kullanılamıyor (yüklü değil).'
                topic = text[len(prefix):].strip()
                if not topic:
                    return 'Aranacak konu belirtilmedi.'
                try:
                    # prefer Turkish
                    try:
                        wikipedia.set_lang('tr')
                    except Exception:
                        pass
                    summary = wikipedia.summary(topic, sentences=3)
                    return summary
                except wikipedia.exceptions.DisambiguationError as e:
                    opts = e.options[:10]
                    lines = ['Birden fazla anlam bulundu. Lütfen daha spesifik olun. Bazı seçenekler:']
                    lines += [f"- {o}" for o in opts]
                    return '\n'.join(lines)
                except wikipedia.exceptions.PageError:
                    return 'Bu konu için sayfa bulunamadı.'
                except Exception:
                    traceback.print_exc()
                    return 'Wikipedia araması sırasında hata oluştu.'

        return None

    def new_execute(self, text: str, session_id: str = None):
        try:
            res = wiki_handle(self, text, session_id)
            if res is not None:
                return res
        except Exception:
            traceback.print_exc()
        if orig_exec:
            return orig_exec(self, text, session_id)
        return None

    def new_reply(self, text: str, session_id: str = None):
        # if user asked for help, append Wikipedia section
        try:
            out = orig_reply(self, text, session_id) if orig_reply else None
        except Exception:
            out = None
        t = _normalize_cmd(text).lower()
        help_triggers = ('yardim', 'help')
        if any(t.startswith(h) for h in help_triggers):
            status = 'Açık' if is_enabled_from_config() else 'Kapalı'
            wiki_help = ("\n\n--- Wikipedia Yardım ---\n"
                         "Arama: wiki <konu>, wikipedia <konu>, nedir <konu>, kimdir <konu>\n"
                         f"Durum: {status}\n"
                         "Açma/Kapama: wikipedia aç / wikipedia kapa\n")
            if isinstance(out, str):
                return out + wiki_help
            else:
                return wiki_help
        return out

    # attach wrappers
    try:
        setattr(Enhanced, 'execute_command', new_execute)
        setattr(Enhanced, 'reply', new_reply)
        setattr(Enhanced, '_forze_wiki_wrapped', True)
    except Exception:
        # maybe Enhanced is a class; patch instance methods instead
        try:
            Enhanced.execute_command = new_execute
            Enhanced.reply = new_reply
            Enhanced._forze_wiki_wrapped = True
        except Exception:
            raise


# Run ensure default config (non-destructive)
try:
    ensure_setting_default()
except Exception:
    pass

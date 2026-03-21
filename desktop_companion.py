import os
import threading
import time
import random
import re
import tkinter as tk
from tkinter import Toplevel, Frame, Label, Entry, Text, Scrollbar, Button
from PIL import Image, ImageTk
from typing import TYPE_CHECKING
import math
import math_engine
# hint to analyzers but avoid importing at runtime to prevent unresolved import warnings
if TYPE_CHECKING:
    # type-checker only: this helps editors like Pylance know the symbol exists
    from function_art import FunctionArtWindow  # type: ignore
FUNCTION_ART_AVAILABLE = False
FunctionArtWindow = None
import logging
logger = logging.getLogger(__name__)

# Assistant availability: prefer the offline enhanced assistant, fallback to the
# small rule-based assistant. Use dynamic importlib loading so static analyzers
# (Pylance) don't error when the file is present only at runtime or outside the
# current analysis root.
AssistantClass = None
try:
    # Prefer the canonical modular assistant if present (assistant_ai). Fall back to
    # the lightweight offline assistant (assistant_ai_offline) or older modules.
    import importlib
    try:
        mod = importlib.import_module('assistant_ai')
        AssistantClass = getattr(mod, 'AssistantAI', None)
        if AssistantClass:
            logger.debug("Using assistant_ai.AssistantAI as primary assistant")
    except Exception:
        # not available - try the offline embedded style module
        try:
            mod = importlib.import_module('assistant_ai_offline')
            AssistantClass = getattr(mod, 'EnhancedAssistantAI', None)
            if AssistantClass:
                logger.debug("Using assistant_ai_offline.EnhancedAssistantAI as fallback")
        except Exception:
            # final attempt: older assistant_ai variant names
            try:
                mod2 = importlib.import_module('assistant_ai')
                AssistantClass = getattr(mod2, 'EnhancedAssistantAI', getattr(mod2, 'AssistantAI', None))
                if AssistantClass:
                    logger.debug("Using legacy assistant_ai.* as fallback")
            except Exception:
                AssistantClass = None
except Exception:
    # best-effort: leave AssistantClass as None; runtime code will handle missing assistant
    AssistantClass = None


class DesktopCompanion:
    """A small draggable desktop companion for ForzeOS.

    Usage (from ForzeOS):
        from desktop_companion import DesktopCompanion
        self.companion = DesktopCompanion(self)
        self.companion.install(x=80, y=150)

    Features:
    - Loads sprites from "forzeos_assets" folder using names like
      companion_idle_0.png, companion_talk_0.png, etc.
    - Shows a borderless Tk Toplevel with animation.
    - Click to open a chat balloon (simple Entry + Text history).
    - Rule-based commands mapped to ForzeOS methods (open_social_media, ...).
    - Optional pyttsx3 TTS (non-blocking) if installed.
    """

    ASSET_DIR = os.path.join(os.path.dirname(__file__), "forzeos_assets")

    def __init__(self, forzeos_instance, size=96, fps=6):
        self.forzeos = forzeos_instance
        self.root = getattr(forzeos_instance, 'root', None)
        if self.root is None:
            raise RuntimeError("ForzeOS instance must expose a Tk root as `root` attribute")

        self.size = size
        self.fps = fps
        self.ai_enabled = True
        self._stop_anim = False
        # awaiting a follow-up topic for wiki command
        self._expecting_wiki_topic = False
        # Prefer the host-attached assistant if available to keep session state
        # centralized. Fall back to the imported AssistantClass only when needed.
        host_ai = getattr(forzeos_instance, 'assistant', None) or getattr(forzeos_instance, 'ai', None)
        if host_ai:
            # Use host-provided assistant instance to avoid duplicate/conflicting assistants
            self.ai = host_ai
        else:
            # No host assistant attached; instantiate the local AssistantClass if present.
            if AssistantClass is not None:
                try:
                    self.ai = AssistantClass()
                except Exception:
                    logger.exception('Failed to instantiate AssistantClass for DesktopCompanion')
                    self.ai = None
            else:
                self.ai = None
        # host open mapping placeholder (populated later)
        self._host_open_map = {}

        # sprite lists
        self.idle_imgs = []
        self.talk_imgs = []
        self.tap_imgs = []
        self.wave_imgs = []

        # tkinter widgets
        self.win = None
        self.canvas_label = None

        # animation state
        self._anim_thread = None
        self._anim_state = 'idle'  # idle, talk, tap, wave
        self._frame_index = 0
        self._last_blink = 0

        # chat
        self.chat_win = None
        self.history_text = None
        self.input_entry = None

        # TTS
        self._tts_engine = None
        self._tts_available = False
        try:
            import pyttsx3
            self.pyttsx3 = pyttsx3
            self._tts_engine = pyttsx3.init()
            # try to set a friendly voice if available
            try:
                voices = self._tts_engine.getProperty('voices')
                if voices:
                    # pick first non-empty
                    for v in voices:
                        if 'female' in getattr(v, 'name', '').lower() or 'female' in getattr(v, 'id', '').lower():
                            self._tts_engine.setProperty('voice', v.id)
                            break
            except Exception:
                pass
            self._tts_available = True
        except Exception:
            self._tts_available = False

        # commands mapping: lowercased trigger -> (callable, friendly_reply)
        # use local wrapper methods so mapping can be self-contained and easier to test
        self.command_map = {
            'open browser': (self.open_social_media, "Tarayıcıyı açıyorum — iyi gezmeler!"),
            'open social': (self.open_social_media, "Sosyal medyaya geçiyoruz — dikkatli ol!"),
            'open music': (self.open_music_studio, "Müziğe geçiliyor — ritmi yakala!"),
            'music studio': (self.open_music_studio, "Müzik stüdyosu açıldı — kaliteli sesler bekliyor"),
            'open video editor': (self.open_video_editor, "Video editör hazır — kes, kopyala, yapıştır"),
            'open gallery': (self.open_gallery, "Galeriyi açıyorum — anıları karıştırma!"),
            'open pdf': (self.open_pdf_reader, "PDF okuyucuyu açıyorum — sayfaları yıpratma"),
            'show pdf': (self.open_pdf_reader, "Belgeyi açıyorum"),
            # Explicit log/audio mappings so companion recognizes common phrases
            'open log file': (self.open_log_file, "Log dosyasını açıyorum"),
            'open log': (self.open_log_file, "Log dosyasını açıyorum"),
            'show logs': (self.open_log_file, "Log dosyasını açıyorum"),
            'open audio settings': (self.open_audio_settings, "Ses ayarlarını açıyorum"),
            'help': (None, "Şunu yazabilirsin: open browser, open music, open video editor, open gallery, open pdf, shortcuts, companion settings"),
            'shortcuts': (self.open_shortcuts_manager, "Kısayollar penceresini açıyorum"),
            'companion settings': (self.open_companion_settings, "Asistan ayarlarını açıyorum"),
            'open function art': (self.open_function_art, "Function ART penceresini açıyorum"),
            'open settings': (self.open_companion_settings, "Ayarları açıyorum"),
            'ayarlar': (self.open_companion_settings, "Ayarları açıyorum"),
            'weather': (self.ai_weather, "Hava durumu bilgilerini getiriyorum..."),
            'sosyal medya': (self.open_social_media, "Sosyal medyayı açıyorum — dikkatli ol!"),
            'wikipedia': (self._cmd_wikipedia if hasattr(self, '_cmd_wikipedia') else None, "Wikipedia araması: wiki <konu>"),
            'wiki': (self._cmd_wikipedia if hasattr(self, '_cmd_wikipedia') else None, "Wikipedia araması: wiki <konu>"),
        }

        # extend with advanced commands (lowercased keys)
        try:
            self.command_map.update({
                'delete app': (self.delete_app, "Uygulamayı siliyorum..."),
                'open path': (self.open_path, "Dosya yöneticisini açıyorum..."),
                'dosya aç': (self.open_path, "Dosya yöneticisini açıyorum..."),
                'screenshot': (self.take_screenshot, "Ekran görüntüsü alınıyor..."),
                'change wallpaper': (self.change_wallpaper, "Duvar kağıdı ayarları açılıyor..."),
                'system info': (self.system_info, "Sistem bilgileri alınıyor..."),
                'joke': (self.ai_joke if getattr(self, 'ai', None) else None, "Bir şaka arıyorum..."),
                'şaka': (self.ai_joke if getattr(self, 'ai', None) else None, "Bir şaka arıyorum..."),
                'teach python': (self.ai_teach if getattr(self, 'ai', None) else None, "Python dersi getiriyorum..."),
                'motivate': (self.ai_motivate if getattr(self, 'ai', None) else None, "Motivasyon mesajı geliyor...")
            })
        except Exception:
            pass

        # polite random replies for unknown queries
        self.default_replies = [
            "Hehe, komik soru. Bunu yapamam ama başka bir şey dene!",
            "Bana bir görev ver: open browser, open music, open gallery...",
            "Hmm bunu bilmiyorum ama öğrenebilirim — merak etme, not aldım."
        ]

        # mouse drag
        self._drag_data = {'x': 0, 'y': 0}

        # allow move-on-rightclick (can be toggled via chat or host config)
        self.allow_move_on_rightclick = True
        try:
            self.allow_move_on_rightclick = bool(self.forzeos.config.get('desktop', {}).get('companion_allow_move', True))
        except Exception:
            pass

        # companion visibility behaviors
        try:
            dcfg = self.forzeos.config.get('desktop', {}) if hasattr(self.forzeos, 'config') else {}
            self.hide_on_open = bool(dcfg.get('companion_hide_on_open', False))
            self.keep_on_top_when_open = bool(dcfg.get('companion_keep_on_top', True))
        except Exception:
            self.hide_on_open = False
            self.keep_on_top_when_open = True

        # AI assistant enabled flag (persisted in host config)
        self.ai_enabled = True
        try:
            self.ai_enabled = bool(self.forzeos.config.get('desktop', {}).get('companion_ai_enabled', True))
        except Exception:
            pass

        # instantiate assistant if available (prefer AssistantClass set at module import)
        try:
            if AssistantClass is not None:
                # Try common constructor signatures; some assistants accept session_size/name
                try:
                    self.ai = AssistantClass(session_size=40, name='Forzos')
                except TypeError:
                    try:
                        self.ai = AssistantClass()
                    except Exception:
                        self.ai = None
                # inject available companion commands into assistant so help shows them
                try:
                    if getattr(self, 'ai', None):
                        cmds = sorted(list(self.command_map.keys()))
                        # only inject the command names (no duplicates)
                        self.ai.external_commands = cmds
                except Exception:
                    pass
                # also try to add host app names (if host exposes FILE_ASSOCIATIONS or desktops)
                try:
                    if getattr(self, 'ai', None):
                        app_names = [v[0] for v in getattr(self.forzeos, 'FILE_ASSOCIATIONS', {}).values() if isinstance(v, (list, tuple)) and v]
                        # add desktops listed in config
                        cfg_apps = []
                        try:
                            cfg = getattr(self.forzeos, 'config', {}) or {}
                            desktops = cfg.get('desktop', {}).get('desktops', {})
                            for k, lst in (desktops or {}).items():
                                for it in lst:
                                    n = it.get('name') if isinstance(it, dict) else None
                                    if n:
                                        cfg_apps.append(n)
                        except Exception:
                            pass
                        all_apps = sorted(set(app_names + cfg_apps))
                        if all_apps:
                            try:
                                existing = list(getattr(self.ai, 'external_commands', []) or [])
                                merged = sorted(set(existing + [a for a in all_apps if a]))
                                self.ai.external_commands = merged
                            except Exception:
                                pass
                except Exception:
                    pass
                # attach assistant to host for easy host-level access
                try:
                    setattr(self.forzeos, 'assistant', self.ai)
                except Exception:
                    pass
            else:
                self.ai = None
        except Exception:
            self.ai = None

        # Build a mapping of available host open_* methods and friendly app names
        try:
            self._host_open_map = {}  # lower-name -> callable
            # check ForzeOS FILE_ASSOCIATIONS first (maps ext -> (AppName, handler_name))
            try:
                fa = getattr(self.forzeos, 'FILE_ASSOCIATIONS', {}) or {}
                for v in fa.values():
                    if isinstance(v, (list, tuple)) and len(v) >= 2:
                        app_name = str(v[0]).strip().lower()
                        handler = v[1]
                        if isinstance(handler, str) and hasattr(self.forzeos, handler):
                            self._host_open_map[app_name] = getattr(self.forzeos, handler)
            except Exception:
                pass

            # Inspect ForzeOS methods starting with open_
            try:
                for name in dir(getattr(self.forzeos, '__class__', self.forzeos)):
                    if name.startswith('open_') or name.startswith('open'):
                        # friendly name: drop leading 'open_' and replace '_' with ' '
                        friendly = name
                        if friendly.startswith('open_'):
                            friendly = friendly[5:]
                        elif friendly.startswith('open'):
                            friendly = friendly[4:]
                        friendly = friendly.replace('_', ' ').strip().lower()
                        if hasattr(self.forzeos, name):
                            try:
                                self._host_open_map[friendly] = getattr(self.forzeos, name)
                            except Exception:
                                pass
            except Exception:
                pass
        except Exception:
            self._host_open_map = {}

        # Expand companion command_map with discovered host methods and useful aliases.
        # This keeps the companion's commands in sync with ForzeOS without manual edits.
        try:
            # For each discovered host open_* method, add 'open <name>' and short name aliases
            for friendly, func in list(self._host_open_map.items()):
                if not friendly:
                    continue
                key_open = f"open {friendly}"
                key_simple = friendly
                # prefer not to overwrite existing explicit mappings
                if key_open not in self.command_map:
                    # store the raw host callable; caller will use forzeos._call_cmd_safe
                    self.command_map[key_open] = (func, f"Açıyorum: {friendly}")
                if key_simple not in self.command_map:
                    self.command_map[key_simple] = (func, f"Açıyorum: {friendly}")

            # Add commonly useful control aliases if the host exposes them
            def _bind_cmd(name, func, reply=None):
                if not func:
                    return
                if name not in self.command_map:
                    self.command_map[name] = (func, reply or f"Komut: {name}")

            # Music controls
            try:
                _bind_cmd('play music', getattr(self.forzeos, 'music_play', None), 'Müziği oynatıyorum')
                _bind_cmd('pause music', getattr(self.forzeos, 'music_pause', None), 'Müziği duraklatıyorum')
                _bind_cmd('stop music', getattr(self.forzeos, 'music_stop', None), 'Müziği durduruyorum')
                _bind_cmd('export track', getattr(self.forzeos, 'export_wav', None) if hasattr(self.forzeos, 'export_wav') else None, 'Dışa aktarıyorum')
            except Exception:
                pass

            # File / system helpers
            try:
                _bind_cmd('open file manager', getattr(self.forzeos, 'open_file_manager', None), 'Dosya yöneticisini açıyorum')
                _bind_cmd('open terminal', getattr(self.forzeos, 'open_terminal', None), 'Terminal açılıyor')
                _bind_cmd('open notepad', getattr(self.forzeos, 'open_notepad', None), 'Notepad açılıyor')
                _bind_cmd('screenshot', getattr(self.forzeos, 'take_screenshot', None), 'Ekran görüntüsü alınıyor')
            except Exception:
                pass

            # Settings and helpers
            try:
                _bind_cmd('open settings', getattr(self.forzeos, 'open_desktop_settings', None) or getattr(self.forzeos, 'open_companion_settings', None), 'Ayarlar açılıyor')
            except Exception:
                pass

            # Improve help reply to include discovered commands
            try:
                discovered = sorted([k for k in self.command_map.keys() if isinstance(k, str)])
                short_list = ', '.join(discovered[:18]) + (', ...' if len(discovered) > 18 else '')
                help_text = "Kullanılabilir komut örnekleri: " + short_list
                # Replace generic 'help' mapping reply if present
                if 'help' in self.command_map:
                    cmd, _ = self.command_map['help']
                    self.command_map['help'] = (cmd, help_text)
                else:
                    self.command_map['help'] = (None, help_text)
            except Exception:
                pass
        except Exception:
            # non-fatal: companion will still work with manual mappings defined earlier
            pass

        # Load sprites now (non-blocking)
        self._load_sprites()

        # Idle reply scheduling handle (will call assistant.random_idle_reply occasionally)
        self._idle_job_id = None
        try:
            if getattr(self, 'ai', None) and getattr(self, 'ai_enabled', True):
                # schedule first idle
                self._schedule_next_idle()
        except Exception:
            pass

    # -------------------- Sprites --------------------
    def _list_asset_files(self, prefix):
        files = []
        if not os.path.isdir(self.ASSET_DIR):
            return files
        for f in os.listdir(self.ASSET_DIR):
            if f.lower().startswith(prefix) and f.lower().endswith('.png'):
                files.append(os.path.join(self.ASSET_DIR, f))
        # sort by filename to ensure order
        files.sort()
        return files


    def _load_image(self, path):
        try:
            img = Image.open(path).convert('RGBA')
            img = img.resize((self.size, self.size), Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception:
            return None

    def _load_sprites(self):
        # idle
        idle_files = self._list_asset_files('companion_idle_')
        for p in idle_files:
            im = self._load_image(p)
            if im:
                self.idle_imgs.append(im)
        # talk
        talk_files = self._list_asset_files('companion_talk_')
        for p in talk_files:
            im = self._load_image(p)
            if im:
                self.talk_imgs.append(im)
        # tap
        tap_files = self._list_asset_files('companion_tap_')
        for p in tap_files:
            im = self._load_image(p)
            if im:
                self.tap_imgs.append(im)
        # wave
        wave_files = self._list_asset_files('companion_wave_')
        for p in wave_files:
            im = self._load_image(p)
            if im:
                self.wave_imgs.append(im)

        # If some lists are empty, duplicate idle frames to avoid crashes
        if not self.idle_imgs:
            # create a simple placeholder from a blank Image
            blank = Image.new('RGBA', (self.size, self.size), (0, 0, 0, 0))
            self.idle_imgs = [ImageTk.PhotoImage(blank)]
        if not self.talk_imgs:
            self.talk_imgs = self.idle_imgs
        if not self.tap_imgs:
            self.tap_imgs = self.idle_imgs
        if not self.wave_imgs:
            self.wave_imgs = self.idle_imgs

    # -------------------- Wikipedia command --------------------
    def _cmd_wikipedia(self, text: str = None):
        """Handle Wikipedia commands via host assistant or fallback module.

        `text` may be the full user input or just the argument passed by the
        companion command dispatcher. Method returns a short string reply.
        """
        q = (text or '').strip()
        # If only keyword was provided, ask for topic (handled elsewhere too)
        if not q or q.lower() in ('wikipedia', 'wiki'):
            try:
                import forze_wikipedia
                return forze_wikipedia.handle_command('wikipedia')
            except Exception:
                return 'Wikipedia komutu: bir konu söyle (ör: wiki Türkiye)'

        candidate = q
        if not any(candidate.lower().startswith(p) for p in ('wiki ', 'wikipedia ', 'nedir ', 'kimdir ')):
            candidate = 'wiki ' + candidate

        # Prefer host assistant if available
        try:
            host_ai = getattr(self.forze, 'assistant', None) or getattr(self.forze, 'ai', None)
            if host_ai and hasattr(host_ai, 'execute_command'):
                res = host_ai.execute_command(candidate)
                if res:
                    return str(res)
        except Exception:
            pass

        # Fallback to local module
        try:
            import forze_wikipedia
            return forze_wikipedia.handle_command(candidate)
        except Exception:
            return 'Wikipedia araması yapılamıyor.'

    # -------------------- Install / Window --------------------
    def install(self, x=100, y=100):
        """Create the companion window and begin animation."""
        if self.win and tk.Toplevel.winfo_exists(self.win):
            # already installed
            return

        # Create a top-level window without decorations so it looks like a sprite
        self.win = Toplevel(self.root)
        self.win.overrideredirect(True)
        # Keep above the main window but not always on top of everything
        try:
            self.win.attributes('-topmost', True)
        except Exception:
            pass

        # Attempt to apply a transparent background for the toplevel so PNG alpha shows through.
        # On Windows, Tk supports a single-color transparency via '-transparentcolor'. We'll choose
        # a magic color that we'll use as the Label background for areas that should be transparent.
        transparent_color = '#123456'
        try:
            # Set the transparent color on the window (Windows-only; other platforms will ignore)
            self.win.attributes('-transparentcolor', transparent_color)
        except Exception:
            # Not supported on some platforms; fall back to matching desktop bg by using no border
            transparent_color = None

        self.win.geometry(f"+{x}+{y}")

        # store initial position in host config so settings toggle can restore
        try:
            if hasattr(self.forzeos, 'config'):
                self.forzeos.config.setdefault('desktop', {})['companion_position'] = {'x': int(x), 'y': int(y)}
                try:
                    if hasattr(self.forzeos, 'save_config'):
                        self.forzeos.save_config()
                except Exception:
                    pass
        except Exception:
            pass

        frame = Frame(self.win, bg=(transparent_color or 'white'))
        frame.pack()

        # label to hold image — set bg to transparent_color when available so PNG alpha blends
        self.canvas_label = Label(frame, bd=0, bg=(transparent_color or 'white'))
        self.canvas_label.pack()
        # bindings
        # Left-click opens chat (dragging disabled)
        self.canvas_label.bind('<Button-1>', self._on_click)
        self.canvas_label.bind('<ButtonRelease-1>', self._on_release)
        # Right-click toggles move or waves depending on setting
        self.canvas_label.bind('<Button-3>', self._on_right_click)

        # start anim thread, but only show static idle image by default
        self._stop_anim = False
        self._anim_thread = threading.Thread(target=self._anim_loop, daemon=True)
        self._anim_thread.start()

        # display first idle frame immediately
        try:
            if self.idle_imgs:
                img = self.idle_imgs[0]
                self.canvas_label.config(image=img)
        except Exception:
            pass

        # If host config says companion was hidden, hide immediately after install
        try:
            if hasattr(self.forzeos, 'config'):
                hidden = bool(self.forzeos.config.get('desktop', {}).get('companion_hidden', False))
                if hidden:
                    try:
                        self.win.withdraw()
                    except Exception:
                        pass
        except Exception:
            pass

    def uninstall(self):
        self._stop_anim = True
        try:
            if getattr(self, '_idle_job_id', None):
                try:
                    self.root.after_cancel(self._idle_job_id)
                except Exception:
                    pass
                self._idle_job_id = None
        except Exception:
            pass
        if self.win:
            try:
                self.win.destroy()
            except Exception:
                pass
            self.win = None

    def hide_companion(self):
        """Hide the companion window (withdraw)."""
        try:
            if self.win and tk.Toplevel.winfo_exists(self.win):
                try:
                    self.win.withdraw()
                except Exception:
                    pass
                # persist flag
                try:
                    if hasattr(self.forzeos, 'config'):
                        self.forzeos.config.setdefault('desktop', {})['companion_hidden'] = True
                        if hasattr(self.forzeos, 'save_config'):
                            try:
                                self.forzeos.save_config()
                            except Exception:
                                pass
                except Exception:
                    pass
        except Exception:
            pass

    def restore_companion(self):
        """Restore the companion window (deiconify)."""
        try:
            if self.win:
                try:
                    self.win.deiconify()
                    try:
                        self.win.lift()
                    except Exception:
                        pass
                except Exception:
                    pass
                # persist flag
                try:
                    if hasattr(self.forzeos, 'config'):
                        self.forzeos.config.setdefault('desktop', {})['companion_hidden'] = False
                        if hasattr(self.forzeos, 'save_config'):
                            try:
                                self.forzeos.save_config()
                            except Exception:
                                pass
                except Exception:
                    pass
        except Exception:
            pass

    # -------------------- Drag handlers --------------------
    def _on_click(self, event):
        # open chat when quickly clicked (if not dragging)
        # small delay to detect click
        self._click_time = time.time()
        # react to touch with a short, humorous annoyed reply
        try:
            # don't spam on repeated clicks; allow immediate short reply
            annoyed = "Hey! Çok nazikçe dokun, ben de hassas bir botum — rahatsız oldum ama seni affediyorum."
            self._speak_and_reply(annoyed)
            # small tap animation
            self._set_anim_state('tap', duration=0.9)
        except Exception:
            pass

    def _on_drag_motion(self, event):
        # dragging is disabled; leave handler as no-op for compatibility
        return

    def _on_release(self, event):
        # if click was short and there was minimal movement, treat as click (open chat)
        click_duration = time.time() - getattr(self, '_click_time', 0)
        if click_duration < 0.3:
            # open chat
            self.open_chat()
        # notify host that the position may have changed so it can persist
        try:
            if hasattr(self, '_on_position_changed') and callable(self._on_position_changed):
                try:
                    # schedule on main thread
                    self.forzeos.root.after(10, self._on_position_changed)
                except Exception:
                    try:
                        self._on_position_changed()
                    except Exception:
                        pass
        except Exception:
            pass

        # Also persist position directly into host config if available (defensive)
        try:
            if hasattr(self, 'win') and getattr(self, 'win') is not None and hasattr(self.forzeos, 'config'):
                try:
                    wx = self.win.winfo_x()
                    wy = self.win.winfo_y()
                    self.forzeos.config.setdefault('desktop', {})['companion_position'] = {'x': int(wx), 'y': int(wy)}
                    try:
                        if hasattr(self.forzeos, 'save_config'):
                            self.forzeos.save_config()
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception:
            pass

    def _on_right_click(self, event):
        # Right-click behavior: either move the mascot (if allowed) or play a wave
        try:
            allow = bool(getattr(self, 'allow_move_on_rightclick', True))
        except Exception:
            allow = True

        if allow:
            # Move mascot to bottom-right above host taskbar
            try:
                tb_size = self.forzeos.config.get('settings', {}).get('taskbar_size', 'medium') if hasattr(self, 'forzeos') else 'medium'
                size_map = {'small': 30, 'medium': 50, 'large': 70}
                tb_dim = size_map.get(tb_size, 50)
            except Exception:
                tb_dim = 50

            try:
                screen_w = self.forzeos.root.winfo_screenwidth()
                screen_h = self.forzeos.root.winfo_screenheight()
            except Exception:
                screen_w = self.root.winfo_screenwidth()
                screen_h = self.root.winfo_screenheight()

            try:
                comp_w = self.size
                comp_h = self.size
            except Exception:
                comp_w = comp_h = 128

            new_x = max(10, screen_w - comp_w - 20)
            new_y = max(10, screen_h - tb_dim - comp_h - 10)
            try:
                self.win.geometry(f"+{new_x}+{new_y}")
            except Exception:
                pass

            # persist position via host callback if available
            try:
                if hasattr(self, '_on_position_changed') and callable(self._on_position_changed):
                    try:
                        self.forzeos.root.after(10, self._on_position_changed)
                    except Exception:
                        self._on_position_changed()
            except Exception:
                pass

            # feedback animation
            self._set_anim_state('wave', duration=1.0)
        else:
            self._set_anim_state('wave', duration=0.8)

    # -------------------- Wrapper command methods --------------------
    def open_social_media(self):
        """Wrapper that calls host's social media / browser open routine."""
        try:
            if hasattr(self.forzeos, 'open_social_media'):
                # hide companion if configured
                try:
                    if self.hide_on_open and hasattr(self, 'win') and self.win:
                        try:
                            self.win.withdraw()
                        except Exception:
                            pass
                except Exception:
                    pass
                self.forzeos.open_social_media()
            elif hasattr(self.forzeos, '_call_cmd_safe'):
                # only call host methods (not arbitrary strings)
                self.forzeos._call_cmd_safe(self.forzeos.open_social_media)
        except Exception:
            pass

    def open_music_studio(self):
        try:
            if hasattr(self.forzeos, 'open_music_studio'):
                if self.hide_on_open and hasattr(self, 'win') and self.win:
                    try:
                        self.win.withdraw()
                    except Exception:
                        pass
                self.forzeos.open_music_studio()
            elif hasattr(self.forzeos, '_call_cmd_safe'):
                self.forzeos._call_cmd_safe(self.forzeos.open_music_studio)
        except Exception:
            pass

    def open_video_editor(self):
        try:
            if hasattr(self.forzeos, 'open_video_editor'):
                if self.hide_on_open and hasattr(self, 'win') and self.win:
                    try:
                        self.win.withdraw()
                    except Exception:
                        pass
                self.forzeos.open_video_editor()
            elif hasattr(self.forzeos, '_call_cmd_safe'):
                self.forzeos._call_cmd_safe(self.forzeos.open_video_editor)
        except Exception:
            pass

    def open_gallery(self):
        try:
            if hasattr(self.forzeos, 'open_gallery'):
                if self.hide_on_open and hasattr(self, 'win') and self.win:
                    try:
                        self.win.withdraw()
                    except Exception:
                        pass
                self.forzeos.open_gallery()
            elif hasattr(self.forzeos, '_call_cmd_safe'):
                self.forzeos._call_cmd_safe(self.forzeos.open_gallery)
        except Exception:
            pass

    def open_pdf_reader(self):
        try:
            if hasattr(self.forzeos, 'open_pdf_reader'):
                if self.hide_on_open and hasattr(self, 'win') and self.win:
                    try:
                        self.win.withdraw()
                    except Exception:
                        pass
                self.forzeos.open_pdf_reader()
            elif hasattr(self.forzeos, '_call_cmd_safe'):
                self.forzeos._call_cmd_safe(self.forzeos.open_pdf_reader)
        except Exception:
            pass

    def open_log_file(self, path: str = None):
        """Open host's log file via ForzeOS helper."""
        try:
            # Prefer host helper that can accept an optional filepath
            if hasattr(self.forzeos, '_call_cmd_with_optional_filepath'):
                try:
                    ok = self.forzeos._call_cmd_with_optional_filepath(self.forzeos.open_log_file, path)
                    if ok:
                        try:
                            if self.hide_on_open and getattr(self, 'win', None):
                                try:
                                    self.win.withdraw()
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        return True
                except Exception:
                    logger.exception('Companion: _call_cmd_with_optional_filepath failed for open_log_file')

            # Fallback to the generic safe caller
            if hasattr(self.forzeos, '_call_cmd_safe'):
                try:
                    if path:
                        self.forzeos._call_cmd_safe(self.forzeos.open_log_file, path)
                    else:
                        self.forzeos._call_cmd_safe(self.forzeos.open_log_file)
                    try:
                        if self.hide_on_open and getattr(self, 'win', None):
                            try:
                                self.win.withdraw()
                            except Exception:
                                pass
                    except Exception:
                        pass
                    return True
                except Exception:
                    logger.exception('Companion: _call_cmd_safe failed for open_log_file')

            # Last resort: direct call
            if hasattr(self.forzeos, 'open_log_file'):
                try:
                    if path:
                        self.forzeos.open_log_file(path)
                    else:
                        self.forzeos.open_log_file()
                    try:
                        if self.hide_on_open and getattr(self, 'win', None):
                            try:
                                self.win.withdraw()
                            except Exception:
                                pass
                    except Exception:
                        pass
                    return True
                except Exception as e:
                    logger.exception('Companion: direct open_log_file call failed')
                    try:
                        self._speak_and_reply(f'Log açılamadı: {e}')
                    except Exception:
                        pass
            else:
                try:
                    self._speak_and_reply('Host üzerinde log açma fonksiyonu bulunamadı.')
                except Exception:
                    pass
        except Exception:
            logger.exception('Companion: open_log_file encountered an unexpected error')
        return False

    def open_audio_settings(self):
        """Open host's audio settings window."""
        try:
            if hasattr(self.forzeos, 'open_audio_settings'):
                try:
                    if hasattr(self.forzeos, '_call_cmd_safe'):
                        self.forzeos._call_cmd_safe(self.forzeos.open_audio_settings)
                    else:
                        self.forzeos.open_audio_settings()
                except Exception:
                    try:
                        self.forzeos.open_audio_settings()
                    except Exception:
                        pass
        except Exception:
            pass

    # -------------------- Advanced command wrappers --------------------
    def delete_app(self, name: str):
        try:
            if not name:
                self._speak_and_reply('Silinecek uygulama adı verilmedi.')
                return
            # attempt host method first
            try:
                if hasattr(self.forzeos, 'delete_app'):
                    self.forzeos.delete_app(name)
                else:
                    # try to remove desktop icon if such helper exists
                    try:
                        self.forzeos.remove_desktop_icon(name)
                    except Exception:
                        pass
                self._speak_and_reply(f'Uygulama silindi: {name}')
            except Exception as e:
                self._speak_and_reply(f'App silme hatası: {e}')
        except Exception:
            pass

    def open_path(self, path: str = None):
        try:
            if not path:
                # open generic file manager
                if hasattr(self.forzeos, 'open_file_manager'):
                    self.forzeos.open_file_manager()
                return
            # sanitize path
            p = path.strip().strip('"')
            try:
                if hasattr(self.forzeos, 'open_file_manager'):
                    self.forzeos.open_file_manager(p)
                else:
                    # fallback: try to open path via host safe caller
                    self.forzeos._call_cmd_safe(lambda: None)
            except Exception:
                try:
                    # platform open
                    if os.path.exists(p):
                        os.startfile(p)
                except Exception:
                    pass
        except Exception:
            pass

    def take_screenshot(self):
        try:
            # prefer host implementation
            if hasattr(self.forzeos, 'take_screenshot'):
                self.forzeos.take_screenshot()
                self._speak_and_reply('Ekran görüntüsü alındı.')
                return
            # fallback using PIL.ImageGrab if available
            try:
                from PIL import ImageGrab
                img = ImageGrab.grab()
                # save to user's file_system_root if available
                base = getattr(self.forzeos, 'file_system_root', os.getcwd())
                os.makedirs(base, exist_ok=True)
                fname = os.path.join(base, f'screenshot_{int(time.time())}.png')
                img.save(fname)
                self._speak_and_reply(f'Ekran görüntüsü kaydedildi: {fname}')
            except Exception as e:
                self._speak_and_reply(f'Ekran görüntüsü alınamadı: {e}')
        except Exception:
            pass

    def change_wallpaper(self):
        try:
            if hasattr(self.forzeos, 'open_wallpaper_settings'):
                self.forzeos.open_wallpaper_settings()
            else:
                self._speak_and_reply('Duvar kağıdı ayarları açılamıyor.')
        except Exception:
            pass

    def system_info(self):
        try:
            # gather CPU, RAM, disk using psutil if available
            try:
                import psutil
                cpu = psutil.cpu_percent(interval=0.5)
                mem = psutil.virtual_memory()
                disk = psutil.disk_usage('/')
                txt = f'CPU: {cpu}% | RAM: {int(mem.percent)}% ({int(mem.used/1024**2)}MB/{int(mem.total/1024**2)}MB) | Disk: {int(disk.percent)}% ({int(disk.used/1024**3)}GB/{int(disk.total/1024**3)}GB)'
            except Exception:
                txt = 'psutil bulunamadı; sistem bilgisi alınamıyor.'
            # display as command output (green)
            try:
                self.root.after(0, lambda: self._add_history('Companion', (txt, 'cmd')))
            except Exception:
                self._add_history('Companion', (txt, 'cmd'))
        except Exception:
            pass

    # small helpers that call assistant for specific commands
    def ai_joke(self):
        try:
            if getattr(self, 'ai', None):
                resp = self.ai.reply('tell me a joke', session_id=str(id(self.forzeos)))
                self._add_history('Companion', (resp, 'cmd'))
        except Exception:
            pass

    def ai_teach(self):
        try:
            if getattr(self, 'ai', None):
                resp = self.ai.reply('teach', session_id=str(id(self.forzeos)))
                self._add_history('Companion', (resp, 'cmd'))
        except Exception:
            pass

    def ai_motivate(self):
        try:
            if getattr(self, 'ai', None):
                resp = self.ai.reply('motivate', session_id=str(id(self.forzeos)))
                self._add_history('Companion', (resp, 'cmd'))
        except Exception:
            pass

    def ai_weather(self, location: str = None):
        """Return a short weather summary.

        Resolution strategy (conservative / offline-first):
        1. If host provides `get_weather`, call it (may return str or dict).
        2. If host config contains cached weather under `config['weather']`, use that.
        3. If `requests` is available, query wttr.in as a lightweight web fallback.
        4. Otherwise return a polite fallback message explaining lack of data.

        The function posts the result into the companion chat and returns the text.
        """
        try:
            # 1) Host-provided helper
            try:
                if hasattr(self.forzeos, 'get_weather') and callable(getattr(self.forzeos, 'get_weather')):
                    try:
                        data = self.forzeos.get_weather(location) if location else self.forzeos.get_weather()
                        if isinstance(data, str):
                            resp = data
                        elif isinstance(data, dict):
                            parts = []
                            t = data.get('temperature') or data.get('temp') or data.get('temp_c')
                            if t is not None:
                                parts.append(f"Sıcaklık: {t}")
                            desc = data.get('description') or data.get('weather') or data.get('condition')
                            if desc:
                                parts.append(str(desc))
                            hum = data.get('humidity')
                            if hum is not None:
                                parts.append(f"Nem: {hum}%")
                            wind = data.get('wind')
                            if wind:
                                parts.append(f"Rüzgar: {wind}")
                            resp = ' | '.join(parts) if parts else str(data)
                        else:
                            resp = str(data)
                        self._add_history('Companion', (resp, 'cmd'))
                        return resp
                    except Exception:
                        # fall through to other methods
                        pass
            except Exception:
                pass

            # 2) Cached config
            try:
                cfg = getattr(self.forzeos, 'config', {}) or {}
                wcache = cfg.get('weather') if isinstance(cfg, dict) else None
                if wcache:
                    # If location specified, try to find match in cached dict
                    if isinstance(wcache, dict):
                        if location:
                            found = wcache.get(location) or wcache.get(location.lower())
                            if found:
                                resp = str(found)
                                self._add_history('Companion', (resp, 'cmd'))
                                return resp
                        # otherwise, create a short summary from the cached dict
                        try:
                            temp = wcache.get('temperature') or wcache.get('temp')
                            desc = wcache.get('description') or wcache.get('condition')
                            resp = ', '.join([s for s in (str(temp) if temp is not None else None, desc) if s])
                            if resp:
                                self._add_history('Companion', (resp, 'cmd'))
                                return resp
                        except Exception:
                            pass
                    else:
                        # cached blob is a string
                        resp = str(wcache)
                        self._add_history('Companion', (resp, 'cmd'))
                        return resp
            except Exception:
                pass

            # 3) Lightweight web fallback using wttr.in if requests available
            try:
                import requests
                q = (location or '').strip() or ''
                url = f'https://wttr.in/{q}?format=3'
                try:
                    r = requests.get(url, timeout=4)
                    if r.ok:
                        resp = r.text.strip()
                        self._add_history('Companion', (resp, 'cmd'))
                        return resp
                except Exception:
                    pass
            except Exception:
                # requests not available or import failed
                pass

            # 4) Final fallback
            resp = 'Hava bilgisi alınamıyor — host desteklemiyor veya internet yok.'
            self._add_history('Companion', (resp, 'cmd'))
            return resp
        except Exception as e:
            try:
                resp = f'Hava alınırken hata: {e}'
                self._add_history('Companion', (resp, 'cmd'))
                return resp
            except Exception:
                return None

    # -------------------- Shortcuts and Settings UI --------------------
    def open_shortcuts_manager(self):
        """Open a small UI to view/add keyboard shortcuts saved into forzeos.config['shortcuts']."""
        try:
            cfg = getattr(self.forzeos, 'config', {})
            shortcuts = cfg.get('shortcuts', {}) if isinstance(cfg, dict) else {}
        except Exception:
            shortcuts = {}

        win = Toplevel(self.root)
        win.title('Companion - Shortcuts')
        win.geometry('360x220')

        list_frame = Frame(win)
        list_frame.pack(fill='both', expand=True, padx=6, pady=6)

        lbl = Label(list_frame, text='Kayıtlı kısayollar:')
        lbl.pack(anchor='w')

        txt = Text(list_frame, height=6)
        txt.pack(fill='both', expand=True)
        txt.config(state='normal')
        if shortcuts:
            for k, v in shortcuts.items():
                txt.insert('end', f"{k} => {v}\n")
        else:
            txt.insert('end', 'Henüz kısayol yok. Yeni ekleyin.')
        txt.config(state='disabled')

        # Add new shortcut section
        add_frame = Frame(win)
        add_frame.pack(fill='x', padx=6, pady=6)

        app_lbl = Label(add_frame, text='Uygulama anahtarı:')
        app_lbl.grid(row=0, column=0, sticky='w')

        # build a simple list of available app names from host if possible
        apps = []
        try:
            fa = getattr(self.forzeos, 'FILE_ASSOCIATIONS', {})
            apps = sorted({v[0] for v in fa.values()})
        except Exception:
            apps = ['Notepad', 'PDF Reader', 'Gallery', 'Music Player', 'Video Player', 'Code Editor']

        from tkinter import ttk as _ttk
        app_var = tk.StringVar(value=apps[0] if apps else '')
        app_menu = _ttk.Combobox(add_frame, textvariable=app_var, values=apps, state='readonly')
        app_menu.grid(row=0, column=1, sticky='ew', padx=4)

        key_lbl = Label(add_frame, text='Tuș:')
        key_lbl.grid(row=1, column=0, sticky='w')
        key_entry = Entry(add_frame)
        key_entry.grid(row=1, column=1, sticky='ew', padx=4)
        key_entry.insert(0, 'Press a key...')

        # capture single key press into entry
        def on_key(ev):
            try:
                key_entry.delete(0, 'end')
                key_entry.insert(0, ev.keysym)
            except Exception:
                pass

        key_entry.bind('<Key>', on_key)

        def add_shortcut():
            key = key_entry.get().strip()
            appname = app_var.get().strip()
            if not key or not appname or key == 'Press a key...':
                self._speak_and_reply('Lütfen geçerli bir tuş ve uygulama seç.')
                return
            try:
                if not hasattr(self.forzeos, 'config'):
                    self.forzeos.config = {}
                self.forzeos.config.setdefault('shortcuts', {})[key] = appname
                try:
                    if hasattr(self.forzeos, 'save_config'):
                        self.forzeos.save_config()
                except Exception:
                    pass
                self._speak_and_reply(f'Kısayol eklendi: {key} => {appname}')
                win.destroy()
            except Exception as e:
                self._speak_and_reply(f'Hata: {e}')

        add_btn = Button(add_frame, text='Ekle', command=add_shortcut)
        add_btn.grid(row=2, column=0, columnspan=2, pady=6)

        # keep grid columns flexible
        add_frame.columnconfigure(1, weight=1)

    def open_companion_settings(self):
        """Open companion-specific settings (toggle AI, allow move)."""
        win = Toplevel(self.root)
        win.title('Companion Settings')
        win.geometry('300x140')

        frame = Frame(win)
        frame.pack(fill='both', expand=True, padx=8, pady=8)

        ai_var = tk.BooleanVar(value=bool(getattr(self, 'ai_enabled', True)))
        move_var = tk.BooleanVar(value=bool(getattr(self, 'allow_move_on_rightclick', True)))

        def on_toggle_ai():
            self.ai_enabled = bool(ai_var.get())
            try:
                if not hasattr(self.forzeos, 'config'):
                    self.forzeos.config = {}
                self.forzeos.config.setdefault('desktop', {})['companion_ai_enabled'] = bool(self.ai_enabled)
                if hasattr(self.forzeos, 'save_config'):
                    self.forzeos.save_config()
            except Exception:
                pass
            self._speak_and_reply('AI modu ' + ('etkinleştirildi' if self.ai_enabled else 'devre dışı bırakıldı'))

        def on_toggle_move():
            self.allow_move_on_rightclick = bool(move_var.get())
            try:
                if not hasattr(self.forzeos, 'config'):
                    self.forzeos.config = {}
                self.forzeos.config.setdefault('desktop', {})['companion_allow_move'] = bool(self.allow_move_on_rightclick)
                if hasattr(self.forzeos, 'save_config'):
                    self.forzeos.save_config()
            except Exception:
                pass
            self._speak_and_reply('Sağ tık hareketi ' + ('etkin' if self.allow_move_on_rightclick else 'devre dışı'))

        ai_cb = tk.Checkbutton(frame, text='AI Modu (kural tabanlı yanıt + asistan)', variable=ai_var, command=on_toggle_ai)
        ai_cb.pack(anchor='w', pady=6)

        mv_cb = tk.Checkbutton(frame, text='Sağ tıkla taşıma izni', variable=move_var, command=on_toggle_move)
        mv_cb.pack(anchor='w', pady=6)

        # Show-only-on-desktop toggle (hide when apps open)
        show_desktop_var = tk.BooleanVar(value=bool(getattr(self, 'hide_on_open', False)))

        def on_toggle_show_desktop():
            try:
                self.hide_on_open = bool(show_desktop_var.get())
                if not hasattr(self.forzeos, 'config'):
                    self.forzeos.config = {}
                self.forzeos.config.setdefault('desktop', {})['companion_hide_on_open'] = bool(self.hide_on_open)
                # Keep companion_hidden in sync: if hide_on_open is True we don't auto-hide now
                # but the explicit hide_companion()/restore_companion() will toggle companion_hidden.
                try:
                    if hasattr(self.forzeos, 'save_config'):
                        self.forzeos.save_config()
                except Exception:
                    pass
                self._speak_and_reply('Sadece masaüstünde göster ' + ('etkin' if self.hide_on_open else 'devre dışı'))
            except Exception:
                pass

        sd_cb = tk.Checkbutton(frame, text='Sadece masaüstünde göster (uygulama açıldığında gizle)', variable=show_desktop_var, command=on_toggle_show_desktop)
        sd_cb.pack(anchor='w', pady=6)

        # Quick hide / restore buttons
        btn_frame = Frame(frame)
        btn_frame.pack(fill='x', pady=6)
        hide_btn = Button(btn_frame, text='Hide Now', command=lambda: self.hide_companion())
        hide_btn.pack(side='left', padx=4)
        restore_btn = Button(btn_frame, text='Restore Companion', command=lambda: self.restore_companion())
        restore_btn.pack(side='left', padx=4)

        help_lbl = Label(frame, text='Not: Mouse ayarları sistem ayarlarından kaldırıldı; buradan companion ayarlarını düzenleyebilirsin.')
        help_lbl.pack(anchor='w', pady=6)

    def open_function_art(self):
        """Open Function ART window (safe, non-blocking)."""
        try:
            if not FUNCTION_ART_AVAILABLE:
                # try late import using importlib to avoid static import statements
                try:
                    import importlib
                    mod = importlib.import_module('function_art')
                    fa_cls = getattr(mod, 'FunctionArtWindow', None)
                    if fa_cls is None:
                        raise ImportError('FunctionArtWindow not found in function_art')
                except Exception as e:
                    self._speak_and_reply('Function ART modülü bulunamadı: {}'.format(e))
                    return
            else:
                fa_cls = FunctionArtWindow
            # create window on main thread
            def _open(initial_expr=None):
                try:
                    wond = fa_cls(self.root, host=getattr(self, 'forzeos', None), notify=lambda m: self._speak_and_reply(m), initial_expr=initial_expr)
                except Exception as e:
                    self._speak_and_reply('Function ART açılamadı: {}'.format(e))
            try:
                self.root.after(0, lambda: _open(None))
            except Exception:
                _open(None)
        except Exception:
            pass

    def open_function_art_with_expr(self, expr: str):
        """Open Function ART and prefill the expression safely."""
        try:
            # ensure module/class available
            if not FUNCTION_ART_AVAILABLE:
                try:
                    import importlib
                    mod = importlib.import_module('function_art')
                    fa_cls = getattr(mod, 'FunctionArtWindow', None)
                except Exception as e:
                    self._speak_and_reply('Function ART modülü bulunamadı: {}'.format(e))
                    return
            else:
                fa_cls = FunctionArtWindow

            def _open():
                try:
                    fa_cls(self.root, host=getattr(self, 'forzeos', None), notify=lambda m: self._speak_and_reply(m), initial_expr=expr)
                except Exception as e:
                    self._speak_and_reply('Function ART açılamadı: {}'.format(e))

            try:
                self.root.after(0, _open)
            except Exception:
                _open()
        except Exception:
            pass

    # -------------------- Idle scheduling --------------------
    def _schedule_next_idle(self):
        try:
            # schedule between 2 and 5 minutes (milliseconds)
            delay = random.randint(120, 300) * 1000
            if getattr(self, '_idle_job_id', None):
                try:
                    self.root.after_cancel(self._idle_job_id)
                except Exception:
                    pass
            self._idle_job_id = self.root.after(delay, self._do_idle_reply)
        except Exception:
            pass

    def _do_idle_reply(self):
        try:
            if getattr(self, 'ai', None) is None:
                self._schedule_next_idle()
                return
            try:
                # ensure assistant personality is synced from host config if available
                try:
                    ast_cfg = self.forzeos.config.get('settings', {}).get('assistant', {}) if hasattr(self.forzeos, 'config') else {}
                    pers = ast_cfg.get('personality') or ast_cfg.get('mode') or ast_cfg.get('style')
                    if pers:
                        try:
                            self.ai.personality = pers.lower()
                        except Exception:
                            pass
                except Exception:
                    pass
                txt = self.ai.random_idle_reply()
            except Exception:
                txt = None
            if not txt:
                self._schedule_next_idle()
                return
            # show in chat (open if needed) and animate
            try:
                self.open_chat()
                self._set_anim_state('talk', duration=2.0)
                # add with slight delay to simulate thinking
                def _show():
                    try:
                        self._add_history('Companion', txt)
                        # optional TTS
                        try:
                            cfg = getattr(self.forzeos, 'config', {})
                            if cfg.get('settings', {}).get('assistant', {}).get('tts_enabled') and getattr(self, '_tts_available', False):
                                self.speak(txt)
                        except Exception:
                            pass
                    except Exception:
                        pass
                self.root.after(600, _show)
            except Exception:
                pass
            finally:
                self._schedule_next_idle()
        except Exception:
            try:
                self._schedule_next_idle()
            except Exception:
                pass

    # -------------------- Animation --------------------
    def _set_anim_state(self, state, duration=None):
        self._anim_state = state
        self._frame_index = 0
        if duration:
            # schedule return to idle
            def _to_idle_after():
                time.sleep(duration)
                # only revert if not overridden by a new state
                if self._anim_state == state:
                    self._anim_state = 'idle'
            threading.Thread(target=_to_idle_after, daemon=True).start()

    def _anim_loop(self):
        while not self._stop_anim:
            try:
                # Only animate when state != 'idle'. Idle remains static to avoid constant movement.
                if self._anim_state == 'idle':
                    time.sleep(0.5)
                    continue

                if self._anim_state == 'talk':
                    imgs = self.talk_imgs
                elif self._anim_state == 'tap':
                    imgs = self.tap_imgs
                elif self._anim_state == 'wave':
                    imgs = self.wave_imgs
                else:
                    imgs = self.idle_imgs

                if not imgs:
                    time.sleep(0.1)
                    self._anim_state = 'idle'
                    continue

                # play through frames once then return to idle
                for i in range(len(imgs)):
                    if self._anim_state == 'idle' or self._stop_anim:
                        break
                    frame = imgs[i]
                    try:
                        self.root.after(0, lambda f=frame: self.canvas_label.config(image=f))
                    except Exception:
                        pass
                    time.sleep(max(0.05, 1.0 / (self.fps * 1.5)))

                # after finishing, return to idle image
                try:
                    if self.idle_imgs:
                        idle_img = self.idle_imgs[0]
                        self.root.after(0, lambda f=idle_img: self.canvas_label.config(image=f))
                except Exception:
                    pass
                self._anim_state = 'idle'
            except Exception:
                time.sleep(0.2)

    # -------------------- Chat UI --------------------
    def open_chat(self):
        # If chat already open, bring to front
        if self.chat_win and tk.Toplevel.winfo_exists(self.chat_win):
            try:
                self.chat_win.lift()
            except Exception:
                pass
            return

        # create a styled chat balloon anchored to the left of the companion
        self.chat_win = Toplevel(self.root)
        self.chat_win.title("Forze — Companion")
        try:
            self.chat_win.transient(self.root)
        except Exception:
            pass

        # default size and position (left of companion)
        try:
            cx = max(10, self.win.winfo_x() - 420)
            cy = max(10, self.win.winfo_y())
        except Exception:
            cx, cy = 50, 50
        self.chat_win.geometry(f"420x360+{cx}+{cy}")
        # allow resizing and dragging
        try:
            self.chat_win.resizable(True, True)
        except Exception:
            pass

        # main container with subtle shadow effect (approximation using a frame)
        container = Frame(self.chat_win, bg='#dddddd')
        container.pack(fill='both', expand=True, padx=6, pady=6)

        # history canvas so we can layout message 'bubbles' left/right
        self.history_canvas = tk.Canvas(container, bg='#f2f2f2', highlightthickness=0)
        self.history_scroll = Scrollbar(container, orient='vertical', command=self.history_canvas.yview)
        self.history_canvas.configure(yscrollcommand=self.history_scroll.set)
        self.history_scroll.pack(side='right', fill='y')
        self.history_canvas.pack(side='left', fill='both', expand=True)

        # a frame inside canvas to hold message widgets
        self.history_frame = Frame(self.history_canvas, bg='#f2f2f2')
        self.history_canvas.create_window((0, 0), window=self.history_frame, anchor='nw')
        self.history_frame.bind('<Configure>', lambda e: self.history_canvas.configure(scrollregion=self.history_canvas.bbox('all')))

        # Mouse wheel support: Windows/Mac (<MouseWheel>) and Linux (<Button-4/5>)
        def _on_mousewheel(event):
            try:
                if event.num == 4:
                    # Linux scroll up
                    self.history_canvas.yview_scroll(-1, 'units')
                elif event.num == 5:
                    # Linux scroll down
                    self.history_canvas.yview_scroll(1, 'units')
                else:
                    # Windows / Mac
                    delta = int(getattr(event, 'delta', 0))
                    # On Windows, event.delta is multiple of 120
                    if delta > 0:
                        self.history_canvas.yview_scroll(-1 * (abs(delta) // 120 or 1), 'units')
                    elif delta < 0:
                        self.history_canvas.yview_scroll(1 * (abs(delta) // 120 or 1), 'units')
            except Exception:
                pass

        # bind to canvas and to frame so focus/typing doesn't stop scrolling
        try:
            self.history_canvas.bind_all('<MouseWheel>', _on_mousewheel)
            self.history_canvas.bind_all('<Button-4>', _on_mousewheel)
            self.history_canvas.bind_all('<Button-5>', _on_mousewheel)
        except Exception:
            pass

        # ensure we unbind when chat is closed to avoid global bindings leaking
        def _on_close_chat():
            try:
                self.history_canvas.unbind_all('<MouseWheel>')
                self.history_canvas.unbind_all('<Button-4>')
                self.history_canvas.unbind_all('<Button-5>')
            except Exception:
                pass
            try:
                self.chat_win.destroy()
            except Exception:
                pass

        # override window close protocol
        try:
            self.chat_win.protocol('WM_DELETE_WINDOW', _on_close_chat)
        except Exception:
            pass

        # input area
        bottom = Frame(self.chat_win, bg='#eeeeee')
        bottom.pack(fill='x')
        self.input_entry = Entry(bottom)
        self.input_entry.pack(side='left', fill='x', expand=True, padx=8, pady=8)
        self.input_entry.bind('<Return>', self._on_user_enter)
        send_btn = Button(bottom, text='Gönder', command=lambda: self._on_user_enter(None))
        send_btn.pack(side='right', padx=6, pady=6)

        # greet
        self._add_history('Companion', "Merhaba! Ben ForzeOS'un şapkalı asistanıyım. Bana 'help' yaz.")

    def _add_history(self, who, text):
        # who: 'You' or 'Companion'/'Forze'
        try:
            # Support optional special rendering when text is a tuple (text, style)
            style = None
            if isinstance(text, tuple) and len(text) >= 1:
                try:
                    style = text[1]
                    text = text[0]
                except Exception:
                    text = text[0]
            if not getattr(self, 'history_frame', None):
                # fallback to simple text insert
                if not getattr(self, 'history_text', None):
                    return
                self.history_text.config(state='normal')
                self.history_text.insert('end', f"{who}: {text}\n")
                self.history_text.see('end')
                self.history_text.config(state='disabled')
                return

            # bubble container
            bubble = Frame(self.history_frame, bg='#f2f2f2')
            # avatar
            avatar_size = 28
            try:
                # use companion first frame as avatar if available
                avatar_img = None
                if self.idle_imgs:
                    avatar_img = self.idle_imgs[0]
            except Exception:
                avatar_img = None

            # message bubble
            is_user = who.lower() in ('you', 'user')
            if is_user:
                # user message on right
                av_lbl = Label(bubble, image=avatar_img, bg='#f2f2f2')
                txt_bg = '#cfe9ff'
                msg_lbl = Label(bubble, text=text, bg=txt_bg, anchor='e', justify='left', wraplength=420)
                av_lbl.pack(side='right', padx=(6,0))
                msg_lbl.pack(side='right', padx=(0,6), pady=6)
            else:
                # assistant message on left
                av_lbl = Label(bubble, image=avatar_img, bg='#f2f2f2')
                txt_bg = '#e9e9e9'
                # If caller passed style 'cmd' show green background
                try:
                    if style == 'cmd':
                        txt_bg = '#dff0d8'
                except Exception:
                    pass
                av_lbl.pack(side='left', padx=(6,0))
                msg_lbl = Label(bubble, text=text, bg=txt_bg, anchor='w', justify='left', wraplength=420)
                msg_lbl.pack(side='left', padx=(0,6), pady=6)

            bubble.pack(fill='x', pady=2, padx=6)
            # auto-scroll to bottom
            try:
                self.history_canvas.yview_moveto(1.0)
            except Exception:
                pass
        except Exception:
            # fallback to previous simple text history
            try:
                if getattr(self, 'history_text', None):
                    self.history_text.config(state='normal')
                    self.history_text.insert('end', f"{who}: {text}\n")
                    self.history_text.see('end')
                    self.history_text.config(state='disabled')
            except Exception:
                pass

    def _on_user_enter(self, event):
        if not self.input_entry:
            return
        txt = self.input_entry.get().strip()
        if not txt:
            return
        self.input_entry.delete(0, 'end')
        # show user message on the right
        self._add_history('You', txt)
        # process in background to avoid UI freeze
        threading.Thread(target=self._process_user_input, args=(txt,), daemon=True).start()

    # -------------------- Command processing --------------------
    def _process_user_input(self, txt):
        lc = txt.lower().strip()
        # If we are expecting a wikipedia topic from a previous 'wiki' prompt,
        # treat this input as the topic and perform the search.
        try:
            if getattr(self, '_expecting_wiki_topic', False):
                topic = txt.strip()
                self._expecting_wiki_topic = False
                if not topic:
                    self._speak_and_reply('Aranacak konu belirtilmedi.')
                    return
                candidate = 'wiki ' + topic
                # prefer host assistant
                try:
                    host_ai = getattr(self.forze, 'assistant', None) or getattr(self.forze, 'ai', None)
                    if host_ai and hasattr(host_ai, 'execute_command'):
                        res = host_ai.execute_command(candidate)
                        if res:
                            self._speak_and_reply(str(res))
                            return
                except Exception:
                    pass
                # fallback
                try:
                    import forze_wikipedia
                    res = forze_wikipedia.handle_command(candidate)
                    self._speak_and_reply(res)
                    return
                except Exception:
                    self._speak_and_reply('Wikipedia araması yapılamıyor.')
                    return
        except Exception:
            pass
        # Improved inline help: if user types help or yardım, show companion + host commands
        # Math detection: try to recognize casual-chat math while avoiding
        # unintended evaluations (e.g. "ben 44 yasindayim"). Replace common
        # Turkish operator words before detection and require an operator
        # or explicit trigger words.
        try:
            # normalize some Turkish operator words to symbols so users can type naturally
            t = txt
            t = re.sub(r'\bçarpı\b', '*', t, flags=re.IGNORECASE)
            t = re.sub(r'\bbölü\b', '/', t, flags=re.IGNORECASE)
            t = re.sub(r'\bartı\b|\btopla\b', '+', t, flags=re.IGNORECASE)
            t = re.sub(r'\beksi\b|\bçıkar\b', '-', t, flags=re.IGNORECASE)
            t = re.sub(r'\büstü\b|\büzeri\b|\bkare\b', '^', t, flags=re.IGNORECASE)

            has_trigger = bool(re.search(r'\b(hesapla|kaç eder|sonuç|çöz)\b', lc))
            has_operator = bool(re.search(r'[+\-*/\^%()]', t) and re.search(r'\d', t))

            if has_trigger or has_operator:
                # remove trigger words from candidate
                expr = re.sub(r'\b(hesapla|kaç eder|sonuç|çöz)\b', '', t, flags=re.IGNORECASE).strip()
                if not expr:
                    self._speak_and_reply('Hangi ifadeyi hesaplamamı istersiniz? (ör: 5+5 veya 20% of 150)')
                    return

                # If the candidate still contains mostly words (and no known function names),
                # try to extract a math-like substring to avoid parsing sentences like
                # "ben 44 yasindayim" which contain digits but are not expressions.
                if re.search(r'[A-Za-zİığüşöçĞÜŞÖÇ]', expr) and not re.search(r'\b(sqrt|sin|cos|tan|log|ln|exp|abs|round|ceil|floor)\b', expr, re.IGNORECASE):
                    parts = re.findall(r'[0-9\.\+\-\*/\^%()]+', expr)
                    expr_candidate = ' '.join(parts).strip()
                else:
                    expr_candidate = expr

                if not expr_candidate:
                    # not a math expression after extraction; fall through
                    pass
                else:
                    try:
                        res = math_engine.evaluate(expr_candidate)
                        # format nicely: integer if whole
                        if isinstance(res, float) and abs(res - int(res)) < 1e-9:
                            res = int(res)
                        resp = f'{expr_candidate} = {res}'
                        # use single reply method (do not add history twice)
                        self._speak_and_reply(resp)
                        return
                    except Exception:
                        # generic friendly error — avoid exposing raw parse traces
                        self._speak_and_reply('İfadeyi çözerken hata oldu. Lütfen daha basit bir matematik ifadesi girin (ör: 5+5, sqrt(9)).')
                        return
        except Exception:
            pass

        if lc in ('help', 'yardim', 'yardım'):
            try:
                # build help sections
                lines = []
                lines.append('ForzeOS Companion Yardım')
                lines.append('')
                lines.append('Companion komutları:')
                try:
                    for k, v in sorted(self.command_map.items()):
                        # v may be (callable, reply)
                        reply = v[1] if isinstance(v, (list, tuple)) and len(v) > 1 else ''
                        lines.append(f' - {k}  {reply or ""}')
                except Exception:
                    pass
                lines.append('')
                # host-provided open_* helpers
                host_funcs = []
                try:
                    for name in dir(getattr(self.forzeos, '__class__', self.forzeos)):
                        if name.startswith('open_') or name.startswith('open'):
                            host_funcs.append(name)
                except Exception:
                    pass
                if host_funcs:
                    lines.append('Host (ForzeOS) kullanılabilir open_* fonksiyonları:')
                    for h in sorted(set(host_funcs)):
                        lines.append(f' - {h}')
                    lines.append('')
                # file associations (app names)
                try:
                    fa = getattr(self.forzeos, 'FILE_ASSOCIATIONS', {})
                    appnames = sorted({v[0] for v in fa.values() if isinstance(v, (list, tuple)) and v})
                    if appnames:
                        lines.append('Dosya türleriyle ilişkili uygulamalar:')
                        for a in appnames:
                            lines.append(f' - {a}')
                        lines.append('')
                except Exception:
                    pass
                # shortcuts
                try:
                    cfg = getattr(self.forzeos, 'config', {}) or {}
                    shortcuts = cfg.get('shortcuts', {}) if isinstance(cfg, dict) else {}
                    if shortcuts:
                        lines.append('Kayıtlı kısayollar:')
                        for k, v in shortcuts.items():
                            lines.append(f' - {k} => {v}')
                        lines.append('')
                except Exception:
                    pass

                full = '\n'.join(lines)
                # show in chat as a green-styled command bubble
                try:
                    self._add_history('Companion', (full, 'cmd'))
                except Exception:
                    pass

                # also open a Toplevel help window for readability
                try:
                    hw = Toplevel(self.root)
                    hw.title('Companion Help')
                    hw.geometry('520x420')
                    txt = Text(hw, wrap='word')
                    txt.pack(fill='both', expand=True, padx=8, pady=8)
                    txt.insert('end', full)
                    txt.config(state='disabled')
                except Exception:
                    pass
            except Exception:
                pass
            return
        # try AssistantAI execute_command first if available
        # quick shortcut: if user invoked assistant by name and asked to open something, map to host open_* methods
        # If user addressed the assistant specifically and asked to open an app, use host mapping
        try:
            if 'forzos' in lc or 'forz' in lc or 'asist' in lc:
                m = re.search(r'open\s+([\w\s]+)', lc)
                if m:
                    candidate = m.group(1).strip().lower()
                    # direct exact match
                    fn = self._host_open_map.get(candidate)
                    # fuzzy match: check substring in keys
                    if not fn:
                        for k in self._host_open_map:
                            if candidate == k or candidate in k or k in candidate:
                                fn = self._host_open_map.get(k)
                                break
                    # last resort: replace spaces with underscore to form open_<name>
                    if not fn:
                        funcname = 'open_' + candidate.replace(' ', '_')
                        if hasattr(self.forzeos, funcname):
                            fn = getattr(self.forzeos, funcname)
                    if fn:
                        try:
                            # honor hide_on_open
                            try:
                                if self.hide_on_open and hasattr(self, 'win') and self.win:
                                    try:
                                        self.win.withdraw()
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                            if hasattr(self.forzeos, '_call_cmd_safe'):
                                # fn is typically a host bound method; call via host safe caller
                                try:
                                    self.forzeos._call_cmd_safe(fn)
                                except Exception:
                                    # fallback to direct invocation
                                    try:
                                        fn()
                                    except Exception:
                                        pass
                            else:
                                try:
                                    self.root.after(0, fn)
                                except Exception:
                                    fn()
                            try:
                                self.root.after(0, lambda: self._add_history('Companion', (f'Açılıyor: {candidate}', 'cmd')))
                            except Exception:
                                self._add_history('Companion', (f'Açılıyor: {candidate}', 'cmd'))
                            return
                        except Exception:
                            pass
        except Exception:
            pass

        try:
            if getattr(self, 'ai', None):
                try:
                    handled, result = self.ai.execute_command(txt, session_id=str(id(self.forzeos)))
                    if handled:
                        # special marker handling for OPEN_FUNCART
                        try:
                            if isinstance(result, str) and result.startswith('OPEN_FUNCART:::'):
                                expr = result.split(':::', 1)[1]
                                # open function art with prefilled expression
                                try:
                                    if hasattr(self.forzeos, '_call_cmd_safe'):
                                        self.forzeos._call_cmd_safe(lambda: self.open_function_art_with_expr(expr))
                                    else:
                                        try:
                                            self.root.after(0, lambda: self.open_function_art_with_expr(expr))
                                        except Exception:
                                            self.open_function_art_with_expr(expr)
                                except Exception:
                                    pass
                                return
                        except Exception:
                            pass
                        # Try to detect host open_* mentions in assistant result and call them
                        try:
                            if isinstance(result, str):
                                res_l = result.lower()
                                matched_fn = None
                                matched_key = None
                                # check direct app name mentions against host map
                                for k, fn in self._host_open_map.items():
                                    try:
                                        if k and k in res_l:
                                            matched_fn = fn
                                            matched_key = k
                                            break
                                    except Exception:
                                        pass
                                # pattern 'open X' in assistant result -> try to fuzzy match
                                if not matched_fn:
                                    m2 = re.search(r'open\s+([\w\s]+)', res_l)
                                    if m2:
                                        cand = m2.group(1).strip().lower()
                                        # exact
                                        matched_fn = self._host_open_map.get(cand)
                                        if not matched_fn:
                                            # substring heuristic
                                            for k, fn in self._host_open_map.items():
                                                if cand == k or cand in k or k in cand:
                                                    matched_fn = fn
                                                    matched_key = k
                                                    break
                                # if found, call it safely
                                if matched_fn:
                                    try:
                                        try:
                                            if self.hide_on_open and hasattr(self, 'win') and self.win:
                                                try:
                                                    self.win.withdraw()
                                                except Exception:
                                                    pass
                                        except Exception:
                                            pass
                                        if hasattr(self.forzeos, '_call_cmd_safe'):
                                            try:
                                                self.forzeos._call_cmd_safe(matched_fn)
                                            except Exception:
                                                try:
                                                    matched_fn()
                                                except Exception:
                                                    pass
                                        else:
                                            try:
                                                self.root.after(0, matched_fn)
                                            except Exception:
                                                matched_fn()
                                        try:
                                            label = matched_key or getattr(matched_fn, '__name__', str(matched_fn))
                                            self.root.after(0, lambda: self._add_history('Companion', (f'Açılıyor: {label}', 'cmd')))
                                        except Exception:
                                            self._add_history('Companion', (f'Açılıyor: {label}', 'cmd'))
                                        return
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                        except Exception:
                            pass
                        # animate and show result in green-styled bubble
                        self._set_anim_state('tap', duration=0.9)
                        try:
                            self.root.after(0, lambda: self._add_history('Companion', (result, 'cmd')))
                        except Exception:
                            self._add_history('Companion', (result, 'cmd'))
                        # If assistant asked to open Function ART, attempt to open it
                        try:
                            if isinstance(result, str) and 'function art' in result.lower():
                                try:
                                    # prefer host call if available
                                    if hasattr(self.forzeos, '_call_cmd_safe'):
                                        self.forzeos._call_cmd_safe(lambda: self.open_function_art())
                                    else:
                                        # open directly on main thread
                                        try:
                                            self.root.after(0, self.open_function_art)
                                        except Exception:
                                            self.open_function_art()
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        return
                except Exception:
                    pass
        except Exception:
            pass
        # detect teaching trigger early
        if getattr(self, 'ai', None) and re.search(r'\bteach\b|\böğret\b', lc):
            try:
                resp = self.ai.reply(txt, session_id=str(id(self.forzeos)))
                # animate and reply
                self._set_anim_state('talk', duration=1.5)
                # post assistant reply into history UI directly (left side)
                try:
                    self.root.after(0, lambda: self._add_history('Companion', resp))
                except Exception:
                    self._add_history('Companion', resp)
                # optional TTS
                try:
                    cfg = getattr(self.forzeos, 'config', {})
                    if cfg.get('settings', {}).get('assistant', {}).get('tts_enabled') and getattr(self, '_tts_available', False):
                        self.speak(resp)
                except Exception:
                    pass
                # record a light long-term note
                try:
                    self.ai.add_long_term_note('user_requested_teaching')
                except Exception:
                    pass
                return
            except Exception:
                pass
        # exact match first
        if lc in self.command_map:
            func, reply = self.command_map[lc]
            # special handling: if user typed just 'wiki' or 'wikipedia', prompt for topic
            if lc in ('wiki', 'wikipedia'):
                self._expecting_wiki_topic = True
                self._speak_and_reply('Hangi konuyu aramak istiyorsunuz? (ör: wiki Türkiye)')
                return
            self._speak_and_reply(reply)
            if func:
                try:
                    # call function on main thread via forzeos wrapper
                    # if command expects arguments (delete app or open path) try to extract
                    if lc.startswith('delete app'):
                        # expect format: delete app <name>
                        m = re.match(r'delete app\s+(.+)', txt, flags=re.IGNORECASE)
                        name = m.group(1).strip() if m else ''
                        try:
                            self.forzeos._call_cmd_safe(lambda: self.delete_app(name))
                        except Exception:
                            self.forzeos._call_cmd_safe(lambda: func(name))
                    elif lc.startswith('open path') or lc.startswith('dosya aç'):
                        m = re.search(r'open path\s+(.+)', txt, flags=re.IGNORECASE) or re.search(r'dosya aç\s+(.+)', txt, flags=re.IGNORECASE)
                        path = m.group(1).strip() if m else None
                        try:
                            self.forzeos._call_cmd_safe(lambda: self.open_path(path))
                        except Exception:
                            self.forzeos._call_cmd_safe(lambda: func(path) if path else func())
                        else:
                            # generic call without args - prefer running on the companion's
                            # Tk root if the callable is a companion method, otherwise use
                            # host safe caller which schedules on the host GUI thread.
                            try:
                                owner = getattr(func, '__self__', None)
                                if owner is self:
                                    try:
                                        self.root.after(0, func)
                                    except Exception:
                                        func()
                                else:
                                    try:
                                        self.forzeos._call_cmd_safe(lambda func=func: func())
                                    except Exception:
                                        try:
                                            self.root.after(0, func)
                                        except Exception:
                                            func()
                            except Exception:
                                try:
                                    self.forzeos._call_cmd_safe(lambda func=func: func())
                                except Exception:
                                    try:
                                        self.root.after(0, func)
                                    except Exception:
                                        func()
                except Exception as e:
                    self._speak_and_reply("Üzgünüm, komut çalıştırılamadı: {}".format(e))
            return

        # simple substring triggers
        for key in self.command_map:
            if key in lc:
                func, reply = self.command_map[key]
                # handle wiki variations: if 'wiki' present with topic, pass the full text
                if key in ('wiki', 'wikipedia'):
                    # exact keyword -> prompt
                    if lc.strip() == key:
                        self._expecting_wiki_topic = True
                        self._speak_and_reply('Hangi konuyu aramak istiyorsunuz? (ör: wiki Türkiye)')
                        return
                    # contains keyword plus topic -> call with provided text
                    try:
                        self._speak_and_reply(reply)
                        owner = getattr(func, '__self__', None)
                        if owner is self:
                            try:
                                self.root.after(0, lambda: func(txt))
                            except Exception:
                                func(txt)
                        else:
                            try:
                                # if func is a host bound method, pass args through safe caller
                                if getattr(owner, '__class__', None) is getattr(self.forzeos, '__class__', None) or owner is getattr(self.forzeos, None):
                                    try:
                                        self.forzeos._call_cmd_safe(func, txt)
                                    except Exception:
                                        try:
                                            func(txt)
                                        except Exception:
                                            pass
                                else:
                                    try:
                                        self.forzeos._call_cmd_safe(lambda: func(txt))
                                    except Exception:
                                        try:
                                            self.root.after(0, lambda: func(txt))
                                        except Exception:
                                            func(txt)
                            except Exception:
                                try:
                                    self.forzeos._call_cmd_safe(lambda: func(txt))
                                except Exception:
                                    try:
                                        self.root.after(0, lambda: func(txt))
                                    except Exception:
                                        func(txt)
                    except Exception as e:
                        self._speak_and_reply("Üzgünüm, komut çalıştırılamadı: {}".format(e))
                    return
                self._speak_and_reply(reply)
                if func:
                    try:
                        owner = getattr(func, '__self__', None)
                        if owner is self:
                            try:
                                self.root.after(0, func)
                            except Exception:
                                func()
                        else:
                            try:
                                self.forzeos._call_cmd_safe(lambda func=func: func())
                            except Exception:
                                try:
                                    self.root.after(0, func)
                                except Exception:
                                    func()
                    except Exception as e:
                        self._speak_and_reply("Üzgünüm, komut çalıştırılamadı: {}".format(e))
                return

        # some playful rules
        if any(word in lc for word in ("hi", "hello", "merhaba", "selam")):
            self._speak_and_reply("Selam! Nasılsın? Ben bir şapkalı botum, komut için 'help' yazabilirsin.")
            return

        if 'joke' in lc or 'şaka' in lc:
            # delegate to assistant if available
            try:
                if getattr(self, 'ai', None):
                    resp = self.ai.reply(txt, session_id=str(id(self.forzeos)))
                    self._speak_and_reply(resp)
                    return
            except Exception:
                pass
            self._speak_and_reply("Neden programcılar güneşi sevmiyor? Çünkü hep gölgede kalıyorlar. 😄")
            return

        # numeric-ish request: open file types
        if 'open' in lc and 'pdf' in lc:
            self._speak_and_reply("PDF okuyucuyu açıyorum...")
            try:
                self.forzeos._call_cmd_safe(self.forzeos.open_pdf_reader)
            except Exception as e:
                self._speak_and_reply(f"Hata: {e}")
            return

        # toggle right-click move via chat
        if 'disable right click move' in lc or 'disable move' in lc or 'disable hareket' in lc:
            self.allow_move_on_rightclick = False
            try:
                if hasattr(self.forzeos, 'config'):
                    self.forzeos.config.setdefault('desktop', {})['companion_allow_move'] = False
                    try:
                        self.forzeos.save_config()
                    except Exception:
                        pass
            except Exception:
                pass
            self._speak_and_reply("Sağ tıklamayla taşıma devre dışı bırakıldı.")
            return

        if 'enable right click move' in lc or 'enable move' in lc or 'enable hareket' in lc:
            self.allow_move_on_rightclick = True
            try:
                if hasattr(self.forzeos, 'config'):
                    self.forzeos.config.setdefault('desktop', {})['companion_allow_move'] = True
                    try:
                        self.forzeos.save_config()
                    except Exception:
                        pass
            except Exception:
                pass
            self._speak_and_reply("Sağ tıklamayla taşıma etkinleştirildi.")
            return

        # AI toggle commands
        if 'disable ai' in lc or 'ai off' in lc or 'ai kapat' in lc:
            self.ai_enabled = False
            try:
                if hasattr(self.forzeos, 'config'):
                    self.forzeos.config.setdefault('desktop', {})['companion_ai_enabled'] = False
                    try:
                        self.forzeos.save_config()
                    except Exception:
                        pass
            except Exception:
                pass
            self._speak_and_reply("AI modu kapatıldı. Sadece kural-tabani cevaplar verilecektir.")
            return

        if 'enable ai' in lc or 'ai on' in lc or 'ai ac' in lc:
            self.ai_enabled = True
            try:
                if hasattr(self.forzeos, 'config'):
                    self.forzeos.config.setdefault('desktop', {})['companion_ai_enabled'] = True
                    try:
                        self.forzeos.save_config()
                    except Exception:
                        pass
            except Exception:
                pass
            self._speak_and_reply("AI modu etkinleştirildi. Sohbete hazırım.")
            return

        # AI-like fallback: try to forward unknown commands to host command processor
        try:
            if hasattr(self.forzeos, 'execute_real_command'):
                try:
                    self.forzeos.execute_real_command(txt)
                    self._speak_and_reply("Komutu hosta gönderdim.")
                    return
                except Exception:
                    pass
            elif hasattr(self.forzeos, '_call_cmd_safe'):
                try:
                    # some hosts may accept string commands via the safe caller
                    self.forzeos._call_cmd_safe(txt)
                    self._speak_and_reply("Komutu hosta gönderdim.")
                    return
                except Exception:
                    pass
        except Exception:
            pass

        # fallback: prefer offline AI assistant if enabled
        try:
            if getattr(self, 'ai_enabled', False) and getattr(self, 'ai', None) is not None:
                try:
                    # consult host assistant settings to optionally influence reply
                    ast_cfg = self.forzeos.config.get('settings', {}).get('assistant', {}) if hasattr(self.forzeos, 'config') else {}
                    style = ast_cfg.get('style', None)
                    # get raw reply from assistant
                    resp = self.ai.reply(txt, session_id=str(id(self.forzeos)))
                    # post-process reply based on style
                    if style:
                        try:
                            if style == 'Kısa':
                                # shorten: take first sentence
                                resp = resp.split('.')[:1][0].strip()
                            elif style == 'Mizahi':
                                resp = resp + ' 😄'
                            elif style == 'Resmi':
                                resp = resp.replace("Ben", "Ben (asistan)")
                            # Detaylı -> leave as-is
                        except Exception:
                            pass
                    self._speak_and_reply(resp)
                    return
                except Exception:
                    pass
        except Exception:
            pass

        # default random fallback
        import random
        reply = random.choice(self.default_replies)
        self._speak_and_reply(reply)

    def _speak_and_reply(self, reply_text):
        # update UI
        def _ui_update():
            self._add_history('Forze', reply_text)
        try:
            self.root.after(0, _ui_update)
        except Exception:
            pass

        # speak if available
        try:
            # consult host assistant settings whether tts is enabled
            tts_enabled = True
            try:
                ast_cfg = self.forzeos.config.get('settings', {}).get('assistant', {}) if hasattr(self.forzeos, 'config') else {}
                if 'tts_enabled' in ast_cfg:
                    tts_enabled = bool(ast_cfg.get('tts_enabled'))
            except Exception:
                pass
            if tts_enabled and self._tts_available and self._tts_engine:
                try:
                    threading.Thread(target=self._tts_engine.say, args=(reply_text,), daemon=True).start()
                    # run engine in own thread
                    def _run_engine():
                        try:
                            self._tts_engine.runAndWait()
                        except Exception:
                            pass
                    threading.Thread(target=_run_engine, daemon=True).start()
                except Exception:
                    pass
        except Exception:
            pass

        # briefly show talk animation
        self._set_anim_state('talk', duration=1.6)

    # -------------------- Utilities --------------------
    def speak(self, text):
        """Public method to make companion speak via TTS and history."""
        self._speak_and_reply(text)


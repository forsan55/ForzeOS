"""
forzeos_core.py
Core window manager, animation, command palette, and desktop widget helpers
Designed to integrate non-invasively with the large ForzeOS file.
"""
import tkinter as tk
from tkinter import messagebox
import threading
import time
import weakref
import urllib.request
import json
import os
import sys
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Keep weak refs to managed windows
_WINDOW_BASE_INSTANCES = weakref.WeakSet()

class AnimationManager:
    def __init__(self):
        self._locks = weakref.WeakKeyDictionary()

    def fade_in(self, toplevel, duration=0.28, steps=14, target_alpha=1.0):
        try:
            if not hasattr(toplevel, 'wm_attributes'):
                return
            try:
                toplevel.wm_attributes('-alpha', 0.0)
            except Exception:
                pass
            step = max(1, steps)
            interval = max(0.01, float(duration) / step)
            def _run(i=0):
                try:
                    a = float(i) / step * target_alpha
                    toplevel.wm_attributes('-alpha', a)
                    if i < step:
                        toplevel.after(int(interval * 1000), lambda: _run(i+1))
                except Exception:
                    pass
            _run(0)
        except Exception:
            pass

    def fade_out(self, toplevel, duration=0.28, steps=12, on_complete=None):
        try:
            if not hasattr(toplevel, 'wm_attributes'):
                if on_complete:
                    try: on_complete()
                    except Exception: pass
                return
            try:
                cur = toplevel.wm_attributes('-alpha')
            except Exception:
                cur = 1.0
            step = max(1, steps)
            interval = max(0.01, float(duration) / step)
            def _run(i=step):
                try:
                    a = float(i) / step * cur
                    toplevel.wm_attributes('-alpha', a)
                    if i > 0:
                        toplevel.after(int(interval * 1000), lambda: _run(i-1))
                    else:
                        if on_complete:
                            try: on_complete()
                            except Exception: pass
                except Exception:
                    if on_complete:
                        try: on_complete()
                        except Exception: pass
            _run(step)
        except Exception:
            if on_complete:
                try: on_complete()
                except Exception: pass

# single shared manager
_ANIM = AnimationManager()

class WindowBase:
    """Manager attached to an existing Toplevel. Keeps a common header, opacity
    and animation handling. The original Toplevel object is left intact and
    returned to existing code to preserve compatibility.
    """
    def __init__(self, toplevel: tk.Toplevel, title: str = None, forze=None):
        self.window = toplevel
        self.title = title or getattr(toplevel, 'title', '')
        self.forze = forze
        self._closed = False
        _WINDOW_BASE_INSTANCES.add(self)
        try:
            # Add a simple in-window header bar (keeps system titlebar intact)
            header = tk.Frame(self.window, height=26)
            header.pack(side='top', fill='x')
            header.configure(bg=(getattr(forze, 'colors', {}).get('accent', '#333') if forze else '#333'))
            lbl = tk.Label(header, text=self.title or '', bg=header['bg'], fg='white')
            lbl.pack(side='left', padx=6)
            # close button
            def _close():
                try:
                    self.close()
                except Exception:
                    try: self.window.destroy()
                    except Exception: pass
            btn = tk.Button(header, text='✕', bg=header['bg'], fg='white', bd=0, command=_close)
            btn.pack(side='right', padx=6)
        except Exception:
            pass

        # override WM_DELETE to run fade-out animation
        try:
            orig = None
            try:
                orig = self.window.protocol('WM_DELETE_WINDOW')
            except Exception:
                orig = None
            def _on_close():
                if self._closed:
                    try:
                        if orig and callable(orig): orig()
                    except Exception:
                        pass
                    return
                self._closed = True
                try:
                    _ANIM.fade_out(self.window, duration=0.22, steps=10, on_complete=lambda: self._final_destroy(orig))
                except Exception:
                    self._final_destroy(orig)
            try:
                self.window.protocol('WM_DELETE_WINDOW', _on_close)
            except Exception:
                pass
        except Exception:
            pass

        # apply initial opacity
        try:
            self.apply_opacity_from_config()
        except Exception:
            pass

        # run fade-in if enabled
        try:
            animations_on = True
            if forze:
                try:
                    animations_on = bool(forze.config.get('settings', {}).get('animations', True))
                except Exception:
                    animations_on = True
            if animations_on:
                try:
                    _ANIM.fade_in(self.window, duration=0.28, steps=12, target_alpha=float(self.window.wm_attributes('-alpha') if hasattr(self.window, 'wm_attributes') else 1.0))
                except Exception:
                    pass
        except Exception:
            pass

    def _final_destroy(self, orig_protocol=None):
        try:
            try:
                # Always try to unregister this window from ForzeOS taskbar first
                try:
                    if getattr(self, 'forze', None) and hasattr(self.forze, 'unregister_window'):
                        try:
                            # primary unregister by object (if used as key)
                            try:
                                self.forze.unregister_window(self.window)
                            except Exception:
                                pass
                            # additionally remove any taskbar buttons that reference this window object
                            try:
                                tb = getattr(self.forze, '_taskbar_buttons', {}) or {}
                                for tname, entry in list(tb.items()):
                                    try:
                                        wref = entry.get('window') if isinstance(entry, dict) else None
                                        if wref is self.window:
                                            try:
                                                self.forze.remove_taskbar_button(tname)
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                            # also clear taskbar_icons entries mapping to this window
                            try:
                                icons = getattr(self.forze, 'taskbar_icons', {}) or {}
                                for tname, meta in list(icons.items()):
                                    try:
                                        if meta and meta.get('window') is self.window:
                                            try:
                                                self.forze.remove_taskbar_button(tname)
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                        except Exception:
                            pass
                except Exception:
                    pass

                # Then call original protocol if present, otherwise destroy
                if orig_protocol and callable(orig_protocol):
                    try:
                        orig_protocol()
                    except Exception:
                        try:
                            self.window.destroy()
                        except Exception:
                            pass
                else:
                    try:
                        self.window.destroy()
                    except Exception:
                        pass
            except Exception:
                try: self.window.destroy()
                except Exception: pass
        finally:
            try:
                _WINDOW_BASE_INSTANCES.discard(self)
            except Exception:
                pass

    def set_opacity(self, alpha: float):
        try:
            if hasattr(self.window, 'wm_attributes'):
                try:
                    self.window.wm_attributes('-alpha', float(alpha))
                except Exception:
                    pass
        except Exception:
            pass

    def apply_opacity_from_config(self):
        try:
            if not self.forze:
                return
            cfg = self.forze.config.get('settings', {})
            val = cfg.get('opacity_window', None)
            if val is None:
                val = cfg.get('window_opacity', 1.0)
            try:
                val = float(val)
            except Exception:
                val = 1.0
            self.set_opacity(val)
        except Exception:
            pass

    # allow attribute proxying to underlying toplevel for compatibility
    def __getattr__(self, item):
        return getattr(self.window, item)

# Public helper to register an existing Toplevel
def register_window_by_toplevel(toplevel, title=None, forze=None):
    try:
        # If there's already a WindowBase for this toplevel, skip
        for w in list(_WINDOW_BASE_INSTANCES):
            try:
                if getattr(w, 'window', None) is toplevel:
                    return w
            except Exception:
                pass
        wb = WindowBase(toplevel, title=title, forze=forze)
        return wb
    except Exception:
        return None

# Apply current settings to all managed windows and widgets
def apply_live_settings(forze):
    try:
        cfg = getattr(forze, 'config', {}).get('settings', {})
        # opacity values
        win_op = cfg.get('opacity_window', cfg.get('window_opacity', 1.0))
        pop_op = cfg.get('opacity_popup', 0.95)
        task_op = cfg.get('opacity_taskbar', 1.0)
        try:
            win_op = float(win_op)
        except Exception:
            win_op = 1.0
        # update windows
        for w in list(_WINDOW_BASE_INSTANCES):
            try:
                w.set_opacity(win_op)
            except Exception:
                pass
        # update any known popup windows by scanning for Toplevels that are not managed
        # (best-effort; callers can also manually set)
    except Exception:
        pass

# Command palette
class CommandPalette:
    def __init__(self, forze):
        self.forze = forze
        self.window = None

    def show(self):
        try:
            if self.window and getattr(self.window, 'winfo_exists', lambda:False)():
                try:
                    self.window.deiconify()
                    self.window.lift()
                    return
                except Exception:
                    pass
            root = getattr(self.forze, 'root', None)
            if not root:
                return
            w = tk.Toplevel(root)
            w.overrideredirect(False)
            w.transient(root)
            w.geometry('480x60')
            sw = root.winfo_screenwidth()
            sh = root.winfo_screenheight()
            x = int((sw - 480) / 2)
            y = int((sh - 60) / 2)
            w.geometry(f'+{x}+{y}')
            w.title('Run')
            # apply popup opacity
            try:
                pop_op = float(self.forze.config.get('settings', {}).get('opacity_popup', 0.95))
                w.wm_attributes('-alpha', pop_op)
            except Exception:
                pass
            ent = tk.Entry(w, font=('Segoe UI', 12))
            ent.pack(fill='both', expand=True, padx=8, pady=8)
            ent.focus_set()
            def _on_enter(event=None):
                cmd = ent.get().strip()
                if not cmd:
                    try: w.destroy()
                    except Exception: pass
                    return
                # Try engine hooks on ForzeOS
                try:
                    # first: known internal command invocations
                    if hasattr(self.forze, '_start_menu_invoke'):
                        try:
                            self.forze._start_menu_invoke(cmd, name=cmd)
                            w.destroy()
                            return
                        except Exception:
                            pass
                    # second: execute as OS/terminal command
                    if hasattr(self.forze, 'execute_real_command'):
                        try:
                            self.forze.execute_real_command(cmd)
                            w.destroy()
                            return
                        except Exception:
                            pass
                    # last resorts: call common system methods
                    lc = cmd.lower()
                    if lc in ('shutdown', 'poweroff') and hasattr(self.forze, 'shutdown_system'):
                        try: self.forze.shutdown_system(); w.destroy(); return
                        except Exception: pass
                    if lc in ('restart', 'reboot') and hasattr(self.forze, 'restart_system'):
                        try: self.forze.restart_system(); w.destroy(); return
                        except Exception: pass
                except Exception:
                    pass
                try:
                    # fallback: spawn subprocess
                    import subprocess
                    subprocess.Popen(cmd, shell=True)
                except Exception:
                    pass
                try:
                    w.destroy()
                except Exception:
                    pass
            ent.bind('<Return>', _on_enter)
            ent.bind('<Escape>', lambda e: w.destroy())
            self.window = w
        except Exception:
            pass

# Simple weather widget embedded into desktop area
class WeatherWidget:
    def __init__(self, forze, x=None, y=None):
        self.forze = forze
        self.parent = getattr(forze, 'desktop', None) or getattr(forze, 'root', None)
        self.frame = None
        self.x = x
        self.y = y
        try:
            self._create()
            # schedule a refresh every 10 minutes
            try:
                self._schedule_refresh()
            except Exception:
                pass
        except Exception:
            pass

    def _create(self):
        try:
            sw = self.forze.screen_width if hasattr(self.forze, 'screen_width') else self.forze.root.winfo_screenwidth()
            # nicer compact frame
            self.frame = tk.Frame(self.parent, bg='#1f1f1f', bd=0, relief='flat')
            # icon + main text area
            container = tk.Frame(self.frame, bg=self.frame['bg'])
            container.pack(padx=6, pady=6)
            self._icon = tk.Label(container, text='⛅', font=('Segoe UI', 18), bg=self.frame['bg'], fg='white')
            self._icon.pack(side='left')
            textcol = '#ffffff'
            txt_frame = tk.Frame(container, bg=self.frame['bg'])
            txt_frame.pack(side='left', padx=(8,0))
            self._temp = tk.Label(txt_frame, text='--°', font=('Segoe UI', 12, 'bold'), bg=self.frame['bg'], fg=textcol)
            self._temp.pack(anchor='w')
            self._desc = tk.Label(txt_frame, text='Loading...', font=('Segoe UI', 9), bg=self.frame['bg'], fg='#cfcfcf')
            self._desc.pack(anchor='w')

            # clickable: open details popup
            def _on_click(ev=None):
                try:
                    self._show_details()
                except Exception:
                    pass
            for w in (self.frame, container, self._icon, self._temp, self._desc):
                try:
                    w.bind('<Button-1>', _on_click)
                    w.config(cursor='hand2')
                except Exception:
                    pass

            # default position: snug to top-right with small margin
            x = self.x if self.x is not None else sw - 12
            y = self.y if self.y is not None else 12
            try:
                if hasattr(self.forze, 'desktop_canvas') and getattr(self.forze, 'desktop_canvas'):
                    c = self.forze.desktop_canvas
                    try:
                        self._canvas_window = c.create_window(x, y, window=self.frame, anchor='ne')
                    except Exception:
                        self.frame.place(x=x-200, y=y)
                else:
                    self.frame.place(x=x-200, y=y)
            except Exception:
                try:
                    self.frame.pack()
                except Exception:
                    pass

            # keep references
            self._label = self._desc
            self._last_data = None
            self.refresh()
        except Exception:
            pass

    def refresh(self):
        try:
            # quick placeholders
            try:
                self._icon.config(text='⛅')
                self._temp.config(text='--°')
                self._desc.config(text='Updating...')
            except Exception:
                pass

            # background fetch (JSON preferred) to populate rich UI
            def _worker():
                data = None
                # prefer JSON
                try:
                    with urllib.request.urlopen('https://wttr.in/?format=j1', timeout=6) as fh:
                        raw = fh.read().decode('utf-8')
                        data = json.loads(raw)
                except Exception:
                    data = None

                # fallback to simple text if JSON not available
                if not data:
                    txt = None
                    endpoints = [
                        'https://wttr.in/?format=%c+%t',
                        'https://wttr.in/?format=1'
                    ]
                    for ep in endpoints:
                        for attempt in range(2):
                            try:
                                with urllib.request.urlopen(ep, timeout=4 + attempt*2) as fh:
                                    ttxt = fh.read().decode('utf-8').strip()
                                    if ttxt:
                                        txt = ttxt
                                        break
                            except Exception:
                                time.sleep(0.2)
                        if txt:
                            break
                    if txt:
                        # try to split icon/temperature
                        try:
                            parts = txt.split()
                            icon = parts[0]
                            temp = ' '.join(parts[1:])
                        except Exception:
                            icon = '🌤️'
                            temp = txt
                        main = {'icon': icon, 'temp': temp, 'desc': txt}
                        self._last_data = main
                    else:
                        self._last_data = None
                else:
                    try:
                        cur = data.get('current_condition', [{}])[0]
                        temp = cur.get('temp_C')
                        desc = (cur.get('weatherDesc') or [{'value':''}])[0].get('value','')
                        # choose emoji from desc
                        icon = self._cond_to_emoji(desc)
                        self._last_data = {'icon': icon, 'temp': f"{temp}°C" if temp is not None else '', 'desc': desc, 'json': data}
                    except Exception:
                        self._last_data = None

                # update UI on main thread
                try:
                    def _upd():
                        try:
                            if not self._last_data:
                                self._icon.config(text='N/A')
                                self._temp.config(text='N/A')
                                self._desc.config(text='No data')
                                return
                            self._icon.config(text=self._last_data.get('icon','⛅'))
                            self._temp.config(text=self._last_data.get('temp', '--°'))
                            self._desc.config(text=self._last_data.get('desc',''))
                        except Exception:
                            pass
                    if getattr(self, 'forze', None) and getattr(self.forze, 'root', None):
                        try:
                            self.forze.root.after(0, _upd)
                        except Exception:
                            _upd()
                    else:
                        _upd()
                except Exception:
                    pass

            t = threading.Thread(target=_worker, daemon=True)
            t.start()
        except Exception:
            try:
                self._label.config(text='Weather: N/A')
            except Exception:
                pass

    def _cond_to_emoji(self, desc: str):
        try:
            if not desc:
                return '🌤️'
            d = desc.lower()
            if 'sun' in d or 'clear' in d:
                return '☀️'
            if 'part' in d or 'fair' in d:
                return '⛅'
            if 'cloud' in d or 'overcast' in d:
                return '☁️'
            if 'rain' in d or 'shower' in d or 'drizzle' in d:
                return '🌧️'
            if 'thunder' in d or 'storm' in d:
                return '⛈️'
            if 'snow' in d or 'sleet' in d:
                return '❄️'
            return '🌤️'
        except Exception:
            return '🌤️'

    def _show_details(self):
        try:
            root = getattr(self.forze, 'root', None)
            # reuse if exists
            if getattr(self, '_details_win', None) and getattr(self._details_win, 'winfo_exists', lambda:False)():
                try:
                    self._details_win.lift()
                    return
                except Exception:
                    pass
            w = tk.Toplevel(root if root else None)
            w.title('Weather Details')
            w.transient(root)
            w.resizable(False, False)
            w.geometry('+{}+{}'.format(max(20, (root.winfo_screenwidth()-360) if root else 20), 80))
            frame = tk.Frame(w, bg='#1f1f1f', padx=8, pady=8)
            frame.pack(fill='both', expand=True)
            # populate details
            data = getattr(self, '_last_data', None)
            if data and data.get('json'):
                j = data['json']
                # nearest area if available
                try:
                    area = (j.get('nearest_area') or [{}])[0]
                    name = (area.get('areaName') or [{'value':''}])[0].get('value','')
                except Exception:
                    name = ''
                tk.Label(frame, text=(name or 'Weather'), font=('Segoe UI', 11, 'bold'), bg=frame['bg'], fg='white').pack(anchor='w')
                tk.Label(frame, text=data.get('desc',''), bg=frame['bg'], fg='#cfcfcf').pack(anchor='w')
                # show up to 3-day forecast
                try:
                    days = j.get('weather', [])[:3]
                    for day in days:
                        hdr = f"{day.get('date','')}  {day.get('maxtempC','')}°/{day.get('mintempC','')}°"
                        tk.Label(frame, text=hdr, bg=frame['bg'], fg='white').pack(anchor='w')
                        sub = (day.get('hourly') or [])
                        if sub:
                            desc = (sub[0].get('weatherDesc') or [{'value':''}])[0].get('value','')
                            tk.Label(frame, text=f"  {desc}", bg=frame['bg'], fg='#cfcfcf').pack(anchor='w')
                except Exception:
                    pass
            else:
                # simple text fallback
                txt = None
                try:
                    txt = self._last_data.get('desc') if self._last_data else None
                except Exception:
                    txt = None
                if txt:
                    tk.Label(frame, text=txt, bg=frame['bg'], fg='white').pack(anchor='w')
                else:
                    tk.Label(frame, text='Detailed forecast unavailable', bg=frame['bg'], fg='white').pack(anchor='w')

            w.bind('<Escape>', lambda e: w.destroy())
            self._details_win = w
        except Exception:
            pass

    def _schedule_refresh(self):
        try:
            self.forze.root.after(10 * 60 * 1000, self._scheduled)
        except Exception:
            pass

    def _scheduled(self):
        try:
            self.refresh()
            self._schedule_refresh()
        except Exception:
            pass

# Convenient global functions for ForzeOS to call
_CMD_PALETTES = weakref.WeakKeyDictionary()
_WIDGETS = weakref.WeakKeyDictionary()

def show_command_palette(forze):
    try:
        cp = _CMD_PALETTES.get(forze)
        if cp is None:
            cp = CommandPalette(forze)
            _CMD_PALETTES[forze] = cp
        cp.show()
    except Exception:
        pass

def ensure_weather_widget(forze):
    try:
        w = _WIDGETS.get(forze)
        if w is not None:
            return w

        # create with retries: wait until desktop_canvas (or desktop) is ready
        max_tries = 60
        interval_ms = 250

        def _attempt(i=0):
            try:
                if forze is None:
                    return
                canvas = getattr(forze, 'desktop_canvas', None)
                root = getattr(forze, 'root', None)
                # Consider ready when canvas exists and has a reasonable size, or
                # when root is mapped and some desktop attributes exist.
                ready = False
                try:
                    if canvas and getattr(canvas, 'winfo_width', lambda:0)() > 120:
                        ready = True
                except Exception:
                    pass
                try:
                    if not ready and root and root.winfo_ismapped():
                        ready = True
                except Exception:
                    pass

                if ready or i >= max_tries:
                    try:
                        w2 = WeatherWidget(forze)
                        _WIDGETS[forze] = w2
                        # Try to bring widget to front
                        try:
                            if hasattr(w2, 'frame') and w2.frame:
                                try:
                                    w2.frame.lift()
                                except Exception:
                                    pass
                            if hasattr(forze, 'desktop_canvas') and getattr(forze, 'desktop_canvas'):
                                try:
                                    forze.desktop_canvas.tag_raise(getattr(w2, '_canvas_window', None))
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    except Exception:
                        pass
                    return

                # schedule another attempt
                try:
                    if hasattr(forze, 'root') and getattr(forze, 'root'):
                        forze.root.after(interval_ms, lambda: _attempt(i+1))
                    else:
                        threading.Timer(interval_ms/1000.0, lambda: _attempt(i+1)).start()
                except Exception:
                    try:
                        threading.Timer(interval_ms/1000.0, lambda: _attempt(i+1)).start()
                    except Exception:
                        pass
            except Exception:
                pass

        try:
            _attempt(0)
        except Exception:
            pass
        return None
    except Exception:
        return None


# ----------------------- Desktop shortcut helper (Windows) -----------------------
def _get_windows_desktop_path():
    try:
        # Prefer winshell/Desktop (handles OneDrive and redirected folders)
        try:
            import winshell
            d = Path(winshell.desktop())
            if d.exists():
                return d
        except Exception:
            pass
        # Fallback to USERPROFILE\Desktop to handle common Windows layouts
        up = os.environ.get('USERPROFILE')
        if up:
            d = Path(up) / 'Desktop'
            if d.exists():
                return d
    except Exception:
        pass
    # Fallback to home/Desktop
    return Path.home() / 'Desktop'


def create_windows_shortcut(target, shortcut_path, working_dir=None, icon=None, hotkey=None, description='', open_in_console=False):
    """Create a Windows .lnk shortcut. Tries pywin32 (WScript.Shell) first, then winshell if available.

    If `open_in_console` is True and the target is a Python script, the
    created shortcut will launch `cmd.exe` with `/k ...` so a console stays
    open for debugging. Returns True on success, False otherwise.
    """
    try:
        import shutil
        targ_str = str(target)
        targ_path = None
        try:
            targ_path = Path(targ_str)
        except Exception:
            targ_path = None

        # Detect Python script targets and prepare launcher+args
        is_script = False
        try:
            if targ_path and targ_path.suffix.lower() in ('.py', '.pyw'):
                is_script = True
        except Exception:
            is_script = False

        if is_script:
            # Detect available launchers
            py_launcher = shutil.which('py')
            py_exe = shutil.which('python.exe') or shutil.which('python')
            pythonw = shutil.which('pythonw.exe')

            if open_in_console:
                # Launch via cmd.exe and keep console open (/k) so debugger/prints are visible
                cmd_path = Path(os.environ.get('WINDIR', 'C:\\Windows')) / 'System32' / 'cmd.exe'
                if py_launcher:
                    inner = f'py -3 "{targ_str}"'
                else:
                    # Prefer a concrete python.exe if available, otherwise rely on plain 'python'
                    if py_exe:
                        launcher_cmd = f'"{py_exe}"' if ' ' in py_exe else py_exe
                        inner = f'{launcher_cmd} "{targ_str}"'
                    else:
                        inner = f'python "{targ_str}"'
                lnk_target = str(cmd_path)
                lnk_args = f'/k {inner}'
            else:
                # Non-console behavior: prefer the py launcher, then pythonw, then python
                launcher = py_launcher or pythonw or py_exe
                if launcher:
                    lnk_target = str(launcher)
                    lnk_args = f'"{targ_str}"'
                else:
                    # Fallback to invoking python via cmd (non-interactive)
                    lnk_target = str(Path(os.environ.get('WINDIR', 'C:\\Windows')) / 'System32' / 'cmd.exe')
                    lnk_args = f'/c python "{targ_str}"'
        else:
            lnk_target = targ_str
            lnk_args = ''

        # Try pywin32 first
        try:
            from win32com.client import Dispatch
            shell = Dispatch('WScript.Shell')
            lnk = shell.CreateShortcut(str(shortcut_path))
            lnk.TargetPath = lnk_target
            if lnk_args:
                try:
                    lnk.Arguments = lnk_args
                except Exception:
                    pass
            if working_dir:
                lnk.WorkingDirectory = str(working_dir)
            if icon:
                try:
                    lnk.IconLocation = str(icon)
                except Exception:
                    pass
            if description:
                try:
                    lnk.Description = description
                except Exception:
                    pass
            if hotkey:
                try:
                    lnk.Hotkey = hotkey
                except Exception:
                    pass
            try:
                lnk.Save()
            except Exception:
                try:
                    lnk.save()
                except Exception:
                    raise
            return True
        except Exception as e_pywin:
            # Fallback to winshell, using the same launcher+arguments logic
            try:
                import winshell
                launcher = None
                if is_script:
                    py_launcher = shutil.which('py')
                    py_exe = shutil.which('python.exe') or shutil.which('python')
                    pythonw = shutil.which('pythonw.exe')
                    if open_in_console:
                        cmd = str(Path(os.environ.get('WINDIR', 'C:\\Windows')) / 'System32' / 'cmd.exe')
                        if py_launcher:
                            inner = f'py -3 "{targ_str}"'
                            winshell.CreateShortcut(str(shortcut_path), cmd, Arguments=f'/k {inner}', StartIn=str(working_dir) if working_dir else '', Icon=(str(icon) if icon else '', 0), Description=description)
                        else:
                            if py_exe:
                                launcher_cmd = f'"{py_exe}"' if ' ' in py_exe else py_exe
                                inner = f'{launcher_cmd} "{targ_str}"'
                            else:
                                inner = f'python "{targ_str}"'
                            winshell.CreateShortcut(str(shortcut_path), cmd, Arguments=f'/k {inner}', StartIn=str(working_dir) if working_dir else '', Icon=(str(icon) if icon else '', 0), Description=description)
                    else:
                        launcher = py_launcher or pythonw or py_exe
                        if launcher:
                            winshell.CreateShortcut(str(shortcut_path), str(launcher), Arguments=f'"{targ_str}"', StartIn=str(working_dir) if working_dir else '', Icon=(str(icon) if icon else '', 0), Description=description)
                        else:
                            cmd = str(Path(os.environ.get('WINDIR', 'C:\\Windows')) / 'System32' / 'cmd.exe')
                            winshell.CreateShortcut(str(shortcut_path), cmd, Arguments=f'/c python "{targ_str}"', StartIn=str(working_dir) if working_dir else '', Icon=(str(icon) if icon else '', 0), Description=description)
                else:
                    kw = {}
                    if working_dir:
                        kw['StartIn'] = str(working_dir)
                    if icon:
                        kw['Icon'] = (str(icon), 0) if not isinstance(icon, tuple) else icon
                    if description:
                        kw['Description'] = description
                    winshell.CreateShortcut(str(shortcut_path), str(target), Arguments='', **kw)
                return True
            except Exception as e_winsh:
                logger.debug('pywin32 error: %s', e_pywin)
                logger.debug('winshell error: %s', e_winsh)
                return False
    except Exception:
        logger.exception('create_windows_shortcut failed')
        return False


def ensure_desktop_shortcut_prompt(name='ForzeOS', hotkey='Ctrl+Alt+F', icon_path=None, forze=None):
    """If running on Windows, ask for (or respect) a stored permission to
    create a desktop shortcut for `name`. If permission is granted, attempt
    to create the .lnk and assign the requested hotkey.

    Behaviour:
    - If `forze` is provided, read/write the setting at
      `forze.config['settings']['allow_desktop_shortcuts']` and call
      `forze.save_config()` to persist changes.
    - If the setting is True, create the shortcut immediately.
    - If the setting is False, do nothing.
    - If the setting is missing/None, prompt the user once and persist
      their response.

    Returns True if a shortcut was created, False otherwise.
    """
    try:
        if not sys.platform.startswith('win'):
            return False

        # Read stored permission (prefer ForzeOS instance if provided)
        perm = None
        try:
            if forze is not None:
                perm = forze.config.get('settings', {}).get('allow_desktop_shortcuts', None)
            else:
                # best-effort: try to read a nearby config file if present
                try:
                    cfg_path = Path(__file__).parent.parent / 'forzeos_config.json'
                    if cfg_path.exists():
                        with open(cfg_path, 'r', encoding='utf-8') as f:
                            cfg = json.load(f)
                            perm = cfg.get('settings', {}).get('allow_desktop_shortcuts', None)
                except Exception:
                    perm = None
        except Exception:
            perm = None

        # If explicitly denied, stop
        if perm is False:
            return False

        desktop = _get_windows_desktop_path()
        shortcut_file = desktop / f"{name}.lnk"

        # Helper to determine target and icon (reuse existing logic)
        try:
            if getattr(sys, 'frozen', False):
                target = Path(sys.executable).resolve()
            else:
                target = Path(sys.argv[0]).resolve()
        except Exception:
            target = Path.cwd()
            icon = None
        if icon_path:
            icon = Path(icon_path)
        else:
            try:
                cand = Path(__file__).with_name('..').resolve() / 'assets' / 'icons' / 'FORZE_CYBER.png'
                if cand.exists():
                    icon = cand
            except Exception:
                icon = None

        def _create_shortcut():
            ok = create_windows_shortcut(target=target, shortcut_path=shortcut_file, working_dir=target.parent if target.is_file() else None, icon=icon, hotkey=hotkey, description=name, open_in_console=True)
            if ok:
                logger.info('Desktop shortcut created: %s', shortcut_file)
            else:
                logger.warning('Failed to create desktop shortcut: %s', shortcut_file)
            return bool(ok)

        # If already allowed, create and return (use persisted helper that handles existing files)
        if perm is True:
            return create_desktop_shortcut_and_persist(forze, name=name, hotkey=hotkey, icon_path=icon_path)

        # Permission unknown — ask the user and persist choice
        created_root = False
        try:
            root = tk._default_root
            if not root:
                root = tk.Tk()
                root.withdraw()
                created_root = True
        except Exception:
            root = None

        resp = False
        try:
            resp = messagebox.askyesno('Masaüstü Kısayolu', 'ForzeOS masaüstüne bir kısayol oluşturmak istiyor. İzin verilsin mi? (Bu ayarı sonradan Ayarlar uygulamasından değiştirebilirsiniz.)')
        except Exception:
            resp = False

        if created_root and root:
            try:
                root.destroy()
            except Exception:
                pass

        # Persist the user's decision if we have a ForzeOS instance
        try:
            if forze is not None:
                s = forze.config.setdefault('settings', {})
                s['allow_desktop_shortcuts'] = bool(resp)
                try:
                    forze.save_config()
                except Exception:
                    pass
            else:
                try:
                    cfg_path = Path(__file__).parent.parent / 'forzeos_config.json'
                    if cfg_path.exists():
                        with open(cfg_path, 'r', encoding='utf-8') as f:
                            cfg = json.load(f)
                    else:
                        cfg = {}
                    cfg.setdefault('settings', {})['allow_desktop_shortcuts'] = bool(resp)
                    with open(cfg_path, 'w', encoding='utf-8') as f:
                        json.dump(cfg, f, indent=2, ensure_ascii=False)
                except Exception:
                    pass
        except Exception:
            pass

        if not resp:
            return False

        return create_desktop_shortcut_and_persist(forze, name=name, hotkey=hotkey, icon_path=icon_path)
    except Exception:
        logger.exception('ensure_desktop_shortcut_prompt failed')
        return False
    


def create_desktop_shortcut_and_persist(forze, name='ForzeOS', hotkey='Ctrl+Alt+F', icon_path=None):
    """Create a desktop shortcut immediately and persist the permission in
    `forze.config['settings']['allow_desktop_shortcuts'] = True` if successful.

    Returns True on success, False otherwise.
    """
    try:
        if not sys.platform.startswith('win'):
            return False

        # Determine target
        try:
            if getattr(sys, 'frozen', False):
                target = Path(sys.executable).resolve()
            else:
                target = Path(sys.argv[0]).resolve()
        except Exception:
            target = Path.cwd()

        # Determine icon
        icon = None
        if icon_path:
            try:
                icon = Path(icon_path)
            except Exception:
                icon = None
        else:
            try:
                cand = Path(__file__).with_name('..').resolve() / 'assets' / 'icons' / 'FORZE_CYBER.png'
                if cand.exists():
                    icon = cand
            except Exception:
                icon = None

        desktop = _get_windows_desktop_path()
        shortcut_file = desktop / f"{name}.lnk"

        # If already exists, prompt user: Replace / Choose different location / Cancel
        if shortcut_file.exists():
            created_root = False
            try:
                root = tk._default_root
                if not root:
                    root = tk.Tk()
                    root.withdraw()
                    created_root = True
            except Exception:
                root = None

            try:
                msg = f"Masaüstünde '{name}.lnk' zaten var. Üzerine yazmak ister misiniz?\n\n'Evet' = Üzerine yaz, 'Hayır' = Farklı bir isim/konum seç, 'İptal' = vazgeç."
                resp = messagebox.askyesnocancel('Kısayol zaten var', msg)
            except Exception:
                resp = None

            if created_root and root:
                try:
                    root.destroy()
                except Exception:
                    pass

            # Cancel
            if resp is None:
                return False

            # Replace
            if resp is True:
                try:
                    try:
                        shortcut_file.unlink()
                    except Exception:
                        try:
                            os.remove(str(shortcut_file))
                        except Exception:
                            pass
                except Exception:
                    pass
                ok = create_windows_shortcut(target=target, shortcut_path=shortcut_file, working_dir=target.parent if target.is_file() else None, icon=icon, hotkey=hotkey, description=name, open_in_console=True)
                if ok:
                    try:
                        s = forze.config.setdefault('settings', {})
                        s['allow_desktop_shortcuts'] = True
                        try:
                            forze.save_config()
                        except Exception:
                            pass
                    except Exception:
                        pass
                else:
                    try:
                        root = tk._default_root
                        if not root:
                            root = tk.Tk(); root.withdraw(); root.destroy()
                    except Exception:
                        pass
                return bool(ok)

            # Choose different location
            created_root = False
            try:
                root = tk._default_root
                if not root:
                    root = tk.Tk()
                    root.withdraw()
                    created_root = True
            except Exception:
                root = None
            from tkinter import filedialog
            save_path = ''
            try:
                save_path = filedialog.asksaveasfilename(title='Farklı konum seçin', defaultextension='.lnk', filetypes=[('Windows Kısayolu', '*.lnk')], initialdir=str(desktop), initialfile=f"{name}.lnk")
            except Exception:
                save_path = ''
            if created_root and root:
                try:
                    root.destroy()
                except Exception:
                    pass
            if not save_path:
                return False
            chosen = Path(save_path)
            ok = create_windows_shortcut(target=target, shortcut_path=chosen, working_dir=target.parent if target.is_file() else None, icon=icon, hotkey=hotkey, description=name, open_in_console=True)
            if ok:
                try:
                    s = forze.config.setdefault('settings', {})
                    s['allow_desktop_shortcuts'] = True
                    try:
                        forze.save_config()
                    except Exception:
                        pass
                except Exception:
                    pass
            else:
                try:
                    root = tk._default_root
                    if not root:
                        root = tk.Tk(); root.withdraw(); root.destroy()
                    messagebox.showerror('Kısayol oluşturulamadı', 'Kısayol oluşturulurken hata oluştu.')
                except Exception:
                    pass
            return bool(ok)

        # Not existing: create normally
        ok = create_windows_shortcut(target=target, shortcut_path=shortcut_file, working_dir=target.parent if target.is_file() else None, icon=icon, hotkey=hotkey, description=name, open_in_console=True)
        if ok:
            try:
                s = forze.config.setdefault('settings', {})
                s['allow_desktop_shortcuts'] = True
                try:
                    forze.save_config()
                except Exception:
                    pass
            except Exception:
                pass
        else:
            logger.warning('create_desktop_shortcut_and_persist: creation failed')
        return bool(ok)
    except Exception:
        logger.exception('create_desktop_shortcut_and_persist failed')
        return False

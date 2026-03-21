#!/usr/bin/env python3
"""
ForzeOS Market - lightweight application store & developer environment

Features implemented (core MVP):
- Toplevel store window (class ForzeOSMarket)
- Lists apps found under `apps/` and `market_apps/` plus `market_data.json`
- Shows each app as a card with icon, name, description and Open/Edit/Remove buttons
- Integrates `organize_assets.py` as the first tool if present
- Developer tab: simple code editor (open/save/run), Save as App (writes to apps/), live traceback output
- market_data.json persistence for app metadata

This file is intentionally self-contained and can be run standalone or opened
from the main ForzeOS process. When used inside ForzeOS, the Toplevel parent
should be the ForzeOS `root` Tk instance and optionally the ForzeOS instance
can be passed as `forze` to allow tighter integration.
"""
from __future__ import annotations
import os
import json
import subprocess
import traceback
import threading
import sys
import shutil
import ctypes
import logging
import re
import importlib
import importlib.util
import tempfile
import difflib
import time
from functools import lru_cache
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False


MARKET_DATA_FILENAME = 'market_data.json'
# Default apps folder for this market module. Placed next to this file to support
# standalone runs and importing into ForzeOS. This mirrors the secondary
# ForzeMarket helper's `APP_FOLDER` location.
APP_FOLDER = Path(__file__).parent / 'market_apps'

# Default template used for new apps; editable via Template button
MARKET_DEFAULT_TEMPLATE = """#!/usr/bin/env python3
import tkinter as tk

class App:
    def __init__(self, root):
        self.root = tk.Toplevel(root)
        self.root.title('{name}')
        tk.Label(self.root, text='Hello from {name}').pack(padx=20, pady=20)

if __name__ == '__main__':
    r = tk.Tk(); r.withdraw(); App(r); r.mainloop()
"""


class ForzeOSMarket(tk.Toplevel):
    """Application Store + Developer Editor Toplevel.

    parent: tk root or any widget
    forze: optional reference to ForzeOS instance for tighter integration
    """
    def __init__(self, parent, forze=None, base_dir=None):
        # Validate parent
        if not hasattr(parent, 'winfo_toplevel'):
            raise TypeError("Parent must be a tkinter widget")
            
        super().__init__(parent)
        
        # Store parameters
        self.parent = parent
        self.forze = forze
        self._base_dir = base_dir
        
        # Window management setup
        self.title('ForzeOS Market')
        self.geometry('1000x700')
        self.minsize(800, 500)
        
        # Configure window for proper minimize/maximize
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # Set up window states for taskbar integration
        if sys.platform.startswith('win'):
            self.attributes('-toolwindow', False)  # Allow minimize/maximize
            self.wm_overrideredirect(False)  # Show standard window decorations
            
        # If we're running inside ForzeOS, adopt its visual theme but DO NOT
        # register the window yet. Registration (and taskbar button creation)
        # will happen when the window actually maps (<Map>), avoiding
        # premature taskbar entries or style races.
        if self.forze:
            try:
                if hasattr(self.forze, 'apply_theme'):
                    self.forze.apply_theme(self)
            except Exception as e:
                print(f"ForzeOS integration error: {e}")
                
        # Bind standard window events
        self.bind('<Map>', self._on_map)
        self.bind('<Unmap>', self._on_unmap)
        
        # Ensure app folder exists
        APP_FOLDER.mkdir(parents=True, exist_ok=True)
        
        # Load/create config
        self.config = {
            'apps': [],
            'recent': [],
            'installed': set()
        }

        # --- Setup base attributes ---
        self.parent = parent
        self.forze = forze
        from pathlib import Path
        import os
        self.base_dir = Path(base_dir or (os.path.dirname(__file__) if '__file__' in globals() else os.getcwd()))
        self.title('ForzeOS Market')
        self.geometry('1000x700')
        self.minsize(800, 500)

        try:
            # If we're embedded inside ForzeOS (forze provided) we DO NOT
            # make the Toplevel transient; embedding host wants to manage
            # taskbar/button registration itself. Only make this transient
            # when running standalone (no host integration).
            if not self.forze:
                self.transient(parent)
        except Exception:
            pass

        # state
        self.market_data_path = self.base_dir / MARKET_DATA_FILENAME
        self.apps_dirs = [self.base_dir / 'apps', self.base_dir / 'market_apps']
        for d in self.apps_dirs:
            d.mkdir(parents=True, exist_ok=True)

        self.icon_cache = {}

        # UI layout
        self._build_ui()
        self.load_market_data()
        self.refresh_app_list()

    # ---------------- UI ----------------
    def _build_ui(self):
        # Top bar with search and actions
        top = ttk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=8, pady=6)

        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(top, textvariable=self.search_var)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,8))
        search_entry.bind('<KeyRelease>', lambda e: self.refresh_app_list())

        ttk.Button(top, text='Refresh', command=self.refresh_app_list).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text='Settings', command=self._open_settings).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text='New App', command=self._new_app_wizard).pack(side=tk.LEFT, padx=4)
        # Run as Tool: open recognized tool (organize_assets) in editor and run
        try:
            self.run_tool_btn = ttk.Button(top, text='Run as Tool', command=self.run_as_tool)
            self.run_tool_btn.pack(side=tk.LEFT, padx=4)
        except Exception:
            self.run_tool_btn = None

        # Main splitter: left categories, center content, right details/editor stack
        main_pane = ttk.Frame(self)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)

        # left categories
        left = ttk.Frame(main_pane, width=160)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0,8))
        left.pack_propagate(False)

        ttk.Label(left, text='Categories', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(2,6))
        self.cat_list = tk.Listbox(left, height=12)
        for c in ['All', 'Tools', 'Games', 'Utilities', 'Installed', 'Developer']:
            self.cat_list.insert(tk.END, c)
        self.cat_list.selection_set(0)
        self.cat_list.pack(fill=tk.Y, expand=True)
        self.cat_list.bind('<<ListboxSelect>>', lambda e: self.refresh_app_list())

        # center: app cards scroller
        center = ttk.Frame(main_pane)
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(center, borderwidth=0)
        self.cards_frame = ttk.Frame(self.canvas)
        vscroll = ttk.Scrollbar(center, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vscroll.set)

        vscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.cards_frame, anchor='nw')

        def on_config(e):
            if self.canvas.winfo_exists():
                self.canvas.configure(scrollregion=self.canvas.bbox('all'))
                
        def on_resize(e):
            if self.canvas.winfo_exists():
                self.canvas.itemconfig(self.canvas_window, width=e.width)
                
        self.cards_frame.bind('<Configure>', on_config)
        self.canvas.bind('<Configure>', on_resize)

        # right: tabs for details and developer editor
        # make it wider so developer tools fit
        right = ttk.Notebook(main_pane, width=480)
        right.pack(side=tk.LEFT, fill=tk.BOTH, padx=(8,0))

        # details tab
        self.detail_tab = ttk.Frame(right)
        right.add(self.detail_tab, text='Details')
        self.detail_text = tk.Text(self.detail_tab, wrap='word', height=20)
        self.detail_text.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.detail_text.configure(state=tk.DISABLED)

        # developer tab
        self.dev_tab = ttk.Frame(right)
        right.add(self.dev_tab, text='Developer')
        self._build_dev_tab(self.dev_tab)

    def _build_dev_tab(self, parent):
        # Toolbar: use a horizontally scrollable toolbar so buttons never overflow
        toolbar_outer = ttk.Frame(parent)
        toolbar_outer.pack(side=tk.TOP, fill=tk.X, padx=6, pady=4)
        toolbar_canvas = tk.Canvas(toolbar_outer, height=34)
        toolbar_canvas.pack(side=tk.LEFT, fill=tk.X, expand=True)
        toolbar_hsb = ttk.Scrollbar(toolbar_outer, orient='horizontal', command=toolbar_canvas.xview)
        toolbar_hsb.pack(side=tk.BOTTOM, fill=tk.X)
        toolbar_canvas.configure(xscrollcommand=toolbar_hsb.set)
        toolbar_inner = ttk.Frame(toolbar_canvas)
        toolbar_canvas.create_window((0,0), window=toolbar_inner, anchor='nw')

        def _on_toolbar_config(e):
            try:
                toolbar_canvas.configure(scrollregion=toolbar_canvas.bbox('all'))
            except Exception:
                pass
        toolbar_inner.bind('<Configure>', _on_toolbar_config)

        # Buttons
        ttk.Button(toolbar_inner, text='Open', command=self.dev_open_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar_inner, text='Save', command=self.dev_save_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar_inner, text='Save as App', command=self.dev_save_as_app).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar_inner, text='Run', command=self.dev_run_code).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar_inner, text='Template', command=self._open_settings).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar_inner, text='Open in Host Editor', command=self.open_in_host_editor).pack(side=tk.LEFT, padx=2)

        # Use a PanedWindow so the code editor and output area are resizable vertically
        pw = ttk.Panedwindow(parent, orient=tk.VERTICAL)
        pw.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0,6))

        # Code editor
        editor_frame = ttk.Frame(pw)
        self.dev_filename = None
        self.dev_text = tk.Text(editor_frame, wrap='none')
        self.dev_text.pack(fill=tk.BOTH, expand=True)
        pw.add(editor_frame, weight=3)

        # simple traceback/output area
        out_frame = ttk.Frame(pw)
        ttk.Label(out_frame, text='Output / Debug').pack(anchor='w')
        self.dev_output = tk.Text(out_frame, wrap='word', height=10, bg='#111', fg='#eee')
        self.dev_output.pack(fill=tk.BOTH, expand=True)
        pw.add(out_frame, weight=1)

    # ---------------- Data ----------------
    def load_market_data(self):
        self.market_data = {}
        try:
            if self.market_data_path.exists():
                with open(self.market_data_path, 'r', encoding='utf-8') as f:
                    self.market_data = json.load(f)
        except Exception:
            self.market_data = {}
        # ensure template key exists
        try:
            if 'template' not in self.market_data:
                self.market_data.setdefault('template', MARKET_DEFAULT_TEMPLATE)
        except Exception:
            pass

    def save_market_data(self):
        try:
            with open(self.market_data_path, 'w', encoding='utf-8') as f:
                json.dump(self.market_data, f, indent=2)
        except Exception:
            pass

    def discover_apps(self):
        """Return list of app dicts with keys: name, path, icon, desc
        Uses a simple in-memory cache to avoid repeated disk scans when
        called frequently (refresh_app_list will clear cache when needed)."""
        apps = []
        seen = set()
        try:
            # cached version for small delay
            now = time.time()
            if hasattr(self, '_apps_cache'):
                cached, ts = self._apps_cache
                if now - ts < 1.0:
                    return list(cached)
        except Exception:
            pass

        # First, include explicit market_data entries
        try:
            for k, v in (self.market_data.get('apps') or {}).items():
                p = v.get('path')
                if not p:
                    continue
                full = os.path.join(self.base_dir, p) if not os.path.isabs(p) else p
                apps.append({'name': k, 'path': full, 'icon': v.get('icon'), 'desc': v.get('desc', '')})
                seen.add(k.lower())
        except Exception:
            pass

        # Next, scan apps directories for .py files
        for d in self.apps_dirs:
            try:
                for p in sorted(d.glob('*.py')):
                    name = p.stem
                    if name.lower() in seen:
                        continue
                    apps.append({'name': name, 'path': str(p), 'icon': None, 'desc': ''})
                    seen.add(name.lower())
            except Exception:
                pass

        # Ensure organize_assets.py appears first if present near market
        try:
            org_path = self.base_dir / 'tools' / 'organize_assets.py'
            if not org_path.exists():
                org_path = self.base_dir / 'organize_assets.py'
            if org_path.exists():
                apps.insert(0, {'name': 'organize_assets', 'path': str(org_path), 'icon': None, 'desc': 'Project modularizer / asset manager'})
        except Exception:
            pass

        return apps
        try:
            # update cache
            self._apps_cache = (list(apps), time.time())
        except Exception:
            pass
        return apps

    # ---------------- UI actions ----------------
    def refresh_app_list(self):
        # clear cards
        for c in self.cards_frame.winfo_children():
            c.destroy()

        # show loading status
        try:
            self._print_output('[ui] Refreshing app list...\n')
            self.status.config(text='Loading...')
        except Exception:
            pass

        apps = self.discover_apps()
        q = self.search_var.get().lower().strip()
        sel_cat = None
        try:
            sel_cat = self.cat_list.get(self.cat_list.curselection())
        except Exception:
            sel_cat = 'All'

        row = 0; col = 0; max_cols = 2
        # Basic filtering + fuzzy matching for typos
        filtered = []
        names = [ (a.get('name') or '').lower() for a in apps ]
        for a in apps:
            name = (a.get('name') or '')
            lname = name.lower()
            if not q or q in lname or q in (a.get('desc') or '').lower():
                filtered.append(a)
        # If query non-empty and no direct matches, use fuzzy finder to suggest close names
        if q and not filtered:
            try:
                candidates = difflib.get_close_matches(q, names, n=6, cutoff=0.6)
                for c in candidates:
                    for a in apps:
                        if (a.get('name') or '').lower() == c and a not in filtered:
                            filtered.append(a)
            except Exception:
                pass

        for a in filtered:
            name = a.get('name') or ''
            if sel_cat and sel_cat != 'All' and sel_cat != 'Installed' and sel_cat != 'Developer':
                # simple category heuristics
                if sel_cat == 'Tools' and 'tool' not in (a.get('desc') or '').lower() and 'tool' not in name.lower():
                    continue
                if sel_cat == 'Games' and 'game' not in (a.get('desc') or '').lower() and 'game' not in name.lower():
                    continue

            frame = ttk.Frame(self.cards_frame, relief=tk.RIDGE, borderwidth=1, padding=8)
            frame.grid(row=row, column=col, padx=8, pady=8, sticky='nsew')
            # icon
            ico_lbl = ttk.Label(frame)
            ico_lbl.pack(side=tk.TOP)
            img = self._get_icon_image(a.get('icon') or a.get('path'))
            if img:
                ico_lbl.config(image=img)
                ico_lbl.image = img

            # title
            ttk.Label(frame, text=name, font=('Segoe UI', 11, 'bold')).pack(anchor='w', pady=(6,0))
            ttk.Label(frame, text=(a.get('desc') or ''), wraplength=240).pack(anchor='w', pady=(4,8))

            btns = ttk.Frame(frame)
            btns.pack(fill=tk.X)
            ttk.Button(btns, text='Open', command=lambda p=a.get('path'): self.open_app(p)).pack(side=tk.LEFT, padx=2)
            ttk.Button(btns, text='Edit', command=lambda p=a.get('path'): self.dev_open_path(p)).pack(side=tk.LEFT, padx=2)
            ttk.Button(btns, text='Remove', command=lambda p=a.get('path'), n=name: self.remove_app(p, n)).pack(side=tk.LEFT, padx=2)

            col += 1
            if col >= max_cols:
                col = 0; row += 1
        try:
            self.status.config(text='Ready')
        except Exception:
            pass

    def _get_icon_image(self, candidate):
        if not candidate:
            return None
        try:
            key = str(candidate)
            if key in self.icon_cache:
                return self.icon_cache[key]
            p = Path(candidate)
            if not p.exists():
                # try inside assets
                p2 = self.base_dir / 'assets' / 'market_icons' / (p.name)
                if p2.exists():
                    p = p2
            if p.exists() and PIL_AVAILABLE:
                img = Image.open(p).convert('RGBA')
                img.thumbnail((64,64), Image.Resampling.LANCZOS)
                tkimg = ImageTk.PhotoImage(img)
                self.icon_cache[key] = tkimg
                return tkimg
        except Exception:
            pass
        return None

    def open_app(self, path):
        try:
            if not path:
                return
            if os.path.isdir(path):
                # open folder
                try:
                    if sys.platform.startswith('win'):
                        os.startfile(path)
                        return
                except Exception:
                    pass
            # If this was launched inside ForzeOS instance, prefer using its opener
            if self.forze and hasattr(self.forze, 'open_script'):
                try:
                    self.forze.open_script(path)
                    return
                except Exception:
                    pass

            # fallback: spawn a subprocess running the script
            if path.endswith('.py'):
                subprocess.Popen([sys.executable, path], cwd=os.path.dirname(path))
            else:
                # try open with system
                try:
                    if sys.platform.startswith('win'):
                        os.startfile(path)
                    else:
                        subprocess.Popen(['xdg-open', path])
                except Exception:
                    messagebox.showinfo('Open', f'Cannot open: {path}')
        except Exception as e:
            messagebox.showerror('Error', f'Failed to open app: {e}')

    def dev_open_file(self):
        p = filedialog.askopenfilename(title='Open Python file', filetypes=[('Python','*.py')])
        if p:
            self.dev_open_path(p)

    def dev_open_path(self, path):
        try:
            # Prefer host code editor integration when available
            if self.forze and hasattr(self.forze, 'open_code_editor'):
                try:
                    # host may open an editor window; still load into dev tab too
                    self.forze.open_code_editor(path)
                except Exception:
                    pass
            with open(path, 'r', encoding='utf-8') as f:
                txt = f.read()
            self.dev_text.delete('1.0', tk.END)
            self.dev_text.insert('1.0', txt)
            self.dev_filename = path
            self._show_in_details(f'Editing: {path}')
        except Exception as e:
            messagebox.showerror('Error', f'Could not open file: {e}')

    def dev_save_file(self):
        try:
            if not self.dev_filename:
                return self.dev_save_as()
            with open(self.dev_filename, 'w', encoding='utf-8') as f:
                f.write(self.dev_text.get('1.0', tk.END))
            self._print_output(f'Saved: {self.dev_filename}\n')
        except Exception as e:
            messagebox.showerror('Error', f'Could not save file: {e}')

    def dev_save_as(self):
        p = filedialog.asksaveasfilename(defaultextension='.py', filetypes=[('Python','*.py')])
        if not p:
            return
        self.dev_filename = p
        self.dev_save_file()

    def open_in_host_editor(self):
        """Open the current dev editor file in the host editor if available.
        Falls back to external open. Shows a single warning/message if unavailable.
        """
        if not getattr(self, 'dev_filename', None):
            try:
                messagebox.showwarning('No file', 'No file is loaded in the developer editor')
            except Exception:
                self._print_output('[host editor] no file loaded\n')
            return
        path = self.dev_filename
        try:
            # Prefer host code editor if available
            if self.forze and hasattr(self.forze, 'open_code_editor'):
                try:
                    self.forze.open_code_editor(path)
                    return
                except Exception:
                    pass
            if self.forze and hasattr(self.forze, 'open_script'):
                try:
                    self.forze.open_script(path)
                    return
                except Exception:
                    pass
        except Exception:
            pass

        # Fallback to external open
        try:
            if sys.platform.startswith('win'):
                os.startfile(path)
            else:
                subprocess.Popen(['xdg-open', path])
        except Exception as e:
            try:
                messagebox.showinfo('Open', f'Could not open in host editor: {e}')
            except Exception:
                self._print_output(f'[host editor] not available: {e}\n')

    def dev_save_as_app(self):
        # Save current code into apps/ as new module
        try:
            name = simple_input = None
            try:
                name = simpledialog.askstring('New App', 'Enter app module name (no .py):')
            except Exception:
                name = None
            if not name:
                return
            fname = f"{name}.py"
            dst = self.base_dir / 'apps' / fname
            if dst.exists() and not messagebox.askyesno('Overwrite', f'{dst} exists. Overwrite?'):
                return
            with open(dst, 'w', encoding='utf-8') as f:
                f.write(self.dev_text.get('1.0', tk.END))
            # add market_data entry
            self.market_data.setdefault('apps', {})[name] = {'path': str(dst.relative_to(self.base_dir)), 'desc': 'User added app'}
            self.save_market_data()
            self.refresh_app_list()
            self._print_output(f'App saved: {dst}\n')
        except Exception as e:
            messagebox.showerror('Error', f'Could not save as app: {e}')

    def dev_run_code(self):
        src = self.dev_text.get('1.0', tk.END)
        # Run in a separate thread to avoid blocking UI
        def _run():
            self._print_output('--- Running code ---\n')
            try:
                # Prepare globals and ensure imports are executed first
                glb = {'__name__': '__main__'}
                loc = {}

                # If file has a known filename, add its dir to sys.path so relative imports work
                cwd = None
                try:
                    if self.dev_filename:
                        cwd = os.path.dirname(self.dev_filename)
                        if cwd and cwd not in sys.path:
                            sys.path.insert(0, cwd)
                except Exception:
                    cwd = None

                # Extract import lines and attempt to import them first
                try:
                    imports = []
                    for m in re.finditer(r"^\s*(from\s+[^\n]+|import\s+[^\n]+)", src, flags=re.MULTILINE):
                        line = m.group(1).strip()
                        if line and line not in imports:
                            imports.append(line)
                    for imp in imports:
                        try:
                            # Execute the import line in the globals so names are available
                            exec(imp, glb)
                            self._print_output(f'[import] {imp}\n')
                        except Exception as ie:
                            # report import error but continue — some imports may be optional
                            self._print_output(f'[import error] {imp}: {ie}\n')
                except Exception as e:
                    self._print_output(f'[import extraction error] {e}\n')

                # If code looks like a Tkinter app (creates Tk or mainloop), run it in subprocess
                looks_like_tk = False
                try:
                    lower = src.lower()
                    if 'import tkinter' in lower or 'from tkinter' in lower or '.mainloop(' in lower or 'tkinter.t' in lower or 'tk.' in lower:
                        looks_like_tk = True
                except Exception:
                    looks_like_tk = False

                if looks_like_tk:
                    # write to temp file and run as subprocess to avoid blocking/closing this UI
                    try:
                        tf = tempfile.NamedTemporaryFile('w', delete=False, suffix='.py', encoding='utf-8')
                        tf.write(src)
                        tf.flush(); tf.close()
                        self._print_output(f'[subprocess] launching temporary script {tf.name}\n')
                        p = subprocess.Popen([sys.executable, tf.name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                        out, err = p.communicate()
                        try:
                            if out:
                                self._print_output(out + '\n')
                            if err:
                                self._print_output('--- Error ---\n' + err + '\n')
                        finally:
                            # Attempt to clean up the temporary file
                            try:
                                os.unlink(tf.name)
                                self._print_output(f'[tempfile] removed {tf.name}\n')
                            except Exception:
                                pass
                    except Exception as se:
                        self._print_output(f'[subprocess launch error] {se}\n')
                else:
                    # Execute in-process (non-blocking thread) after imports
                    try:
                        exec(compile(src, '<string>', 'exec'), glb, loc)
                        self._print_output('--- Execution finished ---\n')
                    except Exception:
                        tb = traceback.format_exc()
                        self._print_output(tb)
            except Exception:
                tb = traceback.format_exc()
                self._print_output(tb)

        threading.Thread(target=_run, daemon=True).start()

    def _print_output(self, text: str):
        try:
            self.dev_output.insert('end', text)
            self.dev_output.see('end')
        except Exception:
            pass

    # ---------------- Simple Cart / Checkout ----------------
    def _ensure_cart(self):
        try:
            if not hasattr(self, 'cart'):
                self.cart = []
        except Exception:
            self.cart = []

    def add_to_cart(self, app_entry):
        try:
            self._ensure_cart()
            self.cart.append(app_entry)
            self._print_output(f'[cart] Added {app_entry.get("name") if isinstance(app_entry, dict) else str(app_entry)}\n')
        except Exception:
            pass

    def show_cart(self):
        try:
            self._ensure_cart()
            win = tk.Toplevel(self)
            win.title('Cart / Checkout')
            win.geometry('480x420')
            frame = ttk.Frame(win)
            frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
            lb = tk.Listbox(frame)
            lb.pack(fill=tk.BOTH, expand=True)
            for it in self.cart:
                try:
                    lb.insert(tk.END, it.get('name') if isinstance(it, dict) else str(it))
                except Exception:
                    lb.insert(tk.END, str(it))

            details = ttk.Frame(win)
            details.pack(fill=tk.X, padx=8, pady=6)
            ttk.Label(details, text='Name:').grid(row=0, column=0, sticky='w')
            name_var = tk.StringVar()
            ttk.Entry(details, textvariable=name_var).grid(row=0, column=1, sticky='we')
            ttk.Label(details, text='Email:').grid(row=1, column=0, sticky='w')
            email_var = tk.StringVar()
            ttk.Entry(details, textvariable=email_var).grid(row=1, column=1, sticky='we')
            details.columnconfigure(1, weight=1)

            def _checkout():
                try:
                    if not self.cart:
                        messagebox.showwarning('Cart', 'Cart is empty')
                        return
                    # Minimal single-page checkout: gather name/email and confirm
                    buyer = name_var.get().strip() or 'Customer'
                    email = email_var.get().strip()
                    messagebox.showinfo('Order', f'Order placed for {buyer}\nItems: {len(self.cart)}\nEmail: {email or "(not provided)"}')
                    self.cart = []
                    win.destroy()
                except Exception as e:
                    messagebox.showerror('Checkout error', str(e))

            btns = ttk.Frame(win)
            btns.pack(fill=tk.X, padx=8, pady=6)
            ttk.Button(btns, text='Checkout', command=_checkout).pack(side=tk.RIGHT)
            ttk.Button(btns, text='Close', command=win.destroy).pack(side=tk.RIGHT, padx=6)
        except Exception:
            pass

    def run_as_tool(self):
        """Open organize_assets (if present) in the editor and run it as a tool.

        If ForzeOS host is available and exposes run_script_embedded, use it
        for tighter integration. Otherwise run as subprocess.
        """
        try:
            apps = self.discover_apps()
            path = None
            for a in apps:
                try:
                    pname = a.get('name', '').lower()
                    if 'organize_assets' in pname or a.get('path', '').endswith('organize_assets.py'):
                        path = a.get('path')
                        break
                except Exception:
                    continue
            if not path:
                try:
                    messagebox.showinfo('Run as Tool', 'No organize_assets tool found in Market.')
                except Exception:
                    pass
                return

            # open in dev editor
            try:
                with open(path, 'r', encoding='utf-8') as fh:
                    src = fh.read()
                self.dev_text.delete('1.0', tk.END)
                self.dev_text.insert('1.0', src)
                self.dev_filename = path
                self._print_output(f'Loaded tool: {path}\n')
            except Exception:
                pass

            # run via host if possible
            try:
                if self.forze and hasattr(self.forze, 'run_script_embedded'):
                    try:
                        ok = self.forze.run_script_embedded(path)
                        if ok:
                            self._print_output('Tool executed via host run_script_embedded\n')
                            return
                    except Exception:
                        pass
            except Exception:
                pass

            # fallback: spawn subprocess
            try:
                import subprocess, sys
                subprocess.Popen([sys.executable, path], cwd=os.path.dirname(path))
                self._print_output('Tool launched as subprocess\n')
            except Exception as e:
                self._print_output(f'Failed to run tool: {e}\n')
        except Exception:
            pass

    def remove_app(self, path, name):
        try:
            if not messagebox.askyesno('Remove', f'Remove {name}? This will delete the file.'):
                return
            if os.path.exists(path):
                os.remove(path)
            # remove from market data
            try:
                apps = self.market_data.get('apps', {})
                if name in apps:
                    del apps[name]
                    self.save_market_data()
            except Exception:
                pass
            self.refresh_app_list()
        except Exception as e:
            messagebox.showerror('Error', f'Could not remove: {e}')

    # ---------------- helper dialogs ----------------
    def _open_settings(self):
        messagebox.showinfo('Settings', 'No configurable settings yet.')

    def _new_app_wizard(self):
        # Simple wizard: ask name, create starter template in dev editor
        name = simpledialog.askstring('New App', 'App name (module name, no .py):')
        if not name:
            return
        # allow user-custom template stored in market_data
        try:
            tmpl = (self.market_data.get('template') if hasattr(self, 'market_data') else None) or MARKET_DEFAULT_TEMPLATE
            template = tmpl.format(name=name)
        except Exception:
            template = MARKET_DEFAULT_TEMPLATE.format(name=name)
        self.dev_text.delete('1.0', tk.END)
        self.dev_text.insert('1.0', template)
        self.dev_filename = None

    def _open_settings(self):
        """Open simple settings dialog to edit the new-app template."""
        try:
            win = tk.Toplevel(self)
            win.title('Market Template')
            win.geometry('700x480')
            txt = tk.Text(win, wrap='none')
            txt.pack(fill='both', expand=True)
            current = (self.market_data.get('template') if hasattr(self, 'market_data') else None) or MARKET_DEFAULT_TEMPLATE
            txt.delete('1.0', tk.END)
            txt.insert('1.0', current)

            def _save():
                try:
                    val = txt.get('1.0', 'end-1c')
                    if not hasattr(self, 'market_data'):
                        self.market_data = {}
                    self.market_data['template'] = val
                    try:
                        self.save_market_data()
                    except Exception:
                        pass
                    win.destroy()
                    self._print_output('[settings] Template saved\n')
                except Exception as e:
                    messagebox.showerror('Error', f'Could not save template: {e}')

            b = ttk.Button(win, text='Save Template', command=_save)
            b.pack(pady=6)
        except Exception as e:
            messagebox.showerror('Error', f'Failed to open settings: {e}')

    def _show_in_details(self, text):
        try:
            self.detail_text.configure(state=tk.NORMAL)
            self.detail_text.delete('1.0', tk.END)
            self.detail_text.insert('1.0', text)
            self.detail_text.configure(state=tk.DISABLED)
        except Exception:
            pass
            
    def _on_map(self, event=None):
        """Handle window showing"""
        # When mapped, register with host and request the taskbar button.
        # This mirrors other apps' lifecycle: register/create-button on open/map.
        if self.forze:
            try:
                logger.debug("ForzeOSMarket._on_map: mapped (forze=%s)", bool(self.forze))
                # Prefer the host's register_window API which can atomically
                # register and add a taskbar button when add_button=True.
                icon = None
                try:
                    icon = self.forze.get_app_icon('ForzeOS Market') if hasattr(self.forze, 'get_app_icon') else None
                except Exception:
                    icon = None
                if hasattr(self.forze, 'register_window'):
                    try:
                        self.forze.register_window(self, 'ForzeOS Market', icon=icon, add_button=True)
                    except TypeError:
                        # fallback to older signature
                        self.forze.register_window(self, 'ForzeOS Market', icon=icon)
            except Exception:
                pass

            # Notify host about map event (after registration)
            try:
                if hasattr(self.forze, 'on_window_map'):
                    self.forze.on_window_map(self)
            except Exception:
                pass
            
    def _on_unmap(self, event=None):
        """Handle window hiding"""
        # Notify host the window was hidden/unmapped and mark as minimized so
        # the taskbar state remains consistent (button stays visible).
        if self.forze:
            try:
                logger.debug("ForzeOSMarket._on_unmap: unmapped (forze=%s)", bool(self.forze))
                if hasattr(self.forze, 'on_window_unmap'):
                    self.forze.on_window_unmap(self)
            except Exception:
                pass
            try:
                if hasattr(self.forze, 'minimize_window'):
                    # Keep taskbar button present; host will mark it minimized.
                    self.forze.minimize_window(self)
            except Exception:
                pass
            
    def _on_close(self):
        """Handle window closing"""
        try:
            logger.debug("ForzeOSMarket._on_close: closing window")
            # Unregister from ForzeOS if needed
            if self.forze and hasattr(self.forze, 'unregister_window'):
                self.forze.unregister_window(self)
                
            # Clean up any scheduled callbacks
            for after_id in self.tk.call('after', 'info'):
                try:
                    self.after_cancel(after_id)
                except Exception:
                    pass
                    
            # Destroy the window
            self.destroy()
        except Exception as e:
            print(f"Error closing market window: {e}")
            self.destroy()
            
    def minimize(self):
        """Minimize window to taskbar"""
        self.wm_iconify()
        
    def maximize(self):
        """Maximize window"""
        self.wm_state('zoomed')
        
    def restore(self):
        """Restore window from minimized/maximized state"""
        self.wm_state('normal')


def open_market(host):
    """Convenience function for hosts to open the Market in-process.

    host: ForzeOS instance or root object. Returns the created window-like
    object or None.
    """
    try:
        logger.debug("forze_market.open_market called with host=%s", getattr(host, 'root', host))
    except Exception:
        try:
            logger.debug("forze_market.open_market called")
        except Exception:
            pass
    return run_embedded(host)


if __name__ == '__main__':
    # Standalone run
    root = tk.Tk()
    root.withdraw()
    win = ForzeOSMarket(root)
    win.mainloop()
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Forze OS Market
- Lightweight application marketplace/editor for ForzeOS
- Features:
  - Browse installed market apps (folder: forze_market_apps)
  - Import a .py as an app (copy to apps folder)
  - Edit app source in an embedded code editor, save back
  - Launch apps (runs module in a subprocess)
  - Preloads `organize_assets.py` as a sample tool on first run

Integration:
- ForzeOS can call `ForzeMarket(host_app).open()` to open the market window.
- Market will try to use host_app GUI styles (colors) when available.

Note: launching arbitrary .py is inherently dangerous. This tool is for
developer/desktop use. Some actions may require admin rights (not auto-elevated).
"""

import os, sys, shutil, subprocess, importlib, threading, traceback
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

APP_FOLDER = Path(__file__).parent / 'forze_market_apps'
SAMPLE_TOOL_SRC = Path(__file__).parent.parent / 'tools' / 'organize_assets.py'

class ForzeMarket:
    def __init__(self, host_app=None):
        self.host = host_app
        self.app_folder = APP_FOLDER
        self.app_folder.mkdir(parents=True, exist_ok=True)
        
        # Find root window
        if host_app is not None:
            if hasattr(host_app, 'root'):
                self.root = host_app.root
            elif hasattr(host_app, 'winfo_toplevel'):
                self.root = host_app.winfo_toplevel()
            else:
                self.root = tk.Tk()
                self.root.withdraw()
        else:
            self.root = tk.Tk()
            self.root.withdraw()

        # ensure sample tool present
        try:
            if SAMPLE_TOOL_SRC.exists():
                dst = self.app_folder / SAMPLE_TOOL_SRC.name
                if not dst.exists():
                    shutil.copy2(str(SAMPLE_TOOL_SRC), str(dst))
        except Exception:
            pass

        # GUI elements
        self.win = None
        self.app_listbox = None
        self.code_editor = None
        self.current_path = None

    def open(self):
        if self.win and self.win.winfo_exists():
            self.win.lift()
            self.win.focus_force()
            return
            
        # prefer host styles
        bg = '#ffffff'; fg = '#000000'
        try:
            if self.host and hasattr(self.host, 'colors'):
                bg = self.host.colors.get('bg', bg)
                fg = self.host.colors.get('fg', fg)
        except Exception:
            pass

        self.win = tk.Toplevel(self.root)
        
        # Make it transient and remove from taskbar
        self.win.transient(self.root)
        self.win.attributes('-toolwindow', True)  # Windows-specific
        
        # Try to fix window ownership
        try:
            if sys.platform.startswith('win'):
                import ctypes
                hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id())
                style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
                style = style | 0x00000080  # WS_EX_TOOLWINDOW
                style = style & ~0x00040000  # ~WS_EX_APPWINDOW
                ctypes.windll.user32.SetWindowLongW(hwnd, -20, style)
                
                # Set owner to root window
                if self.root.winfo_exists():
                    owner_id = self.root.winfo_id() 
                    ctypes.windll.user32.SetWindowLongW(hwnd, -8, owner_id)  # GWL_HWNDPARENT
        except Exception:
            pass
        self.win.title('Forze OS Market')
        self.win.geometry('1000x700')
        try:
            self.win.configure(bg=bg)
        except Exception:
            pass

        # layout: left pane list, right pane editor/controls
        left = tk.Frame(self.win, width=260)
        left.pack(side='left', fill='y', padx=8, pady=8)
        right = tk.Frame(self.win)
        right.pack(side='right', fill='both', expand=True, padx=8, pady=8)

        tk.Label(left, text='Market Apps', font=('Arial', 12, 'bold')).pack(anchor='w')
        self.app_listbox = tk.Listbox(left, width=40, height=30)
        self.app_listbox.pack(fill='y', expand=True)
        self.app_listbox.bind('<<ListboxSelect>>', lambda e: self.on_select())

        btn_frame = tk.Frame(left)
        btn_frame.pack(fill='x', pady=6)
        tk.Button(btn_frame, text='Import .py', command=self.import_py).pack(side='left', padx=4)
        tk.Button(btn_frame, text='Refresh', command=self.refresh).pack(side='left', padx=4)
        tk.Button(btn_frame, text='Install to Desktop', command=self.install_to_desktop).pack(side='left', padx=4)

        # Editor toolbar
        tool_frame = tk.Frame(right)
        tool_frame.pack(fill='x')
        tk.Button(tool_frame, text='Open in External', command=self.open_external).pack(side='left', padx=4)
        tk.Button(tool_frame, text='Open in Host Editor', command=self.open_in_host_editor).pack(side='left', padx=4)
        tk.Button(tool_frame, text='Save', command=self.save).pack(side='left', padx=4)
        tk.Button(tool_frame, text='Run', command=self.run_editor).pack(side='left', padx=4)
        tk.Button(tool_frame, text='Launch', command=self.launch_app).pack(side='left', padx=4)
        tk.Button(tool_frame, text='Remove', command=self.remove_app).pack(side='left', padx=4)
        try:
            tk.Button(tool_frame, text='Run as Tool', command=self.run_as_tool).pack(side='left', padx=4)
        except Exception:
            pass

        self.code_editor = scrolledtext.ScrolledText(right, wrap='none', undo=True)
        self.code_editor.pack(fill='both', expand=True)

        # bottom status
        self.status = tk.Label(self.win, text='Ready')
        self.status.pack(fill='x')

        self.refresh()

    def refresh(self):
        self.app_listbox.delete(0, 'end')
        for p in sorted(self.app_folder.glob('*.py')):
            self.app_listbox.insert('end', p.name)
        self.status.config(text=f'Found {len(list(self.app_folder.glob("*.py")))} apps')

    def on_select(self):
        sel = self.app_listbox.curselection()
        if not sel:
            return
        name = self.app_listbox.get(sel[0])
        path = self.app_folder / name
        self.load_file(path)

    def load_file(self, path: Path):
        try:
            text = path.read_text(encoding='utf-8', errors='replace')
            self.code_editor.delete('1.0', 'end')
            self.code_editor.insert('1.0', text)
            self.current_path = path
            self.status.config(text=f'Loaded {path.name}')
        except Exception as e:
            messagebox.showerror('Error', f'Failed to load file: {e}')

    def import_py(self):
        f = filedialog.askopenfilename(title='Select Python file', filetypes=[('Python','*.py')])
        if not f:
            return
        src = Path(f)
        dst = self.app_folder / src.name
        try:
            shutil.copy2(str(src), str(dst))
            self.refresh()
            messagebox.showinfo('Imported', f'Imported {src.name} into Market')
        except Exception as e:
            messagebox.showerror('Import failed', str(e))

    def save(self):
        if not self.current_path:
            messagebox.showwarning('No file', 'Select an app to save to')
            return
        try:
            content = self.code_editor.get('1.0', 'end-1c')
            self.current_path.write_text(content, encoding='utf-8')
            messagebox.showinfo('Saved', f'Saved {self.current_path.name}')
            self.status.config(text=f'Saved {self.current_path.name}')
        except Exception as e:
            messagebox.showerror('Save failed', str(e))

    def open_external(self):
        if not self.current_path:
            messagebox.showwarning('No file', 'Select an app first')
            return
        try:
            # Prefer host integration if available
            try:
                if self.host and hasattr(self.host, 'open_script'):
                    try:
                        self.host.open_script(str(self.current_path))
                        return
                    except Exception:
                        pass
                if self.host and hasattr(self.host, 'run_script_embedded'):
                    try:
                        ok = self.host.run_script_embedded(str(self.current_path))
                        if ok:
                            return
                    except Exception:
                        pass
            except Exception:
                pass

            if sys.platform.startswith('win'):
                os.startfile(str(self.current_path))
            else:
                subprocess.Popen(['xdg-open', str(self.current_path)])
        except Exception as e:
            messagebox.showerror('Open failed', str(e))

    def open_in_host_editor(self):
        """Open the current file in the ForzeOS host editor if available, otherwise fall back to open_external."""
        if not self.current_path:
            messagebox.showwarning('No file', 'Select an app first')
            return
        try:
            # Prefer host code editor if available
            try:
                if self.host and hasattr(self.host, 'open_code_editor'):
                    try:
                        self.host.open_code_editor(str(self.current_path))
                        return
                    except Exception:
                        pass
                if self.host and hasattr(self.host, 'open_script'):
                    try:
                        self.host.open_script(str(self.current_path))
                        return
                    except Exception:
                        pass
            except Exception:
                pass

            # Fallback to external open
            return self.open_external()
        except Exception as e:
            messagebox.showerror('Open failed', str(e))

    def run_editor(self):
        """Run the current editor contents in a subprocess without requiring save-to-disk.
        Output (stdout/stderr) is shown in a temporary results window. The temp file
        is removed after execution.
        """
        if not getattr(self, 'code_editor', None):
            try:
                messagebox.showwarning('No editor', 'Editor not available')
            except Exception:
                print('Editor not available')
            return
        content = self.code_editor.get('1.0', 'end-1c')
        if not content.strip():
            try:
                messagebox.showwarning('No code', 'Editor is empty')
            except Exception:
                print('Editor empty')
            return

        import tempfile

        try:
            tf = tempfile.NamedTemporaryFile('w', delete=False, suffix='.py', encoding='utf-8')
            tf.write(content)
            tf.flush(); tf.close()
            # Run in background thread to avoid blocking UI
            def _run():
                try:
                    p = subprocess.Popen([sys.executable, tf.name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    out, err = p.communicate()
                    # Show output in a results window on main thread
                    def _show():
                        try:
                            w = tk.Toplevel(self.win)
                            w.title(f'Run Output - {Path(tf.name).name}')
                            txt = scrolledtext.ScrolledText(w, wrap='none')
                            txt.pack(fill='both', expand=True)
                            if out:
                                txt.insert('end', out + '\n')
                            if err:
                                txt.insert('end', '--- STDERR ---\n' + err + '\n')
                        except Exception:
                            print(out, err)
                    try:
                        self.win.after(10, _show)
                    except Exception:
                        _show()
                finally:
                    try:
                        os.unlink(tf.name)
                    except Exception:
                        pass

            threading.Thread(target=_run, daemon=True).start()
        except Exception as e:
            messagebox.showerror('Run failed', str(e))

    def launch_app(self):
        if not self.current_path:
            messagebox.showwarning('No file', 'Select an app first')
            return
        path = str(self.current_path)
        # Launch in background as separate process
        def _run():
            try:
                # Use the same python interpreter
                p = subprocess.Popen([sys.executable, path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                out, err = p.communicate()
                if p.returncode != 0:
                    # show small dialog with error
                    try:
                        messagebox.showerror('App Error', f'App exited with code {p.returncode}\n\n{err}')
                    except Exception:
                        print('App error:', err)
                else:
                    try:
                        messagebox.showinfo('App Finished', f'App finished successfully: {self.current_path.name}')
                    except Exception:
                        print('App finished')
            except Exception as e:
                try:
                    messagebox.showerror('Launch failed', str(e))
                except Exception:
                    print('Launch failed', e)
        threading.Thread(target=_run, daemon=True).start()

    def remove_app(self):
        if not self.current_path:
            messagebox.showwarning('No file', 'Select an app first')
            return
        if not messagebox.askyesno('Confirm', f'Delete {self.current_path.name}?'):
            return
        try:
            self.current_path.unlink()
            self.current_path = None
            self.code_editor.delete('1.0', 'end')
            self.refresh()
        except Exception as e:
            messagebox.showerror('Delete failed', str(e))

    def install_to_desktop(self):
        # For integration: create a lightweight desktop shortcut by copying the file to a 'market_installed' dir
        try:
            if not self.current_path:
                messagebox.showwarning('No file', 'Select an app first')
                return
            desktop_dir = Path.home() / 'ForzeOS_Market_Installed'
            desktop_dir.mkdir(parents=True, exist_ok=True)
            dst = desktop_dir / self.current_path.name
            shutil.copy2(str(self.current_path), str(dst))
            messagebox.showinfo('Installed', f'Installed {self.current_path.name} to {dst}')
            # Optionally integrate with host: if host provides add_desktop_icon, call it
            try:
                if self.host and hasattr(self.host, 'create_desktop_icon'):
                    # create a callback that will call the module when clicked
                    cb = lambda p=dst: subprocess.Popen([sys.executable, str(p)])
                    self.host.create_desktop_icon(self.current_path.stem, cb, 100, 100, icon_path=None, ignore_saved=True)
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror('Install failed', str(e))

    def run_as_tool(self):
        if not self.current_path:
            messagebox.showwarning('No file', 'Select an app first')
            return
        path = str(self.current_path)
        # prefer host embedded runner
        try:
            if self.host and hasattr(self.host, 'run_script_embedded'):
                try:
                    ok = self.host.run_script_embedded(path)
                    if ok:
                        try:
                            messagebox.showinfo('Run', f'Ran {os.path.basename(path)} via host embedded runner')
                        except Exception:
                            pass
                        return
                except Exception:
                    pass
        except Exception:
            pass


def run_embedded(host):
    """Open the Market embedded inside the given ForzeOS `host`.

    Prefer the ForzeOS-provided ForzeOSMarket class (which registers on <Map>)
    and instantiate it with the host root so it behaves like other apps.
    If that class is not available, fall back to the ForzeMarket wrapper.
    Returns the window-like object created or None on failure.
    """
    try:
        logger.debug("forze_market.run_embedded: host=%s", getattr(host, 'root', host) if host is not None else None)
        # Prefer the newer ForzeOSMarket Toplevel class (same module)
        if 'ForzeOSMarket' in globals():
            try:
                # instantiate using host.root as parent so the Toplevel is attached
                win = ForzeOSMarket(getattr(host, 'root', None) or host, host)
                logger.debug("forze_market.run_embedded: created ForzeOSMarket win=%s", getattr(win, 'winfo_exists', lambda: False)())
                return win
            except Exception:
                logger.exception('forze_market.run_embedded: ForzeOSMarket instantiation failed')
                pass

        # Fallback: use the simpler ForzeMarket helper
        if 'ForzeMarket' in globals():
            try:
                fm = ForzeMarket(host)
                fm.open()
                logger.debug('forze_market.run_embedded: opened ForzeMarket wrapper')
                return fm
            except Exception:
                logger.exception('forze_market.run_embedded: ForzeMarket fallback failed')
                pass

        print('forze_market.run_embedded: could not create embedded market UI')
        return None
    except Exception as e:
        try:
            print('forze_market.run_embedded error:', e)
        except Exception:
            pass
        return None

        # fallback: subprocess
        try:
            subprocess.Popen([sys.executable, path], cwd=os.path.dirname(path))
            try:
                messagebox.showinfo('Run', f'Launched {os.path.basename(path)}')
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror('Run failed', str(e))


# Small self-test when run directly
if __name__ == '__main__':
    root = tk.Tk(); root.withdraw()
    fm = ForzeMarket()
    fm.open()
    root.mainloop()

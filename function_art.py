import json
import math
import time
import tkinter as tk
from tkinter import Toplevel, Frame, Label, Entry, Button, Scale, Checkbutton, IntVar, filedialog, HORIZONTAL
try:
    import numpy as _np
    _NUMPY = True
except Exception:
    _np = None
    _NUMPY = False

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageChops, ImageTk, ImageEnhance, ImageOps
    _PIL = True
except Exception:
    Image = ImageDraw = ImageFilter = ImageChops = ImageTk = ImageEnhance = ImageOps = None
    _PIL = False


class FunctionArtWindow:
    """Function ART window: plot parametric function y=f(t) progressively.

    Usage: FunctionArtWindow(master, host=None, notify=None)
    - master: tk root
    - host: optional ForzeOS host object (for theme/config)
    - notify: callable(msg:str) to show errors/messages (companion._speak_and_reply)
    """

    FILE_VERSION = 1

    def __init__(self, master, host=None, notify=None, initial_expr: str = None):
        self.master = master
        self.host = host
        self.notify = notify or (lambda m: None)

        self.win = Toplevel(master)
        self.win.title('Function ART')
        try:
            self.win.transient(master)
        except Exception:
            pass
        self.win.geometry('760x520')

        # styling - try to inherit a dark mode from host if available
        try:
            cfg = getattr(host, 'config', {}) if host else {}
            dark = bool(cfg.get('settings', {}).get('dark_mode', False))
        except Exception:
            dark = False
        bg = '#1e1e1e' if dark else '#ffffff'
        fg = '#ddd' if dark else '#000'

        container = Frame(self.win, bg=bg)
        container.pack(fill='both', expand=True)

        # Top area: function zone + controls
        top = Frame(container, bg=bg)
        top.pack(fill='x', padx=8, pady=6)

        Label(top, text='Function Zone (multiple layers supported)', bg=bg, fg=fg).pack(side='left')
        # multiline editing area for expressions / layers
        self.func_text = tk.Text(top, height=2, bg='#111111' if dark else '#f7f7f7', fg=fg, wrap='none', font=('Courier New', 10))
        default_expr = 'layer1{math.cos(t); math.sin(t)}\nlayer2{0.6*math.cos(3*t); 0.6*math.sin(3*t)}'
        try:
            if initial_expr:
                default_expr = initial_expr
        except Exception:
            pass
        self.func_text.insert('1.0', default_expr)
        self.func_text.pack(side='left', fill='x', expand=True, padx=6)

        # FX and controls
        ctrl_frame = Frame(top, bg=bg)
        ctrl_frame.pack(side='right')

        self.samples_scale = Scale(ctrl_frame, from_=100, to=8000, orient=HORIZONTAL, label='Samples', length=220)
        self.samples_scale.set(1500)
        self.samples_scale.pack(side='top', padx=6, pady=2)

        self.draw_btn = Button(ctrl_frame, text='Draw / Refresh', command=lambda: self._schedule_draw(), width=14)
        self.draw_btn.pack(side='top', padx=6, pady=2)

        self.save_btn = Button(ctrl_frame, text='Save .fart', command=self.save_fart)
        self.save_btn.pack(side='top', padx=6, pady=2)

        self.load_btn = Button(ctrl_frame, text='Load .fart', command=self.load_fart)
        self.load_btn.pack(side='top', padx=6, pady=2)

        self.export_btn = Button(ctrl_frame, text='Export PNG/JSON', command=lambda: self.export_png(save_json=True))
        self.export_btn.pack(side='top', padx=6, pady=2)

        # Window state buttons
        # Window state buttons (use instance methods to avoid duplicate closures)
        ws = Frame(ctrl_frame)
        ws.pack(side='top', pady=4)
        tk.Button(ws, text='Minimize', command=lambda: self.win.iconify()).pack(side='left', padx=2)
        self._maximized = False
        def _toggle_maximize_local():
            try:
                if not self._maximized:
                    self.win.state('zoomed')
                else:
                    self.win.state('normal')
                self._maximized = not self._maximized
            except Exception:
                pass
        # bind to instance so other UI code can reuse
        self._toggle_maximize = _toggle_maximize_local
        # expose simple names for legacy code paths
        toggle_maximize = self._toggle_maximize
        tk.Button(ws, text='Maximize', command=self._toggle_maximize).pack(side='left', padx=2)
        self._fullscreen = False
        def _toggle_fullscreen_local():
            try:
                self._fullscreen = not self._fullscreen
                self.win.attributes('-fullscreen', self._fullscreen)
            except Exception:
                pass
        self._toggle_fullscreen = _toggle_fullscreen_local
        toggle_fullscreen = self._toggle_fullscreen
        tk.Button(ws, text='Fullscreen', command=self._toggle_fullscreen).pack(side='left', padx=2)

        # FX panel
        fx_frame = Frame(container, bg=bg)
        fx_frame.pack(fill='x', padx=8, pady=4)
        Label(fx_frame, text='FX: Glow', bg=bg, fg=fg).pack(side='left')
        self.glow_scale = Scale(fx_frame, from_=0.0, to=1.0, resolution=0.01, orient=HORIZONTAL, length=140)
        self.glow_scale.set(0.45)
        self.glow_scale.pack(side='left', padx=6)

        Label(fx_frame, text='Blur', bg=bg, fg=fg).pack(side='left')
        self.blur_scale = Scale(fx_frame, from_=0.0, to=1.0, resolution=0.01, orient=HORIZONTAL, length=140)
        self.blur_scale.set(0.18)
        self.blur_scale.pack(side='left', padx=6)

        Label(fx_frame, text='Noise', bg=bg, fg=fg).pack(side='left')
        self.noise_scale = Scale(fx_frame, from_=0.0, to=0.1, resolution=0.005, orient=HORIZONTAL, length=120)
        self.noise_scale.set(0.02)
        self.noise_scale.pack(side='left', padx=6)

        # palette & blend
        self.palette_var = tk.StringVar(value='plasma')
        palettes = ['magma', 'plasma', 'viridis', 'oceanic', 'neon', 'pastel']
        tk.OptionMenu(fx_frame, self.palette_var, *palettes).pack(side='left', padx=6)

        self.blend_var = tk.StringVar(value='normal')
        tk.OptionMenu(fx_frame, self.blend_var, 'normal', 'add', 'multiply', 'screen', 'overlay').pack(side='left', padx=6)

        self.gradient_var = IntVar(value=1)
        Checkbutton(fx_frame, text='Gradient stroke', variable=self.gradient_var, bg=bg, fg=fg).pack(side='left', padx=6)

        Label(fx_frame, text='Seed', bg=bg, fg=fg).pack(side='left')
        self.seed_entry = Entry(fx_frame, width=6)
        self.seed_entry.insert(0, '42')
        self.seed_entry.pack(side='left', padx=4)

        # Template buttons for quick shapes
        tpl_frame = Frame(container, bg=bg)
        tpl_frame.pack(fill='x', padx=8, pady=4)
        def add_template(expr, set_parametric=False):
            try:
                # insert template into the Function Zone (append or replace selection)
                try:
                    sel = self.func_text.tag_ranges('sel')
                    if sel:
                        self.func_text.delete(sel[0], sel[1])
                        self.func_text.insert(sel[0], expr)
                    else:
                        # append on new line
                        self.func_text.insert('end', '\n' + expr)
                except Exception:
                    self.func_text.insert('end', '\n' + expr)
                # draw immediately for quick preview
                try:
                    self._schedule_draw()
                except Exception:
                    pass
            except Exception:
                pass

        Button(tpl_frame, text='Sin', command=lambda: add_template('math.sin(t)')).pack(side='left', padx=4)
        Button(tpl_frame, text='Circle', command=lambda: add_template('math.cos(t); math.sin(t)', True)).pack(side='left', padx=4)
        Button(tpl_frame, text='Lissajous', command=lambda: add_template('math.cos(3*t); math.sin(4*t)', True)).pack(side='left', padx=4)
        Button(tpl_frame, text='Spiral', command=lambda: add_template('t*math.cos(t); t*math.sin(t)', True)).pack(side='left', padx=4)
        Button(tpl_frame, text='Heart', command=lambda: add_template('16*math.sin(t)**3; 13*math.cos(t)-5*math.cos(2*t)-2*math.cos(3*t)-math.cos(4*t)', True)).pack(side='left', padx=4)

        # Click-to-open full editor for the Function Zone
        def open_full_editor(event=None):
            try:
                ed = tk.Toplevel(self.win)
                ed.title('Function Zone - Full Editor')
                ed.geometry('1000x600')
                # Large text area
                big = tk.Text(ed, font=('Courier New', 12))
                big.pack(fill='both', expand=True)
                big.insert('1.0', self.func_text.get('1.0','end'))

                # helper buttons
                hb = tk.Frame(ed)
                hb.pack(fill='x')
                def insert_snip(s):
                    big.insert('insert', s)
                tk.Button(hb, text='Insert Circle', command=lambda: insert_snip('math.cos(t); math.sin(t)')).pack(side='left')
                tk.Button(hb, text='Insert Lissajous', command=lambda: insert_snip('math.cos(3*t); math.sin(4*t)')).pack(side='left')
                tk.Button(hb, text='Insert Spiral', command=lambda: insert_snip('t*math.cos(t); t*math.sin(t)')).pack(side='left')
                tk.Button(hb, text='Insert Butterfly', command=lambda: insert_snip('math.sin(t)*(math.exp(math.cos(t))-2*math.cos(4*t)-(math.sin(t/12))**5); math.cos(t)*(math.exp(math.cos(t))-2*math.cos(4*t)-(math.sin(t/12))**5)')).pack(side='left')
                def apply_and_close():
                    try:
                        txt = big.get('1.0','end')
                        self.func_text.delete('1.0','end')
                        self.func_text.insert('1.0', txt)
                        # schedule a safe redraw
                        try:
                            self._schedule_draw()
                        except Exception:
                            pass
                    finally:
                        ed.destroy()
                tk.Button(hb, text='Apply & Close', command=apply_and_close).pack(side='right')
                tk.Button(hb, text='Cancel', command=ed.destroy).pack(side='right')
            except Exception:
                pass

        self.func_text.bind('<Double-Button-1>', open_full_editor)
        # also provide a small helper button to open full editor
        tk.Button(tpl_frame, text='Open Editor', command=open_full_editor).pack(side='left', padx=6)

        # Help / usage area
        help_frame = Frame(container, bg=bg)
        help_frame.pack(fill='x', padx=8, pady=4)
        help_txt = tk.Text(help_frame, height=4, bg=bg, fg=fg)
        help_txt.pack(fill='x')
        help_txt.insert('end', 'Kullanım: Her satır bir katman. Örnek:\nlayerName{expr} veya sadece expr. Parametrik için x(t);y(t). Komutlar: /draw /newlayer /palette /fx /export /saveart /loadart')
        help_txt.config(state='disabled')

        # canvas area (PIL-backed)
        # split canvas + layer panel
        main_frame = Frame(container, bg=bg)
        main_frame.pack(fill='both', expand=True, padx=8, pady=6)

        self.canvas = tk.Canvas(main_frame, bg='#000', height=420)
        self.canvas.pack(side='left', fill='both', expand=True)

        # Right-side panel holder (scrollable)
        panel_holder = Frame(main_frame, width=300, bg=bg)
        panel_holder.pack(side='right', fill='y')

        panel_canvas = tk.Canvas(panel_holder, borderwidth=0, highlightthickness=0, bg=bg)
        panel_scroll = tk.Scrollbar(panel_holder, orient='vertical', command=panel_canvas.yview)
        panel_canvas.configure(yscrollcommand=panel_scroll.set)
        panel_scroll.pack(side='right', fill='y')
        panel_canvas.pack(side='left', fill='both', expand=True)

        panel = Frame(panel_canvas, bg=bg)
        panel_canvas.create_window((0,0), window=panel, anchor='nw')

        def _on_panel_config(event=None):
            panel_canvas.configure(scrollregion=panel_canvas.bbox('all'))
        panel.bind('<Configure>', _on_panel_config)

        # mousewheel to scroll
        def _on_mousewheel(event):
            delta = -1 * (event.delta // 120) if hasattr(event, 'delta') else 0
            panel_canvas.yview_scroll(delta, 'units')
        panel_canvas.bind_all('<MouseWheel>', _on_mousewheel)

        # Window controls group
        wgroup = Frame(panel, bg=bg)
        wgroup.pack(fill='x', padx=6, pady=6)
        Label(wgroup, text='Window', bg=bg, fg=fg).pack(anchor='w')
        ws_row = Frame(wgroup, bg=bg)
        ws_row.pack(anchor='w')
        tk.Button(ws_row, text='Minimize', command=lambda: self.win.iconify()).pack(side='left', padx=2, pady=4)
        tk.Button(ws_row, text='Maximize', command=lambda: toggle_maximize()).pack(side='left', padx=2)
        tk.Button(ws_row, text='Fullscreen', command=lambda: toggle_fullscreen()).pack(side='left', padx=2)

        # Layers list
        Label(panel, text='Layers', bg=bg, fg=fg).pack(anchor='nw', padx=6, pady=(8,2))
        self.layer_list = tk.Listbox(panel, height=8)
        self.layer_list.pack(fill='x', padx=6)

        def on_select(evt=None):
            try:
                idxs = self.layer_list.curselection()
                if not idxs:
                    return
                idx = idxs[0]
                ly = self.layers[idx]
                self.alpha_scale.set(ly.alpha)
                self.stroke_scale.set(ly.stroke)
                self.z_spin.delete(0,'end'); self.z_spin.insert(0, str(ly.z))
            except Exception:
                pass
        self.layer_list.bind('<<ListboxSelect>>', on_select)

        # Per-layer controls
        lgroup = Frame(panel, bg=bg)
        lgroup.pack(fill='x', padx=6, pady=6)
        Label(lgroup, text='Alpha', bg=bg, fg=fg).pack(anchor='w')
        self.alpha_scale = Scale(lgroup, from_=0.0, to=1.0, resolution=0.01, orient=HORIZONTAL, length=240)
        self.alpha_scale.set(1.0)
        self.alpha_scale.pack()

        Label(lgroup, text='Stroke', bg=bg, fg=fg).pack(anchor='w')
        self.stroke_scale = Scale(lgroup, from_=1, to=12, orient=HORIZONTAL, length=240)
        self.stroke_scale.set(2)
        self.stroke_scale.pack()

        Label(lgroup, text='Depth (z)', bg=bg, fg=fg).pack(anchor='w')
        self.z_spin = Entry(lgroup, width=6)
        self.z_spin.insert(0, '0')
        self.z_spin.pack()

        def apply_layer_changes():
            try:
                idxs = self.layer_list.curselection()
                if not idxs:
                    return
                idx = idxs[0]
                ly = self.layers[idx]
                ly.alpha = float(self.alpha_scale.get())
                ly.stroke = int(self.stroke_scale.get())
                ly.z = int(self.z_spin.get()) if self.z_spin.get().strip() else 0
                # update Function Zone text from layers
                lines = []
                for L in self.layers:
                    if L.expr_x is not None:
                        expr = f"{L.expr_x}; {L.expr_y}"
                    else:
                        expr = L.expr_y
                    lines.append(f"{L.id}{{{expr}}}")
                self.func_text.delete('1.0','end')
                self.func_text.insert('1.0', '\n'.join(lines))
                self._schedule_draw()
            except Exception:
                pass

        tk.Button(panel, text='Apply to Layer', command=apply_layer_changes).pack(padx=6, pady=8)

        # Background group
        bgroup = Frame(panel, bg=bg)
        bgroup.pack(fill='x', padx=6, pady=6)
        Label(bgroup, text='Background', bg=bg, fg=fg).pack(anchor='w')
        self.bg_color = '#080808'
        def pick_bg():
            try:
                from tkinter import colorchooser
                c = colorchooser.askcolor(initialcolor=self.bg_color)
                if c and c[1]:
                    color = c[1]
                    if isinstance(color, str) and not color.startswith('#'):
                        color = '#' + color
                    self.bg_color = color
                    try:
                        self.canvas.configure(bg=self.bg_color)
                    except Exception:
                        pass
                    # schedule redraw
                    try:
                        self._schedule_draw()
                    except Exception:
                        pass
            except Exception:
                pass
        tk.Button(bgroup, text='Pick Background', command=pick_bg).pack(padx=6, pady=4)

        # image holder (avoid GC) and scheduling
        self._photoimage = None
        self._canvas_image_id = None
        self._draw_job = None
        self._render_lock = False

        # internal
        self._points = []
        self._lines = []
        self._stop = False
        self.layers = []
        self.image_size = (1200, 800)
        self._img = None
        self._random = __import__('random')

    def _safe_compile(self, expr: str):
        """Return a callable f(t) that safely evaluates the expression using only math functions."""
        # Allowed names from math
        allowed = {k: getattr(math, k) for k in dir(math) if not k.startswith('_')}
        # expose the math module itself so expressions like math.sin work
        allowed['math'] = math
        # if numpy is available, allow np alias (optional)
        if _NUMPY:
            allowed['np'] = _np
        # also allow builtins constants
        allowed.update({'abs': abs, 'min': min, 'max': max})

        try:
            code = compile(expr, '<funcart>', 'eval')
        except Exception as e:
            raise ValueError(f'Invalid expression: {e}')

        def f(t):
            local = {'t': t}
            local.update(allowed)
            try:
                # Evaluate expression in restricted globals/locals
                return eval(code, {'__builtins__': None}, local)
            except Exception as e:
                raise

        # quick test
        try:
            _ = f(0.0)
        except Exception as e:
            raise ValueError(f'Error evaluating function at t=0: {e}')
        return f

    # ---------------- Layer & parsing helpers ----------------
    class Layer:
        def __init__(self, id, expr_x=None, expr_y=None, color=(0.0, 0.8, 0.4), alpha=1.0, stroke=2, blend='normal', z=0):
            self.id = id
            self.expr_x = expr_x
            self.expr_y = expr_y
            self.color = color
            self.alpha = alpha
            self.stroke = stroke
            self.blend = blend
            self.z = z

    def parse_function_zone(self, text:str):
        """Parse multiline function zone into Layer objects.
        Supported lines:
          name{expr}  where expr can be x(t);y(t) or single f(t)
          or just expr
        Returns list of Layer instances.
        """
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        layers = []
        idx = 0
        for ln in lines:
            name = f'layer{idx+1}'
            expr = ln
            if '{' in ln and '}' in ln:
                try:
                    name, body = ln.split('{',1)
                    body = body.rsplit('}',1)[0]
                    name = name.strip() or name
                    expr = body.strip()
                except Exception:
                    expr = ln
            # detect parametric
            if ';' in expr:
                parts = expr.split(';')
                expr_x = parts[0].strip()
                expr_y = parts[1].strip() if len(parts)>1 else '0'
            else:
                expr_x = None
                expr_y = expr
            layers.append(self.Layer(name, expr_x=expr_x, expr_y=expr_y))
            idx += 1
        return layers

    def _palette_color(self, palette_name, t, seed=0):
        # simple palette mapping using HSV -> RGB
        # t in [0,1]
        base = {'magma':0.0,'plasma':0.6,'viridis':0.3,'oceanic':0.5,'neon':0.85,'pastel':0.15}
        h = (base.get(palette_name,0.5) + (t*0.3) + ((seed%100)/100.0)) % 1.0
        s = 0.85
        v = 0.9
        import colorsys
        r,g,b = colorsys.hsv_to_rgb(h, s, v)
        return int(r*255), int(g*255), int(b*255)

    def _add_noise(self, img, amount=0.02, seed=42):
        if not _PIL:
            return img
        import numpy as _np
        w,h = img.size
        rnd = _np.random.RandomState(seed)
        noise = (rnd.randn(h,w,1) * 255.0 * amount).astype('int16')
        noise_img = Image.fromarray(_np.clip(noise[:,:,0]+128,0,255).astype('uint8'), mode='L')
        noise_rgb = Image.merge('RGB', (noise_img,noise_img,noise_img))
        return ImageChops.add(img, noise_rgb, scale=1.0, offset=0)

    def _blend_images(self, base, top, mode='normal'):
        if not _PIL:
            return base
        if mode == 'normal':
            return Image.alpha_composite(base.convert('RGBA'), top.convert('RGBA'))
        if mode == 'add':
            return ImageChops.add(base, top)
        if mode == 'multiply':
            return ImageChops.multiply(base, top)
        if mode == 'screen':
            invb = ImageChops.invert(base)
            invt = ImageChops.invert(top)
            return ImageChops.invert(ImageChops.multiply(invb, invt))
        if mode == 'overlay':
            # crude overlay: lighten darks, darken lights
            return ImageChops.overlay(base, top) if hasattr(ImageChops, 'overlay') else ImageChops.screen(base, top)
        return Image.alpha_composite(base.convert('RGBA'), top.convert('RGBA'))

    def _render(self, layers, size=None):
        """Render layers to a PIL Image and return it."""
        if size is None:
            size = self.image_size
        w,h = size
        if not _PIL:
            return None
        # use configured background color
        try:
            bgc = tuple(int(self.bg_color.lstrip('#')[i:i+2],16) for i in (0,2,4))
        except Exception:
            bgc = (8,8,8)
        base = Image.new('RGB', (w,h), bgc)
        seed_str = self.seed_entry.get().strip()
        try:
            seed = int(seed_str)
        except Exception:
            seed = 42
        rng = self._random.Random(seed)

        # compute bounding boxes over all layers to normalize
        all_pts = []
        layer_pts = []
        samples = int(self.samples_scale.get())
        for ly in layers:
            try:
                if ly.expr_x is not None:
                    pts = self._compute_parametric_points(ly.expr_x, ly.expr_y, samples)
                else:
                    pts = self._compute_points(ly.expr_y, samples)
                layer_pts.append(pts)
                all_pts.extend(pts)
            except Exception as e:
                layer_pts.append([])

        if not all_pts:
            return base

        xs = [p[0] for p in all_pts]
        ys = [p[1] for p in all_pts]
        xmin,xmax = min(xs), max(xs)
        ymin,ymax = min(ys), max(ys)
        if xmax==xmin: xmax = xmin+1.0
        if ymax==ymin: ymax = ymin+1.0
        pad = 40
        sx = (w-2*pad)/(xmax-xmin)
        sy = (h-2*pad)/(ymax-ymin)
        s = min(sx, sy)
        cx = pad - xmin*s
        cy = h - pad + ymin*s

        # draw layers in z order
        for idx, pts in enumerate(layer_pts):
            if not pts:
                continue
            layer = layers[idx]
            layer_img = Image.new('RGBA', (w,h), (0,0,0,0))
            draw = ImageDraw.Draw(layer_img)
            color_palette = self.palette_var.get()
            # map color across path
            n = len(pts)
            last = None
            for i,p in enumerate(pts):
                x = p[0]*s + cx
                y = -p[1]*s + cy
                if last is not None:
                    t = i/(n-1) if n>1 else 0.0
                    r,g,b = self._palette_color(color_palette, t, seed)
                    a = int(255 * layer.alpha)
                    stroke = max(1, int(layer.stroke))
                    draw.line((last[0], last[1], x, y), fill=(r,g,b,a), width=stroke)
                last = (x,y)

            # apply blur/glow per layer depending on z
            blur_amount = float(self.blur_scale.get()) * (1.0 + (layer.z*0.1))
            if blur_amount>0:
                layer_img = layer_img.filter(ImageFilter.GaussianBlur(radius=blur_amount*12))
            # apply glow by enhancing brightness and compositing
            glow = float(self.glow_scale.get()) * (0.6 + layer.alpha*0.4)
            if glow>0:
                glow_img = layer_img.copy().filter(ImageFilter.GaussianBlur(radius=blur_amount*8 + glow*6))
                layer_img = ImageChops.add(layer_img, glow_img)

            # blend onto base
            try:
                base = self._blend_images(base, layer_img.convert('RGB'), mode=self.blend_var.get())
            except Exception:
                base = Image.alpha_composite(base.convert('RGBA'), layer_img)

        # add vignette and noise
        try:
            vign = Image.new('L', (w,h), 0)
            import numpy as _np
            xv = _np.linspace(-1,1,w)
            yv = _np.linspace(-1,1,h)
            gridx, gridy = _np.meshgrid(xv, yv)
            dist = _np.sqrt(gridx**2 + gridy**2)
            vign_mask = (_np.clip((dist-0.6)/(1.0-0.6), 0,1) * 255).astype('uint8')
            vign = Image.fromarray(vign_mask, mode='L')
            base = ImageChops.darker(base, ImageOps.colorize(vign, (0,0,0), (8,8,8)))
        except Exception:
            pass

        noise_amount = float(self.noise_scale.get())
        if noise_amount>0:
            try:
                base = self._add_noise(base, amount=noise_amount, seed=seed)
            except Exception:
                pass

        return base

    def _compute_points(self, expr, samples, tmin=0.0, tmax=2 * math.pi, use_fourier=False, harmonics=10):
        f = self._safe_compile(expr)
        n = max(10, int(samples))
        if _NUMPY and use_fourier:
            # sample densely for FFT
            ts = _np.linspace(tmin, tmax, n)
            ys = _np.array([f(float(tt)) for tt in ts], dtype=float)
            # compute DFT and truncate
            coeffs = _np.fft.rfft(ys)
            keep = max(1, int(min(len(coeffs), harmonics)))
            truncated = _np.copy(coeffs)
            truncated[keep:] = 0
            ys_approx = _np.fft.irfft(truncated, n=n)
            pts = list(zip([float(t) for t in ts], [float(y) for y in ys_approx]))
            return pts

        ts = [tmin + (tmax - tmin) * i / (n - 1) for i in range(n)]
        pts = []
        for tt in ts:
            try:
                y = f(float(tt))
            except Exception as e:
                raise ValueError(f'Error evaluating function at t={tt}: {e}')
            pts.append((float(tt), float(y)))
        return pts

    def _compute_parametric_points(self, expr_x: str, expr_y: str, samples, tmin=0.0, tmax=2*math.pi, use_fourier=False):
        fx = self._safe_compile(expr_x)
        fy = self._safe_compile(expr_y)
        n = max(10, int(samples))
        ts = [tmin + (tmax - tmin) * i / (n - 1) for i in range(n)]
        pts = []
        for tt in ts:
            try:
                x = fx(float(tt))
                y = fy(float(tt))
            except Exception as e:
                raise ValueError(f'Error evaluating parametric at t={tt}: {e}')
            pts.append((float(x), float(y)))
        return pts

    def _scale_to_canvas(self, pts):
        if not pts:
            return []
        w = max(10, self.canvas.winfo_width() or 700)
        h = max(10, self.canvas.winfo_height() or 400)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        if xmax - xmin == 0:
            xmax = xmin + 1.0
        if ymax - ymin == 0:
            ymax = ymin + 1.0
        pad = 20
        sx = (w - 2 * pad) / (xmax - xmin)
        sy = (h - 2 * pad) / (ymax - ymin)
        s = min(sx, sy)
        cx = pad - xmin * s
        cy = h - pad + ymin * s
        # transform: x' = x*s + cx ; y' = -y*s + cy
        screen = [(x * s + cx, -y * s + cy) for (x, y) in pts]
        return screen

    def start_draw(self):
        """Render the current Function Zone to the canvas.

        This method is guarded by a simple lock to avoid concurrent runs
        and keeps a reference to PhotoImage on the canvas so the image
        is not garbage-collected.
        """
        full_text = self.func_text.get('1.0', 'end').strip()
        # handle slash commands
        if full_text.startswith('/'):
            line = full_text.splitlines()[0]
            self._handle_command(line)
            return

        # prevent re-entrancy
        if self._render_lock:
            return

        self._render_lock = True
        try:
            # clear previous drawn line items but preserve the image item to avoid
            # losing the PhotoImage reference or invalidating the canvas image id.
            try:
                if getattr(self, '_lines', None):
                    for ln in list(self._lines):
                        try:
                            self.canvas.delete(ln)
                        except Exception:
                            pass
                    self._lines = []
            except Exception:
                pass

            layers = self.parse_function_zone(full_text)

            # preserve current selection
            prev_sel = None
            try:
                cur = self.layer_list.curselection()
                if cur:
                    prev_sel = cur[0]
            except Exception:
                prev_sel = None

            self.layers = layers
            # repopulate listbox minimally
            try:
                self.layer_list.delete(0, 'end')
                for L in self.layers:
                    self.layer_list.insert('end', L.id)
                if prev_sel is not None and prev_sel < self.layer_list.size():
                    self.layer_list.select_set(prev_sel)
            except Exception:
                pass

            # do the heavy PIL render
            img = self._render(layers, size=self.image_size)
            if img is None:
                raise RuntimeError('Rendering not available (Pillow missing)')

            cw = max(200, self.canvas.winfo_width() or 400)
            ch = max(200, self.canvas.winfo_height() or 300)
            disp = img.copy().resize((cw, ch), resample=Image.LANCZOS)
            self._img = img
            self._photoimage = ImageTk.PhotoImage(disp)

            try:
                if getattr(self, '_canvas_image_id', None):
                    try:
                        self.canvas.itemconfig(self._canvas_image_id, image=self._photoimage)
                    except Exception:
                        # stored id may be invalid after earlier operations; reset so we create a new one
                        self._canvas_image_id = None
                if not getattr(self, '_canvas_image_id', None):
                    self._canvas_image_id = self.canvas.create_image(0, 0, anchor='nw', image=self._photoimage)
                # keep a reference on canvas as well to prevent GC
                self.canvas.image = self._photoimage
            except Exception:
                pass

        except Exception as e:
            try:
                self.notify(f'Function ART error: {e}')
            except Exception:
                pass
        finally:
            # unlock after a short period to allow UI to breathe
            try:
                self.win.after(10, lambda: setattr(self, '_render_lock', False))
            except Exception:
                self._render_lock = False

    def _draw_chunk(self, chunk_size=200):
        if self._stop:
            return
        n = len(self._points)
        if n < 2:
            return
        end = min(n, self._draw_index + chunk_size)
        for i in range(self._draw_index, end):
            x0, y0 = self._points[i - 1]
            x1, y1 = self._points[i]
            line = self.canvas.create_line(x0, y0, x1, y1, fill='#00ff88')
            self._lines.append(line)
        self._draw_index = end
        # auto-scroll or refresh
        if self._draw_index < n:
            self.win.after(10, lambda: self._draw_chunk(chunk_size))

    def save_fart(self):
        data = {
            'version': self.FILE_VERSION,
            'text': self.func_text.get('1.0', 'end'),
            'samples': int(self.samples_scale.get()),
            'fx': {
                'glow': float(self.glow_scale.get()),
                'blur': float(self.blur_scale.get()),
                'noise': float(self.noise_scale.get()),
                'palette': self.palette_var.get(),
                'blend': self.blend_var.get(),
                'seed': self.seed_entry.get().strip(),
            }
        }
        fname = filedialog.asksaveasfilename(defaultextension='.fart', filetypes=[('Function ART', '*.fart'), ('JSON', '*.json')])
        if not fname:
            return
        try:
            with open(fname, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            self.notify(f'Saved {fname}')
        except Exception as e:
            self.notify(f'Could not save: {e}')

    def load_fart(self):
        fname = filedialog.askopenfilename(filetypes=[('Function ART', '*.fart;*.json'), ('All', '*.*')])
        if not fname:
            return
        try:
            with open(fname, 'r', encoding='utf-8') as f:
                data = json.load(f)
            text = data.get('text') or data.get('expr') or ''
            samples = int(data.get('samples', 800))
            fx = data.get('fx', {})
            self.func_text.delete('1.0', 'end')
            self.func_text.insert('1.0', text)
            self.samples_scale.set(samples)
            try:
                self.glow_scale.set(float(fx.get('glow', self.glow_scale.get())))
                self.blur_scale.set(float(fx.get('blur', self.blur_scale.get())))
                self.noise_scale.set(float(fx.get('noise', self.noise_scale.get())))
                self.palette_var.set(fx.get('palette', self.palette_var.get()))
                self.blend_var.set(fx.get('blend', self.blend_var.get()))
                self.seed_entry.delete(0,'end'); self.seed_entry.insert(0, str(fx.get('seed','42')))
            except Exception:
                pass
            self._schedule_draw()
            self.notify(f'Loaded {fname}')
        except Exception as e:
            self.notify(f'Could not load file: {e}')

    def export_png(self):
        if not _PIL:
            self.notify('Pillow not available; cannot export PNG.')
            return
        fname = filedialog.asksaveasfilename(defaultextension='.png', filetypes=[('PNG image', '*.png')])
        if not fname:
            return
        try:
            if self._img is None:
                # render at canvas size
                layers = self.layers or self.parse_function_zone(self.func_text.get('1.0','end'))
                self._img = self._render(layers, size=self.image_size)
            self._img.save(fname)
            # also write metadata JSON beside it
            if True:
                meta = {
                    'version': self.FILE_VERSION,
                    'palette': self.palette_var.get(),
                    'blend': self.blend_var.get(),
                    'fx': {
                        'glow': float(self.glow_scale.get()),
                        'blur': float(self.blur_scale.get()),
                        'noise': float(self.noise_scale.get()),
                        'seed': self.seed_entry.get().strip()
                    },
                    'text': self.func_text.get('1.0','end')
                }
                metafn = fname + '.json'
                with open(metafn, 'w', encoding='utf-8') as mf:
                    json.dump(meta, mf, indent=2)
            self.notify(f'Exported PNG: {fname} (meta saved)')
        except Exception as e:
            self.notify(f'Export failed: {e}')

    def _schedule_draw(self, delay=80):
        """Debounced draw scheduler: cancels previous pending draw and schedules a new one."""
        try:
            if getattr(self, '_draw_job', None):
                try:
                    self.win.after_cancel(self._draw_job)
                except Exception:
                    pass
                self._draw_job = None
            # schedule draw: clear job handle then call start_draw
            def _run():
                try:
                    self._draw_job = None
                    self.start_draw()
                except Exception:
                    pass
            self._draw_job = self.win.after(delay, _run)
        except Exception:
            try:
                self.start_draw()
            except Exception:
                pass

    def _handle_command(self, line:str):
        # basic slash command parser
        parts = line.strip().split()
        cmd = parts[0].lstrip('/').lower()
        args = parts[1:]
        if cmd == 'draw':
            self._schedule_draw()
        elif cmd == 'newlayer':
            rest = ' '.join(args)
            cur = self.func_text.get('1.0','end')
            self.func_text.insert('end', '\n' + (rest or 'math.sin(t)'))
            self._schedule_draw()
        elif cmd == 'palette' and args:
            self.palette_var.set(args[0])
            self._schedule_draw()
        elif cmd == 'fx':
            for kv in args:
                if '=' in kv:
                    k,v = kv.split('=',1)
                    try:
                        if k=='glow': self.glow_scale.set(float(v))
                        if k=='blur': self.blur_scale.set(float(v))
                        if k=='noise': self.noise_scale.set(float(v))
                    except Exception:
                        pass
            self._schedule_draw()
        elif cmd == 'export':
            # allow export png or json
            fmt = args[0] if args else 'png'
            self.export_png()
        elif cmd == 'saveart':
            self.save_fart()
        elif cmd == 'loadart':
            self.load_fart()
        else:
            self.notify(f'Unknown command: {line}')

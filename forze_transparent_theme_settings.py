"""Settings window for Transparent Theme feature.
This module is loaded dynamically by ForzeOS System.py when user opens the setting.
Provides a simple Tk window to select a theme JSON, validate, apply, disable, and save
selection into ForzeOS config.
"""
import os
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from modules.ui import transparent_theme as tt
except Exception:
    tt = None


class TransparentThemeSettingsWindow:
    def __init__(self, parent):
        self.parent = parent
        self.win = tk.Toplevel(parent) if parent is not None else tk.Tk()
        self.win.title('Transparent Theme')
        self.win.geometry('520x220')
        frame = ttk.Frame(self.win, padding=12)
        frame.pack(fill='both', expand=True)

        ttk.Label(frame, text='Theme JSON path:').grid(row=0, column=0, sticky='w')
        self.path_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.path_var, width=60).grid(row=1, column=0, columnspan=3, sticky='w')
        ttk.Button(frame, text='Select...', command=self.select_file).grid(row=1, column=3, padx=6)

        self.apply_var = tk.IntVar(value=1)
        ttk.Checkbutton(frame, text='Anında uygula (canlı)', variable=self.apply_var).grid(row=2, column=0, sticky='w')

        btn_apply = ttk.Button(frame, text='Uygula ve Kaydet', command=self.apply_and_save)
        btn_apply.grid(row=4, column=0, pady=12, sticky='w')
        btn_disable = ttk.Button(frame, text='Devre Dışı Bırak', command=self.disable_theme)
        btn_disable.grid(row=4, column=1, pady=12, sticky='w')
        btn_close = ttk.Button(frame, text='Kapat', command=self.win.destroy)
        btn_close.grid(row=4, column=3, pady=12, sticky='e')

        # Fill current from parent config if available
        try:
            cfg = getattr(parent, 'config', {}) if parent is not None else {}
            cur = cfg.get('settings', {}).get('transparent_theme', {})
            if cur and isinstance(cur, dict) and cur.get('theme'):
                self.path_var.set('<applied_from_config>')
        except Exception:
            pass

    def select_file(self):
        p = filedialog.askopenfilename(title='Select theme JSON', filetypes=[('JSON','*.json'),('All','*.*')])
        if p:
            self.path_var.set(p)

    def apply_and_save(self):
        path = self.path_var.get()
        if not path or path.strip() == '':
            messagebox.showerror('Hata', 'Lütfen bir tema dosyası seçin.')
            return
        if tt is None:
            messagebox.showerror('Hata', 'Transparent theme modülü bulunamadı.')
            return
        if not tt.validate_theme_path(path, workspace_root=os.getcwd()):
            messagebox.showerror('Hata', 'Seçilen dosya izin verilen dizin dışında veya mevcut değil.')
            return
        try:
            theme = tt.load_theme(path)
        except Exception as e:
            messagebox.showerror('Hata', f'Tema yüklenemedi: {e}')
            return
        # apply
        try:
            tt.apply_theme(self.parent, theme, live=bool(self.apply_var.get()))
            messagebox.showinfo('Uygulandı', 'Tema başarıyla uygulandı ve konfigürasyona kaydedildi.')
        except Exception as e:
            messagebox.showerror('Hata', f'Tema uygulanamadı: {e}')

    def disable_theme(self):
        if tt is None:
            messagebox.showerror('Hata', 'Transparent theme modülü bulunamadı.')
            return
        try:
            tt.revert_theme(self.parent)
            messagebox.showinfo('Devre Dışı', 'Şeffaf tema devre dışı bırakıldı.')
        except Exception as e:
            messagebox.showerror('Hata', f'Devre dışı bırakılırken hata: {e}')


if __name__ == '__main__':
    root = tk.Tk()
    TransparentThemeSettingsWindow(root)
    root.mainloop()

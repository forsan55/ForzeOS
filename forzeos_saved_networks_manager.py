"""
Saved Networks Manager for ForzeOS
This module provides a non-invasive helper function to open a Saved WiFi Networks manager
window for a running ForzeOS instance.

Call from the main program (ForzeOS instance `app`) as:

    import forzeos_saved_networks_manager as snm
    snm.open_saved_networks_manager(app)

The UI lists saved networks (from `app.config['wifi_saved']`), allows refresh/delete, and
supports revealing passwords (after master password), and changing the WiFi master password
(asks for current master password to re-encrypt existing saved entries).

This module intentionally avoids modifying the main ForzeOS file; it's easy to wire a
button in `open_wifi_settings` to call `open_saved_networks_manager(self)`.
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import base64
import traceback

try:
    from cryptography.fernet import Fernet
    CRYPTO_AVAILABLE = True
except Exception:
    CRYPTO_AVAILABLE = False


def _safe_get_config_dict(app, key):
    d = app.config.get(key)
    if d is None:
        d = {}
        app.config[key] = d
    return d


def open_saved_networks_manager(app):
    """Open a saved networks manager window for the given ForzeOS app instance.

    Features:
    - Lists saved SSIDs
    - Refresh list
    - Delete selected saved network (asks confirmation)
    - Reveal password (prompts for master password if needed; copies to clipboard)
    - Change master password (asks for current master password; re-encrypts saved entries)
    """
    try:
        # Ensure config keys exist
        saved = _safe_get_config_dict(app, 'wifi_saved')
        vault = _safe_get_config_dict(app, 'wifi_vault')

        # Toplevel window
        w = tk.Toplevel(app.root)
        w.title("Saved WiFi Networks")
        w.geometry("620x380")
        w.transient(app.root)
        w.grab_set()

        frame = tk.Frame(w, padx=8, pady=8)
        frame.pack(fill=tk.BOTH, expand=True)

        # Treeview
        cols = ("ssid", "saved", "note")
        tree = ttk.Treeview(frame, columns=cols, show='headings', selectmode='browse')
        tree.heading('ssid', text='SSID')
        tree.heading('saved', text='Saved')
        tree.heading('note', text='Note')
        tree.column('ssid', width=260)
        tree.column('saved', width=80, anchor='center')
        tree.column('note', width=220)
        tree.pack(fill=tk.BOTH, expand=True, side=tk.TOP)

        # Buttons
        btn_frame = tk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(8,0))

        def _populate():
            for r in tree.get_children():
                tree.delete(r)
            saved = app.config.get('wifi_saved', {}) or {}
            vault = app.config.get('wifi_vault', {}) or {}
            for ssid, meta in saved.items():
                note = meta.get('note') if isinstance(meta, dict) else ''
                has_vault = 'yes' if ssid in vault else 'no'
                tree.insert('', 'end', iid=ssid, values=(ssid, has_vault, note or ''))

        def _refresh():
            _populate()

        def _delete_selected():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo('Delete', 'Lütfen silinecek bir kayıt seçin.')
                return
            ssid = sel[0]
            if not messagebox.askyesno('Onay', f"'{ssid}' kaydını silmek istediğine emin misin? This will remove saved password and metadata."):
                return
            try:
                cfg_saved = app.config.get('wifi_saved', {}) or {}
                cfg_vault = app.config.get('wifi_vault', {}) or {}
                if ssid in cfg_saved:
                    cfg_saved.pop(ssid, None)
                if ssid in cfg_vault:
                    cfg_vault.pop(ssid, None)
                app.config['wifi_saved'] = cfg_saved
                app.config['wifi_vault'] = cfg_vault
                # persist
                try:
                    app.save_config()
                except Exception:
                    # best-effort
                    app._append_run_log({'event':'save_config_failed', 'when':repr(ssid)})
                _populate()
                messagebox.showinfo('Silindi', f"'{ssid}' kaydı silindi.")
            except Exception:
                traceback.print_exc()
                messagebox.showerror('Hata', 'Silme sırasında hata oluştu.')

        def _reveal_selected():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo('Reveal', 'Lütfen bir kayıt seçin.')
                return
            ssid = sel[0]
            # Try the app helper first
            try:
                pw = app.wifi_get_saved_password(ssid)
                if pw:
                    # show and copy
                    if messagebox.askyesno('Reveal', f"Password for '{ssid}':\n{pw}\n\nCopy to clipboard?"):
                        app.root.clipboard_clear()
                        app.root.clipboard_append(pw)
                        messagebox.showinfo('Kopyalandı', 'Parola panoya kopyalandı.')
                    return
            except Exception:
                # Fallthrough: prompt for master and try direct vault
                pass

            # If the helper failed/returned None, try manual decryption using master password
            if not CRYPTO_AVAILABLE:
                messagebox.showerror('Eksik kütüphane', 'Reveale izin vermek için cryptography modülü gerekli.')
                return
            stored = app.config.get('wifi_vault', {}) or {}
            enc = stored.get(ssid)
            if not enc:
                messagebox.showinfo('Bulunamadı', 'Bu ağa ait şifre vault içinde bulunamadı.')
                return
            master = simpledialog.askstring('Master Password', 'Master şifreyi girin (masked):', show='*', parent=w)
            if not master:
                return
            try:
                key = app._derive_wifi_key(master)
                f = Fernet(key)
                # stored may be bytes or b64 string
                if isinstance(enc, str):
                    enc_bytes = enc.encode()
                else:
                    enc_bytes = enc
                try:
                    pw = f.decrypt(enc_bytes).decode('utf-8')
                except Exception:
                    # maybe the stored is base64 of token
                    try:
                        pw = f.decrypt(base64.b64decode(enc_bytes)).decode('utf-8')
                    except Exception:
                        raise
                if messagebox.askyesno('Reveal', f"Password for '{ssid}':\n{pw}\n\nCopy to clipboard?"):
                    app.root.clipboard_clear()
                    app.root.clipboard_append(pw)
                    messagebox.showinfo('Kopyalandı', 'Parola panoya kopyalandı.')
            except Exception as e:
                traceback.print_exc()
                messagebox.showerror('Hata', 'Parola açılamadı. Master şifre yanlış olabilir.')

        def _change_master_password():
            # Ask for current master and new master
            if not CRYPTO_AVAILABLE:
                messagebox.showerror('Eksik kütüphane', 'Bu işlem için cryptography modülü gerekli.')
                return
            current = simpledialog.askstring('Current Master', 'Mevcut master şifreyi girin (veya boş bırakın):', show='*', parent=w)
            new = simpledialog.askstring('New Master', 'Yeni master şifreyi girin (masked):', show='*', parent=w)
            if not new:
                return
            confirm = simpledialog.askstring('Confirm', 'Yeni master şifreyi tekrar girin:', show='*', parent=w)
            if new != confirm:
                messagebox.showerror('Hata', 'Yeni master şifreler eşleşmiyor.')
                return
            # Attempt to decrypt all existing vault entries using current master (if any), then re-encrypt using new master
            cfg_vault = app.config.get('wifi_vault', {}) or {}
            if cfg_vault and current is None:
                if not messagebox.askyesno('Uyarı', 'Vault içinde kayıtlar var. Devam etmek için mevcut master şifreyi girmeniz gerekecek. Devam edilsin mi?'):
                    return
            # Decrypt loop
            reencrypted = {}
            for ssid, enc in list(cfg_vault.items()):
                try:
                    # try current helper first
                    # if app.wifi_get_saved_password requires unlocked master, it might fail; so manual attempt
                    key_old = app._derive_wifi_key(current) if current is not None else None
                    f_old = Fernet(key_old) if key_old is not None else None
                    enc_bytes = enc.encode() if isinstance(enc, str) else enc
                    if f_old is not None:
                        try:
                            pw = f_old.decrypt(enc_bytes).decode('utf-8')
                        except Exception:
                            # try base64 decode
                            pw = f_old.decrypt(base64.b64decode(enc_bytes)).decode('utf-8')
                    else:
                        # No current key available; ask user for password per-entry
                        pw = simpledialog.askstring('Entry Password', f"Enter password for '{ssid}' to re-encrypt:", show='*', parent=w)
                        if not pw:
                            raise RuntimeError('Missing password for ' + ssid)
                    # now encrypt with new key
                    key_new = app._derive_wifi_key(new)
                    f_new = Fernet(key_new)
                    new_enc = f_new.encrypt(pw.encode('utf-8'))
                    # store as text
                    reencrypted[ssid] = new_enc.decode('utf-8')
                except Exception:
                    traceback.print_exc()
                    if not messagebox.askyesno('Hata', f"'{ssid}' yeniden şifrelenemedi; atlamak istiyor musunuz? (Evet=Atla)\nDevam edilsin mi?", parent=w):
                        return
            # Persist new master and vault
            try:
                app.wifi_set_master_password(new)
            except Exception:
                # best-effort: still continue
                pass
            # Replace vault entries
            if reencrypted:
                app.config['wifi_vault'] = reencrypted
            try:
                app.save_config()
            except Exception:
                app._append_run_log({'event':'save_config_failed_on_change_master'})
            messagebox.showinfo('Tamam', 'Master şifre ve vault güncellendi (varsa yeniden şifrelenen kayıtlar).')
            _populate()

        # Buttons wiring
        tk.Button(btn_frame, text='Refresh', command=_refresh).pack(side=tk.LEFT, padx=4)
        tk.Button(btn_frame, text='Delete Selected', command=_delete_selected, bg='#ff6666').pack(side=tk.LEFT, padx=4)
        tk.Button(btn_frame, text='Reveal / Copy', command=_reveal_selected).pack(side=tk.LEFT, padx=4)
        tk.Button(btn_frame, text='Change Master Password', command=_change_master_password).pack(side=tk.RIGHT, padx=4)
        tk.Button(btn_frame, text='Close', command=w.destroy).pack(side=tk.RIGHT, padx=4)

        _populate()
        w.wait_window()

    except Exception:
        traceback.print_exc()
        messagebox.showerror('Hata', 'Saved Networks Manager açılamadı.')

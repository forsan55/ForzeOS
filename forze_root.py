# ==========================================
# forze_root.py
# ForzeOS proje kökünü yöneten dosya
# ==========================================

import os
import sys

# Proje kök dizini (ForzeOS System.py hangi klasördeyse)
ROOT = os.path.dirname(os.path.abspath(__file__))

def R(*parts):
    """
    Proje kökünden güvenli path oluşturur.
    Örnek: R("assets", "icons", "terminal.png")
    """
    return os.path.join(ROOT, *parts)

def add_import(rel_path):
    """
    Modülleri Python import yoluna ekler.
    Böylece modüller klasör değiştirsen bile bozulmaz.
    """
    full = R(rel_path)
    if os.path.exists(full) and full not in sys.path:
        sys.path.insert(0, full)
        return True
    return False


# Bu klasörler otomatik olarak import yoluna eklenir
DEFAULT_FOLDERS = [
    "modules",
    "modules/core",
    "modules/apps",
    "modules/ui",
    "external",
    "libs"
]

for folder in DEFAULT_FOLDERS:
    try:
        add_import(folder)
    except:
        pass

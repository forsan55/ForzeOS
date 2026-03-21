# ==========================================
# forze_launcher.py
# ForzeOS başlatıcısı — artık bunu çalıştıracaksın
# ==========================================

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Proje kökü Python yoluna ekleniyor
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# forze_root'u erken yükle
try:
    import forze_root
except:
    pass

# ForzeOS System.py dosyasını import etmeye çalış
import importlib.util

MAIN_FILE = os.path.join(BASE_DIR, "ForzeOS System.py")
spec = importlib.util.spec_from_file_location("forze_main", MAIN_FILE)

if spec is None or spec.loader is None:
    print("ForzeOS System.py bulunamadı!")
    exit()

main_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(main_mod)

# ForzeOS sınıfı varsa çalıştır
ForzeOS = getattr(main_mod, "ForzeOS", None)

if ForzeOS:
    app = ForzeOS()
    if hasattr(app, "run"):
        app.run()
    else:
        print("ForzeOS sınıfında run() fonksiyonu yok!")
else:
    print("ForzeOS sınıfı bulunamadı!")


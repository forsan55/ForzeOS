# ==========================================
# apply_forze_root_patch.py
# ForzeOS System.py dosyasının başına
# FORZE_ROOT_LOADER kodunu otomatik ekler
# ==========================================

import os
import shutil

TARGET = "ForzeOS System.py"
BACKUP = TARGET + ".bak"
MARKER = "# FORZE_ROOT_LOADER"

SNIPPET = f"""
{MARKER}
try:
    from forze_root import R, add_import
    add_import('modules')
    add_import('modules/core')
    add_import('modules/apps')
    add_import('modules/ui')
    add_import('external')
    add_import('libs')
except:
    pass

"""

def main():
    if not os.path.exists(TARGET):
        print("ForzeOS System.py bulunamadı!")
        return

    # Yedek oluştur
    if not os.path.exists(BACKUP):
        shutil.copy2(TARGET, BACKUP)
        print("Yedek oluşturuldu:", BACKUP)
    else:
        print("Yedek zaten var:", BACKUP)

    # Dosyayı oku
    with open(TARGET, "r", encoding="utf-8") as f:
        data = f.read()

    # Eğer marker varsa tekrar eklemeyelim
    if MARKER in data:
        print("FORZE_ROOT_LOADER zaten ekli.")
        return

    # En başa snippet ekle
    new_data = SNIPPET + data

    # Dosyayı yaz
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(new_data)

    print("FORZE_ROOT_LOADER başarıyla enjekte edildi.")

if __name__ == "__main__":
    main()

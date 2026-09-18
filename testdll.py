import ctypes
import os

# DLL dosyanın tam yolunu belirle (DLL adının forze_aggressive_focus.dll olduğunu varsayıyoruz)
dll_path = os.path.abspath("forze_aggressive_focus.dll")

try:
    # 64-bit/32-bit uyumuna dikkat ederek DLL'i yükle
    focus_dll = ctypes.WinDLL(dll_path)
    print("✅ DLL başarıyla yüklendi!")

    # 1. DllRegisterFocusFilter Fonksiyonunu Çağır
    if hasattr(focus_dll, 'DllRegisterFocusFilter'):
        result = focus_dll.DllRegisterFocusFilter()
        print(f"🚀 DllRegisterFocusFilter Sonucu: {result}")
    else:
        print("❌ DllRegisterFocusFilter fonksiyonu DLL içinde bulunamadı!")

    # 2. DllUnregisterFocusFilter Fonksiyonunu Çağır
    if hasattr(focus_dll, 'DllUnregisterFocusFilter'):
        unreg_result = focus_dll.DllUnregisterFocusFilter()
        print(f"🛑 DllUnregisterFocusFilter Sonucu: {unreg_result}")

except Exception as e:
    print(f"❌ DLL yükleme hatası: {e}")


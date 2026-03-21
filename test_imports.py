import importlib

def try_import(name):
    try:
        importlib.import_module(name)
        print(f"{name} imported OK")
    except Exception as e:
        print(f"{name} import error: {e}")

try_import('assistant_ai')
try_import('desktop_companion')

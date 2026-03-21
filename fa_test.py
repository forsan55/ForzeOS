import sys
sys.path.append(r'C:\Users\User\Downloads')
import tkinter as tk
from function_art import FunctionArtWindow

root = tk.Tk()
root.withdraw()
win = FunctionArtWindow(root)
# butterfly template
butter = "math.sin(t)*(math.exp(math.cos(t))-2*math.cos(4*t)-(math.sin(t/12))**5); math.cos(t)*(math.exp(math.cos(t))-2*math.cos(4*t)-(math.sin(t/12))**5)"
win.func_text.delete('1.0','end')
win.func_text.insert('1.0', 'butterfly{' + butter + '}')
try:
    win.start_draw()
    if win._img is not None:
        out = r'C:\Users\User\Downloads\function_art_test_butterfly.png'
        win._img.save(out)
        print('Saved test image to', out)
    else:
        print('No image produced')
except Exception as e:
    import traceback
    traceback.print_exc()
    print('ERROR', e)
finally:
    root.destroy()

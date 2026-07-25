#!/usr/bin/env python3
import tkinter as tk

class App:
    def __init__(self, root):
        self.root = tk.Toplevel(root)
        self.root.title('{name}')
        tk.Label(self.root, text='Hello from {name}').pack(padx=20, pady=20)

if __name__ == '__main__':
    r = tk.Tk(); r.withdraw(); App(r); r.mainloop()



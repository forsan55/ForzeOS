import sys
sys.path.append(r'C:\Users\User\Downloads')
import tkinter as tk
from desktop_companion import DesktopCompanion

class DummyHost:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.config = {'desktop': {}, 'settings': {}}
    def save_config(self):
        print('save_config called')
    def open_chess(self):
        print('host: open_chess')
    def open_music_studio(self):
        print('host: open_music_studio')
    def open_gallery(self):
        print('host: open_gallery')
    def open_file_manager(self, p=None):
        print('host: open_file_manager', p)
    def open_snake(self):
        print('host: open_snake')
    def open_paint(self):
        print('host: open_paint')
    def open_terminal(self):
        print('host: open_terminal')
    def open_video_editor(self):
        print('host: open_video_editor')

host = DummyHost()
comp = DesktopCompanion(host)
comp.install(10,10)
print('host open map keys:', list(comp._host_open_map.keys()))
print('host open map reprs:', {k: getattr(v, '__name__', repr(v)) for k, v in comp._host_open_map.items()})
# test dispatch
comp._process_user_input('asistana open chess')
comp._process_user_input('asistana open music studio')
comp._process_user_input('open gallery')
comp._process_user_input('please open snake')
# process pending Tk events so root.after callbacks run in this test
for _ in range(5):
    host.root.update()
    import time
    time.sleep(0.05)
# test assistant-result detection path: simulate ai returning a string
class FakeAI:
    def execute_command(self, text, session_id=None):
        return True, 'I will open the Gallery for you now.'
comp.ai = FakeAI()
comp._process_user_input('do something')
# process pending Tk events again
for _ in range(5):
    host.root.update()
    import time
    time.sleep(0.05)
print('done')

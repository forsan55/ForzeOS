import threading
import queue
import time
import sys
import os
import math
import logging
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except Exception:
    raise

# Prefer sounddevice + soundfile when available for best cross-platform recording
try:
    import sounddevice as sd
    import numpy as np
    SOUNDDEVICE_AVAILABLE = True
except Exception:
    sd = None
    np = None
    SOUNDDEVICE_AVAILABLE = False

try:
    import soundfile as sf
    SANDFILE_AVAILABLE = True
except Exception:
    sf = None
    SANDFILE_AVAILABLE = False

# Fallback to wave + pyaudio if needed
import wave
try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except Exception:
    pyaudio = None
    PYAUDIO_AVAILABLE = False

# Windows beep for "haptic" feel (soft simulated vibration)
if sys.platform.startswith('win'):
    try:
        import winsound
    except Exception:
        winsound = None
else:
    winsound = None


class AudioSettingsWindow:
    """Advanced microphone tester & recorder.

    Features:
    - Large custom button with press/hold semantics to start monitoring/recording
    - Live level meter with smoothing and sensitivity control
    - Visual "haptic" pulses and optional beep when levels pass threshold
    - Save recording to WAV (soundfile if available, else wave)
    - Fully self-contained and uses background threads for audio capture
    """

    def __init__(self, parent=None):
        self.parent = parent
        self.root = tk.Toplevel(parent) if parent is not None else tk.Tk()
        self.root.title("Audio / Microphone Settings")
        self.root.geometry("640x420")
        self.root.resizable(False, False)

        # State
        self._running = False
        self._recording = False
        self._level_queue = queue.Queue()
        self._buffer = []
        self._samplerate = 44100
        self._channels = 1
        self._sensitivity = 0.6  # 0..1 multiplier
        self._visual_gain = 1.0
        self._stream = None
        self._last_peak = 0.0

        self._build_ui()
        self._poll_visual()

        # Keep a reference to the thread so we can stop it
        self._audio_thread = None

        # Ensure window closes cleanly
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        pad = 12
        frm = ttk.Frame(self.root, padding=pad)
        frm.pack(fill="both", expand=True)

        # Top: title and description
        title = ttk.Label(frm, text="Mic Tester & Recorder", font=(None, 16, "bold"))
        title.pack(anchor="w")

        desc = ttk.Label(frm, text="Press and hold the big button to monitor/record. Adjust sensitivity and visual style below.")
        desc.pack(anchor="w", pady=(0, 8))

        # Middle: big custom button + level meter
        mid = ttk.Frame(frm)
        mid.pack(fill="x", pady=(6, 6))

        self.canvas = tk.Canvas(mid, width=220, height=220, highlightthickness=0)
        self.canvas.grid(row=0, column=0, padx=(0, 18))

        # Draw circular button
        self._btn_circle = self.canvas.create_oval(8, 8, 212, 212, fill="#1e90ff", outline="#0b5ea8", width=4)
        self._btn_text = self.canvas.create_text(110, 110, text="Hold to Talk", fill="white", font=(None, 14, "bold"))

        # Bind press/release to canvas for tactile feeling
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        # Level meter (vertical bars)
        meter_frame = ttk.Frame(mid)
        meter_frame.grid(row=0, column=1, sticky="n")
        self.meter_canvas = tk.Canvas(meter_frame, width=220, height=220, bg="#111111", highlightthickness=1, highlightbackground="#333333")
        self.meter_canvas.pack()

        # Sensitivity slider and options
        bottom = ttk.Frame(frm)
        bottom.pack(fill="x", pady=(10, 0))

        sens_label = ttk.Label(bottom, text="Sensitivity")
        sens_label.grid(row=0, column=0, sticky="w")
        self.sens_scale = ttk.Scale(bottom, from_=0.05, to=3.0, orient="horizontal", command=self._on_sensitivity_change)
        self.sens_scale.set(self._sensitivity)
        self.sens_scale.grid(row=0, column=1, sticky="ew", padx=(8, 12))

        show_peak_btn = ttk.Button(bottom, text="Show Peak", command=self._show_peak_dialog)
        show_peak_btn.grid(row=0, column=2)

        bottom.columnconfigure(1, weight=1)

        # Controls row: Save / Test / Options
        controls = ttk.Frame(frm)
        controls.pack(fill="x", pady=(12, 0))

        self.save_btn = ttk.Button(controls, text="Save Last Recording", command=self._save_recording)
        self.save_btn.pack(side="left")

        self.test_btn = ttk.Button(controls, text="Toggle Live Monitor", command=self._toggle_live_monitor)
        self.test_btn.pack(side="left", padx=(8, 8))

        style_btn = ttk.Button(controls, text="Appearance", command=self._appearance_dialog)
        style_btn.pack(side="right")

        # Visual meter initial bars
        self._meter_bars = []
        self._meter_count = 16
        bar_w = 12
        gap = 2
        for i in range(self._meter_count):
            x0 = 6 + i * (bar_w + gap)
            x1 = x0 + bar_w
            # initial small rect
            rect = self.meter_canvas.create_rectangle(x0, 220 - 6, x1, 220, fill="#66ff66", outline="")
            self._meter_bars.append(rect)

    def _on_sensitivity_change(self, v):
        try:
            self._sensitivity = float(v)
        except Exception:
            pass

    def _show_peak_dialog(self):
        messagebox.showinfo("Peak", f"Last peak level: {self._last_peak:.3f}")

    def _appearance_dialog(self):
        messagebox.showinfo("Appearance", "Appearance options: theme, button color, pulse intensity. (Future)")

    def _on_press(self, event=None):
        # Visual press feedback
        self.canvas.itemconfig(self._btn_circle, fill="#2aa6ff")
        self.canvas.scale(self._btn_circle, 110, 110, 0.98, 0.98)
        self.canvas.update()
        # Start monitoring/recording
        if not self._running:
            self._start_stream(recording=True)
        else:
            # already running - treat as voice-activated toggle
            pass

    def _on_release(self, event=None):
        # Visual release feedback with pulse animation
        self._do_pulse_animation()
        self.canvas.itemconfig(self._btn_circle, fill="#1e90ff")
        self.canvas.scale(self._btn_circle, 110, 110, 1.02, 1.02)
        self.canvas.update()
        # Stop recording if we were recording
        if self._running:
            self._stop_stream()

    def _do_pulse_animation(self):
        # brief scale & color flash to simulate haptic
        orig = self.canvas.itemcget(self._btn_circle, 'fill')
        def anim():
            for c in ("#6fb8ff", "#1e90ff"):
                self.canvas.itemconfig(self._btn_circle, fill=c)
                time.sleep(0.06)
            self.canvas.itemconfig(self._btn_circle, fill=orig)
        threading.Thread(target=anim, daemon=True).start()

    def _toggle_live_monitor(self):
        if self._running:
            self._stop_stream()
        else:
            self._start_stream(recording=False)

    def _start_stream(self, recording=False):
        self._running = True
        self._recording = recording
        self._buffer = []
        if SOUNDDEVICE_AVAILABLE:
            try:
                self._stream = sd.InputStream(samplerate=self._samplerate, channels=self._channels, callback=self._sd_callback)
                self._stream.start()
            except Exception as e:
                messagebox.showerror("Audio Error", f"Failed to start input stream: {e}")
                self._running = False
                return
            # start a thread to collect levels (not necessary but keeps UI responsive)
            self._audio_thread = threading.Thread(target=self._sd_collector, daemon=True)
            self._audio_thread.start()
        elif PYAUDIO_AVAILABLE:
            # fallback: pyaudio capture
            self._p = pyaudio.PyAudio()
            try:
                self._pa_stream = self._p.open(format=pyaudio.paInt16, channels=self._channels, rate=self._samplerate, input=True, frames_per_buffer=1024)
                self._audio_thread = threading.Thread(target=self._pyaudio_collector, daemon=True)
                self._audio_thread.start()
            except Exception as e:
                messagebox.showerror("Audio Error", f"Failed to open pyaudio stream: {e}")
                self._running = False
                return
        else:
            messagebox.showwarning("Missing deps", "Install sounddevice or pyaudio for live mic testing and recording.")
            self._running = False

    def _stop_stream(self):
        self._running = False
        # stop streams safely
        if SOUNDDEVICE_AVAILABLE and getattr(self, '_stream', None) is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if PYAUDIO_AVAILABLE and getattr(self, '_pa_stream', None) is not None:
            try:
                self._pa_stream.stop_stream()
                self._pa_stream.close()
            except Exception:
                pass
            self._pa_stream = None
        # optionally offer to save if we were recording
        if self._recording and self._buffer:
            if messagebox.askyesno("Save Recording", "Save the last recording to file?"):
                self._save_recording()
        self._recording = False

    # sounddevice callback - push rms level + buffer
    def _sd_callback(self, indata, frames, time_info, status):
        if status:
            # push status messages into queue for later
            pass
        arr = indata.copy()
        if self._channels > 1:
            arr = arr.mean(axis=1)
        # compute RMS
        try:
            rms = float(np.sqrt(np.mean(arr.astype(np.float64)**2)))
        except Exception:
            rms = 0.0
        # push level
        try:
            self._level_queue.put_nowait(rms)
        except Exception:
            pass
        # buffer if recording
        if self._recording:
            self._buffer.append(arr.copy())

    def _sd_collector(self):
        # keep running while stream open (level updates handled via callback->queue)
        while self._running:
            time.sleep(0.05)
        # finished

    def _pyaudio_collector(self):
        while self._running:
            try:
                data = self._pa_stream.read(1024, exception_on_overflow=False)
                nums = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0 if np is not None else []
                if self._channels > 1:
                    nums = nums.reshape(-1, self._channels).mean(axis=1)
                rms = float(math.sqrt(float((nums**2).mean()))) if len(nums) else 0.0
                try:
                    self._level_queue.put_nowait(rms)
                except Exception:
                    pass
                if self._recording:
                    self._buffer.append(nums.copy())
            except Exception:
                time.sleep(0.02)

    def _poll_visual(self):
        # Poll queue for levels and update visual meter
        try:
            # drain queue but keep latest
            level = None
            while True:
                level = self._level_queue.get_nowait()
        except Exception:
            # empty
            level = None
        if level is not None:
            # apply sensitivity/gain clamp and smoothing
            lvl = min(1.0, level * self._visual_gain * self._sensitivity * 5.0)
            # simple peak smoothing
            self._last_peak = max(lvl, self._last_peak * 0.85)
            self._update_meter(self._last_peak)
            # simulated haptic/beep when crossing threshold
            if lvl > 0.6:
                # quick visual pulse
                self._haptic_pulse()
        else:
            # decay peak
            self._last_peak = max(0.0, self._last_peak * 0.92)
            self._update_meter(self._last_peak)

        # schedule next poll
        self.root.after(60, self._poll_visual)

    def _update_meter(self, peak):
        # peak in 0..1 -> fill bars
        n_on = int(round(peak * self._meter_count))
        for i, rect in enumerate(self._meter_bars):
            if i < n_on:
                # gradient color
                hue = int(120 - (i / max(1, self._meter_count-1)) * 100)
                # use simple green->yellow->red mapping
                if i < self._meter_count * 0.6:
                    color = "#66ff66"
                elif i < self._meter_count * 0.85:
                    color = "#ffcc33"
                else:
                    color = "#ff4444"
                # compute height
                h = int(6 + (peak * 210) * (1.0 - (i / self._meter_count) * 0.35))
                self.meter_canvas.coords(rect, self.meter_canvas.coords(rect)[0], 220 - h, self.meter_canvas.coords(rect)[2], 220)
                self.meter_canvas.itemconfig(rect, fill=color)
            else:
                # minimal height
                self.meter_canvas.coords(rect, self.meter_canvas.coords(rect)[0], 220 - 6, self.meter_canvas.coords(rect)[2], 220)
                self.meter_canvas.itemconfig(rect, fill="#222222")

    def _haptic_pulse(self):
        # very short visual flash + optional beep
        def p():
            # quick color flash on button
            try:
                self.canvas.itemconfig(self._btn_circle, outline="#ffffff")
                time.sleep(0.04)
                self.canvas.itemconfig(self._btn_circle, outline="#0b5ea8")
            except Exception:
                pass
            if winsound:
                try:
                    winsound.Beep(800, 35)
                except Exception:
                    pass
        threading.Thread(target=p, daemon=True).start()

    def _save_recording(self):
        if not self._buffer:
            messagebox.showinfo("No Data", "No recording data available to save.")
            return
        # stitch buffer robustly and write as PCM16 WAV
        fn = filedialog.asksaveasfilename(defaultextension='.wav', filetypes=[('WAV files', '*.wav')])
        if not fn:
            return

        try:
            # If numpy is available, try to form a consistent numpy array
            if np is not None and len(self._buffer) > 0:
                try:
                    parts = [np.asarray(p) for p in self._buffer]
                    # concatenate along time axis
                    arr = np.concatenate(parts, axis=0)
                except Exception:
                    # fallback: try flattening and concatenate 1-D
                    try:
                        parts = [np.ravel(p) for p in self._buffer]
                        arr = np.concatenate(parts, axis=0)
                    except Exception:
                        arr = None

                if arr is None:
                    raise RuntimeError('Failed to assemble numpy buffer')

                # Ensure float32 in -1..1 range
                if arr.dtype != np.float32:
                    try:
                        arr = arr.astype(np.float32)
                    except Exception:
                        arr = arr.astype(np.float32, copy=False)

                # If mono 2D shape (N,1) make it 1-D for simplicity; soundfile/wave accept both shapes
                if arr.ndim == 2 and arr.shape[1] == 1:
                    arr = arr.reshape(-1)

                # Clip to valid range
                arr = np.clip(arr, -1.0, 1.0)

                # Convert to PCM16
                pcm16 = (arr * 32767.0).astype(np.int16)

                # If soundfile is available, prefer it and request PCM_16 subtype
                if SANDFILE_AVAILABLE and sf is not None:
                    try:
                        # soundfile can accept int16 arrays; write with explicit subtype
                        sf.write(fn, pcm16, self._samplerate, subtype='PCM_16')
                        messagebox.showinfo("Saved", f"Recording saved to {fn}")
                        return
                    except Exception:
                        # fall through to wave fallback
                        logger.exception('soundfile write failed, falling back to wave')

                # Wave fallback: determine channels from array shape
                chans = 1
                if pcm16.ndim == 2:
                    chans = pcm16.shape[1]
                else:
                    chans = 1

                # sanity check pcm16 content
                if getattr(pcm16, 'size', None) is None or getattr(pcm16, 'size', 0) == 0:
                    raise RuntimeError('No audio frames to write')

                with wave.open(fn, 'wb') as wf:
                    wf.setnchannels(chans)
                    wf.setsampwidth(2)
                    wf.setframerate(self._samplerate)
                    # Ensure interleaved bytes for multi-channel
                    wf.writeframes(pcm16.tobytes())

                # Verify written file contains data
                try:
                    with wave.open(fn, 'rb') as wf:
                        if wf.getnframes() <= 0:
                            raise RuntimeError('WAV contains no frames')
                except Exception as ex:
                    # remove bad file and report to user
                    try:
                        os.remove(fn)
                    except Exception:
                        pass
                    logging.getLogger(__name__).exception('WAV write verification failed: %s', ex)
                    messagebox.showerror('Save Error', f'Failed to save recording: {ex}')
                    return

                messagebox.showinfo("Saved", f"Recording saved to {fn}")
                return

            # If numpy not available, try to write raw bytes collected (likely from pyaudio)
            with wave.open(fn, 'wb') as wf:
                wf.setnchannels(self._channels)
                wf.setsampwidth(2)
                wf.setframerate(self._samplerate)
                wrote = 0
                for chunk in self._buffer:
                    if isinstance(chunk, bytes):
                        wf.writeframes(chunk)
                        wrote += len(chunk)
                    elif isinstance(chunk, memoryview):
                        b = bytes(chunk)
                        wf.writeframes(b)
                        wrote += len(b)
                # sanity verify
            try:
                with wave.open(fn, 'rb') as wf:
                    if wf.getnframes() <= 0:
                        raise RuntimeError('WAV contains no frames')
            except Exception as ex:
                try:
                    os.remove(fn)
                except Exception:
                    pass
                logging.getLogger(__name__).exception('WAV write verification failed: %s', ex)
                messagebox.showerror('Save Error', f'Failed to save recording: {ex}')
                return
            messagebox.showinfo("Saved", f"Recording saved to {fn}")
        except Exception as e:
            logger.exception('Failed to save recording')
            messagebox.showerror("Save Error", f"Failed to save: {e}")

    def _on_close(self):
        try:
            self._stop_stream()
        except Exception:
            pass
        try:
            if hasattr(self, 'root') and isinstance(self.root, tk.Toplevel):
                self.root.destroy()
            else:
                self.root.quit()
        except Exception:
            pass


if __name__ == '__main__':
    # allow running standalone for testing
    a = AudioSettingsWindow()
    if isinstance(a.root, tk.Tk):
        a.root.mainloop()
    else:
        tk.mainloop()

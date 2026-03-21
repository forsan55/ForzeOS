"""
forzeos_focus.py

Focus Mode helper for ForzeOS.
Implements safe, reversible Focus Mode behavior:
- Measure RAM before/after
- Suspend/resume non-critical heavy processes (Windows only)
- Hide Windows taskbar during session (Windows only)
- Toggle ForzeOS "mini mode": disable animations/widgets and unload heavy modules
- Maintain whitelist/blacklist and logs

The public API expected by ForzeOS:
- enter_focus_mode(forzeos_instance)
- exit_focus_mode(forzeos_instance)

This module is conservative and skips unsafe actions silently.
"""
from __future__ import annotations
import sys
import os
import time
import logging
import threading
import gc
import signal
import weakref
import atexit
from typing import Optional, Dict, List

try:
    import psutil
except Exception:
    psutil = None

IS_WINDOWS = sys.platform.startswith('win')

logger = logging.getLogger('forzeos_focus')

# Safety defaults: default to NOT forcing a global dry-run.
# Per-instance opt-in will control whether potentially unsafe actions are allowed.
FOCUS_SAFE_DRY_RUN = False

def _unsafe_allowed_for_instance(instance) -> bool:
    """Return True only if the instance explicitly enabled Focus Mode (unsafe actions).

    Security decision: remove a global dry-run dependency; instead the instance
    must enable focus mode via its settings key `focus_mode_enabled`.
    """
    try:
        cfg = getattr(instance, 'config', {}) or {}
        settings = cfg.get('settings', {}) if isinstance(cfg, dict) else {}
        # Backwards-compatible: accept previous key `focus_mode_allow_unsafe`.
        if bool(settings.get('focus_mode_enabled', False)):
            return True
        if bool(settings.get('focus_mode_allow_unsafe', False)):
            return True
    except Exception:
        pass
    try:
        if os.environ.get('FORZEOS_FOCUS_ALLOW_UNSAFE') == '1':
            return True
    except Exception:
        pass
    return not FOCUS_SAFE_DRY_RUN


# Aggressive native helper (optional): a Windows DLL that performs lower-level
# working-set trims / process operations. If present, ForzeOS will offer
# an "aggressive" focus mode that uses the native DLL for stronger effects.
AGGRESSIVE_DLL_NAME = 'forze_aggressive_focus.dll'
_aggressive = None

# Track active instances with an active Focus Mode so we can reliably
# restore state on process exit / system shutdown.
_ACTIVE_FOCUS_INSTANCES = weakref.WeakSet()

def _register_active_instance(instance):
    try:
        _ACTIVE_FOCUS_INSTANCES.add(instance)
    except Exception:
        pass

def _unregister_active_instance(instance):
    try:
        if instance in _ACTIVE_FOCUS_INSTANCES:
            _ACTIVE_FOCUS_INSTANCES.discard(instance)
    except Exception:
        pass

def _exit_all_focus_modes():
    # Best-effort: iterate over a snapshot and call the public exit helpers.
    try:
        instances = list(_ACTIVE_FOCUS_INSTANCES)
        for inst in instances:
            try:
                # Prefer aggressive stop if the instance state indicates it was used
                try:
                    st = getattr(inst, '_focus_state', None)
                    if st and isinstance(st.forzeos_saved, dict) and st.forzeos_saved.get('_aggressive_native'):
                        try:
                            exit_aggressive_focus_mode(inst)
                        except Exception:
                            exit_focus_mode(inst)
                    else:
                        exit_focus_mode(inst)
                except Exception:
                    try:
                        exit_focus_mode(inst)
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception:
        pass

# Register handlers so Focus Mode is cleaned up on process exit or signals
try:
    atexit.register(_exit_all_focus_modes)
except Exception:
    pass
try:
    for sig in (signal.SIGINT, signal.SIGTERM, getattr(signal, 'SIGHUP', signal.SIGTERM)):
        try:
            signal.signal(sig, lambda s, f: (_exit_all_focus_modes(), os._exit(0)))
        except Exception:
            pass
except Exception:
    pass

def _find_aggressive_dll_path():
    try:
        base = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
        return os.path.join(base, AGGRESSIVE_DLL_NAME)
    except Exception:
        return AGGRESSIVE_DLL_NAME


def _load_aggressive_dll():
    """Attempt to load the aggressive native DLL (Windows). Returns True on success."""
    global _aggressive
    if not IS_WINDOWS:
        return False
    if _aggressive is not None:
        return True
    path = _find_aggressive_dll_path()
    if not os.path.exists(path):
        logger.info('Aggressive Focus DLL not found at %s', path)
        # Try to build automatically if a compiler is present (best-effort)
        # Only attempt an automatic build if explicitly allowed via env var
        try:
            if os.environ.get('FORZEOS_ALLOW_AUTO_BUILD') == '1':
                built = _try_build_aggressive_dll()
                if built and os.path.exists(path):
                    logger.info('Aggressive Focus DLL built successfully; loading %s', path)
                else:
                    return False
            else:
                logger.info('Automatic build disabled (set FORZEOS_ALLOW_AUTO_BUILD=1 to enable)')
                return False
        except Exception:
            return False
    try:
        _aggressive = ctypes.WinDLL(path)
        # optional prototypes
        try:
            _aggressive.aggressive_focus_start.argtypes = []
            _aggressive.aggressive_focus_start.restype = ctypes.c_int
            _aggressive.aggressive_focus_stop.argtypes = []
            _aggressive.aggressive_focus_stop.restype = ctypes.c_int
        except Exception:
            pass
        logger.info('Aggressive Focus native module loaded: %s', path)
        return True
    except Exception:
        logger.exception('Failed loading Aggressive Focus native module')
        _aggressive = None
        return False


def aggressive_available() -> bool:
    """Return True if aggressive native module is available and loadable."""
    return _load_aggressive_dll()


def _try_build_aggressive_dll() -> bool:
    """Attempt to compile `forze_aggressive_focus.cpp` into a DLL using
    available toolchains (`cl` for MSVC or `g++` for MinGW). This is a
    best-effort helper: it returns True if the command returned success and
    the DLL exists afterwards.

    Note: building requires a toolchain installed and may require running
    from a Developer Command Prompt for MSVC.
    """
    import shutil, subprocess

    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'forze_aggressive_focus.cpp')
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), AGGRESSIVE_DLL_NAME)
    if not os.path.exists(src):
        logger.info('Aggressive source file missing: %s', src)
        return False

    # prefer MSVC if available
    cl = shutil.which('cl')
    if cl:
        # MSVC: cl /LD forze_aggressive_focus.cpp psapi.lib /link /OUT:forze_aggressive_focus.dll
        cmd = ['cl', '/LD', src, 'psapi.lib', '/link', f'/OUT:{out}']
        try:
            logger.info('Attempting to build aggressive DLL with MSVC: %s', ' '.join(cmd))
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=False, cwd=os.path.dirname(os.path.abspath(__file__)), timeout=120)
            logger.info('Build output: %s', p.stdout.decode(errors='ignore'))
            return os.path.exists(out)
        except Exception:
            logger.exception('MSVC build failed')
            # fallthrough to try g++

    gpp = shutil.which('g++') or shutil.which('mingw32-g++')
    if gpp:
        # MinGW: g++ -shared -o forze_aggressive_focus.dll forze_aggressive_focus.cpp -lpsapi -static
        cmd = [gpp, '-shared', '-o', out, src, '-lpsapi']
        try:
            logger.info('Attempting to build aggressive DLL with g++: %s', ' '.join(cmd))
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=False, cwd=os.path.dirname(os.path.abspath(__file__)), timeout=120)
            logger.info('Build output: %s', p.stdout.decode(errors='ignore'))
            return os.path.exists(out)
        except Exception:
            logger.exception('g++ build failed')

    logger.info('No suitable compiler found to build aggressive DLL')
    return False


def enter_aggressive_focus_mode(instance):
    """Attempt to enter an aggressive native-backed Focus Mode.

    If the native DLL isn't present or fails to load, fall back to the
    pure-Python `enter_focus_mode` so the user still gets a safe mode.
    """
    if not aggressive_available():
        msg = 'Aggressive Focus native module not available; falling back to Python Focus Mode.'
        logger.info(msg)
        try:
            if hasattr(instance, 'notify'):
                instance.notify(msg)
        except Exception:
            pass
        return enter_focus_mode(instance)

    # call the native start routine (best-effort)
    try:
        # Before invoking native DLL, feed runtime settings from instance.config
        try:
            cfg = getattr(instance, 'config', {}) or {}
            settings = cfg.get('settings', {}) if isinstance(cfg, dict) else {}
            # max trims
            mt = settings.get('focus_max_trims', None)
            if mt is not None:
                os.environ['FORZEOS_MAX_TRIMS'] = str(int(mt))
            # min rss MB
            mr = settings.get('focus_min_rss_mb', None)
            if mr is not None:
                os.environ['FORZEOS_MIN_RSS_MB'] = str(int(mr))
            # same session
            ss = settings.get('focus_only_same_session', None)
            if ss is not None:
                os.environ['FORZEOS_ONLY_SAME_SESSION'] = '1' if bool(ss) else '0'
            # whitelist/blacklist process name patterns (comma-separated)
            wl = settings.get('focus_whitelist', None)
            if wl is not None:
                if isinstance(wl, (list, tuple)):
                    os.environ['FORZEOS_WHITELIST_NAMES'] = ','.join(str(x) for x in wl)
                else:
                    os.environ['FORZEOS_WHITELIST_NAMES'] = str(wl)
            bl = settings.get('focus_blacklist', None)
            if bl is not None:
                if isinstance(bl, (list, tuple)):
                    os.environ['FORZEOS_BLACKLIST_NAMES'] = ','.join(str(x) for x in bl)
                else:
                    os.environ['FORZEOS_BLACKLIST_NAMES'] = str(bl)
        except Exception:
            pass
        res = _aggressive.aggressive_focus_start()
        msg = f'Aggressive Focus native start returned: {res}'
        logger.info(msg)
        try:
            if hasattr(instance, 'notify'):
                instance.notify(msg)
        except Exception:
            pass
    except Exception:
        logger.exception('Aggressive focus native start failed; falling back')
        return enter_focus_mode(instance)

    # create a FocusModeState and annotate it as aggressive-engaged
    state = enter_focus_mode(instance)
    try:
        state.forzeos_saved['_aggressive_native'] = True
        state.log('Aggressive Focus: native module engaged')
    except Exception:
        pass
    return state


def exit_aggressive_focus_mode(instance) -> Optional[FocusModeState]:
    """Exit aggressive focus: call native stop if present, then restore Python Focus Mode state."""
    try:
        if _aggressive is not None:
            try:
                _aggressive.aggressive_focus_stop()
            except Exception:
                logger.exception('Aggressive native stop failed')
        # restore via Python exit_focus_mode
        try:
            return exit_focus_mode(instance)
        except Exception:
            logger.exception('exit_focus_mode failed during aggressive stop')
            return None
    except Exception:
        logger.exception('exit_aggressive_focus_mode fatal')
        return None


# Windows-specific imports and functions
if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    ntdll = ctypes.WinDLL('ntdll', use_last_error=True)

    PROCESS_ALL_ACCESS = 0x1F0FFF

    OpenProcess = kernel32.OpenProcess
    OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    OpenProcess.restype = wintypes.HANDLE

    CloseHandle = kernel32.CloseHandle
    CloseHandle.argtypes = [wintypes.HANDLE]
    CloseHandle.restype = wintypes.BOOL

    # Working set helpers
    try:
        GetProcessWorkingSetSize = kernel32.GetProcessWorkingSetSize
        GetProcessWorkingSetSize.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
        GetProcessWorkingSetSize.restype = wintypes.BOOL
    except Exception:
        GetProcessWorkingSetSize = None
    try:
        SetProcessWorkingSetSize = kernel32.SetProcessWorkingSetSize
        SetProcessWorkingSetSize.argtypes = [wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t]
        SetProcessWorkingSetSize.restype = wintypes.BOOL
    except Exception:
        SetProcessWorkingSetSize = None

    try:
        NtSuspendProcess = ntdll.NtSuspendProcess
        NtSuspendProcess.argtypes = [wintypes.HANDLE]
        NtSuspendProcess.restype = wintypes.DWORD
        NtResumeProcess = ntdll.NtResumeProcess
        NtResumeProcess.argtypes = [wintypes.HANDLE]
        NtResumeProcess.restype = wintypes.DWORD
    except Exception:
        NtSuspendProcess = None
        NtResumeProcess = None

    # psapi for working set trimming
    try:
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        EmptyWorkingSet = psapi.EmptyWorkingSet
        EmptyWorkingSet.argtypes = [wintypes.HANDLE]
        EmptyWorkingSet.restype = wintypes.BOOL
    except Exception:
        EmptyWorkingSet = None

    # taskbar window helpers
    FindWindowW = ctypes.windll.user32.FindWindowW
    ShowWindow = ctypes.windll.user32.ShowWindow
    SW_HIDE = 0
    SW_SHOW = 5

    # Helper: detect whether a process has at least one visible top-level window
    def _process_has_window(pid: int) -> bool:
        try:
            user32 = ctypes.windll.user32
            EnumWindows = user32.EnumWindows
            GetWindowThreadProcessId = user32.GetWindowThreadProcessId
            IsWindowVisible = user32.IsWindowVisible
            GetWindowTextW = user32.GetWindowTextW
            PWNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

            found = {'ok': False}

            @PWNDENUMPROC
            def _cb(hwnd, lParam):
                try:
                    if not IsWindowVisible(hwnd):
                        return True
                    pid_buf = wintypes.DWORD()
                    GetWindowThreadProcessId(hwnd, ctypes.byref(pid_buf))
                    if int(pid_buf.value) != int(pid):
                        return True
                    # check title length
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length and length > 0:
                        found['ok'] = True
                        return False
                except Exception:
                    return True
                return True

            EnumWindows(_cb, 0)
            return bool(found.get('ok'))
        except Exception:
            # if detection fails, be conservative and return False (do not trim/suspend)
            return False


# Defaults
DEFAULT_RAM_CEILING_PERCENT = 55  # percent
# conservative whitelist (do not suspend)
DEFAULT_WHITELIST = set([
    'System', 'Registry', 'smss.exe', 'csrss.exe', 'wininit.exe', 'services.exe',
    'lsass.exe', 'explorer.exe', 'svchost.exe', 'System Idle Process'
])
# blacklist (prefer suspending) - common huge apps (user may want these suspended)
DEFAULT_BLACKLIST = set(['chrome.exe', 'firefox.exe', 'msedge.exe', 'spotify.exe', 'discord.exe'])


def _now():
    return int(time.time())


def _measure_ram_used() -> Optional[int]:
    try:
        if psutil is None:
            return None
        vm = psutil.virtual_memory()
        return int(vm.used)
    except Exception:
        return None


def _human(n: int) -> str:
    # simple human-readable bytes
    try:
        for unit in ('B', 'KB', 'MB', 'GB'):
            if abs(n) < 1024.0:
                return f"{n:3.1f}{unit}"
            n /= 1024.0
        return f"{n:.1f}TB"
    except Exception:
        return str(n)


def _suspend_process(pid: int) -> bool:
    if not IS_WINDOWS or NtSuspendProcess is None:
        return False
    try:
        h = OpenProcess(PROCESS_ALL_ACCESS, False, int(pid))
        if not h:
            return False
        try:
            rc = NtSuspendProcess(h)
            return rc == 0
        finally:
            try:
                CloseHandle(h)
            except Exception:
                pass
    except Exception:
        return False


def _resume_process(pid: int) -> bool:
    if not IS_WINDOWS or NtResumeProcess is None:
        return False
    try:
        h = OpenProcess(PROCESS_ALL_ACCESS, False, int(pid))
        if not h:
            return False
        try:
            rc = NtResumeProcess(h)
            return rc == 0
        finally:
            try:
                CloseHandle(h)
            except Exception:
                pass
    except Exception:
        return False


def _hide_taskbar() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        hwnd = FindWindowW('Shell_TrayWnd', None)
        if hwnd:
            ShowWindow(hwnd, SW_HIDE)
            return True
    except Exception:
        pass
    return False


def _show_taskbar() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        hwnd = FindWindowW('Shell_TrayWnd', None)
        if hwnd:
            ShowWindow(hwnd, SW_SHOW)
            return True
    except Exception:
        pass
    return False


class FocusModeState:
    """Holds session state so everything is reversible."""

    def __init__(self):
        self.started_at = _now()
        self.before_ram = None
        self.before_pct = None
        self.after_ram = None
        self.after_pct = None
        self.suspended: List[Dict] = []  # list of {pid, name, freed_bytes}
        self.taskbar_hidden = False
        self.explorer_suspended = False
        self.forzeos_saved: Dict = {}
        self.active = False
        self.stop_event = threading.Event()
        # total number of suspends we've performed during this session
        self._suspends_done = 0
        # aggressive native trimmed count (if used)
        self._aggressive_trimmed = 0
        self.log_lines: List[str] = []

    def log(self, s: str):
        try:
            ts = time.strftime('%Y-%m-%d %H:%M:%S')
            self.log_lines.append(f"[{ts}] {s}")
            logger.info(s)
        except Exception:
            pass


def _default_settings(instance):
    # read configured ceiling if present
    try:
        cfg = getattr(instance, 'config', {})
        ceiling = cfg.get('settings', {}).get('focus_ram_ceiling', DEFAULT_RAM_CEILING_PERCENT)
        if isinstance(ceiling, (int, float)):
            return int(ceiling)
    except Exception:
        pass
    return DEFAULT_RAM_CEILING_PERCENT


def _perform_focus_actions(instance, state: FocusModeState):
    """Worker: perform the heavy focus-mode actions in a background thread.

    This is run in a daemon thread to avoid blocking the main/UI thread.
    """
    try:
        # Announce whether unsafe actions will be performed (helps debug dry-run vs active)
        try:
            allowed = _unsafe_allowed_for_instance(instance)
            state.log(f"Focus Mode active. Unsafe actions allowed: {bool(allowed)}")
        except Exception:
            pass

        # Hide taskbar if possible (only when allowed)
        try:
            if _unsafe_allowed_for_instance(instance) and IS_WINDOWS:
                ok = _hide_taskbar()
                state.taskbar_hidden = ok
                state.log(f"Taskbar hidden: {ok}")
            else:
                state.log("Taskbar hide skipped (dry-run/safety)")
        except Exception as e:
            state.log(f"Failed to hide taskbar: {e}")

        # ForzeOS mini-mode: disable animations/widgets/background visuals if present
        try:
            saved = {}
            # common flags this app uses; be defensive about attribute existence
            for attr in ('animations_enabled', 'widgets_enabled', 'background_visuals', 'auto_refresh'):
                if hasattr(instance, attr):
                    saved[attr] = getattr(instance, attr)
                    try:
                        setattr(instance, attr, False)
                    except Exception:
                        pass

            # Record any reference to heavy modules to unload — only actually unload when unsafe allowed.
            saved['_unloaded_modules'] = []
            heavy = ('matplotlib', 'mpl', 'PIL', 'PIL.Image', 'PIL.ImageTk', 'pygame', 'moviepy', 'vlc', 'numpy')

            if _unsafe_allowed_for_instance(instance):
                # Instead of force-unloading modules (dangerous), mark the instance
                # as running in low-power mode and record candidates. Applications
                # should observe `instance.low_power_mode` and reduce activity.
                for mod in heavy:
                    try:
                        if mod in sys.modules:
                            # avoid targeting modules the instance explicitly references
                            referenced = False
                            try:
                                for v in getattr(instance, '__dict__', {}).values():
                                    if getattr(v, '__module__', None) and getattr(v, '__module__', None).startswith(mod.split('.')[0]):
                                        referenced = True
                                        break
                            except Exception:
                                pass
                            if not referenced:
                                saved['_unloaded_modules'].append(mod)
                    except Exception:
                        pass
                # set a cooperative flag instead of deleting modules
                try:
                    instance.low_power_mode = True
                except Exception:
                    pass
                state.log(f"ForzeOS mini-mode applied; recorded modules: {saved.get('_unloaded_modules')}")
            else:
                # Dry-run: record candidates but do not unload
                for mod in heavy:
                    try:
                        if mod in sys.modules:
                            saved['_unloaded_modules'].append(mod)
                    except Exception:
                        pass
                state.log(f"Mini-mode dry-run; would unload: {saved.get('_unloaded_modules')}")

            instance._forzeos_saved_states = saved
            state.forzeos_saved = saved

            # force python GC and optionally trim working sets to show immediate effect
            try:
                gc.collect()
            except Exception:
                pass

            if _unsafe_allowed_for_instance(instance) and IS_WINDOWS:
                # trim this process working set
                try:
                        hself = OpenProcess(PROCESS_ALL_ACCESS, False, os.getpid())
                        if hself and EmptyWorkingSet is not None:
                            try:
                                # record current working set limits for our process so we can restore later
                                try:
                                    if GetProcessWorkingSetSize is not None:
                                        min_ws = ctypes.c_size_t()
                                        max_ws = ctypes.c_size_t()
                                        if GetProcessWorkingSetSize(hself, ctypes.byref(min_ws), ctypes.byref(max_ws)):
                                            state.forzeos_saved.setdefault('trimmed_processes', []).append({'pid': os.getpid(), 'min_ws': int(min_ws.value), 'max_ws': int(max_ws.value)})
                                except Exception:
                                    pass
                                EmptyWorkingSet(hself)
                            except Exception:
                                pass
                            try:
                                CloseHandle(hself)
                            except Exception:
                                pass
                except Exception:
                    pass

                # Instead of trimming many processes at once (which can cause churn),
                # schedule a conservative single-pass trim candidate here and leave
                # heavier actions to the maintenance loop below.
                pass
        except Exception as e:
            state.log(f"Failed to apply mini-mode: {e}")

        # Suspend heavy non-critical processes until available RAM exceeds threshold (only when allowed)
        try:
            if psutil is None:
                state.log('psutil not available; skipping process suspension')
            else:
                # Use available free RAM (MB) to decide whether to suspend processes.
                vm = psutil.virtual_memory()
                free_mb = float(vm.available) / (1024 ** 2)
                # allow per-instance override of threshold in settings or compute from percent ceiling
                try:
                    cfg = getattr(instance, 'config', {}) or {}
                    settings = cfg.get('settings', {}) if isinstance(cfg, dict) else {}
                    # explicit MB threshold takes precedence
                    if 'focus_free_mb_threshold' in settings:
                        threshold_mb = float(settings.get('focus_free_mb_threshold', 1500))
                        ceiling_pct = None
                    else:
                        # compute threshold from percent ceiling (desired free based on allowed usage)
                        ceiling_pct = _default_settings(instance) if callable(_default_settings) else DEFAULT_RAM_CEILING_PERCENT
                        try:
                            total_mb = float(vm.total) / (1024 ** 2)
                            desired_free_mb = total_mb * (100.0 - float(ceiling_pct)) / 100.0
                        except Exception:
                            desired_free_mb = 1500.0
                        # clamp to a reasonable minimum so small machines still trigger
                        threshold_mb = max(100.0, desired_free_mb)
                except Exception:
                    threshold_mb = 1500.0
                    ceiling_pct = None
                if ceiling_pct is not None:
                    state.log(f"Available RAM: {free_mb:.1f} MB, threshold: {threshold_mb:.1f} MB (computed from ceiling={ceiling_pct}%)")
                else:
                    state.log(f"Available RAM: {free_mb:.1f} MB, threshold: {threshold_mb:.1f} MB")

                # build user-configured whitelist/blacklist from settings
                try:
                    user_whitelist = set()
                    user_blacklist = set()
                    raw_wl = settings.get('focus_whitelist', [])
                    raw_bl = settings.get('focus_blacklist', [])
                    if isinstance(raw_wl, str):
                        raw_wl = [x.strip() for x in raw_wl.split(',') if x.strip()]
                    if isinstance(raw_bl, str):
                        raw_bl = [x.strip() for x in raw_bl.split(',') if x.strip()]
                    for x in (raw_wl or []):
                        try:
                            user_whitelist.add(x.lower())
                        except Exception:
                            pass
                    for x in (raw_bl or []):
                        try:
                            user_blacklist.add(x.lower())
                        except Exception:
                            pass
                except Exception:
                    user_whitelist = set()
                    user_blacklist = set()

                if free_mb < threshold_mb:
                    if not _unsafe_allowed_for_instance(instance):
                        state.log('Process suspension skipped (dry-run/safety)')
                    else:
                        # Safety: limit how aggressive suspension can be to avoid system hang.
                        try:
                            total_mb = float(vm.total) / (1024 ** 2)
                        except Exception:
                            total_mb = 0.0
                        # cap threshold to at most 25% of total RAM unless explicitly allowed via env
                        try:
                            env_allow = os.environ.get('FORZEOS_FOCUS_ALLOW_UNSAFE') == '1'
                        except Exception:
                            env_allow = False
                        safe_cap_mb = max(100.0, total_mb * 0.25) if total_mb > 0 else 1500.0
                        if not env_allow and threshold_mb > safe_cap_mb:
                            state.log(f"Computed threshold {threshold_mb:.1f}MB is very large; capping to {safe_cap_mb:.1f}MB for safety")
                            threshold_mb = safe_cap_mb

                        # allow per-instance override for max number of suspends
                        try:
                            max_suspends_total = int(settings.get('focus_max_suspends', 3))
                        except Exception:
                            max_suspends_total = 3

                        # Instead of suspending many processes in one shot, perform a
                        # throttled maintenance loop: suspend at most one candidate per
                        # iteration and re-evaluate system RAM. This reduces churn
                        # and makes Focus Mode feel smoother.
                        maintenance_cycles = int(settings.get('focus_maintenance_cycles', 30))
                        cycle_sleep = float(settings.get('focus_cycle_sleep', 3.0))

                        # Precompute candidates list once per maintenance run
                        our_pid = os.getpid()
                        procs = []
                        for p in psutil.process_iter(['pid', 'name', 'username', 'memory_info']):
                            try:
                                info = p.info
                                pid = int(info.get('pid') or 0)
                                if pid == our_pid:
                                    continue
                                name = (info.get('name') or '').lower()
                                # skip whitelisted names (default + user)
                                if name in (n.lower() for n in DEFAULT_WHITELIST):
                                    continue
                                if any(w in name for w in user_whitelist):
                                    continue
                                # skip system processes (no username or PID <=4)
                                if pid <= 4:
                                    continue
                                # skip system users
                                user = info.get('username') or ''
                                if user and (user.lower().startswith('nt authority') or user.lower() in ('system', 'local system')):
                                    continue
                                mem = 0
                                mi = info.get('memory_info')
                                if mi is not None:
                                    try:
                                        mem = int(mi.rss)
                                    except Exception:
                                        mem = 0
                                procs.append((mem, pid, name))
                            except Exception:
                                continue

                        def _proc_sort_key(t):
                            mem, pid, name = t
                            score = 0
                            lname = name.lower()
                            if any(b in lname for b in ('chrome','firefox','msedge','edge','spotify','discord','steam','epic','battle','riot','launcher','rgb','asus','razer','synapse','steelseries')):
                                score -= 1000000000
                            return (score, mem)

                        procs.sort(key=_proc_sort_key, reverse=True)

                        # If aggressive native helper is available, kick it off once
                        try:
                            if aggressive_available() and _unsafe_allowed_for_instance(instance) and state._aggressive_trimmed == 0:
                                def _call_aggr():
                                    try:
                                        res = 0
                                        try:
                                            res = _aggressive.aggressive_focus_start()
                                        except Exception:
                                            res = 0
                                        try:
                                            state.forzeos_saved['_aggressive_trimmed_count'] = int(res)
                                            state._aggressive_trimmed = int(res)
                                        except Exception:
                                            pass
                                    except Exception:
                                        pass
                                threading.Thread(target=_call_aggr, daemon=True).start()
                        except Exception:
                            pass

                        # maintenance loop: one candidate per iteration
                        for cycle in range(maintenance_cycles):
                            if state.stop_event.is_set() or not state.active:
                                break
                            try:
                                vm = psutil.virtual_memory()
                                cur_free_mb = float(vm.available) / (1024 ** 2)
                            except Exception:
                                cur_free_mb = free_mb
                            if cur_free_mb >= threshold_mb:
                                break
                            if state._suspends_done >= max_suspends_total:
                                state.log(f"Reached total suspend limit: {max_suspends_total}; stopping further suspensions")
                                break

                            # find a single candidate
                            candidate = None
                            for mem, pid, name in procs:
                                try:
                                    if name in (n.lower() for n in DEFAULT_WHITELIST):
                                        continue
                                    # user whitelist: skip
                                    if any(w in name for w in user_whitelist):
                                        continue
                                    try:
                                        p = psutil.Process(pid)
                                        cpu = p.cpu_percent(interval=0.0)
                                    except Exception:
                                        cpu = None
                                    if cpu is not None and cpu > 10.0:
                                        continue
                                    # allow blacklisted names even if memory is smaller
                                    if mem < 150 * 1024 * 1024 and not any(b in name for b in user_blacklist):
                                        continue
                                    has_win = _process_has_window(pid) if IS_WINDOWS else True
                                    if not has_win:
                                        continue
                                    candidate = (mem, pid, name)
                                    break
                                except Exception:
                                    continue

                            if not candidate:
                                # nothing suitable this cycle
                                time.sleep(cycle_sleep)
                                continue

                            mem, pid, name = candidate
                            ok = False
                            try:
                                if IS_WINDOWS and NtSuspendProcess is not None:
                                    # trim working set before suspend
                                    try:
                                        if EmptyWorkingSet is not None:
                                            h = OpenProcess(PROCESS_ALL_ACCESS, False, int(pid))
                                            if h:
                                                try:
                                                    try:
                                                        if GetProcessWorkingSetSize is not None:
                                                            min_ws = ctypes.c_size_t()
                                                            max_ws = ctypes.c_size_t()
                                                            if GetProcessWorkingSetSize(h, ctypes.byref(min_ws), ctypes.byref(max_ws)):
                                                                state.forzeos_saved.setdefault('trimmed_processes', []).append({'pid': int(pid), 'min_ws': int(min_ws.value), 'max_ws': int(max_ws.value)})
                                                    except Exception:
                                                        pass
                                                    EmptyWorkingSet(h)
                                                except Exception:
                                                    pass
                                                try:
                                                    CloseHandle(h)
                                                except Exception:
                                                    pass
                                    except Exception:
                                        pass
                                    ok = _suspend_process(pid)
                                else:
                                    try:
                                        os.kill(pid, getattr(signal, 'SIGSTOP'))
                                        ok = True
                                    except Exception:
                                        ok = False
                            except Exception:
                                ok = False

                            if ok:
                                after = _measure_ram_used()
                                freed = None
                                if after is not None and state.before_ram is not None:
                                    freed = max(0, state.before_ram - after - sum(x.get('freed_bytes', 0) for x in state.suspended))
                                else:
                                    freed = mem
                                state.suspended.append({'pid': pid, 'name': name, 'freed_bytes': freed})
                                state._suspends_done += 1
                                human_freed = _human(freed) if isinstance(freed, int) else str(freed)
                                msg = f"[Focus] {name} suspended (pid={pid}), approx freed={human_freed}"
                                state.log(msg)
                                try:
                                    if hasattr(instance, 'notify'):
                                        try:
                                            instance.notify(msg)
                                        except Exception:
                                            pass
                                except Exception:
                                    pass

                            # sleep before next cycle to avoid rapid churn
                            time.sleep(cycle_sleep)

                        # end maintenance loop

                else:
                    state.log('Available RAM above threshold; no suspension needed')
        except Exception as e:
            state.log(f"Process suspension step failed: {e}")

        # final ram measure
        try:
            state.after_ram = _measure_ram_used()
            try:
                state.after_pct = psutil.virtual_memory().percent if psutil is not None else None
            except Exception:
                state.after_pct = None
            if state.before_ram is not None and state.after_ram is not None:
                freed_total = max(0, state.before_ram - state.after_ram)
            else:
                freed_total = sum(x.get('freed_bytes', 0) for x in state.suspended)
            human_freed_total = _human(freed_total) if isinstance(freed_total, int) else str(freed_total)
            state.log(f"Focus Mode entered. Freed approx: {human_freed_total} bytes (before_pct={state.before_pct}, after_pct={state.after_pct})")
        except Exception:
            pass

        # show a simple visual indicator on the instance if possible (left side)
        try:
            if hasattr(instance, 'root') and hasattr(instance.root, 'winfo_exists') and instance.root.winfo_exists():
                try:
                    lbl = getattr(instance, '_focus_mode_indicator', None)
                    if not lbl:
                        import tkinter as tk
                        before_pct = f"{state.before_pct}%" if state.before_pct is not None else 'N/A'
                        after_pct = f"{state.after_pct}%" if state.after_pct is not None else 'N/A'
                        freed_str = human_freed_total if 'human_freed_total' in locals() else 'N/A'
                        txt = f"🧼 Focus Mode — Before: {before_pct} After: {after_pct} Freed: {freed_str}"
                        lbl = tk.Label(instance.root, text=txt, bg=getattr(instance, 'colors', {}).get('accent', '#4a90e2'),
                                       fg='white', font=('Arial', 10, 'bold'))
                        # place on the left side
                        try:
                            lbl.place(x=8, y=8)
                        except Exception:
                            try:
                                lbl.pack(anchor='nw')
                            except Exception:
                                pass
                        instance._focus_mode_indicator = lbl
                        state.log('Placed Focus Mode UI indicator (left)')
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        logger.exception('_perform_focus_actions fatal')



def enter_focus_mode(instance) -> FocusModeState:
    """Enter Focus Mode for the given ForzeOS instance.

    Returns the FocusModeState object representing the session, or raises on fatal error.
    The instance will receive `._focus_state` attribute storing this state for restoration.
    """
    state = FocusModeState()
    try:
        state.before_ram = _measure_ram_used()
        try:
            state.before_pct = psutil.virtual_memory().percent if psutil is not None else None
        except Exception:
            state.before_pct = None
        state.log(f"Starting Focus Mode; baseline RAM used: {state.before_ram} bytes (pct={state.before_pct})")

        # Mark active early to avoid re-entry
        state.active = True
        try:
            state.stop_event.clear()
        except Exception:
            pass
        instance._focus_state = state
        try:
            _register_active_instance(instance)
        except Exception:
            pass

        # Run heavy actions in background so the caller/UI isn't blocked
        try:
            t = threading.Thread(target=_perform_focus_actions, args=(instance, state), daemon=True)
            t.start()
        except Exception as e:
            state.log(f"Failed to start focus worker thread: {e}")

        return state
    except Exception as e:
        logger.exception('enter_focus_mode fatal')
        raise


def exit_focus_mode(instance) -> Optional[FocusModeState]:
    """Exit Focus Mode: resume suspended processes, restore taskbar and ForzeOS state.

    Returns the FocusModeState that was active (or None if none).
    """
    try:
        state: FocusModeState = getattr(instance, '_focus_state', None)
        if not state:
            logger.info('No active focus state found; nothing to restore')
            return None

        # signal the worker to stop and resume processes
        try:
            if hasattr(state, 'stop_event') and state.stop_event is not None:
                try:
                    state.stop_event.set()
                except Exception:
                    pass
        except Exception:
            pass

        # resume processes
        try:
            for rec in list(state.suspended):
                pid = int(rec.get('pid'))
                try:
                    ok = False
                    if IS_WINDOWS and NtResumeProcess is not None:
                        ok = _resume_process(pid)
                    else:
                        try:
                            os.kill(pid, getattr(signal, 'SIGCONT'))
                            ok = True
                        except Exception:
                            ok = False
                    state.log(f"Resumed pid={pid} ok={ok}")
                except Exception as e:
                    state.log(f"Failed to resume pid={pid}: {e}")
        except Exception as e:
            state.log(f"Error while resuming processes: {e}")

        # restore taskbar
        try:
            # Only attempt to show taskbar if we previously hid it and unsafe operations are allowed
            if state.taskbar_hidden:
                if _unsafe_allowed_for_instance(instance) or IS_WINDOWS:
                    ok = _show_taskbar()
                    state.log(f"Taskbar restored: {ok}")
                else:
                    state.log("Taskbar restoration skipped (dry-run/safety)")
        except Exception as e:
            state.log(f"Failed to restore taskbar: {e}")

        # restore ForzeOS saved states
        try:
            saved = getattr(instance, '_forzeos_saved_states', {}) or {}
            for k, v in saved.items():
                if k == '_unloaded_modules':
                    # We recorded module candidates previously; we did NOT forcibly
                    # unload them. Applications should check `instance.low_power_mode`.
                    try:
                        # clear low_power_mode flag if present
                        if hasattr(instance, 'low_power_mode'):
                            try:
                                instance.low_power_mode = False
                            except Exception:
                                pass
                    except Exception:
                        pass
                else:
                    try:
                        setattr(instance, k, v)
                    except Exception:
                        pass
            try:
                delattr = getattr(instance, '__dict__', None)
            except Exception:
                delattr = None
            try:
                if hasattr(instance, '_forzeos_saved_states'):
                    del instance._forzeos_saved_states
            except Exception:
                pass
            state.log('ForzeOS mini-mode restored')
        except Exception as e:
            state.log(f"Failed to restore ForzeOS state: {e}")

        # Restore working set sizes for trimmed processes if we recorded them
        try:
            trimmed = state.forzeos_saved.get('trimmed_processes', []) if isinstance(state.forzeos_saved, dict) else []
            for rec in trimmed:
                try:
                    pid = int(rec.get('pid'))
                    min_ws = int(rec.get('min_ws') or 0)
                    max_ws = int(rec.get('max_ws') or 0)
                    if pid and (min_ws or max_ws) and IS_WINDOWS and SetProcessWorkingSetSize is not None:
                        try:
                            h = OpenProcess(PROCESS_ALL_ACCESS, False, int(pid))
                            if h:
                                try:
                                    # attempt to restore previous working set limits with retries
                                    for attempt in range(3):
                                        try:
                                            ok = SetProcessWorkingSetSize(h, ctypes.c_size_t(min_ws), ctypes.c_size_t(max_ws))
                                            if ok:
                                                break
                                        except Exception:
                                            pass
                                        try:
                                            time.sleep(0.05)
                                        except Exception:
                                            pass
                                except Exception:
                                    pass
                                try:
                                    CloseHandle(h)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass

        # final ram measure
        try:
            state.after_ram = _measure_ram_used()
            if state.before_ram is not None and state.after_ram is not None:
                freed = max(0, state.before_ram - state.after_ram)
                state.log(f"Focus Mode ended. Net freed approx: {freed} bytes")
        except Exception:
            pass

        # remove UI indicator
        try:
            lbl = getattr(instance, '_focus_mode_indicator', None)
            if lbl:
                try:
                    lbl.destroy()
                except Exception:
                    pass
                try:
                    del instance._focus_mode_indicator
                except Exception:
                    pass
        except Exception:
            pass

        # attach log to instance for user trust features
        try:
            instance._focus_mode_log = list(state.log_lines)
        except Exception:
            pass

        # mark inactive and remove state on instance
        try:
            state.active = False
            try:
                _unregister_active_instance(instance)
            except Exception:
                pass
            try:
                del instance._focus_state
            except Exception:
                pass
        except Exception:
            pass

        return state
    except Exception:
        logger.exception('exit_focus_mode fatal')
        return None

# Removed duplicate wrapper definitions; wrappers defined later with preserved impl.
# Preferred exported names
# Preserve original implementations to avoid recursive wrapper lookups.
# Store references to the concrete functions before we rebind the public names.
_enter_focus_mode_impl = enter_focus_mode
_exit_focus_mode_impl = exit_focus_mode

def enter_focus_mode_wrapper(instance):
    return _enter_focus_mode_impl(instance)


def exit_focus_mode_wrapper(instance):
    return _exit_focus_mode_impl(instance)


# Preferred exported names (public API remains the same)
enter_focus_mode = enter_focus_mode_wrapper
exit_focus_mode = exit_focus_mode_wrapper

def restore_explorer() -> bool:
    """Attempt to start `explorer.exe` on Windows to recover taskbar/desktop.

    Returns True if the process was started (or already running), False otherwise.
    """
    try:
        if not IS_WINDOWS:
            return False
        import subprocess
        subprocess.Popen(['explorer.exe'])
        return True
    except Exception:
        return False

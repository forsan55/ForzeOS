#!/usr/bin/env python3
"""
ForzeOS Market - lightweight application store & developer environment

Features implemented (core MVP):
- Toplevel store window (class ForzeOSMarket)
- Lists apps found under `apps/` and `market_apps/` plus `market_data.json`
- Shows each app as a card with icon, name, description and Open/Edit/Remove buttons
- Integrates `organize_assets.py` as the first tool if present
- Developer tab: simple code editor (open/save/run), Save as App (writes to apps/), live traceback output
- market_data.json persistence for app metadata

This file is intentionally self-contained and can be run standalone or opened
from the main ForzeOS process. When used inside ForzeOS, the Toplevel parent
should be the ForzeOS `root` Tk instance and optionally the ForzeOS instance
can be passed as `forze` to allow tighter integration.
"""
from __future__ import annotations
import os
import json
import csv
import io
import platform
import subprocess
import traceback
import threading
import sys
import shutil
import ctypes
import logging
import re
import importlib
import importlib.util
import tempfile
import difflib
import time
from functools import lru_cache
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False


MARKET_DATA_FILENAME = 'market_data.json'
# Default apps folder for this market module. Placed next to this file to support
# standalone runs and importing into ForzeOS. This mirrors the secondary
# ForzeMarket helper's `APP_FOLDER` location.
APP_FOLDER = Path(__file__).parent / 'market_apps'

# Default template used for new apps; editable via Template button
MARKET_DEFAULT_TEMPLATE = """#!/usr/bin/env python3
import tkinter as tk

class App:
    def __init__(self, root):
        self.root = tk.Toplevel(root)
        self.root.title('{name}')
        tk.Label(self.root, text='Hello from {name}').pack(padx=20, pady=20)

if __name__ == '__main__':
    r = tk.Tk(); r.withdraw(); App(r); r.mainloop()
"""


class ShadowGateAuditor:
    TELEMETRY_TASK_FOLDERS = [
        r"\Microsoft\Windows\Customer Experience Improvement Program",
        r"\Microsoft\Windows\Application Experience"
    ]
    HOSTS_REDIRECTS = {
        'telemetry.intel.com': '0.0.0.0',
        'vortex.data.microsoft.com': '0.0.0.0',
        'telemetry.amd.com': '0.0.0.0'
    }
    FIREWALL_PORTS = '16992,16993,623,624,9998'

    def __init__(self, parent=None, amd_support=True):
        self.parent = parent
        self.results = {}
        self.amd_support = bool(amd_support)

    def _host_redirects(self):
        redirects = dict(self.HOSTS_REDIRECTS)
        if not self.amd_support:
            redirects.pop('telemetry.amd.com', None)
        return redirects

    def _run_process(self, args, timeout=45):
        try:
            proc = subprocess.run(args, capture_output=True, text=True, shell=False, timeout=timeout)
            return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
        except Exception as e:
            return -1, '', str(e)

    def _windows_available(self):
        return sys.platform.startswith('win')

    def _has_admin(self):
        if not self._windows_available():
            return False
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False

    def _list_telemetry_tasks(self):
        tasks = []
        if not self._windows_available():
            return tasks
        for folder in self.TELEMETRY_TASK_FOLDERS:
            query = (
                f"Try {{ Get-ScheduledTask -TaskPath '{folder}\\' | "
                "Select-Object -Property TaskName,TaskPath | ConvertTo-Json -Compress }} "
                "Catch { Write-Output '[]' }"
            )
            rc, out, err = self._run_process(['powershell', '-NoProfile', '-NonInteractive', '-Command', query])
            if rc != 0 or not out:
                continue
            try:
                data = json.loads(out)
            except Exception:
                continue
            if isinstance(data, dict):
                data = [data]
            for item in data:
                try:
                    path = item.get('TaskPath', '') or ''
                    name = item.get('TaskName', '') or ''
                    if path and name:
                        full = path + name
                        tasks.append(full)
                except Exception:
                    continue
        return sorted(set(tasks))

    def _disable_telemetry_tasks(self):
        result = {'found': [], 'disabled': [], 'deleted': [], 'errors': []}
        if not self._windows_available():
            result['status'] = 'unsupported'
            return result

        task_names = self._list_telemetry_tasks()
        result['found'] = task_names
        if not task_names:
            result['status'] = 'none_found'
            return result

        for task in task_names:
            rc, out, err = self._run_process(['schtasks', '/Change', '/TN', task, '/Disable'])
            if rc == 0:
                result['disabled'].append(task)
                continue
            rc2, out2, err2 = self._run_process(['schtasks', '/Delete', '/TN', task, '/F'])
            if rc2 == 0:
                result['deleted'].append(task)
                continue
            result['errors'].append({'task': task, 'error': err or out or err2 or out2})

        if result['errors']:
            result['status'] = 'partial'
        else:
            result['status'] = 'completed'
        return result

    def _apply_firewall_rules(self):
        result = {'created': [], 'errors': []}
        if not self._windows_available():
            result['status'] = 'unsupported'
            return result
        if not self._has_admin():
            result['status'] = 'no_admin'
            return result

        rules = [
            {'name': 'ForzeOS ShadowGate Privacy Hardening - Inbound TCP', 'dir': 'in', 'protocol': 'TCP'},
            {'name': 'ForzeOS ShadowGate Privacy Hardening - Outbound TCP', 'dir': 'out', 'protocol': 'TCP'},
            {'name': 'ForzeOS ShadowGate Privacy Hardening - Inbound UDP', 'dir': 'in', 'protocol': 'UDP'},
            {'name': 'ForzeOS ShadowGate Privacy Hardening - Outbound UDP', 'dir': 'out', 'protocol': 'UDP'},
        ]

        for rule in rules:
            delete_args = [
                'netsh', 'advfirewall', 'firewall', 'delete', 'rule',
                f"name={rule['name']}", 'dir=' + rule['dir'], 'protocol=' + rule['protocol']
            ]
            self._run_process(delete_args)

            add_args = [
                'netsh', 'advfirewall', 'firewall', 'add', 'rule',
                f"name={rule['name']}",
                'dir=' + rule['dir'],
                'action=block',
                'protocol=' + rule['protocol'],
                'localport=' + self.FIREWALL_PORTS,
                'remoteip=any',
                'profile=any',
                'enable=yes'
            ]
            rc, out, err = self._run_process(add_args)
            if rc == 0:
                result['created'].append(rule['name'])
            else:
                result['errors'].append({'rule': rule['name'], 'error': err or out})

        if result['errors']:
            result['status'] = 'partial'
        else:
            result['status'] = 'completed'
        return result

    def _update_hosts(self):
        result = {'added': [], 'existing': [], 'errors': []}
        if not self._windows_available():
            result['status'] = 'unsupported'
            return result
        if not self._has_admin():
            result['status'] = 'no_admin'
            return result

        hosts_path = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'drivers' / 'etc' / 'hosts'
        if not hosts_path.exists():
            result['status'] = 'missing_hosts'
            result['errors'].append('Hosts file not found')
            return result

        try:
            existing = set()
            with hosts_path.open('r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    text = line.strip()
                    if not text or text.startswith('#'):
                        continue
                    parts = text.split()
                    if len(parts) >= 2:
                        existing.add(parts[1].lower())

            add_lines = []
            for host, ip in self._host_redirects().items():
                if host.lower() in existing:
                    result['existing'].append(host)
                else:
                    add_lines.append(f"{ip} {host}\n")
                    result['added'].append(host)

            if add_lines:
                tmp = tempfile.NamedTemporaryFile('w', delete=False, suffix='.tmp', dir=str(hosts_path.parent), encoding='utf-8', newline='\n')
                try:
                    with hosts_path.open('r', encoding='utf-8', errors='replace') as old:
                        tmp.writelines(old.readlines())
                    tmp.writelines(add_lines)
                    tmp.close()
                    try:
                        os.replace(tmp.name, str(hosts_path))
                    except Exception as exc_replace:
                        try:
                            shutil.copyfile(tmp.name, str(hosts_path))
                            os.remove(tmp.name)
                        except Exception as exc_copy:
                            raise exc_copy from exc_replace
                except Exception:
                    try:
                        tmp.close()
                    except Exception:
                        pass
                    raise   

            result['status'] = 'completed'
            return result
            
        except Exception as exc:
            result['status'] = 'error'
            result['errors'].append(str(exc))
            return result

    def _rollback_firewall_rules(self):
        result = {'removed': [], 'errors': []}
        if not self._windows_available():
            result['status'] = 'unsupported'
            return result
        if not self._has_admin():
            result['status'] = 'no_admin'
            return result

        rule_names = [
            'ForzeOS ShadowGate Privacy Hardening - Inbound TCP',
            'ForzeOS ShadowGate Privacy Hardening - Outbound TCP',
            'ForzeOS ShadowGate Privacy Hardening - Inbound UDP',
            'ForzeOS ShadowGate Privacy Hardening - Outbound UDP'
        ]
        for rule in rule_names:
            rc, out, err = self._run_process(['netsh', 'advfirewall', 'firewall', 'delete', 'rule', f'name={rule}'])
            if rc == 0:
                result['removed'].append(rule)
            elif 'No rules match the specified criteria' not in (err or out):
                result['errors'].append({'rule': rule, 'error': err or out})

        result['status'] = 'completed' if not result['errors'] else 'partial'
        return result

    def _rollback_hosts(self):
        result = {'removed': [], 'errors': []}
        if not self._windows_available():
            result['status'] = 'unsupported'
            return result
        if not self._has_admin():
            result['status'] = 'no_admin'
            return result

        hosts_path = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'drivers' / 'etc' / 'hosts'
        if not hosts_path.exists():
            result['status'] = 'missing_hosts'
            result['errors'].append('Hosts file not found')
            return result

        try:
            lines = []
            removed_hosts = set(self._host_redirects().keys())
            with hosts_path.open('r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped or stripped.startswith('#'):
                        lines.append(line)
                        continue
                    parts = stripped.split()
                    if len(parts) >= 2 and parts[1].lower() in removed_hosts:
                        result['removed'].append(parts[1].lower())
                        continue
                    lines.append(line)

            if result['removed']:
                tmp = tempfile.NamedTemporaryFile('w', delete=False, suffix='.tmp', dir=str(hosts_path.parent), encoding='utf-8', newline='\n')
                try:
                    tmp.writelines(lines)
                    tmp.close()
                    try:
                        os.replace(tmp.name, str(hosts_path))
                    except Exception as exc_replace:
                        try:
                            shutil.copyfile(tmp.name, str(hosts_path))
                            os.remove(tmp.name)
                        except Exception as exc_copy:
                            raise exc_copy from exc_replace
                except Exception:
                    try:
                        tmp.close()
                    except Exception:
                        pass
                    raise

            result['status'] = 'completed'
            return result
        except Exception as exc:
            result['status'] = 'error'
            result['errors'].append(str(exc))
            return result

    def _rollback_telemetry_tasks(self):
        result = {'enabled': [], 'errors': []}
        if not self._windows_available():
            result['status'] = 'unsupported'
            return result
        if not self._has_admin():
            result['status'] = 'no_admin'
            return result

        task_names = self._list_telemetry_tasks()
        for task in task_names:
            rc, out, err = self._run_process(['schtasks', '/Change', '/TN', task, '/Enable'])
            if rc == 0:
                result['enabled'].append(task)
            else:
                result['errors'].append({'task': task, 'error': err or out})

        result['status'] = 'completed' if not result['errors'] else 'partial'
        return result

    def rollback(self):
        results = {'admin': self._has_admin()}
        results['hosts'] = self._rollback_hosts()
        results['firewall'] = self._rollback_firewall_rules()
        results['scheduler'] = self._rollback_telemetry_tasks()
        self._schedule_report(results)
        return results

    def _query_secure_boot(self):
        if not self._windows_available():
            return None
        query = (
            "Try { $x = Get-CimInstance -Namespace root\\Microsoft\\Windows\\Storage -ClassName MSFT_SecureBoot -ErrorAction Stop; "
            "if ($null -ne $x) { $x.SecureBootEnabled } else { Write-Output 'UNKNOWN' } } "
            "Catch { Write-Output 'UNKNOWN' }"
        )
        rc, out, _ = self._run_process(['powershell', '-NoProfile', '-NonInteractive', '-Command', query])
        if rc != 0 or not out:
            return None
        text = out.strip().lower()
        if text == 'true':
            return True
        if text == 'false':
            return False
        return None

    def _query_tpm(self):
        if not self._windows_available():
            return None
        query = (
            "Try { $x = Get-CimInstance -Namespace root\\cimv2 -ClassName Win32_Tpm -ErrorAction Stop; "
            "if ($null -ne $x -and $x.TpmPresent -eq $true) { $x.SpecVersion } else { Write-Output 'NONE' } } "
            "Catch { Write-Output 'NONE' }"
        )
        rc, out, _ = self._run_process(['powershell', '-NoProfile', '-NonInteractive', '-Command', query])
        if rc != 0 or not out:
            return None
        out = out.strip().lower()
        if out == 'none':
            return False
        return '2.0' in out

    def _query_hvci(self):
        if not self._windows_available():
            return None
        query = (
            "Try { $x = Get-CimInstance -Namespace root\\Microsoft\\Windows\\DeviceGuard -ClassName Win32_DeviceGuard -ErrorAction Stop; "
            "if ($null -ne $x -and $x.SecurityServicesRunning -ne $null) { $x.SecurityServicesRunning } else { Write-Output 'UNKNOWN' } } "
            "Catch { Write-Output 'UNKNOWN' }"
        )
        rc, out, _ = self._run_process(['powershell', '-NoProfile', '-NonInteractive', '-Command', query])
        if rc != 0 or not out:
            return None
        text = out.strip().lower()
        if text == 'unknown':
            return None
        try:
            value = int(text)
            return value != 0
        except Exception:
            return None

    def _format_bool(self, value):
        if value is True:
            return '[✓] AKTİF'
        if value is False:
            return '[X] PASİF'
        return '[!] BİLİNMEYEN'

    def _format_results(self, results):
        lines = []
        lines.append('Shadow-Gate Privacy Hardening Auditor Report')
        lines.append('=' * 54)
        lines.append(f'Platform: {"Windows" if self._windows_available() else "Unsupported"}')
        lines.append(f'Administrator: {self._format_bool(results.get("admin"))}')
        lines.append('')
        lines.append(f'Secure Boot: {self._format_bool(results.get("secure_boot"))}')
        lines.append(f'TPM 2.0: {self._format_bool(results.get("tpm_2"))}')
        lines.append(f'HVCI: {self._format_bool(results.get("hvci"))}')
        lines.append('')
        scheduler = results.get('scheduler', {})
        lines.append('Scheduled Task Hardening:')
        lines.append(f'  Status: {scheduler.get("status") or "unknown"}')
        if scheduler.get('found'):
            lines.append(f'  Found: {len(scheduler.get("found"))} task(s)')
            for task in scheduler.get('found', []):
                state = 'disabled' if task in scheduler.get('disabled', []) else ('deleted' if task in scheduler.get('deleted', []) else 'pending')
                lines.append(f'    - {task} ({state})')
        if scheduler.get('errors'):
            lines.append('  Errors:')
            for err in scheduler.get('errors', []):
                lines.append(f'    - {err}')
        lines.append('')
        firewall = results.get('firewall', {})
        lines.append('Firewall Hardening:')
        lines.append(f'  Status: {firewall.get("status") or "unknown"}')
        if firewall.get('created'):
            for rule in firewall.get('created', []):
                lines.append(f'    - {rule}')
        if firewall.get('errors'):
            lines.append('  Errors:')
            for err in firewall.get('errors', []):
                lines.append(f'    - {err}')
        lines.append('')
        hosts = results.get('hosts', {})
        lines.append('Hosts Sinkhole:')
        lines.append(f'  Status: {hosts.get("status") or "unknown"}')
        if hosts.get('added'):
            for host in hosts.get('added', []):
                lines.append(f'    - Added: {host}')
        if hosts.get('existing'):
            for host in hosts.get('existing', []):
                lines.append(f'    - Existing: {host}')
        if hosts.get('errors'):
            lines.append('  Errors:')
            for err in hosts.get('errors', []):
                lines.append(f'    - {err}')
        lines.append('')
        lines.append('BIOS Sıkılaştırma Rehberi:')
        lines.append('  Maksimum donanımsal gizlilik için bilgisayarınızı yeniden başlatıp BIOS ayarlarından')
        lines.append('  Intel ME / AMD PSP / WAN Radio seçeneklerini kapatabilirsiniz.')
        lines.append('')
        lines.append('Not: Bu modül yalnızca denetleyici olarak çalışır; Secure Boot, TPM ve HVCI ayarlarını değiştirmez.')
        return '\n'.join(lines)

    def _schedule_report(self, results):
        if self.parent is not None and hasattr(self.parent, 'after'):
            try:
                self.parent.after(0, lambda: self.show_report(results))
                return
            except Exception:
                pass
        self.show_report(results)

    def execute(self):
        results = {'admin': self._has_admin(), 'secure_boot': None, 'tpm_2': None, 'hvci': None}
        if not self._windows_available():
            results['reason'] = 'Only Windows is supported for Shadow-Gate auditing.'
            self._schedule_report(results)
            return results

        if not results['admin']:
            results['admin_note'] = 'Yönetici haklarına sahip değil. Ağ ve hosts düzeltmeleri çalışmayabilir.'

        results['scheduler'] = self._disable_telemetry_tasks()
        results['firewall'] = self._apply_firewall_rules()
        results['hosts'] = self._update_hosts()
        results['secure_boot'] = self._query_secure_boot()
        results['tpm_2'] = self._query_tpm()
        results['hvci'] = self._query_hvci()
        self._schedule_report(results)
        return results

    def show_report(self, results):
        try:
            win = tk.Toplevel(self.parent) if self.parent is not None else tk.Toplevel()
            win.title('Shadow-Gate Audit Report')
            win.geometry('760x560')
            frame = ttk.Frame(win)
            frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
            text = tk.Text(frame, wrap='word')
            text.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
            try:
                scrollbar = ttk.Scrollbar(frame, orient='vertical', command=text.yview)
                scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
                text.configure(yscrollcommand=scrollbar.set)
            except Exception:
                pass
            text.insert('1.0', self._format_results(results))
            text.configure(state=tk.DISABLED)
        except Exception:
            pass


PRIVACY_BACKUP_PATH = Path(__file__).with_name('shadowgate_backup.json')


class _PrivacyModule:
    """Reversible, capability-detected Windows controls for the Market UI."""
    name = 'Windows control'

    def __init__(self, parent=None):
        self.parent = parent

    def _windows_available(self):
        return sys.platform.startswith('win')

    def _run(self, args, timeout=30):
        try:
            kwargs = {
                'capture_output': True,
                'text': True,
                'shell': False,
                'timeout': timeout,
            }
            if sys.platform.startswith('win'):
                kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            proc = subprocess.run(args, **kwargs)
            return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
        except Exception as exc:
            return -1, '', str(exc)

    def _system_info(self):
        info = {'platform': platform.platform(), 'version': platform.win32_ver(), 'build': None}
        if self._windows_available():
            rc, out, _ = self._run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                "(Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion').CurrentBuild"])
            if rc == 0:
                info['build'] = out
        return info

    def _status(self, status, message='', **extra):
        result = {'status': status, 'message': message, 'system': self._system_info()}
        result.update(extra)
        return result

    def _admin_required(self):
        if not self._windows_available():
            return self._status('unsupported', 'Only Windows is supported.')
        try:
            if not ctypes.windll.shell32.IsUserAnAdmin():
                return self._status('requires_admin', 'Administrator permission is required.')
        except Exception:
            return self._status('requires_admin', 'Administrator permission is required.')
        return None

    def _backup(self, key, data):
        try:
            current = json.loads(PRIVACY_BACKUP_PATH.read_text(encoding='utf-8')) if PRIVACY_BACKUP_PATH.exists() else {}
            current.setdefault(key, {}).update(data)
            PRIVACY_BACKUP_PATH.write_text(json.dumps(current, indent=2), encoding='utf-8')
        except Exception:
            logger.exception('Privacy backup failed: %s', key)

    def _saved(self, key):
        try:
            return json.loads(PRIVACY_BACKUP_PATH.read_text(encoding='utf-8')).get(key, {})
        except Exception:
            return {}

    def _ps(self, command):
        return self._run(['powershell', '-NoProfile', '-NonInteractive', '-Command', command])

    def _read_dword(self, path, name):
        rc, out, _ = self._ps(f"$x=Get-ItemProperty -Path '{path}' -Name '{name}' -ErrorAction SilentlyContinue; if ($null -ne $x) {{ $x.{name} }}")
        return out if rc == 0 and out else None

    def _restore_dword(self, path, name, value):
        if value is None:
            self._ps(f"Remove-ItemProperty -Path '{path}' -Name '{name}' -ErrorAction SilentlyContinue")
        else:
            self._ps(f"New-Item -Path '{path}' -Force | Out-Null; New-ItemProperty -Path '{path}' -Name '{name}' -PropertyType DWord -Value {int(value)} -Force | Out-Null")

    def detect(self):
        return self._status('available' if self._windows_available() else 'unsupported',
                            'Windows capability is available.' if self._windows_available() else 'Only Windows is supported.')


class UpdateControlManager(_PrivacyModule):
    name = 'Windows Update control'
    SETTINGS_PATH = r'HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings'
    POLICY_PATH = r'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU'

    def detect(self):
        if not self._windows_available():
            return self._status('unsupported', 'Only Windows is supported.')
        rc, out, _ = self._ps("$p=Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\WindowsUpdate\\UX\\Settings' -ErrorAction SilentlyContinue; if ($p.PauseUpdatesExpiryTime) {'pause_native'}; if ($p.ActiveHoursStart -ne $null) {'active_hours'}")
        return self._status('available', 'Native settings detected.' if out else 'Legacy documented policy fallback available.', native=out.splitlines())

    def _service_type(self, service):
        _, out, _ = self._run(['sc.exe', 'qc', service])
        match = re.search(r'START_TYPE\s+:\s+\S+\s+(\w+)', out, re.I)
        return 'auto' if match and match.group(1).lower() in ('auto_start', 'automatic') else 'demand'

    def apply_update_control(self):
        blocked = self._admin_required()
        if blocked:
            return blocked
        try:
            self._backup('updates', {'service_type': self._service_type('wuauserv'), 'values': {
                'NoAutoRebootWithLoggedOnUsers': self._read_dword(self.POLICY_PATH, 'NoAutoRebootWithLoggedOnUsers'),
                'RebootWarningTimeout': self._read_dword(self.POLICY_PATH, 'RebootWarningTimeout'),
                'ActiveHoursStart': self._read_dword(self.SETTINGS_PATH, 'ActiveHoursStart'),
                'ActiveHoursEnd': self._read_dword(self.SETTINGS_PATH, 'ActiveHoursEnd')}})
            rc, out, err = self._run(['sc.exe', 'config', 'wuauserv', 'start=', 'demand'])
            if rc != 0:
                return self._status('error', err or out)
            rc, out, err = self._ps("New-Item -Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\WindowsUpdate\\AU' -Force | Out-Null; New-ItemProperty -Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\WindowsUpdate\\AU' -Name NoAutoRebootWithLoggedOnUsers -PropertyType DWord -Value 1 -Force | Out-Null; New-ItemProperty -Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\WindowsUpdate\\AU' -Name RebootWarningTimeout -PropertyType DWord -Value 30 -Force | Out-Null; New-Item -Path 'HKLM:\\SOFTWARE\\Microsoft\\WindowsUpdate\\UX\\Settings' -Force | Out-Null; New-ItemProperty -Path 'HKLM:\\SOFTWARE\\Microsoft\\WindowsUpdate\\UX\\Settings' -Name ActiveHoursStart -PropertyType DWord -Value 8 -Force | Out-Null; New-ItemProperty -Path 'HKLM:\\SOFTWARE\\Microsoft\\WindowsUpdate\\UX\\Settings' -Name ActiveHoursEnd -PropertyType DWord -Value 18 -Force | Out-Null")
            if rc != 0:
                return self._status('error', err or out)
            logger.info('Update control applied; build=%s', self._system_info().get('build'))
            return self._status('applied', 'Manual checking/install remain available; automatic restart is deferred.')
        except Exception as exc:
            logger.exception('Update control apply failed')
            return self._status('error', str(exc))

    def revert_update_control(self):
        blocked = self._admin_required()
        if blocked:
            return blocked
        try:
            self._run(['sc.exe', 'config', 'wuauserv', 'start=', self._saved('updates').get('service_type', 'auto')])
            values = self._saved('updates').get('values', {})
            self._restore_dword(self.POLICY_PATH, 'NoAutoRebootWithLoggedOnUsers', values.get('NoAutoRebootWithLoggedOnUsers'))
            self._restore_dword(self.POLICY_PATH, 'RebootWarningTimeout', values.get('RebootWarningTimeout'))
            self._restore_dword(self.SETTINGS_PATH, 'ActiveHoursStart', values.get('ActiveHoursStart'))
            self._restore_dword(self.SETTINGS_PATH, 'ActiveHoursEnd', values.get('ActiveHoursEnd'))
            logger.info('Update control reverted')
            return self._status('reverted', 'Windows Update service and policy were restored.')
        except Exception as exc:
            logger.exception('Update control revert failed')
            return self._status('error', str(exc))

    def check_updates(self):
        if not self._windows_available():
            return self._status('unsupported', 'Only Windows is supported.')
        try:
            os.system('start ms-settings:windowsupdate')
            logger.info('Opened native Windows Update settings for manual checking')
            return self._status('available', 'Native Windows Update settings opened; the user controls the scan.')
        except Exception as exc:
            logger.exception('Could not open Windows Update settings')
            return self._status('error', str(exc))

    def install_updates(self):
        if not self._windows_available():
            return self._status('unsupported', 'Only Windows is supported.')
        try:
            os.system('start ms-settings:windowsupdate')
            logger.info('Opened native Windows Update settings for manual installation')
            return self._status('available', 'Native Windows Update settings opened; install is user-controlled.')
        except Exception as exc:
            logger.exception('Could not open Windows Update settings')
            return self._status('error', str(exc))


class RecallSnapshotManager(_PrivacyModule):
    name = 'Recall snapshot protection'
    POLICY_PATH = r'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsAI'

    def detect(self):
        if not self._windows_available():
            return self._status('unsupported', 'Only Windows is supported.')
        rc, out, _ = self._ps("Get-WindowsOptionalFeature -Online -FeatureName Recall -ErrorAction SilentlyContinue | ConvertTo-Json -Compress")
        rc2, policy, _ = self._ps("if (Test-Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\WindowsAI') {'policy'}")
        feature_state = None
        try:
            feature_state = (json.loads(out) if out else {}).get('State')
        except Exception:
            pass
        exists = bool(out) or bool(policy)
        return self._status('available' if exists else 'not_applicable', 'Recall capability detected.' if exists else 'Recall is not present on this system.', feature=out, feature_state=feature_state)

    def apply_recall_control(self):
        blocked = self._admin_required()
        if blocked:
            return blocked
        detection = self.detect()
        if detection['status'] == 'not_applicable':
            return detection
        try:
            self._backup('recall', {
                'DisableAIDataAnalysis': self._read_dword(self.POLICY_PATH, 'DisableAIDataAnalysis'),
                'feature_state': detection.get('feature_state')
            })
            rc, out, err = self._ps('Disable-WindowsOptionalFeature -Online -FeatureName Recall -NoRestart -ErrorAction SilentlyContinue')
            if rc != 0:
                rc, out, err = self._ps("New-Item -Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\WindowsAI' -Force | Out-Null; New-ItemProperty -Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\WindowsAI' -Name DisableAIDataAnalysis -PropertyType DWord -Value 1 -Force | Out-Null")
            if rc != 0:
                return self._status('error', err or out)
            self._backup('recall', {'changed': True})
            logger.info('Recall protection applied')
            return self._status('applied', 'Recall snapshots disabled; restart may be required.')
        except Exception as exc:
            logger.exception('Recall apply failed')
            return self._status('error', str(exc))

    def revert_recall_control(self):
        blocked = self._admin_required()
        if blocked:
            return blocked
        try:
            saved = self._saved('recall')
            if 'feature_state' not in saved:
                logger.warning('Recall revert skipped feature state: backup is missing feature_state')
                self._restore_dword(self.POLICY_PATH, 'DisableAIDataAnalysis', saved.get('DisableAIDataAnalysis'))
                return self._status('warning', 'Backup lacks the original Recall feature state; feature state was left unchanged.')
            if str(saved.get('feature_state', '')).lower() == 'enabled':
                self._ps("Enable-WindowsOptionalFeature -Online -FeatureName Recall -NoRestart -ErrorAction SilentlyContinue")
            self._restore_dword(self.POLICY_PATH, 'DisableAIDataAnalysis', saved.get('DisableAIDataAnalysis'))
            logger.info('Recall protection reverted')
            return self._status('reverted', 'Recall feature was restored to its saved state and policy restored.')
        except Exception as exc:
            logger.exception('Recall revert failed')
            return self._status('error', str(exc))


class TelemetryManager(_PrivacyModule):
    name = 'Telemetry control'
    POLICY_PATH = r'HKLM:\SOFTWARE\Policies\Microsoft\Windows\DataCollection'

    def __init__(self, parent=None, amd_support=True, allow_hosts=False):
        super().__init__(parent)
        self.auditor = ShadowGateAuditor(parent, amd_support=amd_support)
        self.allow_hosts = allow_hosts

    def apply_telemetry_control(self):
        blocked = self._admin_required()
        if blocked:
            return blocked
        try:
            if self.allow_hosts and not hasattr(self.auditor, '_update_hosts'):
                logger.error('Hosts opt-in unavailable: ShadowGateAuditor has no _update_hosts method')
                return self._status('not_applicable', 'This version does not support hosts sinkhole changes.')
            self._backup('telemetry', {'service_type': self._service_type(), 'AllowTelemetry': self._read_dword(self.POLICY_PATH, 'AllowTelemetry')})
            self._run(['sc.exe', 'config', 'DiagTrack', 'start=', 'demand'])
            self._run(['reg.exe', 'add', r'HKLM\SOFTWARE\Policies\Microsoft\Windows\DataCollection', '/v', 'AllowTelemetry', '/t', 'REG_DWORD', '/d', '1', '/f'])
            if self.allow_hosts:
                hosts_result = self.auditor._update_hosts()
                if hosts_result.get('status') in ('error', 'unsupported', 'no_admin'):
                    return self._status('error', 'Hosts opt-in could not be applied; telemetry changes were not rolled back.')
            logger.info('Telemetry control applied; hosts opt-in=%s', self.allow_hosts)
            return self._status('applied', 'DiagTrack is manual and telemetry is set to Basic.')
        except Exception as exc:
            logger.exception('Telemetry apply failed')
            return self._status('error', str(exc))

    def revert_telemetry_control(self):
        blocked = self._admin_required()
        if blocked:
            return blocked
        try:
            self._run(['sc.exe', 'config', 'DiagTrack', 'start=', self._saved('telemetry').get('service_type', 'auto')])
            self._restore_dword(self.POLICY_PATH, 'AllowTelemetry', self._saved('telemetry').get('AllowTelemetry'))
            if self.allow_hosts:
                if not hasattr(self.auditor, '_rollback_hosts'):
                    logger.error('Hosts revert unavailable: ShadowGateAuditor has no _rollback_hosts method')
                    return self._status('not_applicable', 'This version does not support hosts sinkhole rollback.')
                hosts_result = self.auditor._rollback_hosts()
                if hosts_result.get('status') in ('error', 'unsupported', 'no_admin'):
                    return self._status('error', 'Hosts sinkhole rollback could not be completed.')
            logger.info('Telemetry control reverted')
            return self._status('reverted', 'DiagTrack, telemetry policy, and opted-in hosts entries restored.')
        except Exception as exc:
            logger.exception('Telemetry revert failed')
            return self._status('error', str(exc))

    def _service_type(self):
        _, out, _ = self._run(['sc.exe', 'qc', 'DiagTrack'])
        return 'auto' if re.search(r'START_TYPE\s+:\s+\S+\s+(AUTO_START|Automatic)', out, re.I) else 'demand'

    def detect(self):
        return self._status('available' if self._windows_available() else 'unsupported', 'DiagTrack and AllowTelemetry are documented controls.')


class AccountSetupHelper(_PrivacyModule):
    name = 'Local account setup'

    def apply_account_setup(self):
        if not self._windows_available():
            return self._status('unsupported', 'Only Windows is supported.')
        try:
            os.startfile('ms-cxh:localonly')
            logger.info('Opened official local account setup')
            return self._status('available', 'Official Microsoft local-account setup opened; no bypass was performed.')
        except Exception as exc:
            logger.exception('Account setup failed')
            return self._status('error', str(exc))

    def revert_account_setup(self):
        return self._status('reverted' if self._windows_available() else 'unsupported', 'This helper makes no persistent system change.')


class BloatwareManager(_PrivacyModule):
    name = 'Optional app removal'
    EXCLUDED = (
        'Microsoft.WindowsStore', 'Microsoft.WindowsDefender', 'Microsoft.SecHealthUI',
        'Microsoft.DesktopAppInstaller', 'Microsoft.Windows.ShellExperienceHost',
        'Microsoft.Windows.StartMenuExperienceHost',
        'Microsoft.VCLibs.140.00', 'Microsoft.WindowsAppRuntime', 'Microsoft.UI.Xaml',
        'Microsoft.NET.Native.Framework', 'Microsoft.NET.Native.Runtime', 'Microsoft.Windows.Photos',
        'Microsoft.Windows.CapturePicker', 'Microsoft.Windows.NarratorQuickStart',
        'Microsoft.AAD.BrokerPlugin', 'Microsoft.LockApp', 'Microsoft.Windows.CloudExperienceHost'
    )

    def _is_excluded(self, package_name):
        normalized = (package_name or '').lower()
        return any(normalized.startswith(prefix.lower()) for prefix in self.EXCLUDED)

    def list_packages(self):
        if not self._windows_available():
            return self._status('unsupported', 'Only Windows is supported.')
        rc, out, err = self._ps('Get-AppxPackage | Select-Object Name,PackageFullName,InstallLocation | ConvertTo-Json -Compress')
        if rc != 0:
            return self._status('error', err or out)
        try:
            packages = json.loads(out) if out else []
            if isinstance(packages, dict):
                packages = [packages]
            packages = [p for p in packages if not self._is_excluded(p.get('Name'))]
            return self._status('available', 'No package is selected automatically.', packages=packages)
        except Exception as exc:
            logger.exception('AppX list parsing failed')
            return self._status('error', str(exc))

    def apply_bloatware_removal(self, package_names):
        blocked = self._admin_required()
        if blocked:
            return blocked
        if not package_names:
            return self._status('not_applicable', 'No package selected.')
        try:
            available = self.list_packages().get('packages', [])
            selected = [p for p in available if p.get('Name') in package_names]
            self._backup('appx', {'packages': selected})
            for package in selected:
                self._ps(f"Remove-AppxPackage -Package '{package.get('PackageFullName')}' -ErrorAction Stop")
            logger.info('Explicitly selected AppX packages removed: %s', package_names)
            return self._status('applied', 'Selected packages removed for the current user.')
        except Exception as exc:
            logger.exception('AppX removal failed')
            return self._status('error', str(exc))

    def revert_bloatware_removal(self):
        blocked = self._admin_required()
        if blocked:
            return blocked
        restored = 0
        for package in self._saved('appx').get('packages', []):
            manifest = Path(package.get('InstallLocation', '')) / 'AppxManifest.xml'
            if manifest.exists() and self._ps(f"Add-AppxPackage -Register '{manifest}' -DisableDevelopmentMode")[0] == 0:
                restored += 1
        logger.info('AppX restore attempted; restored=%s', restored)
        return self._status('reverted', f'{restored} package manifest(s) restored; unavailable sources were skipped.')


class ForzeOSMarket(tk.Toplevel):
    """Application Store + Developer Editor Toplevel.

    parent: tk root or any widget
    forze: optional reference to ForzeOS instance for tighter integration
    """
    def __init__(self, parent, forze=None, base_dir=None):
        # Validate parent
        if not hasattr(parent, 'winfo_toplevel'):
            raise TypeError("Parent must be a tkinter widget")
            
        super().__init__(parent)
        
        # Store parameters
        self.parent = parent
        self.forze = forze
        self._base_dir = base_dir
        
        # Window management setup
        self.title('ForzeOS Market')
        self.geometry('1000x700')
        self.minsize(800, 500)
        
        # Configure window for proper minimize/maximize
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # Set up window states for taskbar integration
        if sys.platform.startswith('win'):
            self.attributes('-toolwindow', False)  # Allow minimize/maximize
            self.wm_overrideredirect(False)  # Show standard window decorations
            
        # If we're running inside ForzeOS, adopt its visual theme but DO NOT
        # register the window yet. Registration (and taskbar button creation)
        # will happen when the window actually maps (<Map>), avoiding
        # premature taskbar entries or style races.
        if self.forze:
            try:
                if hasattr(self.forze, 'apply_theme'):
                    self.forze.apply_theme(self)
            except Exception as e:
                print(f"ForzeOS integration error: {e}")
                
        # Bind standard window events
        self.bind('<Map>', self._on_map)
        self.bind('<Unmap>', self._on_unmap)
        
        # Ensure app folder exists
        APP_FOLDER.mkdir(parents=True, exist_ok=True)
        
        # Load/create config
        self.config = {
            'apps': [],
            'recent': [],
            'installed': set()
        }

        # --- Setup base attributes ---
        self.parent = parent
        self.forze = forze
        from pathlib import Path
        import os
        self.base_dir = Path(base_dir or (os.path.dirname(__file__) if '__file__' in globals() else os.getcwd()))
        self.title('ForzeOS Market')
        self.geometry('1000x700')
        self.minsize(800, 500)

        try:
            # If we're embedded inside ForzeOS (forze provided) we DO NOT
            # make the Toplevel transient; embedding host wants to manage
            # taskbar/button registration itself. Only make this transient
            # when running standalone (no host integration).
            if not self.forze:
                self.transient(parent)
        except Exception:
            pass

        # state
        self.market_data_path = self.base_dir / MARKET_DATA_FILENAME
        self.apps_dirs = [self.base_dir / 'apps', self.base_dir / 'market_apps']
        for d in self.apps_dirs:
            d.mkdir(parents=True, exist_ok=True)

        self.icon_cache = {}

        # UI layout
        self._build_ui()
        self.load_market_data()
        self.refresh_app_list()

    # ---------------- UI ----------------
    def _build_ui(self):
        # Top bar with search and actions
        top = ttk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=8, pady=6)

        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(top, textvariable=self.search_var)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,8))
        search_entry.bind('<KeyRelease>', lambda e: self.refresh_app_list())

        ttk.Button(top, text='Refresh', command=self.refresh_app_list).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text='Shadow-Gate Audit', command=self.run_shadowgate_audit).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text='Rollback ShadowGate', command=self.run_shadowgate_rollback).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text='Settings', command=self._open_settings).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text='New App', command=self._new_app_wizard).pack(side=tk.LEFT, padx=4)
        # Run as Tool: open recognized tool (organize_assets) in editor and run
        try:
            self.run_tool_btn = ttk.Button(top, text='Run as Tool', command=self.run_as_tool)
            self.run_tool_btn.pack(side=tk.LEFT, padx=4)
        except Exception:
            self.run_tool_btn = None

        # Main splitter: left categories, center content, right details/editor stack
        main_pane = ttk.Frame(self)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)

        # left categories
        left = ttk.Frame(main_pane, width=160)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0,8))
        left.pack_propagate(False)

        ttk.Label(left, text='Categories', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(2,6))
        self.cat_list = tk.Listbox(left, height=12)
        for c in ['All', 'Tools', 'Games', 'Utilities', 'Installed', 'Developer']:
            self.cat_list.insert(tk.END, c)
        self.cat_list.selection_set(0)
        self.cat_list.pack(fill=tk.Y, expand=True)
        self.cat_list.bind('<<ListboxSelect>>', lambda e: self.refresh_app_list())

        # center: app cards scroller
        center = ttk.Frame(main_pane)
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(center, borderwidth=0)
        self.cards_frame = ttk.Frame(self.canvas)
        vscroll = ttk.Scrollbar(center, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vscroll.set)

        vscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.cards_frame, anchor='nw')

        def on_config(e):
            if self.canvas.winfo_exists():
                self.canvas.configure(scrollregion=self.canvas.bbox('all'))
                
        def on_resize(e):
            if self.canvas.winfo_exists():
                self.canvas.itemconfig(self.canvas_window, width=e.width)
                
        self.cards_frame.bind('<Configure>', on_config)
        self.canvas.bind('<Configure>', on_resize)

        # right: tabs for details and developer editor
        # make it wider so developer tools fit
        right = ttk.Notebook(main_pane, width=480)
        right.pack(side=tk.LEFT, fill=tk.BOTH, padx=(8,0))

        # details tab
        self.detail_tab = ttk.Frame(right)
        right.add(self.detail_tab, text='Details')
        self.detail_text = tk.Text(self.detail_tab, wrap='word', height=20)
        self.detail_text.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.detail_text.configure(state=tk.DISABLED)

        # developer tab
        self.dev_tab = ttk.Frame(right)
        right.add(self.dev_tab, text='Developer')
        self._build_dev_tab(self.dev_tab)

        # Windows Privacy and Control Center
        self.privacy_tab = ttk.Frame(right)
        right.add(self.privacy_tab, text='Windows Privacy')
        self._build_privacy_tab(self.privacy_tab)

    def _build_privacy_tab(self, parent):
        self._privacy_managers = {
            'updates': UpdateControlManager(self),
            'recall': RecallSnapshotManager(self),
            'telemetry': TelemetryManager(self, allow_hosts=False),
            'account': AccountSetupHelper(self),
            'appx': BloatwareManager(self),
        }
        self._privacy_status_labels = {}
        self._privacy_controls = {}
        outer = ttk.Frame(parent)
        outer.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        canvas = tk.Canvas(outer, highlightthickness=0)
        scroll = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        body = ttk.Frame(canvas)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        canvas.create_window((0, 0), window=body, anchor='nw')
        body.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))

        cards = [
            ('updates', 'Update Control', 'updates'),
            ('recall', 'Recall Snapshot Protection', 'recall'),
            ('telemetry', 'Telemetry Control', 'telemetry'),
            ('account', 'Local Account Setup', 'account'),
            ('appx', 'Optional App Removal', 'appx'),
        ]
        for row, (key, title, kind) in enumerate(cards):
            card = ttk.LabelFrame(body, text=title, padding=6)
            card.grid(row=row, column=0, sticky='ew', padx=4, pady=4)
            body.columnconfigure(0, weight=1)
            status = ttk.Label(card, text='Checking...')
            status.grid(row=0, column=0, columnspan=4, sticky='w', pady=(0, 4))
            self._privacy_status_labels[key] = status
            controls = []
            if key == 'updates':
                apply_cmd = lambda: self._privacy_action('updates', 'apply_update_control')
                revert_cmd = lambda: self._privacy_action('updates', 'revert_update_control')
                check_button = ttk.Button(card, text='Check Updates', command=lambda: self._privacy_action('updates', 'check_updates'))
                install_button = ttk.Button(card, text='Install Now', command=lambda: self._privacy_action('updates', 'install_updates'))
                check_button.grid(row=1, column=0, padx=2)
                install_button.grid(row=1, column=1, padx=2)
                controls.extend((check_button, install_button))
            elif key == 'recall':
                apply_cmd = lambda: self._privacy_action('recall', 'apply_recall_control')
                revert_cmd = lambda: self._privacy_action('recall', 'revert_recall_control')
            elif key == 'telemetry':
                self._privacy_hosts_var = tk.BooleanVar(value=False)
                hosts_check = ttk.Checkbutton(card, text='Opt in to hosts sinkhole changes', variable=self._privacy_hosts_var)
                hosts_check.grid(row=1, column=0, columnspan=2, sticky='w')
                controls.append(hosts_check)
                apply_cmd = lambda: self._privacy_action('telemetry', 'apply_telemetry_control', self._set_hosts_opt_in())
                revert_cmd = lambda: self._privacy_action('telemetry', 'revert_telemetry_control')
            elif key == 'account':
                apply_cmd = lambda: self._privacy_action('account', 'apply_account_setup')
                revert_cmd = lambda: self._privacy_action('account', 'revert_account_setup')
            else:
                ttk.Label(card, text='Select packages below; nothing is selected automatically.').grid(row=1, column=0, columnspan=4, sticky='w')
                self._appx_vars = {}
                list_button = ttk.Button(card, text='List Apps', command=self._refresh_appx_choices)
                list_button.grid(row=2, column=0, padx=2, pady=2)
                controls.append(list_button)
                apply_cmd = lambda: self._privacy_action('appx', 'apply_bloatware_removal', [n for n, v in self._appx_vars.items() if v.get()])
                revert_cmd = lambda: self._privacy_action('appx', 'revert_bloatware_removal')
            ttk.Button(card, text='Apply', command=apply_cmd).grid(row=3, column=2, padx=2, pady=2, sticky='e')
            ttk.Button(card, text='Revert', command=revert_cmd).grid(row=3, column=3, padx=2, pady=2, sticky='e')
            controls.extend(card.grid_slaves(row=3))
            self._privacy_controls[key] = controls
        self._privacy_refresh_all()

    def _set_hosts_opt_in(self):
        value = bool(getattr(self, '_privacy_hosts_var', tk.BooleanVar(value=False)).get())
        self._privacy_managers['telemetry'].allow_hosts = value
        return None

    def _privacy_action(self, key, method, argument=None):
        manager = self._privacy_managers[key]
        label = manager.name
        if method.startswith('apply_') and not messagebox.askyesno(label, 'Apply this reversible change? An administrator prompt may appear.'):
            return
        if method.startswith('revert_') and not messagebox.askyesno(label, 'Revert the saved change?'):
            return
        self._privacy_set_busy(key, True)

        def worker():
            try:
                result = getattr(manager, method)(argument) if argument is not None else getattr(manager, method)()
            except Exception as exc:
                logger.exception('Privacy UI action failed: %s', method)
                result = {'status': 'error', 'message': str(exc)}
            try:
                self.after(0, lambda: self._privacy_finish_action(key, result))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True, name=f'forze-privacy-{key}').start()

    def _privacy_set_busy(self, key, busy):
        label = self._privacy_status_labels.get(key)
        if label and busy:
            label.configure(text='Working...')
        for control in self._privacy_controls.get(key, []):
            try:
                control.configure(state=tk.DISABLED if busy else tk.NORMAL)
            except Exception:
                pass

    def _privacy_finish_action(self, key, result):
        self._privacy_set_busy(key, False)
        self._privacy_set_status(key, result)

    def _privacy_set_status(self, key, result):
        status = (result or {}).get('status', 'unknown')
        message = (result or {}).get('message', '')
        text = f'{status}: {message}' if message else status
        label = self._privacy_status_labels.get(key)
        if label:
            label.configure(text=text)
            label.configure(foreground='#888888' if status in ('unsupported', 'not_applicable') else '')

    def _privacy_refresh_all(self):
        for key in self._privacy_managers:
            self._privacy_set_busy(key, True)
        for key, manager in self._privacy_managers.items():
            def worker(current_key=key, current_manager=manager):
                try:
                    result = current_manager.detect() if hasattr(current_manager, 'detect') else current_manager.list_packages()
                except Exception as exc:
                    logger.exception('Privacy status check failed: %s', current_key)
                    result = {'status': 'error', 'message': str(exc)}
                try:
                    self.after(0, lambda: self._privacy_finish_action(current_key, result))
                except Exception:
                    pass
            threading.Thread(target=worker, daemon=True, name=f'forze-privacy-detect-{key}').start()

    def _refresh_appx_choices(self):
        result = self._privacy_managers['appx'].list_packages()
        self._privacy_set_status('appx', result)
        label = self._privacy_status_labels['appx']
        parent = label.master
        for widget in list(parent.grid_slaves()):
            info = widget.grid_info()
            if int(info.get('row', 0)) >= 4:
                widget.destroy()
        self._appx_vars.clear()
        for row, package in enumerate(result.get('packages', [])[:80], start=4):
            name = package.get('Name') or package.get('PackageFullName')
            if name:
                var = tk.BooleanVar(value=False)
                self._appx_vars[name] = var
                ttk.Checkbutton(parent, text=name, variable=var).grid(row=row, column=0, columnspan=4, sticky='w')

    def _build_dev_tab(self, parent):
        # Toolbar: use a horizontally scrollable toolbar so buttons never overflow
        toolbar_outer = ttk.Frame(parent)
        toolbar_outer.pack(side=tk.TOP, fill=tk.X, padx=6, pady=4)
        toolbar_canvas = tk.Canvas(toolbar_outer, height=34)
        toolbar_canvas.pack(side=tk.LEFT, fill=tk.X, expand=True)
        toolbar_hsb = ttk.Scrollbar(toolbar_outer, orient='horizontal', command=toolbar_canvas.xview)
        toolbar_hsb.pack(side=tk.BOTTOM, fill=tk.X)
        toolbar_canvas.configure(xscrollcommand=toolbar_hsb.set)
        toolbar_inner = ttk.Frame(toolbar_canvas)
        toolbar_canvas.create_window((0,0), window=toolbar_inner, anchor='nw')

        def _on_toolbar_config(e):
            try:
                toolbar_canvas.configure(scrollregion=toolbar_canvas.bbox('all'))
            except Exception:
                pass
        toolbar_inner.bind('<Configure>', _on_toolbar_config)

        # Buttons
        ttk.Button(toolbar_inner, text='Open', command=self.dev_open_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar_inner, text='Save', command=self.dev_save_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar_inner, text='Save as App', command=self.dev_save_as_app).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar_inner, text='Run', command=self.dev_run_code).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar_inner, text='Template', command=self._open_settings).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar_inner, text='Open in Host Editor', command=self.open_in_host_editor).pack(side=tk.LEFT, padx=2)

        # Use a PanedWindow so the code editor and output area are resizable vertically
        pw = ttk.Panedwindow(parent, orient=tk.VERTICAL)
        pw.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0,6))

        # Code editor
        editor_frame = ttk.Frame(pw)
        self.dev_filename = None
        self.dev_text = tk.Text(editor_frame, wrap='none')
        self.dev_text.pack(fill=tk.BOTH, expand=True)
        pw.add(editor_frame, weight=3)

        # simple traceback/output area
        out_frame = ttk.Frame(pw)
        ttk.Label(out_frame, text='Output / Debug').pack(anchor='w')
        self.dev_output = tk.Text(out_frame, wrap='word', height=10, bg='#111', fg='#eee')
        self.dev_output.pack(fill=tk.BOTH, expand=True)
        pw.add(out_frame, weight=1)

    # ---------------- Data ----------------
    def load_market_data(self):
        self.market_data = {}
        try:
            if self.market_data_path.exists():
                with open(self.market_data_path, 'r', encoding='utf-8') as f:
                    self.market_data = json.load(f)
        except Exception as e:
            logger.exception('forze_market.load_market_data failed: %s', e)
            self.market_data = {}
        # ensure template and ShadowGate configuration keys exist
        try:
            if 'template' not in self.market_data:
                self.market_data.setdefault('template', MARKET_DEFAULT_TEMPLATE)
            if 'shadowgate' not in self.market_data or not isinstance(self.market_data.get('shadowgate'), dict):
                self.market_data['shadowgate'] = {'enabled': True, 'amd_support': True}
            else:
                self.market_data['shadowgate'].setdefault('enabled', True)
                self.market_data['shadowgate'].setdefault('amd_support', True)
        except Exception:
            pass

    def save_market_data(self):
        try:
            # atomic write: write to temp file then replace
            tmp = self.market_data_path.with_suffix(self.market_data_path.suffix + '.tmp')
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.market_data, f, indent=2)
            try:
                os.replace(str(tmp), str(self.market_data_path))
            except Exception:
                # fallback to rename
                tmp.rename(self.market_data_path)
        except Exception:
            logger.exception('forze_market.save_market_data failed')

    def discover_apps(self):
        """Return list of app dicts with keys: name, path, icon, desc
        Uses a simple in-memory cache to avoid repeated disk scans when
        called frequently (refresh_app_list will clear cache when needed)."""
        apps = []
        seen = set()
        try:
            # cached version for small delay
            now = time.time()
            if hasattr(self, '_apps_cache'):
                cached, ts = self._apps_cache
                if now - ts < 1.0:
                    return list(cached)
        except Exception as e:
            logger.exception('forze_market.discover_apps cache check failed: %s', e)

        # First, include explicit market_data entries
        try:
            for k, v in (self.market_data.get('apps') or {}).items():
                p = v.get('path')
                if not p:
                    continue
                full = os.path.join(self.base_dir, p) if not os.path.isabs(p) else p
                apps.append({'name': k, 'path': full, 'icon': v.get('icon'), 'desc': v.get('desc', '')})
                seen.add(k.lower())
        except Exception:
            pass

        # Next, scan apps directories for .py files
        for d in self.apps_dirs:
            try:
                for p in sorted(d.glob('*.py')):
                    name = p.stem
                    if name.lower() in seen:
                        continue
                    apps.append({'name': name, 'path': str(p), 'icon': None, 'desc': ''})
                    seen.add(name.lower())
            except Exception:
                pass

        # Ensure organize_assets.py appears first if present near market
        try:
            org_path = self.base_dir / 'tools' / 'organize_assets.py'
            if not org_path.exists():
                org_path = self.base_dir / 'organize_assets.py'
            if org_path.exists():
                apps.insert(0, {'name': 'organize_assets', 'path': str(org_path), 'icon': None, 'desc': 'Project modularizer / asset manager'})
        except Exception:
            pass

        # Built-in ShadowGate audit app appears near organize_assets when enabled
        try:
            if self.market_data.get('shadowgate', {}).get('enabled', True):
                shadowgate_entry = {
                    'name': 'ShadowGate Audit',
                    'path': '__shadowgate_audit__',
                    'icon': None,
                    'desc': 'Privacy hardening auditor for telemetry, firewall and firmware checks'
                }
                if apps and apps[0].get('name') == 'organize_assets':
                    apps.insert(1, shadowgate_entry)
                else:
                    apps.insert(0, shadowgate_entry)
        except Exception:
            pass

        # update cache
        try:
            self._apps_cache = (list(apps), time.time())
        except Exception as e:
            logger.exception('forze_market.discover_apps cache set failed: %s', e)

        return apps

    # ---------------- UI actions ----------------
    def refresh_app_list(self):
        # clear cards
        for c in self.cards_frame.winfo_children():
            c.destroy()

        # show loading status
        try:
            self._print_output('[ui] Refreshing app list...\n')
            self.status.config(text='Loading...')
        except Exception:
            pass

        apps = self.discover_apps()
        q = self.search_var.get().lower().strip()
        sel_cat = None
        try:
            sel_cat = self.cat_list.get(self.cat_list.curselection())
        except Exception:
            sel_cat = 'All'

        row = 0; col = 0; max_cols = 2
        # Basic filtering + fuzzy matching for typos
        filtered = []
        names = [ (a.get('name') or '').lower() for a in apps ]
        for a in apps:
            name = (a.get('name') or '')
            lname = name.lower()
            if not q or q in lname or q in (a.get('desc') or '').lower():
                filtered.append(a)
        # If query non-empty and no direct matches, use fuzzy finder to suggest close names
        if q and not filtered:
            try:
                candidates = difflib.get_close_matches(q, names, n=6, cutoff=0.6)
                for c in candidates:
                    for a in apps:
                        if (a.get('name') or '').lower() == c and a not in filtered:
                            filtered.append(a)
            except Exception:
                pass

        for a in filtered:
            name = a.get('name') or ''
            if sel_cat and sel_cat != 'All' and sel_cat != 'Installed' and sel_cat != 'Developer':
                # simple category heuristics
                if sel_cat == 'Tools' and 'tool' not in (a.get('desc') or '').lower() and 'tool' not in name.lower():
                    continue
                if sel_cat == 'Games' and 'game' not in (a.get('desc') or '').lower() and 'game' not in name.lower():
                    continue

            frame = ttk.Frame(self.cards_frame, relief=tk.RIDGE, borderwidth=1, padding=8)
            frame.grid(row=row, column=col, padx=8, pady=8, sticky='nsew')
            # icon
            ico_lbl = ttk.Label(frame)
            ico_lbl.pack(side=tk.TOP)
            img = self._get_icon_image(a.get('icon') or a.get('path'))
            if img:
                ico_lbl.config(image=img)
                ico_lbl.image = img

            # title
            ttk.Label(frame, text=name, font=('Segoe UI', 11, 'bold')).pack(anchor='w', pady=(6,0))
            ttk.Label(frame, text=(a.get('desc') or ''), wraplength=240).pack(anchor='w', pady=(4,8))

            btns = ttk.Frame(frame)
            btns.pack(fill=tk.X)
            ttk.Button(btns, text='Open', command=lambda p=a.get('path'): self.open_app(p)).pack(side=tk.LEFT, padx=2)
            ttk.Button(btns, text='Edit', command=lambda p=a.get('path'): self.dev_open_path(p)).pack(side=tk.LEFT, padx=2)
            ttk.Button(btns, text='Remove', command=lambda p=a.get('path'), n=name: self.remove_app(p, n)).pack(side=tk.LEFT, padx=2)

            col += 1
            if col >= max_cols:
                col = 0; row += 1
        try:
            self.status.config(text='Ready')
        except Exception:
            pass

    def _get_icon_image(self, candidate):
        if not candidate:
            return None
        try:
            key = str(candidate)
            if key in self.icon_cache:
                return self.icon_cache[key]
            p = Path(candidate)
            if not p.exists():
                # try inside assets
                p2 = self.base_dir / 'assets' / 'market_icons' / (p.name)
                if p2.exists():
                    p = p2
            if p.exists() and PIL_AVAILABLE:
                img = Image.open(p).convert('RGBA')
                img.thumbnail((64,64), Image.Resampling.LANCZOS)
                tkimg = ImageTk.PhotoImage(img)
                self.icon_cache[key] = tkimg
                return tkimg
        except Exception:
            pass
        return None

    def open_app(self, path):
        try:
            if not path:
                return
            if os.path.isdir(path):
                # open folder
                try:
                    if sys.platform.startswith('win'):
                        os.startfile(path)
                        return
                except Exception:
                    pass
            if path == '__shadowgate_audit__':
                return self.run_shadowgate_audit()

            # If this was launched inside ForzeOS instance, prefer using its opener
            if self.forze and hasattr(self.forze, 'open_script'):
                try:
                    self.forze.open_script(path)
                    return
                except Exception:
                    pass

            # fallback: spawn a subprocess running the script
            if path.endswith('.py'):
                subprocess.Popen([sys.executable, path], cwd=os.path.dirname(path))
            else:
                # try open with system
                try:
                    if sys.platform.startswith('win'):
                        os.startfile(path)
                    else:
                        subprocess.Popen(['xdg-open', path])
                except Exception:
                    messagebox.showinfo('Open', f'Cannot open: {path}')
        except Exception as e:
            messagebox.showerror('Error', f'Failed to open app: {e}')

    def dev_open_file(self):
        p = filedialog.askopenfilename(title='Open Python file', filetypes=[('Python','*.py')])
        if p:
            self.dev_open_path(p)

    def dev_open_path(self, path):
        try:
            # Prefer host code editor integration when available
            if self.forze and hasattr(self.forze, 'open_code_editor'):
                try:
                    # host may open an editor window; still load into dev tab too
                    self.forze.open_code_editor(path)
                except Exception:
                    pass
            with open(path, 'r', encoding='utf-8') as f:
                txt = f.read()
            self.dev_text.delete('1.0', tk.END)
            self.dev_text.insert('1.0', txt)
            self.dev_filename = path
            self._show_in_details(f'Editing: {path}')
        except Exception as e:
            messagebox.showerror('Error', f'Could not open file: {e}')

    def dev_save_file(self):
        try:
            if not self.dev_filename:
                return self.dev_save_as()
            with open(self.dev_filename, 'w', encoding='utf-8') as f:
                f.write(self.dev_text.get('1.0', tk.END))
            self._print_output(f'Saved: {self.dev_filename}\n')
        except Exception as e:
            messagebox.showerror('Error', f'Could not save file: {e}')

    def dev_save_as(self):
        p = filedialog.asksaveasfilename(defaultextension='.py', filetypes=[('Python','*.py')])
        if not p:
            return
        self.dev_filename = p
        self.dev_save_file()

    def open_in_host_editor(self):
        """Open the current dev editor file in the host editor if available.
        Falls back to external open. Shows a single warning/message if unavailable.
        """
        if not getattr(self, 'dev_filename', None):
            try:
                messagebox.showwarning('No file', 'No file is loaded in the developer editor')
            except Exception:
                self._print_output('[host editor] no file loaded\n')
            return
        path = self.dev_filename
        try:
            # Prefer host code editor if available
            if self.forze and hasattr(self.forze, 'open_code_editor'):
                try:
                    self.forze.open_code_editor(path)
                    return
                except Exception:
                    pass
            if self.forze and hasattr(self.forze, 'open_script'):
                try:
                    self.forze.open_script(path)
                    return
                except Exception:
                    pass
        except Exception:
            pass

        # Fallback to external open
        try:
            if sys.platform.startswith('win'):
                os.startfile(path)
            else:
                subprocess.Popen(['xdg-open', path])
        except Exception as e:
            try:
                messagebox.showinfo('Open', f'Could not open in host editor: {e}')
            except Exception:
                self._print_output(f'[host editor] not available: {e}\n')

    def dev_save_as_app(self):
        # Save current code into apps/ as new module
        try:
            name = simple_input = None
            try:
                name = simpledialog.askstring('New App', 'Enter app module name (no .py):')
            except Exception:
                name = None
            if not name:
                return
            fname = f"{name}.py"
            dst = self.base_dir / 'apps' / fname
            if dst.exists() and not messagebox.askyesno('Overwrite', f'{dst} exists. Overwrite?'):
                return
            with open(dst, 'w', encoding='utf-8') as f:
                f.write(self.dev_text.get('1.0', tk.END))
            # add market_data entry
            self.market_data.setdefault('apps', {})[name] = {'path': str(dst.relative_to(self.base_dir)), 'desc': 'User added app'}
            self.save_market_data()
            self.refresh_app_list()
            self._print_output(f'App saved: {dst}\n')
        except Exception as e:
            messagebox.showerror('Error', f'Could not save as app: {e}')

    def dev_run_code(self):
        src = self.dev_text.get('1.0', tk.END)
        # Run in a separate thread to avoid blocking UI
        def _run():
            self._print_output('--- Running code ---\n')
            try:
                # Prepare globals and ensure imports are executed first
                glb = {'__name__': '__main__'}
                loc = {}

                # If file has a known filename, add its dir to sys.path so relative imports work
                cwd = None
                try:
                    if self.dev_filename:
                        cwd = os.path.dirname(self.dev_filename)
                        if cwd and cwd not in sys.path:
                            sys.path.insert(0, cwd)
                except Exception:
                    cwd = None

                # Extract import lines and attempt to import them first
                try:
                    imports = []
                    for m in re.finditer(r"^\s*(from\s+[^\n]+|import\s+[^\n]+)", src, flags=re.MULTILINE):
                        line = m.group(1).strip()
                        if line and line not in imports:
                            imports.append(line)
                    for imp in imports:
                        try:
                            # Execute the import line in the globals so names are available
                            exec(imp, glb)
                            self._print_output(f'[import] {imp}\n')
                        except Exception as ie:
                            # report import error but continue — some imports may be optional
                            self._print_output(f'[import error] {imp}: {ie}\n')
                except Exception as e:
                    self._print_output(f'[import extraction error] {e}\n')

                # If code looks like a Tkinter app (creates Tk or mainloop), run it in subprocess
                looks_like_tk = False
                try:
                    lower = src.lower()
                    if 'import tkinter' in lower or 'from tkinter' in lower or '.mainloop(' in lower or 'tkinter.t' in lower or 'tk.' in lower:
                        looks_like_tk = True
                except Exception:
                    looks_like_tk = False

                if looks_like_tk:
                    # write to temp file and run as subprocess to avoid blocking/closing this UI
                    try:
                        tf = tempfile.NamedTemporaryFile('w', delete=False, suffix='.py', encoding='utf-8')
                        tf.write(src)
                        tf.flush(); tf.close()
                        self._print_output(f'[subprocess] launching temporary script {tf.name}\n')
                        p = subprocess.Popen([sys.executable, tf.name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                        out, err = p.communicate()
                        try:
                            if out:
                                self._print_output(out + '\n')
                            if err:
                                self._print_output('--- Error ---\n' + err + '\n')
                        finally:
                            # Attempt to clean up the temporary file
                            try:
                                os.unlink(tf.name)
                                self._print_output(f'[tempfile] removed {tf.name}\n')
                            except Exception:
                                pass
                    except Exception as se:
                        self._print_output(f'[subprocess launch error] {se}\n')
                else:
                    # Execute in-process (non-blocking thread) after imports
                    try:
                        exec(compile(src, '<string>', 'exec'), glb, loc)
                        self._print_output('--- Execution finished ---\n')
                    except Exception:
                        tb = traceback.format_exc()
                        self._print_output(tb)
            except Exception:
                tb = traceback.format_exc()
                self._print_output(tb)

        threading.Thread(target=_run, daemon=True).start()

    def _print_output(self, text: str):
        try:
            self.dev_output.insert('end', text)
            self.dev_output.see('end')
        except Exception:
            pass

    # ---------------- Simple Cart / Checkout ----------------
    def _ensure_cart(self):
        try:
            if not hasattr(self, 'cart'):
                self.cart = []
        except Exception:
            self.cart = []

    def add_to_cart(self, app_entry):
        try:
            self._ensure_cart()
            self.cart.append(app_entry)
            self._print_output(f'[cart] Added {app_entry.get("name") if isinstance(app_entry, dict) else str(app_entry)}\n')
        except Exception:
            pass

    def show_cart(self):
        try:
            self._ensure_cart()
            win = tk.Toplevel(self)
            win.title('Cart / Checkout')
            win.geometry('480x420')
            frame = ttk.Frame(win)
            frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
            lb = tk.Listbox(frame)
            lb.pack(fill=tk.BOTH, expand=True)
            for it in self.cart:
                try:
                    lb.insert(tk.END, it.get('name') if isinstance(it, dict) else str(it))
                except Exception:
                    lb.insert(tk.END, str(it))

            details = ttk.Frame(win)
            details.pack(fill=tk.X, padx=8, pady=6)
            ttk.Label(details, text='Name:').grid(row=0, column=0, sticky='w')
            name_var = tk.StringVar()
            ttk.Entry(details, textvariable=name_var).grid(row=0, column=1, sticky='we')
            ttk.Label(details, text='Email:').grid(row=1, column=0, sticky='w')
            email_var = tk.StringVar()
            ttk.Entry(details, textvariable=email_var).grid(row=1, column=1, sticky='we')
            details.columnconfigure(1, weight=1)

            def _checkout():
                try:
                    if not self.cart:
                        messagebox.showwarning('Cart', 'Cart is empty')
                        return
                    # Minimal single-page checkout: gather name/email and confirm
                    buyer = name_var.get().strip() or 'Customer'
                    email = email_var.get().strip()
                    messagebox.showinfo('Order', f'Order placed for {buyer}\nItems: {len(self.cart)}\nEmail: {email or "(not provided)"}')
                    self.cart = []
                    win.destroy()
                except Exception as e:
                    messagebox.showerror('Checkout error', str(e))

            btns = ttk.Frame(win)
            btns.pack(fill=tk.X, padx=8, pady=6)
            ttk.Button(btns, text='Checkout', command=_checkout).pack(side=tk.RIGHT)
            ttk.Button(btns, text='Close', command=win.destroy).pack(side=tk.RIGHT, padx=6)
        except Exception:
            pass

    def run_as_tool(self):
        """Open organize_assets (if present) in the editor and run it as a tool.

        If ForzeOS host is available and exposes run_script_embedded, use it
        for tighter integration. Otherwise run as subprocess.
        """
        try:
            apps = self.discover_apps()
            path = None
            for a in apps:
                try:
                    pname = a.get('name', '').lower()
                    if 'organize_assets' in pname or a.get('path', '').endswith('organize_assets.py'):
                        path = a.get('path')
                        break
                except Exception:
                    continue
            if not path:
                try:
                    messagebox.showinfo('Run as Tool', 'No organize_assets tool found in Market.')
                except Exception:
                    pass
                return

            # open in dev editor
            try:
                with open(path, 'r', encoding='utf-8') as fh:
                    src = fh.read()
                self.dev_text.delete('1.0', tk.END)
                self.dev_text.insert('1.0', src)
                self.dev_filename = path
                self._print_output(f'Loaded tool: {path}\n')
            except Exception:
                pass

            # run via host if possible
            try:
                if self.forze and hasattr(self.forze, 'run_script_embedded'):
                    try:
                        ok = self.forze.run_script_embedded(path)
                        if ok:
                            self._print_output('Tool executed via host run_script_embedded\n')
                            return
                    except Exception:
                        pass
            except Exception:
                pass

            # fallback: spawn subprocess
            try:
                import subprocess, sys
                subprocess.Popen([sys.executable, path], cwd=os.path.dirname(path))
                self._print_output('Tool launched as subprocess\n')
            except Exception as e:
                self._print_output(f'Failed to run tool: {e}\n')
        except Exception:
            pass

    def run_shadowgate_audit(self):
        try:
            amd_support = self.market_data.get('shadowgate', {}).get('amd_support', True)
            auditor = ShadowGateAuditor(parent=self, amd_support=amd_support)
            threading.Thread(target=auditor.execute, daemon=True).start()
        except Exception as e:
            messagebox.showerror('Shadow-Gate Audit', f'Başlatılamadı: {e}')

    def run_shadowgate_rollback(self):
        try:
            auditor = ShadowGateAuditor(parent=self, amd_support=self.market_data.get('shadowgate', {}).get('amd_support', True))
            threading.Thread(target=auditor.rollback, daemon=True).start()
        except Exception as e:
            messagebox.showerror('Shadow-Gate Rollback', f'Başlatılamadı: {e}')

    def remove_app(self, path, name):
        try:
            if not messagebox.askyesno('Remove', f'Remove {name}? This will delete the file.'):
                return
            if os.path.exists(path):
                os.remove(path)
            # remove from market data
            try:
                apps = self.market_data.get('apps', {})
                if name in apps:
                    del apps[name]
                    self.save_market_data()
            except Exception:
                pass
            self.refresh_app_list()
        except Exception as e:
            messagebox.showerror('Error', f'Could not remove: {e}')

    # ---------------- helper dialogs ----------------

    def _new_app_wizard(self):
        # Simple wizard: ask name, create starter template in dev editor
        name = simpledialog.askstring('New App', 'App name (module name, no .py):')
        if not name:
            return
        # allow user-custom template stored in market_data
        try:
            tmpl = (self.market_data.get('template') if hasattr(self, 'market_data') else None) or MARKET_DEFAULT_TEMPLATE
            template = tmpl.format(name=name)
        except Exception:
            template = MARKET_DEFAULT_TEMPLATE.format(name=name)
        self.dev_text.delete('1.0', tk.END)
        self.dev_text.insert('1.0', template)
        self.dev_filename = None

    def _open_settings(self):
        """Open settings dialog to edit market template and ShadowGate configuration."""
        try:
            win = tk.Toplevel(self)
            win.title('Market Settings')
            win.geometry('760x560')

            container = ttk.Frame(win)
            container.pack(fill='both', expand=True, padx=8, pady=8)

            ttk.Label(container, text='Market Template', font=('Segoe UI', 11, 'bold')).pack(anchor='w', pady=(0, 6))
            txt = tk.Text(container, wrap='none', height=14)
            txt.pack(fill='both', expand=False)
            current = (self.market_data.get('template') if hasattr(self, 'market_data') else None) or MARKET_DEFAULT_TEMPLATE
            txt.delete('1.0', tk.END)
            txt.insert('1.0', current)

            shadowgate = self.market_data.get('shadowgate', {})
            enabled_var = tk.BooleanVar(value=shadowgate.get('enabled', True))
            amd_support_var = tk.BooleanVar(value=shadowgate.get('amd_support', True))

            chk_frame = ttk.Frame(container)
            chk_frame.pack(fill='x', pady=8)
            ttk.Checkbutton(chk_frame, text='Enable built-in ShadowGate Audit app', variable=enabled_var).pack(anchor='w', pady=2)
            ttk.Checkbutton(chk_frame, text='Enable AMD telemetry sinkhole support', variable=amd_support_var).pack(anchor='w', pady=2)

            ttk.Label(container, text='If AMD telemetry support is disabled, telemetry.amd.com will not be altered.', wraplength=720).pack(anchor='w', pady=(0,6))

            def _save():
                try:
                    val = txt.get('1.0', 'end-1c')
                    if not hasattr(self, 'market_data'):
                        self.market_data = {}
                    self.market_data['template'] = val
                    self.market_data.setdefault('shadowgate', {})['enabled'] = enabled_var.get()
                    self.market_data.setdefault('shadowgate', {})['amd_support'] = amd_support_var.get()
                    try:
                        self.save_market_data()
                    except Exception:
                        pass
                    self.refresh_app_list()
                    win.destroy()
                    self._print_output('[settings] Market settings saved\n')
                except Exception as e:
                    messagebox.showerror('Error', f'Could not save settings: {e}')

            button_frame = ttk.Frame(container)
            button_frame.pack(fill='x', pady=8)
            ttk.Button(button_frame, text='Save Settings', command=_save).pack(side='left', padx=2)
            ttk.Button(button_frame, text='Run ShadowGate Rollback', command=self.run_shadowgate_rollback).pack(side='left', padx=2)
        except Exception as e:
            messagebox.showerror('Error', f'Failed to open settings: {e}')

    def _show_in_details(self, text):
        try:
            self.detail_text.configure(state=tk.NORMAL)
            self.detail_text.delete('1.0', tk.END)
            self.detail_text.insert('1.0', text)
            self.detail_text.configure(state=tk.DISABLED)
        except Exception:
            pass
            
    def _on_map(self, event=None):
        """Handle window showing"""
        # When mapped, register with host and request the taskbar button.
        # This mirrors other apps' lifecycle: register/create-button on open/map.
        if self.forze:
            try:
                logger.debug("ForzeOSMarket._on_map: mapped (forze=%s)", bool(self.forze))
                # Prefer the host's register_window API which can atomically
                # register and add a taskbar button when add_button=True.
                icon = None
                try:
                    icon = self.forze.get_app_icon('ForzeOS Market') if hasattr(self.forze, 'get_app_icon') else None
                except Exception:
                    icon = None
                if hasattr(self.forze, 'register_window'):
                    try:
                        self.forze.register_window(self, 'ForzeOS Market', icon=icon, add_button=True)
                    except TypeError:
                        # fallback to older signature
                        self.forze.register_window(self, 'ForzeOS Market', icon=icon)
            except Exception:
                pass

            # Notify host about map event (after registration)
            try:
                if hasattr(self.forze, 'on_window_map'):
                    self.forze.on_window_map(self)
            except Exception:
                pass
            
    def _on_unmap(self, event=None):
        """Handle window hiding"""
        if event is not None and event.widget is not self:
            return
        try:
            if str(self.wm_state()) != 'iconic':
                return
        except Exception:
            pass
        # Notify host the window was hidden/unmapped and mark as minimized so
        # the taskbar state remains consistent (button stays visible).
        if self.forze:
            try:
                logger.debug("ForzeOSMarket._on_unmap: unmapped (forze=%s)", bool(self.forze))
                if hasattr(self.forze, 'on_window_unmap'):
                    self.forze.on_window_unmap(self)
            except Exception:
                pass
            try:
                if hasattr(self.forze, 'minimize_window'):
                    # Keep taskbar button present; host will mark it minimized.
                    self.forze.minimize_window(self)
            except Exception:
                pass
            
    def _on_close(self):
        """Handle window closing"""
        try:
            logger.debug("ForzeOSMarket._on_close: closing window")
            # Unregister from ForzeOS if needed
            if self.forze and hasattr(self.forze, 'unregister_window'):
                self.forze.unregister_window(self)
                
            # Clean up any scheduled callbacks
            try:
                # querying 'after info' can fail if the Tcl interpreter is
                # partially torn down; guard against that and ignore errors.
                infos = None
                try:
                    infos = self.tk.call('after', 'info')
                except Exception:
                    infos = None
                if infos:
                    for after_id in infos:
                        try:
                            # after_cancel can also raise if id is invalid
                            self.after_cancel(after_id)
                        except Exception:
                            pass
            except Exception:
                pass
                    
            # Destroy the window
            self.destroy()
        except Exception as e:
            print(f"Error closing market window: {e}")
            self.destroy()
            
    def minimize(self):
        """Minimize window to taskbar"""
        self.wm_iconify()
        
    def maximize(self):
        """Maximize window"""
        self.wm_state('zoomed')
        
    def restore(self):
        """Restore window from minimized/maximized state"""
        self.wm_state('normal')


def open_market(host):
    """Convenience function for hosts to open the Market in-process.

    host: ForzeOS instance or root object. Returns the created window-like
    object or None.
    """
    try:
        logger.debug("forze_market.open_market called with host=%s", getattr(host, 'root', host))
    except Exception:
        try:
            logger.debug("forze_market.open_market called")
        except Exception:
            pass
    return run_embedded(host)


if __name__ == '__main__':
    # Standalone run
    root = tk.Tk()
    root.withdraw()
    win = ForzeOSMarket(root)
    win.mainloop()
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Forze OS Market
- Lightweight application marketplace/editor for ForzeOS
- Features:
  - Browse installed market apps (folder: forze_market_apps)
  - Import a .py as an app (copy to apps folder)
  - Edit app source in an embedded code editor, save back
  - Launch apps (runs module in a subprocess)
  - Preloads `organize_assets.py` as a sample tool on first run

Integration:
- ForzeOS can call `ForzeMarket(host_app).open()` to open the market window.
- Market will try to use host_app GUI styles (colors) when available.

Note: launching arbitrary .py is inherently dangerous. This tool is for
developer/desktop use. Some actions may require admin rights (not auto-elevated).
"""

import os, sys, shutil, subprocess, importlib, threading, traceback
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

APP_FOLDER = Path(__file__).parent / 'forze_market_apps'
SAMPLE_TOOL_SRC = Path(__file__).parent.parent / 'tools' / 'organize_assets.py'

class ForzeMarket:
    def __init__(self, host_app=None):
        self.host = host_app
        self.app_folder = APP_FOLDER
        self.app_folder.mkdir(parents=True, exist_ok=True)
        
        # Find root window
        if host_app is not None:
            if hasattr(host_app, 'root'):
                self.root = host_app.root
            elif hasattr(host_app, 'winfo_toplevel'):
                self.root = host_app.winfo_toplevel()
            else:
                self.root = tk.Tk()
                self.root.withdraw()
        else:
            self.root = tk.Tk()
            self.root.withdraw()

        # ensure sample tool present
        try:
            if SAMPLE_TOOL_SRC.exists():
                dst = self.app_folder / SAMPLE_TOOL_SRC.name
                if not dst.exists():
                    shutil.copy2(str(SAMPLE_TOOL_SRC), str(dst))
        except Exception:
            pass

        # GUI elements
        self.win = None
        self.app_listbox = None
        self.code_editor = None
        self.current_path = None

    def open(self):
        if self.win and self.win.winfo_exists():
            self.win.lift()
            self.win.focus_force()
            return
            
        # prefer host styles
        bg = '#ffffff'; fg = '#000000'
        try:
            if self.host and hasattr(self.host, 'colors'):
                bg = self.host.colors.get('bg', bg)
                fg = self.host.colors.get('fg', fg)
        except Exception:
            pass

        self.win = tk.Toplevel(self.root)
        
        # Make it transient and remove from taskbar
        self.win.transient(self.root)
        self.win.attributes('-toolwindow', True)  # Windows-specific
        
        # Try to fix window ownership
        try:
            if sys.platform.startswith('win'):
                import ctypes
                hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id())
                style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
                style = style | 0x00000080  # WS_EX_TOOLWINDOW
                style = style & ~0x00040000  # ~WS_EX_APPWINDOW
                ctypes.windll.user32.SetWindowLongW(hwnd, -20, style)
                
                # Set owner to root window
                if self.root.winfo_exists():
                    owner_id = self.root.winfo_id() 
                    ctypes.windll.user32.SetWindowLongW(hwnd, -8, owner_id)  # GWL_HWNDPARENT
        except Exception:
            pass
        self.win.title('Forze OS Market')
        self.win.geometry('1000x700')
        try:
            self.win.configure(bg=bg)
        except Exception:
            pass

        # layout: left pane list, right pane editor/controls
        left = tk.Frame(self.win, width=260)
        left.pack(side='left', fill='y', padx=8, pady=8)
        right = tk.Frame(self.win)
        right.pack(side='right', fill='both', expand=True, padx=8, pady=8)

        tk.Label(left, text='Market Apps', font=('Arial', 12, 'bold')).pack(anchor='w')
        self.app_listbox = tk.Listbox(left, width=40, height=30)
        self.app_listbox.pack(fill='y', expand=True)
        self.app_listbox.bind('<<ListboxSelect>>', lambda e: self.on_select())

        btn_frame = tk.Frame(left)
        btn_frame.pack(fill='x', pady=6)
        tk.Button(btn_frame, text='Import .py', command=self.import_py).pack(side='left', padx=4)
        tk.Button(btn_frame, text='Refresh', command=self.refresh).pack(side='left', padx=4)
        tk.Button(btn_frame, text='Install to Desktop', command=self.install_to_desktop).pack(side='left', padx=4)

        # Editor toolbar
        tool_frame = tk.Frame(right)
        tool_frame.pack(fill='x')
        tk.Button(tool_frame, text='Open in External', command=self.open_external).pack(side='left', padx=4)
        tk.Button(tool_frame, text='Open in Host Editor', command=self.open_in_host_editor).pack(side='left', padx=4)
        tk.Button(tool_frame, text='Save', command=self.save).pack(side='left', padx=4)
        tk.Button(tool_frame, text='Run', command=self.run_editor).pack(side='left', padx=4)
        tk.Button(tool_frame, text='Shadow-Gate Audit', command=self.run_shadowgate_audit).pack(side='left', padx=4)
        tk.Button(tool_frame, text='Launch', command=self.launch_app).pack(side='left', padx=4)
        tk.Button(tool_frame, text='Remove', command=self.remove_app).pack(side='left', padx=4)
        try:
            tk.Button(tool_frame, text='Run as Tool', command=self.run_as_tool).pack(side='left', padx=4)
        except Exception:
            pass

        self.code_editor = scrolledtext.ScrolledText(right, wrap='none', undo=True)
        self.code_editor.pack(fill='both', expand=True)

        # bottom status
        self.status = tk.Label(self.win, text='Ready')
        self.status.pack(fill='x')

        self.refresh()

    def refresh(self):
        self.app_listbox.delete(0, 'end')
        for p in sorted(self.app_folder.glob('*.py')):
            self.app_listbox.insert('end', p.name)
        self.status.config(text=f'Found {len(list(self.app_folder.glob("*.py")))} apps')

    def on_select(self):
        sel = self.app_listbox.curselection()
        if not sel:
            return
        name = self.app_listbox.get(sel[0])
        path = self.app_folder / name
        self.load_file(path)

    def load_file(self, path: Path):
        try:
            text = path.read_text(encoding='utf-8', errors='replace')
            self.code_editor.delete('1.0', 'end')
            self.code_editor.insert('1.0', text)
            self.current_path = path
            self.status.config(text=f'Loaded {path.name}')
        except Exception as e:
            messagebox.showerror('Error', f'Failed to load file: {e}')

    def import_py(self):
        f = filedialog.askopenfilename(title='Select Python file', filetypes=[('Python','*.py')])
        if not f:
            return
        src = Path(f)
        dst = self.app_folder / src.name
        try:
            shutil.copy2(str(src), str(dst))
            self.refresh()
            messagebox.showinfo('Imported', f'Imported {src.name} into Market')
        except Exception as e:
            messagebox.showerror('Import failed', str(e))

    def save(self):
        if not self.current_path:
            messagebox.showwarning('No file', 'Select an app to save to')
            return
        try:
            content = self.code_editor.get('1.0', 'end-1c')
            self.current_path.write_text(content, encoding='utf-8')
            messagebox.showinfo('Saved', f'Saved {self.current_path.name}')
            self.status.config(text=f'Saved {self.current_path.name}')
        except Exception as e:
            messagebox.showerror('Save failed', str(e))

    def open_external(self):
        if not self.current_path:
            messagebox.showwarning('No file', 'Select an app first')
            return
        try:
            # Prefer host integration if available
            try:
                if self.host and hasattr(self.host, 'open_script'):
                    try:
                        self.host.open_script(str(self.current_path))
                        return
                    except Exception:
                        pass
                if self.host and hasattr(self.host, 'run_script_embedded'):
                    try:
                        ok = self.host.run_script_embedded(str(self.current_path))
                        if ok:
                            return
                    except Exception:
                        pass
            except Exception:
                pass

            if sys.platform.startswith('win'):
                os.startfile(str(self.current_path))
            else:
                subprocess.Popen(['xdg-open', str(self.current_path)])
        except Exception as e:
            messagebox.showerror('Open failed', str(e))

    def open_in_host_editor(self):
        """Open the current file in the ForzeOS host editor if available, otherwise fall back to open_external."""
        if not self.current_path:
            messagebox.showwarning('No file', 'Select an app first')
            return
        try:
            # Prefer host code editor if available
            try:
                if self.host and hasattr(self.host, 'open_code_editor'):
                    try:
                        self.host.open_code_editor(str(self.current_path))
                        return
                    except Exception:
                        pass
                if self.host and hasattr(self.host, 'open_script'):
                    try:
                        self.host.open_script(str(self.current_path))
                        return
                    except Exception:
                        pass
            except Exception:
                pass

            # Fallback to external open
            return self.open_external()
        except Exception as e:
            messagebox.showerror('Open failed', str(e))

    def run_editor(self):
        """Run the current editor contents in a subprocess without requiring save-to-disk.
        Output (stdout/stderr) is shown in a temporary results window. The temp file
        is removed after execution.
        """
        if not getattr(self, 'code_editor', None):
            try:
                messagebox.showwarning('No editor', 'Editor not available')
            except Exception:
                print('Editor not available')
            return
        content = self.code_editor.get('1.0', 'end-1c')
        if not content.strip():
            try:
                messagebox.showwarning('No code', 'Editor is empty')
            except Exception:
                print('Editor empty')
            return

        import tempfile

        try:
            tf = tempfile.NamedTemporaryFile('w', delete=False, suffix='.py', encoding='utf-8')
            tf.write(content)
            tf.flush(); tf.close()
            # Run in background thread to avoid blocking UI
            def _run():
                try:
                    p = subprocess.Popen([sys.executable, tf.name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    out, err = p.communicate()
                    # Show output in a results window on main thread
                    def _show():
                        try:
                            w = tk.Toplevel(self.win)
                            w.title(f'Run Output - {Path(tf.name).name}')
                            txt = scrolledtext.ScrolledText(w, wrap='none')
                            txt.pack(fill='both', expand=True)
                            if out:
                                txt.insert('end', out + '\n')
                            if err:
                                txt.insert('end', '--- STDERR ---\n' + err + '\n')
                        except Exception:
                            print(out, err)
                    try:
                        self.win.after(10, _show)
                    except Exception:
                        _show()
                finally:
                    try:
                        os.unlink(tf.name)
                    except Exception:
                        pass

            threading.Thread(target=_run, daemon=True).start()
        except Exception as e:
            messagebox.showerror('Run failed', str(e))

    def launch_app(self):
        if not self.current_path:
            messagebox.showwarning('No file', 'Select an app first')
            return
        path = str(self.current_path)
        # Launch in background as separate process
        def _run():
            try:
                # Use the same python interpreter
                p = subprocess.Popen([sys.executable, path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                out, err = p.communicate()
                if p.returncode != 0:
                    # show small dialog with error
                    try:
                        messagebox.showerror('App Error', f'App exited with code {p.returncode}\n\n{err}')
                    except Exception:
                        print('App error:', err)
                else:
                    try:
                        messagebox.showinfo('App Finished', f'App finished successfully: {self.current_path.name}')
                    except Exception:
                        print('App finished')
            except Exception as e:
                try:
                    messagebox.showerror('Launch failed', str(e))
                except Exception:
                    print('Launch failed', e)
        threading.Thread(target=_run, daemon=True).start()

    def remove_app(self):
        if not self.current_path:
            messagebox.showwarning('No file', 'Select an app first')
            return
        if not messagebox.askyesno('Confirm', f'Delete {self.current_path.name}?'):
            return
        try:
            self.current_path.unlink()
            self.current_path = None
            self.code_editor.delete('1.0', 'end')
            self.refresh()
        except Exception as e:
            messagebox.showerror('Delete failed', str(e))

    def install_to_desktop(self):
        # For integration: create a lightweight desktop shortcut by copying the file to a 'market_installed' dir
        try:
            if not self.current_path:
                messagebox.showwarning('No file', 'Select an app first')
                return
            desktop_dir = Path.home() / 'ForzeOS_Market_Installed'
            desktop_dir.mkdir(parents=True, exist_ok=True)
            dst = desktop_dir / self.current_path.name
            shutil.copy2(str(self.current_path), str(dst))
            messagebox.showinfo('Installed', f'Installed {self.current_path.name} to {dst}')
            # Optionally integrate with host: if host provides add_desktop_icon, call it
            try:
                if self.host and hasattr(self.host, 'create_desktop_icon'):
                    # create a callback that will call the module when clicked
                    cb = lambda p=dst: subprocess.Popen([sys.executable, str(p)])
                    self.host.create_desktop_icon(self.current_path.stem, cb, 100, 100, icon_path=None, ignore_saved=True)
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror('Install failed', str(e))

    def run_shadowgate_audit(self):
        try:
            auditor = ShadowGateAuditor(parent=self.win)
            threading.Thread(target=auditor.execute, daemon=True).start()
        except Exception as e:
            messagebox.showerror('Shadow-Gate Audit', f'Başlatılamadı: {e}')

    def run_as_tool(self):
        if not self.current_path:
            messagebox.showwarning('No file', 'Select an app first')
            return
        path = str(self.current_path)
        # prefer host embedded runner
        try:
            if self.host and hasattr(self.host, 'run_script_embedded'):
                try:
                    ok = self.host.run_script_embedded(path)
                    if ok:
                        try:
                            messagebox.showinfo('Run', f'Ran {os.path.basename(path)} via host embedded runner')
                        except Exception:
                            pass
                        return
                except Exception:
                    pass
        except Exception:
            pass


def run_embedded(host):
    """Open the Market embedded inside the given ForzeOS `host`.

    Prefer the ForzeOS-provided ForzeOSMarket class (which registers on <Map>)
    and instantiate it with the host root so it behaves like other apps.
    If that class is not available, fall back to the ForzeMarket wrapper.
    Returns the window-like object created or None on failure.
    """
    try:
        logger.debug("forze_market.run_embedded: host=%s", getattr(host, 'root', host) if host is not None else None)
        # Prefer the newer ForzeOSMarket Toplevel class (same module)
        if 'ForzeOSMarket' in globals():
            try:
                # instantiate using host.root as parent so the Toplevel is attached
                win = ForzeOSMarket(getattr(host, 'root', None) or host, host)
                logger.debug("forze_market.run_embedded: created ForzeOSMarket win=%s", getattr(win, 'winfo_exists', lambda: False)())
                return win
            except Exception:
                logger.exception('forze_market.run_embedded: ForzeOSMarket instantiation failed')
                pass

        # Fallback: use the simpler ForzeMarket helper
        if 'ForzeMarket' in globals():
            try:
                fm = ForzeMarket(host)
                fm.open()
                logger.debug('forze_market.run_embedded: opened ForzeMarket wrapper')
                return fm
            except Exception:
                logger.exception('forze_market.run_embedded: ForzeMarket fallback failed')
                pass

        print('forze_market.run_embedded: could not create embedded market UI')
        return None
    except Exception as e:
        try:
            print('forze_market.run_embedded error:', e)
        except Exception:
            pass
        return None

        # fallback: subprocess
        try:
            subprocess.Popen([sys.executable, path], cwd=os.path.dirname(path))
            try:
                messagebox.showinfo('Run', f'Launched {os.path.basename(path)}')
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror('Run failed', str(e))


# Small self-test when run directly
if __name__ == '__main__':
    root = tk.Tk(); root.withdraw()
    fm = ForzeMarket()
    fm.open()
    root.mainloop()

    def get_wifi_networks(self, timeout=12):
        """Return a list of available WiFi networks as dicts.

        Each dict includes: ssid, signal, auth, encryption, bssids (optional).
        Platform-specific: Windows uses netsh, Linux uses nmcli if available.
        """
        try:
            if platform.system() == 'Windows':
                # Use netsh to list networks with BSSID/signal. Run a few quick retries
                # because on some systems the initial query returns only the connected
                # interface while the radio is still updating its scan results.
                raw = ''
                retries = 5
                all_results = []
                seen_bssids = set()
                for attempt in range(retries):
                    try:
                        # slightly increase timeout on Windows
                        p = subprocess.run(['netsh', 'wlan', 'show', 'networks', 'mode=bssid'], capture_output=True, text=True, timeout=max(8, timeout))
                        out = p.stdout or ''
                        raw += '\n' + out + '\n' + (p.stderr or '')
                        parsed = self._parse_netsh_networks(out)
                        # merge parsed results, dedupe by BSSID
                        for ent in parsed:
                            b = (ent.get('bssid') or '').lower()
                            if b and b not in seen_bssids:
                                seen_bssids.add(b)
                                all_results.append(ent)
                        # if we've collected multiple unique BSSIDs, we likely have full list
                        if len(seen_bssids) > 1:
                            break
                    except Exception:
                        pass
                    # small pause before retrying
                    try:
                        time.sleep(1.0)
                    except Exception:
                        pass
                # if we gathered any results, return them (sorted by signal if available)
                if all_results:
                    try:
                        all_results.sort(key=lambda x: (x.get('signal') or 0), reverse=True)
                    except Exception:
                        pass
                    # If we only discovered one AP so far, try per-interface netsh scans
                    # which on some systems return more results when run against each
                    # wireless interface explicitly (drivers/firmware quirk).
                    try:
                        if len(all_results) <= 1:
                            # enumerate interfaces and retry per-interface
                            try:
                                p_if = subprocess.run(['netsh', 'wlan', 'show', 'interfaces'], capture_output=True, text=True, timeout=6)
                                iface_out = p_if.stdout or p_if.stderr or ''
                                iface_names = []
                                for line in iface_out.splitlines():
                                    m = re.match(r'(?i)^\s*name\s*:\s*(.*)$', line)
                                    if m:
                                        name = m.group(1).strip()
                                        if name:
                                            iface_names.append(name)
                            except Exception:
                                iface_names = []

                            # fallback: common interface names
                            if not iface_names:
                                iface_names = ['Wi-Fi', 'Wireless Network Connection', 'wlan0']

                            for iface in iface_names:
                                try:
                                    p_iface = subprocess.run(['netsh', 'wlan', 'show', 'networks', f'interface="{iface}"', 'mode=bssid'], capture_output=True, text=True, timeout=max(6, timeout))
                                    out_iface = p_iface.stdout or p_iface.stderr or ''
                                    parsed_iface = self._parse_netsh_networks(out_iface)
                                    for ent in parsed_iface:
                                        b = (ent.get('bssid') or '').lower()
                                        if b and b not in seen_bssids:
                                            seen_bssids.add(b)
                                            all_results.append(ent)
                                except Exception:
                                    continue
                            # If still only one or zero results, try Windows WLAN API (wlanapi) as a best-effort
                            if len(all_results) <= 1:
                                try:
                                    wlan_api_results = self._scan_wlanapi_networks(timeout=max(6, timeout))

                                    # helper: validate MAC-like bssid
                                    def _is_valid_bssid_str(s):
                                        try:
                                            if not s:
                                                return False
                                            ss = str(s).lower().strip()
                                            if not re.match(r'^[0-9a-f]{2}(:[0-9a-f]{2}){5}$', ss):
                                                return False
                                            # reject obviously invalid all-zero entries
                                            parts = ss.split(':')
                                            if all(p == '00' for p in parts):
                                                return False
                                            return True
                                        except Exception:
                                            return False

                                    for ent in (wlan_api_results or []):
                                        b_raw = ent.get('bssid') or ''
                                        b = str(b_raw).lower()
                                        # prefer only valid-looking BSSIDs from wlanapi; otherwise skip
                                        if not _is_valid_bssid_str(b):
                                            # if entry contains useful SSID but malformed bssid, skip adding as BSSID entry
                                            continue
                                        if b and b not in seen_bssids:
                                            seen_bssids.add(b)
                                            all_results.append(ent)
                                except Exception:
                                    # ignore wlanapi failures and proceed
                                    pass
                            # sort after merging
                            try:
                                all_results.sort(key=lambda x: (x.get('signal') or 0), reverse=True)
                            except Exception:
                                pass
                    except Exception:
                        pass
                    return all_results
                # final fallback: try a more verbose netsh command
                try:
                    p2 = subprocess.run(['netsh', 'wlan', 'show', 'all'], capture_output=True, text=True, timeout=max(8, timeout))
                    return self._parse_netsh_networks(p2.stdout or p2.stderr or '')
                except Exception:
                    return []
            elif platform.system() == 'Linux':
                nets = []
                # Prefer nmcli when available (richer, reliable)
                if shutil.which('nmcli'):
                    try:
                        p = subprocess.run(['nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY,BSSID,CHAN', 'dev', 'wifi', 'list'], capture_output=True, text=True, timeout=timeout)
                        for line in p.stdout.splitlines():
                            if not line.strip():
                                continue
                            parts = line.split(':')
                            ssid = parts[0] if len(parts) > 0 else ''
                            signal = parts[1] if len(parts) > 1 else ''
                            security = parts[2] if len(parts) > 2 else ''
                            bssid = parts[3] if len(parts) > 3 else None
                            chan = parts[4] if len(parts) > 4 else None
                            try:
                                signal = int(signal)
                            except Exception:
                                pass
                            try:
                                if chan is not None:
                                    chan = int(chan)
                            except Exception:
                                pass
                            d = {'ssid': ssid or '', 'signal': signal, 'auth': security}
                            if bssid:
                                d.setdefault('bssids', []).append(bssid)
                            if chan:
                                d['channel'] = chan
                            nets.append(d)
                        # sort by signal desc
                        nets.sort(key=lambda x: (x.get('signal') or 0), reverse=True)
                        return nets
                    except Exception:
                        pass

                # Fallback: try iwlist (older systems) or `iw dev wlan0 scan` parsing
                try:
                    # try iw first (newer tool)
                    if shutil.which('iw'):
                        # run a scan; interface autodetection may be required
                        # attempt common interface names if none specified
                        ifaces = [i for i in psutil.net_if_addrs().keys() if i.startswith('wl') or i.startswith('wlan')]
                        if not ifaces:
                            ifaces = ['wlan0', 'wlp2s0']
                        for iface in ifaces:
                            try:
                                p = subprocess.run(['iw', 'dev', iface, 'scan'], capture_output=True, text=True, timeout=timeout)
                                if p.stdout:
                                    parsed = self._parse_iwlist_networks(p.stdout)
                                    if parsed:
                                        nets.extend(parsed)
                            except Exception:
                                continue

                    # fallback to iwlist
                    if shutil.which('iwlist') and not nets:
                        # detect interface name
                        ifaces = [i for i in psutil.net_if_addrs().keys() if i.startswith('wl') or i.startswith('wlan')]
                        if not ifaces:
                            ifaces = ['wlan0', 'wlp2s0']
                        for iface in ifaces:
                            try:
                                p = subprocess.run(['iwlist', iface, 'scanning'], capture_output=True, text=True, timeout=timeout)
                                if p.stdout:
                                    parsed = self._parse_iwlist_networks(p.stdout)
                                    if parsed:
                                        nets.extend(parsed)
                            except Exception:
                                continue
                except Exception:
                    pass

                # sort and dedupe by bssid when possible
                seen = set()
                out = []
                for n in sorted(nets, key=lambda x: (x.get('signal') or 0), reverse=True):
                    b = (tuple(n.get('bssids') or []) or (n.get('bssid'),))
                    key = (n.get('ssid',''), b)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(n)
                return out
            else:
                return []
        except Exception:
            return []

    def get_connected_wifi_info(self):
        """Return connected WiFi info (ssid, interface) or None."""
        try:
            if platform.system() == 'Windows':
                p = subprocess.run(['netsh', 'wlan', 'show', 'interfaces'], capture_output=True, text=True, timeout=8)
                ssid = None
                iface = None
                ip = None
                for line in p.stdout.splitlines():
                    line = line.strip()
                    if line.startswith('Name') and ':' in line:
                        iface = line.split(':', 1)[1].strip()
                    if line.startswith('SSID') and ':' in line:
                        # avoid lines like BSSID
                        if line.lower().startswith('ssid '):
                            ssid = line.split(':', 1)[1].strip()
                # get IP via psutil if possible
                ip = None
                try:
                    for ifname, addrs in psutil.net_if_addrs().items():
                        if iface and iface.lower() in ifname.lower():
                            for a in addrs:
                                if a.family == socket.AF_INET:
                                    ip = a.address; break
                except Exception:
                    pass
                return {'ssid': ssid, 'interface': iface, 'ip': ip}
            elif platform.system() == 'Linux':
                if shutil.which('nmcli'):
                    p = subprocess.run(['nmcli', '-t', '-f', 'ACTIVE,SSID,DEVICE', 'dev', 'wifi'], capture_output=True, text=True, timeout=6)
                    for line in p.stdout.splitlines():
                        parts = line.split(':')
                        if parts and parts[0] == 'yes':
                            ssid = parts[1]
                            iface = parts[2] if len(parts) > 2 else None
                            ip = None
                            try:
                                for ifname, addrs in psutil.net_if_addrs().items():
                                    if iface and iface in ifname:
                                        for a in addrs:
                                            if a.family == socket.AF_INET:
                                                ip = a.address; break
                            except Exception:
                                pass
                            return {'ssid': ssid, 'interface': iface, 'ip': ip}
                return {'ssid': None, 'interface': None, 'ip': None}
        except Exception:
            return {'ssid': None, 'interface': None, 'ip': None}

    def _parse_iwlist_networks(self, raw: str):
        """Parse `iwlist ... scanning` or `iw dev ... scan` output into list of dicts.

        Returns list of dicts with keys: ssid, bssids (list), bssid, signal (int dBm or percent when available), channel, auth/security.
        """
        nets = []
        cur = None

        for raw_line in raw.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            # iwlist: Cell 01 - Address: XX:XX:...
            m = re.match(r'(?i)^cell\s+\d+\s+-\s+address:\s*([0-9A-Fa-f:]{17})', line)
            if m:
                # finalize previous
                if cur:
                    if 'bssid' in cur:
                        cur.setdefault('bssids', [cur.get('bssid')])
                    nets.append(cur)
                cur = {'bssid': m.group(1).lower(), 'ssid': ''}
                continue

            # iw newer output: BSS xx:xx:xx... or BSS xx:xx:xx(ssid)
            m = re.match(r'(?i)^bss\s+([0-9a-f:]{17})', line)
            if m:
                if cur:
                    if 'bssid' in cur:
                        cur.setdefault('bssids', [cur.get('bssid')])
                    nets.append(cur)
                cur = {'bssid': m.group(1).lower(), 'ssid': ''}
                continue

            # ESSID: "name"
            m = re.match(r'ESSID:\s*"(.*)"', line)
            if m and cur is not None:
                cur['ssid'] = m.group(1)
                continue

            # ssid: name (iw)
            m = re.match(r'(?i)^ssid:\s*(.*)$', line)
            if m and cur is not None:
                cur['ssid'] = m.group(1).strip()
                continue

            # Signal quality or signal level
            m = re.search(r'(-?\d+)\s*dBm', line)
            if m and cur is not None:
                try:
                    cur['signal'] = int(m.group(1))
                except Exception:
                    cur['signal'] = m.group(1)
                continue

            m = re.search(r'Quality=\s*(\d+)/(\d+)', line)
            if m and cur is not None:
                try:
                    q = int(m.group(1)); total = int(m.group(2))
                    # convert to percent
                    cur['signal'] = int((q/total)*100)
                except Exception:
                    cur['signal'] = line
                continue

            # Channel or Frequency
            m = re.match(r'(?i)^channel[:\s]*([0-9]+)', line)
            if m and cur is not None:
                try:
                    cur['channel'] = int(m.group(1))
                except Exception:
                    cur['channel'] = m.group(1)
                continue
            m = re.search(r'Frequency:\s*(\d+\.\d+)\s*GHz', line)
            if m and cur is not None:
                try:
                    freq = float(m.group(1))
                    # approximate channel for 2.4 GHz
                    if 2.4 <= freq < 2.5:
                        cur['channel'] = int(round((freq - 2.412) / 0.005) + 1) if False else cur.get('channel')
                except Exception:
                    pass

            # Encryption / WPA / RSN indications
            if ('wpa' in line.lower() or 'rsn' in line.lower() or 'ie:' in line.lower() and ('wpa' in line.lower() or 'rsn' in line.lower())) and cur is not None:
                cur.setdefault('auth', line)
                continue

            if 'encryption key' in line.lower() and cur is not None:
                if 'on' in line.lower():
                    cur.setdefault('auth', cur.get('auth', 'encrypted'))
                else:
                    cur.setdefault('auth', 'open')
                continue

        if cur:
            if 'bssid' in cur:
                cur.setdefault('bssids', [cur.get('bssid')])
            nets.append(cur)

        return nets

    def _scan_wlanapi_networks(self, timeout: int = 6):
        """Best-effort Windows WLAN API scan using ctypes.

        Returns list of dicts with keys: ssid, bssid, signal (percent), channel (if available).
        This is defensive: any failure returns an empty list. Lightweight and only used
        as a fallback when netsh reports too few networks.
        """
        try:
            if not platform.system().lower().startswith('win'):
                return []
            import ctypes
            from ctypes import POINTER, byref, Structure, c_ulong, c_void_p, c_wchar_p, c_ulonglong, c_uint32, c_int32

            wlanapi = ctypes.WinDLL('wlanapi')

            # basic types
            HANDLE = c_void_p
            DWORD = c_ulong
            BOOL = c_uint32

            class DOT11_SSID(Structure):
                _fields_ = [('uSSIDLength', c_ulong), ('ucSSID', ctypes.c_ubyte * 32)]

            class WLAN_INTERFACE_INFO(Structure):
                _fields_ = [
                    ('InterfaceGuid', ctypes.c_ubyte * 16),
                    ('strInterfaceDescription', ctypes.c_wchar * 256),
                    ('isState', DWORD)
                ]

            class WLAN_INTERFACE_INFO_LIST(Structure):
                _fields_ = [('dwNumberOfItems', DWORD), ('dwIndex', DWORD), ('InterfaceInfo', WLAN_INTERFACE_INFO * 1)]

            class WLAN_BSS_ENTRY(Structure):
                _fields_ = [
                    ('dot11Ssid', DOT11_SSID),
                    ('dot11Bssid', ctypes.c_ubyte * 6),
                    ('uPhyId', DWORD),
                    ('dot11BssType', DWORD),
                    ('dwNumberOfBssids', DWORD),
                    ('lRssi', c_int32),
                    ('uLinkQuality', DWORD),
                    ('ulChCenterFrequency', DWORD),
                    ('wlanRateSet', DWORD * 8),
                    ('ulIeOffset', DWORD),
                    ('ulIeSize', DWORD)
                ]

            class WLAN_BSS_LIST(Structure):
                _fields_ = [('dwTotalSize', DWORD), ('dwNumberOfItems', DWORD), ('wlanBssEntries', WLAN_BSS_ENTRY * 1)]

            # function prototypes
            wlanapi.WlanOpenHandle.argtypes = [DWORD, c_void_p, POINTER(DWORD), POINTER(HANDLE)]
            wlanapi.WlanOpenHandle.restype = DWORD
            wlanapi.WlanEnumInterfaces.argtypes = [HANDLE, c_void_p, POINTER(POINTER(WLAN_INTERFACE_INFO_LIST))]
            wlanapi.WlanEnumInterfaces.restype = DWORD
            wlanapi.WlanFreeMemory.argtypes = [c_void_p]
            wlanapi.WlanFreeMemory.restype = None
            wlanapi.WlanGetNetworkBssList.argtypes = [HANDLE, POINTER(ctypes.c_ubyte * 16), POINTER(DOT11_SSID), DWORD, BOOL, c_void_p, POINTER(POINTER(WLAN_BSS_LIST))]
            wlanapi.WlanGetNetworkBssList.restype = DWORD

            client_handle = HANDLE()
            negotiated = DWORD()
            rc = wlanapi.WlanOpenHandle(2, None, byref(negotiated), byref(client_handle))
            if rc != 0:
                return []

            results = []
            try:
                p_iface_list = POINTER(WLAN_INTERFACE_INFO_LIST)()
                rc = wlanapi.WlanEnumInterfaces(client_handle, None, byref(p_iface_list))
                if rc != 0 or not p_iface_list:
                    return []

                # read number of interfaces
                num = p_iface_list.contents.dwNumberOfItems
                # pointer arithmetic: manually compute array base
                # The structure definition above uses size 1 array; handle generically
                base = ctypes.addressof(p_iface_list.contents.InterfaceInfo)
                size_iface = ctypes.sizeof(WLAN_INTERFACE_INFO)
                for i in range(num):
                    addr = base + size_iface * i
                    iface = ctypes.cast(addr, POINTER(WLAN_INTERFACE_INFO)).contents
                    # extract GUID bytes
                    guid_bytes = bytes(bytearray(iface.InterfaceGuid))
                    # prepare GUID pointer type for WlanGetNetworkBssList
                    guid_arr = (ctypes.c_ubyte * 16)(*iface.InterfaceGuid)
                    p_bss_list = POINTER(WLAN_BSS_LIST)()
                    # call get bss list (NULL SSID -> all)
                    rc2 = wlanapi.WlanGetNetworkBssList(client_handle, byref(guid_arr), None, 0, 0, None, byref(p_bss_list))
                    if rc2 != 0 or not p_bss_list:
                        continue
                    try:
                        count = p_bss_list.contents.dwNumberOfItems
                        # entries start at wlanBssEntries
                        bbase = ctypes.addressof(p_bss_list.contents.wlanBssEntries)
                        size_entry = ctypes.sizeof(WLAN_BSS_ENTRY)
                        for j in range(count):
                            eaddr = bbase + size_entry * j
                            entry = ctypes.cast(eaddr, POINTER(WLAN_BSS_ENTRY)).contents
                            ssid_len = int(entry.dot11Ssid.uSSIDLength)
                            ssid = ''
                            if ssid_len > 0:
                                ssid = bytes(bytearray(entry.dot11Ssid.ucSSID[:ssid_len])).decode('utf-8', errors='ignore')
                            bssid = ':'.join('%02x' % x for x in bytearray(entry.dot11Bssid))
                            rssi = int(entry.lRssi)
                            # convert rssi (-100..-50) to percent
                            if rssi <= -100:
                                sig = 0
                            elif rssi >= -50:
                                sig = 100
                            else:
                                sig = 2 * (rssi + 100)
                                if sig < 0: sig = 0
                                if sig > 100: sig = 100
                            freq = int(entry.ulChCenterFrequency) if entry.ulChCenterFrequency else 0
                            channel = None
                            try:
                                # freq is in kHz per docs; convert to MHz
                                if freq:
                                    mhz = freq / 1000.0
                                    # 2.4GHz mapping
                                    if 2400 <= mhz <= 2500:
                                        channel = int(round((mhz - 2412) / 5.0) + 1)
                                    # 5GHz simplistic mapping (may vary)
                                    elif 5000 <= mhz <= 6000:
                                        channel = int(round(mhz / 5.0))
                            except Exception:
                                channel = None
                            results.append({'ssid': ssid or '', 'bssid': bssid.lower(), 'signal': int(sig), 'channel': channel})
                    finally:
                        try:
                            wlanapi.WlanFreeMemory(p_bss_list)
                        except Exception:
                            pass
            finally:
                try:
                    wlanapi.WlanFreeMemory(p_iface_list)
                except Exception:
                    pass
                try:
                    wlanapi.WlanCloseHandle(client_handle, None)
                except Exception:
                    pass

            # dedupe by bssid
            seen = set(); out = []
            for r in results:
                b = (r.get('bssid') or '').lower()
                if b and b not in seen:
                    seen.add(b); out.append(r)
            return out
        except Exception:
            return []

    def scan_and_log_wifi(self, timeout=8):
        """Convenience helper that performs a live scan and shows results in a small dialog.

        Useful for quick verification while developing/testing. Uses real system tools
        (nmcli/iw/iwlist/netsh) and does not simulate results.
        """
        try:
            nets = self.get_wifi_networks(timeout=timeout)
            if not nets:
                messagebox.showinfo('WiFi Scan', 'No networks found or scanning not supported on this system')
                return nets
            # prepare summary (first 12 entries)
            lines = []
            for n in nets[:12]:
                ss = n.get('ssid') or '<hidden>'
                b = (n.get('bssids') or [n.get('bssid') or ''])[0]
                sig = n.get('signal', '')
                ch = n.get('channel', '')
                sec = n.get('auth') or n.get('encryption') or ''
                lines.append(f"{ss}\t{b}\t{sig}\t{ch}\t{sec}")
            text = '\n'.join(lines)
            messagebox.showinfo('WiFi Scan', f'Found {len(nets)} networks (showing up to 12):\n\n{text}')
            return nets
        except Exception as e:
            messagebox.showerror('WiFi Scan Error', str(e))
            return []

    def _connect_wifi_windows(self, ssid: str, password: str = None, encryption: str = 'AES'):
        """Attempt to connect to a WiFi network on Windows using netsh.

        Returns (success:bool, message:str)
        """
        try:
            # Build a profile XML for WPA2PSK or open network
            import tempfile
            ssid_xml = ssid.replace('&', '&amp;')
            if not password:
                # Open network
                profile = f'''<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
  <name>{ssid_xml}</name>
  <SSIDConfig><SSID><name>{ssid_xml}</name></SSID></SSIDConfig>
  <connectionType>ESS</connectionType>
  <connectionMode>manual</connectionMode>
  <MSM>
    <security>
      <authEncryption>
        <authentication>open</authentication>
        <encryption>none</encryption>
        <useOneX>false</useOneX>
      </authEncryption>
    </security>
  </MSM>
</WLANProfile>'''
            else:
                # WPA2PSK profile (common case)
                profile = f'''<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
  <name>{ssid_xml}</name>
  <SSIDConfig><SSID><name>{ssid_xml}</name></SSID></SSIDConfig>
  <connectionType>ESS</connectionType>
  <connectionMode>manual</connectionMode>
  <MSM>
    <security>
      <authEncryption>
        <authentication>WPA2PSK</authentication>
        <encryption>{encryption}</encryption>
        <useOneX>false</useOneX>
      </authEncryption>
      <sharedKey>
        <keyType>passPhrase</keyType>
        <protected>false</protected>
        <keyMaterial>{password}</keyMaterial>
      </sharedKey>
    </security>
  </MSM>
</WLANProfile>'''
            with tempfile.NamedTemporaryFile('w', suffix='.xml', delete=False, encoding='utf-8') as f:
                f.write(profile)
                fname = f.name
            try:
                add = subprocess.run(['netsh', 'wlan', 'add', 'profile', f'filename={fname}'], capture_output=True, text=True, timeout=15)
                # Attempt to connect
                conn = subprocess.run(['netsh', 'wlan', 'connect', f'name={ssid}', f'ssid={ssid}'], capture_output=True, text=True, timeout=15)
                if 'The command completed successfully' in conn.stdout or conn.returncode == 0:
                    return True, 'Connected (pending)'
                # netsh may print to stderr
                out = conn.stdout + '\n' + conn.stderr
                if 'successfully' in out.lower():
                    return True, 'Connected'
                return False, out.strip()
            finally:
                try:
                    os.remove(fname)
                except Exception:
                    pass
        except Exception as e:
            return False, str(e)

    def _connect_wifi_linux(self, ssid: str, password: str = None):
        try:
            if not shutil.which('nmcli'):
                return False, 'nmcli not available'
            if password:
                # use nmcli to connect with password
                p = subprocess.run(['nmcli', 'dev', 'wifi', 'connect', ssid, 'password', password], capture_output=True, text=True, timeout=20)
            else:
                p = subprocess.run(['nmcli', 'dev', 'wifi', 'connect', ssid], capture_output=True, text=True, timeout=20)
            out = p.stdout + '\n' + p.stderr
            if p.returncode == 0:
                return True, out.strip()
            return False, out.strip()
        except Exception as e:
            return False, str(e)

    # --- WiFi vault helpers (securely save/retrieve small secrets) ---
    def _ensure_wifi_vault(self):
        try:
            return self.config.setdefault('wifi_vault', {})
        except Exception:
            self.config['wifi_vault'] = {}
            return self.config['wifi_vault']

    def wifi_set_master_password(self, password: str, iterations: int = 200000):
        """Set a master password for the WiFi vault. Stores only salt/iterations in config.

        Returns True on success.
        """
        try:
            if not CRYPTO_AVAILABLE:
                messagebox.showerror('Error', 'Encryption support requires cryptography library (cryptography).')
                return False
            import os, base64
            salt = os.urandom(16)
            key = self.generate_vault_key_from_password(password, salt=salt, iterations=iterations)
            if not key:
                return False
            vault = self._ensure_wifi_vault()
            vault['salt'] = base64.b64encode(salt).decode('utf-8')
            vault['iterations'] = int(iterations)
            # Do not store any plaintext or password-derived key
            try:
                self.save_config()
            except Exception:
                pass
            return True
        except Exception as e:
            try:
                logger.exception('wifi_set_master_password failed')
            except Exception:
                pass
            messagebox.showerror('Error', f'Failed to set master password: {e}')
            return False

    def _derive_wifi_key(self, master_password: str):
        """Derive a Fernet-compatible key from stored salt and provided master password."""
        try:
            if not CRYPTO_AVAILABLE:
                return None
            import base64
            vault = (self.config.get('wifi_vault') or {})
            salt_b64 = vault.get('salt')
            iterations = int(vault.get('iterations', 200000))
            if not salt_b64:
                return None
            salt = base64.b64decode(salt_b64)
            key = self.generate_vault_key_from_password(master_password, salt=salt, iterations=iterations)
            return key
        except Exception:
            return None

    def wifi_save_password(self, ssid: str, password: str, master_password: str = None):
        """Encrypt and save WiFi password for ssid using master_password (or ask to set one).

        Returns True on success.
        """
        try:
            if not CRYPTO_AVAILABLE:
                messagebox.showerror('Error', 'Encryption support requires cryptography library.')
                return False
            import base64
            # Ensure vault salt exists or prompt to set
            vault = self._ensure_wifi_vault()
            if not vault.get('salt'):
                # ask user to set a master password
                mp = simpledialog.askstring('Set Vault Password', 'Create a master password to protect saved WiFi passwords:', show='*', parent=self.root)
                if not mp:
                    return False
                ok = self.wifi_set_master_password(mp)
                if not ok:
                    return False
                key = self._derive_wifi_key(mp)
            else:
                if master_password is None:
                    mp = simpledialog.askstring('Vault Password', 'Enter master password to encrypt WiFi password:', show='*', parent=self.root)
                else:
                    mp = master_password
                if not mp:
                    return False
                key = self._derive_wifi_key(mp)
            if not key:
                messagebox.showerror('Error', 'Invalid master password or vault not initialized')
                return False
            f = Fernet(key)
            token = f.encrypt(password.encode('utf-8'))
            token_str = token.decode('utf-8')
            self.config.setdefault('wifi_saved', {})[ssid] = {'token': token_str}
            try:
                self.save_config()
            except Exception:
                pass
            return True
        except Exception as e:
            try:
                logger.exception('wifi_save_password failed')
            except Exception:
                pass
            messagebox.showerror('Error', f'Failed to save WiFi password: {e}')
            return False

    def wifi_get_saved_password(self, ssid: str):
        """Prompt for master password and return decrypted saved WiFi password or None."""
        try:
            saved = (self.config.get('wifi_saved') or {}).get(ssid)
            if not saved or 'token' not in saved:
                return None
            mp = simpledialog.askstring('Vault Password', 'Enter master password to reveal saved WiFi password:', show='*', parent=self.root)
            if not mp:
                return None
            key = self._derive_wifi_key(mp)
            if not key:
                return None
            f = Fernet(key)
            token = saved.get('token')
            if isinstance(token, str):
                token = token.encode('utf-8')
            plain = f.decrypt(token).decode('utf-8')
            return plain
        except Exception as e:
            try:
                logger.exception('wifi_get_saved_password failed')
            except Exception:
                pass
            messagebox.showerror('Error', 'Failed to decrypt saved password or master password is incorrect')
            return None

    def connect_wifi(self, ssid: str, password: str = None, callback=None):
        """Connect to WiFi network in background. callback(success, msg) runs on main thread."""
        def _worker():
            try:
                if platform.system() == 'Windows':
                    ok, msg = self._connect_wifi_windows(ssid, password)
                elif platform.system() == 'Linux':
                    ok, msg = self._connect_wifi_linux(ssid, password)
                else:
                    ok, msg = False, 'Unsupported platform'
            except Exception as e:
                ok, msg = False, str(e)
            if callback:
                try:
                    self.root.after(10, lambda: callback(ok, msg))
                except Exception:
                    try:
                        callback(ok, msg)
                    except Exception:
                        pass

        threading.Thread(target=_worker, daemon=True).start()

    def open_wifi_settings(self):
        """Open a WiFi settings window showing networks and allowing connect/disconnect."""
        try:
            if hasattr(self, 'wifi_window') and getattr(self, 'wifi_window') and self.wifi_window.winfo_exists():
                self.wifi_window.lift(); return

            self.wifi_window = self.create_window('WiFi Settings', 600, 420)
            if not self.wifi_window:
                return

            frame = tk.Frame(self.wifi_window, bg=self.colors['bg'])
            frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

            # Treeview for networks (expanded columns for richer details)
            cols = ('ssid', 'signal', 'channel', 'auth', 'bssid')
            tv = ttk.Treeview(frame, columns=cols, show='headings', height=12)
            tv.heading('ssid', text='SSID')
            tv.heading('signal', text='Signal')
            tv.heading('channel', text='Channel')
            tv.heading('auth', text='Security')
            tv.heading('bssid', text='BSSID')
            tv.column('ssid', width=260)
            tv.column('signal', width=90, anchor='center')
            tv.column('channel', width=70, anchor='center')
            tv.column('auth', width=140)
            tv.column('bssid', width=180)
            tv.pack(fill=tk.BOTH, expand=True)

            status_lbl = tk.Label(frame, text='Ready', bg=self.colors['bg'], fg=self.colors['fg'])
            status_lbl.pack(fill=tk.X, pady=(6,0))

            btn_frame = tk.Frame(frame, bg=self.colors['bg'])
            btn_frame.pack(fill=tk.X, pady=6)

            # Progress indicator for scans
            scan_progress = ttk.Progressbar(btn_frame, mode='indeterminate', length=140)
            scan_progress.pack(side=tk.RIGHT, padx=6)

            # Helper: convert numeric signal to bars (textual)
            def _signal_bars(val):
                try:
                    v = int(val)
                except Exception:
                    # try to parse 'xx%' or other
                    try:
                        v = int(str(val).replace('%',''))
                    except Exception:
                        return ''
                if v >= 90:
                    return '▂▄▆█'
                if v >= 70:
                    return '▂▄▆ '
                if v >= 50:
                    return '▂▄  '
                if v >= 30:
                    return '▂   '
                return '▁   '

            # Prevent aggressive repeated scans
            if not hasattr(self, '_last_wifi_scan_time'):
                self._last_wifi_scan_time = 0.0

            # Sorting helper: bind headings to sort
            def _tv_sort(col, reverse=False):
                try:
                    items = [(tv.set(k, col), k) for k in tv.get_children('')]
                    # numeric sort if possible
                    try:
                        items = [(float(x[0]) if x[0] != '' else float('-inf'), x[1]) for x in items]
                    except Exception:
                        pass
                    items.sort(reverse=reverse)
                    for index, (_, k) in enumerate(items):
                        tv.move(k, '', index)
                    # toggle next
                    tv.heading(col, command=lambda: _tv_sort(col, not reverse))
                except Exception:
                    pass

            # attach sorting to headings
            for c in cols:
                try:
                    tv.heading(c, command=lambda _c=c: _tv_sort(_c, False))
                except Exception:
                    pass

            def _on_scan():
                # Rate-limit scans to avoid stressing the radio/OS
                try:
                    now = time.time()
                    if now - getattr(self, '_last_wifi_scan_time', 0) < 5:
                        remaining = int(5 - (now - getattr(self, '_last_wifi_scan_time', 0)))
                        status_lbl.config(text=f'Please wait {remaining}s before rescanning')
                        return
                    status_lbl.config(text='Scanning nearby networks...')
                    for i in tv.get_children(): tv.delete(i)
                    scan_progress.start(10)
                except Exception:
                    pass

                def _scan_worker():
                    try:
                        nets = self.get_wifi_networks(timeout=8)
                        connected = self.get_connected_wifi_info()
                    except Exception as e:
                        nets = []
                        connected = None
                        try:
                            self.root.after(10, lambda: status_lbl.config(text=f'Scan failed: {e}'))
                        except Exception:
                            pass

                    # Helpers: sanitize SSID for safe display and validate BSSID format
                    def _sanitize_ssid(raw_ssid):
                        try:
                            s = '' if raw_ssid is None else str(raw_ssid)
                        except Exception:
                            s = ''
                        if not s:
                            return '<hidden>', None
                        # Replace control/non-printable chars with replacement marker, but keep readable chars
                        printable = ''.join(ch if ch.isprintable() else '\uFFFD' for ch in s)
                        # If there were non-printable characters, also provide a short hex preview
                        if any((not ch.isprintable()) for ch in s):
                            try:
                                hex_repr = ' '.join(f"{ord(ch):02x}" for ch in s)
                                short = hex_repr if len(hex_repr) <= 60 else hex_repr[:57] + '...'
                            except Exception:
                                short = None
                            return f"{printable} ⟨hex:{short}⟩" if short else printable, hex_repr if short else None
                        return printable, None

                    def _is_valid_bssid(b):
                        if not b:
                            return False
                        try:
                            s = str(b).lower().strip()
                        except Exception:
                            return False
                        if re.match(r'^[0-9a-f]{2}(:[0-9a-f]{2}){5}$', s):
                            # reject all-zero addresses
                            if all(x == '00' for x in s.split(':')):
                                return False
                            return True
                        return False

                    def _ui_update():
                        try:
                            # dedupe per-BSSID so each AP/radio is shown independently
                            seen = set()
                            inserted = 0
                            for n in nets:
                                # normalize possible bssid lists
                                bss_list = []
                                if n.get('bssids'):
                                    bss_list = list(n.get('bssids'))
                                elif n.get('bssid'):
                                    bss_list = [n.get('bssid')]
                                else:
                                    bss_list = [None]

                                for b in bss_list:
                                    b_norm = (b or '').lower()
                                    # Skip duplicates by bssid; if no bssid, fallback to SSID+index
                                    if b_norm:
                                        if b_norm in seen:
                                            continue
                                        seen.add(b_norm)
                                    else:
                                        # create a synthetic key for hidden/no-bssid entries
                                        synthetic = (n.get('ssid') or '') + f":{inserted}"
                                        if synthetic in seen:
                                            continue
                                        seen.add(synthetic)

                                    ss_raw = n.get('ssid') or ''
                                    ss_display, ss_hex = _sanitize_ssid(ss_raw)

                                    sig_raw = n.get('signal') or ''
                                    sig_text = f"{sig_raw}%" if isinstance(sig_raw, int) or (isinstance(sig_raw, str) and str(sig_raw).strip().endswith('%')) else str(sig_raw)
                                    bars = _signal_bars(sig_raw)
                                    signal_display = f"{sig_text} {bars}".strip()

                                    channel = n.get('channel') or n.get('chan') or ''
                                    auth = n.get('auth') or n.get('encryption') or n.get('security') or ''
                                    b_display = b_norm or ''

                                    # mark invalid-looking BSSIDs visually but still show them
                                    tags = ()
                                    if b_norm and not _is_valid_bssid(b_norm):
                                        tags = ('invalid_bssid',)

                                    item = tv.insert('', 'end', values=(ss_display, signal_display, channel, auth, b_display), tags=tags)
                                    # mark connected (prefer BSSID match, fall back to SSID)
                                    try:
                                        if connected:
                                            if connected.get('ssid') and ss_raw and ss_raw == connected.get('ssid'):
                                                tv.item(item, tags=tv.item(item, 'tags') + ('connected',))
                                            # if connected info includes interface but not bssid, still allow SSID match
                                    except Exception:
                                        pass
                                    inserted += 1

                            status_lbl.config(text=f'Found {inserted} networks')
                            tv.tag_configure('connected', background='#dff0d8')
                            tv.tag_configure('invalid_bssid', background='#fff3cd')
                        except Exception:
                            try:
                                status_lbl.config(text='Error updating UI with scan results')
                            except Exception:
                                pass
                        finally:
                            try:
                                scan_progress.stop()
                            except Exception:
                                pass
                            # update last scan time
                            try:
                                self._last_wifi_scan_time = time.time()
                            except Exception:
                                pass

                    try:
                        self.root.after(10, _ui_update)
                    except Exception:
                        _ui_update()

                threading.Thread(target=_scan_worker, daemon=True).start()

            def _on_connect():
                sel = tv.selection()
                if not sel:
                    messagebox.showinfo('Connect', 'Select a network first')
                    return
                ssid = tv.item(sel[0], 'values')[0]
                # ask for password
                pwd = simpledialog.askstring('Password', f'Enter password for {ssid} (leave empty for open network):', show='*', parent=self.wifi_window)
                # Confirm the user wants to proceed (helps avoid accidental auto-modifications)
                if not messagebox.askyesno('Confirm', f'Connect to network "{ssid}"?'):
                    return
                status_lbl.config(text=f'Connecting to {ssid}...')

                def _connect_cb(ok, msg):
                    if ok:
                        messagebox.showinfo('WiFi', f'Connected to {ssid}\n{msg}')
                        # Ask whether to save password securely (only if encryption available and password provided)
                        try:
                            if pwd and CRYPTO_AVAILABLE:
                                if messagebox.askyesno('Save Password', f'Do you want to save the password for "{ssid}" securely?'):
                                    # attempt to save; prompt for master password if needed
                                    saved_ok = self.wifi_save_password(ssid, pwd)
                                    if saved_ok:
                                        messagebox.showinfo('WiFi', f'Password saved for {ssid} (encrypted)')
                                    else:
                                        messagebox.showwarning('WiFi', 'Password not saved')
                            elif pwd and not CRYPTO_AVAILABLE:
                                messagebox.showwarning('WiFi', 'Cannot save password securely: cryptography library not available')
                        except Exception:
                            pass
                    else:
                        messagebox.showerror('WiFi', f'Failed to connect to {ssid}:\n{msg}')
                    status_lbl.config(text='')
                    # refresh list after attempt
                    _on_scan()

                self.connect_wifi(ssid, pwd, callback=_connect_cb)

            def _on_details():
                sel = tv.selection()
                if not sel:
                    return
                vals = tv.item(sel[0], 'values')
                ssid = vals[0] if vals else ''
                bssid_sel = vals[4] if vals and len(vals) > 4 else ''
                info_lines = []
                # try to find detailed info from a fresh scan
                nets = self.get_wifi_networks()
                # Prefer matching by BSSID when available
                found = False
                if bssid_sel:
                    for n in nets:
                        # normalize both
                        nb = (n.get('bssid') or '')
                        if nb and nb.lower() == bssid_sel.lower():
                            info_lines.append(f"SSID: {n.get('ssid')}")
                            info_lines.append(f"BSSID: {nb}")
                            info_lines.append(f"Signal: {n.get('signal')}")
                            info_lines.append(f"Auth: {n.get('auth')}")
                            info_lines.append(f"Encryption: {n.get('encryption')}")
                            if n.get('bssids'):
                                info_lines.append(f"Other BSSIDs: {', '.join(n.get('bssids')[:5])}")
                            found = True; break
                if not found:
                    for n in nets:
                        if (n.get('ssid') or '') == ssid or (n.get('ssid') or '') == ssid.split(' ⟨hex:')[0]:
                            info_lines.append(f"SSID: {n.get('ssid')}")
                            info_lines.append(f"Signal: {n.get('signal')}")
                            info_lines.append(f"Auth: {n.get('auth')}")
                            info_lines.append(f"Encryption: {n.get('encryption')}")
                            if n.get('bssids'):
                                info_lines.append(f"BSSIDs: {', '.join(n.get('bssids')[:3])}")
                            break
                connected = self.get_connected_wifi_info()
                if connected and connected.get('ssid') == ssid:
                    info_lines.append(f"Connected on interface: {connected.get('interface')}")
                    info_lines.append(f"IP: {connected.get('ip')}")
                # Show basic details first
                details = '\n'.join(info_lines) if info_lines else 'No details'
                messagebox.showinfo('Network Details', details)
                # If we have a saved (encrypted) password for this SSID, offer to reveal it (requires master password)
                try:
                    saved = (self.config.get('wifi_saved') or {}).get(ssid)
                    if saved:
                        if messagebox.askyesno('Saved Password', 'A saved password exists for this network. Reveal it? (requires master password)'):
                            pwd_plain = self.wifi_get_saved_password(ssid)
                            if pwd_plain is None:
                                messagebox.showerror('Error', 'Could not reveal saved password (bad master password or vault not set)')
                            else:
                                # Offer to copy to clipboard rather than showing plainly
                                if messagebox.askyesno('Reveal', 'Show password in dialog? (No = copy to clipboard)'):
                                    messagebox.showinfo('Saved Password', f'Password for {ssid}: {pwd_plain}')
                                else:
                                    try:
                                        self.root.clipboard_clear(); self.root.clipboard_append(pwd_plain)
                                        messagebox.showinfo('Saved Password', 'Password copied to clipboard')
                                    except Exception:
                                        messagebox.showinfo('Saved Password', f'Password: {pwd_plain}')
                except Exception:
                    pass

            scan_btn = tk.Button(btn_frame, text='Scan', command=_on_scan, bg=self.colors['accent'], fg='white')
            scan_btn.pack(side=tk.LEFT, padx=6)
            connect_btn = tk.Button(btn_frame, text='Connect', command=_on_connect, bg=self.colors['success'], fg='white')
            connect_btn.pack(side=tk.LEFT, padx=6)
            details_btn = tk.Button(btn_frame, text='Details', command=_on_details, bg=self.colors['light'])
            details_btn.pack(side=tk.LEFT, padx=6)
            # Show raw scanner output for debugging (helps when only connected network shows)
            def _show_raw_scan_output():
                try:
                    out = ''
                    if platform.system() == 'Windows':
                        try:
                            p = subprocess.run(['netsh', 'wlan', 'show', 'networks', 'mode=bssid'], capture_output=True, text=True, timeout=8)
                            out = p.stdout + '\n' + p.stderr
                        except Exception as e:
                            out = f'netsh failed: {e}'
                    elif platform.system() == 'Linux':
                        try:
                            if shutil.which('nmcli'):
                                p = subprocess.run(['nmcli', 'dev', 'wifi', 'list'], capture_output=True, text=True, timeout=8)
                                out = p.stdout + '\n' + p.stderr
                            elif shutil.which('iw'):
                                # try interfaces
                                ifaces = [i for i in psutil.net_if_addrs().keys() if i.startswith('wl') or i.startswith('wlan')]
                                if not ifaces:
                                    ifaces = ['wlan0', 'wlp2s0']
                                parts = []
                                for iface in ifaces:
                                    try:
                                        p = subprocess.run(['iw', 'dev', iface, 'scan'], capture_output=True, text=True, timeout=8)
                                        parts.append(f"=== iface: {iface} ===\n" + (p.stdout or p.stderr or ''))
                                    except Exception:
                                        continue
                                out = '\n'.join(parts) or 'No iw output'
                            elif shutil.which('iwlist'):
                                ifaces = [i for i in psutil.net_if_addrs().keys() if i.startswith('wl') or i.startswith('wlan')]
                                if not ifaces:
                                    ifaces = ['wlan0', 'wlp2s0']
                                parts = []
                                for iface in ifaces:
                                    try:
                                        p = subprocess.run(['iwlist', iface, 'scanning'], capture_output=True, text=True, timeout=8)
                                        parts.append(f"=== iface: {iface} ===\n" + (p.stdout or p.stderr or ''))
                                    except Exception:
                                        continue
                                out = '\n'.join(parts) or 'No iwlist output'
                        except Exception as e:
                            out = f'scan failed: {e}'
                    else:
                        out = 'Unsupported platform for raw scan'

                    # Show in a scrollable dialog
                    raw_win = tk.Toplevel(self.wifi_window)
                    raw_win.title('Raw WiFi scan output')
                    raw_win.geometry('800x420')
                    txt = scrolledtext.ScrolledText(raw_win, wrap=tk.WORD)
                    txt.pack(fill=tk.BOTH, expand=True)
                    txt.insert('1.0', out)
                    txt.configure(state='disabled')
                except Exception as e:
                    try:
                        messagebox.showerror('Raw scan failed', str(e), parent=self.wifi_window)
                    except Exception:
                        pass

            raw_btn = tk.Button(btn_frame, text='Raw', command=_show_raw_scan_output, bg=self.colors['dark'], fg='white')
            raw_btn.pack(side=tk.LEFT, padx=6)

            def _show_parsed_scan_output():
                try:
                    nets = self.get_wifi_networks(timeout=8)
                    # write a quick timestamped log for offline inspection
                    try:
                        logpath = Path(__file__).with_suffix('.wifi.log') if '__file__' in globals() else Path.cwd() / 'forzeos_wifi.log'
                        with open(logpath, 'a', encoding='utf-8') as lf:
                            lf.write(f"--- {time.ctime()} Parsed scan ({len(nets)} entries) ---\n")
                            for n in nets:
                                lf.write(repr(n) + '\n')
                            lf.write('\n')
                    except Exception:
                        pass

                    raw_win = tk.Toplevel(self.wifi_window)
                    raw_win.title('Parsed WiFi scan output')
                    raw_win.geometry('800x420')
                    txt = scrolledtext.ScrolledText(raw_win, wrap=tk.WORD)
                    txt.pack(fill=tk.BOTH, expand=True)
                    if not nets:
                        txt.insert('1.0', 'No parsed networks (empty list)')
                    else:
                        for i, n in enumerate(nets, 1):
                            txt.insert(tk.END, f"{i}. {n}\n")
                    txt.configure(state='disabled')
                except Exception as e:
                    try:
                        messagebox.showerror('Parsed scan failed', str(e), parent=self.wifi_window)
                    except Exception:
                        pass

            parsed_btn = tk.Button(btn_frame, text='Parsed', command=_show_parsed_scan_output, bg=self.colors['dark'], fg='white')
            parsed_btn.pack(side=tk.LEFT, padx=6)

            def _export_csv():
                try:
                    filename = filedialog.asksaveasfilename(title='Export networks as CSV', defaultextension='.csv', filetypes=[('CSV','*.csv'),('All','*.*')], parent=self.wifi_window)
                    if not filename:
                        return
                    rows = []
                    cols_hdr = ('SSID','Signal','Channel','Security','BSSID')
                    for iid in tv.get_children():
                        rows.append(tv.item(iid, 'values'))
                    import csv
                    with open(filename, 'w', newline='', encoding='utf-8') as f:
                        w = csv.writer(f)
                        w.writerow(cols_hdr)
                        for r in rows:
                            w.writerow(r)
                    messagebox.showinfo('Export', f'Exported {len(rows)} entries to {filename}', parent=self.wifi_window)
                except Exception as e:
                    messagebox.showerror('Export failed', str(e), parent=self.wifi_window)

            def _copy_selected():
                try:
                    sel = tv.selection()
                    if not sel:
                        messagebox.showinfo('Copy', 'Select a row first', parent=self.wifi_window)
                        return
                    vals = tv.item(sel[0], 'values')
                    txt = '\t'.join(str(x) for x in vals)
                    try:
                        self.root.clipboard_clear(); self.root.clipboard_append(txt)
                        messagebox.showinfo('Copied', 'Row copied to clipboard', parent=self.wifi_window)
                    except Exception:
                        messagebox.showinfo('Copied', txt, parent=self.wifi_window)
                except Exception as e:
                    messagebox.showerror('Copy failed', str(e), parent=self.wifi_window)

            export_btn = tk.Button(btn_frame, text='Export CSV', command=_export_csv, bg=self.colors['dark'], fg='white')
            export_btn.pack(side=tk.LEFT, padx=6)
            copy_btn = tk.Button(btn_frame, text='Copy', command=_copy_selected, bg=self.colors['light'])
            copy_btn.pack(side=tk.LEFT, padx=6)

            # initial scan
            _on_scan()

        except Exception as e:
            try:
                messagebox.showerror('WiFi', f'Failed to open WiFi settings: {e}')
            except Exception:
                pass
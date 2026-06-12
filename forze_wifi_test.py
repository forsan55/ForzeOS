# wifi_scan_test.py
import subprocess, re, time, sys

def parse_netsh(raw):
    results = []
    ssid = None
    cur = None
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r'(?i)^ssid\s*(?:\d+)?\s*:\s*(.*)$', line)
        if m:
            ssid = m.group(1).strip()
            cur = None
            continue
        m = re.match(r'(?i)^bssid\s*\d*\s*:\s*(.*)$', line)
        if m:
            if cur:
                cur.setdefault('ssid', ssid or '')
                results.append(cur)
            cur = {'bssid': m.group(1).strip().lower(), 'ssid': ssid or ''}
            continue
        if ':' in line:
            k,v = [p.strip() for p in line.split(':',1)]
            lk = k.lower()
            target = cur if cur is not None else {'ssid': ssid or ''}
            if lk == 'signal':
                try:
                    target['signal'] = int(v.replace('%','').strip())
                except:
                    target['signal'] = v
            elif lk == 'channel':
                try:
                    target['channel'] = int(v)
                except:
                    target['channel'] = v
            elif lk.startswith('authentication'):
                target['auth'] = v
            elif lk.startswith('encryption'):
                target['encryption'] = v
            else:
                target.setdefault('other', {})[k] = v
            if cur is None and 'bssid' in target:
                results.append(target)
    if cur:
        cur.setdefault('ssid', ssid or '')
        results.append(cur)
    # coerce duplicates out
    seen = set()
    out = []
    for r in results:
        b = (r.get('bssid') or '').lower()
        if b and b not in seen:
            seen.add(b)
            out.append(r)
    return out

def run_netsh_basic():
    try:
        p = subprocess.run(['netsh','wlan','show','networks','mode=bssid'], capture_output=True, text=True, timeout=8)
        return p.stdout + '\n' + p.stderr
    except Exception as e:
        return ''

def run_netsh_per_interface():
    aggregated = []
    try:
        p = subprocess.run(['netsh','wlan','show','interfaces'], capture_output=True, text=True, timeout=6)
        iface_out = p.stdout or p.stderr or ''
        iface_names = []
        for line in iface_out.splitlines():
            m = re.match(r'(?i)^\s*name\s*:\s*(.*)$', line)
            if m:
                nm = m.group(1).strip()
                if nm:
                    iface_names.append(nm)
    except Exception:
        iface_names = []
    if not iface_names:
        iface_names = ['Wi-Fi','Wireless Network Connection','wlan0']
    seen = set()
    for iface in iface_names:
        try:
            # note: interface name may need escaping/quotes; we pass as a single arg
            cmd = ['netsh','wlan','show','networks', f'interface="{iface}"', 'mode=bssid']
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
            parsed = parse_netsh(p.stdout or p.stderr or '')
            for ent in parsed:
                b = (ent.get('bssid') or '').lower()
                if b and b not in seen:
                    seen.add(b)
                    aggregated.append(ent)
        except Exception:
            continue
    return aggregated

def try_pywifi_scan(timeout=6):
    try:
        import pywifi
        from pywifi import PyWiFi, const
    except Exception:
        return []
    try:
        wifi = PyWiFi()
        ifaces = wifi.interfaces()
        out = []
        for iface in ifaces:
            try:
                iface.scan()
            except Exception:
                continue
            time.sleep(min(3, timeout))
            for r in iface.scan_results():
                ss = getattr(r,'ssid', '') or ''
                b = getattr(r,'bssid', '') or getattr(r,'bssid', None) or ''
                sig = getattr(r,'signal', None)
                freq = getattr(r,'freq', None)
                out.append({'ssid': ss, 'bssid': b.lower() if b else '', 'signal': sig, 'freq': freq})
        # dedupe
        seen = set(); final=[]
        for e in out:
            k = (e.get('bssid') or '').lower()
            if k and k not in seen:
                seen.add(k); final.append(e)
        return final
    except Exception:
        return []

def main():
    print("Running netsh basic scan...")
    raw = run_netsh_basic()
    parsed = parse_netsh(raw)
    if parsed:
        print(f"Found {len(parsed)} network(s) by basic netsh:")
        for p in parsed:
            print(f"  SSID: {p.get('ssid')!r}  BSSID: {p.get('bssid')}  Signal: {p.get('signal')}")
    else:
        print("No networks found by basic netsh output.")

    if len(parsed) <= 1:
        print("\nTrying per-interface netsh scans...")
        per = run_netsh_per_interface()
        if per:
            print(f"Found {len(per)} network(s) by per-interface scan:")
            for p in per:
                print(f"  SSID: {p.get('ssid')!r}  BSSID: {p.get('bssid')}  Signal: {p.get('signal')}")
        else:
            print("No extra networks found per-interface.")

        # merge parsed + per
        merged = { (x.get('bssid') or ''): x for x in (parsed + per) if x.get('bssid')}
        results = list(merged.values())
    else:
        results = parsed

    if len(results) <= 1:
        print("\nAttempting pywifi fallback (if installed)...")
        py = try_pywifi_scan(timeout=6)
        if py:
            print(f"pywifi found {len(py)} networks:")
            for p in py:
                print(f"  SSID: {p.get('ssid')!r}  BSSID: {p.get('bssid')}  Signal: {p.get('signal')}")
            # merge
            merged = { (x.get('bssid') or ''): x for x in (results + py) if x.get('bssid')}
            results = list(merged.values())
        else:
            print("pywifi not available or found nothing.")

    print("\nFinal aggregated results:")
    if results:
        for r in results:
            print(f"SSID: {r.get('ssid')!r}  BSSID: {r.get('bssid')}  Signal: {r.get('signal')}  Channel: {r.get('channel','')}")
    else:
        print("No networks detected.")

    if len(results) > 1:
        print("\nSUCCESS: Multiple networks seen.")
        sys.exit(0)
    elif len(results) == 1:
        print("\nOnly 1 network visible. If other devices see more networks in same location, follow the checklist in the instructions (restart wlansvc, check driver, disable hotspot, try another adapter).")
        sys.exit(2)
    else:
        print("\nNo networks visible at all. Check Wi‑Fi adapter, drivers, and services.")
        sys.exit(3)

if __name__ == '__main__':
    main()
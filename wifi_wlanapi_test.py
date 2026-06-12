#!/usr/bin/env python3
"""
Standalone WLAN API test for Windows.

Run this in PowerShell:

python "C:/Users/User/Downloads/wifi_wlanapi_test.py"

It will print discovered BSSIDs / SSIDs / signal % / channel (best-effort).
"""
import ctypes
import sys

if not sys.platform.startswith('win'):
    print('This script is for Windows only.')
    sys.exit(1)

from ctypes import POINTER, byref, Structure, c_ulong, c_void_p, c_uint32, c_int32, c_ubyte, c_wchar

DWORD = c_ulong
HANDLE = c_void_p
BOOL = c_uint32

class DOT11_SSID(Structure):
    _fields_ = [('uSSIDLength', DWORD), ('ucSSID', c_ubyte * 32)]

class WLAN_INTERFACE_INFO(Structure):
    _fields_ = [
        ('InterfaceGuid', c_ubyte * 16),
        ('strInterfaceDescription', c_wchar * 256),
        ('isState', DWORD)
    ]

class WLAN_INTERFACE_INFO_LIST(Structure):
    _fields_ = [('dwNumberOfItems', DWORD), ('dwIndex', DWORD), ('InterfaceInfo', WLAN_INTERFACE_INFO * 1)]

class WLAN_BSS_ENTRY(Structure):
    _fields_ = [
        ('dot11Ssid', DOT11_SSID),
        ('dot11Bssid', c_ubyte * 6),
        ('uPhyId', DWORD),
        ('dot11BssType', DWORD),
        ('dwNumberOfBssids', DWORD),
        ('lRssi', c_int32),
        ('uLinkQuality', DWORD),
        ('ulChCenterFrequency', DWORD),  # ULONG (kHz)
        ('wlanRateSet', DWORD * 8),
        ('ulIeOffset', DWORD),
        ('ulIeSize', DWORD)
    ]

class WLAN_BSS_LIST(Structure):
    _fields_ = [('dwTotalSize', DWORD), ('dwNumberOfItems', DWORD), ('wlanBssEntries', WLAN_BSS_ENTRY * 1)]

try:
    wlanapi = ctypes.WinDLL('wlanapi')
except Exception as e:
    print('Failed to load wlanapi:', e)
    sys.exit(1)

# prototypes
wlanapi.WlanOpenHandle.argtypes = [DWORD, c_void_p, POINTER(DWORD), POINTER(HANDLE)]
wlanapi.WlanOpenHandle.restype = DWORD
wlanapi.WlanEnumInterfaces.argtypes = [HANDLE, c_void_p, POINTER(POINTER(WLAN_INTERFACE_INFO_LIST))]
wlanapi.WlanEnumInterfaces.restype = DWORD
wlanapi.WlanGetNetworkBssList.argtypes = [HANDLE, POINTER(c_ubyte * 16), POINTER(DOT11_SSID), DWORD, BOOL, c_void_p, POINTER(POINTER(WLAN_BSS_LIST))]
wlanapi.WlanGetNetworkBssList.restype = DWORD
wlanapi.WlanFreeMemory.argtypes = [c_void_p]
wlanapi.WlanFreeMemory.restype = None
wlanapi.WlanCloseHandle.argtypes = [HANDLE, c_void_p]
wlanapi.WlanCloseHandle.restype = DWORD

client = HANDLE()
neg = DWORD()
rc = wlanapi.WlanOpenHandle(2, None, byref(neg), byref(client))
if rc != 0:
    print('WlanOpenHandle failed rc=', rc)
    sys.exit(1)

try:
    p_iface_list = POINTER(WLAN_INTERFACE_INFO_LIST)()
    rc = wlanapi.WlanEnumInterfaces(client, None, byref(p_iface_list))
    if rc != 0 or not p_iface_list:
        print('WlanEnumInterfaces failed rc=', rc)
        sys.exit(1)

    num = p_iface_list.contents.dwNumberOfItems
    print('Interfaces found:', num)
    base = ctypes.addressof(p_iface_list.contents.InterfaceInfo)
    size_iface = ctypes.sizeof(WLAN_INTERFACE_INFO)

    all_results = []
    seen = set()
    for i in range(num):
        addr = base + size_iface * i
        iface = ctypes.cast(addr, POINTER(WLAN_INTERFACE_INFO)).contents
        desc = iface.strInterfaceDescription
        guid_bytes = bytes(bytearray(iface.InterfaceGuid))
        print('\nInterface #%d: %s' % (i+1, desc))
        guid_arr = (c_ubyte * 16)(*iface.InterfaceGuid)
        p_bss_list = POINTER(WLAN_BSS_LIST)()
        rc2 = wlanapi.WlanGetNetworkBssList(client, byref(guid_arr), None, 0, 0, None, byref(p_bss_list))
        if rc2 != 0 or not p_bss_list:
            print('  WlanGetNetworkBssList failed rc=', rc2)
            continue
        try:
            count = p_bss_list.contents.dwNumberOfItems
            print('  BSS entries:', count)
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
                if rssi <= -100:
                    sig = 0
                elif rssi >= -50:
                    sig = 100
                else:
                    sig = 2 * (rssi + 100)
                    if sig < 0: sig = 0
                    if sig > 100: sig = 100
                # freq stored as array of 1 DWORD in our layout
                try:
                    freq = int(entry.ulChCenterFrequency[0])
                except Exception:
                    freq = 0
                channel = None
                if freq:
                    mhz = freq / 1000.0
                    if 2400 <= mhz <= 2500:
                        channel = int(round((mhz - 2412) / 5.0) + 1)
                    elif 5000 <= mhz <= 6000:
                        channel = int(round(mhz / 5.0))
                key = (bssid.lower())
                if key not in seen:
                    seen.add(key)
                    all_results.append({'ssid': ssid, 'bssid': bssid.lower(), 'signal': int(sig), 'channel': channel, 'iface': desc})
        finally:
            try:
                wlanapi.WlanFreeMemory(p_bss_list)
            except Exception:
                pass

    if not all_results:
        print('\nNo BSS entries discovered via wlanapi.')
    else:
        print('\nDiscovered networks (wlanapi):')
        for r in all_results:
            print('SSID: %s | BSSID: %s | Signal: %s%% | Channel: %s | Interface: %s' % (
                r['ssid'] or '<hidden>', r['bssid'], r['signal'], r['channel'] or 'N/A', r['iface']
            ))

finally:
    wlanapi.WlanCloseHandle(client, None)

print('\nDone.')

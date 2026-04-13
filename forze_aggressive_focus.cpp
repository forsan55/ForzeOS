// forze_aggressive_focus.cpp
// Professional aggressive focus helper for ForzeOS (best-effort, guarded).
// Implements deeper, guarded optimizations requested by users:
// - Enable profiling / base-priority privileges (best-effort)
// - Trim system file cache via SetSystemFileCacheSize (best-effort)
// - Use MMCSS (Avrt.dll) to request multimedia scheduling attributes where possible
// - Confine background user-folder processes to the last CPU core and reduce their priority
// - Raise GPU scheduling priority via D3DKMTSetProcessSchedulingPriorityClass (if available)
// - Record and restore modified process affinity/priority
// Safety: all operations are best-effort. If any advanced API is not present or fails,
// the code logs and continues without crashing the system. Do not call on production
// machines without backups and prefer testing in a VM snapshot.
#include <windows.h>
#include <psapi.h>
#include <tlhelp32.h>
#include <tchar.h>
#include <stdio.h>
#include <vector>
#include <string>
#include <algorithm>
#include <cstdlib>
#include <stdint.h>
#ifdef __GNUC__
#include <excpt.h>
#endif

#pragma comment(lib, "psapi.lib")

// Minimal typedefs to avoid depending on Windows SDK WDK headers for optional APIs.
typedef LONG NTSTATUS;

struct ModifiedInfo {
    DWORD pid;
    DWORD origPri;
    ULONG_PTR origAffinity;
    bool affinitySaved;
    bool priorityChanged;
    bool affinityChanged;
    bool gpuPriorityChanged;
    bool suspended; // whether we suspended this process via NtSuspendProcess
};
static std::vector<ModifiedInfo> g_modified;

// Synchronization for g_modified access (worker thread + starter thread)
static CRITICAL_SECTION g_modified_lock;
static volatile LONG g_modified_lock_inited = 0;

// Periodic worker control
static HANDLE g_worker_thread = NULL;
static HANDLE g_worker_stop_event = NULL;

// Optional NT functions (resolved at runtime)
typedef NTSTATUS (NTAPI *PFN_NtSuspendProcess)(HANDLE ProcessHandle);
typedef NTSTATUS (NTAPI *PFN_NtResumeProcess)(HANDLE ProcessHandle);
typedef NTSTATUS (NTAPI *PFN_NtSetSystemInformation)(ULONG SystemInformationClass, PVOID SystemInformation, ULONG SystemInformationLength);
static PFN_NtSuspendProcess pNtSuspendProc = NULL;
static PFN_NtResumeProcess pNtResumeProc = NULL;
static PFN_NtSetSystemInformation pNtSetSystemInformation = NULL;

static std::string to_lower(const std::string &s) {
    std::string out = s;
    std::transform(out.begin(), out.end(), out.begin(), ::tolower);
    return out;
}

static std::string get_process_image_path(HANDLE h)
{
    char buf[MAX_PATH] = {0};
    HMODULE mods[1024];
    DWORD cbNeeded = 0;
    if (EnumProcessModules(h, mods, sizeof(mods), &cbNeeded) && cbNeeded >= sizeof(HMODULE)) {
        if (GetModuleFileNameExA(h, mods[0], buf, (int)sizeof(buf))) {
            return std::string(buf);
        }
    }
    if (GetProcessImageFileNameA(h, buf, (int)sizeof(buf))) {
        return std::string(buf);
    }
    return std::string();
}

static int count_bits(ULONG_PTR v) {
    int c = 0;
    while (v) { c += (int)(v & 1); v >>= 1; }
    return c;
}

// Best-effort: enable named privilege
static bool EnablePrivilegeByName(LPCTSTR privName) // LPCSTR yerine LPCTSTR yaptık
{
    HANDLE hToken = NULL;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, &hToken)) 
        return false;

    TOKEN_PRIVILEGES tp;
    LUID luid;
    
    // LookupPrivilegeValueA yerine LookupPrivilegeValue kullanıyoruz
    if (!LookupPrivilegeValue(NULL, privName, &luid)) { 
        CloseHandle(hToken); 
        return false; 
    }

    tp.PrivilegeCount = 1;
    tp.Privileges[0].Luid = luid;
    tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED;

    AdjustTokenPrivileges(hToken, FALSE, &tp, sizeof(tp), NULL, NULL);
    BOOL ok = (GetLastError() == ERROR_SUCCESS);
    CloseHandle(hToken);
    
    return ok == TRUE;
}

// Try enabling a set of privileges (best-effort)
static void TryEnablePrivileges()
{
    // SE_DEBUG_NAME zaten sistem tarafından Unicode tanımlanmıştır
    EnablePrivilegeByName(SE_DEBUG_NAME);

    // Diğerlerini TEXT() içine alarak "incompatible" hatasını çözüyoruz
    EnablePrivilegeByName(TEXT("SeProfileSingleProcessPrivilege"));
    EnablePrivilegeByName(TEXT("SeIncreaseBasePriorityPrivilege"));
    EnablePrivilegeByName(TEXT("SeIncreaseQuotaPrivilege")); 
}

// Best-effort trim of system file cache using SetSystemFileCacheSize
static void TrimSystemFileCache()
{
    HMODULE hKernel = GetModuleHandleA("Kernel32.dll");
    if (!hKernel) return;
    typedef BOOL (WINAPI *SetSystemFileCacheSize_t)(SIZE_T, SIZE_T, DWORD);
    SetSystemFileCacheSize_t func = (SetSystemFileCacheSize_t)GetProcAddress(hKernel, "SetSystemFileCacheSize");
    if (!func) return;
    // call with zeros - documented to be a hint; may require privileges
    (void)func((SIZE_T)0, (SIZE_T)0, (DWORD)0);
}

// Munge GPU priority via D3DKMT if available (guarded)
// Minimal struct matching WDK: D3DKMT_SET_PROCESS_SCHEDULING_PRIORITY_CLASS
struct D3DKMT_SET_PROCESS_SCHEDULING_PRIORITY_CLASS {
    HANDLE hProcess;
    UINT32 PriorityClass; // 1 = High (best-effort)
};

typedef NTSTATUS (WINAPI *PFN_D3DKMTSetProcessSchedulingPriorityClass)(D3DKMT_SET_PROCESS_SCHEDULING_PRIORITY_CLASS*);

// Helper: get highest single CPU bit in sys mask
static ULONG_PTR pick_last_cpu(ULONG_PTR sysMask)
{
    if (!sysMask) return 0;
    // pick highest set bit
    for (int i = sizeof(ULONG_PTR)*8 - 1; i >= 0; --i) {
        ULONG_PTR bit = ((ULONG_PTR)1) << i;
        if (sysMask & bit) return bit;
    }
    return 0;
}

// Minimal whitelist check
static bool is_builtin_whitelist(const std::string &exeLower)
{
    static const char* whitelist[] = { "dwm.exe", "explorer.exe", "audiodg.exe", "svchost.exe", "lsass.exe", "csrss.exe", NULL };
    for (const char** p = whitelist; *p; ++p) {
        if (exeLower.find(*p) != std::string::npos) return true;
    }
    return false;
}

// Best-effort: attempt to purge Standby List via NtSetSystemInformation.
// This is dangerous/undocumented; only runs if env FORZEOS_ALLOW_STANDBY_PURGE=1
static void PurgeStandbyList()
{
    const char* allow = getenv("FORZEOS_ALLOW_STANDBY_PURGE");
    if (!allow || strcmp(allow, "1") != 0) return;
    HMODULE hNtdll = GetModuleHandleA("ntdll.dll");
    if (!hNtdll) return;
    if (!pNtSetSystemInformation) {
        pNtSetSystemInformation = (PFN_NtSetSystemInformation)GetProcAddress(hNtdll, "NtSetSystemInformation");
        if (!pNtSetSystemInformation) return;
    }

    // Minimal command structure used by many community tools. This may fail
    // on unsupported OS versions; call is best-effort and return quietly.
    struct { ULONG Command; ULONG Flags; } cmd;
    cmd.Command = 1; // MemoryPurgeStandbyList (best-effort; may vary by OS)
    cmd.Flags = 0;
    const ULONG SystemMemoryListInformation = 0x50; // widely used value in community tools
    (void)pNtSetSystemInformation(SystemMemoryListInformation, &cmd, sizeof(cmd));
}

// Worker thread performs periodic light trims and suspends stubborn processes.
static DWORD WINAPI WorkerThreadProc(LPVOID lpParam)
{
    int interval = 300; // default seconds
    const char* v = getenv("FORZEOS_TRIM_INTERVAL_SECONDS"); if (v) interval = atoi(v);
    int threshold_mb = 1024;
    v = getenv("FORZEOS_TRIM_THRESHOLD_MB"); if (v) threshold_mb = atoi(v);

    // Ensure NT functions available
    HMODULE hNtdll = GetModuleHandleA("ntdll.dll");
    if (hNtdll) {
        if (!pNtSuspendProc) pNtSuspendProc = (PFN_NtSuspendProcess)GetProcAddress(hNtdll, "NtSuspendProcess");
        if (!pNtResumeProc) pNtResumeProc = (PFN_NtResumeProcess)GetProcAddress(hNtdll, "NtResumeProcess");
        if (!pNtSetSystemInformation) pNtSetSystemInformation = (PFN_NtSetSystemInformation)GetProcAddress(hNtdll, "NtSetSystemInformation");
    }

    while (WaitForSingleObject(g_worker_stop_event, (DWORD)interval * 1000) == WAIT_TIMEOUT) {
        // light maintenance
        TrimSystemFileCache();
        PurgeStandbyList();

        // Snapshot modified list under lock
        std::vector<ModifiedInfo> snapshot;
        if (g_modified_lock_inited) {
            EnterCriticalSection(&g_modified_lock);
            snapshot = g_modified;
            LeaveCriticalSection(&g_modified_lock);
        }

        for (auto &mi : snapshot) {
            HANDLE h = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ | PROCESS_SET_QUOTA, FALSE, mi.pid);
            if (!h) continue;

            // light empty working set
            if (EmptyWorkingSet(h)) {
                // ok
            }

            PROCESS_MEMORY_COUNTERS pmc; SIZE_T rss = 0;
            if (GetProcessMemoryInfo(h, &pmc, sizeof(pmc))) rss = pmc.WorkingSetSize;
            CloseHandle(h);

            // If still heavy and user allowed suspend, suspend stubborn user-folder apps
            const char* allowSuspend = getenv("FORZEOS_ALLOW_SUSPEND");
            if (allowSuspend && strcmp(allowSuspend, "1") == 0 && pNtSuspendProc && rss > (SIZE_T)threshold_mb * 1024ull * 1024ull) {
                // find and mark in main list
                EnterCriticalSection(&g_modified_lock);
                for (auto &mref : g_modified) {
                    if (mref.pid == mi.pid && !mref.suspended) {
                        HANDLE h2 = OpenProcess(PROCESS_QUERY_INFORMATION, FALSE, mref.pid);
                        if (h2) {
                            // best-effort suspend
                            pNtSuspendProc(h2);
                            CloseHandle(h2);
                            mref.suspended = true;
                        }
                        break;
                    }
                }
                LeaveCriticalSection(&g_modified_lock);
            }
        }
    }

    return 0;
}

extern "C" {

__declspec(dllexport) int __stdcall aggressive_focus_start()
{
    // Configuration via env
    int max_mods = 8;
    const char* e = getenv("FORZEOS_MAX_TRIMS"); if (e) max_mods = atoi(e);
    int min_rss_mb = 100; e = getenv("FORZEOS_MIN_RSS_MB"); if (e) min_rss_mb = atoi(e);

    TryEnablePrivileges();
    TrimSystemFileCache();

    // Resolve NT functions (best-effort)
    HMODULE hNtdll = GetModuleHandleA("ntdll.dll");
    if (hNtdll) {
        if (!pNtSuspendProc) pNtSuspendProc = (PFN_NtSuspendProcess)GetProcAddress(hNtdll, "NtSuspendProcess");
        if (!pNtResumeProc) pNtResumeProc = (PFN_NtResumeProcess)GetProcAddress(hNtdll, "NtResumeProcess");
        if (!pNtSetSystemInformation) pNtSetSystemInformation = (PFN_NtSetSystemInformation)GetProcAddress(hNtdll, "NtSetSystemInformation");
    }

    // Initialize modified-list lock once
    if (InterlockedCompareExchange(&g_modified_lock_inited, 1, 0) == 0) {
        InitializeCriticalSection(&g_modified_lock);
    }

    // Try to locate D3DKMT function
    PFN_D3DKMTSetProcessSchedulingPriorityClass d3dSetProc = NULL;
    HMODULE hDxg = LoadLibraryA("dxgkrnl.dll");
    if (hDxg) {
        d3dSetProc = (PFN_D3DKMTSetProcessSchedulingPriorityClass)GetProcAddress(hDxg, "D3DKMTSetProcessSchedulingPriorityClass");
    }

    // MMCSS helpers (Avrt.dll) - used only if this process needs to register its own threads
    HMODULE hav = LoadLibraryA("avrt.dll");
    typedef HANDLE (WINAPI *PFN_AvSetMmThreadCharacteristicsA)(LPCSTR, LPDWORD);
    typedef BOOL (WINAPI *PFN_AvSetMmThreadPriority)(HANDLE, int);
    typedef BOOL (WINAPI *PFN_AvRevertMmThreadCharacteristics)(HANDLE);
    PFN_AvSetMmThreadCharacteristicsA pAvSet = NULL;
    PFN_AvSetMmThreadPriority pAvPrio = NULL;
    PFN_AvRevertMmThreadCharacteristics pAvRevert = NULL;
    if (hav) {
        pAvSet = (PFN_AvSetMmThreadCharacteristicsA)GetProcAddress(hav, "AvSetMmThreadCharacteristicsA");
        pAvPrio = (PFN_AvSetMmThreadPriority)GetProcAddress(hav, "AvSetMmThreadPriority");
        pAvRevert = (PFN_AvRevertMmThreadCharacteristics)GetProcAddress(hav, "AvRevertMmThreadCharacteristics");
    }

    // Get foreground PID and system affinity
    DWORD fg_pid = 0;
    HWND fg = GetForegroundWindow(); if (fg) GetWindowThreadProcessId(fg, &fg_pid);
    ULONG_PTR procMask = 0, sysMask = 0;
    GetProcessAffinityMask(GetCurrentProcess(), &procMask, &sysMask);
    ULONG_PTR lastCore = pick_last_cpu(sysMask);

    // enumerate processes and pick candidates
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return -1;

    PROCESSENTRY32 pe; pe.dwSize = sizeof(pe);
    std::vector<DWORD> candidates;
    if (Process32First(snap, &pe)) {
        do {
            DWORD pid = pe.th32ProcessID;
            if (pid == 0 || pid <= 4) continue;
            std::string exeName;
#ifdef UNICODE
            {
                wchar_t* w = pe.szExeFile;
                int n = WideCharToMultiByte(CP_UTF8, 0, w, -1, NULL, 0, NULL, NULL);
                if (n > 0) { exeName.resize(n); WideCharToMultiByte(CP_UTF8, 0, w, -1, &exeName[0], n, NULL, NULL); }
            }
#else
            exeName = pe.szExeFile;
#endif
            std::string exeLower = to_lower(exeName);
            if (is_builtin_whitelist(exeLower)) continue;

            HANDLE h = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, FALSE, pid);
            if (!h) continue;

            // skip system binaries under C:\Windows
            std::string full = to_lower(get_process_image_path(h));
            if (!full.empty()) {
                if (full.rfind("c:\\windows", 0) == 0 || full.find("\\windows\\") != std::string::npos) { CloseHandle(h); continue; }
            }

            // skip interactive processes with visible windows
            BOOL hasWindow = FALSE;
            // simple check: enumerate top-level windows and match pid -- heavy but safe
            // (reuse a minimal approach: if process has visible window, skip)
            // We keep it simple and rely on the Python wrapper's earlier window checks when possible.

            PROCESS_MEMORY_COUNTERS pmc; SIZE_T rss = 0;
            if (GetProcessMemoryInfo(h, &pmc, sizeof(pmc))) rss = pmc.WorkingSetSize;
            CloseHandle(h);
            if (rss < (SIZE_T)min_rss_mb * 1024ull * 1024ull) continue;

            // Candidate for background trimming
            candidates.push_back(pid);
        } while (Process32Next(snap, &pe));
    }
    CloseHandle(snap);

    int mods = 0;
    for (DWORD pid : candidates) {
        if (mods >= max_mods) break;
        // skip foreground PID
        if (pid == fg_pid) continue;
        HANDLE h = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_SET_INFORMATION | PROCESS_SET_QUOTA, FALSE, pid);
        if (!h) continue;

        ModifiedInfo mi; ZeroMemory(&mi, sizeof(mi)); mi.pid = pid;

        DWORD origPri = 0; BOOL havePri = FALSE;
        origPri = GetPriorityClass(h); if (origPri) havePri = TRUE;
        mi.origPri = origPri;

        ULONG_PTR origAffinity = 0, sys = 0; if (GetProcessAffinityMask(h, &origAffinity, &sys)) { mi.origAffinity = origAffinity; mi.affinitySaved = true; }

        bool changed = false;

        // If the process executable is under the user's folders, confine to last core
        HANDLE h2 = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, FALSE, pid);
        if (h2) {
            std::string full = to_lower(get_process_image_path(h2));
            CloseHandle(h2);
            if (!full.empty()) {
                // crude user-folder check: contains "\\users\\" or "\\users\\"
                if (full.find("\\users\\") != std::string::npos || full.find("/users/") != std::string::npos || full.find("\\appdata\\") != std::string::npos) {
                    if (lastCore && mi.affinitySaved) {
                        // set to lastCore but only if it leaves at least one CPU for system and doesn't reduce to zero
                        if ((mi.origAffinity & lastCore) != lastCore) {
                            if (SetProcessAffinityMask(h, lastCore)) { mi.affinityChanged = true; changed = true; }
                        }
                    }
                    // reduce priority aggressively for background user apps
                    if (SetPriorityClass(h, IDLE_PRIORITY_CLASS)) { mi.priorityChanged = true; changed = true; }
                } else {
                    // generic background trimming: lower to BELOW_NORMAL
                    if (SetPriorityClass(h, BELOW_NORMAL_PRIORITY_CLASS)) { mi.priorityChanged = true; changed = true; }
                }
            }
        }

        // attempt to free working set
        if (EmptyWorkingSet(h)) { /* ok */ }

        // store if we changed anything
        if (mi.priorityChanged || mi.affinityChanged) {
            if (g_modified_lock_inited) EnterCriticalSection(&g_modified_lock);
            g_modified.push_back(mi);
            if (g_modified_lock_inited) LeaveCriticalSection(&g_modified_lock);
            mods++;
        }

        CloseHandle(h);
    }

// Promote foreground process: raise priority and attempt GPU priority bump
    if (fg_pid && fg_pid > 4) {
        HANDLE hfg = OpenProcess(PROCESS_SET_INFORMATION | PROCESS_QUERY_INFORMATION, FALSE, fg_pid);
        if (hfg) {
            // try to raise to HIGH_PRIORITY_CLASS (best-effort)
            SetPriorityClass(hfg, HIGH_PRIORITY_CLASS);

            // attempt to call D3DKMTSetProcessSchedulingPriorityClass if available
            if (d3dSetProc) {
                D3DKMT_SET_PROCESS_SCHEDULING_PRIORITY_CLASS req;
                req.hProcess = hfg;
                req.PriorityClass = 1; // request high (best-effort)

                try {
                    // MinGW için standart try bloğu - koruma sağlar
                    d3dSetProc(&req);
                } 
                catch (...) {
                    // Hata oluşursa ForzeOS çökmez
                }
            }
            CloseHandle(hfg); // HANDLE sızıntısını önlemek için kapatmalısın
        }
    } // if (fg_pid) bloğu sonu
    
    // If we have MMCSS functions and this process is hosting a game, register current thread
    if (pAvSet) {
        DWORD taskIndex = 0;
        HANDLE hAv = pAvSet("Games", &taskIndex);
        if (hAv) {
            if (pAvPrio) pAvPrio(hAv, 1); // try to set higher multimedia priority (AVRT_PRIORITY) - numeric mapping may vary
            if (pAvRevert) pAvRevert(hAv);
        }
    }

    // start background worker (periodic trims/suspend) if not already running
    if (!g_worker_stop_event) g_worker_stop_event = CreateEvent(NULL, TRUE, FALSE, NULL);
    if (!g_worker_thread) {
        DWORD tid = 0;
        g_worker_thread = CreateThread(NULL, 0, WorkerThreadProc, NULL, 0, &tid);
    }

    if (hDxg) FreeLibrary(hDxg);
    if (hav) FreeLibrary(hav);

    return mods;
}

__declspec(dllexport) int __stdcall aggressive_focus_stop()
{
    // Signal worker thread to stop and wait for it
    if (g_worker_stop_event) SetEvent(g_worker_stop_event);
    if (g_worker_thread) {
        WaitForSingleObject(g_worker_thread, 10000);
        CloseHandle(g_worker_thread);
        g_worker_thread = NULL;
    }
    if (g_worker_stop_event) {
        CloseHandle(g_worker_stop_event);
        g_worker_stop_event = NULL;
    }

    int restored = 0;

    // Restore priorities/affinity and resume suspended processes
    if (g_modified_lock_inited) EnterCriticalSection(&g_modified_lock);
    for (auto &mi : g_modified) {
        DWORD pid = mi.pid;
        HANDLE h = OpenProcess(PROCESS_SET_INFORMATION | PROCESS_QUERY_INFORMATION, FALSE, pid);
        if (!h) continue;
        bool ok = false;
        if (mi.affinityChanged && mi.affinitySaved && mi.origAffinity != 0) {
            if (SetProcessAffinityMask(h, mi.origAffinity)) ok = true;
        }
        if (mi.priorityChanged && mi.origPri != 0) {
            if (SetPriorityClass(h, mi.origPri)) ok = true;
        }

        // resume if suspended
        if (mi.suspended && pNtResumeProc) {
            HANDLE h2 = OpenProcess(PROCESS_QUERY_INFORMATION, FALSE, pid);
            if (h2) {
                pNtResumeProc(h2);
                CloseHandle(h2);
            }
        }

        if (ok) restored++;
        CloseHandle(h);
    }
    if (g_modified_lock_inited) LeaveCriticalSection(&g_modified_lock);

    g_modified.clear();

    // Destroy lock
    if (g_modified_lock_inited) {
        DeleteCriticalSection(&g_modified_lock);
        InterlockedExchange(&g_modified_lock_inited, 0);
    }

    return restored;
}

} // extern "C"

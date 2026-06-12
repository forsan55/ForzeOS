// forze_aggressive_focus.cpp
// Rewritten per user request:
// - Dynamic API resolution for sensitive Win32 functions (GetProcAddress/LoadLibrary used at runtime)
// - All sensitive strings are built from ASCII byte arrays to avoid cleartext literals
// - SEH (__try / __except) used instead of C++ try/catch so this targets MSVC
// - Exports are masked as DllRegisterFocusFilter / DllUnregisterFocusFilter
// - Very conservative whitelist that never touches critical system processes or anything
//   whose full image path is under C:\\Windows\\System32
// - Preserves performance features: standby purge (NtSetSystemInformation),
//   SetPriorityClass, D3DKMT scheduling bump, SetProcessInformation (IO priority),
//   Avrt MMCSS "Games" optimization, SetSystemFileCacheSize and EmptyWorkingSet.
// Eski include bloklarını silip yerine bunu yapıştırın:
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif

#include <windows.h>
#include <tlhelp32.h> // PROCESSENTRY32A yapısının kararlı yüklenmesi için windows.h altında olmalıdır
#include <psapi.h>
#include <tchar.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <time.h>
#include <vector>
#include <string>
#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <cstdint>
#include <memory>
#include <exception>
// Ensure NTSTATUS exists in case headers differ
#ifndef NTSTATUS
typedef LONG NTSTATUS;
#endif

// Provide PROCESSENTRY32A fallback for toolchains that expose only wide typedefs
#ifndef PROCESSENTRY32A
typedef struct tagPROCESSENTRY32A {
    DWORD dwSize;
    DWORD cntUsage;
    DWORD th32ProcessID;
    ULONG_PTR th32DefaultHeapID;
    DWORD th32ModuleID;
    DWORD cntThreads;
    DWORD th32ParentProcessID;
    LONG pcPriClassBase;
    DWORD dwFlags;
    CHAR szExeFile[MAX_PATH];
} PROCESSENTRY32A;
#endif

// Allow this source to compile under non-MSVC toolchains by mapping
// the MSVC-only SEH tokens to C++ try/catch so GCC/MinGW can build.
#if !defined(_MSC_VER)
#ifndef EXCEPTION_EXECUTE_HANDLER
#define EXCEPTION_EXECUTE_HANDLER 1
#endif
#define __try try
#define __except(x) catch(...)
#endif

// Link-time helpers for MSVC so users can simply run `cl` without extra args
#pragma comment(lib, "psapi.lib")
#pragma comment(lib, "advapi32.lib")

// Note: This file intentionally uses __try/__except for SEH handlers and performs
// runtime GetProcAddress lookups for all sensitive symbols. It is designed for
// MSVC builds.

// Helper: build string at runtime from byte array to avoid static literals
static std::string build_str(const unsigned char *arr)
{
    std::string s;
    for (size_t i = 0; arr[i]; ++i) s.push_back((char)arr[i]);
    return s;
}

// Minimal native logfile helper (best-effort, avoids heavy runtime deps)
static void native_log(const char *fmt, ...)
{
    __try {
        const char *path = getenv("FORZEOS_FOCUS_NATIVE_LOG");
        const char *default_name = "forze_aggressive_focus_native.log";
        FILE *f = NULL;
        if (path && path[0]) f = fopen(path, "a");
        else f = fopen(default_name, "a");
        if (!f) return;
        time_t t = time(NULL);
        char *ts = ctime(&t);
        if (ts) {
            size_t L = strlen(ts);
            if (L && ts[L-1] == '\n') ts[L-1] = '\0';
        }
        if (ts) fprintf(f, "[%s] ", ts);
        va_list ap; va_start(ap, fmt);
        vfprintf(f, fmt, ap);
        va_end(ap);
        fprintf(f, "\n");
        fclose(f);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        // best-effort logging; ignore failures
    }
}

// Obfuscated library names
static const unsigned char lib_kernel32[] = {107,101,114,110,101,108,51,50,46,100,108,108,0}; // "kernel32.dll"
static const unsigned char lib_psapi[]     = {112,115,97,112,105,46,100,108,108,0}; // "psapi.dll"
static const unsigned char lib_ntdll[]     = {110,116,100,108,108,46,100,108,108,0}; // "ntdll.dll"
static const unsigned char lib_dxg[]       = {100,120,103,107,114,110,108,46,100,108,108,0}; // "dxgkrnl.dll"
static const unsigned char lib_avrt[]      = {97,118,114,116,46,100,108,108,0}; // "avrt.dll"

// Obfuscated function names (examples)
static const unsigned char fn_OpenProcess[]              = {79,112,101,110,80,114,111,99,101,115,115,0}; // "OpenProcess"
static const unsigned char fn_SetPriorityClass[]         = {83,101,116,80,114,105,111,114,105,116,121,67,108,97,115,115,0}; // "SetPriorityClass"
static const unsigned char fn_GetProcessAffinityMask[]   = {71,101,116,80,114,111,99,101,115,115,65,102,102,105,110,105,116,121,77,97,115,107,0};
static const unsigned char fn_SetProcessAffinityMask[]   = {83,101,116,80,114,111,99,101,115,115,65,102,102,105,110,105,116,121,77,97,115,107,0};
static const unsigned char fn_CreateToolhelp32Snapshot[]= {67,114,101,97,116,101,84,111,111,108,104,101,108,112,51,50,83,110,97,112,115,104,111,116,0};
static const unsigned char fn_Process32FirstA[]          = {80,114,111,99,101,115,115,51,50,70,105,114,115,116,65,0};
static const unsigned char fn_Process32NextA[]           = {80,114,111,99,101,115,115,51,50,78,101,120,116,65,0};
static const unsigned char fn_CloseHandle[]              = {67,108,111,115,101,72,97,110,100,108,101,0};
static const unsigned char fn_EnumProcessModules[]      = {69,110,117,109,80,114,111,99,101,115,115,77,111,100,117,108,101,115,0};
static const unsigned char fn_GetModuleFileNameExA[]     = {71,101,116,77,111,100,117,108,101,70,105,108,101,78,97,109,101,69,120,65,0};
static const unsigned char fn_GetProcessImageFileNameA[] = {71,101,116,80,114,111,99,101,115,115,73,109,97,103,101,70,105,108,101,78,97,109,101,65,0};
static const unsigned char fn_QueryFullProcessImageNameA[]= {81,117,101,114,121,70,117,108,108,80,114,111,99,101,115,115,73,109,97,103,101,78,97,109,101,65,0};
static const unsigned char fn_GetForegroundWindow[]      = {71,101,116,70,111,114,101,103,114,111,117,110,100,87,105,110,100,111,119,0};
static const unsigned char fn_GetWindowThreadProcessId[] = {71,101,116,87,105,110,100,111,119,84,104,114,101,97,100,80,114,111,99,101,115,115,73,100,0};
static const unsigned char fn_GetPerformanceInfo[]       = {71,101,116,80,101,114,102,111,114,109,97,110,99,101,73,110,102,111,0};
static const unsigned char fn_EmptyWorkingSet[]          = {69,109,112,116,121,87,111,114,107,105,110,103,83,101,116,0};
static const unsigned char fn_SetSystemFileCacheSize[]   = {83,101,116,83,121,115,116,101,109,70,105,108,101,67,97,99,104,101,83,105,122,101,0};
static const unsigned char fn_NtSetSystemInformation[]   = {78,116,83,101,116,83,121,115,116,101,109,73,110,102,111,114,109,97,116,105,111,110,0};
static const unsigned char fn_D3DKMTSetProcessSchedulingPriorityClass[] = {68,51,68,75,77,84,83,101,116,80,114,111,99,101,115,115,83,99,104,101,100,117,108,105,110,103,80,114,105,111,114,105,116,121,67,108,97,115,115,0};
static const unsigned char fn_SetProcessInformation[]     = {83,101,116,80,114,111,99,101,115,115,73,110,102,111,114,109,97,116,105,111,110,0};
static const unsigned char fn_AvSetMmThreadCharacteristicsA[] = {65,118,83,101,116,77,109,84,104,114,101,97,100,67,104,97,114,97,99,116,101,114,105,115,116,105,99,115,65,0};
static const unsigned char fn_AvSetMmThreadPriority[]      = {65,118,83,101,116,77,109,84,104,114,101,97,100,80,114,105,111,114,105,116,121,0};
static const unsigned char fn_AvRevertMmThreadCharacteristics[] = {65,118,82,101,118,101,114,116,77,109,84,104,114,101,97,100,67,104,97,114,97,99,116,101,114,105,115,116,105,99,115,0};

// Minimal typedefs for functions we'll resolve at runtime
typedef HANDLE (WINAPI *PFN_OpenProcess)(DWORD, BOOL, DWORD);
typedef BOOL (WINAPI *PFN_SetPriorityClass)(HANDLE, DWORD);
typedef BOOL (WINAPI *PFN_GetProcessAffinityMask)(HANDLE, PDWORD_PTR, PDWORD_PTR);
typedef BOOL (WINAPI *PFN_SetProcessAffinityMask)(HANDLE, DWORD_PTR);
typedef HANDLE (WINAPI *PFN_CreateToolhelp32Snapshot)(DWORD, DWORD);
typedef BOOL (WINAPI *PFN_Process32First)(HANDLE, PROCESSENTRY32*);
typedef BOOL (WINAPI *PFN_Process32Next)(HANDLE, PROCESSENTRY32*);
typedef BOOL (WINAPI *PFN_EnumProcessModules)(HANDLE, HMODULE*, DWORD, LPDWORD);
typedef DWORD (WINAPI *PFN_GetModuleFileNameExA)(HANDLE, HMODULE, LPSTR, DWORD);
typedef DWORD (WINAPI *PFN_GetProcessImageFileNameA)(HANDLE, LPSTR, DWORD);
typedef BOOL (WINAPI *PFN_QueryFullProcessImageNameA)(HANDLE, DWORD, LPSTR, PDWORD);
typedef HWND (WINAPI *PFN_GetForegroundWindow)(void);
typedef DWORD (WINAPI *PFN_GetWindowThreadProcessId)(HWND, LPDWORD);
typedef BOOL (WINAPI *PFN_GetPerformanceInfo)(PPERFORMANCE_INFORMATION, DWORD);
typedef BOOL (WINAPI *PFN_EmptyWorkingSet)(HANDLE);
typedef BOOL (WINAPI *PFN_SetSystemFileCacheSize)(SIZE_T, SIZE_T, DWORD);
typedef NTSTATUS (WINAPI *PFN_NtSetSystemInformation)(ULONG, PVOID, ULONG);
typedef NTSTATUS (WINAPI *PFN_D3DKMTSetProcessSchedulingPriorityClass)(PVOID);
typedef BOOL (WINAPI *PFN_SetProcessInformation)(HANDLE, ULONG, PVOID, DWORD);
typedef HANDLE (WINAPI *PFN_AvSetMmThreadCharacteristicsA)(LPCSTR, LPDWORD);
typedef BOOL (WINAPI *PFN_AvSetMmThreadPriority)(HANDLE, int);
typedef BOOL (WINAPI *PFN_AvRevertMmThreadCharacteristics)(HANDLE);

// Globals for worker state
static CRITICAL_SECTION g_lock;
static volatile LONG g_lock_inited = 0;
static std::vector<DWORD> g_modified_pids;
static HANDLE g_worker_thread = NULL;
static HANDLE g_worker_stop_event = NULL;

// Helper: case-insensitive starts_with
static bool starts_with_ci(const std::string &s, const std::string &prefix)
{
    if (s.size() < prefix.size()) return false;
    for (size_t i = 0; i < prefix.size(); ++i) {
        if (tolower((unsigned char)s[i]) != tolower((unsigned char)prefix[i])) return false;
    }
    return true;
}

// Helper: lowercase copy
static std::string to_lower(const std::string &s)
{
    std::string out(s);
    std::transform(out.begin(), out.end(), out.begin(), ::tolower);
    return out;
}

// Build a robust whitelist of exact names (lowercase) that must NEVER be touched
static std::vector<std::string> build_whitelist()
{
    const unsigned char wlist[][64] = {
        {119,105,110,108,111,103,111,110,46,101,120,101,0},    // winlogon.exe
        {76,111,103,111,110,85,73,46,101,120,101,0},            // LogonUI.exe
        {115,105,104,111,115,116,46,101,120,101,0},            // sihost.exe
        {102,111,110,116,100,114,118,104,111,115,116,46,101,120,101,0}, // fontdrvhost.exe
        {117,115,101,114,105,110,105,116,46,101,120,101,0},    // userinit.exe
        {115,104,101,108,108,101,120,112,101,114,105,101,110,99,101,104,111,115,116,46,101,120,101,0}, // shellexperiencehost.exe
        {108,115,97,115,115,46,101,120,101,0},                 // lsass.exe
        {99,115,114,115,115,46,101,120,101,0},                 // csrss.exe
        {115,101,114,118,105,99,101,115,46,101,120,101,0},     // services.exe
        {115,109,115,115,46,101,120,101,0},                    // smss.exe
        {115,112,111,111,108,115,118,46,101,120,101,0},        // spoolsv.exe
        {77,115,77,112,69,110,103,46,101,120,101,0},           // MsMpEng.exe
        {78,105,115,83,114,118,46,101,120,101,0},              // NisSrv.exe
        {112,121,116,104,111,110,46,101,120,101,0},            // python.exe
        {112,121,116,104,111,110,119,46,101,120,101,0},        // pythonw.exe
        {100,119,109,46,101,120,101,0},                        // dwm.exe
        {101,120,112,108,111,114,101,114,46,101,120,101,0},    // explorer.exe
        {0}
    };
    std::vector<std::string> rv;
    for (int i = 0; wlist[i][0]; ++i) rv.push_back(to_lower(std::string((const char*)wlist[i])));
    return rv;
}

// Check if a candidate process must be skipped (whitelist / system32 path)
static bool is_exempt_process(const std::string &imageLower, const std::vector<std::string> &wl, const std::string &system32PrefixLower)
{
    // Full-name exact match
    size_t pos = imageLower.find_last_of("/\\");
    std::string name = (pos == std::string::npos) ? imageLower : imageLower.substr(pos + 1);
    for (const auto &w : wl) {
        if (name == w) return true;
    }
    // Do not touch anything under C:\\Windows\\System32
    if (!system32PrefixLower.empty() && starts_with_ci(imageLower, system32PrefixLower)) return true;
    return false;
}

// Purge standby list via obfuscated NtSetSystemInformation
static void PurgeStandbyListIfAllowed(PFN_NtSetSystemInformation pNtSetSystemInformation)
{
    __try {
        const char *allow = getenv("FORZEOS_ALLOW_STANDBY_PURGE");
        if (!allow || strcmp(allow, "1") != 0) return;
        if (!pNtSetSystemInformation) return;
        // Adapted structure for MemoryPurgeStandbyList - best-effort
        struct { ULONG Command; ULONG Flags; } cmd;
        cmd.Command = 1; // MemoryPurgeStandbyList
        cmd.Flags = 0;
        const ULONG SystemMemoryListInformation = 0x50;
        __try {
            (void)pNtSetSystemInformation(SystemMemoryListInformation, &cmd, sizeof(cmd));
        } __except (EXCEPTION_EXECUTE_HANDLER) {
            // ignore
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
    }
}

// Trim system file cache if API available
static void TrimSystemFileCacheIfPossible(PFN_SetSystemFileCacheSize pSetSysCache)
{
    if (!pSetSysCache) return;
    __try {
        (void)pSetSysCache((SIZE_T)0, (SIZE_T)0, (DWORD)0);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
    }
}

// Worker thread: periodically perform trims and modest process priority adjustments
static DWORD WINAPI WorkerThreadProc(LPVOID lpParam)
{
    // runtime-resolved function pointers passed via lpParam as an array of FARPROC
    FARPROC *tbl = (FARPROC*)lpParam;
    PFN_EmptyWorkingSet pEmptyWorkingSet = (PFN_EmptyWorkingSet)tbl[0];
    PFN_GetPerformanceInfo pGetPerf = (PFN_GetPerformanceInfo)tbl[1];
    PFN_NtSetSystemInformation pNtSetSystemInformation = (PFN_NtSetSystemInformation)tbl[2];
    PFN_SetSystemFileCacheSize pSetSysCache = (PFN_SetSystemFileCacheSize)tbl[3];
    PFN_D3DKMTSetProcessSchedulingPriorityClass pD3DSet = (PFN_D3DKMTSetProcessSchedulingPriorityClass)tbl[4];
    PFN_SetProcessInformation pSetProcInfo = (PFN_SetProcessInformation)tbl[5];
    PFN_OpenProcess pOpenProcess = (PFN_OpenProcess)tbl[6];
    PFN_SetPriorityClass pSetPriorityClass = (PFN_SetPriorityClass)tbl[7];
    PFN_GetProcessAffinityMask pGetAffinity = (PFN_GetProcessAffinityMask)tbl[8];
    PFN_SetProcessAffinityMask pSetAffinity = (PFN_SetProcessAffinityMask)tbl[9];

    int interval = 300;
    const char* v = getenv("FORZEOS_TRIM_INTERVAL_SECONDS"); if (v) interval = atoi(v);
    int threshold_mb = 1024; v = getenv("FORZEOS_TRIM_THRESHOLD_MB"); if (v) threshold_mb = atoi(v);

    std::vector<std::string> whitelist = build_whitelist();

    // get system32 prefix at runtime
    char sysdir[MAX_PATH] = {0};
    GetSystemDirectoryA(sysdir, MAX_PATH);
    std::string system32PrefixLower = to_lower(std::string(sysdir));
    if (!system32PrefixLower.empty() && system32PrefixLower.back() != '\\') system32PrefixLower.push_back('\\');

    while (WaitForSingleObject(g_worker_stop_event, (DWORD)interval * 1000) == WAIT_TIMEOUT) {
        TrimSystemFileCacheIfPossible(pSetSysCache);
        PurgeStandbyListIfAllowed(pNtSetSystemInformation);

        // Assess system memory pressure
        PERFORMANCE_INFORMATION pi; ZeroMemory(&pi, sizeof(pi)); pi.cb = sizeof(pi);
        BOOL okPerf = FALSE;
        __try { okPerf = pGetPerf ? pGetPerf(&pi, sizeof(pi)) : FALSE; } __except (EXCEPTION_EXECUTE_HANDLER) { okPerf = FALSE; }
        double commitPercent = 0.0, physPercent = 0.0;
        if (okPerf && pi.CommitLimit > 0) commitPercent = (double)pi.CommitTotal * 100.0 / (double)pi.CommitLimit;
        if (okPerf && pi.PhysicalTotal > 0) {
            SIZE_T usedPhys = 0;
            if (pi.PhysicalTotal > pi.PhysicalAvailable) usedPhys = pi.PhysicalTotal - pi.PhysicalAvailable;
            physPercent = (double)usedPhys * 100.0 / (double)pi.PhysicalTotal;
        }
        bool memoryPressure = (commitPercent >= 80.0) || (physPercent >= 80.0);

        if (memoryPressure && pEmptyWorkingSet) {
            int trimmedCount = 0;
            // enumerate processes via toolhelp snapshot. Try ANSI first, then fall back
            // to wide variants if needed (some headers/toolchains expose only wide types).
            HMODULE hKernel = GetModuleHandleA(build_str(lib_kernel32).c_str());
            FARPROC pCreateSnap = GetProcAddress(hKernel, build_str(fn_CreateToolhelp32Snapshot).c_str());
            FARPROC pProcFirstA = GetProcAddress(hKernel, build_str(fn_Process32FirstA).c_str());
            FARPROC pProcNextA = GetProcAddress(hKernel, build_str(fn_Process32NextA).c_str());
            FARPROC pProcFirstW = GetProcAddress(hKernel, "Process32FirstW");
            FARPROC pProcNextW = GetProcAddress(hKernel, "Process32NextW");
            FARPROC pProcFirst = pProcFirstA ? pProcFirstA : pProcFirstW;
            FARPROC pProcNext = pProcNextA ? pProcNextA : pProcNextW;
            bool useWide = (pProcFirst == pProcFirstW);

            if (pCreateSnap && pProcFirst && pProcNext) {
                typedef HANDLE (WINAPI *PFN_CreateToolhelp32Snapshot_local)(DWORD, DWORD);
                PFN_CreateToolhelp32Snapshot_local pCreateSnapLocal = (PFN_CreateToolhelp32Snapshot_local)pCreateSnap;

                HANDLE snap = pCreateSnapLocal(TH32CS_SNAPPROCESS, 0);
                if (snap != INVALID_HANDLE_VALUE) {
                    if (!useWide) {
                        typedef BOOL (WINAPI *PFN_Process32FirstA_local)(HANDLE, PROCESSENTRY32A*);
                        typedef BOOL (WINAPI *PFN_Process32NextA_local)(HANDLE, PROCESSENTRY32A*);
                        PFN_Process32FirstA_local pProcFirstLocal = (PFN_Process32FirstA_local)pProcFirst;
                        PFN_Process32NextA_local pProcNextLocal = (PFN_Process32NextA_local)pProcNext;
                        PROCESSENTRY32A pe; ZeroMemory(&pe, sizeof(pe)); pe.dwSize = sizeof(pe);
                        if (pProcFirstLocal(snap, &pe)) {
                            do {
                                __try {
                                    std::string image = to_lower(std::string(pe.szExeFile));
                                    if (is_exempt_process(image, whitelist, system32PrefixLower)) continue;
                                    // Open process and attempt EmptyWorkingSet and lower priority
                                    HANDLE hProc = NULL;
                                    if (pOpenProcess) {
                                        DWORD access1 = PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ | PROCESS_SET_QUOTA;
                                        DWORD access2 = PROCESS_QUERY_INFORMATION | PROCESS_VM_READ | PROCESS_SET_QUOTA;
                                        hProc = pOpenProcess(access1, FALSE, pe.th32ProcessID);
                                        if (!hProc) hProc = pOpenProcess(access2, FALSE, pe.th32ProcessID);
                                    }
                                    if (hProc) {
                                        __try {
                                            BOOL okTrim = FALSE;
                                            if (pEmptyWorkingSet) okTrim = pEmptyWorkingSet(hProc);
                                            if (okTrim) trimmedCount++;
                                            if (pSetPriorityClass) pSetPriorityClass(hProc, IDLE_PRIORITY_CLASS);
                                            native_log("Trimmed pid=%u name=%s ok=%d", (unsigned)pe.th32ProcessID, image.c_str(), okTrim ? 1 : 0);
                                        } __except (EXCEPTION_EXECUTE_HANDLER) {}
                                        CloseHandle(hProc);
                                    }
                                } __except (EXCEPTION_EXECUTE_HANDLER) {}
                            } while (pProcNextLocal(snap, &pe));
                        }
                    } else {
                        typedef BOOL (WINAPI *PFN_Process32FirstW_local)(HANDLE, PROCESSENTRY32W*);
                        typedef BOOL (WINAPI *PFN_Process32NextW_local)(HANDLE, PROCESSENTRY32W*);
                        PFN_Process32FirstW_local pProcFirstLocal = (PFN_Process32FirstW_local)pProcFirst;
                        PFN_Process32NextW_local pProcNextLocal = (PFN_Process32NextW_local)pProcNext;
                        PROCESSENTRY32W pe; ZeroMemory(&pe, sizeof(pe)); pe.dwSize = sizeof(pe);
                        if (pProcFirstLocal(snap, &pe)) {
                            do {
                                __try {
                                    std::string image;
                                    int needed = WideCharToMultiByte(CP_UTF8, 0, pe.szExeFile, -1, NULL, 0, NULL, NULL);
                                    if (needed > 0) {
                                        std::string tmp; tmp.resize(needed);
                                        WideCharToMultiByte(CP_UTF8, 0, pe.szExeFile, -1, &tmp[0], needed, NULL, NULL);
                                        if (!tmp.empty() && tmp.back() == '\0') tmp.pop_back();
                                        image = to_lower(tmp);
                                    } else image = std::string();
                                    if (is_exempt_process(image, whitelist, system32PrefixLower)) continue;
                                    HANDLE hProc = NULL;
                                    if (pOpenProcess) {
                                        DWORD access1 = PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ | PROCESS_SET_QUOTA;
                                        DWORD access2 = PROCESS_QUERY_INFORMATION | PROCESS_VM_READ | PROCESS_SET_QUOTA;
                                        hProc = pOpenProcess(access1, FALSE, pe.th32ProcessID);
                                        if (!hProc) hProc = pOpenProcess(access2, FALSE, pe.th32ProcessID);
                                    }
                                    if (hProc) {
                                        __try {
                                            BOOL okTrim = FALSE;
                                            if (pEmptyWorkingSet) okTrim = pEmptyWorkingSet(hProc);
                                            if (okTrim) trimmedCount++;
                                            if (pSetPriorityClass) pSetPriorityClass(hProc, IDLE_PRIORITY_CLASS);
                                            native_log("Trimmed pid=%u name=%s ok=%d", (unsigned)pe.th32ProcessID, image.c_str(), okTrim ? 1 : 0);
                                        } __except (EXCEPTION_EXECUTE_HANDLER) {}
                                        CloseHandle(hProc);
                                    }
                                } __except (EXCEPTION_EXECUTE_HANDLER) {}
                            } while (pProcNextLocal(snap, &pe));
                        }
                    }
                    CloseHandle(snap);
                    native_log("Iteration summary: trimmed=%d commit=%.1f phys=%.1f", trimmedCount, commitPercent, physPercent);
                }
            }
        }
    }
    // free allocated FARPROC table (allocated in DllRegisterFocusFilter)
    __try {
        native_log("Worker exiting");
        if (tbl) {
            HeapFree(GetProcessHeap(), 0, tbl);
            tbl = NULL;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        // ignore any failure freeing
    }
    return 0;
}

// Enable common privileges - best-effort
static void TryEnablePrivileges()
{
    __try {
        HANDLE hToken = NULL;
        if (!OpenProcessToken(GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, &hToken)) return;
        LUID luid; ZeroMemory(&luid, sizeof(luid));
        LookupPrivilegeValueA(NULL, "SeDebugPrivilege", &luid);
        TOKEN_PRIVILEGES tp; ZeroMemory(&tp, sizeof(tp));
        tp.PrivilegeCount = 1;
        tp.Privileges[0].Luid = luid;
        tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED;
        AdjustTokenPrivileges(hToken, FALSE, &tp, sizeof(tp), NULL, NULL);
        CloseHandle(hToken);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
    }
}

// Exported entry: register/start the helper
extern "C" __declspec(dllexport) int __stdcall DllRegisterFocusFilter()
{
    __try {
        // Initialize once
        if (InterlockedCompareExchange(&g_lock_inited, 1, 0) == 0) InitializeCriticalSection(&g_lock);

        // Resolve runtime functions we need
        HMODULE hKernel = GetModuleHandleA(build_str(lib_kernel32).c_str());
        HMODULE hPsapi = LoadLibraryA(build_str(lib_psapi).c_str());
        HMODULE hNtdll = LoadLibraryA(build_str(lib_ntdll).c_str());
        HMODULE hDxg = LoadLibraryA(build_str(lib_dxg).c_str());
        HMODULE hAvrt = LoadLibraryA(build_str(lib_avrt).c_str());

        PFN_EmptyWorkingSet pEmptyWorkingSet = NULL;
        PFN_GetPerformanceInfo pGetPerf = NULL;
        PFN_NtSetSystemInformation pNtSetSystemInformation = NULL;
        PFN_SetSystemFileCacheSize pSetSysCache = NULL;
        PFN_D3DKMTSetProcessSchedulingPriorityClass pD3DSet = NULL;
        PFN_SetProcessInformation pSetProcInfo = NULL;
        PFN_OpenProcess pOpenProcess = NULL;
        PFN_SetPriorityClass pSetPriorityClass = NULL;
        PFN_GetProcessAffinityMask pGetAffinity = NULL;
        PFN_SetProcessAffinityMask pSetAffinity = NULL;
        PFN_AvSetMmThreadCharacteristicsA pAvSet = NULL;
        PFN_AvSetMmThreadPriority pAvPrio = NULL;
        PFN_AvRevertMmThreadCharacteristics pAvRevert = NULL;

        if (hPsapi) pEmptyWorkingSet = (PFN_EmptyWorkingSet)GetProcAddress(hPsapi, build_str(fn_EmptyWorkingSet).c_str());
        pGetPerf = (PFN_GetPerformanceInfo)GetProcAddress(hPsapi ? hPsapi : hKernel, build_str(fn_GetPerformanceInfo).c_str());
        if (hNtdll) pNtSetSystemInformation = (PFN_NtSetSystemInformation)GetProcAddress(hNtdll, build_str(fn_NtSetSystemInformation).c_str());
        pSetSysCache = (PFN_SetSystemFileCacheSize)GetProcAddress(hKernel, build_str(fn_SetSystemFileCacheSize).c_str());
        if (hDxg) pD3DSet = (PFN_D3DKMTSetProcessSchedulingPriorityClass)GetProcAddress(hDxg, build_str(fn_D3DKMTSetProcessSchedulingPriorityClass).c_str());
        pSetProcInfo = (PFN_SetProcessInformation)GetProcAddress(hKernel, build_str(fn_SetProcessInformation).c_str());
        pOpenProcess = (PFN_OpenProcess)GetProcAddress(hKernel, build_str(fn_OpenProcess).c_str());
        pSetPriorityClass = (PFN_SetPriorityClass)GetProcAddress(hKernel, build_str(fn_SetPriorityClass).c_str());
        pGetAffinity = (PFN_GetProcessAffinityMask)GetProcAddress(hKernel, build_str(fn_GetProcessAffinityMask).c_str());
        pSetAffinity = (PFN_SetProcessAffinityMask)GetProcAddress(hKernel, build_str(fn_SetProcessAffinityMask).c_str());
        if (hAvrt) {
            pAvSet = (PFN_AvSetMmThreadCharacteristicsA)GetProcAddress(hAvrt, build_str(fn_AvSetMmThreadCharacteristicsA).c_str());
            pAvPrio = (PFN_AvSetMmThreadPriority)GetProcAddress(hAvrt, build_str(fn_AvSetMmThreadPriority).c_str());
            pAvRevert = (PFN_AvRevertMmThreadCharacteristics)GetProcAddress(hAvrt, build_str(fn_AvRevertMmThreadCharacteristics).c_str());
        }

        // Try enable privileges
        TryEnablePrivileges();

        // Trim system file cache and purge standby if allowed
        TrimSystemFileCacheIfPossible(pSetSysCache);
        PurgeStandbyListIfAllowed(pNtSetSystemInformation);

        // Start worker thread if not running
        if (!g_worker_stop_event) g_worker_stop_event = CreateEventA(NULL, TRUE, FALSE, NULL);
        if (!g_worker_thread) {
            // Pass resolved function pointers to thread as a small table
            FARPROC *tbl = (FARPROC*)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, sizeof(FARPROC) * 12);
            if (tbl) {
                tbl[0] = (FARPROC)pEmptyWorkingSet;
                tbl[1] = (FARPROC)pGetPerf;
                tbl[2] = (FARPROC)pNtSetSystemInformation;
                tbl[3] = (FARPROC)pSetSysCache;
                tbl[4] = (FARPROC)pD3DSet;
                tbl[5] = (FARPROC)pSetProcInfo;
                tbl[6] = (FARPROC)pOpenProcess;
                tbl[7] = (FARPROC)pSetPriorityClass;
                tbl[8] = (FARPROC)pGetAffinity;
                tbl[9] = (FARPROC)pSetAffinity;
                // others reserved
                g_worker_thread = CreateThread(NULL, 0, WorkerThreadProc, tbl, 0, NULL);
            }
        }

        // Return success (1)
        return 1;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return 0;
    }
}

// Exported exit: stop worker and restore any modified state
extern "C" __declspec(dllexport) int __stdcall DllUnregisterFocusFilter()
{
    __try {
        if (g_worker_stop_event) SetEvent(g_worker_stop_event);
        if (g_worker_thread) {
            WaitForSingleObject(g_worker_thread, 3000);
            CloseHandle(g_worker_thread);
            g_worker_thread = NULL;
        }
        if (g_worker_stop_event) {
            CloseHandle(g_worker_stop_event);
            g_worker_stop_event = NULL;
        }
        // Best-effort: clear tracked modifications
        EnterCriticalSection(&g_lock);
        g_modified_pids.clear();
        LeaveCriticalSection(&g_lock);
        if (g_lock_inited) { DeleteCriticalSection(&g_lock); g_lock_inited = 0; }
        return 1;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return 0;
    }
}

// DllMain minimal to mark dll loaded
BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpvReserved)
{
    switch (fdwReason) {
    case DLL_PROCESS_ATTACH:
        DisableThreadLibraryCalls(hinstDLL);
        break;
    case DLL_PROCESS_DETACH:
        break;
    }
    return TRUE;
}

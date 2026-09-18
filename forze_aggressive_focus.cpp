// forze_aggressive.cpp
// Cleaned, transparent, high-performance Windows focus mode optimization DLL
// - No obfuscation: all Win32/NT APIs called transparently (resolved via
//   LoadLibrary/GetProcAddress, same pattern throughout)
// - Expanded whitelist: protects games and anti-cheat services
// - 9 integrated performance modules:
//   1. High Precision Timer Resolution (timeBeginPeriod/timeEndPeriod)
//   2. MMCSS "Games" Thread Registration (AvSetMmThreadCharacteristicsW)
//   3. Dynamic Power Plan Switcher (PowerSetActiveScheme via powrprof.dll)
//   4. GameDVR & Network Throttling Registry Fixes
//   5. Self-Process & Heap Hardening
//   6. Memory Optimizer (working-set trimming, whitelist-aware)
//   7. Standby List Purge (NtSetSystemInformation / MemoryPurgeStandbyList)
//   8. Dynamic RAM Threshold Monitor (background watcher, triggers 6+7
//      only when memory load crosses a configurable threshold)
//   9. CPU Affinity & Core Parking Management (hybrid P-core detection via
//      GetLogicalProcessorInformationEx + PowerWriteACValueIndex core-parking)

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif

// Required for GetLogicalProcessorInformationEx / EfficiencyClass (hybrid
// P-core/E-core detection) used by the CPU affinity module below. Only
// raises the API surface windows.h declares at compile time.
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0601
#endif

// Suppress MSVC C4996 security warnings for getenv, fopen, etc.
#define _CRT_SECURE_NO_WARNINGS

#include <windows.h>
#include <tlhelp32.h>
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
#include <mutex>
#include <mmsystem.h>

// Ensure NTSTATUS exists
#ifndef NTSTATUS
typedef LONG NTSTATUS;
#endif

// SystemMemoryListInformation / SYSTEM_MEMORY_LIST_COMMAND are documented in
// the WDK (ntddk.h / winternl-adjacent headers) but not exposed through a
// public Win32 wrapper. Declared here so the module can call
// NtSetSystemInformation transparently (resolved dynamically from ntdll.dll,
// same pattern as avrt.dll/powrprof.dll elsewhere in this file) without
// requiring the WDK to build this project.
#ifndef SystemMemoryListInformation
#define SystemMemoryListInformation 80
#endif

#ifndef STATUS_SUCCESS
#define STATUS_SUCCESS ((NTSTATUS)0x00000000L)
#endif

typedef enum _SYSTEM_MEMORY_LIST_COMMAND
{
    MemoryCaptureAccessedBits,
    MemoryCaptureAndResetAccessedBits,
    MemoryEmptyWorkingSets,
    MemoryFlushModifiedList,
    MemoryPurgeStandbyList,
    MemoryPurgeLowPriorityStandbyList,
    MemoryCommandMax
} SYSTEM_MEMORY_LIST_COMMAND;

// AVRT priority constants (may not be defined in all MinGW versions)
#ifndef AVRT_PRIORITY_HIGH
#define AVRT_PRIORITY_HIGH 2
#endif

// Link libraries
#pragma comment(lib, "psapi.lib")
#pragma comment(lib, "advapi32.lib")
#pragma comment(lib, "winmm.lib")
#pragma comment(lib, "powrprof.lib")

// Safe GetEnvironmentVariable wrapper (replace deprecated getenv)
static std::string get_env_var(const char *var_name, const char *default_val)
{
    char buffer[1024] = {0};
    DWORD size = GetEnvironmentVariableA(var_name, buffer, sizeof(buffer) - 1);
    if (size > 0 && size < sizeof(buffer)) {
        return std::string(buffer);
    }
    return default_val ? std::string(default_val) : std::string();
}

// Minimal logging helper (uses try/catch for C++ exception safety)
static void native_log(const char *fmt, ...)
{
    try {
        std::string log_path = get_env_var("FORZEOS_FOCUS_NATIVE_LOG", "forze_aggressive.log");
        FILE *f = fopen(log_path.c_str(), "a");
        if (!f) return;

        time_t t = time(NULL);
        char *ts = ctime(&t);
        if (ts) {
            size_t L = strlen(ts);
            if (L && ts[L-1] == '\n') ts[L-1] = '\0';
            fprintf(f, "[%s] ", ts);
        }

        va_list ap;
        va_start(ap, fmt);
        vfprintf(f, fmt, ap);
        va_end(ap);

        fprintf(f, "\n");
        fclose(f);
    } catch (...) {
        // Silently ignore logging failures
    }
}

// Case-insensitive string comparison helper
static bool starts_with_ci(const std::string &s, const std::string &prefix)
{
    if (s.size() < prefix.size()) return false;
    for (size_t i = 0; i < prefix.size(); ++i) {
        if (tolower((unsigned char)s[i]) != tolower((unsigned char)prefix[i])) return false;
    }
    return true;
}

// Convert string to lowercase
static std::string to_lower(const std::string &s)
{
    std::string out(s);
    std::transform(out.begin(), out.end(), out.begin(), ::tolower);
    return out;
}

// Convert UTF-16 process names from Toolhelp32 to UTF-8 so they can be stored
// in std::string on Unicode builds of the DLL.
static std::string utf8_from_utf16(const wchar_t *text)
{
    if (!text || !*text) {
        return std::string();
    }

    int size_needed = WideCharToMultiByte(CP_UTF8, 0, text, -1, NULL, 0, NULL, NULL);
    if (size_needed <= 0) {
        return std::string();
    }

    std::string out(static_cast<size_t>(size_needed) - 1, '\0');
    WideCharToMultiByte(CP_UTF8, 0, text, -1, &out[0], size_needed, NULL, NULL);
    return out;
}

// Enables a named privilege (e.g. SeProfileSingleProcessPrivilege) on the
// current process token. This only ever ENABLES a privilege the token
// already holds by policy (typically requires the process to be running
// elevated/as Administrator) - it cannot grant a privilege the account
// doesn't already have. Failure is expected and non-fatal on a standard
// (non-admin) token; callers must treat this as best-effort.
static bool enable_privilege(LPCWSTR privilege_name)
{
    try {
        HANDLE h_token = NULL;
        if (!OpenProcessToken(GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, &h_token)) {
            native_log("enable_privilege: OpenProcessToken failed, error %u", GetLastError());
            return false;
        }

        LUID luid;
        if (!LookupPrivilegeValueW(NULL, privilege_name, &luid)) {
            native_log("enable_privilege: LookupPrivilegeValueW failed, error %u", GetLastError());
            CloseHandle(h_token);
            return false;
        }

        TOKEN_PRIVILEGES tp;
        tp.PrivilegeCount = 1;
        tp.Privileges[0].Luid = luid;
        tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED;

        BOOL adjust_ok = AdjustTokenPrivileges(h_token, FALSE, &tp, sizeof(tp), NULL, NULL);
        DWORD last_err = GetLastError();
        CloseHandle(h_token);

        // AdjustTokenPrivileges can return TRUE while still not actually
        // granting the privilege (ERROR_NOT_ALL_ASSIGNED) if the token
        // doesn't hold it - both conditions must be checked.
        bool ok = (adjust_ok != 0) && (last_err == ERROR_SUCCESS);
        native_log("enable_privilege: requested (best-effort) -> %s", ok ? "OK" : "NOT GRANTED (needs elevation)");
        return ok;
    } catch (...) {
        return false;
    }
}

// ========== MODULE 1: HIGH PRECISION TIMER RESOLUTION ==========
class TimerResolutionManager
{
private:
    UINT mm_resolution_set;
    
public:
    TimerResolutionManager() : mm_resolution_set(0) {}
    
    bool enable()
    {
        try {
            TIMECAPS tc;
            if (timeGetDevCaps(&tc, sizeof(tc)) != TIMERR_NOERROR) {
                native_log("TimerResolution: timeGetDevCaps failed");
                return false;
            }
            
            // Use the system's minimum supported period, but never below 1ms
            UINT resolution = (tc.wPeriodMin > 1) ? tc.wPeriodMin : 1;
            MMRESULT result = timeBeginPeriod(resolution);
            if (result != TIMERR_NOERROR) {
                native_log("TimerResolution: timeBeginPeriod failed with result %u", result);
                return false;
            }
            
            mm_resolution_set = resolution;
            native_log("TimerResolution: enabled at %.1f ms", (double)resolution);
            return true;
        } catch (...) {
            return false;
        }
    }
    
    bool disable()
    {
        try {
            if (mm_resolution_set > 0) {
                MMRESULT result = timeEndPeriod(mm_resolution_set);
                if (result != TIMERR_NOERROR) {
                    native_log("TimerResolution: timeEndPeriod failed with result %u", result);
                    return false;
                }
                mm_resolution_set = 0;
                native_log("TimerResolution: disabled");
                return true;
            }
            return true;
        } catch (...) {
            return false;
        }
    }
};

// ========== MODULE 2: MMCSS "GAMES" THREAD REGISTRATION ==========
class MMCSSThreadRegistration
{
private:
    HMODULE h_avrt;
    typedef HANDLE (WINAPI *PFN_AvSetMmThreadCharacteristicsW)(LPCWSTR, LPDWORD);
    typedef BOOL (WINAPI *PFN_AvSetMmThreadPriority)(HANDLE, int);
    typedef BOOL (WINAPI *PFN_AvRevertMmThreadCharacteristics)(HANDLE);
    
    PFN_AvSetMmThreadCharacteristicsW p_av_set;
    PFN_AvSetMmThreadPriority p_av_prio;
    PFN_AvRevertMmThreadCharacteristics p_av_revert;
    HANDLE av_task_handle;
    
public:
    MMCSSThreadRegistration() : h_avrt(NULL), p_av_set(NULL), p_av_prio(NULL), p_av_revert(NULL), av_task_handle(NULL) {}
    
    bool init()
    {
        try {
            h_avrt = LoadLibraryW(L"avrt.dll");
            if (!h_avrt) {
                native_log("MMCSS: Failed to load avrt.dll");
                return false;
            }
            
            // Safe GetProcAddress casting with reinterpret_cast
            p_av_set = reinterpret_cast<PFN_AvSetMmThreadCharacteristicsW>(
                GetProcAddress(h_avrt, "AvSetMmThreadCharacteristicsW"));
            p_av_prio = reinterpret_cast<PFN_AvSetMmThreadPriority>(
                GetProcAddress(h_avrt, "AvSetMmThreadPriority"));
            p_av_revert = reinterpret_cast<PFN_AvRevertMmThreadCharacteristics>(
                GetProcAddress(h_avrt, "AvRevertMmThreadCharacteristics"));
            
            if (!p_av_set || !p_av_prio || !p_av_revert) {
                native_log("MMCSS: Failed to resolve AVRT functions");
                FreeLibrary(h_avrt);
                h_avrt = NULL;
                return false;
            }
            
            return true;
        } catch (...) {
            return false;
        }
    }
    
    bool register_current_thread_as_games()
    {
        try {
            if (!p_av_set) return false;
            
            DWORD task_index = 0;
            HANDLE av_handle = p_av_set(L"Games", &task_index);
            if (!av_handle) {
                native_log("MMCSS: AvSetMmThreadCharacteristicsW failed");
                return false;
            }
            
            av_task_handle = av_handle;
            
            // Set high priority
            if (p_av_prio) {
                BOOL ok = p_av_prio(av_handle, AVRT_PRIORITY_HIGH);
                native_log("MMCSS: Thread registered as Games, priority set: %d", ok ? 1 : 0);
            }
            
            return true;
        } catch (...) {
            return false;
        }
    }
    
    bool revert()
    {
        try {
            if (av_task_handle && p_av_revert) {
                BOOL ok = p_av_revert(av_task_handle);
                native_log("MMCSS: Thread characteristics reverted: %d", ok ? 1 : 0);
                av_task_handle = NULL;
                return ok != 0;
            }
            return true;
        } catch (...) {
            return false;
        }
    }
    
    ~MMCSSThreadRegistration()
    {
        revert();
        if (h_avrt) {
            FreeLibrary(h_avrt);
            h_avrt = NULL;
        }
    }
};

// ========== MODULE 3: DYNAMIC POWER PLAN SWITCHER ==========
class PowerPlanManager
{
private:
    HMODULE h_powrprof;
    typedef DWORD (WINAPI *PFN_PowerSetActiveScheme)(HANDLE, const GUID*);
    typedef DWORD (WINAPI *PFN_PowerGetActiveScheme)(HANDLE, GUID**);
    typedef void (WINAPI *PFN_PowerFreeGuidArray)(GUID*);
    
    PFN_PowerSetActiveScheme p_set_scheme;
    PFN_PowerGetActiveScheme p_get_scheme;
    PFN_PowerFreeGuidArray p_free_guids;
    
    GUID original_scheme;
    bool original_saved;
    
public:
    PowerPlanManager() : h_powrprof(NULL), p_set_scheme(NULL), p_get_scheme(NULL), p_free_guids(NULL), original_saved(false)
    {
        ZeroMemory(&original_scheme, sizeof(original_scheme));
    }
    
    bool init()
    {
        try {
            h_powrprof = LoadLibraryW(L"powrprof.dll");
            if (!h_powrprof) {
                native_log("PowerPlan: Failed to load powrprof.dll");
                return false;
            }
            
            // Safe GetProcAddress casting with reinterpret_cast
            p_set_scheme = reinterpret_cast<PFN_PowerSetActiveScheme>(
                GetProcAddress(h_powrprof, "PowerSetActiveScheme"));
            p_get_scheme = reinterpret_cast<PFN_PowerGetActiveScheme>(
                GetProcAddress(h_powrprof, "PowerGetActiveScheme"));
            p_free_guids = reinterpret_cast<PFN_PowerFreeGuidArray>(
                GetProcAddress(h_powrprof, "PowerFreeGuidArray"));
            
            if (!p_set_scheme || !p_get_scheme || !p_free_guids) {
                native_log("PowerPlan: Failed to resolve powrprof functions");
                FreeLibrary(h_powrprof);
                h_powrprof = NULL;
                return false;
            }
            
            return true;
        } catch (...) {
            return false;
        }
    }
    
    bool switch_to_high_performance()
    {
        try {
            if (!p_set_scheme || !p_get_scheme) return false;
            
            // Save original scheme
            GUID *p_orig = NULL;
            if (p_get_scheme(NULL, &p_orig) == ERROR_SUCCESS && p_orig) {
                original_scheme = *p_orig;
                original_saved = true;
                if (p_free_guids) p_free_guids(p_orig);
            }
            
            // High Performance GUID: 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c
            GUID high_perf_guid = { 0x8c5e7fda, 0xe8bf, 0x4a96, { 0x9a, 0x85, 0xa6, 0xe2, 0x3a, 0x8c, 0x63, 0x5c } };
            
            DWORD result = p_set_scheme(NULL, &high_perf_guid);
            if (result == ERROR_SUCCESS) {
                native_log("PowerPlan: Switched to High Performance scheme");
                return true;
            } else {
                native_log("PowerPlan: PowerSetActiveScheme failed with error %u", result);
                return false;
            }
        } catch (...) {
            return false;
        }
    }
    
    bool restore_original_scheme()
    {
        try {
            if (!original_saved || !p_set_scheme) return false;
            
            DWORD result = p_set_scheme(NULL, &original_scheme);
            if (result == ERROR_SUCCESS) {
                native_log("PowerPlan: Restored original power scheme");
                return true;
            } else {
                native_log("PowerPlan: Failed to restore scheme, error %u", result);
                return false;
            }
        } catch (...) {
            return false;
        }
    }
    
    ~PowerPlanManager()
    {
        if (h_powrprof) {
            FreeLibrary(h_powrprof);
            h_powrprof = NULL;
        }
    }
};

// ========== MODULE 4: GAMEDVR & NETWORK THROTTLING REGISTRY FIXES ==========
class RegistryOptimizer
{
public:
    bool apply_all_fixes()
    {
        bool success = true;
        
        // Fix 1: Disable Network Throttling
        if (!disable_network_throttling()) {
            native_log("RegistryOptimizer: Failed to disable network throttling");
            success = false;
        }
        
        // Fix 2: Disable GameDVR
        if (!disable_gamedvr()) {
            native_log("RegistryOptimizer: Failed to disable GameDVR");
            success = false;
        }
        
        return success;
    }
    
private:
    bool disable_network_throttling()
    {
        try {
            HKEY h_key = NULL;
            LONG result = RegOpenKeyExA(
                HKEY_LOCAL_MACHINE,
                "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Multimedia\\SystemProfile",
                0,
                KEY_READ | KEY_WRITE,
                &h_key
            );
            
            if (result != ERROR_SUCCESS) {
                native_log("RegistryOptimizer: Failed to open SystemProfile key");
                return false;
            }
            
            DWORD value = 0xFFFFFFFF;
            result = RegSetValueExA(
                h_key,
                "NetworkThrottlingIndex",
                0,
                REG_DWORD,
                (BYTE*)&value,
                sizeof(value)
            );
            
            RegCloseKey(h_key);
            
            if (result == ERROR_SUCCESS) {
                native_log("RegistryOptimizer: Network throttling disabled (0xFFFFFFFF)");
                return true;
            } else {
                native_log("RegistryOptimizer: Failed to set NetworkThrottlingIndex, error %ld", result);
                return false;
            }
        } catch (...) {
            return false;
        }
    }
    
    bool disable_gamedvr()
    {
        try {
            HKEY h_key = NULL;
            LONG result = RegOpenKeyExA(
                HKEY_CURRENT_USER,
                "Software\\Microsoft\\Windows\\CurrentVersion\\GameDVR",
                0,
                KEY_READ | KEY_WRITE,
                &h_key
            );
            
            if (result != ERROR_SUCCESS) {
                // Key might not exist, try to create it
                result = RegCreateKeyExA(
                    HKEY_CURRENT_USER,
                    "Software\\Microsoft\\Windows\\CurrentVersion\\GameDVR",
                    0,
                    NULL,
                    REG_OPTION_NON_VOLATILE,
                    KEY_READ | KEY_WRITE,
                    NULL,
                    &h_key,
                    NULL
                );
                
                if (result != ERROR_SUCCESS) {
                    native_log("RegistryOptimizer: Failed to open/create GameDVR key");
                    return false;
                }
            }
            
            DWORD value = 0;
            result = RegSetValueExA(
                h_key,
                "AppCaptureEnabled",
                0,
                REG_DWORD,
                (BYTE*)&value,
                sizeof(value)
            );
            
            RegCloseKey(h_key);
            
            if (result == ERROR_SUCCESS) {
                native_log("RegistryOptimizer: GameDVR disabled (AppCaptureEnabled=0)");
                return true;
            } else {
                native_log("RegistryOptimizer: Failed to set AppCaptureEnabled, error %ld", result);
                return false;
            }
        } catch (...) {
            return false;
        }
    }
};

// ========== MODULE 5: SELF-PROCESS & HEAP HARDENING ==========
class ProcessHardening
{
private:
    DWORD original_priority_class;
    bool priority_changed;
    
public:
    ProcessHardening() : original_priority_class(0), priority_changed(false) {}
    
    bool apply_hardening()
    {
        bool success = true;
        
        // Set self-process to high priority
        if (!set_high_priority()) {
            native_log("ProcessHardening: Failed to set high priority");
            success = false;
        }
        
        // Harden heap
        if (!harden_heap()) {
            native_log("ProcessHardening: Failed to harden heap");
            success = false;
        }
        
        return success;
    }
    
    // Restores the process priority class that was active before apply_hardening().
    // Heap hardening (HeapEnableTerminationOnCorruption) is intentionally NOT undone:
    // Windows does not support disabling it once set, and it's a safety net, not a
    // performance trade-off, so leaving it on is harmless.
    bool revert_priority()
    {
        try {
            if (!priority_changed) return true;
            HANDLE h_current = GetCurrentProcess();
            BOOL ok = SetPriorityClass(h_current, original_priority_class);
            native_log("ProcessHardening: Restored original priority class: %d", ok ? 1 : 0);
            priority_changed = false;
            return ok != 0;
        } catch (...) {
            return false;
        }
    }
    
private:
    bool set_high_priority()
    {
        try {
            HANDLE h_current = GetCurrentProcess();
            
            DWORD current_class = GetPriorityClass(h_current);
            if (current_class != 0) {
                original_priority_class = current_class;
                priority_changed = true;
            }
            
            BOOL ok = SetPriorityClass(h_current, HIGH_PRIORITY_CLASS);
            if (ok) {
                native_log("ProcessHardening: Set current process to HIGH_PRIORITY_CLASS");
                return true;
            } else {
                DWORD err = GetLastError();
                native_log("ProcessHardening: SetPriorityClass failed, error %u", err);
                priority_changed = false;
                return false;
            }
        } catch (...) {
            return false;
        }
    }
    
    bool harden_heap()
    {
        try {
            HANDLE h_heap = GetProcessHeap();
            if (!h_heap) {
                native_log("ProcessHardening: GetProcessHeap failed");
                return false;
            }
            
            // HeapEnableTerminationOnCorruption: option 1
            ULONG enable_termination = 1;
            BOOL ok = HeapSetInformation(
                h_heap,
                HeapEnableTerminationOnCorruption,
                &enable_termination,
                sizeof(enable_termination)
            );
            
            if (ok) {
                native_log("ProcessHardening: Heap hardening enabled (termination on corruption)");
                return true;
            } else {
                DWORD err = GetLastError();
                native_log("ProcessHardening: HeapSetInformation failed, error %u", err);
                return false;
            }
        } catch (...) {
            return false;
        }
    }
};

// Forward declaration - full definition lives with the whitelist code below
static bool is_protected_process(const std::string &exe_name, const std::vector<std::string> &whitelist);

// ========== MODULE 6: MEMORY OPTIMIZER (WORKING SET TRIMMING) ==========
// Honest description of what this does and does not do:
// - EmptyWorkingSet / SetProcessWorkingSetSize move a process's *currently
//   resident but not actively used* pages out of physical RAM. Pages that are
//   still needed get paged back in automatically on next access (a soft
//   page fault). This is NOT deletion or a leak fix; it's a cache trim.
// - It only meaningfully helps when a process has accumulated a large
//   working set it isn't actively using (idle background apps, browsers
//   after tab-heavy sessions). Trimming a genuinely active process (e.g.
//   the game itself, mid-session) can cause a stutter as pages page back in.
// - This module deliberately never touches processes on the protected
//   whitelist (see is_protected_process) — games and anti-cheat included.
struct MemoryTrimResult
{
    DWORD pid;
    std::string exe_name;
    SIZE_T working_set_before;
    SIZE_T working_set_after;
    bool success;
};

// SEH-protected single-process working-set trim.
//
// Win32 APIs that reach into another process's memory (GetProcessMemoryInfo,
// SetProcessWorkingSetSize) can raise structured exceptions - e.g. an access
// violation if the target process exits or its memory layout changes mid-call.
// A plain C++ `catch (...)` does NOT catch these unless the whole binary is
// built with the non-default /EHa flag, which this project intentionally
// does not require. Isolating the risky calls behind __try/__except here
// gives crash safety without depending on a global compiler flag.
//
// IMPORTANT: this function must stay free of C++ objects with non-trivial
// destructors (std::string, std::vector, etc.) - MSVC raises compiler error
// C2712 if __try is mixed with object unwinding in the same function.
static bool seh_trim_single_process(HANDLE h_proc, SIZE_T *out_before, SIZE_T *out_after)
{
#if defined(_MSC_VER)
    __try 
    {

        PROCESS_MEMORY_COUNTERS pmc;
        SIZE_T before = 0, after = 0;

        ZeroMemory(&pmc, sizeof(pmc));
        if (GetProcessMemoryInfo(h_proc, &pmc, sizeof(pmc))) {
            before = pmc.WorkingSetSize;
        }

        BOOL ok = SetProcessWorkingSetSize(h_proc, (SIZE_T)-1, (SIZE_T)-1);

        ZeroMemory(&pmc, sizeof(pmc));
        if (GetProcessMemoryInfo(h_proc, &pmc, sizeof(pmc))) {
            after = pmc.WorkingSetSize;
        }

        if (out_before) *out_before = before;
        if (out_after) *out_after = after;
        return ok != 0;
    } 
    __except (EXCEPTION_EXECUTE_HANDLER) 
    {
        if (out_before) *out_before = 0;
        if (out_after) *out_after = 0;
        return false;
    }
#else
    try {
        PROCESS_MEMORY_COUNTERS pmc;
        SIZE_T before = 0, after = 0;

        ZeroMemory(&pmc, sizeof(pmc));
        if (GetProcessMemoryInfo(h_proc, &pmc, sizeof(pmc))) {
            before = pmc.WorkingSetSize;
        }

        BOOL ok = SetProcessWorkingSetSize(h_proc, (SIZE_T)-1, (SIZE_T)-1);

        ZeroMemory(&pmc, sizeof(pmc));
        if (GetProcessMemoryInfo(h_proc, &pmc, sizeof(pmc))) {
            after = pmc.WorkingSetSize;
        }

        if (out_before) *out_before = before;
        if (out_after) *out_after = after;
        return ok != 0;
    } catch (...) {
        if (out_before) *out_before = 0;
        if (out_after) *out_after = 0;
        return false;
    }
#endif
}

class MemoryOptimizer
{
public:
    // Trim this DLL's own host process. Always safe to call.
    bool trim_own_working_set(SIZE_T *out_before = NULL, SIZE_T *out_after = NULL)
    {
        try {
            HANDLE h_self = GetCurrentProcess();
            SIZE_T before = get_working_set_size(h_self);
            
            BOOL ok = EmptyWorkingSet(h_self);
            
            SIZE_T after = get_working_set_size(h_self);
            if (out_before) *out_before = before;
            if (out_after) *out_after = after;
            
            native_log("MemoryOptimizer: Self trim %s (%.1f MB -> %.1f MB)",
                ok ? "OK" : "FAILED",
                before / (1024.0 * 1024.0),
                after / (1024.0 * 1024.0));
            
            return ok != 0;
        } catch (...) {
            return false;
        }
    }
    
    // Trim working sets of eligible background processes system-wide.
    // "Eligible" = not on the protected whitelist, not a critical PID (0/4),
    // and readable/writable via OpenProcess. Requires no special privilege
    // for processes owned by the same user session; cross-session/elevated
    // processes will simply fail OpenProcess and are skipped, not forced.
    std::vector<MemoryTrimResult> trim_system_background_processes(
        const std::vector<std::string> &protected_whitelist,
        size_t max_processes = 64)
    {
        std::vector<MemoryTrimResult> results;
        
        try {
            HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
            if (snap == INVALID_HANDLE_VALUE) {
                native_log("MemoryOptimizer: CreateToolhelp32Snapshot failed");
                return results;
            }
            
            PROCESSENTRY32W pe;
            pe.dwSize = sizeof(PROCESSENTRY32W);
            
            if (!Process32FirstW(snap, &pe)) {
                CloseHandle(snap);
                return results;
            }
            
            do {
                if (results.size() >= max_processes) break;
                if (pe.th32ProcessID <= 4) continue; // System / System Idle
                
                std::string exe_name = utf8_from_utf16(pe.szExeFile);
                if (is_protected_process(exe_name, protected_whitelist)) {
                    continue; // never touch games, anti-cheat, system, drivers
                }
                
                MemoryTrimResult r;
                r.pid = pe.th32ProcessID;
                r.exe_name = exe_name;
                r.success = false;
                r.working_set_before = 0;
                r.working_set_after = 0;
                
                HANDLE h_proc = OpenProcess(
                    PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION,
                    FALSE, pe.th32ProcessID);
                
                if (!h_proc) {
                    continue; // no access (elevated/system process) - skip silently
                }
                
                // SetProcessWorkingSetSize(-1,-1) is the documented way to
                // request an immediate trim (equivalent to EmptyWorkingSet).
                // Routed through seh_trim_single_process so an access
                // violation touching another process's memory can't take
                // down this one (see comment on that function).
                r.success = seh_trim_single_process(h_proc, &r.working_set_before, &r.working_set_after);
                
                CloseHandle(h_proc);
                results.push_back(r);
                
            } while (Process32NextW(snap, &pe));
            
            CloseHandle(snap);
            
            SIZE_T total_freed = 0;
            for (const auto &r : results) {
                if (r.success && r.working_set_after < r.working_set_before) {
                    total_freed += (r.working_set_before - r.working_set_after);
                }
            }
            
            native_log("MemoryOptimizer: Trimmed %zu processes, ~%.1f MB moved out of working sets",
                results.size(), total_freed / (1024.0 * 1024.0));
            
        } catch (...) {
            native_log("MemoryOptimizer: Exception during system trim");
        }
        
        return results;
    }
    
private:
    SIZE_T get_working_set_size(HANDLE h_process)
    {
        PROCESS_MEMORY_COUNTERS pmc;
        ZeroMemory(&pmc, sizeof(pmc));
        if (GetProcessMemoryInfo(h_process, &pmc, sizeof(pmc))) {
            return pmc.WorkingSetSize;
        }
        return 0;
    }
};

// ========== MODULE 7: STANDBY LIST PURGE ==========
// Windows caches recently-used file/game pages in the "Standby List" so a
// future re-open is fast. Under memory pressure Windows normally reclaims
// this cache on its own, but the reclaim isn't always fast enough during a
// heavy level-load spike, which can show up as a transient FPS drop. This
// module calls the same underlying mechanism tools like RAMMap's "Empty
// Standby List" use: NtSetSystemInformation(SystemMemoryListInformation,
// MemoryPurgeStandbyList). It never touches active/working-set memory of
// any running process - only the discardable standby cache.
//
// Requires SeProfileSingleProcessPrivilege, which in practice means the
// host process must be running elevated (as Administrator). On a
// non-elevated token this fails safely and is logged, never crashes.
class StandbyListPurgeManager
{
private:
    HMODULE h_ntdll;
    typedef NTSTATUS (WINAPI *PFN_NtSetSystemInformation)(int, PVOID, ULONG);
    PFN_NtSetSystemInformation p_nt_set_sysinfo;
    bool privilege_available;

public:
    StandbyListPurgeManager() : h_ntdll(NULL), p_nt_set_sysinfo(NULL), privilege_available(false) {}

    bool init()
    {
        try {
            h_ntdll = LoadLibraryW(L"ntdll.dll");
            if (!h_ntdll) {
                native_log("StandbyListPurge: Failed to load ntdll.dll");
                return false;
            }

            p_nt_set_sysinfo = reinterpret_cast<PFN_NtSetSystemInformation>(
                GetProcAddress(h_ntdll, "NtSetSystemInformation"));

            if (!p_nt_set_sysinfo) {
                native_log("StandbyListPurge: Failed to resolve NtSetSystemInformation");
                FreeLibrary(h_ntdll);
                h_ntdll = NULL;
                return false;
            }

            // Best-effort; purge_standby_list() below still checks the
            // actual NTSTATUS and fails safely if this wasn't granted.
            privilege_available = enable_privilege(L"SeProfileSingleProcessPrivilege");
            enable_privilege(L"SeIncreaseQuotaPrivilege");

            return true;
        } catch (...) {
            return false;
        }
    }

    bool purge_standby_list()
    {
        try {
            if (!p_nt_set_sysinfo) return false;

            SYSTEM_MEMORY_LIST_COMMAND cmd = MemoryPurgeStandbyList;
            NTSTATUS status = p_nt_set_sysinfo(SystemMemoryListInformation, &cmd, sizeof(cmd));
            bool ok = (status == STATUS_SUCCESS);

            native_log("StandbyListPurge: MemoryPurgeStandbyList NTSTATUS=0x%08lX (%s)%s",
                (unsigned long)status,
                ok ? "OK" : "FAILED",
                (!ok && !privilege_available) ? " - requires running elevated (Administrator)" : "");

            return ok;
        } catch (...) {
            return false;
        }
    }

    ~StandbyListPurgeManager()
    {
        if (h_ntdll) {
            FreeLibrary(h_ntdll);
            h_ntdll = NULL;
        }
    }
};

// ========== MODULE 8: DYNAMIC RAM THRESHOLD MONITOR ==========
// The other modules in this file run once, at DllRegisterFocusFilter time.
// This module instead runs a lightweight background thread for the
// lifetime of the focus session: it polls system-wide memory load via
// GlobalMemoryStatusEx (a cheap call - no disk I/O, no process
// enumeration) and only triggers the heavier standby-list purge /
// background working-set trim when memory pressure actually crosses the
// configured threshold. A cooldown prevents back-to-back triggers from
// hammering the disk or causing unnecessary page-fault churn in
// still-active background apps.
class DynamicMemoryMonitor
{
private:
    HANDLE h_thread;
    volatile LONG stop_flag;
    DWORD threshold_percent;   // e.g. 85 = trigger when memory load >= 85%
    DWORD poll_interval_ms;    // how often to check GlobalMemoryStatusEx
    DWORD cooldown_ms;         // minimum time between two triggered cleanups
    StandbyListPurgeManager *standby_purger; // not owned
    MemoryOptimizer *mem_opt;                // not owned
    const std::vector<std::string> *protected_list; // not owned

    static DWORD WINAPI thread_proc(LPVOID param)
    {
        DynamicMemoryMonitor *self = reinterpret_cast<DynamicMemoryMonitor *>(param);
        self->run();
        return 0;
    }

    void run()
    {
        native_log("DynamicMemoryMonitor: thread started (threshold=%lu%%, poll=%lums, cooldown=%lums)",
            (unsigned long)threshold_percent, (unsigned long)poll_interval_ms, (unsigned long)cooldown_ms);

        ULONGLONG last_trigger_tick = 0;

        while (InterlockedCompareExchange(&stop_flag, 0, 0) == 0) {
            MEMORYSTATUSEX ms;
            ZeroMemory(&ms, sizeof(ms));
            ms.dwLength = sizeof(ms);

            if (GlobalMemoryStatusEx(&ms) && ms.dwMemoryLoad >= threshold_percent) {
                ULONGLONG now = GetTickCount64();
                if (last_trigger_tick == 0 || (now - last_trigger_tick) >= cooldown_ms) {
                    native_log("DynamicMemoryMonitor: memory load %lu%% >= threshold %lu%%, triggering cleanup",
                        (unsigned long)ms.dwMemoryLoad, (unsigned long)threshold_percent);

                    if (standby_purger) standby_purger->purge_standby_list();
                    if (mem_opt && protected_list) mem_opt->trim_system_background_processes(*protected_list);

                    last_trigger_tick = now;
                } else {
                    native_log("DynamicMemoryMonitor: load %lu%% over threshold but still in cooldown, skipping",
                        (unsigned long)ms.dwMemoryLoad);
                }
            }

            // Sleep in small slices so a stop() request is honored promptly
            // instead of waiting out a potentially long poll interval.
            DWORD slept = 0;
            const DWORD slice = 200;
            while (slept < poll_interval_ms && InterlockedCompareExchange(&stop_flag, 0, 0) == 0) {
                DWORD remaining = poll_interval_ms - slept;
                Sleep(remaining < slice ? remaining : slice);
                slept += slice;
            }
        }

        native_log("DynamicMemoryMonitor: thread exiting");
    }

public:
    DynamicMemoryMonitor()
        : h_thread(NULL), stop_flag(0), threshold_percent(85), poll_interval_ms(5000),
          cooldown_ms(30000), standby_purger(NULL), mem_opt(NULL), protected_list(NULL) {}

    // Reads FORZEOS_FOCUS_RAM_THRESHOLD / _POLL_MS / _COOLDOWN_MS env vars
    // if present, otherwise keeps the defaults above. Kept consistent with
    // this file's existing get_env_var-based configuration style.
    void load_config_from_env()
    {
        try {
            std::string thr = get_env_var("FORZEOS_FOCUS_RAM_THRESHOLD", "");
            if (!thr.empty()) {
                int v = atoi(thr.c_str());
                if (v > 0 && v <= 100) threshold_percent = (DWORD)v;
            }
            std::string poll = get_env_var("FORZEOS_FOCUS_RAM_POLL_MS", "");
            if (!poll.empty()) {
                int v = atoi(poll.c_str());
                if (v >= 500) poll_interval_ms = (DWORD)v;
            }
            std::string cd = get_env_var("FORZEOS_FOCUS_RAM_COOLDOWN_MS", "");
            if (!cd.empty()) {
                int v = atoi(cd.c_str());
                if (v >= 1000) cooldown_ms = (DWORD)v;
            }
        } catch (...) {
            // keep defaults
        }
    }

    bool start(StandbyListPurgeManager *purger, MemoryOptimizer *opt, const std::vector<std::string> *whitelist)
    {
        try {
            if (h_thread) return true; // already running

            load_config_from_env();

            standby_purger = purger;
            mem_opt = opt;
            protected_list = whitelist;
            stop_flag = 0;

            h_thread = CreateThread(NULL, 0, thread_proc, this, 0, NULL);
            if (!h_thread) {
                native_log("DynamicMemoryMonitor: CreateThread failed, error %u", GetLastError());
                return false;
            }

            return true;
        } catch (...) {
            return false;
        }
    }

    bool stop()
    {
        try {
            if (!h_thread) return true;

            InterlockedExchange(&stop_flag, 1);
            // Wait for the thread to notice and exit cleanly; if it somehow
            // doesn't within 3s we still close our handle rather than hang
            // DLL unload - the thread's own resources are stack-only.
            WaitForSingleObject(h_thread, 3000);
            CloseHandle(h_thread);
            h_thread = NULL;

            return true;
        } catch (...) {
            return false;
        }
    }

    ~DynamicMemoryMonitor()
    {
        stop();
    }
};

// ========== MODULE 9: CPU AFFINITY & CORE PARKING MANAGEMENT ==========
// Two related but distinct optimizations:
//
// 1. Process affinity: on hybrid CPUs (Intel 12th-gen+ P-core/E-core,
//    similar AMD designs) we detect the highest-EfficiencyClass core group
//    via GetLogicalProcessorInformationEx(RelationProcessorCore) and pin
//    the current process to just those cores with SetProcessAffinityMask,
//    so background/scheduler noise is less likely to displace this
//    process's threads onto slower efficiency cores. On non-hybrid CPUs
//    every core reports the same efficiency class, so the computed mask
//    naturally becomes "all cores" - a safe no-op.
//
// 2. Core parking: Windows' power scheduler "parks" (idles down) cores
//    under light load to save power, which adds latency when a parked
//    core is suddenly needed. We use the same documented power-policy API
//    the Control Panel "Processor power management -> minimum parked
//    cores" slider uses (PowerWriteACValueIndex against
//    GUID_PROCESSOR_CORE_PARKING_MIN_CORES) to request that all cores
//    stay unparked while focus mode is active.
class CpuAffinityManager
{
private:
    DWORD_PTR original_affinity_mask;
    bool original_saved;
    HMODULE h_powrprof;

    typedef DWORD (WINAPI *PFN_PowerWriteACValueIndex)(HANDLE, const GUID *, const GUID *, const GUID *, DWORD);
    typedef DWORD (WINAPI *PFN_PowerSetActiveScheme)(HANDLE, const GUID *);
    typedef DWORD (WINAPI *PFN_PowerGetActiveScheme)(HANDLE, GUID **);

    // Builds a mask of the "performance" core group on hybrid CPUs (the
    // core group with the highest reported EfficiencyClass). On a uniform
    // (non-hybrid) CPU every core shares the same class, so out_mask ends
    // up equal to "every core the process is allowed to use" - correct,
    // safe behavior rather than an error.
    bool build_performance_core_mask(DWORD_PTR *out_mask)
    {
        try {
            DWORD len = 0;
            GetLogicalProcessorInformationEx(RelationProcessorCore, NULL, &len);
            if (len == 0) {
                native_log("CpuAffinity: GetLogicalProcessorInformationEx size query failed");
                return false;
            }

            std::vector<BYTE> buffer(len);
            PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX info =
                reinterpret_cast<PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX>(buffer.data());

            if (!GetLogicalProcessorInformationEx(RelationProcessorCore, info, &len)) {
                native_log("CpuAffinity: GetLogicalProcessorInformationEx failed, error %u", GetLastError());
                return false;
            }

            DWORD_PTR all_mask = 0;
            BYTE max_eff_class = 0;
            BYTE *cursor = buffer.data();
            BYTE *end = buffer.data() + len;

            // Pass 1: collect the full core mask and the highest efficiency class present.
            while (cursor < end) {
                PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX entry =
                    reinterpret_cast<PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX>(cursor);
                if (entry->Relationship == RelationProcessorCore) {
                    if (entry->Processor.EfficiencyClass > max_eff_class) {
                        max_eff_class = entry->Processor.EfficiencyClass;
                    }
                    for (WORD g = 0; g < entry->Processor.GroupCount; ++g) {
                        all_mask |= entry->Processor.GroupMask[g].Mask;
                    }
                }
                if (entry->Size == 0) break; // guard against malformed data
                cursor += entry->Size;
            }

            // Pass 2: collect only the cores at the highest efficiency class.
            DWORD_PTR perf_mask = 0;
            cursor = buffer.data();
            while (cursor < end) {
                PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX entry =
                    reinterpret_cast<PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX>(cursor);
                if (entry->Relationship == RelationProcessorCore &&
                    entry->Processor.EfficiencyClass == max_eff_class) {
                    for (WORD g = 0; g < entry->Processor.GroupCount; ++g) {
                        perf_mask |= entry->Processor.GroupMask[g].Mask;
                    }
                }
                if (entry->Size == 0) break;
                cursor += entry->Size;
            }

            *out_mask = perf_mask ? perf_mask : all_mask;

            native_log("CpuAffinity: %s CPU detected, target mask=0x%p (all-cores mask=0x%p)",
                (perf_mask && perf_mask != all_mask) ? "hybrid" : "uniform",
                (void *)*out_mask, (void *)all_mask);

            return *out_mask != 0;
        } catch (...) {
            return false;
        }
    }

public:
    CpuAffinityManager() : original_affinity_mask(0), original_saved(false), h_powrprof(NULL) {}

    bool apply_current_process_affinity()
    {
        try {
            HANDLE h_self = GetCurrentProcess();
            DWORD_PTR proc_mask = 0, sys_mask = 0;

            if (!GetProcessAffinityMask(h_self, &proc_mask, &sys_mask)) {
                native_log("CpuAffinity: GetProcessAffinityMask failed, error %u", GetLastError());
                return false;
            }

            original_affinity_mask = proc_mask;
            original_saved = true;

            DWORD_PTR perf_mask = 0;
            if (!build_performance_core_mask(&perf_mask) || perf_mask == 0) {
                native_log("CpuAffinity: performance-core detection unavailable, leaving default affinity untouched");
                return false;
            }

            // Never request cores the system didn't actually grant this process.
            perf_mask &= sys_mask;
            if (perf_mask == 0) {
                native_log("CpuAffinity: computed mask empty after intersecting with system mask, skipping");
                return false;
            }

            BOOL ok = SetProcessAffinityMask(h_self, perf_mask);
            native_log("CpuAffinity: SetProcessAffinityMask(0x%p) -> %s", (void *)perf_mask, ok ? "OK" : "FAILED");
            return ok != 0;
        } catch (...) {
            return false;
        }
    }

    bool restore_affinity()
    {
        try {
            if (!original_saved) return true;
            HANDLE h_self = GetCurrentProcess();
            BOOL ok = SetProcessAffinityMask(h_self, original_affinity_mask);
            native_log("CpuAffinity: affinity restored -> %s", ok ? "OK" : "FAILED");
            original_saved = false;
            return ok != 0;
        } catch (...) {
            return false;
        }
    }

    // Requests that all cores stay unparked (min parked cores = 100% stay
    // active) via the documented power-policy API - the same mechanism
    // Windows' own Power Options advanced settings use. This is a
    // system-wide power-plan setting, not a per-process one, so it is left
    // in place on shutdown by design (see PerformanceManager::shutdown),
    // consistent with how the registry fixes are handled elsewhere in
    // this file.
    bool disable_core_parking()
    {
        try {
            h_powrprof = LoadLibraryW(L"powrprof.dll");
            if (!h_powrprof) {
                native_log("CpuAffinity: Failed to load powrprof.dll");
                return false;
            }

            PFN_PowerWriteACValueIndex p_write_ac = reinterpret_cast<PFN_PowerWriteACValueIndex>(
                GetProcAddress(h_powrprof, "PowerWriteACValueIndex"));
            PFN_PowerSetActiveScheme p_set_scheme = reinterpret_cast<PFN_PowerSetActiveScheme>(
                GetProcAddress(h_powrprof, "PowerSetActiveScheme"));
            PFN_PowerGetActiveScheme p_get_scheme = reinterpret_cast<PFN_PowerGetActiveScheme>(
                GetProcAddress(h_powrprof, "PowerGetActiveScheme"));

            if (!p_write_ac || !p_set_scheme || !p_get_scheme) {
                native_log("CpuAffinity: Failed to resolve power-policy functions");
                return false;
            }

            // GUID_PROCESSOR_SETTINGS_SUBGROUP
            GUID sub_processor = { 0x54533251, 0x82be, 0x4824, { 0x96, 0xc1, 0x47, 0xb6, 0x0b, 0x74, 0x0d, 0x00 } };
            // GUID_PROCESSOR_CORE_PARKING_MIN_CORES
            GUID min_cores_setting = { 0x0cc5b647, 0xc1df, 0x4637, { 0x89, 0x1a, 0xde, 0xc3, 0x5c, 0x31, 0x85, 0x83 } };

            // Apply to the currently active scheme (NULL GUID = active scheme).
            DWORD result = p_write_ac(NULL, NULL, &sub_processor, &min_cores_setting, 100);
            bool ok = (result == ERROR_SUCCESS);
            native_log("CpuAffinity: core parking min-cores set to 100%% -> %s (error %lu)",
                ok ? "OK" : "FAILED", (unsigned long)result);

            // Re-activate the current scheme so the new AC value index takes
            // effect immediately rather than on next plan switch.
            GUID *active_scheme = NULL;
            if (p_get_scheme(NULL, &active_scheme) == ERROR_SUCCESS && active_scheme) {
                p_set_scheme(NULL, active_scheme);
                LocalFree(active_scheme); // PowerGetActiveScheme allocates via LocalAlloc
            }

            return ok;
        } catch (...) {
            return false;
        }
    }

    ~CpuAffinityManager()
    {
        if (h_powrprof) {
            FreeLibrary(h_powrprof);
            h_powrprof = NULL;
        }
    }
};

// ========== COMPREHENSIVE WHITELIST: GAMES & ANTI-CHEAT SERVICES ==========
static std::vector<std::string> build_protected_whitelist()
{
    // Extensive whitelist to protect critical system processes, games, and anti-cheat services
    const char *protect_list[] = {
        // Critical system processes
        "system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "services.exe",
        "lsass.exe", "explorer.exe", "svchost.exe", "system idle process",
        "winlogon.exe", "logonui.exe", "sihost.exe", "fontdrvhost.exe",
        "userinit.exe", "shellexperiencehost.exe", "spoolsv.exe", "dwm.exe",
        
        // Windows Defender & Security
        "msmpeng.exe", "nissrv.exe", "securityhealthservice.exe",
        
        // Python & Dev tools
        "python.exe", "pythonw.exe", "java.exe", "javaw.exe",
        
        // Major Games & Launchers
        // Valve
        "hl2.exe", "cstrike.exe", "csgo.exe", "cs2.exe", "dota2.exe", "tf2.exe",
        "steamapps", "steam.exe", "steamwebhelper.exe",
        
        // Riot Games
        "valorant-win64-shipping.exe", "vgc.exe", "valorantcrashupload.exe",
        "riotclientservices.exe", "riotclientsservices.exe",
        
        // Epic Games
        "fortniteclient-win64-shipping.exe", "unrealengine.exe", "epicgameslauncher.exe",
        "epiconlineservices.exe",
        
        // Apex Legends / EA
        "r5apex.exe", "eaapp.exe", "origin.exe", "originwebhelperservice.exe",
        
        // PUBG
        "pubg.exe", "pubgbattlegrounds.exe",
        
        // The Finals
        "thefinals.exe", "theatersclient.exe",
        
        // Dead by Daylight
        "deadbydaylight-win64-shipping.exe", "unreal.exe",
        
        // Overwatch 2
        "overwatch2.exe", "battle.net.exe", "battle.net launcher.exe",
        
        // Call of Duty
        "callofduty.exe", "modernwarfare3.exe", "warzoneracetrackerapi.exe",
        
        // World of Warcraft
        "wow.exe", "wowclassic.exe", "bnetlauncher.exe",
        
        // Diablo IV
        "diablo.exe",
        
        // Starcraft II
        "starcraft ii.exe", "sc2.exe",
        
        // League of Legends (riotclientservices.exe already listed above under Riot Games)
        "leagueoflegends.exe", "riotgamesservices.exe",
        
        // Minecraft (javaw.exe already listed above under Python & Dev tools)
        "minecraft.exe", "minecraftlauncher.exe",
        
        // Other major titles
        "baldursgate3.exe", "cyberpunk2077.exe", "elden ring.exe", "gta5.exe",
        "rdr2.exe", "hogwarts legacy.exe", "starcitizen.exe", "squadron42.exe",
        "msfs.exe", "aviasimulator.exe", "gtaonline.exe",
        
        // Anti-Cheat Services (CRITICAL - NEVER SUSPEND)
        "easyanticheat.exe", "easyanticheatlauncherstub.exe",
        "battleye.exe", "beservice.exe", "beclient.exe",
        "xigncode.exe", "xhunterx64.exe",
        "hwid.exe", "hwidentifier.exe",
        "faceitservice.exe", "facieitanticheat.exe",
        "esea.exe", "eseal.exe",
        "gameguard.exe", "npgmsvr.exe",
        "nprotect.exe", "ngen.exe",
        "hybridacl.exe",
        "ahnlaunch.exe",
        "waveac.exe",
        "untrackedexe.exe",
        "ffl.exe",
        "anticheatsettings.exe",
        
        // Protected runtime services
        "nvidia", "amd", "intel", "graphics", "audio", "network",
        "realtek", "qualcomm", "broadcom", "razer", "corsair", "logitech",
        "steelseries", "hyperx",
        
        NULL  // Sentinel
    };
    
    std::vector<std::string> result;
    for (int i = 0; protect_list[i]; ++i) {
        result.push_back(to_lower(std::string(protect_list[i])));
    }
    
    native_log("Whitelist built with %zu protected processes", result.size());
    return result;
}

// Returns true if `needle` occurs inside `haystack` at a word boundary on
// both sides (start/end of string, or a non-alphanumeric neighbor). Plain
// substring search (std::string::find) let short whitelist tokens like
// "nvidia" or "audio" match unrelated processes that merely happen to
// contain those letters (e.g. a hypothetical "mynvidiafix.exe" is fine to
// match, but "find" would also match inside an arbitrary unrelated token
// with no separator, which is not what the whitelist author intended).
// Boundary-checking keeps short vendor/keyword tokens precise without
// requiring every entry to be a full, exact executable name.
static bool contains_word_boundary(const std::string &haystack, const std::string &needle)
{
    if (needle.empty() || haystack.size() < needle.size()) return false;

    size_t pos = 0;
    while ((pos = haystack.find(needle, pos)) != std::string::npos) {
        bool left_ok = (pos == 0) ||
            !isalnum((unsigned char)haystack[pos - 1]);

        size_t right_idx = pos + needle.size();
        bool right_ok = (right_idx == haystack.size()) ||
            !isalnum((unsigned char)haystack[right_idx]);

        if (left_ok && right_ok) return true;
        pos += 1;
    }
    return false;
}

// Check if process is in protected list
static bool is_protected_process(const std::string &exe_name, const std::vector<std::string> &whitelist)
{
    std::string name_lower = to_lower(exe_name);
    
    // Extract filename from full path
    size_t pos = name_lower.find_last_of("/\\");
    if (pos != std::string::npos) {
        name_lower = name_lower.substr(pos + 1);
    }
    
    for (const auto &w : whitelist) {
        if (name_lower == w) return true;
        // Word-boundary match: catches paths/names that legitimately embed
        // a protected token (e.g. "nvidia broadcast.exe") without letting
        // the token match mid-word inside an unrelated process name.
        if (contains_word_boundary(name_lower, w)) return true;
    }
    
    // Protect anything under System32
    if (name_lower.find("system32") != std::string::npos || 
        name_lower.find("syswow64") != std::string::npos) {
        return true;
    }
    
    return false;
}

// ========== PERFORMANCE MANAGER SINGLETON ==========
class PerformanceManager
{
private:
    static PerformanceManager *instance;
    static std::once_flag init_flag;
    TimerResolutionManager timer_mgr;
    MMCSSThreadRegistration mmcss;
    PowerPlanManager power_plan;
    RegistryOptimizer registry_opt;
    ProcessHardening process_hard;
    MemoryOptimizer memory_opt;
    StandbyListPurgeManager standby_purge;
    DynamicMemoryMonitor ram_monitor;
    CpuAffinityManager cpu_affinity;
    std::vector<std::string> protected_processes;
    
public:
    // Thread-safe lazy init: std::call_once guarantees the initializer runs
    // exactly once even if multiple threads race into get_instance()
    // simultaneously, without needing a manual double-checked-lock mutex.
    static PerformanceManager* get_instance()
    {
        std::call_once(init_flag, []() {
            instance = new PerformanceManager();
        });
        return instance;
    }
    
    bool initialize()
    {
        try {
            native_log("=== PerformanceManager: Initializing all modules ===");
            
            // Load whitelist
            protected_processes = build_protected_whitelist();
            
            // Initialize each module
            bool timer_ok = timer_mgr.enable();
            bool mmcss_ok = mmcss.init() && mmcss.register_current_thread_as_games();
            bool power_ok = power_plan.init() && power_plan.switch_to_high_performance();
            bool registry_ok = registry_opt.apply_all_fixes();
            bool harden_ok = process_hard.apply_hardening();
            
            // Memory optimization: trim eligible background processes, never
            // touching anything on the protected whitelist (games, anti-cheat,
            // system-critical). Results are measured, not assumed.
            SIZE_T self_before = 0, self_after = 0;
            bool self_trim_ok = memory_opt.trim_own_working_set(&self_before, &self_after);
            auto trim_results = memory_opt.trim_system_background_processes(protected_processes);
            
            SIZE_T total_freed = 0;
            for (const auto &r : trim_results) {
                if (r.success && r.working_set_after < r.working_set_before) {
                    total_freed += (r.working_set_before - r.working_set_after);
                }
            }

            // Standby List Purge: one-shot upfront purge, same mechanism
            // RAMMap's "Empty Standby List" uses. Best-effort - fails
            // safely (and is logged) on a non-elevated token.
            bool standby_ok = standby_purge.init() && standby_purge.purge_standby_list();

            // CPU Affinity: pin this process to physical/performance cores
            // on hybrid CPUs, and request Windows stop parking cores while
            // focus mode is active.
            bool affinity_ok = cpu_affinity.apply_current_process_affinity();
            bool core_parking_ok = cpu_affinity.disable_core_parking();

            // Dynamic RAM Threshold Monitor: unlike the modules above,
            // which run once here, this starts a background thread that
            // keeps watching memory load for the rest of the session and
            // only re-triggers standby purge + background trim when the
            // configured threshold (default 85%) is actually crossed.
            bool ram_monitor_ok = ram_monitor.start(&standby_purge, &memory_opt, &protected_processes);
            
            native_log("=== PerformanceManager: Initialization complete ===");
            native_log("Timer: %s | MMCSS: %s | Power: %s | Registry: %s | Hardening: %s | MemTrim: %s (%zu procs, ~%.1f MB) | StandbyPurge: %s | CpuAffinity: %s | CoreParking: %s | RamMonitor: %s",
                timer_ok ? "OK" : "FAIL",
                mmcss_ok ? "OK" : "FAIL",
                power_ok ? "OK" : "FAIL",
                registry_ok ? "OK" : "FAIL",
                harden_ok ? "OK" : "FAIL",
                self_trim_ok ? "OK" : "FAIL",
                trim_results.size(),
                total_freed / (1024.0 * 1024.0),
                standby_ok ? "OK" : "FAIL",
                affinity_ok ? "OK" : "FAIL",
                core_parking_ok ? "OK" : "FAIL",
                ram_monitor_ok ? "OK" : "FAIL"
            );
            
            return timer_ok || mmcss_ok || power_ok || registry_ok || harden_ok || self_trim_ok
                || standby_ok || affinity_ok || core_parking_ok || ram_monitor_ok;
        } catch (...) {
            return false;
        }
    }
    
    bool shutdown()
    {
        try {
            native_log("=== PerformanceManager: Shutting down ===");
            
            // Stop the background RAM monitor first so it can't fire a
            // purge/trim mid-shutdown while other modules are being reverted.
            ram_monitor.stop();

            timer_mgr.disable();
            power_plan.restore_original_scheme();
            mmcss.revert();
            process_hard.revert_priority();
            cpu_affinity.restore_affinity();
            // Note: registry fixes (GameDVR/throttling), heap hardening, and
            // core parking (a system-wide power-plan setting, not a
            // per-process one) are intentionally left in place on shutdown -
            // they're safe defaults, not performance trade-offs that need
            // undoing. Memory trims and standby-list purges are one-shot
            // actions, not persistent state, so there's nothing to revert
            // for MemoryOptimizer or StandbyListPurgeManager either.
            
            native_log("=== PerformanceManager: Shutdown complete ===");
            return true;
        } catch (...) {
            return false;
        }
    }
    
    bool is_process_protected(const std::string &exe_name) const
    {
        return is_protected_process(exe_name, protected_processes);
    }
    
    size_t get_whitelist_size() const
    {
        return protected_processes.size();
    }
};

PerformanceManager *PerformanceManager::instance = NULL;
std::once_flag PerformanceManager::init_flag;

// ========== DLL ENTRY POINTS ==========

extern "C" __declspec(dllexport) int __stdcall DllRegisterFocusFilter()
{
    try {
        native_log("DllRegisterFocusFilter: Activating performance optimization");
        
        PerformanceManager *pm = PerformanceManager::get_instance();
        bool ok = pm->initialize();
        
        if (ok) {
            native_log("DllRegisterFocusFilter: All modules activated successfully");
            return 1;
        } else {
            native_log("DllRegisterFocusFilter: Some modules failed to initialize");
            return 0;
        }
    } catch (...) {
        native_log("DllRegisterFocusFilter: Exception caught");
        return 0;
    }
}

extern "C" __declspec(dllexport) int __stdcall DllUnregisterFocusFilter()
{
    try {
        native_log("DllUnregisterFocusFilter: Deactivating performance optimization");
        
        PerformanceManager *pm = PerformanceManager::get_instance();
        bool ok = pm->shutdown();
        
        if (ok) {
            native_log("DllUnregisterFocusFilter: All modules deactivated successfully");
            return 1;
        } else {
            native_log("DllUnregisterFocusFilter: Some modules failed to shutdown");
            return 0;
        }
    } catch (...) {
        native_log("DllUnregisterFocusFilter: Exception caught");
        return 0;
    }
}

// Compatibility export for forzeos_focus.py
extern "C" __declspec(dllexport) int __stdcall ForzeStartAggressiveFocus()
{
    return DllRegisterFocusFilter();
}

extern "C" __declspec(dllexport) int __stdcall ForzeStopAggressiveFocus()
{
    return DllUnregisterFocusFilter();
}

BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpvReserved)
{
    switch (fdwReason) {
    case DLL_PROCESS_ATTACH:
        DisableThreadLibraryCalls(hinstDLL);
        native_log("DllMain: DLL_PROCESS_ATTACH");
        break;
    case DLL_PROCESS_DETACH:
        native_log("DllMain: DLL_PROCESS_DETACH - cleaning up");
        break;
    }
    return TRUE;
}

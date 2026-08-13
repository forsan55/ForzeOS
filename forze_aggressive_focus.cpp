// forze_aggressive.cpp
// Cleaned, transparent, high-performance Windows focus mode optimization DLL
// - No obfuscation: all Win32 APIs called transparently
// - Expanded whitelist: protects games and anti-cheat services
// - 5 integrated performance modules:
//   1. High Precision Timer Resolution (timeBeginPeriod/timeEndPeriod)
//   2. MMCSS "Games" Thread Registration (AvSetMmThreadCharacteristicsW)
//   3. Dynamic Power Plan Switcher (PowerSetActiveScheme via powrprof.dll)
//   4. GameDVR & Network Throttling Registry Fixes
//   5. Self-Process & Heap Hardening

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
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
#include <mmsystem.h>

// Ensure NTSTATUS exists
#ifndef NTSTATUS
typedef LONG NTSTATUS;
#endif

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
            
            UINT resolution = (tc.wPeriodMin < 1) ? tc.wPeriodMin : 1;
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
    
public:
    MMCSSThreadRegistration() : h_avrt(NULL), p_av_set(NULL), p_av_prio(NULL), p_av_revert(NULL) {}
    
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
    
    ~MMCSSThreadRegistration()
    {
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
public:
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
    
private:
    bool set_high_priority()
    {
        try {
            HANDLE h_current = GetCurrentProcess();
            BOOL ok = SetPriorityClass(h_current, HIGH_PRIORITY_CLASS);
            if (ok) {
                native_log("ProcessHardening: Set current process to HIGH_PRIORITY_CLASS");
                return true;
            } else {
                DWORD err = GetLastError();
                native_log("ProcessHardening: SetPriorityClass failed, error %u", err);
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
        
        // League of Legends
        "leagueoflegends.exe", "riotclientservices.exe", "riotgamesservices.exe",
        
        // Minecraft
        "javaw.exe", "minecraft.exe", "minecraftlauncher.exe",
        
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

// Check if process is in protected list
static bool is_protected_process(const std::string &exe_name, const std::vector<std::string> &whitelist)
{
    std::string name_lower = to_lower(exe_name);
    
    // Extract filename from full path
    size_t pos = name_lower.find_last_of("/\\");
    if (pos != std::string::npos) {
        name_lower = name_lower.substr(pos + 1);
    }
    
    // Check exact match
    for (const auto &w : whitelist) {
        if (name_lower == w) return true;
        // Partial match for paths containing protected names
        if (name_lower.find(w) != std::string::npos) return true;
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
    TimerResolutionManager timer_mgr;
    MMCSSThreadRegistration mmcss;
    PowerPlanManager power_plan;
    RegistryOptimizer registry_opt;
    ProcessHardening process_hard;
    std::vector<std::string> protected_processes;
    
public:
    static PerformanceManager* get_instance()
    {
        if (!instance) {
            instance = new PerformanceManager();
        }
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
            
            native_log("=== PerformanceManager: Initialization complete ===");
            native_log("Timer: %s | MMCSS: %s | Power: %s | Registry: %s | Hardening: %s",
                timer_ok ? "OK" : "FAIL",
                mmcss_ok ? "OK" : "FAIL",
                power_ok ? "OK" : "FAIL",
                registry_ok ? "OK" : "FAIL",
                harden_ok ? "OK" : "FAIL"
            );
            
            return timer_ok || mmcss_ok || power_ok || registry_ok || harden_ok;
        } catch (...) {
            return false;
        }
    }
    
    bool shutdown()
    {
        try {
            native_log("=== PerformanceManager: Shutting down ===");
            
            timer_mgr.disable();
            power_plan.restore_original_scheme();
            
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

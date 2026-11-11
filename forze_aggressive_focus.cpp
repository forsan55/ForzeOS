// forze_aggressive_focus.cpp
// ForzeOS Focus Engine - Single-File Production Windows Performance Orchestrator
// All 7 critical concurrency, RAII, Loader Lock, and state-machine bugs fixed.
// Additional fixes are marked with [EK-FIX] comments.

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif

#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00
#endif

#ifndef WINVER
#define WINVER 0x0A00
#endif

#define _CRT_SECURE_NO_WARNINGS

#include <windows.h>
#include <tlhelp32.h>
#include <psapi.h>
#include <mmsystem.h>
#include <pdh.h>
#include <pdhmsg.h>
#include <stdio.h>
#include <stdarg.h>
#include <string>
#include <vector>
#include <map>
#include <set>
#include <mutex>
#include <shared_mutex>
#include <atomic>
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <utility>
#include <cctype>   // [EK-FIX] tolower icin acik include
#include <cstring>  // [EK-FIX] memcmp icin acik include

#ifdef _MSC_VER
#pragma comment(lib, "winmm.lib")
#pragma comment(lib, "psapi.lib")
#pragma comment(lib, "advapi32.lib")
#pragma comment(lib, "powrprof.lib")
#pragma comment(lib, "pdh.lib")
#endif

namespace ForzeEngine {

// ============================================================================
// WINDOWS API SABİTLERİ VE DİNAMİK FONKSİYON İŞARETÇİLERİ
// ============================================================================
static const DWORD kPowerThrottlingVersion = 1;
static const DWORD kExecutionSpeedControl = 0x1;
static const int kProcessMemoryPriority = 0;
static const int kProcessPowerThrottling = 4;

#define SystemMemoryListInformation 80
// [EK-FIX] SDK baslik dosyalari STATUS_SUCCESS tanimlayabilir; makro yeniden tanimlama uyarisi/cakismasi onlendi
#ifndef STATUS_SUCCESS
#define STATUS_SUCCESS ((LONG)0x00000000L)
#endif

#define FORZE_MEM_PRIORITY_VERY_LOW   1
#define FORZE_MEM_PRIORITY_LOW        2
#define FORZE_MEM_PRIORITY_MEDIUM     3
#define FORZE_MEM_PRIORITY_BELOW_NORM 4
#define FORZE_MEM_PRIORITY_NORMAL     5

typedef enum {
    MemoryCaptureAccessedBits,
    MemoryCaptureAndResetAccessedBits,
    MemoryEmptyWorkingSets,
    MemoryFlushModifiedList,
    MemoryPurgeStandbyList,
    MemoryPurgeLowPriorityStandbyList
} SYSTEM_MEMORY_LIST_COMMAND;

typedef BOOL (WINAPI *PFN_GetSystemCpuSetInformation)(PVOID, ULONG, PULONG, HANDLE, ULONG);
typedef BOOL (WINAPI *PFN_GetProcessDefaultCpuSets)(HANDLE, PULONG, ULONG, PULONG);
typedef BOOL (WINAPI *PFN_SetProcessDefaultCpuSets)(HANDLE, const ULONG *, ULONG);
typedef BOOL (WINAPI *PFN_GetProcessInformation)(HANDLE, int, LPVOID, DWORD);
typedef BOOL (WINAPI *PFN_SetProcessInformation)(HANDLE, int, LPVOID, DWORD);
typedef LONG (WINAPI *PFN_NtSetSystemInformation)(int, PVOID, ULONG);
typedef DWORD (WINAPI *PFN_PowerSetActiveScheme)(HANDLE, const GUID*);
typedef DWORD (WINAPI *PFN_PowerGetActiveScheme)(HANDLE, GUID**);
typedef void (WINAPI *PFN_PowerFreeGuidArray)(GUID*);

// [EK-FIX] GetProcAddress sonucunu void* uzerinden cevirir (-Wcast-function-type uyarisini giderir)
template <typename T>
static inline T ForzeProc(FARPROC p) {
    return reinterpret_cast<T>(reinterpret_cast<void *>(p));
}

struct PowerThrottlingState {
    ULONG Version;
    ULONG ControlMask;
    ULONG StateMask;
};

struct CpuSetRecord {
    ULONG Size;
    ULONG Type;
    ULONG Id;
    USHORT Group;
    BYTE LogicalProcessorIndex;
    BYTE CoreIndex;
    BYTE LastLevelCacheIndex;
    BYTE NumaNodeIndex;
    BYTE EfficiencyClass;
    BYTE AllFlags;
    BYTE Reserved[2];
};

enum class AppliedPolicy : uint8_t {
    None = 0,
    GameOptimized = 1,
    BackgroundThrottled = 2,
    ForegroundRestored = 3
};

// ============================================================================
// TELEMETRİ YAPISI (PYTHON CTYPES ABI UYUMLU)
// ============================================================================
#pragma pack(push, 1)
struct EngineTelemetry {
    DWORD current_game_pid;
    double current_game_cpu_percent;
    double total_cpu_usage_percent;
    double background_cpu_usage_percent;

    UINT64 total_physical_ram_bytes;
    UINT64 available_physical_ram_bytes;
    UINT64 used_physical_ram_bytes;
    DWORD memory_load_percent;

    UINT64 working_set_freed_bytes;
    DWORD standby_purge_success_count;

    double gpu_engine_utilization_percent;
    UINT64 gpu_dedicated_memory_bytes;
    UINT64 gpu_shared_memory_bytes;

    double avg_loop_latency_ms;
    BOOL power_plan_active;
    BOOL timer_resolution_active;
    DWORD total_tracked_processes;
    BOOL is_gaming_mode_active;
    BOOL recovery_engine_ready;
};
#pragma pack(pop)

// ============================================================================
// PROCESS STATE (RAII MOVE-ONLY HANDLE MANAGEMENT - FIX #3)
// ============================================================================
struct ProcessState {
    DWORD pid;
    HANDLE process_handle;
    FILETIME creation_time;
    std::string exe_name;
    bool is_game;
    bool is_foreground;
    AppliedPolicy current_policy;

    // CPU Priority
    DWORD original_priority;
    bool priority_saved;
    bool priority_modified;

    // Memory Priority
    ULONG original_mem_priority;
    bool mem_priority_saved;
    bool mem_priority_modified;

    // Power Throttling (EcoQoS)
    PowerThrottlingState original_power;
    bool power_saved;
    bool power_modified;

    // CPU Sets
    std::vector<ULONG> original_cpu_sets;
    bool cpu_sets_saved;
    bool cpu_sets_modified;

    // CPU Usage Tracking
    FILETIME last_sys_kernel_time;
    FILETIME last_sys_user_time;
    FILETIME last_proc_kernel_time;
    FILETIME last_proc_user_time;
    double current_cpu_percent;

    ProcessState() noexcept
        : pid(0), process_handle(NULL), is_game(false), is_foreground(false),
          current_policy(AppliedPolicy::None),
          original_priority(NORMAL_PRIORITY_CLASS), priority_saved(false), priority_modified(false),
          original_mem_priority(FORZE_MEM_PRIORITY_NORMAL), mem_priority_saved(false), mem_priority_modified(false),
          power_saved(false), power_modified(false),
          cpu_sets_saved(false), cpu_sets_modified(false),
          current_cpu_percent(0.0) {
        ZeroMemory(&creation_time, sizeof(creation_time));
        ZeroMemory(&original_power, sizeof(original_power));
        ZeroMemory(&last_sys_kernel_time, sizeof(last_sys_kernel_time));
        ZeroMemory(&last_sys_user_time, sizeof(last_sys_user_time));
        ZeroMemory(&last_proc_kernel_time, sizeof(last_proc_kernel_time));
        ZeroMemory(&last_proc_user_time, sizeof(last_proc_user_time));
    }

    // Kopyalama kesinlikle yasaklandı (Handle çoğaltılmasını ve çift kapatmayı önler)
    ProcessState(const ProcessState &) = delete;
    ProcessState &operator=(const ProcessState &) = delete;

    // Move Constructor
    ProcessState(ProcessState &&other) noexcept
        : pid(other.pid),
          process_handle(other.process_handle),
          creation_time(other.creation_time),
          exe_name(std::move(other.exe_name)),
          is_game(other.is_game),
          is_foreground(other.is_foreground),
          current_policy(other.current_policy),
          original_priority(other.original_priority),
          priority_saved(other.priority_saved),
          priority_modified(other.priority_modified),
          original_mem_priority(other.original_mem_priority),
          mem_priority_saved(other.mem_priority_saved),
          mem_priority_modified(other.mem_priority_modified),
          original_power(other.original_power),
          power_saved(other.power_saved),
          power_modified(other.power_modified),
          original_cpu_sets(std::move(other.original_cpu_sets)),
          cpu_sets_saved(other.cpu_sets_saved),
          cpu_sets_modified(other.cpu_sets_modified),
          last_sys_kernel_time(other.last_sys_kernel_time),
          last_sys_user_time(other.last_sys_user_time),
          last_proc_kernel_time(other.last_proc_kernel_time),
          last_proc_user_time(other.last_proc_user_time),
          current_cpu_percent(other.current_cpu_percent) {
        other.process_handle = NULL;
        other.pid = 0;
    }

    // Move Assignment
    ProcessState &operator=(ProcessState &&other) noexcept {
        if (this != &other) {
            CloseHandleSafe();
            pid = other.pid;
            process_handle = other.process_handle;
            creation_time = other.creation_time;
            exe_name = std::move(other.exe_name);
            is_game = other.is_game;
            is_foreground = other.is_foreground;
            current_policy = other.current_policy;
            original_priority = other.original_priority;
            priority_saved = other.priority_saved;
            priority_modified = other.priority_modified;
            original_mem_priority = other.original_mem_priority;
            mem_priority_saved = other.mem_priority_saved;
            mem_priority_modified = other.mem_priority_modified;
            original_power = other.original_power;
            power_saved = other.power_saved;
            power_modified = other.power_modified;
            original_cpu_sets = std::move(other.original_cpu_sets);
            cpu_sets_saved = other.cpu_sets_saved;
            cpu_sets_modified = other.cpu_sets_modified;
            last_sys_kernel_time = other.last_sys_kernel_time;
            last_sys_user_time = other.last_sys_user_time;
            last_proc_kernel_time = other.last_proc_kernel_time;
            last_proc_user_time = other.last_proc_user_time;
            current_cpu_percent = other.current_cpu_percent;

            other.process_handle = NULL;
            other.pid = 0;
        }
        return *this;
    }

    void CloseHandleSafe() noexcept {
        if (process_handle && process_handle != INVALID_HANDLE_VALUE) {
            CloseHandle(process_handle);
            process_handle = NULL;
        }
    }

    ~ProcessState() noexcept {
        CloseHandleSafe();
    }
};

// ============================================================================
// 1. STATE RECOVERY ENGINE (FIX #4 & FIX #5)
// ============================================================================
class StateRecoveryEngine {
public:
    // Süreç ön plana geçtiğinde veya ayarları geri alınırken handle'ı kapatmadan tüm kısıtları kaldırır
    static void RestoreLiveState(ProcessState &state,
                                 PFN_SetProcessInformation pSetProcInfo,
                                 PFN_SetProcessDefaultCpuSets pSetCpuSets) {
        if (!state.process_handle || state.process_handle == INVALID_HANDLE_VALUE) {
            return;
        }

        // 1. CPU Önceliğini Geri Yükle
        if (state.priority_saved && state.priority_modified) {
            if (SetPriorityClass(state.process_handle, state.original_priority)) {
                state.priority_modified = false;
            }
        }

        // 2. Bellek Önceliğini Geri Yükle
        if (pSetProcInfo && state.mem_priority_saved && state.mem_priority_modified) {
            if (pSetProcInfo(state.process_handle, kProcessMemoryPriority,
                             &state.original_mem_priority, sizeof(state.original_mem_priority))) {
                state.mem_priority_modified = false;
            }
        }

        // 3. EcoQoS / Power Throttling Durumunu Geri Yükle
        if (pSetProcInfo && state.power_saved && state.power_modified) {
            if (pSetProcInfo(state.process_handle, kProcessPowerThrottling,
                             &state.original_power, sizeof(state.original_power))) {
                state.power_modified = false;
            }
        }

        // 4. CPU Sets Kısıtlamasını Geri Yükle
        if (pSetCpuSets && state.cpu_sets_saved && state.cpu_sets_modified) {
            BOOL ok = pSetCpuSets(state.process_handle,
                                  state.original_cpu_sets.empty() ? NULL : state.original_cpu_sets.data(),
                                  static_cast<ULONG>(state.original_cpu_sets.size()));
            if (ok) {
                state.cpu_sets_modified = false;
            }
        }
    }

    // Süreç listeden çıkarılırken veya motor durdurulurken hem ayarları geri yükler hem handle'ı kapatır
    static void RestoreAndClose(ProcessState &state,
                                PFN_SetProcessInformation pSetProcInfo,
                                PFN_SetProcessDefaultCpuSets pSetCpuSets) {
        RestoreLiveState(state, pSetProcInfo, pSetCpuSets);
        state.current_policy = AppliedPolicy::None;
        state.CloseHandleSafe();
    }
};

// ============================================================================
// 2. POWER MANAGER
// ============================================================================
class PowerManager {
private:
    HMODULE h_powrprof;
    PFN_PowerSetActiveScheme p_set_scheme;
    PFN_PowerGetActiveScheme p_get_scheme;
    PFN_PowerFreeGuidArray p_free_guid;

    GUID original_scheme;
    GUID applied_scheme;
    bool scheme_saved;
    std::atomic<bool> high_perf_applied;

    bool IsOnBattery() const {
        SYSTEM_POWER_STATUS sps;
        if (GetSystemPowerStatus(&sps)) {
            return (sps.ACLineStatus == 0);
        }
        return false;
    }

    bool IsGuidEqual(const GUID &a, const GUID &b) const {
        return memcmp(&a, &b, sizeof(GUID)) == 0;
    }

public:
    PowerManager() : h_powrprof(NULL), p_set_scheme(NULL), p_get_scheme(NULL),
                     p_free_guid(NULL), scheme_saved(false), high_perf_applied(false) {
        ZeroMemory(&original_scheme, sizeof(original_scheme));
        ZeroMemory(&applied_scheme, sizeof(applied_scheme));
    }

    void Initialize() {
        if (!h_powrprof) {
            h_powrprof = LoadLibraryW(L"powrprof.dll");
            if (h_powrprof) {
                p_set_scheme = ForzeProc<PFN_PowerSetActiveScheme>(GetProcAddress(h_powrprof, "PowerSetActiveScheme"));
                p_get_scheme = ForzeProc<PFN_PowerGetActiveScheme>(GetProcAddress(h_powrprof, "PowerGetActiveScheme"));
                p_free_guid = ForzeProc<PFN_PowerFreeGuidArray>(GetProcAddress(h_powrprof, "PowerFreeGuidArray"));
            }
        }
    }

    bool SetHighPerformance() {
        if (IsOnBattery() || !p_set_scheme || !p_get_scheme) {
            return false;
        }

        GUID *current = NULL;
        if (p_get_scheme(NULL, &current) == ERROR_SUCCESS && current) {
            original_scheme = *current;
            scheme_saved = true;
            if (p_free_guid) p_free_guid(current);
            else LocalFree(current);
        } else {
            return false;
        }

        // High Performance GUID: 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c
        GUID high_guid = { 0x8c5e7fda, 0xe8bf, 0x4a96, { 0x9a, 0x85, 0xa6, 0xe2, 0x3a, 0x8c, 0x63, 0x5c } };
        if (IsGuidEqual(original_scheme, high_guid)) {
            applied_scheme = high_guid;
            high_perf_applied.store(true);
            return true;
        }

        if (p_set_scheme(NULL, &high_guid) == ERROR_SUCCESS) {
            applied_scheme = high_guid;
            high_perf_applied.store(true);
            return true;
        }
        return false;
    }

    bool RestoreOriginal() {
        if (!p_set_scheme || !p_get_scheme || !scheme_saved || !high_perf_applied.load()) {
            return true;
        }

        // Kullanıcı çalışma esnasında güç planını manuel değiştirdiyse ezme
        GUID *current = NULL;
        if (p_get_scheme(NULL, &current) == ERROR_SUCCESS && current) {
            bool user_changed = !IsGuidEqual(*current, applied_scheme);
            if (p_free_guid) p_free_guid(current);
            else LocalFree(current);

            if (user_changed) {
                scheme_saved = false;
                high_perf_applied.store(false);
                return true;
            }
        }

        if (p_set_scheme(NULL, &original_scheme) == ERROR_SUCCESS) {
            scheme_saved = false;
            high_perf_applied.store(false);
            return true;
        }
        return false;
    }

    void Shutdown() {
        RestoreOriginal();
        if (h_powrprof) {
            FreeLibrary(h_powrprof);
            h_powrprof = NULL;
            // [EK-FIX] Kutuphane serbest birakildiktan sonra eski fonksiyon isaretcileri kullanilmasin (dangling pointer onlendi)
            p_set_scheme = NULL;
            p_get_scheme = NULL;
            p_free_guid = NULL;
        }
    }

    bool IsHighPerfActive() const { return high_perf_applied.load(); }
};

// ============================================================================
// 3. CPU SCHEDULER (FIX #6 & FIX #7 - STATE-AWARE IDEMPOTENT APPLICATION)
// ============================================================================
class CpuScheduler {
private:
    PFN_GetSystemCpuSetInformation p_get_cpu_sets;
    PFN_GetProcessDefaultCpuSets p_get_proc_cpu_sets;
    PFN_SetProcessDefaultCpuSets p_set_proc_cpu_sets;
    PFN_GetProcessInformation p_get_proc_info;
    PFN_SetProcessInformation p_set_proc_info;

    bool is_hybrid_architecture;
    std::vector<ULONG> performance_core_ids;
    std::vector<ULONG> efficiency_core_ids;

    FILETIME prev_sys_idle;
    FILETIME prev_sys_kernel;
    FILETIME prev_sys_user;

    uint64_t FileTimeToUint64(const FILETIME &ft) const {
        return (static_cast<uint64_t>(ft.dwHighDateTime) << 32) | ft.dwLowDateTime;
    }

public:
    CpuScheduler() : p_get_cpu_sets(NULL), p_get_proc_cpu_sets(NULL),
                     p_set_proc_cpu_sets(NULL), p_get_proc_info(NULL),
                     p_set_proc_info(NULL), is_hybrid_architecture(false) {
        ZeroMemory(&prev_sys_idle, sizeof(prev_sys_idle));
        ZeroMemory(&prev_sys_kernel, sizeof(prev_sys_kernel));
        ZeroMemory(&prev_sys_user, sizeof(prev_sys_user));
    }

    void Initialize(HMODULE kernel) {
        if (!kernel) return;
        p_get_cpu_sets = ForzeProc<PFN_GetSystemCpuSetInformation>(GetProcAddress(kernel, "GetSystemCpuSetInformation"));
        p_get_proc_cpu_sets = ForzeProc<PFN_GetProcessDefaultCpuSets>(GetProcAddress(kernel, "GetProcessDefaultCpuSets"));
        p_set_proc_cpu_sets = ForzeProc<PFN_SetProcessDefaultCpuSets>(GetProcAddress(kernel, "SetProcessDefaultCpuSets"));
        p_get_proc_info = ForzeProc<PFN_GetProcessInformation>(GetProcAddress(kernel, "GetProcessInformation"));
        p_set_proc_info = ForzeProc<PFN_SetProcessInformation>(GetProcAddress(kernel, "SetProcessInformation"));

        DetectTopologyAndCores();
        GetSystemTimes(&prev_sys_idle, &prev_sys_kernel, &prev_sys_user);
    }

    void DetectTopologyAndCores() {
        performance_core_ids.clear();
        efficiency_core_ids.clear();
        is_hybrid_architecture = false;

        if (!p_get_cpu_sets) return;

        ULONG buffer_size = 0;
        p_get_cpu_sets(NULL, 0, &buffer_size, GetCurrentProcess(), 0);
        if (buffer_size == 0) return;

        std::vector<BYTE> buffer(buffer_size);
        if (!p_get_cpu_sets(buffer.data(), buffer_size, &buffer_size, GetCurrentProcess(), 0)) {
            return;
        }

        BYTE *ptr = buffer.data();
        BYTE *limit = buffer.data() + buffer_size;

        BYTE min_eff = 0xFF;
        BYTE max_eff = 0;
        std::vector<CpuSetRecord> records;

        while (ptr + sizeof(ULONG) * 2 <= limit) {
            CpuSetRecord *rec = reinterpret_cast<CpuSetRecord *>(ptr);
            if (rec->Size < sizeof(ULONG) * 2 || ptr + rec->Size > limit) break;

            // [EK-FIX] Kayit, CpuSetRecord'dan kucukse (rec->Size < sizeof(CpuSetRecord)) kopyalama tampon sinirini asabilirdi
            if (rec->Type == 0 && rec->Size >= sizeof(CpuSetRecord)) {
                records.push_back(*rec);
                if (rec->EfficiencyClass < min_eff) min_eff = rec->EfficiencyClass;
                if (rec->EfficiencyClass > max_eff) max_eff = rec->EfficiencyClass;
            }
            ptr += rec->Size;
        }

        if (max_eff > min_eff) {
            is_hybrid_architecture = true;
            for (const auto &r : records) {
                if (r.EfficiencyClass == max_eff) performance_core_ids.push_back(r.Id);
                else efficiency_core_ids.push_back(r.Id);
            }
        } else {
            is_hybrid_architecture = false;
            for (const auto &r : records) {
                performance_core_ids.push_back(r.Id);
            }
        }
    }

    double CalculateSystemCpuUsage() {
        FILETIME idle_t, kernel_t, user_t;
        if (!GetSystemTimes(&idle_t, &kernel_t, &user_t)) return 0.0;

        uint64_t idle = FileTimeToUint64(idle_t) - FileTimeToUint64(prev_sys_idle);
        uint64_t kernel = FileTimeToUint64(kernel_t) - FileTimeToUint64(prev_sys_kernel);
        uint64_t user = FileTimeToUint64(user_t) - FileTimeToUint64(prev_sys_user);
        uint64_t total = kernel + user;

        prev_sys_idle = idle_t;
        prev_sys_kernel = kernel_t;
        prev_sys_user = user_t;

        if (total == 0) return 0.0;
        double pct = (static_cast<double>(total - idle) * 100.0) / static_cast<double>(total);
        return (std::max)(0.0, (std::min)(100.0, pct));
    }

    double CalculateProcessCpuUsage(ProcessState &state) {
        if (!state.process_handle) return 0.0;

        FILETIME ft_create, ft_exit, ft_kernel, ft_user;
        if (!GetProcessTimes(state.process_handle, &ft_create, &ft_exit, &ft_kernel, &ft_user)) {
            return 0.0;
        }

        FILETIME sys_idle, sys_kernel, sys_user;
        if (!GetSystemTimes(&sys_idle, &sys_kernel, &sys_user)) return 0.0;

        if (state.last_proc_kernel_time.dwLowDateTime == 0 && state.last_proc_kernel_time.dwHighDateTime == 0) {
            state.last_proc_kernel_time = ft_kernel;
            state.last_proc_user_time = ft_user;
            state.last_sys_kernel_time = sys_kernel;
            state.last_sys_user_time = sys_user;
            return 0.0;
        }

        uint64_t proc_diff = (FileTimeToUint64(ft_kernel) - FileTimeToUint64(state.last_proc_kernel_time)) +
                             (FileTimeToUint64(ft_user) - FileTimeToUint64(state.last_proc_user_time));
        uint64_t sys_diff = (FileTimeToUint64(sys_kernel) - FileTimeToUint64(state.last_sys_kernel_time)) +
                            (FileTimeToUint64(sys_user) - FileTimeToUint64(state.last_sys_user_time));

        state.last_proc_kernel_time = ft_kernel;
        state.last_proc_user_time = ft_user;
        state.last_sys_kernel_time = sys_kernel;
        state.last_sys_user_time = sys_user;

        if (sys_diff == 0) return 0.0;
        double usage = (static_cast<double>(proc_diff) * 100.0) / static_cast<double>(sys_diff);
        state.current_cpu_percent = (std::max)(0.0, (std::min)(100.0, usage));
        return state.current_cpu_percent;
    }

    // FIX #6: Yalnızca politika henüz uygulanmamışsa API çağrısı yapar
    void OptimizeGame(ProcessState &state) {
        if (!state.process_handle || state.current_policy == AppliedPolicy::GameOptimized) {
            return;
        }

        if (state.priority_saved) {
            if (SetPriorityClass(state.process_handle, ABOVE_NORMAL_PRIORITY_CLASS)) {
                state.priority_modified = true;
            }
        }

        if (p_set_proc_info) {
            if (state.power_saved) {
                PowerThrottlingState power = { kPowerThrottlingVersion, kExecutionSpeedControl, 0 };
                if (p_set_proc_info(state.process_handle, kProcessPowerThrottling, &power, sizeof(power))) {
                    state.power_modified = true;
                }
            }

            if (state.mem_priority_saved) {
                ULONG priority = FORZE_MEM_PRIORITY_NORMAL;
                if (p_set_proc_info(state.process_handle, kProcessMemoryPriority, &priority, sizeof(priority))) {
                    state.mem_priority_modified = true;
                }
            }
        }

        if (is_hybrid_architecture && p_set_proc_cpu_sets && state.cpu_sets_saved && !performance_core_ids.empty()) {
            if (p_set_proc_cpu_sets(state.process_handle, performance_core_ids.data(),
                                    static_cast<ULONG>(performance_core_ids.size()))) {
                state.cpu_sets_modified = true;
            }
        }

        state.current_policy = AppliedPolicy::GameOptimized;
    }

    // FIX #7: Yalnızca arka plan politikası henüz uygulanmamışsa API çağrısı yapar
    void ThrottleBackground(ProcessState &state) {
        if (!state.process_handle || state.current_policy == AppliedPolicy::BackgroundThrottled) {
            return;
        }

        if (state.priority_saved) {
            if (SetPriorityClass(state.process_handle, BELOW_NORMAL_PRIORITY_CLASS)) {
                state.priority_modified = true;
            }
        }

        if (p_set_proc_info) {
            if (state.mem_priority_saved) {
                ULONG priority = FORZE_MEM_PRIORITY_VERY_LOW;
                if (p_set_proc_info(state.process_handle, kProcessMemoryPriority, &priority, sizeof(priority))) {
                    state.mem_priority_modified = true;
                }
            }

            if (state.power_saved) {
                PowerThrottlingState power = { kPowerThrottlingVersion, kExecutionSpeedControl, kExecutionSpeedControl };
                if (p_set_proc_info(state.process_handle, kProcessPowerThrottling, &power, sizeof(power))) {
                    state.power_modified = true;
                }
            }
        }

        if (is_hybrid_architecture && p_set_proc_cpu_sets && state.cpu_sets_saved && !efficiency_core_ids.empty()) {
            if (p_set_proc_cpu_sets(state.process_handle, efficiency_core_ids.data(),
                                    static_cast<ULONG>(efficiency_core_ids.size()))) {
                state.cpu_sets_modified = true;
            }
        }

        state.current_policy = AppliedPolicy::BackgroundThrottled;
    }

    PFN_SetProcessInformation GetSetProcInfo() const { return p_set_proc_info; }
    PFN_GetProcessInformation GetGetProcInfo() const { return p_get_proc_info; }
    PFN_SetProcessDefaultCpuSets GetSetCpuSets() const { return p_set_proc_cpu_sets; }
    PFN_GetProcessDefaultCpuSets GetGetCpuSets() const { return p_get_proc_cpu_sets; }
};

// ============================================================================
// 4. MEMORY MANAGER
// ============================================================================
class MemoryManager {
private:
    PFN_NtSetSystemInformation p_nt_set_sys_info;
    std::atomic<UINT64> working_set_freed_bytes;
    std::atomic<DWORD> standby_purge_count;
    std::chrono::steady_clock::time_point last_purge_time;

    bool EnablePrivilege(LPCWSTR priv_name) {
        HANDLE token = NULL;
        if (!OpenProcessToken(GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, &token)) return false;
        LUID luid;
        if (!LookupPrivilegeValueW(NULL, priv_name, &luid)) {
            CloseHandle(token);
            return false;
        }
        TOKEN_PRIVILEGES tp = { 1, { { luid, SE_PRIVILEGE_ENABLED } } };
        BOOL ok = AdjustTokenPrivileges(token, FALSE, &tp, sizeof(tp), NULL, NULL);
        DWORD err = GetLastError();
        CloseHandle(token);
        return ok && (err == ERROR_SUCCESS);
    }

public:
    MemoryManager() : p_nt_set_sys_info(NULL), working_set_freed_bytes(0), standby_purge_count(0) {
        last_purge_time = std::chrono::steady_clock::now() - std::chrono::seconds(60);
    }

    void Initialize() {
        HMODULE ntdll = GetModuleHandleW(L"ntdll.dll");
        if (ntdll) {
            p_nt_set_sys_info = ForzeProc<PFN_NtSetSystemInformation>(GetProcAddress(ntdll, "NtSetSystemInformation"));
            EnablePrivilege(L"SeProfileSingleProcessPrivilege");
            EnablePrivilege(L"SeIncreaseQuotaPrivilege");
        }
    }

    void GetSystemMemoryMetrics(UINT64 &total_phys, UINT64 &avail_phys, UINT64 &used_phys, DWORD &load_pct) {
        MEMORYSTATUSEX ms;
        ms.dwLength = sizeof(ms);
        if (GlobalMemoryStatusEx(&ms)) {
            total_phys = ms.ullTotalPhys;
            avail_phys = ms.ullAvailPhys;
            used_phys = ms.ullTotalPhys - ms.ullAvailPhys;
            load_pct = ms.dwMemoryLoad;
        } else {
            total_phys = avail_phys = used_phys = 0;
            load_pct = 0;
        }
    }

    void OptimizeUnderPressure(std::map<DWORD, ProcessState> &processes, DWORD pressure_threshold = 85) {
        UINT64 total_p, avail_p, used_p;
        DWORD load_pct;
        GetSystemMemoryMetrics(total_p, avail_p, used_p, load_pct);

        if (load_pct < pressure_threshold) return;

        auto now = std::chrono::steady_clock::now();
        if (std::chrono::duration_cast<std::chrono::seconds>(now - last_purge_time).count() < 30) {
            return;
        }

        for (auto &kv : processes) {
            ProcessState &state = kv.second;
            if (!state.is_game && !state.is_foreground && state.process_handle) {
                PROCESS_MEMORY_COUNTERS pmc_before, pmc_after;
                ZeroMemory(&pmc_before, sizeof(pmc_before));
                ZeroMemory(&pmc_after, sizeof(pmc_after));
                pmc_before.cb = sizeof(pmc_before);
                pmc_after.cb = sizeof(pmc_after);

                if (GetProcessMemoryInfo(state.process_handle, &pmc_before, sizeof(pmc_before))) {
                    SIZE_T before = pmc_before.WorkingSetSize;
                    if (EmptyWorkingSet(state.process_handle)) {
                        if (GetProcessMemoryInfo(state.process_handle, &pmc_after, sizeof(pmc_after))) {
                            if (before > pmc_after.WorkingSetSize) {
                                working_set_freed_bytes.fetch_add(before - pmc_after.WorkingSetSize);
                            }
                        }
                    }
                }
            }
        }

        if (load_pct >= 90 && p_nt_set_sys_info) {
            SYSTEM_MEMORY_LIST_COMMAND cmd = MemoryPurgeStandbyList;
            if (p_nt_set_sys_info(SystemMemoryListInformation, &cmd, sizeof(cmd)) == STATUS_SUCCESS) {
                standby_purge_count.fetch_add(1);
            }
        }

        last_purge_time = now;
    }

    UINT64 GetFreedBytes() const { return working_set_freed_bytes.load(); }
    DWORD GetPurgeCount() const { return standby_purge_count.load(); }
};

// ============================================================================
// 5. GPU MONITOR
// [EK-FIX] "\GPU Engine(*)" joker (wildcard) sayaci PdhGetFormattedCounterValue ile okunamaz
//          (her zaman hata doner ve GPU kullanimi hep 0 cikardi). PdhGetFormattedCounterArrayW
//          ile tum instance'lar okunup motor tipine gore toplanir (Task Manager mantigi: en yuksek
//          motor tipi). Ayrica telemetride hic doldurulmayan GPU bellek alanlari icin sayaclar eklendi.
// ============================================================================
class GpuMonitor {
private:
    PDH_HQUERY query_handle;
    PDH_HCOUNTER gpu_util_counter;
    PDH_HCOUNTER gpu_ded_counter;
    PDH_HCOUNTER gpu_shared_counter;
    bool is_initialized;

    static bool ReadCounterArray(PDH_HCOUNTER counter, std::vector<BYTE> &buf, DWORD &count) {
        count = 0;
        if (!counter) return false;
        for (int attempt = 0; attempt < 2; ++attempt) {
            DWORD buf_size = 0;
            DWORD item_count = 0;
            PDH_STATUS st = PdhGetFormattedCounterArrayW(counter, PDH_FMT_DOUBLE, &buf_size, &item_count, NULL);
            if (st != static_cast<PDH_STATUS>(PDH_MORE_DATA) || buf_size == 0) return false;
            buf.assign(buf_size, 0);
            st = PdhGetFormattedCounterArrayW(counter, PDH_FMT_DOUBLE, &buf_size, &item_count,
                                              reinterpret_cast<PDH_FMT_COUNTERVALUE_ITEM_W *>(buf.data()));
            if (st == ERROR_SUCCESS) {
                count = item_count;
                return true;
            }
            if (st != static_cast<PDH_STATUS>(PDH_MORE_DATA)) return false;
        }
        return false;
    }

    static UINT64 SumCounter(PDH_HCOUNTER counter) {
        std::vector<BYTE> buf;
        DWORD count = 0;
        if (!ReadCounterArray(counter, buf, count)) return 0;
        PDH_FMT_COUNTERVALUE_ITEM_W *items = reinterpret_cast<PDH_FMT_COUNTERVALUE_ITEM_W *>(buf.data());
        double sum = 0.0;
        for (DWORD i = 0; i < count; ++i) {
            if (items[i].FmtValue.CStatus == PDH_CSTATUS_VALID_DATA ||
                items[i].FmtValue.CStatus == PDH_CSTATUS_NEW_DATA) {
                if (items[i].FmtValue.doubleValue > 0.0) sum += items[i].FmtValue.doubleValue;
            }
        }
        return static_cast<UINT64>(sum);
    }

public:
    GpuMonitor() : query_handle(NULL), gpu_util_counter(NULL), gpu_ded_counter(NULL),
                   gpu_shared_counter(NULL), is_initialized(false) {}

    void Initialize() {
        if (is_initialized) return;
        if (PdhOpenQueryW(NULL, 0, &query_handle) == ERROR_SUCCESS) {
            if (PdhAddEnglishCounterW(query_handle, L"\\GPU Engine(*)\\Utilization Percentage", 0, &gpu_util_counter) == ERROR_SUCCESS) {
                if (PdhAddEnglishCounterW(query_handle, L"\\GPU Adapter Memory(*)\\Dedicated Usage", 0, &gpu_ded_counter) != ERROR_SUCCESS) {
                    gpu_ded_counter = NULL;
                }
                if (PdhAddEnglishCounterW(query_handle, L"\\GPU Adapter Memory(*)\\Shared Usage", 0, &gpu_shared_counter) != ERROR_SUCCESS) {
                    gpu_shared_counter = NULL;
                }
                PdhCollectQueryData(query_handle);
                is_initialized = true;
            } else {
                gpu_util_counter = NULL;
                PdhCloseQuery(query_handle);
                query_handle = NULL;
            }
        }
    }

    double GetGpuUtilization() {
        if (!is_initialized || !query_handle) return 0.0;
        if (PdhCollectQueryData(query_handle) != ERROR_SUCCESS) return 0.0;

        std::vector<BYTE> buf;
        DWORD count = 0;
        if (!ReadCounterArray(gpu_util_counter, buf, count)) return 0.0;

        PDH_FMT_COUNTERVALUE_ITEM_W *items = reinterpret_cast<PDH_FMT_COUNTERVALUE_ITEM_W *>(buf.data());
        std::map<std::wstring, double> per_engine_type;
        for (DWORD i = 0; i < count; ++i) {
            if (items[i].FmtValue.CStatus != PDH_CSTATUS_VALID_DATA &&
                items[i].FmtValue.CStatus != PDH_CSTATUS_NEW_DATA) {
                continue;
            }
            if (!items[i].szName) continue;
            std::wstring name(items[i].szName);
            size_t pos = name.find(L"engtype_");
            std::wstring type = (pos == std::wstring::npos) ? std::wstring() : name.substr(pos + 8);
            per_engine_type[type] += items[i].FmtValue.doubleValue;
        }

        double best = 0.0;
        for (const auto &kv : per_engine_type) {
            if (kv.second > best) best = kv.second;
        }
        return (std::max)(0.0, (std::min)(100.0, best));
    }

    // GetGpuUtilization() ile ayni sorgu ornegini kullanir (ayri Collect gerekmez)
    void GetGpuMemory(UINT64 &dedicated_bytes, UINT64 &shared_bytes) {
        dedicated_bytes = 0;
        shared_bytes = 0;
        if (!is_initialized || !query_handle) return;
        dedicated_bytes = SumCounter(gpu_ded_counter);
        shared_bytes = SumCounter(gpu_shared_counter);
    }

    void Shutdown() {
        if (query_handle) {
            PdhCloseQuery(query_handle);
            query_handle = NULL;
        }
        gpu_util_counter = NULL;
        gpu_ded_counter = NULL;
        gpu_shared_counter = NULL;
        is_initialized = false;
    }

    ~GpuMonitor() {
        Shutdown();
    }
};

// ============================================================================
// 6. FOCUS ENGINE ORCHESTRATOR (FIX #1, #2, #4, #5)
// ============================================================================
class FocusEngine {
private:
    std::mutex lifecycle_mutex; // Start/Stop yaşam döngüsü kilidi
    mutable std::shared_mutex data_mutex; // Telemetri ve süreç listesi kilidi

    std::atomic<bool> is_running;
    std::atomic<bool> stop_requested;

    HANDLE monitor_thread;
    HANDLE stop_event;
    UINT timer_period;

    PowerManager power_mgr;
    CpuScheduler cpu_sched;
    MemoryManager mem_mgr;
    GpuMonitor gpu_mon;

    std::map<DWORD, ProcessState> tracked_processes;
    EngineTelemetry telemetry_cache;

    std::set<std::string> target_games;
    std::set<std::string> background_candidates;
    std::set<std::string> protected_processes;
    std::set<std::string> user_exclusions;

    FocusEngine() : is_running(false), stop_requested(false), monitor_thread(NULL),
                    stop_event(NULL), timer_period(0) {
        ZeroMemory(&telemetry_cache, sizeof(telemetry_cache));
        InitializeDefaultLists();
    }

    void InitializeDefaultLists() {
        target_games = {
            "cs2.exe", "csgo.exe", "hl2.exe", "dota2.exe", "tf2.exe",
            "valorant-win64-shipping.exe", "fortniteclient-win64-shipping.exe",
            "r5apex.exe", "thefinals.exe", "deadbydaylight-win64-shipping.exe",
            "gta5.exe", "cyberpunk2077.exe", "eldenring.exe", "bhoppro.exe"
        };

        background_candidates = {
            "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe",
            "vivaldi.exe", "spotify.exe", "onedrive.exe", "googledrivesync.exe",
            "adobeipcbroker.exe", "ccxprocess.exe", "epicgameslauncher.exe"
        };

        protected_processes = {
            "system", "registry", "smss.exe", "csrss.exe", "wininit.exe",
            "services.exe", "lsass.exe", "svchost.exe", "winlogon.exe",
            "dwm.exe", "explorer.exe", "audiodg.exe", "obs64.exe", "discord.exe",
            "python.exe", "pythonw.exe", "msmpeng.exe", "nissrv.exe",
            "securityhealthservice.exe", "easyanticheat.exe", "easyanticheat_eos.exe",
            "beservice.exe", "battleye.exe", "vgc.exe", "vgk.exe", "faceitservice.exe"
        };
    }

    static std::string ToLower(std::string str) {
        std::transform(str.begin(), str.end(), str.begin(),
                       [](unsigned char c) { return static_cast<char>(tolower(c)); });
        return str;
    }

    static std::string Utf8FromWide(const wchar_t *wstr) {
        if (!wstr || !*wstr) return std::string();
        int len = WideCharToMultiByte(CP_UTF8, 0, wstr, -1, NULL, 0, NULL, NULL);
        if (len <= 1) return std::string();
        std::string res(static_cast<size_t>(len), '\0');
        WideCharToMultiByte(CP_UTF8, 0, wstr, -1, &res[0], len, NULL, NULL);
        res.resize(static_cast<size_t>(len - 1));
        return res;
    }

    DWORD GetForegroundProcessIdSafe() const {
        HWND hwnd = GetForegroundWindow();
        if (!hwnd) return 0;
        DWORD pid = 0;
        GetWindowThreadProcessId(hwnd, &pid);
        return pid;
    }

    bool CaptureProcessState(DWORD pid, const std::string &exe_name, bool is_game, ProcessState &out_state) {
        // [EK-FIX] SetProcessDefaultCpuSets PROCESS_SET_LIMITED_INFORMATION hakki ister;
        //          eksikken CPU Sets atamasi/geri yuklemesi sessizce basarisiz oluyordu
        HANDLE hProc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SET_INFORMATION |
                                   PROCESS_SET_LIMITED_INFORMATION | PROCESS_SET_QUOTA, FALSE, pid);
        if (!hProc) return false;

        FILETIME ft_create, ft_exit, ft_kernel, ft_user;
        if (!GetProcessTimes(hProc, &ft_create, &ft_exit, &ft_kernel, &ft_user)) {
            CloseHandle(hProc);
            return false;
        }

        ProcessState state;
        state.pid = pid;
        state.process_handle = hProc;
        state.creation_time = ft_create;
        state.exe_name = exe_name;
        state.is_game = is_game;

        DWORD prio = GetPriorityClass(hProc);
        if (prio != 0) {
            state.original_priority = prio;
            state.priority_saved = true;
        }

        if (cpu_sched.GetGetProcInfo()) {
            if (cpu_sched.GetGetProcInfo()(hProc, kProcessMemoryPriority,
                                           &state.original_mem_priority, sizeof(state.original_mem_priority))) {
                state.mem_priority_saved = true;
            }

            state.original_power.Version = kPowerThrottlingVersion;
            if (cpu_sched.GetGetProcInfo()(hProc, kProcessPowerThrottling,
                                           &state.original_power, sizeof(state.original_power))) {
                state.power_saved = true;
            }
        }

        if (cpu_sched.GetGetCpuSets()) {
            ULONG required_count = 0;
            BOOL ok = cpu_sched.GetGetCpuSets()(hProc, NULL, 0, &required_count);
            if (ok && required_count == 0) {
                state.cpu_sets_saved = true; // Boş liste varsayılan geçerli durumdur
            } else if (required_count > 0) {
                state.original_cpu_sets.resize(required_count);
                ULONG returned = 0;
                if (cpu_sched.GetGetCpuSets()(hProc, state.original_cpu_sets.data(), required_count, &returned)) {
                    state.original_cpu_sets.resize(returned);
                    state.cpu_sets_saved = true;
                } else {
                    state.original_cpu_sets.clear();
                }
            }
        }

        out_state = std::move(state);
        return true;
    }

    // PID'nin işletim sisteminde yeni bir sürece devredilip devredilmediğini kontrol eder
    bool HasPidBeenRecycled(DWORD pid, const FILETIME &expected_creation_time) const {
        HANDLE hCheck = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
        if (!hCheck) return false;

        FILETIME ft_create, ft_exit, ft_kernel, ft_user;
        bool recycled = false;
        if (GetProcessTimes(hCheck, &ft_create, &ft_exit, &ft_kernel, &ft_user)) {
            if (CompareFileTime(&ft_create, &expected_creation_time) != 0) {
                recycled = true;
            }
        }
        CloseHandle(hCheck);
        return recycled;
    }

    void OrchestrationCycle() {
        if (stop_requested.load()) return;

        auto cycle_start = std::chrono::high_resolution_clock::now();
        DWORD fg_pid = GetForegroundProcessIdSafe();

        HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
        if (snap == INVALID_HANDLE_VALUE) return;

        PROCESSENTRY32W pe;
        pe.dwSize = sizeof(pe);

        std::set<DWORD> active_pids;
        DWORD detected_game_pid = 0;
        DWORD current_session = 0;
        ProcessIdToSessionId(GetCurrentProcessId(), &current_session);

        {
            std::unique_lock<std::shared_mutex> lock(data_mutex);

            if (Process32FirstW(snap, &pe)) {
                do {
                    if (pe.th32ProcessID <= 4 || pe.th32ProcessID == GetCurrentProcessId()) continue;

                    DWORD proc_session = 0;
                    if (!ProcessIdToSessionId(pe.th32ProcessID, &proc_session) || proc_session != current_session) {
                        continue;
                    }

                    std::string exe = ToLower(Utf8FromWide(pe.szExeFile));
                    if (protected_processes.find(exe) != protected_processes.end()) continue;
                    if (user_exclusions.find(exe) != user_exclusions.end()) continue;

                    bool is_game = (target_games.find(exe) != target_games.end());
                    bool is_bg = (background_candidates.find(exe) != background_candidates.end());

                    if (!is_game && !is_bg) continue;

                    active_pids.insert(pe.th32ProcessID);
                    if (is_game) detected_game_pid = pe.th32ProcessID;

                    auto it = tracked_processes.find(pe.th32ProcessID);
                    if (it != tracked_processes.end()) {
                        // FIX #4: PID başka bir sürece devredildiyse önce eski süreci (handle'ı üzerinden) kurtar ve kapat
                        if (HasPidBeenRecycled(pe.th32ProcessID, it->second.creation_time) || it->second.exe_name != exe) {
                            StateRecoveryEngine::RestoreAndClose(it->second, cpu_sched.GetSetProcInfo(), cpu_sched.GetSetCpuSets());
                            tracked_processes.erase(it);
                            it = tracked_processes.end();
                        }
                    }

                    if (it == tracked_processes.end()) {
                        ProcessState new_state;
                        if (CaptureProcessState(pe.th32ProcessID, exe, is_game, new_state)) {
                            tracked_processes.emplace(pe.th32ProcessID, std::move(new_state));
                        }
                    }
                } while (Process32NextW(snap, &pe));
            }
            CloseHandle(snap);

            // Kapanan süreçleri geri yükle ve listeden sil
            for (auto it = tracked_processes.begin(); it != tracked_processes.end();) {
                if (active_pids.find(it->first) == active_pids.end()) {
                    StateRecoveryEngine::RestoreAndClose(it->second, cpu_sched.GetSetProcInfo(), cpu_sched.GetSetCpuSets());
                    it = tracked_processes.erase(it);
                } else {
                    ++it;
                }
            }

            // Politikaları Uygula
            double game_cpu_pct = 0.0;
            double bg_cpu_total_pct = 0.0;

            for (auto &kv : tracked_processes) {
                ProcessState &st = kv.second;
                st.is_foreground = (st.pid == fg_pid);
                double p_usage = cpu_sched.CalculateProcessCpuUsage(st);

                if (st.is_game) {
                    game_cpu_pct += p_usage;
                    cpu_sched.OptimizeGame(st);
                } else if (st.is_foreground) {
                    // FIX #5: Ön plana geçen arka plan uygulamasının TÜM kısıtlarını kaldır (Priority, Memory, EcoQoS, CpuSets)
                    if (st.current_policy != AppliedPolicy::ForegroundRestored) {
                        StateRecoveryEngine::RestoreLiveState(st, cpu_sched.GetSetProcInfo(), cpu_sched.GetSetCpuSets());
                        st.current_policy = AppliedPolicy::ForegroundRestored;
                    }
                } else {
                    bg_cpu_total_pct += p_usage;
                    cpu_sched.ThrottleBackground(st);
                }
            }

            // Dinamik Bellek Baskısı Kontrolü
            mem_mgr.OptimizeUnderPressure(tracked_processes, 85);

            // Telemetri Güncellemesi
            auto cycle_end = std::chrono::high_resolution_clock::now();
            double latency = std::chrono::duration<double, std::milli>(cycle_end - cycle_start).count();

            UINT64 total_ram, avail_ram, used_ram;
            DWORD mem_load;
            mem_mgr.GetSystemMemoryMetrics(total_ram, avail_ram, used_ram, mem_load);

            // [EK-FIX] GPU bellek alanlari daha once hic doldurulmuyordu
            double gpu_util = gpu_mon.GetGpuUtilization();
            UINT64 gpu_ded_bytes = 0, gpu_shared_bytes = 0;
            gpu_mon.GetGpuMemory(gpu_ded_bytes, gpu_shared_bytes);

            telemetry_cache.current_game_pid = detected_game_pid;
            telemetry_cache.current_game_cpu_percent = game_cpu_pct;
            telemetry_cache.total_cpu_usage_percent = cpu_sched.CalculateSystemCpuUsage();
            telemetry_cache.background_cpu_usage_percent = bg_cpu_total_pct;
            telemetry_cache.total_physical_ram_bytes = total_ram;
            telemetry_cache.available_physical_ram_bytes = avail_ram;
            telemetry_cache.used_physical_ram_bytes = used_ram;
            telemetry_cache.memory_load_percent = mem_load;
            telemetry_cache.working_set_freed_bytes = mem_mgr.GetFreedBytes();
            telemetry_cache.standby_purge_success_count = mem_mgr.GetPurgeCount();
            telemetry_cache.gpu_engine_utilization_percent = gpu_util;
            telemetry_cache.gpu_dedicated_memory_bytes = gpu_ded_bytes;
            telemetry_cache.gpu_shared_memory_bytes = gpu_shared_bytes;
            telemetry_cache.avg_loop_latency_ms = latency;
            telemetry_cache.power_plan_active = power_mgr.IsHighPerfActive();
            telemetry_cache.timer_resolution_active = (timer_period > 0);
            telemetry_cache.total_tracked_processes = static_cast<DWORD>(tracked_processes.size());
            telemetry_cache.is_gaming_mode_active = (detected_game_pid != 0);
            telemetry_cache.recovery_engine_ready = TRUE;
        }
    }

    // [EK-FIX] Thread icindeki yakalanmamis bir C++ istisnasi (ornegin bad_alloc) tum host sureci cokertirdi
    void SafeOrchestrationCycle() {
        try {
            OrchestrationCycle();
        } catch (...) {
        }
    }

    static DWORD WINAPI MonitorThreadProc(LPVOID param) {
        FocusEngine *engine = reinterpret_cast<FocusEngine *>(param);
        engine->SafeOrchestrationCycle();
        while (!engine->stop_requested.load()) {
            DWORD wait_rc = WaitForSingleObject(engine->stop_event, 2000);
            if (wait_rc == WAIT_OBJECT_0 || engine->stop_requested.load()) {
                break;
            }
            engine->SafeOrchestrationCycle();
        }
        return 0;
    }

public:
    static FocusEngine &Instance() {
        static FocusEngine instance;
        return instance;
    }

    bool Start() {
        std::lock_guard<std::mutex> lock(lifecycle_mutex);
        if (is_running.load()) return true;

        // Eğer önceki bir Stop() çağrısı zaman aşımına uğradıysa ve eski thread sonunda bittiyse temizle
        if (monitor_thread) {
            if (WaitForSingleObject(monitor_thread, 0) == WAIT_OBJECT_0) {
                CloseHandle(monitor_thread);
                monitor_thread = NULL;
            } else {
                return false; // Eski thread hâlâ yanıt vermiyor
            }
        }
        if (stop_event) {
            CloseHandle(stop_event);
            stop_event = NULL;
        }

        stop_requested.store(false);

        HMODULE kernel = GetModuleHandleW(L"kernel32.dll");
        cpu_sched.Initialize(kernel);
        power_mgr.Initialize();
        mem_mgr.Initialize();
        gpu_mon.Initialize();

        TIMECAPS tc;
        if (timeGetDevCaps(&tc, sizeof(tc)) == TIMERR_NOERROR) {
            UINT target_period = (tc.wPeriodMin < 1) ? 1 : tc.wPeriodMin;
            if (timeBeginPeriod(target_period) == TIMERR_NOERROR) {
                timer_period = target_period;
            }
        }

        power_mgr.SetHighPerformance();

        stop_event = CreateEventW(NULL, TRUE, FALSE, NULL);
        if (!stop_event) {
            // [EK-FIX] Basarisiz baslatmada PDH sorgusu ve powrprof.dll sizdirilmasin
            power_mgr.Shutdown();
            gpu_mon.Shutdown();
            if (timer_period > 0) {
                timeEndPeriod(timer_period);
                timer_period = 0;
            }
            return false;
        }

        monitor_thread = CreateThread(NULL, 0, MonitorThreadProc, this, 0, NULL);
        if (!monitor_thread) {
            CloseHandle(stop_event);
            stop_event = NULL;
            // [EK-FIX] Basarisiz baslatmada PDH sorgusu ve powrprof.dll sizdirilmasin
            power_mgr.Shutdown();
            gpu_mon.Shutdown();
            if (timer_period > 0) {
                timeEndPeriod(timer_period);
                timer_period = 0;
            }
            return false;
        }

        is_running.store(true);
        return true;
    }

    // FIX #1: Thread gerçekten sonlanmadan handle kapatılmaz ve kaynaklar temizlenmez
    bool Stop() {
        std::lock_guard<std::mutex> lock(lifecycle_mutex);
        if (!is_running.load() && !monitor_thread) return true;

        stop_requested.store(true);
        if (stop_event) {
            SetEvent(stop_event);
        }

        if (monitor_thread) {
            DWORD wait_res = WaitForSingleObject(monitor_thread, 8000);
            if (wait_res != WAIT_OBJECT_0) {
                // KRİTİK KORUMA: Thread hâlâ çalışıyor!
                // Handle kapatılmaz, haritalar temizlenmez, veri yarışı (data race) önlenir ve başarısızlık bildirilir.
                return false;
            }
            CloseHandle(monitor_thread);
            monitor_thread = NULL;
        }

        if (stop_event) {
            CloseHandle(stop_event);
            stop_event = NULL;
        }

        // Thread'in tamamen sonlandığı garanti edildi; şimdi kaynaklar güvenle geri yüklenebilir
        {
            std::unique_lock<std::shared_mutex> dlock(data_mutex);
            for (auto &kv : tracked_processes) {
                StateRecoveryEngine::RestoreAndClose(kv.second, cpu_sched.GetSetProcInfo(), cpu_sched.GetSetCpuSets());
            }
            tracked_processes.clear();
            telemetry_cache.current_game_pid = 0;
            telemetry_cache.total_tracked_processes = 0;
            telemetry_cache.is_gaming_mode_active = FALSE;
        }

        power_mgr.Shutdown();
        gpu_mon.Shutdown();

        if (timer_period > 0) {
            timeEndPeriod(timer_period);
            timer_period = 0;
        }

        // [EK-FIX] Durdurulduktan sonra telemetride eski (stale) "aktif" bayraklari kalmasin
        {
            std::unique_lock<std::shared_mutex> dlock(data_mutex);
            telemetry_cache.power_plan_active = FALSE;
            telemetry_cache.timer_resolution_active = FALSE;
        }

        is_running.store(false);
        return true;
    }

    void GetTelemetry(EngineTelemetry *out) const {
        if (!out) return;
        std::shared_lock<std::shared_mutex> lock(data_mutex);
        *out = telemetry_cache;
    }

    void AddTargetGame(const std::string &exe_name) {
        std::unique_lock<std::shared_mutex> lock(data_mutex);
        target_games.insert(ToLower(exe_name));
    }

    void AddUserExclusion(const std::string &exe_name) {
        std::unique_lock<std::shared_mutex> lock(data_mutex);
        user_exclusions.insert(ToLower(exe_name));
    }

    bool IsRunning() const { return is_running.load(); }
};

} // namespace ForzeEngine

// ============================================================================
// DIŞA AKTARILAN C API FONKSİYONLARI (PYTHON & ESKİ SÜRÜM UYUMLU)
// ============================================================================
extern "C" {

__declspec(dllexport) int __stdcall ForzeEngineStart() {
    return ForzeEngine::FocusEngine::Instance().Start() ? 1 : 0;
}

__declspec(dllexport) int __stdcall ForzeEngineStop() {
    return ForzeEngine::FocusEngine::Instance().Stop() ? 1 : 0;
}

__declspec(dllexport) int __stdcall ForzeEngineGetTelemetry(ForzeEngine::EngineTelemetry *out) {
    if (!out) return 0;
    ForzeEngine::FocusEngine::Instance().GetTelemetry(out);
    return 1;
}

__declspec(dllexport) int __stdcall ForzeEngineAddGame(const char *exe_name) {
    if (!exe_name) return 0;
    ForzeEngine::FocusEngine::Instance().AddTargetGame(exe_name);
    return 1;
}

__declspec(dllexport) int __stdcall ForzeEngineAddExclusion(const char *exe_name) {
    if (!exe_name) return 0;
    ForzeEngine::FocusEngine::Instance().AddUserExclusion(exe_name);
    return 1;
}

__declspec(dllexport) int __stdcall ForzeEngineIsRunning() {
    return ForzeEngine::FocusEngine::Instance().IsRunning() ? 1 : 0;
}

// Eski ForzeOS sarmalayıcıları (wrappers) ile tam geriye dönük uyumluluk
__declspec(dllexport) int __stdcall ForzeStartAggressiveFocus() {
    return ForzeEngineStart();
}

__declspec(dllexport) int __stdcall ForzeStopAggressiveFocus() {
    return ForzeEngineStop();
}

__declspec(dllexport) int __stdcall DllRegisterFocusFilter() {
    return ForzeEngineStart();
}

__declspec(dllexport) int __stdcall DllUnregisterFocusFilter() {
    return ForzeEngineStop();
}

} // extern "C"

// FIX #2: DllMain içinde kesinlikle thread beklenmez veya Stop() çağrılmaz (Loader Lock Deadlock Koruması)
BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(inst);
    }
    return TRUE;
}
// forze_aggressive_focus.cpp
// Improved aggressive focus native helper.
// Behavior:
// - Best-effort enable SeDebugPrivilege for larger access (non-fatal if unavailable).
// - Enumerates user processes (Toolhelp32), filters out critical/system processes,
//   prefers processes in the same session, and skips small/RSS processes.
// - Performs a working-set trim (EmptyWorkingSet) on selected candidates.
// - Limits number of trims and is configurable via environment variables:
//     FORZEOS_MAX_TRIMS (default 5)
//     FORZEOS_MIN_RSS_MB (default 300)
//     FORZEOS_ONLY_SAME_SESSION (default 1)
// - Returns the number of processes successfully trimmed, or -1 on fatal error.

#include <windows.h>
#include <psapi.h>
#include <tlhelp32.h>
#include <tchar.h>
#include <stdio.h>
#include <vector>
#include <string>
#include <algorithm>
#include <cstdlib>

#pragma comment(lib, "psapi.lib")

// Track modified process priorities so we can restore them when focus stops
static std::vector<std::pair<DWORD, DWORD>> g_modified_priorities;

// Helper: enum callback to find visible top-level windows for a pid
struct EnumData { DWORD pid; bool found; RECT rect; };
static BOOL CALLBACK _enum_proc_find(HWND hwnd, LPARAM lParam)
{
    EnumData* d = (EnumData*)lParam;
    DWORD wpid = 0;
    GetWindowThreadProcessId(hwnd, &wpid);
    if (wpid != d->pid) return TRUE;
    if (!IsWindowVisible(hwnd)) return TRUE;
    RECT r; GetWindowRect(hwnd, &r);
    if ((r.right - r.left) > 20 && (r.bottom - r.top) > 20) {
        d->found = true;
        d->rect = r;
        return FALSE; // stop
    }
    return TRUE;
}

static bool has_visible_window_for_pid(DWORD pid)
{
    EnumData d = { pid, false, {0,0,0,0} };
    EnumWindows(_enum_proc_find, (LPARAM)&d);
    return d.found;
}

static bool pid_has_fullscreen_window(DWORD pid)
{
    EnumData d = { pid, false, {0,0,0,0} };
    EnumWindows(_enum_proc_find, (LPARAM)&d);
    if (!d.found) return false;
    int sw = GetSystemMetrics(SM_CXSCREEN);
    int sh = GetSystemMetrics(SM_CYSCREEN);
    int w = d.rect.right - d.rect.left;
    int h = d.rect.bottom - d.rect.top;
    return (abs(w - sw) <= 6 && abs(h - sh) <= 6);
}

static BOOL EnableDebugPrivilege()
{
    HANDLE hToken = NULL;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, &hToken))
        return FALSE;

    TOKEN_PRIVILEGES tp;
    LUID luid;
    if (!LookupPrivilegeValue(NULL, SE_DEBUG_NAME, &luid)) {
        CloseHandle(hToken);
        return FALSE;
    }

    tp.PrivilegeCount = 1;
    tp.Privileges[0].Luid = luid;
    tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED;

    AdjustTokenPrivileges(hToken, FALSE, &tp, sizeof(TOKEN_PRIVILEGES), NULL, NULL);
    BOOL ok = (GetLastError() == ERROR_SUCCESS);
    CloseHandle(hToken);
    return ok;
}

// helper: read integer env var, with default
static int getenv_int(const char* name, int def)
{
    char buf[64];
    DWORD r = GetEnvironmentVariableA(name, buf, (DWORD)sizeof(buf));
    if (r == 0 || r >= sizeof(buf)) return def;
    return atoi(buf);
}

// Read comma-separated env var into vector of lowercase strings
static std::vector<std::string> getenv_list_lower(const char* name)
{
    std::vector<std::string> out;
    char buf[8192];
    DWORD r = GetEnvironmentVariableA(name, buf, (DWORD)sizeof(buf));
    if (r == 0 || r >= sizeof(buf)) return out;
    std::string s(buf);
    size_t pos = 0;
    while (pos < s.size()) {
        size_t comma = s.find(',', pos);
        if (comma == std::string::npos) comma = s.size();
        std::string item = s.substr(pos, comma - pos);
        // trim
        size_t a = item.find_first_not_of(" \t\r\n");
        size_t b = item.find_last_not_of(" \t\r\n");
        if (a != std::string::npos && b != std::string::npos && b >= a) {
            std::string t = item.substr(a, b - a + 1);
            std::transform(t.begin(), t.end(), t.begin(), ::tolower);
            out.push_back(t);
        }
        pos = comma + 1;
    }
    return out;
}

extern "C" {

__declspec(dllexport) int aggressive_focus_start()
{
    // Read runtime configuration from env vars
    int max_trims = getenv_int("FORZEOS_MAX_TRIMS", 5);
    int min_rss_mb = getenv_int("FORZEOS_MIN_RSS_MB", 300);
    int only_same_session = getenv_int("FORZEOS_ONLY_SAME_SESSION", 1);

    // Try enable debug privilege (best-effort)
    EnableDebugPrivilege();

    // Get current session id to prefer trimming processes in same session
    DWORD my_session = 0;
    ProcessIdToSessionId(GetCurrentProcessId(), &my_session);

    // Snapshot processes
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return -1;

    PROCESSENTRY32 pe;
    pe.dwSize = sizeof(pe);

    std::vector<std::pair<SIZE_T, DWORD>> candidates; // (rss, pid)

    if (Process32First(snap, &pe)) {
        do {
            DWORD pid = pe.th32ProcessID;
            if (pid == 0 || pid <= 4) continue;

            // skip obvious critical names
            std::string name;
            #ifdef UNICODE
            {
                wchar_t* w = pe.szExeFile;
                int n = WideCharToMultiByte(CP_UTF8, 0, w, -1, NULL, 0, NULL, NULL);
                if (n > 0) {
                    name.resize(n);
                    WideCharToMultiByte(CP_UTF8, 0, w, -1, &name[0], n, NULL, NULL);
                }
            }
            #else
            name = pe.szExeFile;
            #endif
            std::transform(name.begin(), name.end(), name.begin(), ::tolower);
            // Load optional lists from env once
            static std::vector<std::string> g_whitelist = getenv_list_lower("FORZEOS_WHITELIST_NAMES");
            static std::vector<std::string> g_blacklist = getenv_list_lower("FORZEOS_BLACKLIST_NAMES");

            // Built-in exclusions still apply
            if (name.find("explorer.exe") != std::string::npos) continue;
            if (name.find("svchost.exe") != std::string::npos) continue;
            if (name.find("lsass.exe") != std::string::npos) continue;
            if (name.find("csrss.exe") != std::string::npos) continue;

            // If name is explicitly whitelisted, skip trimming
            bool is_whitelisted = false;
            for (auto &w : g_whitelist) if (!w.empty() && name.find(w) != std::string::npos) { is_whitelisted = true; break; }
            if (is_whitelisted) { continue; }

            // Open process with slightly broader rights (we may query/set info)
            HANDLE h = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ | PROCESS_SET_INFORMATION | PROCESS_SET_QUOTA, FALSE, pid);
            if (!h) continue;

            // Optionally prefer same session
            if (only_same_session) {
                DWORD sess = 0;
                if (ProcessIdToSessionId(pid, &sess)) {
                    if (sess != my_session) {
                        CloseHandle(h);
                        continue;
                    }
                }
            }

            // Skip interactive apps / games: if a process has a visible top-level window, skip it.
            bool hasVis = has_visible_window_for_pid(pid);
            if (hasVis) {
                // if fullscreen, definitely skip (avoid touching games)
                if (pid_has_fullscreen_window(pid)) {
                    CloseHandle(h);
                    continue;
                }
                // non-fullscreen visible windows: skip too (conservative)
                CloseHandle(h);
                continue;
            }

            PROCESS_MEMORY_COUNTERS pmc;
            SIZE_T rss = 0;
            if (GetProcessMemoryInfo(h, &pmc, sizeof(pmc))) {
                rss = pmc.WorkingSetSize;
            }
            CloseHandle(h);

            // If blacklisted, prefer to include even if below threshold
            bool is_blacklisted = false;
            for (auto &b : g_blacklist) if (!b.empty() && name.find(b) != std::string::npos) { is_blacklisted = true; break; }

            // filter by rss (don't trim tiny processes) unless blacklisted
            if (!is_blacklisted && rss < (SIZE_T)min_rss_mb * 1024ull * 1024ull) continue;

            candidates.emplace_back(rss, pid);
        } while (Process32Next(snap, &pe));
    }

    CloseHandle(snap);

    // Sort candidates by RSS descending
    std::sort(candidates.begin(), candidates.end(), [](const std::pair<SIZE_T, DWORD>& a, const std::pair<SIZE_T, DWORD>& b){
        return a.first > b.first;
    });

    int trimmed = 0;
    for (auto &c : candidates) {
        if (trimmed >= max_trims) break;
        DWORD pid = c.second;

        HANDLE h = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA | PROCESS_SET_INFORMATION, FALSE, pid);
        if (!h) continue;

        // Lower priority to reduce CPU contention for background processes
        DWORD origPri = 0;
        origPri = GetPriorityClass(h);
        if (origPri != 0) {
            if (SetPriorityClass(h, BELOW_NORMAL_PRIORITY_CLASS)) {
                g_modified_priorities.emplace_back(pid, origPri);
            }
        }

        // Attempt to empty working set (least intrusive)
        BOOL ok = FALSE;
        if (EmptyWorkingSet(h)) ok = TRUE;

        CloseHandle(h);

        if (ok) {
            trimmed++;
        }
    }

    return trimmed;
}

__declspec(dllexport) int aggressive_focus_stop()
{
    int restored = 0;
    for (auto &p : g_modified_priorities) {
        DWORD pid = p.first;
        DWORD orig = p.second;
        HANDLE h = OpenProcess(PROCESS_SET_INFORMATION, FALSE, pid);
        if (!h) continue;
        if (SetPriorityClass(h, orig)) restored++;
        CloseHandle(h);
    }
    g_modified_priorities.clear();
    return restored;
}

} // extern "C"

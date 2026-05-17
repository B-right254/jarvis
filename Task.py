import win32gui
import win32con
import win32process
import psutil

# System processes that are never real user apps
SYSTEM_PROCS = {
    "TextInputHost.exe",
    "ApplicationFrameHost.exe",
    "ShellExperienceHost.exe",
    "SearchHost.exe",
    "LockApp.exe",
    "SystemSettings.exe",       # <-- add this
}
def is_real_taskbar_window(hwnd):
    if not win32gui.IsWindowVisible(hwnd):
        return False
    if not win32gui.GetWindowText(hwnd).strip():
        return False
    if win32gui.GetWindow(hwnd, win32con.GW_OWNER):
        return False

    ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    if ex_style & win32con.WS_EX_TOOLWINDOW:
        return False
    if ex_style & win32con.WS_EX_NOACTIVATE:
        return False

    return True

def get_taskbar_apps():
    taskbar_apps = []
    seen_titles = set()

    def callback(hwnd, _):
        if not is_real_taskbar_window(hwnd):
            return

        title = win32gui.GetWindowText(hwnd)

        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = psutil.Process(pid)
            proc_name = proc.name()
        except Exception:
            proc_name = "unknown"

        # Skip known system processes
        if proc_name in SYSTEM_PROCS:
            return

        # Deduplicate by title (catches UWP doubles)
        if title in seen_titles:
            return
        seen_titles.add(title)

        taskbar_apps.append((title, proc_name))

    win32gui.EnumWindows(callback, None)

    print(f"\nTaskbar applications: {len(taskbar_apps)}\n")
    for i, (title, proc) in enumerate(taskbar_apps, 1):
        print(f"{i}. [{proc}] {title}")

    return taskbar_apps

if __name__ == "__main__":
    get_taskbar_apps()
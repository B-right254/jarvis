"""
Tool adapters â€” maps clean schema tool names to Python implementations.
Each function accepts **kwargs (unpacked by safety executor), returns dict.
"""
import datetime
import os
import re
import subprocess
import glob as glob_mod
import shutil
import webbrowser
from pathlib import Path

import psutil
try:
    import pyautogui
except ImportError:
    pyautogui = None  # type: ignore

try:
    import pygetwindow as gw
except ImportError:
    gw = None  # type: ignore

# Stub for pyautogui if missing
if pyautogui is None:
    class _PyAutoGuiStub:
        FAILSAFE = True
        @staticmethod
        def screenshot(region=None):
            class DummyImg:
                width = 0
                height = 0
                def save(self, buf, format):
                    pass
            return DummyImg()
        @staticmethod
        def click(x=None, y=None, button='left'):
            pass
        @staticmethod
        def write(text):
            pass
        @staticmethod
        def press(key):
            pass
        @staticmethod
        def hotkey(*keys):
            pass
        @staticmethod
        def scroll(clicks):
            pass
        @staticmethod
        def doubleClick(x=None, y=None):
            pass
        @staticmethod
        def rightClick(x=None, y=None):
            pass
        @staticmethod
        def moveTo(x, y):
            pass
        @staticmethod
        def drag(x, y):
            pass
    pyautogui = _PyAutoGuiStub()

# Stub for pygetwindow if missing
if gw is None:
    class _GWWindowStub:
        def __init__(self, title=''):
            self.title = title
            self.visible = True
            self.isMinimized = False
        def restore(self):
            pass
        def activate(self):
            pass
        @property
        def _hWnd(self):
            return 0

    class _GWStub:
        @staticmethod
        def getActiveWindow():
            return None
        @staticmethod
        def getAllWindows():
            return []
        @staticmethod
        def getWindowsWithTitle(title):
            return []
    gw = _GWStub()

from tools.system.execute_code import execute_code as _run_code
from tools.comm.schedule_tool import schedule as _schedule
from tools.voice.listen import listen as _listen
from tools.comm.time_calendar import time_calendar as _time_calendar


def _safe_resolve_path(path: str) -> str | None:
    """Resolve and validate a path is within allowed directories. Returns resolved path or None."""
    try:
        resolved = Path(path).resolve()
        home = Path.home().resolve()
        allowed = [home, Path(os.environ.get("TEMP", "C:\\Windows\\Temp")).resolve()]
        if any(str(resolved).startswith(str(a)) for a in allowed):
            return str(resolved)
    except (OSError, ValueError, RuntimeError):
        pass
    return None


def open_app(**kwargs) -> dict:
    # LLM sometimes hallucinates app_name instead of name — normalise both
    name = kwargs.get("name") or kwargs.get("app_name", "")
    # Try 1: os.startfile (works for PATH-resolvable names like 'notepad', 'calc')
    try:
        os.startfile(name) if os.name == "nt" else subprocess.Popen([name])
        return {"success": True, "status": f"launched {name}", "name": name}
    except Exception:
        pass
    # Try 2: shutil.which (finds system PATH executables)
    try:
        which_path = shutil.which(name) or shutil.which(f"{name}.exe")
        if which_path:
            os.startfile(which_path) if os.name == "nt" else subprocess.Popen([which_path])
            return {"success": True, "status": f"launched {name}", "name": name, "path": which_path}
    except Exception:
        pass
    # Try 3: search installed apps via PC index DB
    try:
        db_path = Path(__file__).parent.parent / "indexer" / "db" / "pc_index.db"
        if db_path.exists():
            import sqlite3
            conn = sqlite3.connect(str(db_path))
            try:
                cur = conn.execute("SELECT name, exe_path FROM apps WHERE name LIKE ?", (f"%{name}%",))
                rows = cur.fetchall()
            finally:
                conn.close()
            for row_name, exe_path in rows:
                resolved = _resolve_exe(exe_path, row_name)
                if resolved:
                    try:
                        os.startfile(resolved) if os.name == "nt" else subprocess.Popen([resolved])
                        return {"success": True, "status": f"launched {name}", "name": name, "path": resolved}
                    except Exception:
                        pass
    except Exception:
        pass
    return {"success": False, "error": f"could not find '{name}' in PATH or app index. try list_installed_apps first."}


def _resolve_exe(exe_path: str | None, app_name: str) -> str | None:
    """Resolve a DB path to an executable. Returns best-effort path or None.

    - Direct .exe/.lnk paths returned as-is (may exist, may be permission-restricted)
    - Directory paths searched for first matching .exe
    - Falls back to shutil.which() for PATH-resolvable apps (e.g. 'notepad', 'calc')
    """
    if exe_path:
        cleaned = exe_path.strip().strip('"')
        if cleaned:
            p = Path(cleaned)
            if p.suffix.lower() in (".exe", ".lnk"):
                return str(p)
            if p.is_dir():
                exe_candidate = p / f"{app_name}.exe"
                if exe_candidate.exists():
                    return str(exe_candidate)
                try:
                    for f in p.iterdir():
                        if f.suffix.lower() == ".exe":
                            return str(f)
                except PermissionError:
                    pass

    which = shutil.which(app_name)
    if which:
        return which
    which_alt = shutil.which(f"{app_name}.exe")
    if which_alt:
        return which_alt
    if app_name.endswith(".exe"):
        which_alt = shutil.which(app_name[:-4])
        if which_alt:
            return which_alt

    return exe_path if exe_path else None


def close_app(**kwargs) -> dict:
    name = kwargs.get("name", "")
    force = kwargs.get("force", False)
    if not re.match(r"^[a-zA-Z0-9._\-, ]+$", name):
        return {"success": False, "error": f"Invalid process name: {name!r}"}
    try:
        args = ["taskkill", "/IM", f"{name}.exe"]
        if force:
            args.append("/F")
        subprocess.run(args, capture_output=True, timeout=5)
        return {"success": True, "status": f"closed {name}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_active_window(**kwargs) -> dict:
    try:
        win = gw.getActiveWindow()
        if win:
            return {"success": True, "title": win.title, "process": "unknown"}
        return {"success": True, "title": "", "process": ""}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _find_window(title: str = "", process: str = ""):
    """Find a window by title or process name. Returns window object or None."""
    target = None
    if title:
        for w in gw.getWindowsWithTitle(title):
            target = w
            break
    if not target and process:
        for w in gw.getAllWindows():
            if process.lower() in w.title.lower():
                target = w
                break
    return target


def focus_window(**kwargs) -> dict:
    title = kwargs.get("title", "")
    process = kwargs.get("process", "")
    try:
        target = _find_window(title, process)
        if target:
            if target.isMinimized:
                target.restore()
            target.activate()
            try:
                import ctypes
                hwnd = target._hWnd
                ctypes.windll.user32.BringWindowToTop(hwnd)
                ctypes.windll.user32.SetForegroundWindow(hwnd)
            except Exception:
                pass
            return {"success": True, "status": f"focused {target.title}"}
        return {"success": False, "error": "window not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_running_apps(**kwargs) -> dict:
    try:
        windows = []
        for w in gw.getAllWindows():
            if w.title.strip():
                windows.append({"title": w.title, "visible": w.visible})
        return {"success": True, "windows": windows[:50]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_system_stats(**kwargs) -> dict:
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/" if os.name != "nt" else "C:\\")
        battery = psutil.sensors_battery()
        return {
            "success": True,
            "cpu_percent": cpu,
            "ram_percent": ram.percent,
            "ram_free_gb": round(ram.available / 1e9, 1),
            "disk_percent": disk.percent,
            "disk_free_gb": round(disk.free / 1e9, 1),
            "battery_percent": round(battery.percent, 1) if battery else None,
            "battery_plugged": battery.power_plugged if battery else None,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def screenshot(**kwargs) -> dict:
    try:
        region = kwargs.get("region")
        if region:
            img = pyautogui.screenshot(region=(region["left"], region["top"], region["width"], region["height"]))
        else:
            img = pyautogui.screenshot()
        import io, base64
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return {"success": True, "image_b64": b64, "width": img.width, "height": img.height}
    except Exception as e:
        return {"success": False, "error": str(e)}


def read_screen(**kwargs) -> dict:
    try:
        import pytesseract
        from PIL import Image
        region = kwargs.get("region")
        if region:
            img = pyautogui.screenshot(region=(region["left"], region["top"], region["width"], region["height"]))
        else:
            img = pyautogui.screenshot()
        text = pytesseract.image_to_string(img)
        return {"success": True, "text": text.strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def click(**kwargs) -> dict:
    try:
        x, y = kwargs.get("x"), kwargs.get("y")
        button = kwargs.get("button", "left")
        verify_text = kwargs.get("verify_text", "")

        # B2: Two-phase grounding â€” if verify_text is provided, cross-reference with OCR
        if verify_text and x is not None and y is not None:
            try:
                ocr_result = detect_ui_elements(text=verify_text, element_type="text")
                if ocr_result.get("success") and ocr_result.get("elements"):
                    for elem in ocr_result["elements"]:
                        bx, by, bw, bh = elem.get("x", 0), elem.get("y", 0), elem.get("w", 0), elem.get("h", 0)
                        # Use OCR center as the verified target
                        x, y = bx + bw // 2, by + bh // 2
                        break
            except Exception:
                pass  # Fall through to raw coordinates on any failure

        failsafe_was = pyautogui.FAILSAFE
        pyautogui.FAILSAFE = False
        try:
            pyautogui.click(x, y, button=button)
        finally:
            pyautogui.FAILSAFE = failsafe_was
        return {"success": True, "status": f"clicked ({x}, {y})"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def type_text(**kwargs) -> dict:
    try:
        text = kwargs.get("text", "")
        pyautogui.write(text)
        if kwargs.get("enter"):
            pyautogui.press("enter")
        return {"success": True, "typed": len(text)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def press_keys(**kwargs) -> dict:
    try:
        raw = kwargs.get("keys", "")
        keys = raw.lower().replace(" ", "").split("+")
        # pyautogui.hotkey only understands named keys (ctrl, shift, etc.)
        # For single characters like "/", use write() instead
        if len(keys) == 1 and len(keys[0]) == 1:
            pyautogui.write(keys[0])
        else:
            pyautogui.hotkey(*keys)
        return {"success": True, "keys": raw}
    except Exception as e:
        return {"success": False, "error": str(e)}


def scroll(**kwargs) -> dict:
    try:
        clicks = kwargs.get("clicks", -3)
        pyautogui.scroll(clicks)
        return {"success": True, "clicks": clicks}
    except Exception as e:
        return {"success": False, "error": str(e)}


def wait(**kwargs) -> dict:
    import time
    ms = kwargs.get("ms", 1000)
    condition = kwargs.get("condition", "")
    target = kwargs.get("target", "")
    timeout_ms = kwargs.get("timeout_ms", ms * 2)

    if condition and target:
        deadline = time.time() + (timeout_ms / 1000.0)
        poll_interval = 0.2
        started = time.time()
        while time.time() < deadline:
            if _check_wait_condition(condition, target):
                elapsed = int((time.time() - started) * 1000)
                return {"success": True, "message": f"condition met: {condition} '{target}'", "data": {"condition": condition, "target": target, "duration_ms": elapsed}}
            time.sleep(poll_interval)
        elapsed = int((time.time() - started) * 1000)
        return {"success": False, "message": f"Timeout waiting for {condition} '{target}' after {timeout_ms}ms", "data": {"condition": condition, "target": target, "timeout_ms": timeout_ms, "duration_ms": elapsed}, "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()}

    time.sleep(ms / 1000.0)
    return {"success": True, "message": f"waited {ms}ms", "data": {"duration_ms": ms}, "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()}


def _check_wait_condition(condition: str, target: str) -> bool:
    import psutil
    target_lower = target.lower()

    if condition == "process_running":
        return any(target_lower in p.name().lower() for p in psutil.process_iter(["name"]))
    if condition == "process_gone":
        return not any(target_lower in p.name().lower() for p in psutil.process_iter(["name"]))
    if condition == "cpu_idle":
        try:
            return psutil.cpu_percent(interval=0.1) < float(target_lower)
        except ValueError:
            return False
    if condition in ("window_visible", "text_visible", "window_exists"):
        try:
            import pygetwindow as gw
            return len(gw.getWindowsWithTitle(target_lower)) > 0
        except Exception:
            return False

    return False


def search_files(**kwargs) -> dict:
    try:
        pattern = kwargs.get("pattern", "")
        location = kwargs.get("location", str(Path.home() / "Desktop"))
        # Prevent path traversal
        location_resolved = Path(location).resolve()
        home = Path.home().resolve()
        if not str(location_resolved).startswith(str(home)):
            return {"success": False, "error": f"Location must be under user home directory: {home}"}
        max_results = kwargs.get("max_results", 20)
        matches = []
        search_path = location_resolved / "**" / pattern
        for f in glob_mod.glob(str(search_path), recursive=True)[:max_results]:
            p = Path(f)
            try:
                size = p.stat().st_size if p.is_file() else 0
            except OSError:
                size = 0
            matches.append({"name": p.name, "path": str(p), "size": size})
        return {"success": True, "results": matches, "count": len(matches)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def open_file(**kwargs) -> dict:
    try:
        path = kwargs.get("path", "")
        resolved = _safe_resolve_path(path)
        if not resolved:
            return {"success": False, "error": f"Path not allowed: {path}"}
        os.startfile(resolved)
        return {"success": True, "status": f"opened {resolved}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def read_file(**kwargs) -> dict:
    try:
        path = kwargs.get("path", "")
        resolved = _safe_resolve_path(path)
        if not resolved:
            return {"success": False, "error": f"Path not allowed: {path}"}
        max_chars = kwargs.get("max_chars", 5000)
        with open(resolved, encoding="utf-8", errors="replace") as f:
            content = f.read(max_chars)
        return {"success": True, "content": content, "truncated": len(content) >= max_chars}
    except Exception as e:
        return {"success": False, "error": str(e)}


def write_file(**kwargs) -> dict:
    try:
        path = kwargs.get("path", "")
        content = kwargs.get("content", "")
        resolved = _safe_resolve_path(path)
        if not resolved:
            return {"success": False, "error": f"Path not allowed: {path}"}
        os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)
        return {"success": True, "status": f"wrote {len(content)} chars to {resolved}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def delete_file(**kwargs) -> dict:
    try:
        path = kwargs.get("path", "")
        resolved = _safe_resolve_path(path)
        if not resolved:
            return {"success": False, "error": f"Path not allowed: {path}"}
        if os.path.isdir(resolved):
            try:
                os.rmdir(resolved)
            except OSError:
                return {"success": False, "error": f"Directory not empty: {resolved}. Use execute_code with caution for recursive deletes."}
        else:
            os.remove(resolved)
        return {"success": True, "status": f"deleted {resolved}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def move_file(**kwargs) -> dict:
    try:
        src = kwargs.get("source", "")
        dst = kwargs.get("destination", "")
        src_resolved = _safe_resolve_path(src)
        dst_resolved = _safe_resolve_path(dst)
        if not src_resolved:
            return {"success": False, "error": f"Source path not allowed: {src}"}
        if not dst_resolved:
            return {"success": False, "error": f"Destination path not allowed: {dst}"}
        os.makedirs(os.path.dirname(dst_resolved) or ".", exist_ok=True)
        shutil.move(src_resolved, dst_resolved)
        return {"success": True, "status": f"moved {src_resolved} to {dst_resolved}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_python(**kwargs) -> dict:
    return _run_code(
        code=kwargs.get("code", ""),
        language="python",
        timeout=kwargs.get("timeout", 30),
    )


def execute_code(**kwargs) -> dict:
    return _run_code(
        code=kwargs.get("code", ""),
        language=kwargs.get("language", "python"),
        background=kwargs.get("background", False),
        action=kwargs.get("action", "run"),
        pid=kwargs.get("pid", 0),
        timeout=kwargs.get("timeout", 60),
    )


_WEB_SEARCH_TEMPLATE = """\
import json, urllib.request, urllib.parse, re
q = urllib.parse.quote({query_repr})
url = f"https://html.duckduckgo.com/html/?q={{q}}"
try:
    req = urllib.request.Request(url, headers={{"User-Agent": "Mozilla/5.0"}})
    resp = urllib.request.urlopen(req, timeout=15)
    html = resp.read().decode("utf-8", errors="replace")
    results = []
    # Parse result blocks from DDG HTML search results
    for block in re.findall(r'<a rel="nofollow" class="result__a" href="(.*?)".*?>(.*?)</a>', html, re.DOTALL)[:{n_repr}]:
        url = block[0]
        title = re.sub(r"<.*?>", "", block[1]).strip()
        results.append({{"title": title[:200], "url": url}})
    print(json.dumps({{"results": results, "count": len(results)}}))
except Exception as e:
    print(json.dumps({{"error": str(e), "results": [], "count": 0}}))
"""


def web_search(**kwargs) -> dict:
    query = kwargs.get("query", "")
    n = kwargs.get("max_results", 5)
    code = _WEB_SEARCH_TEMPLATE.format(
        query_repr=repr(query),
        n_repr=repr(n),
    )
    return _run_code(code=code, language="python", timeout=20)


def open_url(**kwargs) -> dict:
    try:
        url = kwargs.get("url", "")
        webbrowser.open(url)
        return {"success": True, "status": f"opened {url}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


_FETCH_TEMPLATE = """\
import urllib.request, html.parser
class P(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
    def handle_data(self, d):
        self.text.append(d)
p = P()
try:
    resp = urllib.request.urlopen({url_repr}, timeout=10)
    p.feed(resp.read().decode("utf-8", errors="replace"))
    result = " ".join(p.text)[:{n_repr}]
    print(result)
except Exception as e:
    print(f"Error: {{e}}")
"""


def fetch_page(**kwargs) -> dict:
    url = kwargs.get("url", "")
    n = kwargs.get("max_chars", 10000)
    code = _FETCH_TEMPLATE.format(
        url_repr=repr(url),
        n_repr=repr(n),
    )
    return _run_code(code=code, language="python", timeout=15)


def store_memory(**kwargs) -> dict:
    from tools.memory import memory
    return memory(action="store", key=kwargs.get("key"), value=kwargs.get("value"))


def retrieve_memory(**kwargs) -> dict:
    from tools.memory import memory
    return memory(action="recall", key=kwargs.get("key"))


def forget_memory(**kwargs) -> dict:
    from tools.memory import memory
    return memory(action="forget", key=kwargs.get("key"))


def search_memory(**kwargs) -> dict:
    from tools.memory import memory
    return memory(action="search", query=kwargs.get("query"), limit=kwargs.get("limit", 10))


def send_message(**kwargs) -> dict:
    from tools.comm.send_message import send_message as _send
    return _send(
        to=kwargs.get("to", ""),
        subject=kwargs.get("subject", ""),
        body=kwargs.get("body", ""),
    )


def speak(**kwargs) -> dict:
    from tools.voice.speak import speak as _speak
    return _speak(text=kwargs.get("text", ""), blocking=True)


def minimize_window(**kwargs) -> dict:
    title = kwargs.get("title", "")
    process = kwargs.get("process", "")
    try:
        target = _find_window(title, process)
        if target:
            target.minimize()
            return {"success": True, "status": f"minimized {target.title}"}
        return {"success": False, "error": "window not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def maximize_window(**kwargs) -> dict:
    title = kwargs.get("title", "")
    process = kwargs.get("process", "")
    try:
        target = _find_window(title, process)
        if target:
            target.maximize()
            return {"success": True, "status": f"maximized {target.title}"}
        return {"success": False, "error": "window not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def double_click(**kwargs) -> dict:
    try:
        x, y = kwargs.get("x"), kwargs.get("y")
        pyautogui.doubleClick(x, y)
        return {"success": True, "status": f"double-clicked ({x}, {y})"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def right_click(**kwargs) -> dict:
    try:
        x, y = kwargs.get("x"), kwargs.get("y")
        pyautogui.rightClick(x, y)
        return {"success": True, "status": f"right-clicked ({x}, {y})"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def move_mouse(**kwargs) -> dict:
    try:
        x, y = kwargs.get("x"), kwargs.get("y")
        failsafe_was = pyautogui.FAILSAFE
        pyautogui.FAILSAFE = False
        try:
            pyautogui.moveTo(x, y)
        finally:
            pyautogui.FAILSAFE = failsafe_was
        return {"success": True, "status": f"moved to ({x}, {y})"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def drag(**kwargs) -> dict:
    try:
        sx, sy = kwargs.get("start_x"), kwargs.get("start_y")
        ex, ey = kwargs.get("end_x"), kwargs.get("end_y")
        pyautogui.moveTo(sx, sy)
        pyautogui.drag(ex - sx, ey - sy)
        return {"success": True, "status": f"dragged from ({sx},{sy}) to ({ex},{ey})"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def set_volume(**kwargs) -> dict:
    level = kwargs.get("level", 0)
    try:
        from pycaw.pycaw import AudioUtilities
        devices = AudioUtilities.GetSpeakers()
        interface = devices.EndpointVolume
        interface.SetMasterVolumeLevelScalar(max(0, min(1, level / 100)), None)
        return {"success": True, "status": f"volume set to {level}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_process_info(**kwargs) -> dict:
    name = kwargs.get("name", "")
    try:
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status", "create_time"]):
            if name.lower() in p.info["name"].lower():
                procs.append(p.info)
        return {"success": True, "processes": procs[:10], "count": len(procs)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def kill_process(**kwargs) -> dict:
    name = kwargs.get("name", "")
    if not re.match(r"^[a-zA-Z0-9._\-, ]+$", name):
        return {"success": False, "error": f"Invalid process name: {name!r}"}
    try:
        subprocess.run(["taskkill", "/IM", f"{name}.exe", "/F"], capture_output=True, timeout=5)
        return {"success": True, "status": f"killed {name}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def download_file(**kwargs) -> dict:
    url = kwargs.get("url", "")
    path = kwargs.get("path", "")
    try:
        import urllib.request
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        urllib.request.urlretrieve(url, path)
        return {"success": True, "status": f"downloaded to {path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def detect_ui_elements(**kwargs) -> dict:
    try:
        import pytesseract
        from PIL import Image
        region = kwargs.get("region")
        if region:
            img = pyautogui.screenshot(region=(region["left"], region["top"], region["width"], region["height"]))
        else:
            img = pyautogui.screenshot()
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        elements = []
        for i in range(len(data["text"])):
            if data["text"][i].strip():
                elements.append({
                    "text": data["text"][i],
                    "x": data["left"][i], "y": data["top"][i],
                    "w": data["width"][i], "h": data["height"][i],
                })
        return {"success": True, "elements": elements, "count": len(elements)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def update_memory(**kwargs) -> dict:
    from tools.memory import memory
    return memory(action="store", key=kwargs.get("key"), value=kwargs.get("value"))


def summarize_session(**kwargs) -> dict:
    from tools.memory import memory
    return memory(action="summary", limit=kwargs.get("limit", 10))


def get_battery(**kwargs) -> dict:
    try:
        battery = psutil.sensors_battery()
        if battery is None:
            return {"success": True, "battery_percent": None, "plugged_in": None, "status": "No battery detected"}
        return {
            "success": True,
            "battery_percent": round(battery.percent, 1),
            "plugged_in": battery.power_plugged,
            "charging": battery.power_plugged if battery.power_plugged is not None else False,
            "status": f"{battery.percent:.0f}% {'plugged in' if battery.power_plugged else 'on battery'}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def lock_screen(**kwargs) -> dict:
    try:
        import ctypes
        ctypes.windll.user32.LockWorkStation()
        return {"success": True, "status": "screen locked"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def shutdown(**kwargs) -> dict:
    try:
        import ctypes
        # Confirm with user first â€” no silent shutdown
        confirmed = kwargs.get("_confirmed", False)
        if not confirmed:
            return {"success": False, "error": "Shutdown requires explicit user confirmation. Call again with _confirmed=True after asking the user."}
        ctypes.windll.user32.ExitWindowsEx(0x00000001 | 0x00000004, 0)  # EWX_SHUTDOWN | EWX_FORCE
        return {"success": True, "status": "shutting down"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def restart(**kwargs) -> dict:
    try:
        import ctypes
        confirmed = kwargs.get("_confirmed", False)
        if not confirmed:
            return {"success": False, "error": "Restart requires explicit user confirmation. Call again with _confirmed=True after asking the user."}
        ctypes.windll.user32.ExitWindowsEx(0x00000002 | 0x00000004, 0)  # EWX_REBOOT | EWX_FORCE
        return {"success": True, "status": "restarting"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def create_file(**kwargs) -> dict:
    try:
        path = kwargs.get("path", "")
        resolved = _safe_resolve_path(path)
        if not resolved:
            return {"success": False, "error": f"Path not allowed: {path}"}
        os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as f:
            pass
        return {"success": True, "status": f"created {resolved}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def data_analysis(**kwargs) -> dict:
    return _run_code(
        code=kwargs.get("data", "") + "\nimport pandas as pd\n" + kwargs.get("operations", "describe()"),
        language="python",
        timeout=30,
    )


def list_installed_apps(**kwargs) -> dict:
    query = kwargs.get("query", "")
    try:
        db_path = Path(__file__).parent.parent / "indexer" / "db" / "pc_index.db"
        if not db_path.exists():
            return {"success": False, "error": "app index not built yet - try again in a minute"}
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        try:
            if query:
                cur = conn.execute("SELECT name, exe_path, version FROM apps WHERE name LIKE ?", (f"%{query}%",))
            else:
                cur = conn.execute("SELECT name, exe_path, version FROM apps ORDER BY name")
            apps = []
            seen = set()
            for row_name, exe_path, version in cur.fetchall()[:100]:
                resolved = _resolve_exe(exe_path, row_name)
                key = resolved or row_name.lower()
                if key in seen:
                    continue
                seen.add(key)
                apps.append({"name": row_name, "path": resolved or "", "version": version or ""})
        finally:
            conn.close()
        return {"success": True, "apps": apps[:50], "count": len(apps)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def set_brightness(**kwargs) -> dict:
    level = max(0, min(100, int(kwargs.get("level", 50))))
    try:
        subprocess.run(
            ["powershell", "-command",
             f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{level})"],
            capture_output=True, timeout=10
        )
        return {"success": True, "status": f"brightness set to {level}%"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def minimize_all_except(**kwargs) -> dict:
    exclude = [s.lower() for s in kwargs.get("exclude_titles", [])]
    try:
        minimized = 0
        skipped = 0
        for w in gw.getAllWindows():
            title = w.title.strip().lower()
            if not title:
                continue
            if any(excl in title for excl in exclude):
                skipped += 1
                continue
            try:
                w.minimize()
                minimized += 1
            except Exception:
                pass
        return {"success": True, "minimized": minimized, "skipped": skipped, "status": f"minimized {minimized} windows, kept {skipped} open"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def vision_query(**kwargs) -> dict:
    import base64, io
    # Strip hallucinated params not in schema (e.g. LLM sometimes emits "image")
    kwargs = {k: v for k, v in kwargs.items() if k in ("question", "region")}
    question = kwargs.get("question", "")
    region = kwargs.get("region")
    try:
        if region:
            img = pyautogui.screenshot(region=(region["left"], region["top"], region["width"], region["height"]))
        else:
            img = pyautogui.screenshot()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()

        import requests
        from settings import LLM_VISION_MODEL, LLM_BASE_URL, OLLAMA_API_KEY
        payload = {
            "model": LLM_VISION_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a screen analysis assistant. "
                        "When describing element locations, ALWAYS provide exact pixel coordinates (x, y) as numbers. "
                        "For any element the user asks about, return its center coordinates and bounding box "
                        "in this format: center=(x, y), bbox=(left, top, width, height). "
                        "Be precise â€” these coordinates will be used for mouse clicks."
                    ),
                },
                {
                    "role": "user",
                    "content": question,
                    "images": [b64],
                },
            ],
            "stream": False,
        }
        headers = {"Content-Type": "application/json"}
        if OLLAMA_API_KEY:
            headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
        url = LLM_BASE_URL.rstrip("/")
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        if "choices" in data:
            answer = data["choices"][0].get("message", {}).get("content", "")
        else:
            answer = data.get("message", {}).get("content", "")
        return {"success": True, "answer": answer.strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def schedule(**kwargs) -> dict:
    return _schedule(
        action=kwargs.get("action", ""),
        command=kwargs.get("command"),
        when=kwargs.get("when"),
        task_id=kwargs.get("task_id"),
    )


def listen(**kwargs) -> dict:
    return _listen(
        prompt=kwargs.get("prompt"),
        timeout_seconds=kwargs.get("timeout_seconds", 10),
        speak_prompt=kwargs.get("speak_prompt", True),
    )


def time_calendar(**kwargs) -> dict:
    return _time_calendar(
        action=kwargs.get("action", ""),
        subject=kwargs.get("subject", ""),
        start=kwargs.get("start", ""),
        end=kwargs.get("end", ""),
        location=kwargs.get("location", ""),
        body=kwargs.get("body", ""),
        all_day=kwargs.get("all_day", False),
        days=kwargs.get("days", 7),
        date=kwargs.get("date", ""),
    )



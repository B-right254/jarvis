"""
Primitive: execute_code(code, language='python')
Sandboxed subprocess with AST guard, minimal env, and process tree kill.

Background execution
--------------------
Set ``background=True`` to start a long-running task that won't block the tool
loop.  The function returns immediately with a PID.  Use action='check' to poll,
action='wait' to block until done, action='kill' to terminate, or action='list'
to enumerate all tracked processes.

Example (LLM decomposition):
  1. execute_code("search for X", background=True) → {pid: 1234}
  2. execute_code("do unrelated work")
  3. execute_code(action="check", pid=1234) → {status: "done", output: "..."}
  4. Report results to user.
"""

import logging
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

# Windows-only constant for hiding console windows
if sys.platform == "win32":
    CREATE_NO_WINDOW = 0x00080000  # CREATE_NO_WINDOW constant for hiding console windows
else:
    CREATE_NO_WINDOW = 0

from safety.tool_guard import check_imports, get_safe_env
from settings import EXECUTE_CODE_TIMEOUT

logger = logging.getLogger(__name__)

# ── Background process tracking ────────────────────────────────────────────────
# Maps PID → process info.  Thread-safe via _bg_lock.
_bg_processes: dict[int, dict] = {}
_bg_lock = threading.Lock()
_bg_counter = 0


def _bg_register(proc: subprocess.Popen, temp_path: str, code: str, language: str) -> int:
    global _bg_counter
    with _bg_lock:
        _bg_counter += 1
        pid = _bg_counter
        _bg_processes[pid] = {
            "proc": proc,
            "temp_path": temp_path,
            "code": code,
            "language": language,
            "started": __import__("time").time(),
            "done": False,
            "stdout": "",
            "stderr": "",
            "returncode": None,
        }
        return pid


def _bg_unregister(pid: int) -> None:
    with _bg_lock:
        info = _bg_processes.pop(pid, None)
    # Clean up temp file outside the lock to avoid holding it during I/O
    if info and info.get("temp_path"):
        try:
            os.unlink(info["temp_path"])
        except Exception:
            pass


def _bg_get(pid: int) -> dict | None:
    with _bg_lock:
        return _bg_processes.get(pid)



def execute_code(
    code: str = "",
    language: str = "python",
    background: bool = False,
    action: str = "run",
    pid: int = 0,
    timeout: int = 60,
) -> dict:
    """
    Execute Python or PowerShell code, optionally in the background.

    Actions
    -------
    run        Execute *code* (default).  When *background*=True, starts it
               and returns ``{pid, status: "running"}`` immediately.  When
               *background*=False (default), blocks until done.
    check      Poll a background process by *pid*.  Returns current stdout,
               stderr, and whether it's still running.
    wait       Block until a background process finishes (or *timeout* sec).
               Returns full output when done.
    kill       Terminate a background process by *pid*.
    list       Return all tracked background processes with status summary.
    """
    # ── Action dispatch (non-execution actions) ──────────────────────────────
    if action == "list":
        with _bg_lock:
            snapshot = dict(_bg_processes)
        if not snapshot:
            return {"success": True, "processes": [], "count": 0}
        result = []
        for pid, info in snapshot.items():
            p = info["proc"]
            rc = p.poll()
            done = rc is not None
            result.append({
                "pid": pid,
                "running": not done,
                "returncode": rc,
                "elapsed_seconds": round(__import__("time").time() - info["started"], 1),
                "language": info["language"],
                "code_preview": info["code"][:80],
            })
        return {"success": True, "processes": result, "count": len(result)}

    if action in ("check", "wait", "kill"):
        info = _bg_get(pid)
        if not info:
            return {"success": False, "error": f"No tracked background process with pid={pid}"}
        proc = info["proc"]
        rc = proc.poll()
        done = rc is not None

        # Collect output if finished and not yet collected — under lock to avoid races
        if done:
            with _bg_lock:
                info = _bg_processes.get(pid)
                if info is None:
                    return {"success": False, "error": f"No tracked background process with pid={pid}"}
                if info["done"]:
                    done = True
                    rc = info["returncode"]
                else:
                    info["done"] = True
                    info["returncode"] = rc
                    try:
                        info["stdout"], info["stderr"] = proc.communicate(timeout=5)
                    except Exception:
                        pass
                    # Clean up temp file
                    try:
                        os.unlink(info["temp_path"])
                    except Exception:
                        pass
            proc = info["proc"]
            rc = info["returncode"]

        if action == "kill":
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
            _bg_unregister(pid)
            return {"success": True, "action": "kill", "pid": pid}

        if action == "wait" and not done:
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
                info["done"] = True
                info["returncode"] = proc.returncode
                info["stdout"] = stdout
                info["stderr"] = stderr
                done = True
                rc = proc.returncode
                try:
                    os.unlink(info["temp_path"])
                except Exception:
                    pass
            except subprocess.TimeoutExpired:
                return {
                    "success": True,
                    "pid": pid,
                    "status": "still_running",
                    "note": f"Process still running after {timeout}s wait — check again or increase timeout.",
                }
            except Exception as e:
                return {"success": False, "error": str(e)}

        if done:
            _bg_unregister(pid)
            out = info.get("stdout") or ""
            err = info.get("stderr") or ""
            return {
                "success": rc == 0,
                "pid": pid,
                "status": "done",
                "return_code": rc,
                "output": out,
                "error": err or ("" if rc == 0 else f"Exited with code {rc}"),
            }
        else:
            # Still running — return partial output
            return {
                "success": True,
                "pid": pid,
                "status": "running",
                "return_code": None,
                "note": f"Still running ({round(__import__('time').time() - info['started'], 1)}s elapsed). "
                        f"Call action='wait' with pid={pid} to block until done, or action='check' to poll again.",
            }

    # ── Normal / background execution ────────────────────────────────────────
    if not code.strip():
        return {"success": False, "error": "No code provided"}

    if language not in ("python", "powershell"):
        return {
            "success": False,
            "error": f"Unsupported language: {language}. Must be 'python' or 'powershell'."
        }

    # Security check for Python code
    if language == "python":
        allowed, reason = check_imports(code, language)
        if not allowed:
            return {"success": False, "error": f"Security check failed: {reason}"}

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py" if language == "python" else ".ps1",
            delete=False
        ) as f:
            f.write(code)
            temp_path = f.name

        if language == "python":
            cmd = [sys.executable, temp_path]
        else:
            cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", temp_path]

        env = get_safe_env()
        env["PYTHONIOENCODING"] = "utf-8"
        project_root = str(Path(__file__).resolve().parent.parent)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = project_root + (os.pathsep + existing if existing else "")

        if background:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=env,
                creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            bg_pid = _bg_register(proc, temp_path, code, language)
            temp_path = None  # ownership transferred to _bg_register
            return {
                "success": True,
                "pid": bg_pid,
                "status": "running",
                "note": f"Task started in background (local id {bg_pid}). "
                        f"Use execute_code(action='check', pid={bg_pid}) to poll, "
                        f"action='wait' to block until done, or action='kill' to terminate.",
            }

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=EXECUTE_CODE_TIMEOUT,
            env=env,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )

        if result.returncode == 0:
            return {
                "success": True,
                "output": result.stdout,
                "return_code": result.returncode,
            }
        else:
            return {
                "success": False,
                "error": result.stderr or f"Process exited with code {result.returncode}",
                "output": result.stdout,
                "return_code": result.returncode,
            }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"Code execution timed out after {EXECUTE_CODE_TIMEOUT} seconds",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }
    finally:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except Exception:
                pass


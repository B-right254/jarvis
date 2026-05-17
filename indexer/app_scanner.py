"""
Scans Windows registry & Start Menu for installed apps.
Pushes results to async write queue.
"""

import json
import logging
import os
import re
import subprocess
import winreg
from pathlib import Path

from settings import REGISTRY_UNINSTALL_PATHS

logger = logging.getLogger(__name__)


def scan_registry():
    apps = []
    for hive, paths in [
        (winreg.HKEY_LOCAL_MACHINE, REGISTRY_UNINSTALL_PATHS),
        (winreg.HKEY_CURRENT_USER, REGISTRY_UNINSTALL_PATHS),
    ]:
        for reg_path in paths:
            try:
                with winreg.OpenKey(hive, reg_path, 0, winreg.KEY_READ) as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, subkey_name, 0, winreg.KEY_READ) as subkey:
                                name = winreg.QueryValueEx(subkey, "DisplayName")[0]
                                if not name:
                                    continue
                                exe = None
                                try:
                                    exe = winreg.QueryValueEx(subkey, "InstallLocation")[0]
                                except Exception:
                                    pass
                                ver = None
                                try:
                                    ver = winreg.QueryValueEx(subkey, "DisplayVersion")[0]
                                except Exception:
                                    pass
                                pub = None
                                try:
                                    pub = winreg.QueryValueEx(subkey, "Publisher")[0]
                                except Exception:
                                    pass
                                apps.append(
                                    {
                                        "name": name,
                                        "exe_path": exe,
                                        "version": ver,
                                        "publisher": pub,
                                        "source": "registry",
                                    }
                                )
                        except FileNotFoundError:
                            pass
            except (FileNotFoundError, PermissionError):
                pass
    return apps


def _resolve_lnk(lnk_path: Path) -> str:
    """Resolve a .lnk shortcut to its target executable path.
    Falls back to the original path string if win32com is unavailable.
    """
    try:
        import pythoncom
        from win32com.shell import shell

        pythoncom.CoInitialize()
        try:
            shortcut = pythoncom.CoCreateInstance(
                shell.CLSID_ShellLink,
                None,
                pythoncom.CLSCTX_INPROC_SERVER,
                shell.IID_IShellLink,
            )
            shortcut.QueryInterface(pythoncom.IID_IPersistFile).Load(str(lnk_path))
            target, _ = shortcut.GetPath(shell.SLGP_UNCPRIORITY)
            return target if target else str(lnk_path)
        finally:
            pythoncom.CoUninitialize()
    except Exception:
        return str(lnk_path)


def scan_start_menu():
    apps = []
    for base in [
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    ]:
        if not base.exists():
            continue
        for lnk in base.rglob("*.lnk"):
            exe_path = _resolve_lnk(lnk)
            apps.append(
                {
                    "name": lnk.stem,
                    "exe_path": exe_path,
                    "version": None,
                    "publisher": None,
                    "source": "startmenu",
                }
            )
    return apps


def scan_uwp_apps() -> list:
    """Scan UWP/Microsoft Store apps via PowerShell Get-AppxPackage."""
    try:
        ps_cmd = (
            "Get-AppxPackage | Where-Object {$_.IsFramework -eq $false -and "
            "$_.SignatureKind -ne 'None'} | "
            "Select-Object Name, PackageFullName, InstallLocation, Version, Publisher | "
            "ConvertTo-Json -Compress"
        )
        proc = subprocess.run(
            ["powershell", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return []
        data = json.loads(proc.stdout)
        if isinstance(data, dict):
            data = [data]
        apps = []
        for pkg in data:
            name = pkg.get("Name", "")
            if not name:
                continue
            # Format name: Microsoft.WindowsCalculator → Windows Calculator
            display_name = name.split(".")[-1]
            display_name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", display_name)
            apps.append(
                {
                    "name": display_name,
                    "exe_path": pkg.get("InstallLocation", ""),
                    "version": pkg.get("Version", ""),
                    "publisher": str(pkg.get("Publisher", "")),
                    "source": "uwp",
                    "package_name": pkg.get("PackageFullName", ""),
                }
            )
        return apps
    except Exception as e:
        logger.warning(f"UWP scan failed: {e}")
        return []


def scan_apps(writer):
    logger.info("Running app scan...")
    all_apps = scan_registry() + scan_start_menu() + scan_uwp_apps()
    # Deduplicate by normalised name; prefer entries that have a real exe_path
    seen: dict = {}
    for app in all_apps:
        key = re.sub(r"\s+", "", app["name"].lower())
        if key not in seen:
            seen[key] = app
        elif app.get("exe_path") and not seen[key].get("exe_path"):
            seen[key] = app
    deduped = list(seen.values())
    writer.push("apps", deduped)
    logger.info(
        f"App scan pushed {len(deduped)} records (from {len(all_apps)} raw) to queue"
    )

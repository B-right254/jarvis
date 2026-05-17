"""
Safety Policy Audit - Simulate LLM-generated code for Windows tasks
Tests for false positives that would block legitimate non-harmful code
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safety.tool_guard import check_imports, check_paths
from safety.plan_validator import validate
from settings import ALLOWED_IMPORTS

print("=" * 80)
print("SAFETY POLICY AUDIT - FALSE POSITIVE DETECTION")
print("=" * 80)

# Test cases: (description, code, language, should_pass)
test_cases = [
    # === PYTHON TESTS ===
    
    # 1. Basic file operations (should pass)
    ("Python: Create directory", 
     "import os\nos.makedirs('C:/Users/Test/Documents/new_folder', exist_ok=True)",
     "python", True),
    
    # 2. File reading (should pass)
    ("Python: Read file",
     "with open('C:/Users/Test/Documents/file.txt', 'r') as f:\n    content = f.read()\n    print(content)",
     "python", True),
    
    # 3. File writing (should pass)
    ("Python: Write file",
     "with open('C:/Users/Test/Documents/output.txt', 'w') as f:\n    f.write('Hello World')",
     "python", True),
    
    # 4. List directory contents (should pass)
    ("Python: List directory",
     "import os\nfiles = os.listdir('C:/Users/Test/Documents')\nprint(files)",
     "python", True),
    
    # 5. Move file (should pass)
    ("Python: Move file",
     "import shutil\nshutil.move('C:/Users/Test/Documents/old.txt', 'C:/Users/Test/Documents/new.txt')",
     "python", True),
    
    # 6. Copy file (should pass)
    ("Python: Copy file",
     "import shutil\nshutil.copy('C:/Users/Test/Documents/source.txt', 'C:/Users/Test/Documents/dest.txt')",
     "python", True),
    
    # 7. Get system info (should pass)
    ("Python: System info",
     "import platform\nprint(platform.system())\nprint(platform.version())",
     "python", True),
    
    # 8. Check running processes (should pass)
    ("Python: List processes",
     "import psutil\nfor proc in psutil.processes(['pid', 'name']):\n    print(proc)",
     "python", True),
    
    # 9. Network request (should pass)
    ("Python: HTTP request",
     "import requests\nresponse = requests.get('https://api.example.com/data')\nprint(response.json())",
     "python", True),
    
    # 10. JSON parsing (should pass)
    ("Python: JSON parse",
     "import json\ndata = json.loads('{\"key\": \"value\"}')\nprint(data)",
     "python", True),
    
    # 11. Regex operations (should pass)
    ("Python: Regex",
     "import re\npattern = r'\\d+'\nmatches = re.findall(pattern, 'abc123def456')\nprint(matches)",
     "python", True),
    
    # 12. DateTime operations (should pass)
    ("Python: DateTime",
     "from datetime import datetime\nnow = datetime.now()\nprint(now.strftime('%Y-%m-%d'))",
     "python", True),
    
    # 13. Subprocess - safe command (should pass)
    ("Python: Subprocess dir",
     "import subprocess\nresult = subprocess.run(['dir'], shell=True, capture_output=True, text=True)\nprint(result.stdout)",
     "python", True),
    
    # 14. Subprocess - Python version (should pass)
    ("Python: Subprocess python --version",
     "import subprocess\nresult = subprocess.run(['python', '--version'], capture_output=True, text=True)\nprint(result.stdout)",
     "python", True),
    
    # 15. Threading (should pass)
    ("Python: Threading",
     "import threading\ndef worker():\n    print('Working')\nt = threading.Thread(target=worker)\nt.start()",
     "python", True),
    
    # 16. SQLite database (should pass)
    ("Python: SQLite",
     "import sqlite3\nconn = sqlite3.connect('test.db')\ncursor = conn.cursor()\ncursor.execute('CREATE TABLE IF NOT EXISTS test (id INTEGER)')\nconn.commit()",
     "python", True),
    
    # 17. Hashlib (should pass)
    ("Python: Hashlib",
     "import hashlib\nhash = hashlib.sha256(b'data').hexdigest()\nprint(hash)",
     "python", True),
    
    # 18. Base64 encoding (should pass)
    ("Python: Base64",
     "import base64\nencoded = base64.b64encode(b'data')\nprint(encoded)",
     "python", True),
    
    # 19. Win32 GUI - get window title (should pass)
    ("Python: Win32GUI window list",
     "import win32gui\nwindows = []\ndef callback(hwnd, windows):\n    if win32gui.IsWindowVisible(hwnd):\n        windows.append(win32gui.GetWindowText(hwnd))\n    return True\nwin32gui.EnumWindows(callback, windows)\nprint(windows)",
     "python", True),
    
    # 20. Win32 API - send key (should pass)
    ("Python: Win32API SendKey",
     "import win32api\nimport win32con\nwin32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)\nwin32api.keybd_event(ord('C'), 0, 0, 0)",
     "python", True),
    
    # 21. PyAutoGUI screenshot region (should pass)
    ("Python: PyAutoGUI screenshot",
     "import pyautogui\nscreenshot = pyautogui.screenshot(region=(0, 0, 100, 100))\nscreenshot.save('test.png')",
     "python", True),
    
    # 22. PIL image processing (should pass)
    ("Python: PIL image",
     "from PIL import Image\nimg = Image.open('test.jpg')\nimg.rotate(90).save('rotated.jpg')",
     "python", True),
    
    # 23. Temp file cleanup (SHOULD PASS - temp context)
    ("Python: Temp cleanup with tempfile",
     "import tempfile\nimport shutil\ntemp_dir = tempfile.gettempdir()\nshutil.rmtree(temp_dir + '/cache', ignore_errors=True)",
     "python", True),
    
    # 24. Clear user temp folder (SHOULD PASS - temp context)
    ("Python: Clear %TEMP% folder",
     "import os\nimport shutil\ntemp = os.environ.get('TEMP', '')\nif temp:\n    for item in os.listdir(temp):\n        path = os.path.join(temp, item)\n        if os.path.isdir(path):\n            shutil.rmtree(path, ignore_errors=True)",
     "python", True),
    
    # 25. Windows Registry READ (should pass - read only)
    ("Python: RegQueryValue",
     "import winreg\nkey = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Software\\\\Microsoft\\\\Windows\\\\CurrentVersion')\nvalue = winreg.QueryValueEx(key, 'ThemePath')\nprint(value)",
     "python", True),
    
    # 26. ctypes - MessageBox (should pass)
    ("Python: ctypes MessageBox",
     "import ctypes\nctypes.windll.user32.MessageBoxW(0, 'Hello', 'Title', 1)",
     "python", True),
    
    # 27. socket - get hostname (should pass)
    ("Python: socket hostname",
     "import socket\nhostname = socket.gethostname()\nprint(hostname)",
     "python", True),
    
    # 28. urllib - URL parse (should pass)
    ("Python: urllib parse",
     "from urllib.parse import urlparse\nparsed = urlparse('https://example.com/path')\nprint(parsed)",
     "python", True),
    
    # 29. Logging (should pass)
    ("Python: logging",
     "import logging\nlogging.basicConfig(level=logging.INFO)\nlogger = logging.getLogger(__name__)\nlogger.info('Test message')",
     "python", True),
    
    # 30. Collections - Counter (should pass)
    ("Python: collections Counter",
     "from collections import Counter\ncounts = Counter(['a', 'b', 'a', 'c'])\nprint(counts)",
     "python", True),
    
    # === POWERSHELL TESTS ===
    
    # 31. PS: Get files (should pass)
    ("PowerShell: Get-ChildItem",
     "Get-ChildItem -Path C:\\Users\\Test\\Documents",
     "powershell", True),
    
    # 32. PS: Copy file (should pass)
    ("PowerShell: Copy-Item",
     "Copy-Item -Path 'C:\\Users\\Test\\file.txt' -Destination 'C:\\Users\\Test\\backup.txt'",
     "powershell", True),
    
    # 33. PS: Move file (should pass)
    ("PowerShell: Move-Item",
     "Move-Item -Path 'C:\\Users\\Test\\old.txt' -Destination 'C:\\Users\\Test\\new.txt'",
     "powershell", True),
    
    # 34. PS: Create directory (should pass)
    ("PowerShell: New-Item directory",
     "New-Item -Path 'C:\\Users\\Test\\Documents\\new_folder' -ItemType Directory",
     "powershell", True),
    
    # 35. PS: Read file content (should pass)
    ("PowerShell: Get-Content",
     "Get-Content -Path 'C:\\Users\\Test\\file.txt'",
     "powershell", True),
    
    # 36. PS: Write file (should pass)
    ("PowerShell: Set-Content",
     "Set-Content -Path 'C:\\Users\\Test\\output.txt' -Value 'Hello World'",
     "powershell", True),
    
    # 37. PS: Get process list (should pass)
    ("PowerShell: Get-Process",
     "Get-Process | Select-Object Name, Id",
     "powershell", True),
    
    # 38. PS: Get service status (should pass)
    ("PowerShell: Get-Service",
     "Get-Service -Name Spooler",
     "powershell", True),
    
    # 39. PS: Get event log (should pass)
    ("PowerShell: Get-EventLog",
     "Get-EventLog -LogName Application -Newest 10",
     "powershell", True),
    
    # 40. PS: Select string (should pass)
    ("PowerShell: Select-String",
     "Select-String -Path 'C:\\Users\\Test\\file.txt' -Pattern 'error'",
     "powershell", True),
    
    # 41. PS: Where filter (should pass)
    ("PowerShell: Where-Object filter",
     "Get-Process | Where-Object { $_.CPU -gt 10 }",
     "powershell", True),
    
    # 42. PS: ForEach loop (should pass)
    ("PowerShell: ForEach-Object",
     "Get-ChildItem | ForEach-Object { Write-Host $_.Name }",
     "powershell", True),
    
    # 43. PS: Invoke WebRequest (should pass)
    ("PowerShell: Invoke-WebRequest",
     "Invoke-WebRequest -Uri 'https://api.example.com/data' -OutFile 'data.json'",
     "powershell", True),
    
    # 44. PS: Convert to JSON (should pass)
    ("PowerShell: ConvertTo-Json",
     "$data = @{Name='Test'; Value=123}\n$data | ConvertTo-Json",
     "powershell", True),
    
    # 45. PS: Import CSV (should pass)
    ("PowerShell: Import-Csv",
     "Import-Csv -Path 'C:\\Users\\Test\\data.csv'",
     "powershell", True),
    
    # 46. PS: Export CSV (should pass)
    ("PowerShell: Export-Csv",
     "$data | Export-Csv -Path 'C:\\Users\\Test\\output.csv' -NoTypeInformation",
     "powershell", True),
    
    # 47. PS: Clear recycle bin (SHOULD PASS - recycle context)
    ("PowerShell: Clear RecycleBin",
     "Clear-RecycleBin -Force",
     "powershell", True),
    
    # 48. PS: Get disk info (should pass)
    ("PowerShell: Get-Volume",
     "Get-Volume | Select-Object DriveLetter, SizeRemaining",
     "powershell", True),
    
    # 49. PS: Get network config (should pass)
    ("PowerShell: Get-NetIPAddress",
     "Get-NetIPAddress | Where-Object AddressFamily -eq IPv4",
     "powershell", True),
    
    # 50. PS: Test connection (should pass)
    ("PowerShell: Test-Connection",
     "Test-Connection -ComputerName google.com -Count 2",
     "powershell", True),
    
    # === EDGE CASES THAT SHOULD PASS ===
    
    # 51. Delete specific file by name (NOT recursive, should pass)
    ("Python: Delete single file",
     "import os\nos.remove('C:/Users/Test/Documents/old_file.txt')",
     "python", True),
    
    # 52. Remove empty directory (should pass)
    ("Python: Remove empty dir",
     "import os\nos.rmdir('C:/Users/Test/Documents/empty_folder')",
     "python", True),
    
    # 53. Rename file (should pass)
    ("Python: Rename file",
     "import os\nos.rename('C:/Users/Test/Documents/old.txt', 'C:/Users/Test/Documents/new.txt')",
     "python", True),
    
    # 54. Get file stats (should pass)
    ("Python: Get file stats",
     "import os\nstats = os.stat('C:/Users/Test/Documents/file.txt')\nprint(stats.st_size)",
     "python", True),
    
    # 55. Path manipulation (should pass)
    ("Python: pathlib operations",
     "from pathlib import Path\np = Path('C:/Users/Test/Documents')\nprint(p.exists())",
     "python", True),
]

# Track results
passed = 0
failed = 0
false_positives = []

print(f"\nRunning {len(test_cases)} test cases...\n")
print("-" * 80)

for desc, code, lang, should_pass in test_cases:
    # Test 1: Import check (for Python)
    import_ok = True
    import_reason = ""
    if lang == "python":
        import_ok, import_reason = check_imports(code)
    
    # Test 2: Path check
    args = {"code": code, "language": lang}
    path_ok, path_reason = check_paths(args)
    
    # Test 3: Plan validator
    plan = {"code": code, "language": lang}
    plan_ok, plan_reason = validate(plan)
    
    # Determine overall result
    overall_pass = import_ok and path_ok and plan_ok
    
    if overall_pass == should_pass:
        status = "✅ PASS"
        passed += 1
    else:
        status = "❌ FAIL (False Positive)"
        failed += 1
        false_positives.append({
            "desc": desc,
            "code": code[:100],
            "lang": lang,
            "import_ok": import_ok,
            "import_reason": import_reason,
            "path_ok": path_ok,
            "path_reason": path_reason,
            "plan_ok": plan_ok,
            "plan_reason": plan_reason
        })
    
    print(f"{status}: {desc}")
    if overall_pass != should_pass:
        if not import_ok:
            print(f"       └─ Import blocked: {import_reason}")
        if not path_ok:
            print(f"       └─ Path blocked: {path_reason}")
        if not plan_ok:
            print(f"       └─ Plan blocked: {plan_reason}")

print("-" * 80)
print(f"\nRESULTS: {passed}/{len(test_cases)} passed, {failed} false positives detected")

if false_positives:
    print("\n" + "=" * 80)
    print("FALSE POSITIVES FOUND - NEEDS FIXING:")
    print("=" * 80)
    for i, fp in enumerate(false_positives, 1):
        print(f"\n{i}. {fp['desc']}")
        print(f"   Language: {fp['lang']}")
        print(f"   Code snippet: {fp['code']}...")
        if not fp['import_ok']:
            print(f"   ❌ Import check failed: {fp['import_reason']}")
        if not fp['path_ok']:
            print(f"   ❌ Path check failed: {fp['path_reason']}")
        if not fp['plan_ok']:
            print(f"   ❌ Plan validator failed: {fp['plan_reason']}")
    
    print("\n" + "=" * 80)
    print("RECOMMENDATION: Fix these false positives before deployment")
    print("=" * 80)
    if __name__ == "__main__":
        sys.exit(1)
else:
    print("\n✅ ALL TESTS PASSED - No false positives detected!")
    if __name__ == "__main__":
        sys.exit(0)



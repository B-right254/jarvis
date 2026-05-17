"""
Verify that genuinely DANGEROUS code is still properly blocked
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from safety.tool_guard import check_imports, check_paths
from safety.plan_validator import validate

print("=" * 80)
print("SAFETY POLICY AUDIT - DANGEROUS CODE BLOCKING VERIFICATION")
print("=" * 80)

# Test cases: (description, code, language, should_block)
dangerous_tests = [
    # === SHOULD BE BLOCKED ===
    
    # 1. rm -rf equivalent
    ("BLOCK: rm -rf", "import subprocess\nsubprocess.run(['rm', '-rf', '/'])", "python", True),
    
    # 2. del /s command
    ("BLOCK: del /s", "import subprocess\nsubprocess.run('del /s /q C:\\\\*.*', shell=True)", "python", True),
    
    # 3. rd /s command
    ("BLOCK: rd /s", "import subprocess\nsubprocess.run('rd /s /q C:\\\\Users', shell=True)", "python", True),
    
    # 4. Format disk
    ("BLOCK: format C:", "import subprocess\nsubprocess.run('format C: /y', shell=True)", "python", True),
    
    # 5. Shutdown command
    ("BLOCK: shutdown", "import subprocess\nsubprocess.run('shutdown /s /t 0', shell=True)", "python", True),
    
    # 6. Registry delete
    ("BLOCK: reg delete", "import subprocess\nsubprocess.run('reg delete HKLM\\\\SOFTWARE /f', shell=True)", "python", True),
    
    # 7. diskpart
    ("BLOCK: diskpart", "import subprocess\nsubprocess.run('diskpart /s script.txt', shell=True)", "python", True),
    
    # 8. bcdedit
    ("BLOCK: bcdedit", "import subprocess\nsubprocess.run('bcdedit /delete {current}', shell=True)", "python", True),
    
    # 9. cipher wipe
    ("BLOCK: cipher /w", "import subprocess\nsubprocess.run('cipher /w:C:\\\\', shell=True)", "python", True),
    
    # 10. shutil.rmtree without temp context
    ("BLOCK: shutil.rmtree system dir", "import shutil\nshutil.rmtree('C:\\\\Users\\\\Documents')", "python", True),
    
    # 11. Blocked path - System32
    ("BLOCK: System32 path", "{'path': 'C:/Windows/System32/drivers'}", "python", True),
    
    # 12. Blocked path - SSH keys
    ("BLOCK: SSH key path", "{'file': 'C:/Users/Test/.ssh/id_rsa'}", "python", True),
    
    # 13. Blocked path - AWS credentials
    ("BLOCK: AWS credentials", "{'path': 'C:/Users/Test/.aws/credentials'}", "python", True),
    
    # 14. PowerShell Remove-Item recursive
    ("BLOCK: PS Remove-Item -Recurse system", "Remove-Item -Path 'C:\\\\Program Files' -Recurse -Force", "powershell", True),
    
    # 15. PowerShell format
    ("BLOCK: PS format", "Format-Volume -DriveLetter C", "powershell", True),
    
    # 16. PowerShell shutdown
    ("BLOCK: PS shutdown", "Stop-Computer -Force", "powershell", True),
    
    # 17. Disallowed import - ctypes should be allowed now
    ("PASS: ctypes allowed", "import ctypes\nctypes.windll.user32.MessageBoxW(0, 'Hi', 'Title', 0)", "python", False),
    
    # 18. os.rmdir on non-temp (should PASS - single dir removal is safe)
    ("PASS: os.rmdir single dir", "import os\nos.rmdir('C:/Users/Test/Documents/empty_folder')", "python", False),
    
    # 19. shutil.rmtree with temp context (should PASS)
    ("PASS: shutil.rmtree temp", "import shutil\nimport tempfile\ntemp = tempfile.gettempdir()\nshutil.rmtree(temp + '/cache', ignore_errors=True)", "python", False),
]

passed = 0
failed = 0

print(f"\nRunning {len(dangerous_tests)} verification tests...\n")
print("-" * 80)

for desc, code, lang, should_block in dangerous_tests:
    import_ok, import_reason = check_imports(code) if lang == "python" else (True, "")
    path_ok, path_reason = check_paths({"code": code, "language": lang})
    plan_ok, plan_reason = validate({"code": code, "language": lang})
    
    overall_blocked = not (import_ok and path_ok and plan_ok)
    
    if overall_blocked == should_block:
        status = "✅ CORRECT"
        passed += 1
        action = "blocked" if should_block else "allowed"
        print(f"{status}: {desc} (correctly {action})")
    else:
        status = "❌ WRONG"
        failed += 1
        expected = "BLOCKED" if should_block else "ALLOWED"
        actual = "BLOCKED" if overall_blocked else "ALLOWED"
        print(f"{status}: {desc}")
        print(f"       Expected: {expected}, Got: {actual}")
        if not import_ok:
            print(f"       └─ Import: {import_reason}")
        if not path_ok:
            print(f"       └─ Path: {path_reason}")
        if not plan_ok:
            print(f"       └─ Plan: {plan_reason}")

print("-" * 80)
print(f"\nRESULTS: {passed}/{len(dangerous_tests)} correct")

if failed > 0:
    print(f"\n❌ {failed} VERIFICATION FAILURES - Safety policies need adjustment!")
    if __name__ == "__main__":
        sys.exit(1)
else:
    print("\n✅ ALL VERIFICATION TESTS PASSED!")
    print("\nSafety policies correctly:")
    print("  • Block genuinely dangerous operations (rm -rf, format, shutdown, etc.)")
    print("  • Allow legitimate non-harmful code (file ops, system queries, etc.)")
    print("  • Permit temp/cache cleanup when context is clear")
    if __name__ == "__main__":
        sys.exit(0)

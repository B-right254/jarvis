
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tools.system import execute_code

code = """import subprocess, time, os, sys
# Launch Notepad
subprocess.Popen(['notepad.exe'])
# Give it a moment to start
time.sleep(2)
print('Notepad launched')"""

print("Testing execute_code...")
result = execute_code(code=code, language="python")
print("execute_code result:", result)

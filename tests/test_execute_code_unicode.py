"""
Diagnostic test: unicode/emoji encoding in execute_code.

Root cause of loop-burning behavior:
  The LLM prints emoji characters (✅ \u2705, ❌ \u274c) in generated code as instructed
  by the system prompt.  subprocess.run(capture_output=True, text=True) on Windows decodes
  stdout with the system ANSI code page (cp1252), which CANNOT represent these characters.
  The child process crashes with UnicodeEncodeError on every first attempt, triggering
  the recovery retry loop (3 retries × ~5s each = ~15s delay per failed command).

The fix: set PYTHONIOENCODING=utf-8 in the subprocess env and encoding='utf-8' in run().
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.system import execute_code


def test_unicode_print_succeeds():
    """Code with emoji/unicode in print statements must not crash."""
    code = "print('hello world')"
    r = execute_code(code)
    assert r["success"], f"Basic print failed: {r.get('error')}"
    assert "hello world" in r["output"]


def test_unicode_emoji_succeeds():
    """The exact pattern the LLM generates: print('✅ ...') — must work."""
    code = "print('\\u2705 Notepad launched successfully.')"
    r = execute_code(code)
    if not r["success"]:
        print(f"DIAGNOSTIC: emoji print FAILED — {r.get('error')}")
        print("This is the root cause of the retry loop.")
        print("Fix: add PYTHONIOENCODING=utf-8 to subprocess env")
        print("  and encoding='utf-8' to subprocess.run()")
    assert r["success"], (
        f"Emoji print crashed: {r.get('error')}\n"
        f"  This causes the agent to burn through recovery retries."
    )
    assert "\u2705" in r["output"], (
        f"Emoji character missing from output: {r['output']!r}"
    )


def test_unicode_emoji_and_text_succeeds():
    """Full pattern: emoji + message + variable content."""
    code = (
        "name = 'Notepad'\n"
        "print('\\u2705 ' + name + ' launched successfully.')\n"
    )
    r = execute_code(code)
    assert r["success"], f"Emoji + text crashed: {r.get('error')}"
    assert "\u2705 Notepad launched" in r["output"]


def test_unicode_x_emoji_succeeds():
    """The cross-mark emoji (❌) also used by the LLM."""
    code = "print('\\u274c Failed to launch')"
    r = execute_code(code)
    assert r["success"], f"Cross-mark emoji crashed: {r.get('error')}"
    assert "\u274c Failed to launch" in r["output"]


def test_unicode_japanese_succeeds():
    """Non-ASCII Unicode beyond the Basic Multilingual Plane."""
    code = "print('\\u3053\\u3093\\u306b\\u3061\\u306f')"  # konnichiwa
    r = execute_code(code)
    assert r["success"], f"Japanese text crashed: {r.get('error')}"
    assert "こんにちは" in r["output"]


if __name__ == "__main__":
    print("=" * 60)
    print("DIAGNOSTIC: execute_code unicode/emoji encoding")
    print("=" * 60)
    tests = [
        ("Basic ascii print", test_unicode_print_succeeds),
        ("Emoji checkmark", test_unicode_emoji_succeeds),
        ("Emoji + text interpolation", test_unicode_emoji_and_text_succeeds),
        ("Emoji cross-mark", test_unicode_x_emoji_succeeds),
        ("Japanese Unicode", test_unicode_japanese_succeeds),
    ]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            print(f"  FAIL  {name}")
            print(f"        {e}")
            failures += 1
    print()
    if failures:
        print(f"RESULT: {failures}/{len(tests)} tests FAILED")
        print("Root cause: subprocess stdout encoding mismatch")
        if __name__ == "__main__":
            sys.exit(1)
    else:
        print("RESULT: All tests PASSED - unicode/emoji encoding is working")

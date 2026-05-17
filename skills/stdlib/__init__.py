"""
skills.stdlib — Standard Library Skills
========================================
Pre-written, audited Python modules the LLM imports inside execute_code
for operations that require non-trivial integration code.

The LLM can write simple Python/PowerShell directly via execute_code for
file ops, web fetching, process management, system settings, etc.

Modules
-------
system      volume_mute_then_set, brightness_set_robust
messaging   send_email, send_telegram
"""

# Manifest — used by prompt_builder to inject docs into the system prompt.
STDLIB_MANIFEST = {
    "system": {
        "module": "skills.stdlib.system",
        "functions": ["volume_mute_then_set", "brightness_set_robust"],
        "summary": "volume control with pycaw/keypress fallback, brightness control with WMI/keypress fallback",
    },
    "messaging": {
        "module": "skills.stdlib.messaging",
        "functions": ["send_email", "send_telegram"],
        "summary": "send email (SMTP) or Telegram message",
    },
}

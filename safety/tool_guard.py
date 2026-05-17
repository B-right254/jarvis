"""
AST-based import allowlist + environment stripping. Replaces string denylist.
"""

import ast
import logging
import os
import sys

from settings import ALLOWED_IMPORTS, BLOCKED_PATHS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sensitive path fragments checked by check_paths() in addition to the
# settings-driven BLOCKED_PATHS list.  These cover SSH keys, cloud-provider
# credential directories, and common standalone credential files.
# ---------------------------------------------------------------------------
_SENSITIVE_PATH_FRAGMENTS = (
    ".ssh",
    ".aws",
    ".gnupg",
    ".gpg",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
    "authorized_keys",
    "known_hosts",
    "credentials",
    ".netrc",
    ".pgpass",
    ".kube/config",
    "kubeconfig",
)

# ---------------------------------------------------------------------------
# Secret-bearing environment variable keywords.
# A variable is stripped from the safe env when its upper-cased name either
# *is* one of these keywords exactly, or *ends with* "_<keyword>" — so that
# real-world names like GITHUB_TOKEN, OPENAI_API_KEY, or DB_PASSWORD are all
# caught without risking false positives on common system variables.
# ---------------------------------------------------------------------------
_SECRET_KEYWORDS = frozenset(
    {
        "PASSWORD",
        "PASSWD",
        "SECRET",
        "API_KEY",
        "ACCESS_KEY",
        "PRIVATE_KEY",
        "TOKEN",
        "ACCESS_TOKEN",
        "AUTH_TOKEN",
        "CREDENTIAL",
        "CREDENTIALS",
        "KEY",
    }
)


def _is_secret_env_key(key: str) -> bool:
    """Return True if *key* looks like it holds a secret value."""
    upper = key.upper()
    # Exact match preserves the original behaviour.
    if upper in _SECRET_KEYWORDS:
        return True
    # Suffix match catches GITHUB_TOKEN, OPENAI_API_KEY, DB_PASSWORD, etc.
    for kw in _SECRET_KEYWORDS:
        if upper.endswith("_" + kw):
            return True
    return False


def check_imports(code: str, language: str = "python"):
    if language != "python":
        return True, ""
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name.split(".")[0]
                    if mod not in ALLOWED_IMPORTS:
                        return False, f"Import not allowed: {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    return False, "Relative imports are not allowed"
                mod = node.module.split(".")[0]
                if mod not in ALLOWED_IMPORTS:
                    return False, f"Import not allowed: {node.module}"
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    if func.id in ("exec", "eval", "compile", "__import__"):
                        return False, f"{func.id}() not allowed"
                elif isinstance(func, ast.Attribute):
                    if func.attr in ("exec", "eval", "compile", "__import__", "import_module", "exec_module"):
                        return False, f"{func.attr}() not allowed"
                elif isinstance(func, ast.Subscript):
                    return False, "Dynamic function call via subscript is not allowed"
        return True, ""
    except SyntaxError as e:
        return False, f"Syntax error: {e}"


def _resolve_short_paths(args_str: str) -> str:
    """Resolve any Windows 8.3 short-path names to their full paths."""
    if sys.platform != "win32":
        return args_str
    import ctypes
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_unicode_buffer(260)
    parts = args_str.replace("/", "\\").split("\\")
    resolved = []
    for part in parts:
        if "~" in part and len(part) > 2:
            ret = kernel32.GetLongPathNameW(part, buf, 260)
            if ret and ret <= 260:
                resolved.append(buf.value.lower())
                continue
        resolved.append(part.lower())
    return "\\".join(resolved)


def check_paths(args: dict):
    """
    Reject tool calls whose arguments reference a blocked or sensitive path.

    Two layers of checks are applied:
      1. Settings-driven BLOCKED_PATHS (system directories such as System32).
      2. Hardcoded _SENSITIVE_PATH_FRAGMENTS (.ssh, .aws, credential files,
         etc.) that must never be accessible regardless of settings.

    Windows 8.3 short-path names (e.g. WINDO~1) are resolved first.
    """
    args_str = str(args).replace("\\", "/")
    # Resolve short-path names on Windows
    args_str_lower = _resolve_short_paths(str(args)).replace("\\", "/")

    # 1. Settings-driven blocked paths (system directories, etc.)
    for path in BLOCKED_PATHS:
        if path.lower().replace("\\", "/") in args_str_lower:
            return False, f"Blocked path in args: '{path}'"

    # 2. Hardcoded sensitive path fragments (SSH keys, cloud credentials, …)
    for fragment in _SENSITIVE_PATH_FRAGMENTS:
        if fragment.lower() in args_str_lower:
            return False, f"Blocked sensitive path in args: '{fragment}'"

    return True, ""


def get_safe_env() -> dict:
    """
    Return a sanitised copy of the current environment suitable for passing to
    subprocesses.

    The full original PATH is preserved so that tools installed by the user
    (winget, git, npm, pipx applications, etc.) remain reachable.  Only
    environment variables whose names indicate they hold secrets — passwords,
    API keys, tokens, private keys, etc. — are removed.
    """
    env = os.environ.copy()

    stripped = []
    for key in list(env.keys()):
        if _is_secret_env_key(key):
            del env[key]
            stripped.append(key)

    if stripped:
        logger.debug(
            "get_safe_env: stripped %d secret env var(s): %s", len(stripped), stripped
        )

    return env

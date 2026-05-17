"""
JARVIS — Single Source of Truth Configuration
All paths, thresholds, timeouts, model names, and caps.
Loads from .env file with sensible defaults.
Nothing hardcoded in module files.
"""

import os
import threading
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file
BASE_DIR = Path(__file__).parent
load_dotenv(dotenv_path=BASE_DIR / ".env")


def get_env_str(key: str, default: str = "") -> str:
    val = os.getenv(key, default).strip()
    return val if val else default


def get_env_int(key: str, default: int = 0) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def get_env_float(key: str, default: float = 0.0) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def get_env_bool(key: str, default: bool = False) -> bool:
    val = os.getenv(key, str(default)).lower().strip()
    return val in ("true", "1", "yes", "on")


# ── Paths ──────────────────────────────────────────────
DATA_DIR = BASE_DIR / get_env_str("DATA_DIR", "data")
LOGS_DIR = BASE_DIR / get_env_str("LOG_DIR", "logs")
SKILLS_DB = BASE_DIR / "skills" / "db" / "skills.db"
SKILLS_CHROMA = BASE_DIR / "skills" / "db" / "chroma"
PC_INDEX_DB = BASE_DIR / "indexer" / "db" / "pc_index.db"
MEMORY_DB = BASE_DIR / "memory" / "db" / "memory.db"
NOTES_DIR = BASE_DIR / get_env_str("NOTES_DIR", "notes")
REMINDERS_DIR = BASE_DIR / get_env_str("REMINDERS_DIR", "reminders")
CONFIG_DIR = BASE_DIR / get_env_str("CONFIG_DIR", "config")

# ── LLM & Context Budget ───────────────────────────────
LLM_MODEL = get_env_str("OLLAMA_MODEL", "gpt-oss:120b-cloud")
EXECUTOR_MODEL = get_env_str("EXECUTOR_MODEL", "nemotron-3-nano:30b-cloud")
LLM_VISION_MODEL = get_env_str("OLLAMA_VISION_MODEL", "gemma3:27b-cloud")
LLM_BASE_URL = get_env_str("OLLAMA_CLOUD_URL", "https://api.ollama.com/api/chat")
OLLAMA_LOCAL_URL = get_env_str("OLLAMA_LOCAL_URL", "http://localhost:11434")
OLLAMA_LOCAL_MODEL = get_env_str("OLLAMA_LOCAL_MODEL", "llama3")
OLLAMA_API_KEY = get_env_str("OLLAMA_API_KEY", "")
OLLAMA_MODE = get_env_str("OLLAMA_MODE", "auto")
OLLAMA_TEMPERATURE = get_env_float("OLLAMA_TEMPERATURE", 0.7)
# gpt-oss:120b has a 128K (131 072 token) context window.
# 512 / 6000 were tuned for small local models — raise both for the 120B cloud model.
# Override in .env if you want tighter cost control:
#   MAX_CONTEXT_TOKENS=16000   # keeps history shorter → cheaper per call
#   OLLAMA_MAX_TOKENS=1024     # shorter replies → cheaper per call
OLLAMA_MAX_TOKENS = get_env_int("OLLAMA_MAX_TOKENS", 8192)  # raised: reasoning model needs headroom
AGENT_MAX_TOKENS = get_env_int("AGENT_MAX_TOKENS", 8192)  # was 4096
LLM_TIMEOUT = get_env_int("OLLAMA_TIMEOUT", 180)  # longer for big model
OLLAMA_MAX_RETRIES = get_env_int("OLLAMA_MAX_RETRIES", 3)
MAX_CONTEXT_TOKENS = get_env_int(
    "MAX_CONTEXT_TOKENS", 100000
)  # raised from 64000 — gpt-oss has 128K, use more of it

# ── gpt-oss 120b Thinking / Reasoning ─────────────────────────────────────────
# think=True enables chain-of-thought reasoning inside the model before it
# responds.  Dramatically improves multi-step planning and complex tasks.
# thinking_budget controls max tokens spent thinking (separate from output).
# reasoning_effort: "low" (fast) | "medium" (balanced) | "high" (best quality).
THINKING_ENABLED = get_env_bool("THINKING_ENABLED", True)
THINKING_BUDGET = get_env_int("THINKING_BUDGET", 8000)
REASONING_EFFORT = get_env_str("REASONING_EFFORT", "medium")
# 0 = send every tool schema on each LLM call (recommended for cloud models).
# Set e.g. 8 when using a small local model with tight context.
LLM_TOOL_SCHEMA_LIMIT = get_env_int("LLM_TOOL_SCHEMA_LIMIT", 0)
# User/assistant/tool messages merged before the current turn in the ReAct loop.
TOOL_LOOP_HISTORY_MESSAGES = get_env_int("TOOL_LOOP_HISTORY_MESSAGES", 24)
MAX_SCREENSHOTS_IN_CONTEXT = get_env_int("MAX_SCREENSHOTS_IN_CONTEXT", 0)
VISION_TO_TEXT_MODE = get_env_bool("VISION_TO_TEXT_MODE", True)

# ── Iteration & Mode Caps (Cloud-Optimized) ────────────────
# Read from .env with explicit type conversion
_max_rounds = get_env_int("MAX_AGENT_ROUNDS", 10)
ITERATION_CAPS = {
    "interactive_cloud": _max_rounds,
    "interactive_local": _max_rounds + 2,
    "autonomous_cloud": max(4, _max_rounds - 2),
    "autonomous_local": _max_rounds,
}

# ── Risk Classification (single source of truth) ──────
HIGH_RISK_TOOLS = frozenset({
    "delete_file",
    "execute_code",
    "shutdown",
    "restart",
    "kill_process",
    "write_file",
    "move_file",
    "run_python",
    "control_input",
})
MEDIUM_RISK_TOOLS = frozenset({
    "send_message",
    "open_url",
    "download_file",
    "browser",
    "schedule",
})

# ── Safety & Sandboxing ────────────────────────────────
EXECUTE_CODE_TIMEOUT = get_env_int("EXECUTE_CODE_TIMEOUT", 30)
MAX_RAM_PERCENT = get_env_int("MAX_RAM_PERCENT", 85)
TOOL_RETRY_LIMITS = {
    "execute_code": get_env_int("EXECUTE_CODE_RETRIES", 3),
}

ALLOWED_IMPORTS = {
    "os",
    "pathlib",
    "shutil",
    "glob",
    "tools",
    "pkgutil",
    "webbrowser",
    "tempfile",
    "json",
    "csv",
    "re",
    "datetime",
    "time",
    "collections",
    "itertools",
    "functools",
    "copy",
    "psutil",
    "win32gui",
    "win32con",
    "win32api",
    "win32process",
    "pyautogui",
    "PIL",
    "requests",
    "pytesseract",
    "sqlite3",
    "hashlib",
    "base64",
    "uuid",
    "logging",
    "math",
    "string",
    "textwrap",
    "difflib",
    "sys",
    "winreg",
    "threading",
    "socket",
    "urllib",
    "http",
    "io",
    "struct",
    "platform",
    "signal",
    "queue",
    "traceback",
    "pyperclip",
    "win32clipboard",
    "win32ui",
    "win32pdh",
    "comtypes",
    "pythoncom",
    "mss",
    "cv2",
    "numpy",
    "imagegrab",
    "selenium",
    "webdriver",
    "bs4",
    "lxml",
    "pycaw",
    "pycaw.pycaw",
    "docx",
    "xlsxwriter",
    "openpyxl",
    "pdf2image",
    "PyPDF2",
    "wave",
    "audioop",
    "pyaudio",
    "speech_recognition",
    "yaml",
    "toml",
    "xml",
    "html",
    "zipfile",
    "tarfile",
    "gzip",
    "bz2",
    "ftplib",
    "poplib",
    "imaplib",
    "smtplib",
    "email",
    "asyncio",
    "aiohttp",
    "inspect",
    "ast",
    "concurrent",
    "contextlib",
    "skills",
    "icalendar",
    "win32com",
    "zoneinfo",
    "tzlocal",
    "pygetwindow",
    "reportlab",
    "exchangelib",
    "playwright",
    "spacy",
    "nltk",
    "tqdm",
    "rich",
    "colorama",
    "dotenv",
    "python_pptx",
    "fitz",
    "scipy",
    "matplotlib",
    "skimage",
    "sounddevice",
    "soundfile",
    "pandas",
    "sqlalchemy",
    "chardet",
    "dateutil",
    "shlex",
    "warnings",
    "unittest",
    "typing",
    "dataclasses",
    "enum",
    "abc",
    "weakref",
    "types",
    "pprint",
    "random",
    "statistics",
    "decimal",
    "fractions",
    "array",
    "bisect",
    "heapq",
    "configparser",
    "mimetypes",
    "binascii",
    "hmac",
    "secrets",
    "unicodedata",
    "codecs",
    "fnmatch",
    "linecache",
    "locale",
    "gettext",
    "numbers",
    "win32event",
    "win32service",
    "win32file",
    "win32pipe",
    "win32security",
    "win32net",
    "win32print",
}

BLOCKED_PATHS = [
    "C:/Windows/System32",
    "C:/Windows/SysWOW64",
    "C:/Windows/Boot",
]

# ── Confidence & Verification ──────────────────────────
CONFIDENCE_THRESHOLD = get_env_float("CONFIDENCE_THRESHOLD", 0.70)
VERIFICATION_MODE = get_env_str("VERIFICATION_MODE", "state_first")
VERIFICATION_TIMEOUT = get_env_int("VERIFICATION_TIMEOUT", 3)
MAX_VERIFICATION_RETRIES = get_env_int("MAX_VERIFICATION_RETRIES", 2)

# ── PC Indexer ─────────────────────────────────────────
INDEX_REFRESH_APPS = get_env_int("INDEX_REFRESH_APPS", 14400)
INDEX_REFRESH_FILES = get_env_int("INDEX_REFRESH_FILES", 7200)
STATE_MONITOR_INTERVAL = get_env_int("STATE_MONITOR_INTERVAL", 1)
DB_WAL_MODE = get_env_bool("DB_WAL_MODE", True)
DB_BUSY_TIMEOUT = get_env_int("DB_BUSY_TIMEOUT", 5000)

INDEX_FILE_DIRS = [
    "~/Documents",
    "~/Downloads",
    "~/Desktop",
    "~/Pictures",
    "~/Videos",
]

REGISTRY_UNINSTALL_PATHS = [
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
]

# ── Skill Store Lifecycle ──────────────────────────────
SKILL_MATCH_THRESHOLD = get_env_float("SKILL_MATCH_THRESHOLD", 0.75)
SKILL_CANDIDATE_CAP = get_env_int("SKILL_CANDIDATE_CAP", 50)

# ── Voice I/O ──────────────────────────────────────────────
WAKE_WORD = get_env_str("WAKE_WORD", "hey_jarvis")
WAKE_WORD_THRESHOLD = get_env_float("WAKE_WORD_THRESHOLD", 0.45)
WAKE_WORD_COOLDOWN = get_env_float("WAKE_WORD_COOLDOWN", 3.0)
# Extra silence window after TTS finishes — absorbs speaker→mic echo.
WAKE_WORD_POST_TTS_DRAIN = get_env_float("WAKE_WORD_POST_TTS_DRAIN", 1.0)
WAKE_WORD_ENABLED = get_env_bool("WAKE_WORD_ENABLED", True)
CONTINUOUS_MODE = get_env_bool("CONTINUOUS_MODE", False)

# TTS engine selection: "edge" (default, no install needed) | "piper" | "kokoro"
TTS_ENGINE = get_env_str("TTS_ENGINE", "edge")
TTS_ENABLED = get_env_bool("TTS_ENABLED", True)
VOICE_ENABLED = get_env_bool("VOICE_ENABLED", False)
# Keep desktop toasts opt-in on Windows; win10toast can emit WNDPROC/LRESULT noise.
DESKTOP_TOAST_ENABLED = get_env_bool("DESKTOP_TOAST_ENABLED", False)

# ── Edge TTS (primary) ────────────────────────────────────
# Full voice list: `python -m edge_tts --list-voices`
EDGE_TTS_VOICE = get_env_str("EDGE_TTS_VOICE", "en-US-JennyNeural")
EDGE_TTS_RATE = get_env_str("EDGE_TTS_RATE", "+0%")
EDGE_TTS_VOLUME = get_env_str("EDGE_TTS_VOLUME", "+0%")
EDGE_TTS_PITCH = get_env_str("EDGE_TTS_PITCH", "+0Hz")
# Max seconds to wait for the TTS network call
EDGE_TTS_TIMEOUT = get_env_int("EDGE_TTS_TIMEOUT", 15)

# ── Piper TTS (local fallback) ────────────────────────────
PIPER_BINARY = get_env_str("PIPER_EXE", "piper.exe")
PIPER_MODEL = get_env_str("PIPER_MODEL", "en_US-lessac-medium.onnx")
PIPER_MODEL_JSON = get_env_str("PIPER_MODEL_JSON", "en_US-lessac-medium.onnx.json")

# ── Kokoro TTS (legacy, kept for compatibility) ───────────
KOKORO_VOICE = get_env_str("KOKORO_VOICE", "bm_george")
KOKORO_LANG_CODE = get_env_str("KOKORO_LANG_CODE", "a")
KOKORO_SPEED = get_env_float("KOKORO_SPEED", 1.15)

STT_ENGINE = get_env_str("STT_ENGINE", "google")
STT_LANGUAGE = get_env_str("STT_LANGUAGE", "en-US")
STT_SAMPLE_RATE = get_env_int("SAMPLE_RATE", 16000)
MIC_DEVICE = get_env_int("MIC_DEVICE", -1)
AUDIO_DEVICE = get_env_int("AUDIO_DEVICE", -1)
SILENCE_THRESHOLD = get_env_int("SILENCE_THRESHOLD", 400)
SILENCE_DURATION = get_env_float("SILENCE_DURATION", 1.5)
MAX_RECORD_SECS = get_env_int("MAX_RECORD_SECS", 30)
# Thread-safe flag so TTS can mute STT while speaking.
# Use .set() / .clear() / .is_set() instead of raw boolean assignment.
IS_SPEAKING = threading.Event()

# Thread-safe flag for tools that need exclusive mic access (e.g. listen tool).
# When set, the continuous wake-word listener releases the mic and waits.
STT_EXCLUSIVE = threading.Event()

# ── Agent Configuration ────────────────────────────────
MAX_HISTORY = get_env_int("MAX_HISTORY", 10)
MAX_AGENT_ROUNDS = get_env_int("MAX_AGENT_ROUNDS", 12)
MAX_TOOL_ITERATIONS = get_env_int("MAX_TOOL_ITERATIONS", 5)
AGENT_MODE = get_env_str("AGENT_MODE", "agent")
MODE = get_env_str("MODE", "agent")
FALLBACK_TO_LOCAL = get_env_bool("FALLBACK_TO_LOCAL", True)
CONVERSATION_HISTORY_LIMIT = get_env_int("CONVERSATION_HISTORY_LIMIT", 20)

# ── Memory Configuration ───────────────────────────────
WORKING_MEMORY_MAX_MESSAGES = get_env_int("WORKING_MEMORY_MAX_MESSAGES", 20)
WORKING_MEMORY_MAX_TOKENS = get_env_int("WORKING_MEMORY_MAX_TOKENS", 4000)
MEMORY_RETRIEVAL_LIMIT = get_env_int("MEMORY_RETRIEVAL_LIMIT", 5)

# ── Ambient Monitoring ─────────────────────────────────
BATTERY_WARN_THRESHOLD = get_env_int("BATTERY_WARN_THRESHOLD", 20)
BATTERY_CRITICAL_THRESHOLD = get_env_int("BATTERY_CRITICAL_THRESHOLD", 10)
CPU_SPIKE_THRESHOLD = get_env_int("CPU_SPIKE_THRESHOLD", 90)
CPU_SPIKE_DURATION = get_env_int("CPU_SPIKE_DURATION", 30)
MEMORY_WARN_THRESHOLD = get_env_int("MEMORY_WARN_THRESHOLD", 85)
DISK_WARN_THRESHOLD = get_env_int("DISK_WARN_THRESHOLD", 92)
IDLE_MINUTES = get_env_int("IDLE_MINUTES", 20)
MONITOR_INTERVAL = get_env_int("MONITOR_INTERVAL", 15)
HEALTH_CHECK_INTERVAL = get_env_int("HEALTH_CHECK_INTERVAL", 60)
AMBIENT_MONITORING = get_env_bool("AMBIENT_MONITORING", True)

# ── Safety ─────────────────────────────────────────────
CONFIRM_DANGEROUS = get_env_bool("CONFIRM_DANGEROUS", True)
ENABLE_AUDIT_LOG = get_env_bool("ENABLE_AUDIT_LOG", True)
SAFETY_ENABLED = get_env_bool("SAFETY_ENABLED", True)

# ── Logging ────────────────────────────────────────────
LOG_FILE = LOGS_DIR / "jarvis.log"
LOG_LEVEL = get_env_str("LOG_LEVEL", "INFO")

# ── Autonomous Mode ─────────────────────────────────────
AUTONOMOUS_CONFIDENCE_THRESHOLD = get_env_float("AUTONOMOUS_CONFIDENCE_THRESHOLD", 0.90)
AUTONOMOUS_TIMEOUT_SECONDS = get_env_int("AUTONOMOUS_TIMEOUT_SECONDS", 86400)
AUTONOMOUS_CLEANUP_DAYS = get_env_int("AUTONOMOUS_CLEANUP_DAYS", 7)

AUTONOMOUS_REQUIRE_APPROVAL = {
    "delete",
    "format",
    "shutdown",
    "restart",
    "uninstall",
    "send_email",
    "make_purchase",
    # control_input removed — blocking every keystroke in autonomous mode
    # prevents legitimate background automation (file renaming, form filling).
    # Destructive bulk operations are caught by the task queue approval gate.
}

# ── Optional Integrations ──────────────────────────────
WEATHER_API_KEY = get_env_str("WEATHER_API_KEY", "")
NEWS_API_KEY = get_env_str("NEWS_API_KEY", "")
HF_TOKEN = get_env_str("HF_TOKEN", "")

# ── User Profile ───────────────────────────────────────
USER_NAME = get_env_str("USER_NAME", "User")

# ── Tool Stage (graduated exposure) ──────────────────────
# Controls which tools the LLM can see. Higher stages unlock more tools.
# Stage 1: core OS control + input + perception (21 tools)
# Stage 2: + file ops + process state + python (32 tools)
# Stage 3: + advanced perception / UI detection (33 tools)
# Stage 4: + web + memory + comms (42 tools)
# Set to 0 to expose ALL tools.
TOOL_STAGE = get_env_int("TOOL_STAGE", 4)

# ── Advanced Features ──────────────────────────────────
ENABLE_SKILLS = get_env_bool("ENABLE_SKILLS", True)

# ── Outbound Messaging (send_message tool) ─────────────
SMTP_HOST     = get_env_str("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = get_env_int("SMTP_PORT", 587)
SMTP_USER     = get_env_str("SMTP_USER", "")
SMTP_PASS     = get_env_str("SMTP_PASS", "")
SMTP_FROM     = get_env_str("SMTP_FROM", "")          # defaults to SMTP_USER if blank
TELEGRAM_BOT_TOKEN = get_env_str("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = get_env_str("TELEGRAM_CHAT_ID", "")

# ── Calendar (time_calendar tool) ──────────────────────
CALENDAR_BACKEND = get_env_str("CALENDAR_BACKEND", "outlook")  # outlook | ics
ICS_CALENDAR_PATH = get_env_str("ICS_CALENDAR_PATH", "")       # path for ics backend

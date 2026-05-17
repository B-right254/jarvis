"""
Tier 3: Vision LLM → text summary. Never injects raw base64 into context.

Endpoint resolution
-------------------
LLM_BASE_URL may be a full chat URL (https://api.ollama.com/api/chat) or a
bare host (http://localhost:11434).  The old code used `endpoint = base_url`
verbatim, which worked for the cloud case but sent requests to the root path
on local Ollama (404).  We now mirror ollama_client.py's resolution logic.
"""

import logging

import requests
from settings import (
    LLM_BASE_URL,
    LLM_TIMEOUT,
    LLM_VISION_MODEL,
    OLLAMA_API_KEY,
    OLLAMA_LOCAL_URL,
    OLLAMA_MODE,
)

logger = logging.getLogger(__name__)


def _vision_endpoint() -> str:
    """
    Return the correct chat endpoint for vision requests.
    Mirrors the logic in ollama_client.py so both always agree.
    """
    mode = OLLAMA_MODE.strip().lower()
    if mode == "local":
        base = OLLAMA_LOCAL_URL.rstrip("/")
        # Local Ollama native API
        return base if base.endswith("/api/chat") else base + "/api/chat"

    # Cloud / auto: LLM_BASE_URL is usually the full path already
    base = LLM_BASE_URL.rstrip("/")
    # If a bare host was configured (no API path), append /api/chat
    if not any(seg in base for seg in ("/api/", "/v1/")):
        base = base + "/api/chat"
    return base


def summarize_screen(image_b64: str, expected_outcome: str) -> str:
    """
    Post a base64 screenshot to the vision LLM and return a plain-text summary.
    Returns a human-readable fallback string on any failure — never raises.
    """
    endpoint = "unknown"
    try:
        headers = {"Content-Type": "application/json"}
        if OLLAMA_API_KEY:
            headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"

        messages = [
            {
                "role": "user",
                "content": f"Describe this screenshot concisely. Expected outcome: '{expected_outcome}'.",
                "images": [image_b64],
            }
        ]

        payload = {
            "model": LLM_VISION_MODEL,
            "messages": messages,
            "stream": False,
            "temperature": 0.2,
        }

        endpoint = _vision_endpoint()
        logger.debug(f"vision_summary: posting to {endpoint} model={LLM_VISION_MODEL}")

        resp = requests.post(
            endpoint, json=payload, headers=headers, timeout=LLM_TIMEOUT
        )
        resp.raise_for_status()
        data = resp.json()

        # Support both OpenAI-compatible and native Ollama response shapes
        if "choices" in data:
            summary = data["choices"][0].get("message", {}).get("content", "").strip()
        else:
            summary = data.get("message", {}).get("content", "").strip()

        return summary if summary else "Vision summary unavailable"

    except Exception as exc:
        logger.warning(f"Vision summary failed ({endpoint}): {exc}")
        return "Vision verification unavailable"

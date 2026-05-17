#!/usr/bin/env python3
"""Check if .env cloud config is loading correctly"""
from settings import (
    LLM_MODEL,
    LLM_BASE_URL,
    OLLAMA_API_KEY,
    ITERATION_CAPS
)

print("=== JARVIS Cloud Config Check ===")
print(f"LLM_MODEL: {LLM_MODEL}")
print(f"LLM_BASE_URL: {LLM_BASE_URL}")
print(f"OLLAMA_API_KEY loaded: {bool(OLLAMA_API_KEY)}")
print(f"ITERATION_CAPS: {ITERATION_CAPS}")
print()

if LLM_BASE_URL != "http://localhost:11434" and OLLAMA_API_KEY:
    print("✅ Cloud config loaded successfully!")
else:
    print("⚠️ Using mock LLM fallback (safe for testing routing)")

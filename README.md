# JARVIS — Autonomous Windows Desktop AI Agent

JARVIS is a production-grade AI assistant for Windows that uses cloud LLMs (Ollama) to understand natural language, plan tasks, and control your PC via tool execution.

## Architecture

```
User Input → Orchestrator → Brain (ReAct Tool Loop) → Safety Funnel → Tools → Verification
                                ↕
                           Ollama LLM
                        (gpt-oss:120b-cloud)
```

### Key Components

- **Orchestrator** — Routes commands, manages history, wires all subsystems
- **Brain** — ReAct reasoning loop, LLM communication, context management, tool call validation
- **Safety** — AST-based import sandboxing, path blocking, confidence gates, fail-loop guards, audit log
- **Memory** — Episodic (SQLite) + semantic (ChromaDB vector) memory
- **Skills** — Learns from successful multi-step solutions, retrieves via semantic search
- **PC Indexer** — Indexes installed apps and files for system-aware automation
- **Agents (Tier 3)** — Planner/Coder/Executor/Supervisor for complex task decomposition
- **Tools** — 40+ stage-gated tools (window control, file ops, web, email, calendar, voice I/O)

## Setup

1. Copy `.env.example` to `.env` and configure your API key
2. `pip install -r requirements.txt`
3. `python jarvis.py`

## Configuration

All settings are in `.env` and `settings.py`. Key options:
- `OLLAMA_API_KEY` — Your Ollama cloud API key
- `OLLAMA_MODEL` — Primary LLM (default: gpt-oss:120b-cloud)
- `TOOL_STAGE` — Graduated tool exposure (1-4)
- `VOICE_ENABLED` — Enable voice I/O

## Tool Stages

| Stage | Tools |
|-------|-------|
| 1 | Core OS control, mouse/keyboard, screenshots, basic queries |
| 2 | File ops, process management, Python/PowerShell execution |
| 3 | UI detection, vision queries, data analysis |
| 4 | Web search, memory, messaging, calendar, voice |

## Safety

- Import allowlist (AST-parsed, not string-matched)
- Windows system path blocking (including short-name variants)
- Dangerous operation detection (format, shutdown, bulk delete)
- Confidence gates with risk-tier escalation
- SHA-256 chained audit log
- Fail-loop guard (blocks after 2 consecutive tool failures)

## Tests

Run `pytest tests/` from the `jarvis/` directory.

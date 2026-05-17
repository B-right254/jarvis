# JARVIS — Agent Session Context

## Architecture
- **JARVIS** (ReAct tool loop) is the sole agent. No sub-agents. No Supervisor pipeline.
- `brain/tool_loop.py` — Max 10 iterations per request, structured logging to `logs/tool_loop.ndjson`, system prompt always included in every LLM call.
- `core/orchestrator.py` — Routes input through classifier (fast-path) or tool loop.
- `core/system_state.py` — Tracks active_window, mouse pos, CPU/RAM/disk/battery. Updated after every tool call. Injected as `## Live State` system message before each LLM iteration.
- `core/classifier.py` — Fast-path intent classifier for special commands (summary, skills_status, listen, etc.).

## Tool System
- **56 registered tools** across 4 levels (hierarchy in `prompts/jarvis.yaml`).
- Single source of truth: `tools/schemas.json` — validated against adapter functions at startup.
- Output envelope: `{success, message, data, timestamp}` via `safety/executor.py`.
- Verification with polling (6×0.5s) for app launches in `verification/verifier.py`.

## Known Fixes (don't re-break)
1. **open_app**: `_resolve_exe()` falls back to `shutil.which()`. Verifier strips prefixes (`"launched "`, `"focused "`) from app_name. Three-attempt strategy: `os.startfile()` → `shutil.which()` → DB path.
2. **vision_query**: No consent gate. `image_b64` stripped from nested `data` dict in tool_loop before sending to LLM.
3. **press_keys**: Single-char keys (e.g., `"/"`) use `pyautogui.write()` — `hotkey()` only accepts named keys (`ctrl`, `shift`, etc.).
4. **click / move_mouse**: Temporarily disable `pyautogui.FAILSAFE` during execution (screen-corner coordinates are valid targets for vision-guided automation).
5. **LLM 400 errors**: Caused by `image_b64` embedded in executor's `data` dict not being stripped before sending tool results to LLM.
6. **System prompt must always be included** — LLM API calls are stateless. History from memory is NOT loaded at startup.
7. **list_installed_apps**: Includes apps with null `path` (previously dropped silently).

## Key Files
- `core/orchestrator.py` — Main routing, SystemState integration, state-aware wait
- `brain/tool_loop.py` — ReAct loop engine
- `brain/prompt_builder.py` — Prompt construction, `build_state_context()`
- `brain/structured_log.py` — JSON-Lines logger
- `brain/tool_validator.py` — Tool result validation
- `tools/adapters.py` — All tool adapter functions (56 tools)
- `tools/schemas.json` — Tool definitions
- `safety/executor.py` — Tool output envelope, try/except wrapper
- `verification/verifier.py` — OS-level state verification with polling
- `prompts/jarvis.yaml` — System prompt with tool hierarchy rules
- `indexer/db/pc_index.db` — PC app index (1,237 apps, 904 null exe_path)

## Important Behaviors
- Memory is read-only (for system state, app index). No episode history loaded into LLM context.
- Wait tool is state-aware: `_execute_wrapper` checks SystemState before calling wait (skips polling if already satisfied).
- Classifier fast-path handles: `summary`, `skills_status`, `listen`, `status`, `stop`, `shutdown`, `help`, `history`, `clear`.
- Structured logging captures: tool_call, tool_retry, guard_triggered, loop_iteration, loop_complete.

## Not Implemented Yet
- Sub-agents / Director pattern (planned but deferred)
- Empty `__init__.py` re-exports (blocked by circular imports in `skills/` package)
- Agentic pre-authorization for tools (planned but deferred per "don't expand features, harden runtime")

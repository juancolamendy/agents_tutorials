# Design Spec: bot2 — Agno Migration

**Date:** 2026-03-16
**Status:** Approved
**Source:** bot1 (custom Claude chatbot) → bot2 (Agno framework)

---

## 1. Goals

Migrate the OpenClaw-style `bot1` CLI chatbot to the [Agno](https://github.com/agno-agi/agno)
agentic framework while:

- Preserving full feature parity with bot1
- Keeping JSONL session files and markdown memory files (storage Option B)
- Replacing all hand-rolled agentic infrastructure with Agno equivalents
- Making storage swappable to SQLite/Postgres via a one-line constructor change
- Not adding new features or dependencies beyond what is needed for the migration

> **Agno version note:** This spec targets Agno `>=0.5` where `Agent` uses `db=`
> (not `storage=`) and the custom DB base class is `agno.db.base.BaseDb`.
> Pin `agno` in `pyproject.toml` before implementation.

---

## 2. Approved Design

### 2.1 Architecture

```
CLI (main.py)
  └── Agent
        ├── model:                  Claude(id="claude-sonnet-4-6")
        ├── tools:                  [BotToolkit(), MemoryTools(db=MarkdownMemoryDb(...))]
        ├── db:                     JsonlAgentDb(sessions_dir="./sessions")
        ├── system_message:         build_system_prompt()   [from prompt.py]
        ├── add_history_to_context: True
        └── num_history_runs:       20
```

### 2.2 Components

#### `storage.py` — `JsonlAgentDb`
- Extends `agno.db.base.BaseDb`
- Implements `read`, `upsert`, `get_all_session_ids`, `get_all_sessions`, `delete_session`
- Files stored at `sessions/{user_id}_{session_id}.jsonl` (same filename convention as bot1)
- Content schema differs from bot1 (stores `AgentSession` JSON, not raw message lists)
- Single-line overwrite model: `upsert` writes one JSON line; `.jsonl` extension is kept for filename convention only
- **Does NOT include `save_memory` or `memory_search`** — those are delegated entirely to `MemoryTools`
- **Swap path:** replace with `SqliteDb` or `PostgresDb` at construction (one line)

#### `memory_db.py` — `MarkdownMemoryDb`
- Does **NOT** extend `BaseDb` — `MemoryTools.db` uses a different interface from
  session storage. The exact adapter method names must be inspected from `MemoryTools`
  source before implementing (see CLAUDE.md pitfall #12 and plan Task 5 Step 1).
- Core logic: `save(key, content)` and `search(query)` with keyword matching across `.md` files.
- Adapter layer: wrappers with the exact method names Agno calls on `db`.
- Stores memories as `memory/{key}.md` files — compatible with bot1 memory files
- Passed as `MemoryTools(db=MarkdownMemoryDb(MEMORY_DIR))`

#### `tools.py` — `BotToolkit(Toolkit)`
- Extends `agno.tools.Toolkit`
- Tools registered in `__init__` via `super().__init__(tools=[self.run_command, ...])`
- Methods use Google-style `Args:` docstrings (migrated from bot1's `:param:` style)
- Tools (these four only — memory tools are NOT here):
  - `run_command(command: str) -> str` — with safety check + interactive approval
  - `read_file(path: str) -> str` — with error string return (not exception)
  - `write_file(path: str, content: str) -> str`
  - `web_search(query: str) -> str` — stub
- Safety constants (`SAFE_COMMANDS`, `DANGEROUS_PATTERNS`, `APPROVALS_FILE`) unchanged

#### `prompt.py` — `build_system_prompt() -> str`
- Identical logic to bot1's `build_system_prompt()`
- Assembles: date + context files + daily memory + skills index + memory instructions
- Called once at `Agent` initialization (workspace file changes require bot restart)
- `parse_skill_frontmatter`, `load_context_files`, `load_daily_memory`, `load_skills_index` preserved unchanged

#### `main.py` — CLI Entry Point
```python
agent = Agent(
    model=Claude(id="claude-sonnet-4-6", cache_system_prompt=True),  # cache large prompt
    tools=[
        BotToolkit(approvals_file=os.path.join(_HERE, "workspace", "exec-approvals.json")),
        MemoryTools(db=MarkdownMemoryDb(MEMORY_DIR)),
    ],
    db=JsonlAgentDb(sessions_dir=SESSIONS_DIR),
    system_message=build_system_prompt(),
    add_history_to_context=True,
    num_history_runs=20,
    max_tool_calls_from_history=5,   # guards against large tool-output context bloat
)

# loop — wrap agent.run() to handle network/API errors gracefully
try:
    response = agent.run(text, user_id=user_id, session_id=session_id)
    print(f"Claude: {response.content or ''}")
except KeyboardInterrupt:
    raise
except Exception as e:
    print(f"Error: {e}")
```

**Key constraints:**
- `BotToolkit` receives absolute `approvals_file` path (consistent with `SESSIONS_DIR`/`MEMORY_DIR`).
- `cache_system_prompt=True` — system prompt includes large workspace files; caching is meaningful.
- Main loop catches exceptions to prevent single API/network failures from crashing the bot.
- `input()` raises `EOFError` if stdin is closed (e.g. piped input); handle or document.

### 2.3 What Is Removed

| Removed from bot1 | Reason |
|---|---|
| `ToolRegistry` + `_infer_schema` | Replaced by Agno's native tool system |
| `serialize_content()` | Agno handles message serialization internally |
| `run_agent_turn()` while-loop | Replaced by `Agent.run()` |
| `handle_message()` async wrapper | Not needed; `Agent.run()` handles session load/save |
| `compact_session()` LLM summarization | **Deliberate trade-off:** replaced by `num_history_runs` + `max_tool_calls_from_history`; see note below |
| `estimate_tokens()` | Not needed with `num_history_runs` approach |

> **Context protection trade-off:** bot1's `compact_session()` fires at ~100,000 tokens
> and summarizes old messages via a Claude call. `num_history_runs=20` caps the number
> of injected runs but not token volume — a single run with a large `read_file` result
> can still be large. `max_tool_calls_from_history=5` mitigates this by capping
> historical tool outputs. For extreme cases, `compact_session()` logic can be
> re-added as a `JsonlAgentDb` subclass hook in a future iteration.

### 2.4 What Is Preserved

- All workspace files: `SOUL.md`, context files, `skills/` directory
- Session file naming: `sessions/{user_id}_{session_id}.jsonl` (content schema differs from bot1)
- Memory file format: `memory/{key}.md` (long-term agent memory)
- Safety approval logic and `exec-approvals.json`
- CLI commands: `/quit`, `/exit`, `/new`
- System prompt assembly logic (all helper functions unchanged)

---

## 3. Data Flow

```
user input
  ↓
main.py: agent.run(text, user_id=uid, session_id=sid)
  ↓
Agno Agent:
  1. JsonlAgentDb.read(sid, uid)         → load history
  2. inject system_message + history into context
  3. Claude API: messages.create(...)
     ↕ tool_use loop (BotToolkit / MemoryTools)
  4. end_turn → RunResponse
  5. JsonlAgentDb.upsert(session)        → save history
  ↓
main.py: print(response.content or '')
```

---

## 4. Storage Swap Path

To swap to SQLite (one-line change):
```python
# Before (bot2 default)
from storage import JsonlAgentDb
db=JsonlAgentDb(sessions_dir="./sessions")

# After (SQLite)
from agno.db.sqlite import SqliteDb
db=SqliteDb(db_file="./sessions/agent.db")
```

No other code changes required. `Agent` consumes the `BaseDb` interface only.

---

## 5. File Layout

```
bot2/
├── .gitignore           ← excludes: .env, sessions/, memory/ (runtime artifacts)
├── CLAUDE.md
├── main.py
├── prompt.py
├── storage.py           ← JsonlAgentDb
├── memory_db.py         ← MarkdownMemoryDb
├── tools.py             ← BotToolkit
├── sessions/            ← JSONL session files (git-ignored; same filename format as bot1)
├── memory/              ← long-term agent memory (git-ignored; *.md keyed by save_memory)
└── workspace/
    ├── SOUL.md
    ├── skills/
    └── memory/          ← daily memory logs (YYYY-MM-DD.md, read into system prompt)
```

> **Note:** `sessions/` and `memory/` contain runtime data and must be git-ignored.
> `.env` must also be git-ignored. See gitignore step in the implementation plan.

---

## 6. Testing Strategy

- Preserve existing test structure from bot1 (`tests/`)
- `test_prompt.py` — unit tests for `build_system_prompt`, `load_context_files`, `load_daily_memory`, `load_skills_index`, `parse_skill_frontmatter` (migrated from bot1's `test_main.py`)
- `test_storage.py` — unit tests for `JsonlAgentDb` CRUD
- `test_memory_db.py` — unit tests for `MarkdownMemoryDb` save/search
- `test_tools.py` — unit tests for `BotToolkit` tool functions
- Agent-level tests mock `anthropic` client (same pattern as bot1's `TestRunAgentTurn`)

---

## 7. Dependencies

Add to `pyproject.toml`:
```toml
[project]
dependencies = [
    "agno>=0.5,<1.0",   # upper bound — Agno is fast-moving; major versions may break API
    "anthropic",
    "python-dotenv",
]
```

---

## 8. Out of Scope

- Web UI or API server
- Multi-agent workflows
- Postgres storage (may be added later via storage swap)
- Real web search implementation
- Streaming output (can be added with `agent.run(..., stream=True)` later)

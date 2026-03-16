# bot2 — Agno Migration Guide

> Research summary for migrating the OpenClaw-style bot1 to the [Agno](https://github.com/agno-agi/agno) agentic framework.
> Researched via context7 MCP on 2026-03-16.

---

## What is Agno?

Agno is a Python framework for building multi-agent systems with shared memory, knowledge, and reasoning. It provides:

- A production-ready `Agent` class with a built-in agentic (tool-use) loop
- A native `Toolkit` / `@tool` decorator system for registering tools with auto-inferred schemas
- Pluggable storage backends (`BaseDb`) for session persistence
- Built-in memory management (`MemoryTools`)
- First-class support for Anthropic Claude models via `agno.models.anthropic.Claude`

> **Version note:** This guide targets `agno>=0.5`. The `Agent` constructor uses `db=`
> (not `storage=`) and the custom DB base class is `agno.db.base.BaseDb`.
> Pin in `pyproject.toml`: `agno>=0.5`.

---

## Architecture

### Core Agno Primitives

```
Agent
├── model                       → Claude(id="claude-sonnet-4-6")
├── tools                       → [BotToolkit(), MemoryTools(db=MarkdownMemoryDb(...))]
├── db                          → JsonlAgentDb(sessions_dir="./sessions")
├── system_message              → build_system_prompt()
├── add_history_to_context      → True
├── num_history_runs            → 20
└── max_tool_calls_from_history → 5
```

### Request Flow

```
user input
  → agent.run(message, user_id=..., session_id=...)
      → load session history from db (JsonlAgentDb.read)
      → build context (system prompt + history)
      → Claude API call
          → tool_use? → execute tool → loop
          → end_turn  → return RunResponse
      → save session to db (JsonlAgentDb.upsert)
  → print response.content or ''
```

### Storage Abstraction

Agno's `agno.db.base.BaseDb` defines the interface all storage backends must implement:

```python
class BaseDb:
    def read(self, session_id: str, user_id: str | None) -> AgentSession | None: ...
    def upsert(self, session: AgentSession) -> AgentSession | None: ...
    def get_all_session_ids(self, user_id: str | None) -> list[str]: ...
    def get_all_sessions(self, user_id: str | None) -> list[AgentSession]: ...
    def delete_session(self, session_id: str): ...
```

**bot2 uses `JsonlAgentDb`** — a custom `BaseDb` subclass backed by
`sessions/{user_id}_{session_id}.jsonl` files, identical in layout to bot1.
Swap to `SqliteDb` or `PostgresDb` by replacing the one `db=` argument at startup:

```python
# bot2 default
db=JsonlAgentDb(sessions_dir="./sessions")

# swap to SQLite — one line, no other changes
from agno.db.sqlite import SqliteDb
db=SqliteDb(db_file="./sessions/agent.db")
```

---

## Components

### 1. `JsonlAgentDb` (`storage.py`)
Custom `BaseDb` subclass. Reads/writes JSONL session files at
`sessions/{user_id}_{session_id}.jsonl`. Preserves full compatibility with
bot1's session files.

### 2. `MarkdownMemoryDb` (`memory_db.py`)
Custom `BaseDb` subclass for memory storage. Stores `memory/{key}.md` files.
Implements keyword search. Passed as `MemoryTools(db=MarkdownMemoryDb(MEMORY_DIR))`.

**Note:** `MarkdownMemoryDb` stores long-term memory (`memory/*.md`).
This is separate from `workspace/memory/YYYY-MM-DD.md` daily logs, which are
read into the system prompt by `prompt.py` and are NOT managed by `MarkdownMemoryDb`.

### 3. `BotToolkit` (`tools.py`)
Extends `agno.tools.Toolkit`. Contains **only** these four tools:
- `run_command` — shell execution with safety check + interactive approval
- `read_file` — filesystem read
- `write_file` — filesystem write
- `web_search` — stub

**Does NOT include `save_memory` or `memory_search`** — those are delegated
entirely to `MemoryTools`.

Safety constants (`SAFE_COMMANDS`, `DANGEROUS_PATTERNS`, `APPROVALS_FILE`)
are preserved unchanged from bot1.

### 4. `prompt.py`
Standalone `build_system_prompt()` function. Assembles the system prompt from:
1. Current date
2. Workspace context files (`AGENTS.md`, `SOUL.md`, `USER.md`, `IDENTITY.md`, `TOOLS.md`)
3. Daily memory logs (`workspace/memory/YYYY-MM-DD.md`)
4. Skills index XML (scanned from `workspace/skills/*/SKILL.md`)
5. Memory tool instructions

Passed to `Agent(system_message=build_system_prompt())`. Called once at agent
initialization — workspace file changes require a restart.

### 5. `main.py`
Thin CLI entry point:
- Prompts for `user_id` / `session_id`
- Creates `Agent` with all components wired
- Loop: reads input → `agent.run(text, user_id=..., session_id=...)` → prints `response.content or ''`
- `/new` resets `session_id`; `/quit` or `/exit` exits

---

## Key Differences from bot1

| Concern | bot1 | bot2 (Agno) |
|---------|------|-------------|
| Tool registration | Custom `ToolRegistry` + `_infer_schema` | `Toolkit` + `@tool` decorator |
| Schema inference | Manual via type hints + `:param:` docstrings | Native Agno (same source: type hints + Google-style docstrings) |
| Agentic loop | Hand-rolled `run_agent_turn()` while-loop | `Agent.run()` built-in |
| Message serialization | Custom `serialize_content()` | Handled by Agno |
| Session storage | JSONL files (hand-rolled) | `JsonlAgentDb(BaseDb)` — same files |
| Memory | Plain `memory/*.md` + custom search | `MemoryTools` + `MarkdownMemoryDb` |
| Context compaction | LLM summarization at ~100k tokens | `num_history_runs=20` + `max_tool_calls_from_history=5` (see pitfall #9) |
| System prompt | Rebuilt on every message | Built once at agent init (workspace changes need restart) |

---

## Best Practices (from Agno docs)

1. **Use `@tool` decorator** — Agno infers JSON schema from Python type hints and
   Google-style `Args:` docstrings. Keep function signatures typed.

2. **Use `Toolkit` for grouped tools** — pass a single `Toolkit` instance rather
   than a flat list of functions when tools share state (e.g., approval records).

3. **`add_history_to_context=True`** — tells Agno to inject session history into
   the context on each run. Combine with `num_history_runs` to cap context size.

4. **`max_tool_calls_from_history`** — limits how many historical tool calls are
   injected, preventing context bloat from large `read_file` results without
   losing the conversation narrative.

5. **Storage swap is one line** — design `JsonlAgentDb` to match the
   `BaseDb` interface exactly so the consumer (`Agent`) never needs to change.

6. **`user_id` + `session_id` on every `agent.run()` call** — Agno routes storage
   and memory scoping through these; always pass them explicitly in CLI bots.

7. **Prompt caching** — use `Claude(id=..., cache_system_prompt=True)` to cache
   the large static system prompt across calls; cost savings are significant when
   workspace files are large.

---

## Known Pitfalls

1. **`@tool` on class methods requires `super().__init__(tools=[self.method, ...])`**
   in `Toolkit.__init__`. Forgetting to register methods means they are invisible
   to the agent.

2. **`MemoryTools` needs an explicit `db=` argument** — without it, memories are
   in-process only and lost between runs.

3. **`session_id` scope** — if `session_id` is not passed to `agent.run()`, Agno
   generates a new one each call, breaking conversation continuity.

4. **`AgentStorage.upsert` vs `save`** — always implement `upsert` (not just
   `save`); Agno calls `upsert` on every run completion.

5. **Tool docstring format** — Agno parses Google-style `Args:` blocks, not
   Sphinx `:param:` style used in bot1. Docstrings must be updated during migration.

6. **`build_system_prompt()` rebuild cost** — the function reads disk files on
   every call. Acceptable for a CLI bot; for high-throughput use cases, cache it.

7. **`stop_after_tool_call`** — some Agno built-in tools default to
   `stop_after_tool_call=True`. Custom tools default to `False` (continue loop).
   Be explicit to avoid unexpected early exits.

8. **`add_history_to_context` is the correct parameter name** (not
   `add_history_to_messages` — that is a different, lower-level parameter with
   different semantics). Always check your installed Agno version's API.

9. **Context volume vs context count** — `num_history_runs` caps the number of
   runs injected, not token volume. A single run with a large `read_file` result
   can still be large. Pair with `max_tool_calls_from_history` to limit tool output
   size. bot1's LLM-summarization compaction can be re-added as a `BaseDb` hook
   if needed in the future.

10. **`response.content` can be `None`** — on tool-only turns where the agent ends
    without generating a text response. Always use `response.content or ''`.

11. **Do not duplicate `save_memory`/`memory_search` in `BotToolkit`** — these are
    provided by `MemoryTools`. Duplicate tool names cause schema conflicts.

---

## Dependencies

Add to `pyproject.toml`:

```toml
[project]
dependencies = [
    "agno>=0.5",
    "anthropic",
    "python-dotenv",
]
```

---

## Directory Structure

```
bot2/
├── CLAUDE.md              ← this file
├── main.py                ← CLI entry point
├── prompt.py              ← build_system_prompt()
├── storage.py             ← JsonlAgentDb (BaseDb subclass)
├── memory_db.py           ← MarkdownMemoryDb (BaseDb subclass)
├── tools.py               ← BotToolkit
├── sessions/              ← JSONL session files (same format as bot1)
├── memory/                ← long-term agent memory (*.md, keyed by save_memory calls)
└── workspace/
    ├── SOUL.md
    ├── skills/
    └── memory/            ← daily memory logs (YYYY-MM-DD.md, read into system prompt)
```

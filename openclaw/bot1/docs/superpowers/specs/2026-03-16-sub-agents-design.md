# Sub-Agent Support Design

**Date:** 2026-03-16
**Status:** Approved
**File:** `main.py` (modified in place)

---

## Overview

Add support for sub-agents in the existing Claude chatbot. The main agent can dispatch work to specialized sub-agents defined as markdown files under `workspace/agents/`. Sub-agents are invoked as a registered tool (`run_agent`), receive the current session history as context, and return their response as a string back into the main conversation.

---

## Functional Requirements

- **FR1:** `load_agents_index()` scans `workspace/agents/`, reads each agent's markdown file, and builds an XML index injected into the system prompt.
- **FR2:** The system prompt includes a `## Agents` section (after `## Skills`, before `## Memory Instructions`) listing available agents. The section is omitted when no agents are found (mirrors the `## Skills` conditional guard).
- **FR3:** `tool_run_agent(agent_name: str, input: str)` is a registered tool the main LLM can call to dispatch to a sub-agent.
- **FR4:** `tool_run_agent` loads the current session messages and appends `input` as the final user message before calling the sub-agent. This gives the sub-agent full conversation context.
- **FR5:** The sub-agent model is taken directly from the agent frontmatter `model` field (full model ID, e.g. `claude-sonnet-4-6`). If the field is absent or empty, defaults to `claude-sonnet-4-6`. The default is resolved at dispatch time in `tool_run_agent`; `load_agents_index` stores `None` when the field is absent.
- **FR6:** If `agent_name` is not found, the file is unreadable, or the API call fails, return an error string — never raise an exception.

---

## Non-Functional Requirements

- **NFR1 (DX):** New code mirrors existing patterns (`load_skills_index`, `tool_read_file`) for consistency and readability. Tool docstrings follow the `:param name: description` convention used by all other tool functions.
- **NFR2 (Correctness):** Frontmatter is stripped before passing body as `system` prompt to the sub-agent. A helper `extract_frontmatter_body(content) -> str` handles this (see below).
- **NFR3 (Safety):** Sub-agent API calls have no tools registered. The sub-agent can read context but cannot call tools, write files, or execute commands.
- **NFR4 (Testability):** All new functions are unit-testable via `tmp_path`/`monkeypatch` and `unittest.mock`. Tests must reset `_agents_registry` between test cases.
- **NFR5 (Concurrency):** This is a single-user CLI chatbot (sequential `asyncio` loop). The `_current_session` global is safe for this use case. Concurrent multi-user use is out of scope.

---

## Agent File Convention

```
workspace/agents/
  <agent_dir>/
    <agent_dir>.md       ← frontmatter + system prompt body
```

**Example:** `workspace/agents/summarizer_agent/summarizer_agent.md`

### Frontmatter fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Identifier used by `tool_run_agent` (e.g. `summarizer-agent`) |
| `description` | yes | Shown in the agents index XML |
| `model` | no | Full Claude model ID; stored as `None` if absent; defaults to `claude-sonnet-4-6` at dispatch |
| `color` | no | Display-only; ignored by the runtime |

If `name` is absent from frontmatter, the agent is **silently skipped** (consistent with how skills handle missing metadata).

---

## Architecture

### New module-level state

```python
_agents_registry: dict[str, dict] = {}
# Populated by load_agents_index()
# key: frontmatter "name" value
# value: {"file_path": str, "model": str | None}

_current_session: dict = {"user_id": None, "session_id": None}
# Set in handle_message() before run_agent_turn()
# Safe for single-user CLI; not safe for concurrent multi-user use
```

### `extract_frontmatter_body(content: str) -> str`

New helper. Uses the same multiline regex as `parse_skill_frontmatter`: `re.split(r"^---\s*$", content, maxsplit=2, flags=re.MULTILINE)`. Returns `parts[2].strip()` if 3 parts exist, otherwise returns the full content stripped. Using the multiline regex (not plain string split) ensures `---` appearing mid-line or within paragraphs is not treated as a delimiter.

### `load_agents_index() -> str`

Mirrors `load_skills_index()`:

1. Clear `_agents_registry` at the start (removes stale entries from previous calls).
2. List subdirectories under `workspace/agents/`. Sort alphabetically (`sorted(os.listdir(...))`, mirrors skills).
3. For each dir, read `<dir>/<dir>.md`. Skip silently if unreadable.
4. Parse frontmatter → extract `name`, `description`, `model` (store `None` if absent).
5. Skip agent if `name` is absent or empty.
6. Populate `_agents_registry[name] = {"file_path": ..., "model": model_or_none}`.
7. Build and return `<available_agents>` XML block with `<agent>` children.
8. Return `""` if no agents found or directory missing.

**Expected XML output shape:**
```xml
<available_agents>
  <agent>
    <name>summarizer-agent</name>
    <description>Expert text summarization agent...</description>
    <location>./workspace/agents/summarizer_agent/summarizer_agent.md</location>
    <directory>./workspace/agents/summarizer_agent</directory>
  </agent>
</available_agents>
```

All values are HTML-escaped (same as skills).

### `build_system_prompt()` update

Section ordering after the change (updated comment numbers):

```
1.  ## Current Date & Time
2-6. Context files (AGENTS.md, SOUL.md, etc.)
7.  ## Recent Memory
8.  ## Skills
9.  ## Agents          ← NEW (conditional, omitted if empty)
10. ## Memory Instructions
```

```python
agents = load_agents_index()
if agents:
    parts.append(f"## Agents\n\n{agents}")
```

### `handle_message()` update

Set `_current_session` before calling `run_agent_turn`:

```python
_current_session["user_id"] = user_id
_current_session["session_id"] = session_id
```

### `tool_run_agent(agent_name: str, input: str) -> str`

Docstring follows `:param` convention:

```python
def tool_run_agent(agent_name: str, input: str) -> str:
    """Dispatch a task to a specialized sub-agent and return its response.
    :param agent_name: Name of the agent as listed in the agents index.
    :param input: The task or question to send to the agent.
    """
```

Execution steps:

```
1. Look up agent_name in _agents_registry
   → if not found: return "Error: agent '{agent_name}' not found."

2. Read file at file_path
   → if unreadable: return "Error running agent '{agent_name}': {e}"

3. body = extract_frontmatter_body(content)

4. model = entry["model"] or "claude-sonnet-4-6"

5. user_id = _current_session["user_id"]
   session_id = _current_session["session_id"]
   if user_id is None or session_id is None:
       messages = []
   else:
       messages = load_session(user_id, session_id)

6. messages = messages + [{"role": "user", "content": input}]
   (do not mutate the loaded list in place)

7. try:
       response = client.messages.create(
           model=model,
           max_tokens=4096,
           system=body,
           messages=messages
       )
       return response.content[0].text
   except Exception as e:
       return f"Error running agent '{agent_name}': {e}"
```

### Tool registration

```python
registry.register("run_agent", tool_run_agent)
```

---

## Data Flow

```
User message
    │
    ▼
handle_message(user_id, session_id, text)
    ├─ _current_session["user_id"] = user_id
    ├─ _current_session["session_id"] = session_id
    ├─ build_system_prompt()
    │     └─ load_agents_index() → populates _agents_registry, returns XML
    └─ run_agent_turn(messages, system_prompt)
           │
           ▼  (LLM decides to call run_agent tool)
       execute_tool("run_agent", {agent_name, input})
           │
           ▼
       tool_run_agent(agent_name, input)
           ├─ [not found] → return error string
           ├─ load_session() → messages  ([] if _current_session unset)
           ├─ messages + [{role: user, content: input}]
           └─ client.messages.create(system=body, messages=messages)
                   │
                   ├─ [API error] → return error string
                   └─ response text → returned as tool_result into main conversation
```

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| `agent_name` not in `_agents_registry` | Return `"Error: agent '{agent_name}' not found."` |
| Agent file unreadable | Return `"Error running agent '{agent_name}': {e}"` |
| API call fails | Return `"Error running agent '{agent_name}': {e}"` |
| `model` field absent/empty in frontmatter | Default to `"claude-sonnet-4-6"` at dispatch |
| `_current_session` user_id/session_id is `None` | `messages = []`; sub-agent receives only `input` |
| Agent has no frontmatter `name` field | Agent silently skipped by `load_agents_index` |

---

## Testing

### `TestLoadAgentsIndex`

Use `tmp_path` + `monkeypatch(WORKSPACE_DIR)`. Reset `_agents_registry` in a `setup_method` or `autouse` fixture via `monkeypatch.setattr(main, "_agents_registry", {})`.

Required cases:
- No `workspace/agents/` dir → returns `""`
- Dir exists but no agent subdirs → returns `""`
- Agent dir with no `.md` file → skipped, returns `""`
- Basic agent appears in XML with correct `<name>`, `<description>`, `<location>`, `<directory>` tags
- Agent with no `model` field → `_agents_registry[name]["model"]` is `None`
- Agent with no `name` field → skipped silently
- XML special chars in description → HTML-escaped
- Multiple agents → sorted alphabetically in output
- `_agents_registry` populated correctly after call
- Called twice (agent removed between calls) → stale entry absent from registry on second call (verifies registry is cleared at start)

### `TestExtractFrontmatterBody`

- Content with frontmatter → returns body only
- Content without frontmatter → returns full content
- Body containing `---` horizontal rule → not split (maxsplit=2 handles this)

### `TestToolRunAgent`

Mock `client.messages.create` and `load_session` (or `_current_session`).

Required cases:
- Agent not found → returns error string (no exception raised)
- Agent file unreadable → returns error string
- API exception → returns error string
- Successful call → returns response text
- `_current_session` with None values → `messages` starts as `[]`
- `model` absent in registry entry → uses `claude-sonnet-4-6`

### `TestBuildSystemPrompt` (addition)

- `## Agents` appears between `## Skills` and `## Memory Instructions` when agents dir is present
- `## Agents` absent when `workspace/agents/` is empty

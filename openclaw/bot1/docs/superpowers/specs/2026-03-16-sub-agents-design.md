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
- **FR2:** The system prompt includes an `## Agents` section (after `## Skills`) listing available agents.
- **FR3:** `tool_run_agent(agent_name: str, input: str)` is a registered tool the main LLM can call to dispatch to a sub-agent.
- **FR4:** `tool_run_agent` loads the current session messages and appends `input` as the final user message before calling the sub-agent.
- **FR5:** The sub-agent model is taken directly from the agent frontmatter `model` field (full model ID, e.g. `claude-sonnet-4-6`). If missing, defaults to `claude-sonnet-4-6`.
- **FR6:** If `agent_name` is not found or the API call fails, return an error string — never raise an exception.

---

## Non-Functional Requirements

- **NFR1 (DX):** New code mirrors existing patterns (`load_skills_index`, `tool_read_file`) for consistency and readability.
- **NFR2 (Correctness):** Frontmatter is stripped before passing body as `system` prompt to the sub-agent.
- **NFR3 (Safety):** Sub-agent calls are stateless API calls — no tools registered, no side effects beyond returning text.
- **NFR4 (Testability):** All new functions are unit-testable via `tmp_path`/`monkeypatch` and `unittest.mock`.

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
| `model` | no | Full Claude model ID; defaults to `claude-sonnet-4-6` |
| `color` | no | Display-only; ignored by the runtime |

---

## Architecture

### New module-level state

```python
_agents_registry: dict[str, dict] = {}
# Populated by load_agents_index()
# key: frontmatter "name" value
# value: {"file_path": str, "model": str}

_current_session: dict = {"user_id": None, "session_id": None}
# Set in handle_message() before run_agent_turn()
```

### `load_agents_index() -> str`

Mirrors `load_skills_index()`:

1. List subdirectories under `workspace/agents/`.
2. For each dir, read `<dir>/<dir>.md`.
3. Parse frontmatter → extract `name`, `description`, `model`.
4. Populate `_agents_registry[name] = {"file_path": ..., "model": ...}`.
5. Build and return `<available_agents>` XML block (same structure as `<available_skills>`).
6. Return `""` if no agents found or directory missing.

### `build_system_prompt()` update

Add section 9 `## Agents` after `## Skills`, before `## Memory Instructions`:

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

```
1. Look up agent_name in _agents_registry
   → if not found: return "Error: agent '{agent_name}' not found."
2. Read file at file_path
   → strip frontmatter (reuse parse_skill_frontmatter logic)
   → body = text after closing ---
3. model = registry entry["model"] or "claude-sonnet-4-6"
4. messages = load_session(_current_session["user_id"], _current_session["session_id"])
5. messages.append({"role": "user", "content": input})
6. response = client.messages.create(
       model=model,
       max_tokens=4096,
       system=body,
       messages=messages
   )
7. return response.content[0].text
   → on any exception: return "Error running agent '{agent_name}': {e}"
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
handle_message()
    ├─ sets _current_session
    ├─ builds system_prompt (includes ## Agents section)
    └─ run_agent_turn()
           │
           ▼ (LLM decides to call run_agent)
       execute_tool("run_agent", {agent_name, input})
           │
           ▼
       tool_run_agent(agent_name, input)
           ├─ load_session() → messages
           ├─ append input
           └─ client.messages.create(system=agent_body, messages=messages)
                   │
                   ▼
               sub-agent response text
                   │
                   ▼
           returned as tool_result into main conversation
```

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| `agent_name` not in `_agents_registry` | Return `"Error: agent '{agent_name}' not found."` |
| Agent file unreadable | Return `"Error running agent '{agent_name}': {e}"` |
| API call fails | Return `"Error running agent '{agent_name}': {e}"` |
| `model` field missing in frontmatter | Default to `claude-sonnet-4-6` |
| `_current_session` not set (user_id/session_id is None) | `load_session` returns `[]`; sub-agent gets only the appended input |

---

## Testing

Mirror `TestLoadSkillsIndex` and `TestToolReadFile` patterns:

- **`TestLoadAgentsIndex`** — `tmp_path` + `monkeypatch(WORKSPACE_DIR)`: no dir, no file, basic agent appears in XML, missing model defaults, XML special chars escaped, `_agents_registry` populated correctly.
- **`TestToolRunAgent`** — mock `client.messages.create` and `load_session`: agent not found returns error string, successful call returns response text, API exception returns error string.

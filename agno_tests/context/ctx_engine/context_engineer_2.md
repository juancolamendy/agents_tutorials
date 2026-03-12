# Technical Specification: context_enginer_2.py

## Overview

Generic Context-Aware Multi-Agent System built with [Agno](https://github.com/agno-agi/agno) and LanceDB. Implements a two-step workflow where a **Planner** agent produces a JSON execution plan and an **Executor** agent runs it by dispatching specialized subagents.

---

## Architecture

```
run_context_engine(goal, style_hint)
        │
        ▼
┌─────────────────────────────────────┐
│         Workflow (Agno)             │
│  Step 1: Planner Step               │
│  Step 2: Executor Step              │
└─────────────────────────────────────┘
        │
        ▼ session_state["plan"]
┌─────────────────────────────────────┐
│         Executor Agent              │
│  Tools: DependencyTools             │
│         SubagentRouterTools         │
└─────────────────────────────────────┘
        │
        ├──► Librarian Agent  (LibrarianTools)
        ├──► Researcher Agent (ResearcherTools)
        └──► Writer Agent
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `agno` | Agent/Workflow framework |
| `lancedb` | Vector database for semantic search |
| `openai` | Embedding model (`text-embedding-3-small`) |
| `anthropic` (via agno) | LLM backbone (`claude-sonnet-4-20250514`) |
| `python-dotenv` | Load environment variables from `.env` |

### Required Environment Variables

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | Used to generate embeddings via OpenAI API |
| `ANTHROPIC_API_KEY` | Used by Agno's `Claude` model for all agents |

---

## Module Sections

### 0. Embeddings + Chunking

**`embed_batch(texts, model)`**
- Calls OpenAI Embeddings API in batch.
- Default model: `text-embedding-3-small`.
- Returns `List[List[float]]`.

**`chunk_text(text, chunk_size, overlap)`**
- Splits raw text into overlapping character-level chunks.
- Defaults: `chunk_size=500`, `overlap=50`.

---

### 1. Data + LanceDB

**Vector Database:** `./context_enginer_1.db` (LanceDB on disk)

**Tables created at startup by `init_lancedb()`:**

| Table | Schema | Purpose |
|---|---|---|
| `context_library` | `id`, `description`, `blueprint` (JSON str), `vector` | Stores style blueprints; searched semantically by the Librarian |
| `knowledge_base` | `id`, `text`, `vector` | Stores chunked factual knowledge; searched semantically by the Researcher |

**Style Blueprints (seeded at startup):**

| ID | Description |
|---|---|
| `suspenseful_narrative` | Mysterious/tense narrative with hooks and reveals |
| `technical_explanation` | Precise, structured technical writing |
| `casual_summary` | Friendly, conversational summary for non-experts |

Each blueprint contains: `tone`, `style`, `structure`, `techniques[]`.

---

### 2. Subagent Toolkits

#### `LibrarianTools` (Toolkit)

Registered tool: **`semantic_blueprint_search(intent_query)`**
- Embeds `intent_query` and queries `context_library` with `limit=1`.
- Writes result into `session_state["semantic_blueprint"]` and `session_state["blueprint_found"]`.
- Returns JSON string of the matched blueprint (or a neutral fallback if no match).

#### `ResearcherTools` (Toolkit)

Registered tool: **`semantic_research(query, limit=5)`**
- Embeds `query` and queries `knowledge_base`.
- Writes result list into `session_state["research_results"]`.
- Returns JSON string of `[{id, text}, ...]`.

---

### 3. Subagents

All agents use `Claude(id="claude-sonnet-4-20250514")`.

| Agent | Role | Tools | Behavior |
|---|---|---|---|
| `librarian_agent` | Context Librarian | `LibrarianTools` | Calls `semantic_blueprint_search` and returns the JSON blueprint |
| `researcher_agent` | Knowledge Researcher | `ResearcherTools` | Calls `semantic_research` and summarizes findings |
| `writer_agent` | Writer | None | Reads `semantic_blueprint` and `research_results` from session_state; generates final content following the blueprint |

**`subagents_team`** — An Agno `Team` grouping all three subagents (used as a logical grouping; dispatching is done via `SubagentRouterTools`).

---

### 4. DependencyTools (Toolkit)

Registered tool: **`resolve_template(template)`**
- Reads `session_state["step_outputs"]` (a `Dict[str, str]`).
- Replaces `{{step_id}}` placeholders in `template` with the corresponding step output.
- Returns the fully resolved string.

---

### 5. SubagentRouterTools (Toolkit)

Registered tool: **`call_subagent(agent_name, input_text)`**
- Dispatches to one of the three subagents based on fuzzy name matching (case-insensitive substring match).
- Falls back to `writer_agent` for any unrecognized name.
- Passes `session_state` into the subagent call so state is shared.
- Returns the subagent's response content as a string.

**Name matching rules:**

| Match keyword(s) | Routed to |
|---|---|
| `librarian` | `librarian_agent` |
| `researcher`, `research` | `researcher_agent` |
| `writer`, `solution`, `executor`, `summary`, `analyst`, `compose`, `content`, `author`, or unrecognized | `writer_agent` |

---

### 6. Planner Agent + Step

**`planner_agent`** — An Agno `Agent` that returns a JSON execution plan.

**Output schema:**
```json
{
  "steps": [
    {"id": "step_librarian", "agent": "Librarian", "input_template": "..."},
    {"id": "step_researcher", "agent": "Researcher", "input_template": "..."},
    {"id": "step_writer",    "agent": "Writer",     "input_template": "..."}
  ]
}
```

- Later steps may reference earlier step outputs via `{{step_id}}` placeholders in `input_template`.
- The planner is instructed to return **only JSON** (no prose).

**`planner_step_fn(step_input, run_context)`**
1. Reads `user_goal` and `style_hint` from `session_state`.
2. Calls `planner_agent.run(prompt)`.
3. Parses JSON; on parse failure, falls back to a hardcoded 3-step plan.
4. Writes the plan into `session_state["plan"]`.
5. Returns the plan as a JSON string.

---

### 7. Executor Agent + Step

**`executor_agent`** — An Agno `Agent` equipped with `DependencyTools` and `SubagentRouterTools`.

**Execution algorithm (defined in system instructions):**
1. Initialize `step_outputs = {}` in `session_state`.
2. For each step in `plan.steps`:
   - a) Call `resolve_template(template)` to substitute `{{step_id}}` placeholders.
   - b) Call `call_subagent(agent_name, resolved_input)`.
   - c) Store result in `step_outputs[step.id]` and update `session_state["step_outputs"]`.
   - d) Append a trace entry to `session_state["trace_logs"]`.
3. Write `step_outputs[last_step_id]` into `session_state["final_output"]` and return it.

**`executor_step_fn(step_input, run_context)`**
1. Bootstraps `step_outputs = {}` and `trace_logs = []` in `session_state` (if not present).
2. Calls `executor_agent.run(...)` with the shared `session_state`.
3. Returns `session_state["final_output"]` (or falls back to `resp.content`).

---

### 8. Workflow

```python
context_engine_workflow = Workflow(
    name="Generic Context Engine",
    steps=[planner_step, executor_step],
    session_state={},
    db=SqliteDb(
        session_table="generic_context_engine_sessions",
        db_file="tmp/generic_context_engine.db",
    ),
)
```

- Session state is persisted to SQLite for replay/resumption via `session_id`.
- Steps execute sequentially; `session_state` is the shared communication channel.

---

### 9. Public API

```python
def run_context_engine(
    goal: str,
    style_hint: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
```

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `goal` | `str` | The user's content generation goal |
| `style_hint` | `str \| None` | Natural language hint for tone/style selection |
| `session_id` | `str \| None` | Resume a prior session (SQLite-backed) |

**Returns:**

```python
{
    "final_output": str,       # Generated content from the Writer agent
    "plan":         dict,      # The JSON plan produced by the Planner
    "trace_logs":   list,      # Per-step execution trace entries
    "session_id":   str,       # Session ID (new or resumed)
}
```

---

## Session State Schema

The following keys are used across the workflow:

| Key | Set by | Type | Description |
|---|---|---|---|
| `user_goal` | `run_context_engine` | `str` | User's original goal |
| `style_hint` | `run_context_engine` | `str \| None` | Style hint for the Planner |
| `plan` | `planner_step_fn` | `dict` | JSON execution plan |
| `semantic_blueprint` | `LibrarianTools` | `dict` | Best-match style blueprint |
| `blueprint_found` | `LibrarianTools` | `bool` | Whether a semantic match was found |
| `research_results` | `ResearcherTools` | `list` | Retrieved knowledge chunks |
| `step_outputs` | `executor_agent` | `dict[str, str]` | Per-step output keyed by step ID |
| `trace_logs` | `executor_agent` | `list[dict]` | Execution trace entries |
| `final_output` | `executor_agent` | `str` | Final generated content |

---

## Data Flow

```
run_context_engine(goal, style_hint)
  │
  ├─ session_state["user_goal"] = goal
  ├─ session_state["style_hint"] = style_hint
  │
  ▼ Planner Step
  planner_agent.run(prompt)
  ├─ session_state["plan"] = { steps: [...] }
  │
  ▼ Executor Step
  executor_agent.run(...)
  │
  ├─ Step: Librarian
  │   LibrarianTools.semantic_blueprint_search(intent_query)
  │   └─ session_state["semantic_blueprint"] = { tone, style, ... }
  │
  ├─ Step: Researcher
  │   ResearcherTools.semantic_research(query)
  │   └─ session_state["research_results"] = [{ id, text }, ...]
  │
  └─ Step: Writer
      writer_agent.run(resolved_input, session_state)
      └─ session_state["final_output"] = <generated content>
```

---

## Example Usage

```python
result = run_context_engine(
    goal="Explain retrieval-augmented generation to a non-technical founder.",
    style_hint="casual summary with friendly tone",
)

print(result["final_output"])
print(result["plan"])
print(result["trace_logs"])
```

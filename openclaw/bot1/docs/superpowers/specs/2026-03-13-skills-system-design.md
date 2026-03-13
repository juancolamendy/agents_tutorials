# Skills System Design

**Date:** 2026-03-13
**Status:** Approved
**Scope:** Extend `main.py` with rich context-file system prompt, workspace skills directory, and progressive skill loading.

---

## Overview

Extend the existing CLI chatbot (`main.py`) to:
1. Build the system prompt from multiple workspace markdown files (AGENTS.md, SOUL.md, USER.md, IDENTITY.md, TOOLS.md) plus daily memory logs.
2. Inject a compact skills index (name + description + path) into the system prompt.
3. Let the model load full skill instructions on-demand via the existing `read_file` tool (progressive disclosure).
4. Include date/time and optional session context in every system prompt.

---

## Constraints

- Keep using Anthropic API/SDK (not Agent SDK).
- Functions only — no classes.
- No new tool registrations.
- No new file dependencies (no PyYAML).
- Session loading, compaction, and saving are **unchanged**.

---

## Architecture

### What Changes

| Component | Change |
|-----------|--------|
| Tool registry, agentic loop, session management | **Untouched** |
| `load_soul()` | **Removed** — absorbed into `load_context_files()` |
| `build_memory_prompt()` | **Kept** — renamed header to `## Memory Instructions` to avoid confusion with `## Recent Memory` |
| `build_system_prompt()` | **Expanded** — calls new helpers, gains optional `session_context: dict = None` param |
| Imports | Add `timedelta` to existing `datetime` import (used to compute yesterday's date: `datetime.now() - timedelta(days=1)`) |

### New Functions (5)

```
load_context_files() -> dict[str, str]
    Reads each file in CONTEXT_FILES from workspace/. Returns a dict mapping
    filename to content. Silently omits missing files. Caller (build_system_prompt)
    is responsible for header formatting.

load_daily_memory() -> str
    Reads workspace/memory/YYYY-MM-DD.md for today then yesterday (in that order).
    Returns a single string: today's content first, yesterday's second, each
    prefixed with a "### Memory YYYY-MM-DD" sub-header, separated by "\n\n".
    Returns "" if neither file exists.
    No `days_back` parameter — always reads exactly today and yesterday.

parse_skill_frontmatter(content: str) -> dict
    Splits content on "---" to extract the frontmatter block.
    Parses each non-empty line using str.partition(":") (splits on FIRST colon only,
    so values containing colons — e.g. URLs — are preserved correctly).
    Returns {} on malformed or absent frontmatter.
    Does NOT perform dir_name substitution — that is the caller's responsibility.

load_skills_index() -> str
    Scans workspace/skills/ for subdirectory/SKILL.md files.
    Sorts skill directories alphabetically by name for deterministic ordering.
    For each skill, calls parse_skill_frontmatter(). If the returned dict is missing
    "name", substitutes the directory name. If missing "description", substitutes "".
    Builds compact XML block. Returns "" if directory missing or no skills found.
    Paths in <location> are relative to the process working directory (project root).

build_system_prompt(session_context: dict = None) -> str
    Assembles all prompt sections in order. Omits any section that has no content.
```

---

## Memory Directories — Two Distinct Locations

The project has two separate memory stores that must not be confused:

| Directory | Purpose | Used By |
|-----------|---------|---------|
| `./memory/` | Long-term key/value memory files (e.g., `user-preferences.md`) | `tool_save_memory`, `tool_memory_search` — **unchanged** |
| `./workspace/memory/` | Daily memory logs (`YYYY-MM-DD.md`) | New `load_daily_memory()` — **read-only at prompt build time** |

The existing `MEMORY_DIR = "./memory"` constant and the `tool_save_memory` / `tool_memory_search` tools are **not affected** by this change.

---

## Workspace Layout

```
workspace/
├── AGENTS.md          # Operating instructions (optional)
├── SOUL.md            # Personality — already exists
├── USER.md            # User profile (optional)
├── IDENTITY.md        # Agent identity (optional)
├── TOOLS.md           # Tool usage notes (optional)
├── memory/
│   ├── 2026-03-13.md  # Daily memory log (today)
│   └── 2026-03-12.md  # Daily memory log (yesterday)
└── skills/
    ├── github/
    │   └── SKILL.md
    └── weather/
        └── SKILL.md
```

Skills are loaded from `workspace/skills/` only (single location, workspace-scoped).

---

## System Prompt Assembly Order

Each section is only included if it has content — no empty headers emitted.

```
1.  ## Current Date & Time      — always present
2.  ## AGENTS.md                — if file exists in workspace/
3.  ## SOUL.md                  — if file exists in workspace/
4.  ## USER.md                  — if file exists in workspace/
5.  ## IDENTITY.md              — if file exists in workspace/
6.  ## TOOLS.md                 — if file exists in workspace/
7.  ## Recent Memory            — if workspace/memory/ has matching date files
8.  ## Skills                   — if workspace/skills/ has any SKILL.md files
9.  ## Memory Instructions      — existing build_memory_prompt() output (unchanged content, header renamed)
10. ## Session Context          — only if session_context dict is provided with known keys
```

Context file headers are formatted by `build_system_prompt()` as `## {filename}` where
`filename` is the key returned by `load_context_files()` (e.g., `"SOUL.md"`).

---

## `session_context` Parameter

`build_system_prompt(session_context=None)` accepts an optional dict with these keys:

```python
{
    "active_task": str,         # e.g. "Write a blog post about Python"
    "working_directory": str,   # e.g. "/home/user/projects/myapp"
}
```

Unknown keys are ignored. For the initial implementation, `session_context` is always
`None` (passed through from `run_agent_turn` which keeps its existing signature).
No caller currently constructs a `session_context` dict — the parameter is a forward-
compatible hook for future use. The `## Session Context` section is simply omitted when
`session_context` is `None` or empty.

---

## SKILL.md Format

```markdown
---
name: github
description: Interact with GitHub using the gh CLI.
emoji: 🐙
---

# GitHub Skill

## When to Use
...

## Instructions
...
```

**Frontmatter parser detail:**
- Split content on `"---"` (first two occurrences) to extract the frontmatter block.
- For each non-empty line in the block: call `line.partition(":")` which splits on the
  **first colon only**, preserving values that contain colons (e.g. URLs, metadata strings).
- Strips whitespace from both key and value.
- Returns `{}` if frontmatter is absent or malformed — does NOT perform dir_name substitution.
- `load_skills_index()` (the caller) is responsible for substituting the directory name when `"name"` is absent, and `""` when `"description"` is absent.

---

## Skills Index (injected into system prompt)

```xml
When a task matches one of the skills below, use the `read_file` tool to load
the SKILL.md at the listed location for detailed instructions.

<available_skills>
  <skill>
    <name>github</name>
    <description>Interact with GitHub using the gh CLI.</description>
    <location>workspace/skills/github/SKILL.md</location>
  </skill>
</available_skills>
```

`<location>` paths are **relative to the process working directory** (assumed to be the
project root where `main.py` is launched). This matches how the existing `tool_read_file`
resolves paths via `open(path, "r")`.

Skill directories are sorted **alphabetically by directory name** before building the XML
block, ensuring deterministic ordering across runs.

---

## Two-Phase Skill Flow

**Phase 1 — Every turn (system prompt):**
Skills index XML is injected. Model sees name + description + path only. Cheap, deterministic.

**Phase 2 — On-demand (when model decides skill is relevant):**
Model calls `read_file(path="workspace/skills/github/SKILL.md")`.
Full SKILL.md content arrives as a `tool_result` in conversation history.
Model follows skill instructions, using existing tools (`run_command`, `read_file`, `write_file`) as directed.
Skill scripts (`.sh`, `.py`, `.js`) are invoked via `run_command` with the existing safety/approval system.

---

## Session Loading (Unchanged)

```
handle_message(user_id, session_id, text)
  ├── load_session()        ← reads sessions/{user_id}_{session_id}.jsonl
  ├── compact_session()     ← summarizes if token estimate > 100K
  ├── messages.append(user turn)
  ├── run_agent_turn(messages)
  │     └── build_system_prompt()   ← only this changes (session_context=None for now)
  └── save_session()        ← writes updated history back to disk
```

Conversation history (`messages=`) and context/persona/skills (`system=`) are separate API parameters. The session files are untouched.

---

## Data Flow Summary

```
workspace/SOUL.md, AGENTS.md, USER.md, IDENTITY.md, TOOLS.md
       ↓ load_context_files() → dict[str, str]
workspace/memory/YYYY-MM-DD.md
       ↓ load_daily_memory() → str
workspace/skills/*/SKILL.md  →  parse_skill_frontmatter()  →  load_skills_index() → str
       ↓
build_system_prompt(session_context=None)  →  system= parameter in API call
                                    +
sessions/{user_id}_{session_id}.jsonl  →  messages= parameter in API call

./memory/*.md  ← used only by tool_save_memory / tool_memory_search (unchanged)
```

---

## Error Handling

- Missing workspace context files: silently skipped (no error, no default created).
- Missing `workspace/skills/` directory: `load_skills_index()` returns `""`.
- Malformed SKILL.md frontmatter: `parse_skill_frontmatter` returns `{}`; `load_skills_index` substitutes dir name as skill name and `""` as description.
- Skill script execution: handled by existing `run_command` safety/approval system.
- `session_context` is `None`: `## Session Context` section is omitted entirely.

---

## Known Limitation

No size ceiling is enforced on the system prompt. For workspaces with many or large context files, the combined prompt could approach the model's context limit. This is acceptable for the current scope (personal assistant with a small workspace) and can be addressed later with per-file truncation or a total character budget.

---

## Testing Notes

- Add `workspace/skills/test-skill/SKILL.md` with valid frontmatter → verify skill appears in system prompt XML.
- Add a skill with no frontmatter → verify graceful fallback to dir name / empty description.
- Add `workspace/AGENTS.md` → verify it appears before `SOUL.md` in the assembled prompt.
- Verify missing context files produce no empty `##` headers.
- Verify `workspace/memory/` daily files appear under `## Recent Memory`, today first.
- Verify `./memory/` long-term files are NOT loaded into the system prompt (only via tools).
- Verify session load/save is unaffected by running an existing session after the change.
- Verify `session_context=None` produces no `## Session Context` section.
- Verify `session_context={"active_task": "foo"}` produces the section with only that key.
- Verify `parse_skill_frontmatter` correctly handles a description value containing a colon (e.g., `description: Load files from https://example.com`).
- Verify skills appear in alphabetical order in the XML block.

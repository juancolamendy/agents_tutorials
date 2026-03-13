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
| `build_memory_prompt()` | **Kept** — appended at end of system prompt |
| `build_system_prompt()` | **Expanded** — calls new helpers, gains optional `session_context` param |
| Imports | Add `timedelta` to existing `datetime` import |

### New Functions (5)

```
load_context_files()        — reads workspace/*.md, silently skips missing files
load_daily_memory()         — reads workspace/memory/YYYY-MM-DD.md (today + yesterday)
parse_skill_frontmatter()   — splits "---…---" header, extracts key: value pairs (no PyYAML)
load_skills_index()         — scans workspace/skills/*/SKILL.md → compact XML block
build_system_prompt()       — assembles all parts in order
```

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
│   ├── 2026-03-13.md  # Daily memory log
│   └── 2026-03-12.md
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
2.  ## AGENTS.md                — if file exists
3.  ## SOUL.md                  — if file exists
4.  ## USER.md                  — if file exists
5.  ## IDENTITY.md              — if file exists
6.  ## TOOLS.md                 — if file exists
7.  ## Recent Memory            — if workspace/memory/ has matching date files
8.  ## Skills                   — if workspace/skills/ has any SKILL.md files
9.  ## Memory                   — existing build_memory_prompt() output (unchanged)
10. ## Session Context          — only if session_context dict provided
```

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

Frontmatter parser: split content on `"---"`, take the middle block, partition each non-empty line on `":"`. Falls back to `{"name": <dir_name>, "description": ""}` on malformed input.

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
  │     └── build_system_prompt()   ← only this changes
  └── save_session()        ← writes updated history back to disk
```

Conversation history (`messages=`) and context/persona/skills (`system=`) are separate API parameters. The session files are untouched.

---

## Data Flow Summary

```
workspace/SOUL.md, AGENTS.md, USER.md, IDENTITY.md, TOOLS.md
       ↓ load_context_files()
workspace/memory/YYYY-MM-DD.md
       ↓ load_daily_memory()
workspace/skills/*/SKILL.md  →  parse_skill_frontmatter()  →  load_skills_index()
       ↓
build_system_prompt()  →  system= parameter in API call
                                    +
sessions/{user_id}_{session_id}.jsonl  →  messages= parameter in API call
```

---

## Error Handling

- Missing workspace files: silently skipped (no error, no default created).
- Missing `workspace/skills/` directory: `load_skills_index()` returns `""`.
- Malformed SKILL.md frontmatter: falls back to dir name as skill name, empty description.
- Skill script execution: handled by existing `run_command` safety/approval system.

---

## Testing Notes

- Add a `workspace/skills/test-skill/SKILL.md` with valid frontmatter and verify it appears in the system prompt.
- Add a skill with no frontmatter and verify graceful fallback.
- Add `workspace/AGENTS.md` and verify it appears before `SOUL.md` in the prompt.
- Verify missing files produce no empty `##` headers.
- Verify session load/save is unaffected by running an existing session after the change.

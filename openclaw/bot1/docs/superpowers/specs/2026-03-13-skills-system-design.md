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
4. Include date/time in every system prompt.

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
| Tool registry, session management | **Untouched** |
| `load_soul()` | **Removed** — absorbed into `load_context_files()` |
| `build_memory_prompt()` | **Kept** — only the string literal `## Memory` inside the function is changed to `## Memory Instructions`. All other text in the function body (including the `./memory/` path reference) remains verbatim. The return value's first line must be `## Memory Instructions` with no preceding whitespace or newline. |
| `build_system_prompt()` | **Expanded** — signature unchanged (no parameters); implementation is replaced to call new helpers |
| `run_agent_turn(messages)` | **Updated** — accepts new `system_prompt: str` parameter; no longer calls `build_system_prompt()` internally |
| `handle_message()` | **Updated** — calls `build_system_prompt()` once and passes result to `run_agent_turn()` |
| `tool_read_file` | **Updated** — wrapped in try/except; returns error string instead of raising |
| Imports | Change `from datetime import datetime` to `from datetime import datetime, timedelta`; `re` is already present |

### New Constants

```python
CONTEXT_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "IDENTITY.md", "TOOLS.md"]
```

Defined at module level alongside `SESSIONS_DIR` and `MEMORY_DIR`.
No `os.makedirs` call is needed for `CONTEXT_FILES`.

**File encoding:** All file reads introduced by this spec use `encoding='utf-8'`. The workspace directory and its
subdirectories are user-managed and must already exist.

### New Functions (5)

```
load_context_files() -> dict[str, str]
    Reads each file in CONTEXT_FILES from workspace/. Paths are resolved as
    workspace/{filename} relative to the process working directory (matching
    the convention of APPROVALS_FILE = "./workspace/exec-approvals.json").
    Files are opened with encoding='utf-8'.
    Returns a dict mapping filename to content, inserting keys in CONTEXT_FILES
    order. Silently omits missing files. Iteration order of the returned dict
    matches CONTEXT_FILES insertion order (Python 3.7+ dict guarantee); callers
    must iterate in insertion order to produce a deterministic prompt.
    Caller (build_system_prompt) is responsible for header formatting.

load_daily_memory() -> str
    Reads workspace/memory/YYYY-MM-DD.md for today then yesterday (in that order).
    Path is workspace/memory/{date}.md relative to the process working directory.
    Date strings are formatted using datetime.now().strftime('%Y-%m-%d') (local time).
    Yesterday is computed as datetime.now() - timedelta(days=1) (also local time).
    Both the writer of daily memory files and this function must use the same local
    clock source; UTC is not mandated.
    Each present file is formatted as:
        "### Memory {date}\n\n{content}"
    Entries are joined with "\n\n". Today's entry appears first when both exist.
    Each date is included independently — missing dates are silently skipped,
    not a failure condition. Returns "" if neither file exists.

parse_skill_frontmatter(content: str) -> dict
    Splits content using:
        re.split(r'^---\s*$', content, maxsplit=2, flags=re.MULTILINE)
    to extract the frontmatter block (index 1 of the result).
    This correctly handles "---" appearing as a horizontal rule in the body.
    If the split result has fewer than 3 elements (no valid frontmatter block
    is present), return {} immediately without attempting to access result[1].
    For each line in the frontmatter block, skip if line.strip() is empty.
    For non-empty lines, call str.partition(":") (splits on FIRST colon only,
    preserving values containing colons — e.g. URLs).
    Strips whitespace from both key and value.
    Returns {} on malformed or absent frontmatter.
    Does NOT perform dir_name substitution — that is the caller's responsibility.

load_skills_index() -> str
    Scans workspace/skills/ using sorted(os.listdir("workspace/skills/")) for
    deterministic alphabetical ordering by bare directory name.
    Only processes entries where os.path.isdir() returns True; plain files
    (e.g., README.md, .DS_Store) are silently skipped.
    If a subdirectory exists but contains no SKILL.md, that subdirectory is
    silently skipped.
    For each qualifying subdirectory, reads its SKILL.md and calls parse_skill_frontmatter().
    If the returned dict is missing "name", substitutes the directory name.
    If missing "description", substitutes "".
    If the directory exists but no qualifying skills are found (all entries fail
    isdir, or all SKILL.md files are missing/unreadable), return "" — do not
    emit an empty <available_skills> block.
    The returned string includes the preamble line:
        "When a task matches one of the skills below, use the `read_file` tool to
        load the SKILL.md at the listed location for detailed instructions."
    followed by the <available_skills> XML block. Indentation within the XML is
    implementation-defined, but tag structure must match the example in the
    "Skills Index" section. build_system_prompt() does NOT add an additional
    preamble — load_skills_index() owns the full section content.
    Returns "" if directory missing, not listable (any OSError), or no skills found.
    Paths in <location> are relative to the process working directory (project root).

build_system_prompt() -> str
    Assembles all prompt sections in order. A section is omitted when its content
    string is falsy (empty string ""). A file containing only whitespace is
    considered to have content (if content: test, not if content.strip():).
    No parameters.
```

---

## System Prompt Assembly — One-Time Build

`build_system_prompt()` is called **once per user message** inside `handle_message()`.
The resulting string is passed into `run_agent_turn(messages, system_prompt)` and
reused for every API call within that turn's agentic loop.

```python
# handle_message (updated)
async def handle_message(user_id, session_id, text):
    messages = load_session(user_id, session_id)
    messages = compact_session(user_id, session_id, messages)
    messages.append({"role": "user", "content": text})
    system_prompt = build_system_prompt()
    response_text, messages = run_agent_turn(messages, system_prompt)
    save_session(user_id, session_id, messages)
    return response_text

# run_agent_turn (updated signature)
def run_agent_turn(messages, system_prompt: str):
    while True:
        response = client.messages.create(
            ...,
            system=system_prompt,   # reused, not rebuilt
            ...
        )
```

`run_agent_turn` is **synchronous** (`def`, not `async def`) — unchanged from current.
Return type is **unchanged**: `tuple[str, list]`. Only the signature (adding
`system_prompt: str`) and the `system=` argument inside the loop change.

The `"tool_use"` branch appends tool results and falls through to the top of the
`while True` loop naturally (no explicit `return` or `continue` needed — the loop
body ends and the next iteration begins). Only `stop_reason` values that are neither
`"end_turn"` nor `"tool_use"` represent unexpected exits; those must either
`return (last_text, messages)` or raise a descriptive error — never return `None`.

---

## Memory Directories — Two Distinct Locations

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
9.  ## Memory Instructions      — existing build_memory_prompt() output (header renamed)
```

**Header ownership per section:**
- Sections 2–6: `build_system_prompt()` emits the `## {filename}` header, then appends the file content returned by `load_context_files()`.
- Section 7: `build_system_prompt()` emits `## Recent Memory`, then appends the string returned by `load_daily_memory()`. `load_daily_memory()` returns only the `### Memory {date}\n\n{content}` entries — it does not include the `## Recent Memory` header.
- Section 8: `build_system_prompt()` emits `## Skills`, then appends the string returned by `load_skills_index()`. `load_skills_index()` owns the preamble text and XML block but does NOT include the `## Skills` header.
- Section 9: `build_system_prompt()` appends the return value of `build_memory_prompt()` directly, without adding an extra header. `build_memory_prompt()` already contains the `## Memory Instructions` line as the first line of its return value. No header is emitted by `build_system_prompt()` for this section.

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
- Split using `re.split(r'^---\s*$', content, maxsplit=2, flags=re.MULTILINE)`.
  The frontmatter block is the element at index `[1]` of the result.
  This handles `---` appearing as a horizontal rule in the body without misreading it.
- For each non-empty line in the block: call `line.partition(":")` which splits on the
  **first colon only**, preserving values that contain colons (e.g. URLs, metadata strings).
- Strips whitespace from both key and value.
- Returns `{}` if frontmatter is absent or malformed — does NOT perform dir_name substitution.
- `load_skills_index()` (the caller) is responsible for substituting the directory name when
  `"name"` is absent, and `""` when `"description"` is absent.

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

Skill directories are sorted using `sorted(os.listdir("workspace/skills/"))` — bare
directory names, alphabetical, deterministic across runs.

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
  ├── load_session()           ← reads sessions/{user_id}_{session_id}.jsonl
  ├── compact_session()        ← summarizes if token estimate > 100K
  ├── messages.append(user turn)
  ├── build_system_prompt()    ← called ONCE here (new)
  ├── run_agent_turn(messages, system_prompt)
  └── save_session()           ← writes updated history back to disk
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
build_system_prompt()  →  system= parameter passed into run_agent_turn()
                                    +
sessions/{user_id}_{session_id}.jsonl  →  messages= parameter in API call

./memory/*.md  ← used only by tool_save_memory / tool_memory_search (unchanged)
```

---

## Error Handling

- Missing workspace context files: silently skipped (no error, no default created).
- Missing `workspace/skills/` directory or any `OSError` when listing it (including the directory being a file): `load_skills_index()` returns `""`.
- Skill subdirectory exists but has no `SKILL.md`, or `SKILL.md` raises `OSError` on read: that skill entry is silently skipped.
- Plain files inside `workspace/skills/` (e.g., README.md, .DS_Store): silently skipped (only `isdir()` entries are processed).
- Malformed SKILL.md frontmatter: `parse_skill_frontmatter` returns `{}`; `load_skills_index` substitutes dir name as skill name and `""` as description.
- `tool_read_file` exceptions: wrapped in try/except; returns `f"Error reading {path}: {e}"` instead of propagating. This prevents a missing or unreadable skill file from crashing the agentic loop.
- Skill script execution: handled by existing `run_command` safety/approval system.

---

## Known Limitation

No size ceiling is enforced on the system prompt. For workspaces with many or large context files, the combined prompt could approach the model's context limit. This is acceptable for the current scope (personal assistant with a small workspace) and can be addressed later with per-file truncation or a total character budget.

---

## Testing Notes

- Verify that `## Current Date & Time` is the first section in the assembled system prompt, appearing before any context file content.
- When all five CONTEXT_FILES are present, verify they appear in the system prompt in the order defined by `CONTEXT_FILES` (AGENTS.md, SOUL.md, USER.md, IDENTITY.md, TOOLS.md) regardless of filesystem order.
- Add `workspace/skills/test-skill/SKILL.md` with valid frontmatter → verify skill appears in system prompt XML.
- Add a skill with no frontmatter → verify graceful fallback to dir name / empty description.
- Add a skill whose SKILL.md body contains `---` as a horizontal rule → verify frontmatter is still parsed correctly.
- Add `workspace/AGENTS.md` → verify it appears before `SOUL.md` in the assembled prompt.
- Verify missing context files produce no empty `##` headers.
- Verify `workspace/memory/` daily files appear under `## Recent Memory`, today first.
- Verify only today's content is returned when yesterday's file is absent (and vice versa).
- When both today's and yesterday's files exist, verify today's content appears before yesterday's in the `## Recent Memory` section.
- Verify `./memory/` long-term files are NOT loaded into the system prompt (only via tools).
- Verify session load/save is unaffected by running an existing session after the change.
- Verify `build_system_prompt()` is called exactly once per user message, not once per API call.
- Verify `tool_read_file` returns an error string (not an exception) for a nonexistent path.
- Verify skills appear in alphabetical order in the XML block.
- Verify `parse_skill_frontmatter` correctly handles a description value containing a colon (e.g., `description: Load files from https://example.com`).
- Verify the assembled system prompt contains `## Memory Instructions` (not `## Memory`) as the header for the memory instructions section.

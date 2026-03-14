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
4. Include the current date in every system prompt.

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
| `build_memory_prompt()` | **Kept** — only the string literal `## Memory` inside the function body is changed to `## Memory Instructions`. All other text in the function body (including the `./memory/` path reference) remains verbatim. The return value's first line must be `## Memory Instructions` with no preceding whitespace or newline. |
| `build_system_prompt()` | **Expanded** — signature unchanged (no parameters); implementation is replaced to call new helpers |
| `run_agent_turn(messages)` | **Updated** — accepts new `system_prompt: str` parameter; no longer calls `build_system_prompt()` internally. Unexpected `stop_reason` handling fixed (see below). |
| `handle_message()` | **Updated** — calls `build_system_prompt()` once and passes result to `run_agent_turn()` |
| `tool_read_file` | **Updated** — wrapped in try/except; returns error string instead of raising; adds `encoding='utf-8'` |
| Imports | Change `from datetime import datetime` to `from datetime import datetime, timedelta`; `re` is already present |

### New Constants

```python
WORKSPACE_DIR = "./workspace"
CONTEXT_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "IDENTITY.md", "TOOLS.md"]
```

Both defined at module level alongside `SESSIONS_DIR` and `MEMORY_DIR`.
No `os.makedirs` call is needed for either — `workspace/` and its subdirectories are
user-managed and assumed to already exist. `load_skills_index()` handles a missing
`workspace/skills/` directory gracefully (returns `""`).

**File encoding:** All file reads introduced by this spec use `encoding='utf-8'`.

### New Functions (5)

```
load_context_files() -> dict[str, str]
    Reads each file in CONTEXT_FILES from WORKSPACE_DIR. Paths are resolved as
    os.path.join(WORKSPACE_DIR, filename).
    For each file, wraps the open() call in try/except Exception. On any exception
    (FileNotFoundError, PermissionError, OSError, etc.) the file is silently skipped.
    This matches the existing load_soul() error-handling pattern.
    All opens use encoding='utf-8'.
    Returns a dict mapping filename to content, inserting keys in CONTEXT_FILES
    order. Silently omits files that cannot be read. Iteration order of the returned
    dict matches CONTEXT_FILES insertion order (Python 3.7+ dict guarantee); callers
    must iterate in insertion order to produce a deterministic prompt.
    Caller (build_system_prompt) is responsible for header formatting.

load_daily_memory() -> str
    Reads workspace/memory/YYYY-MM-DD.md for today then yesterday (in that order).
    Path is os.path.join(WORKSPACE_DIR, "memory", f"{date}.md").
    Date strings are formatted using datetime.now().strftime('%Y-%m-%d') (local time).
    Yesterday is computed as datetime.now() - timedelta(days=1) (also local time).
    Both the writer of daily memory files and this function must use the same local
    clock source; UTC is not mandated.
    Wraps each file read in try/except Exception — missing or unreadable date files
    are silently skipped, not a failure condition.
    All opens use encoding='utf-8'.
    Each present file is formatted as:
        "### Memory {date}\n\n{content}"
    Entries are joined with "\n\n". Today's entry appears first when both exist.
    Returns "" if neither file exists or can be read.

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
    Scans WORKSPACE_DIR/skills/ using sorted(os.listdir(os.path.join(WORKSPACE_DIR, "skills/")))
    for deterministic alphabetical ordering by bare directory name.
    Only processes entries where os.path.isdir() returns True; plain files
    (e.g., README.md, .DS_Store) are silently skipped.
    If a subdirectory exists but contains no SKILL.md, that subdirectory is
    silently skipped.
    For each qualifying subdirectory, reads its SKILL.md using encoding='utf-8'
    inside a try/except Exception block — unreadable SKILL.md files are silently
    skipped (that skill entry is omitted from the index).
    Calls parse_skill_frontmatter(). If the returned dict is missing "name",
    substitutes the directory name. If missing "description", substitutes "".
    If the directory exists but no qualifying skills are found (all entries fail
    isdir, all SKILL.md files are missing/unreadable), return "" — do not emit an
    empty <available_skills> block.
    The returned string includes the preamble line:
        "When a task matches one of the skills below, use the `read_file` tool to
        load the SKILL.md at the listed location for detailed instructions."
    followed by the <available_skills> XML block. Indentation within the XML is
    implementation-defined, but tag structure must match the example in the
    "Skills Index" section. build_system_prompt() does NOT add an additional
    preamble — load_skills_index() owns the full section content.
    Returns "" if directory missing, not listable (any OSError), or no skills found.
    Paths in <location> are os.path.join(WORKSPACE_DIR, "skills", dir_name, "SKILL.md")
    — relative to the process working directory (project root). This matches how
    the existing tool_read_file resolves paths via open(path, "r").

build_system_prompt() -> str
    Assembles all prompt sections in order. A section is omitted when its content
    string is falsy (empty string "").
    NOTE: A context file containing only whitespace (e.g., "\n  \n") IS truthy and
    will be included as a section — this is intentional. Authors of workspace files
    are responsible for keeping them non-empty. Implementors must NOT add a
    content.strip() check.
    No parameters.
```

---

## System Prompt Assembly — One-Time Build

`build_system_prompt()` is called **once per user message** inside `handle_message()`.
The resulting string is passed into `run_agent_turn(messages, system_prompt)` and
reused for every API call within that turn's agentic loop. This avoids re-reading
workspace files on every tool call within a single turn.

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
            system=system_prompt,   # reused, not rebuilt each loop iteration
            ...
        )
```

`run_agent_turn` is **synchronous** (`def`, not `async def`) — unchanged from current.
Return type is **unchanged**: `tuple[str, list]`. Only the signature (adding
`system_prompt: str`) and the `system=` argument inside the loop change.

### Unexpected `stop_reason` Handling (Bug Fix)

The current code returns `None` implicitly when `stop_reason` is neither `"end_turn"`
nor `"tool_use"` (e.g., `"max_tokens"`). This crashes `handle_message` at:
    `response_text, messages = run_agent_turn(...)`

**Fix:** Add an explicit fallback after the `tool_use` block:

```python
    # After the tool_use block — catches "max_tokens", "stop_sequence", etc.
    text = "".join(block.text for block in response.content if hasattr(block, "text"))
    messages.append({"role": "assistant", "content": content})
    return text, messages
```

This uses the same text-extraction expression as the `end_turn` branch, ensuring the
model's partial response is returned rather than lost. For `"max_tokens"`, this returns
whatever text was generated before the cap was hit. This is correct behavior — the
conversation is not destroyed.

The `"tool_use"` branch appends tool results and falls through to the top of the
`while True` loop naturally (no explicit `return` or `continue` needed).

---

## Date-Only System Prompt Header (Prompt Caching Note)

The `## Current Date & Time` section uses **date only**, not date+time:

```python
datetime.now().strftime("%A, %B %d, %Y")  # e.g. "Saturday, March 14, 2026"
```

**Why not include the time:** Including minutes or seconds makes the system prompt
change on every message, making Anthropic prompt caching permanently impossible for
this bot. Date-only changes once per day — allowing up to 24 hours of cache hits if
prompt caching is added later. If the user needs time-awareness within a turn, the
model can call `run_command("date")` via the existing tool.

---

## Memory Directories — Two Distinct Locations

| Directory | Purpose | Used By |
|-----------|---------|---------|
| `./memory/` | Long-term key/value memory files (e.g., `user-preferences.md`) | `tool_save_memory`, `tool_memory_search` — **unchanged** |
| `./workspace/memory/` | Daily memory logs (`YYYY-MM-DD.md`) | New `load_daily_memory()` — **read-only at prompt build time** |

The existing `MEMORY_DIR = "./memory"` constant and the `tool_save_memory` /
`tool_memory_search` tools are **not affected** by this change.

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
│   ├── 2026-03-14.md  # Daily memory log (today)
│   └── 2026-03-13.md  # Daily memory log (yesterday)
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
1.  ## Current Date & Time      — always present (date only, see note above)
2.  ## AGENTS.md                — if file readable in workspace/
3.  ## SOUL.md                  — if file readable in workspace/
4.  ## USER.md                  — if file readable in workspace/
5.  ## IDENTITY.md              — if file readable in workspace/
6.  ## TOOLS.md                 — if file readable in workspace/
7.  ## Recent Memory            — if workspace/memory/ has readable date files
8.  ## Skills                   — if workspace/skills/ has any readable SKILL.md files
9.  ## Memory Instructions      — existing build_memory_prompt() output (header renamed)
```

**Header ownership per section:**
- Sections 2–6: `build_system_prompt()` emits the `## {filename}` header, then appends the file content returned by `load_context_files()`.
- Section 7: `build_system_prompt()` emits `## Recent Memory`, then appends the string returned by `load_daily_memory()`. `load_daily_memory()` returns only the `### Memory {date}\n\n{content}` entries — it does not include the `## Recent Memory` header.
- Section 8: `build_system_prompt()` emits `## Skills`, then appends the string returned by `load_skills_index()`. `load_skills_index()` owns the preamble text and XML block but does NOT include the `## Skills` header.
- Section 9: `build_system_prompt()` appends the return value of `build_memory_prompt()` directly, without adding an extra header. `build_memory_prompt()` already contains the `## Memory Instructions` line as the first line of its return value. No header is emitted by `build_system_prompt()` for this section.

---

## `tool_read_file` Update

The existing `tool_read_file` raises unhandled exceptions on missing or unreadable paths.
Since the model will call this tool to load SKILL.md files, an unreadable skill file
must not crash the agentic loop.

**Updated implementation:**
```python
def tool_read_file(path: str) -> str:
    """Read a file from the filesystem.
    :param path: Path to the file.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading {path}: {e}"
```

Changes from current: adds try/except, adds `encoding='utf-8'`.

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
- If the split result has fewer than 3 elements, return `{}` immediately.
- For each non-empty line in the block: call `line.partition(":")` which splits on the
  **first colon only**, preserving values that contain colons (e.g. URLs, metadata strings).
- Strips whitespace from both key and value.
- Returns `{}` if frontmatter is absent or malformed — does NOT perform dir_name substitution.
- `load_skills_index()` (the caller) is responsible for substituting the directory name
  when `"name"` is absent, and `""` when `"description"` is absent.

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

`<location>` paths are **relative to the process working directory** (project root).
This matches how `tool_read_file` resolves paths via `open(path, "r", encoding="utf-8")`.

Skill directories are sorted using `sorted(os.listdir(...))` — bare directory names,
alphabetical, deterministic across runs.

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

Conversation history (`messages=`) and context/persona/skills (`system=`) are separate
API parameters. The session files are untouched.

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

- Unreadable workspace context files (missing, permissions, etc.): silently skipped via try/except per file in `load_context_files()`. Matches existing `load_soul()` pattern.
- Missing `workspace/skills/` directory or any `OSError` when listing it: `load_skills_index()` returns `""`.
- Skill subdirectory exists but has no `SKILL.md`, or `SKILL.md` raises exception on read: that skill entry is silently skipped.
- Plain files inside `workspace/skills/` (e.g., README.md, .DS_Store): silently skipped (`isdir()` check).
- Malformed SKILL.md frontmatter: `parse_skill_frontmatter` returns `{}`; `load_skills_index` substitutes dir name as skill name and `""` as description.
- `tool_read_file` exceptions: wrapped in try/except; returns `f"Error reading {path}: {e}"` instead of propagating. Prevents a missing or unreadable skill file from crashing the agentic loop.
- `run_agent_turn` unexpected `stop_reason` (e.g., `"max_tokens"`): extract text from response content, append to messages, return `(text, messages)`. Never returns `None`.
- Skill script execution: handled by existing `run_command` safety/approval system.

---

## Known Limitation

No size ceiling is enforced on the system prompt. For workspaces with many or large context files, the combined prompt could approach the model's context limit. This is acceptable for the current scope (personal assistant with a small workspace) and can be addressed later with per-file truncation or a total character budget.

---

## Testing Notes

- Verify `## Current Date & Time` is the first section and contains a date-only string (no hours/minutes).
- When all five CONTEXT_FILES are present, verify they appear in the order defined by `CONTEXT_FILES` (AGENTS.md, SOUL.md, USER.md, IDENTITY.md, TOOLS.md) regardless of filesystem order.
- Verify a context file with chmod 000 (unreadable) is silently skipped without crashing.
- Add `workspace/skills/test-skill/SKILL.md` with valid frontmatter → verify skill appears in system prompt XML.
- Add a skill with no frontmatter → verify graceful fallback to dir name / empty description.
- Add a skill whose SKILL.md body contains `---` as a horizontal rule → verify frontmatter is still parsed correctly.
- Add `workspace/AGENTS.md` → verify it appears before `SOUL.md` in the assembled prompt.
- Verify missing context files produce no empty `##` headers.
- Verify `workspace/memory/` daily files appear under `## Recent Memory`, today first.
- Verify only today's content is returned when yesterday's file is absent (and vice versa).
- When both today's and yesterday's files exist, verify today's content appears before yesterday's.
- Verify `./memory/` long-term files are NOT loaded into the system prompt (only via tools).
- Verify session load/save is unaffected by running an existing session after the change.
- Verify `build_system_prompt()` is called exactly once per user message, not once per API call inside the loop.
- Verify `tool_read_file` returns an error string (not an exception) for a nonexistent path.
- Verify `tool_read_file` can read a UTF-8 file with non-ASCII characters (e.g., emoji in SKILL.md).
- Verify skills appear in alphabetical order in the XML block.
- Verify `parse_skill_frontmatter` correctly handles a description value containing a colon (e.g., `description: Load files from https://example.com`).
- Verify the assembled system prompt contains `## Memory Instructions` (not `## Memory`) as the header for the memory instructions section.
- Simulate `stop_reason="max_tokens"` in `run_agent_turn` → verify a `(str, list)` tuple is returned, not `None`.

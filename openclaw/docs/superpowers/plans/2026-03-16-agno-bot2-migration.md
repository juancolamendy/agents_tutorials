# bot2 Agno Migration — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the bot1 OpenClaw CLI chatbot to the Agno agentic framework in `bot2/`, preserving full feature parity while replacing all hand-rolled infrastructure with Agno equivalents.

**Architecture:** Each bot1 custom layer maps 1-to-1 to an Agno equivalent: `ToolRegistry` → `BotToolkit(Toolkit)`, `run_agent_turn()` → `Agent.run()`, JSONL session files → `JsonlAgentDb(BaseDb)`, markdown memory → `MarkdownMemoryDb(BaseDb)` + `MemoryTools`, prompt assembly → preserved `prompt.py`. Storage is swappable by replacing one `db=` argument.

**Tech Stack:** Python 3.12, `agno>=0.5`, `anthropic`, `python-dotenv`, `pytest`

**Spec:** `docs/superpowers/specs/2026-03-16-agno-bot2-design.md`
**Research:** `bot2/CLAUDE.md`

---

## File Map

| File | Status | Responsibility |
|------|--------|----------------|
| `pyproject.toml` | Modify | Add `agno>=0.5`, add bot2 to pytest paths |
| `bot2/__init__.py` | Create | Package marker |
| `bot2/prompt.py` | Create | `build_system_prompt()` + helpers (migrated from bot1) |
| `bot2/storage.py` | Create | `JsonlAgentDb(BaseDb)` — JSONL session persistence |
| `bot2/memory_db.py` | Create | `MarkdownMemoryDb` — markdown memory files for `MemoryTools` |
| `bot2/tools.py` | Create | `BotToolkit(Toolkit)` — 4 tools: run_command, read_file, write_file, web_search |
| `bot2/main.py` | Create | CLI entry point wiring all components via `Agent` |
| `bot2/tests/__init__.py` | Create | Package marker |
| `bot2/tests/conftest.py` | Create | Set `ANTHROPIC_API_KEY` env var for tests |
| `bot2/tests/test_prompt.py` | Create | Unit tests for prompt.py (migrated from bot1/tests/test_main.py) |
| `bot2/tests/test_storage.py` | Create | Unit tests for `JsonlAgentDb` |
| `bot2/tests/test_memory_db.py` | Create | Unit tests for `MarkdownMemoryDb` |
| `bot2/tests/test_tools.py` | Create | Unit tests for `BotToolkit` |

**Working directory for all commands:** `/Users/jcolamendy/ai_ml/agents_tutorials/openclaw`

---

## Chunk 1: Project Setup + prompt.py

### Task 1: Update pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add agno dependency and bot2 test paths**

Edit `pyproject.toml`:

```toml
[project]
name = "openclaw"
version = "0.1.0"
description = "Add your description here"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "agno>=0.5",
    "anthropic>=0.84.0",
    "python-dotenv>=1.2.2",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
pythonpath = ["bot1", "bot2"]
testpaths = ["bot1/tests", "bot2/tests"]
```

- [ ] **Step 2: Install dependencies**

```bash
uv pip install -e ".[dev]"
```

Expected: Installs without errors. `python -c "import agno"` should succeed.

- [ ] **Step 3: Create package markers**

```bash
touch bot2/__init__.py bot2/tests/__init__.py
```

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml bot2/__init__.py bot2/tests/__init__.py
git commit -m "chore: scaffold bot2 package and add agno dependency"
```

---

### Task 2: Create bot2/tests/conftest.py

**Files:**
- Create: `bot2/tests/conftest.py`

- [ ] **Step 1: Write conftest.py**

```python
import os
os.environ.setdefault("ANTHROPIC_API_KEY", "test-placeholder")
```

- [ ] **Step 2: Verify pytest discovers bot2/tests**

```bash
pytest bot2/tests/ --collect-only
```

Expected: `0 errors` (no tests yet, but no import errors).

- [ ] **Step 3: Commit**

```bash
git add bot2/tests/conftest.py
git commit -m "chore: add bot2 test conftest"
```

---

### Task 3: Migrate prompt.py from bot1

The prompt assembly logic is identical to bot1. This task copies it into `bot2/prompt.py` with no functional changes.

**Files:**
- Create: `bot2/prompt.py`
- Create: `bot2/tests/test_prompt.py`

- [ ] **Step 1: Write the failing tests first**

Create `bot2/tests/test_prompt.py` — copy directly from `bot1/tests/test_main.py`, keeping only the prompt-related test classes and updating the import:

```python
import os
from datetime import datetime, timedelta

import prompt  # bot2/prompt.py


class TestParseSkillFrontmatter:

    def test_basic_frontmatter(self):
        content = "---\nname: github\ndescription: GitHub CLI.\n---\n\n# Body"
        result = prompt.parse_skill_frontmatter(content)
        assert result == {"name": "github", "description": "GitHub CLI."}

    def test_colon_in_value_preserved(self):
        content = "---\nname: web\ndescription: Load from https://example.com\n---"
        result = prompt.parse_skill_frontmatter(content)
        assert result["description"] == "Load from https://example.com"

    def test_no_frontmatter_returns_empty_dict(self):
        content = "# Just a heading\nSome content"
        result = prompt.parse_skill_frontmatter(content)
        assert result == {}

    def test_empty_string_returns_empty_dict(self):
        result = prompt.parse_skill_frontmatter("")
        assert result == {}

    def test_horizontal_rule_in_body_not_confused_with_frontmatter(self):
        content = "---\nname: test\n---\n# Body\n\n---\n\nMore content"
        result = prompt.parse_skill_frontmatter(content)
        assert result == {"name": "test"}

    def test_whitespace_stripped_from_key_and_value(self):
        content = "---\n  name :  github  \n---"
        result = prompt.parse_skill_frontmatter(content)
        assert result["name"] == "github"

    def test_emoji_in_value(self):
        content = "---\nname: github\nemoji: 🐙\n---"
        result = prompt.parse_skill_frontmatter(content)
        assert result["emoji"] == "🐙"

    def test_malformed_no_closing_delimiter(self):
        content = "---\nname: github\n"
        result = prompt.parse_skill_frontmatter(content)
        assert result == {}


class TestLoadContextFiles:

    def test_reads_existing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prompt, "WORKSPACE_DIR", str(tmp_path))
        (tmp_path / "SOUL.md").write_text("You are Jarvis.", encoding="utf-8")
        result = prompt.load_context_files()
        assert "SOUL.md" in result
        assert result["SOUL.md"] == "You are Jarvis."

    def test_missing_file_silently_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prompt, "WORKSPACE_DIR", str(tmp_path))
        result = prompt.load_context_files()
        assert result == {}

    def test_preserves_context_files_order(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prompt, "WORKSPACE_DIR", str(tmp_path))
        for fname in ["TOOLS.md", "AGENTS.md", "SOUL.md"]:
            (tmp_path / fname).write_text(f"# {fname}", encoding="utf-8")
        result = prompt.load_context_files()
        keys = list(result.keys())
        assert keys.index("AGENTS.md") < keys.index("SOUL.md")
        assert keys.index("SOUL.md") < keys.index("TOOLS.md")

    def test_unreadable_file_silently_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prompt, "WORKSPACE_DIR", str(tmp_path))
        soul = tmp_path / "SOUL.md"
        soul.write_text("content", encoding="utf-8")
        soul.chmod(0o000)
        try:
            result = prompt.load_context_files()
            assert "SOUL.md" not in result
        finally:
            soul.chmod(0o644)

    def test_reads_utf8_content(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prompt, "WORKSPACE_DIR", str(tmp_path))
        (tmp_path / "SOUL.md").write_text("Name: Jàrvis 🤖", encoding="utf-8")
        result = prompt.load_context_files()
        assert result["SOUL.md"] == "Name: Jàrvis 🤖"

    def test_only_context_files_loaded(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prompt, "WORKSPACE_DIR", str(tmp_path))
        (tmp_path / "SOUL.md").write_text("soul", encoding="utf-8")
        (tmp_path / "OTHER.md").write_text("other", encoding="utf-8")
        result = prompt.load_context_files()
        assert "OTHER.md" not in result
        assert "SOUL.md" in result


class TestLoadDailyMemory:

    def test_returns_empty_if_no_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prompt, "WORKSPACE_DIR", str(tmp_path))
        result = prompt.load_daily_memory()
        assert result == ""

    def test_reads_todays_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prompt, "WORKSPACE_DIR", str(tmp_path))
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        today = datetime.now().strftime("%Y-%m-%d")
        (memory_dir / f"{today}.md").write_text("Today content", encoding="utf-8")
        result = prompt.load_daily_memory()
        assert f"### Memory {today}" in result
        assert "Today content" in result

    def test_today_appears_before_yesterday(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prompt, "WORKSPACE_DIR", str(tmp_path))
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        (memory_dir / f"{today}.md").write_text("Today", encoding="utf-8")
        (memory_dir / f"{yesterday}.md").write_text("Yesterday", encoding="utf-8")
        result = prompt.load_daily_memory()
        assert result.index(f"### Memory {today}") < result.index(f"### Memory {yesterday}")

    def test_missing_yesterday_returns_only_today(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prompt, "WORKSPACE_DIR", str(tmp_path))
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        today = datetime.now().strftime("%Y-%m-%d")
        (memory_dir / f"{today}.md").write_text("Only today", encoding="utf-8")
        result = prompt.load_daily_memory()
        assert "Only today" in result
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        assert f"### Memory {yesterday}" not in result


class TestLoadSkillsIndex:

    def test_returns_empty_if_no_skills_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prompt, "WORKSPACE_DIR", str(tmp_path))
        result = prompt.load_skills_index()
        assert result == ""

    def test_basic_skill_appears_in_xml(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prompt, "WORKSPACE_DIR", str(tmp_path))
        skill_dir = tmp_path / "skills" / "github"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: github\ndescription: GitHub CLI.\n---\n# GitHub",
            encoding="utf-8",
        )
        result = prompt.load_skills_index()
        assert "<name>github</name>" in result
        assert "<description>GitHub CLI.</description>" in result
        assert "SKILL.md" in result
        assert "read_file" in result

    def test_skills_sorted_alphabetically(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prompt, "WORKSPACE_DIR", str(tmp_path))
        for name in ["weather", "github", "calendar"]:
            d = tmp_path / "skills" / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(f"---\nname: {name}\n---", encoding="utf-8")
        result = prompt.load_skills_index()
        assert result.index("calendar") < result.index("github") < result.index("weather")

    def test_xml_special_chars_escaped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prompt, "WORKSPACE_DIR", str(tmp_path))
        skill_dir = tmp_path / "skills" / "myskill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test\ndescription: Load <data> & save\n---",
            encoding="utf-8",
        )
        result = prompt.load_skills_index()
        assert "<data>" not in result
        assert "&lt;data&gt;" in result
        assert "&amp;" in result


class TestBuildSystemPrompt:

    def test_date_section_always_first(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prompt, "WORKSPACE_DIR", str(tmp_path))
        result = prompt.build_system_prompt()
        assert result.startswith("## Current Date & Time")

    def test_memory_instructions_always_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prompt, "WORKSPACE_DIR", str(tmp_path))
        result = prompt.build_system_prompt()
        assert "## Memory Instructions" in result

    def test_soul_md_included_when_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prompt, "WORKSPACE_DIR", str(tmp_path))
        (tmp_path / "SOUL.md").write_text("You are Jarvis.", encoding="utf-8")
        result = prompt.build_system_prompt()
        assert "## SOUL.md" in result
        assert "You are Jarvis." in result

    def test_skills_section_included_when_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prompt, "WORKSPACE_DIR", str(tmp_path))
        skill_dir = tmp_path / "skills" / "github"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: github\ndescription: GitHub CLI.\n---", encoding="utf-8"
        )
        result = prompt.build_system_prompt()
        assert "## Skills" in result
        assert "github" in result
```

- [ ] **Step 2: Run tests to confirm they all fail (import error)**

```bash
pytest bot2/tests/test_prompt.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'prompt'`

- [ ] **Step 3: Create bot2/prompt.py**

Copy `bot1/main.py`'s prompt-related functions verbatim. The only change: rename the module-level constants to be explicit about their scope.

```python
import html
import os
import re
from datetime import datetime, timedelta

WORKSPACE_DIR = "./workspace"
CONTEXT_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "IDENTITY.md", "TOOLS.md"]


def parse_skill_frontmatter(content: str) -> dict:
    """Parse YAML-style frontmatter from a SKILL.md file."""
    parts = re.split(r"^---\s*$", content, maxsplit=2, flags=re.MULTILINE)
    if len(parts) < 3:
        return {}
    meta = {}
    for line in parts[1].splitlines():
        if not line.strip():
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta


def load_context_files() -> dict:
    """Load workspace context markdown files in CONTEXT_FILES order."""
    context = {}
    for filename in CONTEXT_FILES:
        path = os.path.join(WORKSPACE_DIR, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                context[filename] = f.read()
        except Exception:
            pass
    return context


def load_daily_memory() -> str:
    """Load today's and yesterday's daily memory logs from workspace/memory/."""
    entries = []
    for delta in [0, 1]:
        date_str = (datetime.now() - timedelta(days=delta)).strftime("%Y-%m-%d")
        path = os.path.join(WORKSPACE_DIR, "memory", f"{date_str}.md")
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            entries.append(f"### Memory {date_str}\n\n{content}")
        except Exception:
            pass
    return "\n\n".join(entries)


def load_skills_index() -> str:
    """Scan workspace/skills/ and build a compact XML skills index."""
    skills_dir = os.path.join(WORKSPACE_DIR, "skills")
    try:
        entries = sorted(os.listdir(skills_dir))
    except OSError:
        return ""

    skills = []
    for name in entries:
        dir_path = os.path.join(skills_dir, name)
        if not os.path.isdir(dir_path):
            continue
        skill_file = os.path.join(dir_path, "SKILL.md")
        try:
            with open(skill_file, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        meta = parse_skill_frontmatter(content)
        skills.append({
            "name": meta.get("name", name),
            "description": meta.get("description", ""),
            "location": os.path.join(WORKSPACE_DIR, "skills", name, "SKILL.md"),
        })

    if not skills:
        return ""

    xml_entries = "\n".join(
        f"  <skill>\n"
        f"    <name>{html.escape(s['name'])}</name>\n"
        f"    <description>{html.escape(s['description'])}</description>\n"
        f"    <location>{html.escape(s['location'])}</location>\n"
        f"  </skill>"
        for s in skills
    )
    return (
        "When a task matches one of the skills below, use the `read_file` tool to "
        "load the SKILL.md at the listed location for detailed instructions.\n\n"
        f"<available_skills>\n{xml_entries}\n</available_skills>"
    )


def _build_memory_prompt() -> str:
    # Private helper (renamed from bot1's `build_memory_prompt` — intentional,
    # it is an internal detail not part of the public prompt.py API).
    return """## Memory Instructions
You have a long-term memory system.
- Use save_memory to store important information (user preferences, key facts, project details).
- Use memory_search at the start of conversations to recall context from previous sessions.
Memory files are stored in ./memory/ as markdown files."""


def build_system_prompt() -> str:
    """Assemble the full system prompt from workspace files, skills index, and memory instructions."""
    parts = []

    date_str = datetime.now().strftime("%A, %B %d, %Y")
    parts.append(f"## Current Date & Time\n\n{date_str}")

    for filename, content in load_context_files().items():
        if content:
            parts.append(f"## {filename}\n\n{content}")

    daily_mem = load_daily_memory()
    if daily_mem:
        parts.append(f"## Recent Memory\n\n{daily_mem}")

    skills = load_skills_index()
    if skills:
        parts.append(f"## Skills\n\n{skills}")

    parts.append(_build_memory_prompt())

    return "\n\n".join(parts)
```

- [ ] **Step 4: Run tests**

```bash
pytest bot2/tests/test_prompt.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add bot2/prompt.py bot2/tests/test_prompt.py
git commit -m "feat(bot2): migrate prompt assembly from bot1"
```

---

## Chunk 2: JsonlAgentDb

### Task 4: Implement JsonlAgentDb

**Files:**
- Create: `bot2/storage.py`
- Create: `bot2/tests/test_storage.py`

> **MANDATORY — do not skip:** Run the inspection steps below and confirm results
> before writing any code. The implementation depends on Agno's exact abstract
> method signatures. Implementing without verifying will cause `TypeError: Can't
> instantiate abstract class` at runtime.

- [ ] **Step 0 (BLOCKING): Inspect BaseDb and AgentSession**

```bash
# 1. Confirm BaseDb import path and list abstract methods
python -c "from agno.db.base import BaseDb; import inspect; print(inspect.getsource(BaseDb))" 2>&1

# 2. Confirm AgentSession import path
python -c "from agno.db.session import AgentSession; s = AgentSession(session_id='x', user_id=None); print('AgentSession OK, user_id=None accepted')" 2>&1
```

**Read the output carefully:**
- List every `@abstractmethod` in `BaseDb` — these MUST be implemented in `JsonlAgentDb`
- If `from agno.db.session import AgentSession` fails, try `from agno.models.session import AgentSession` or search: `python -c "import agno; import pkgutil; [print(m.name) for m in pkgutil.walk_packages(agno.__path__, 'agno.') if 'session' in m.name]"`
- If `AgentSession(user_id=None)` raises a validation error, the `test_read_with_no_user_id` test must be removed or adjusted
- If `BaseDb` abstract method signatures differ from the plan, update `storage.py` and `test_storage.py` accordingly before proceeding

- [ ] **Step 1: Write the failing tests**

Create `bot2/tests/test_storage.py`:

```python
import json
import os

import pytest

from storage import JsonlAgentDb


@pytest.fixture
def db(tmp_path):
    return JsonlAgentDb(sessions_dir=str(tmp_path))


class TestJsonlAgentDb:

    def test_read_returns_none_for_missing_session(self, db):
        result = db.read(session_id="s1", user_id="u1")
        assert result is None

    def test_upsert_and_read_roundtrip(self, db):
        from agno.db.session import AgentSession
        session = AgentSession(session_id="s1", user_id="u1")
        db.upsert(session)
        loaded = db.read(session_id="s1", user_id="u1")
        assert loaded is not None
        assert loaded.session_id == "s1"
        assert loaded.user_id == "u1"

    def test_upsert_overwrites_existing(self, db):
        from agno.db.session import AgentSession
        # First upsert with no runs; second with a modified state
        s1 = AgentSession(session_id="s1", user_id="u1")
        db.upsert(s1)
        # Modify the session and upsert again — read should return the updated state
        s2 = AgentSession(session_id="s1", user_id="u1")
        db.upsert(s2)
        loaded = db.read(session_id="s1", user_id="u1")
        assert loaded is not None
        assert loaded.session_id == "s1"

    def test_get_all_session_ids_returns_ids_for_user(self, db):
        from agno.db.session import AgentSession
        db.upsert(AgentSession(session_id="s1", user_id="u1"))
        db.upsert(AgentSession(session_id="s2", user_id="u1"))
        db.upsert(AgentSession(session_id="s3", user_id="u2"))
        ids = db.get_all_session_ids(user_id="u1")
        assert set(ids) == {"s1", "s2"}

    def test_get_all_session_ids_none_user_returns_all(self, db):
        from agno.db.session import AgentSession
        db.upsert(AgentSession(session_id="s1", user_id="u1"))
        db.upsert(AgentSession(session_id="s2", user_id="u2"))
        ids = db.get_all_session_ids(user_id=None)
        assert set(ids) == {"s1", "s2"}

    def test_get_all_sessions_returns_session_objects(self, db):
        from agno.db.session import AgentSession
        db.upsert(AgentSession(session_id="s1", user_id="u1"))
        sessions = db.get_all_sessions(user_id="u1")
        assert len(sessions) == 1
        assert sessions[0].session_id == "s1"

    def test_delete_session_removes_file(self, db, tmp_path):
        from agno.db.session import AgentSession
        db.upsert(AgentSession(session_id="s1", user_id="u1"))
        db.delete_session(session_id="s1")
        path = tmp_path / "u1_s1.jsonl"
        assert not path.exists()

    def test_delete_nonexistent_session_does_not_raise(self, db):
        db.delete_session(session_id="doesnt-exist")  # should not raise

    def test_session_file_named_userid_sessionid(self, db, tmp_path):
        from agno.db.session import AgentSession
        db.upsert(AgentSession(session_id="mysession", user_id="myuser"))
        assert (tmp_path / "myuser_mysession.jsonl").exists()

    def test_read_with_no_user_id(self, db):
        from agno.db.session import AgentSession
        db.upsert(AgentSession(session_id="s1", user_id=None))
        result = db.read(session_id="s1", user_id=None)
        assert result is not None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest bot2/tests/test_storage.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'storage'`

> If the error is `ModuleNotFoundError: No module named 'agno.db.session'` instead,
> fix the `AgentSession` import path first (see Step 0), then re-run.

- [ ] **Step 3: Implement JsonlAgentDb**

Create `bot2/storage.py`:

```python
import json
import os
from typing import Optional

from agno.db.base import BaseDb
from agno.db.session import AgentSession


class JsonlAgentDb(BaseDb):
    """JSONL-backed agent storage. Each session is one file: sessions/{user_id}_{session_id}.jsonl.
    Uses the same file naming convention as bot1 but stores AgentSession objects (not raw
    message lists). Bot1 session files are NOT byte-compatible but filenames are preserved.
    Swap to SqliteDb/PostgresDb at construction."""

    def __init__(self, sessions_dir: str = "./sessions"):
        self.sessions_dir = sessions_dir
        os.makedirs(sessions_dir, exist_ok=True)

    def _path(self, session_id: str, user_id: Optional[str]) -> str:
        prefix = user_id if user_id else "anonymous"
        return os.path.join(self.sessions_dir, f"{prefix}_{session_id}.jsonl")

    def _find_path(self, session_id: str) -> Optional[str]:
        """Locate the file for session_id regardless of user_id prefix.
        Uses exact suffix match to avoid session ID collision (e.g. 's1' matching 'long-s1')."""
        suffix = f"_{session_id}.jsonl"
        for fname in os.listdir(self.sessions_dir):
            # Split on '_' and compare the session_id part exactly
            if fname == f"anonymous_{session_id}.jsonl":
                return os.path.join(self.sessions_dir, fname)
            parts = fname.rsplit("_", 1)
            if len(parts) == 2 and parts[1] == f"{session_id}.jsonl":
                return os.path.join(self.sessions_dir, fname)
        return None

    def read(self, session_id: str, user_id: Optional[str] = None) -> Optional[AgentSession]:
        path = self._path(session_id, user_id)
        if not os.path.exists(path):
            path = self._find_path(session_id)
        if not path or not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            lines = [json.loads(l) for l in f if l.strip()]
        if not lines:
            return None
        data = lines[-1]  # last line is the authoritative state
        return AgentSession(**data)

    def upsert(self, session: AgentSession) -> Optional[AgentSession]:
        path = self._path(session.session_id, session.user_id)
        data = session.model_dump() if hasattr(session, "model_dump") else session.__dict__
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")
        return session

    def get_all_session_ids(self, user_id: Optional[str] = None) -> list[str]:
        sessions = self.get_all_sessions(user_id=user_id)
        return [s.session_id for s in sessions]

    def get_all_sessions(self, user_id: Optional[str] = None) -> list[AgentSession]:
        results = []
        for fname in os.listdir(self.sessions_dir):
            if not fname.endswith(".jsonl"):
                continue
            path = os.path.join(self.sessions_dir, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    lines = [json.loads(l) for l in f if l.strip()]
                if not lines:
                    continue
                session = AgentSession(**lines[-1])
                if user_id is None or session.user_id == user_id:
                    results.append(session)
            except Exception:
                continue
        return results

    def delete_session(self, session_id: str) -> None:
        path = self._find_path(session_id)
        if path and os.path.exists(path):
            os.remove(path)
```

- [ ] **Step 4: Run tests**

```bash
pytest bot2/tests/test_storage.py -v
```

Expected: All tests pass.

> **If `AgentSession` import path differs:** run `python -c "from agno.db.session import AgentSession; print('ok')"`. If that fails, try `from agno.models.session import AgentSession` or check `agno.db` submodules. Adjust the import in both `storage.py` and `test_storage.py`.

- [ ] **Step 5: Commit**

```bash
git add bot2/storage.py bot2/tests/test_storage.py
git commit -m "feat(bot2): implement JsonlAgentDb for JSONL session persistence"
```

---

## Chunk 3: MarkdownMemoryDb

### Task 5: Implement MarkdownMemoryDb

**Files:**
- Create: `bot2/memory_db.py`
- Create: `bot2/tests/test_memory_db.py`

> **MANDATORY — do not skip:** Run Step 1 first and confirm the exact method names
> `MemoryTools` calls on its `db` object before writing any code. The adapter method
> names in the implementation are placeholder names only. Wrong names cause silent
> failures — `MemoryTools` will initialize but never route calls to `MarkdownMemoryDb`.

- [ ] **Step 1 (BLOCKING): Inspect MemoryTools interface and confirm adapter method names**

```bash
# Full source — find what methods are called on self.db
python -c "from agno.tools.memory import MemoryTools; import inspect; print(inspect.getsource(MemoryTools))" 2>&1

# Quick scan — just list attribute accesses on self.db
python -c "
import inspect, re
from agno.tools.memory import MemoryTools
src = inspect.getsource(MemoryTools)
# find all 'self.db.<method>' calls
methods = re.findall(r'self\.db\.(\w+)\(', src)
print('Methods called on self.db:', set(methods))
" 2>&1
```

Read the output carefully. **Update the adapter method names** in the implementation
below to match the actual method names Agno calls.

For example:
- If output shows `{'save_memory', 'search_memories'}` → keep `upsert_memory`/`search_memories` as aliases, or rename
- If output shows `{'add', 'search'}` → rename adapter methods accordingly
- If output shows nothing (MemoryTools uses a different pattern) → check if `db=` is passed directly to individual tool functions and trace the call path

Note the exact names before proceeding.

- [ ] **Step 2: Write the failing tests**

Create `bot2/tests/test_memory_db.py`:

```python
import os
import pytest
from memory_db import MarkdownMemoryDb


@pytest.fixture
def db(tmp_path):
    return MarkdownMemoryDb(memory_dir=str(tmp_path))


class TestMarkdownMemoryDb:

    def test_save_creates_md_file(self, db, tmp_path):
        db.save("user-prefs", "I like Python")
        assert (tmp_path / "user-prefs.md").exists()

    def test_save_and_load_roundtrip(self, db, tmp_path):
        db.save("user-prefs", "I like Python")
        content = (tmp_path / "user-prefs.md").read_text(encoding="utf-8")
        assert content == "I like Python"

    def test_search_returns_matching_file(self, db):
        db.save("python-notes", "I like Python and pip")
        db.save("java-notes", "I use Java at work")
        results = db.search("Python")
        assert any("python-notes" in r for r in results)

    def test_search_case_insensitive(self, db):
        db.save("notes", "I like PYTHON")
        results = db.search("python")
        assert len(results) > 0

    def test_search_returns_empty_list_for_no_match(self, db):
        db.save("notes", "I like Python")
        results = db.search("ruby")
        assert results == []

    def test_search_matches_multiple_words(self, db):
        db.save("notes", "Python and Django")
        results = db.search("Python Django")
        assert len(results) > 0

    def test_save_overwrites_existing(self, db, tmp_path):
        db.save("key", "old content")
        db.save("key", "new content")
        content = (tmp_path / "key.md").read_text(encoding="utf-8")
        assert content == "new content"

    def test_empty_memory_dir_search_returns_empty(self, db):
        results = db.search("anything")
        assert results == []

    # --- Adapter method tests ---
    # Replace `upsert_memory` and `search_memories` with the actual names
    # you confirmed from Step 1's MemoryTools inspection.

    def test_upsert_memory_creates_file(self, db, tmp_path):
        db.upsert_memory("key1", "value1")
        assert (tmp_path / "key1.md").exists()

    def test_search_memories_returns_results(self, db):
        db.upsert_memory("key2", "remember this")
        results = db.search_memories("remember")
        assert len(results) > 0
        assert any("remember this" in r for r in results)
```

- [ ] **Step 3: Run tests to confirm they fail**

```bash
pytest bot2/tests/test_memory_db.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'memory_db'`

- [ ] **Step 4: Implement MarkdownMemoryDb**

Create `bot2/memory_db.py`.

> **Important:** After running the MemoryTools inspection in Step 1, adjust the class
> to satisfy whatever interface `MemoryTools` actually expects. The `save` and `search`
> methods below are the core logic — wrap them in whatever method names Agno needs.

```python
import os
from typing import List


class MarkdownMemoryDb:
    """Markdown-file-backed memory store. Stores memory/{key}.md files.
    Passed to MemoryTools(db=MarkdownMemoryDb(memory_dir)).
    Compatible with bot1's memory/*.md format.

    Note: 'memory_dir' stores long-term agent memory (save_memory/memory_search).
    This is separate from workspace/memory/ daily logs (read into system prompt).
    """

    def __init__(self, memory_dir: str = "./memory"):
        self.memory_dir = memory_dir
        os.makedirs(memory_dir, exist_ok=True)

    def save(self, key: str, content: str) -> str:
        """Save content to memory/{key}.md. Returns the key."""
        filepath = os.path.join(self.memory_dir, f"{key}.md")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return key

    def search(self, query: str) -> List[str]:
        """Keyword search across all memory/*.md files.
        Returns list of '--- key.md ---\\ncontent' strings for matching files."""
        q = query.lower()
        results = []
        try:
            filenames = os.listdir(self.memory_dir)
        except OSError:
            return []
        for fname in filenames:
            if not fname.endswith(".md"):
                continue
            try:
                with open(os.path.join(self.memory_dir, fname), "r", encoding="utf-8") as f:
                    content = f.read()
                if any(word in content.lower() for word in q.split()):
                    results.append(f"--- {fname} ---\n{content}")
            except Exception:
                continue
        return results

    # --- MemoryTools adapter methods ---
    # Agno's MemoryTools calls these methods on the db object.
    # If inspection (Task 5 Step 1) reveals different method names, rename accordingly.

    def upsert_memory(self, key: str, content: str) -> str:
        """Adapter: called by MemoryTools to save a memory."""
        return self.save(key, content)

    def search_memories(self, query: str) -> List[str]:
        """Adapter: called by MemoryTools to search memories."""
        return self.search(query)
```

- [ ] **Step 5: Run tests**

```bash
pytest bot2/tests/test_memory_db.py -v
```

Expected: All tests pass.

- [ ] **Step 6: Verify MemoryTools accepts MarkdownMemoryDb**

```bash
python -c "
from memory_db import MarkdownMemoryDb
from agno.tools.memory import MemoryTools
db = MarkdownMemoryDb('/tmp/test-mem')
tools = MemoryTools(db=db)
print('MemoryTools initialized OK')
"
```

Expected: `MemoryTools initialized OK`. If it raises, check the error and add any missing methods to `MarkdownMemoryDb`.

- [ ] **Step 7: Commit**

```bash
git add bot2/memory_db.py bot2/tests/test_memory_db.py
git commit -m "feat(bot2): implement MarkdownMemoryDb for MemoryTools integration"
```

---

## Chunk 4: BotToolkit

### Task 6: Implement BotToolkit

**Files:**
- Create: `bot2/tools.py`
- Create: `bot2/tests/test_tools.py`

- [ ] **Step 1: Write the failing tests**

Create `bot2/tests/test_tools.py`:

```python
import json
import os
from unittest.mock import patch

import pytest

from tools import BotToolkit, SAFE_COMMANDS


@pytest.fixture
def toolkit(tmp_path):
    return BotToolkit(approvals_file=str(tmp_path / "approvals.json"))


class TestRunCommand:

    def test_safe_command_runs_without_approval(self, toolkit):
        result = toolkit.run_command("echo hello")
        assert "hello" in result

    def test_safe_command_set_includes_expected_commands(self):
        assert "ls" in SAFE_COMMANDS
        assert "cat" in SAFE_COMMANDS
        assert "echo" in SAFE_COMMANDS

    def test_denied_command_returns_denied_message(self, toolkit, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "n")
        result = toolkit.run_command("rm -rf /tmp/nonexistent")
        assert "denied" in result.lower()

    def test_approved_command_runs(self, toolkit, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "y")
        result = toolkit.run_command("date")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_previously_approved_command_skips_prompt(self, toolkit, tmp_path, monkeypatch):
        approvals = {"allowed": ["date"], "denied": []}
        approvals_file = str(tmp_path / "approvals.json")
        with open(approvals_file, "w") as f:
            json.dump(approvals, f)
        tk = BotToolkit(approvals_file=approvals_file)
        # No monkeypatch of input — should not prompt
        result = tk.run_command("date")
        assert isinstance(result, str)


class TestReadFile:

    def test_reads_existing_file(self, toolkit, tmp_path):
        path = tmp_path / "test.txt"
        path.write_text("hello", encoding="utf-8")
        result = toolkit.read_file(str(path))
        assert result == "hello"

    def test_missing_file_returns_error_string(self, toolkit, tmp_path):
        result = toolkit.read_file(str(tmp_path / "nonexistent.txt"))
        assert "Error reading" in result
        assert isinstance(result, str)

    def test_reads_utf8_with_emoji(self, toolkit, tmp_path):
        path = tmp_path / "test.md"
        path.write_text("Hello 🌍", encoding="utf-8")
        result = toolkit.read_file(str(path))
        assert result == "Hello 🌍"


class TestWriteFile:

    def test_writes_content_to_file(self, toolkit, tmp_path):
        path = tmp_path / "out.txt"
        result = toolkit.write_file(str(path), "content here")
        assert path.read_text(encoding="utf-8") == "content here"
        assert "Wrote" in result

    def test_overwrites_existing_file(self, toolkit, tmp_path):
        path = tmp_path / "out.txt"
        path.write_text("old", encoding="utf-8")
        toolkit.write_file(str(path), "new")
        assert path.read_text(encoding="utf-8") == "new"


class TestWebSearch:

    def test_returns_string(self, toolkit):
        result = toolkit.web_search("test query")
        assert isinstance(result, str)
        assert len(result) > 0


class TestToolkitRegistration:

    def test_all_four_tools_registered(self, toolkit):
        from agno.tools import Toolkit
        assert isinstance(toolkit, Toolkit)
        tool_names = [t.name for t in toolkit.tools]
        assert "run_command" in tool_names
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "web_search" in tool_names

    def test_memory_tools_not_registered(self, toolkit):
        tool_names = [t.name for t in toolkit.tools]
        assert "save_memory" not in tool_names
        assert "memory_search" not in tool_names
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest bot2/tests/test_tools.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'tools'`

- [ ] **Step 3: Implement BotToolkit**

Create `bot2/tools.py`:

```python
import json
import os
import re
import subprocess

from agno.tools import Toolkit

SAFE_COMMANDS = {"ls", "cat", "head", "tail", "wc", "date", "whoami", "echo"}
DANGEROUS_PATTERNS = [r"\brm\b", r"\bsudo\b", r"\bchmod\b", r"\bcurl.*\|.*sh"]
_DEFAULT_APPROVALS_FILE = "./workspace/exec-approvals.json"


class BotToolkit(Toolkit):
    """Tools for the bot: shell commands, file I/O, web search.
    Does NOT include save_memory or memory_search — those are in MemoryTools."""

    def __init__(self, approvals_file: str = _DEFAULT_APPROVALS_FILE):
        self.approvals_file = approvals_file
        super().__init__(
            name="bot_tools",
            tools=[self.run_command, self.read_file, self.write_file, self.web_search],
        )

    def _load_approvals(self) -> dict:
        if os.path.exists(self.approvals_file):
            with open(self.approvals_file) as f:
                return json.load(f)
        return {"allowed": [], "denied": []}

    def _save_approval(self, command: str, approved: bool) -> None:
        approvals = self._load_approvals()
        key = "allowed" if approved else "denied"
        if command not in approvals[key]:
            approvals[key].append(command)
        os.makedirs(os.path.dirname(self.approvals_file) or ".", exist_ok=True)
        with open(self.approvals_file, "w") as f:
            json.dump(approvals, f, indent=2)

    def _check_command_safety(self, command: str) -> str:
        """Returns 'safe', 'approved', or 'needs_approval'."""
        base_cmd = command.strip().split()[0] if command.strip() else ""
        if base_cmd in SAFE_COMMANDS:
            return "safe"
        approvals = self._load_approvals()
        if command in approvals["allowed"]:
            return "approved"
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, command):
                return "needs_approval"
        return "needs_approval"

    def run_command(self, command: str) -> str:
        """Run a shell command on the user's computer.

        Args:
            command: The shell command to run.

        Returns:
            The stdout and stderr of the command.
        """
        safety = self._check_command_safety(command)
        if safety == "needs_approval":
            print(f"  [approval needed] {command}")
            answer = input("  Allow this command? (y/n): ").strip().lower()
            approved = answer == "y"
            self._save_approval(command, approved)
            if not approved:
                return "Command denied by user."

        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30
        )
        return result.stdout + result.stderr

    def read_file(self, path: str) -> str:
        """Read a file from the filesystem.

        Args:
            path: Path to the file.

        Returns:
            The file contents, or an error string if unreadable.
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"Error reading {path}: {e}"

    def write_file(self, path: str, content: str) -> str:
        """Write content to a file.

        Args:
            path: Path to the file.
            content: Content to write.

        Returns:
            Confirmation message.
        """
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Wrote to {path}"

    def web_search(self, query: str) -> str:
        """Search the web for information.

        Args:
            query: Search query.

        Returns:
            Search results string.
        """
        return f"Search results for: {query}"
```

- [ ] **Step 4: Run tests**

```bash
pytest bot2/tests/test_tools.py -v
```

Expected: All tests pass.

> **If `toolkit.tools` is not iterable or has a different shape:** Agno's `Toolkit` may
> store registered tools differently. Check with:
> ```bash
> python -c "from agno.tools import Toolkit; import inspect; print([m for m in dir(Toolkit) if not m.startswith('_')])"
> ```
> Adjust `TestToolkitRegistration` to match the actual attribute name.

- [ ] **Step 5: Commit**

```bash
git add bot2/tools.py bot2/tests/test_tools.py
git commit -m "feat(bot2): implement BotToolkit with run_command, read_file, write_file, web_search"
```

---

## Chunk 5: main.py + Integration

### Task 7: Wire main.py

**Files:**
- Create: `bot2/main.py`

- [ ] **Step 1: Copy workspace directory from bot1**

bot2 needs the workspace files (SOUL.md, skills/, etc.) that define the bot's identity.

```bash
cp -r bot1/workspace bot2/workspace
mkdir -p bot2/sessions bot2/memory
```

- [ ] **Step 2: Create bot2/.env**

```bash
cp bot1/.env bot2/.env 2>/dev/null || echo "ANTHROPIC_API_KEY=your-key-here" > bot2/.env
```

- [ ] **Step 3: Implement main.py**

Create `bot2/main.py`:

```python
import os
from datetime import datetime

from dotenv import load_dotenv

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.memory import MemoryTools

from memory_db import MarkdownMemoryDb
from prompt import build_system_prompt
from storage import JsonlAgentDb
from tools import BotToolkit

load_dotenv()

# Resolve paths relative to this file so the bot works from any working directory
_HERE = os.path.dirname(os.path.abspath(__file__))
SESSIONS_DIR = os.path.join(_HERE, "sessions")
MEMORY_DIR = os.path.join(_HERE, "memory")

os.makedirs(SESSIONS_DIR, exist_ok=True)
os.makedirs(MEMORY_DIR, exist_ok=True)


def build_agent() -> Agent:
    return Agent(
        model=Claude(id="claude-sonnet-4-6"),
        tools=[
            BotToolkit(),
            MemoryTools(db=MarkdownMemoryDb(MEMORY_DIR)),
        ],
        db=JsonlAgentDb(sessions_dir=SESSIONS_DIR),
        system_message=build_system_prompt(),
        add_history_to_context=True,
        num_history_runs=20,
        max_tool_calls_from_history=5,
    )


def main():
    user_id = input("Enter your user ID: ").strip() or "default"
    session_id = (
        input("Enter your session ID: ").strip()
        or datetime.now().strftime("%Y%m%d%H%M%S")
    )
    print(
        f"Session loaded for user '{user_id}', session '{session_id}'. "
        "Type /quit or /exit to quit. Type /new to reset the session."
    )

    agent = build_agent()

    while True:
        text = input("You: ")
        if text in ["/quit", "/exit"]:
            print("Goodbye!")
            break
        if text == "/new":
            session_id = datetime.now().strftime("%Y%m%d%H%M%S")
            print(f"Session reset. New session ID: {session_id}")
            continue
        response = agent.run(text, user_id=user_id, session_id=session_id)
        print(f"Claude: {response.content or ''}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Smoke test — import check (no API key needed)**

```bash
cd bot2 && python -c "
import os; os.environ['ANTHROPIC_API_KEY'] = 'test'
from main import build_agent
agent = build_agent()
print('Agent built OK')
# agent.tools holds Toolkit/MemoryTools objects, not individual functions
# Print toolkit-level names to confirm wiring
print('Toolkits:', [getattr(t, 'name', type(t).__name__) for t in agent.tools])
"
```

Expected output (toolkit names, not individual function names):
```
Agent built OK
Toolkits: ['bot_tools', 'memory']
```

> The exact names depend on Agno version. What matters is:
> 1. No exception is raised
> 2. Two toolkits appear — `BotToolkit` and `MemoryTools`
> 3. The agent's `db` is a `JsonlAgentDb` (check with `print(type(agent.db))` if needed)

- [ ] **Step 5: Run all bot2 tests**

```bash
cd /Users/jcolamendy/ai_ml/agents_tutorials/openclaw
pytest bot2/tests/ -v
```

Expected: All tests pass.

- [ ] **Step 6: Run bot1 tests to confirm no regressions**

```bash
pytest bot1/tests/ -v
```

Expected: All existing bot1 tests still pass.

- [ ] **Step 7: Commit**

```bash
git add bot2/main.py bot2/workspace bot2/sessions bot2/memory bot2/.env
git commit -m "feat(bot2): wire main.py — Agno migration complete"
```

---

## Final Verification

- [ ] **Run full test suite**

```bash
pytest -v
```

Expected: All tests (bot1 + bot2) pass.

- [ ] **Manual smoke test (requires real API key)**

```bash
cd bot2
python main.py
# Enter user ID: testuser
# Enter session ID: (press enter for auto)
# You: What's today's date?
# Claude: [response]
# You: /quit
```

Expected: Bot responds, session file appears in `bot2/sessions/`.

- [ ] **Final commit**

```bash
git add -A
git commit -m "chore: bot2 Agno migration complete — all tests passing"
```

import os
from datetime import datetime, timedelta

import main


class TestParseSkillFrontmatter:

    def test_basic_frontmatter(self):
        content = "---\nname: github\ndescription: GitHub CLI.\n---\n\n# Body"
        result = main.parse_skill_frontmatter(content)
        assert result == {"name": "github", "description": "GitHub CLI."}

    def test_colon_in_value_preserved(self):
        content = "---\nname: web\ndescription: Load from https://example.com\n---"
        result = main.parse_skill_frontmatter(content)
        assert result["description"] == "Load from https://example.com"

    def test_no_frontmatter_returns_empty_dict(self):
        content = "# Just a heading\nSome content"
        result = main.parse_skill_frontmatter(content)
        assert result == {}

    def test_empty_string_returns_empty_dict(self):
        result = main.parse_skill_frontmatter("")
        assert result == {}

    def test_horizontal_rule_in_body_not_confused_with_frontmatter(self):
        content = "---\nname: test\n---\n# Body\n\n---\n\nMore content"
        result = main.parse_skill_frontmatter(content)
        assert result == {"name": "test"}

    def test_whitespace_stripped_from_key_and_value(self):
        content = "---\n  name :  github  \n---"
        result = main.parse_skill_frontmatter(content)
        assert result["name"] == "github"

    def test_emoji_in_value(self):
        content = "---\nname: github\nemoji: 🐙\n---"
        result = main.parse_skill_frontmatter(content)
        assert result["emoji"] == "🐙"

    def test_malformed_no_closing_delimiter(self):
        content = "---\nname: github\n"
        result = main.parse_skill_frontmatter(content)
        assert result == {}


class TestLoadContextFiles:

    def test_reads_existing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        (tmp_path / "SOUL.md").write_text("You are Jarvis.", encoding="utf-8")
        result = main.load_context_files()
        assert "SOUL.md" in result
        assert result["SOUL.md"] == "You are Jarvis."

    def test_missing_file_silently_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        # No files created
        result = main.load_context_files()
        assert result == {}

    def test_preserves_context_files_order(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        for fname in ["TOOLS.md", "AGENTS.md", "SOUL.md"]:
            (tmp_path / fname).write_text(f"# {fname}", encoding="utf-8")
        result = main.load_context_files()
        keys = list(result.keys())
        assert keys.index("AGENTS.md") < keys.index("SOUL.md")
        assert keys.index("SOUL.md") < keys.index("TOOLS.md")

    def test_unreadable_file_silently_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        soul = tmp_path / "SOUL.md"
        soul.write_text("content", encoding="utf-8")
        soul.chmod(0o000)
        try:
            result = main.load_context_files()
            assert "SOUL.md" not in result
        finally:
            soul.chmod(0o644)

    def test_reads_utf8_content(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        (tmp_path / "SOUL.md").write_text("Name: Jàrvis 🤖", encoding="utf-8")
        result = main.load_context_files()
        assert result["SOUL.md"] == "Name: Jàrvis 🤖"

    def test_only_context_files_loaded(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        (tmp_path / "SOUL.md").write_text("soul", encoding="utf-8")
        (tmp_path / "OTHER.md").write_text("other", encoding="utf-8")
        result = main.load_context_files()
        assert "OTHER.md" not in result
        assert "SOUL.md" in result


class TestLoadDailyMemory:

    def test_returns_empty_if_no_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        result = main.load_daily_memory()
        assert result == ""

    def test_returns_empty_if_memory_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        # No workspace/memory/ dir created
        result = main.load_daily_memory()
        assert result == ""

    def test_reads_todays_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        today = datetime.now().strftime("%Y-%m-%d")
        (memory_dir / f"{today}.md").write_text("Today content", encoding="utf-8")
        result = main.load_daily_memory()
        assert f"### Memory {today}" in result
        assert "Today content" in result

    def test_today_appears_before_yesterday(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        (memory_dir / f"{today}.md").write_text("Today", encoding="utf-8")
        (memory_dir / f"{yesterday}.md").write_text("Yesterday", encoding="utf-8")
        result = main.load_daily_memory()
        assert result.index(f"### Memory {today}") < result.index(f"### Memory {yesterday}")

    def test_missing_yesterday_returns_only_today(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        today = datetime.now().strftime("%Y-%m-%d")
        (memory_dir / f"{today}.md").write_text("Only today", encoding="utf-8")
        result = main.load_daily_memory()
        assert "Only today" in result
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        assert f"### Memory {yesterday}" not in result

    def test_entries_separated_by_double_newline(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        (memory_dir / f"{today}.md").write_text("A", encoding="utf-8")
        (memory_dir / f"{yesterday}.md").write_text("B", encoding="utf-8")
        result = main.load_daily_memory()
        assert "\n\n" in result


class TestLoadSkillsIndex:

    def test_returns_empty_if_no_skills_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        result = main.load_skills_index()
        assert result == ""

    def test_returns_empty_if_no_skill_md(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        (tmp_path / "skills" / "empty-skill").mkdir(parents=True)
        result = main.load_skills_index()
        assert result == ""

    def test_returns_empty_if_only_plain_files_in_skills(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "README.md").write_text("readme", encoding="utf-8")
        result = main.load_skills_index()
        assert result == ""

    def test_basic_skill_appears_in_xml(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        skill_dir = tmp_path / "skills" / "github"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: github\ndescription: GitHub CLI.\n---\n# GitHub",
            encoding="utf-8",
        )
        result = main.load_skills_index()
        assert "<name>github</name>" in result
        assert "<description>GitHub CLI.</description>" in result
        assert "SKILL.md" in result
        assert "read_file" in result

    def test_skills_sorted_alphabetically(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        for name in ["weather", "github", "calendar"]:
            d = tmp_path / "skills" / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(f"---\nname: {name}\n---", encoding="utf-8")
        result = main.load_skills_index()
        assert result.index("calendar") < result.index("github") < result.index("weather")

    def test_no_frontmatter_falls_back_to_dir_name(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        skill_dir = tmp_path / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# No frontmatter", encoding="utf-8")
        result = main.load_skills_index()
        assert "<name>my-skill</name>" in result
        assert "<description></description>" in result

    def test_location_path_relative_to_workspace(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        skill_dir = tmp_path / "skills" / "github"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: github\n---", encoding="utf-8")
        result = main.load_skills_index()
        assert "<location>" in result
        assert "SKILL.md" in result

    def test_no_empty_available_skills_block(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        (tmp_path / "skills").mkdir()
        result = main.load_skills_index()
        assert "<available_skills>" not in result

    def test_xml_special_chars_in_description_are_escaped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        skill_dir = tmp_path / "skills" / "myskill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test\ndescription: Load <data> & save\n---",
            encoding="utf-8",
        )
        result = main.load_skills_index()
        assert "<data>" not in result
        assert "&lt;data&gt;" in result
        assert "&amp;" in result


class TestBuildMemoryPrompt:

    def test_header_is_memory_instructions(self):
        result = main.build_memory_prompt()
        assert result.startswith("## Memory Instructions")

    def test_no_old_header(self):
        result = main.build_memory_prompt()
        # Old header must not appear
        assert "## Memory\n" not in result

    def test_contains_save_memory_reference(self):
        result = main.build_memory_prompt()
        assert "save_memory" in result

    def test_contains_memory_search_reference(self):
        result = main.build_memory_prompt()
        assert "memory_search" in result


class TestBuildSystemPrompt:

    def test_date_section_always_first(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        result = main.build_system_prompt()
        assert result.startswith("## Current Date & Time")

    def test_date_is_date_only_no_time(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        result = main.build_system_prompt()
        # Should contain the day name (e.g. "Saturday") but NOT ":" (which appears in HH:MM)
        lines = result.splitlines()
        date_line = lines[2]  # third line after header and blank
        assert ":" not in date_line

    def test_no_empty_context_headers(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        result = main.build_system_prompt()
        for fname in main.CONTEXT_FILES:
            assert f"## {fname}\n\n\n" not in result
            # If the file doesn't exist, the header must not appear
            assert f"## {fname}" not in result

    def test_soul_md_included_when_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        (tmp_path / "SOUL.md").write_text("You are Jarvis.", encoding="utf-8")
        result = main.build_system_prompt()
        assert "## SOUL.md" in result
        assert "You are Jarvis." in result

    def test_context_files_in_correct_order(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        (tmp_path / "AGENTS.md").write_text("agents", encoding="utf-8")
        (tmp_path / "SOUL.md").write_text("soul", encoding="utf-8")
        result = main.build_system_prompt()
        assert result.index("## AGENTS.md") < result.index("## SOUL.md")

    def test_recent_memory_included_when_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        today = datetime.now().strftime("%Y-%m-%d")
        (memory_dir / f"{today}.md").write_text("Remember this.", encoding="utf-8")
        result = main.build_system_prompt()
        assert "## Recent Memory" in result
        assert "Remember this." in result

    def test_skills_section_included_when_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        skill_dir = tmp_path / "skills" / "github"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: github\ndescription: GitHub CLI.\n---", encoding="utf-8"
        )
        result = main.build_system_prompt()
        assert "## Skills" in result
        assert "github" in result

    def test_memory_instructions_always_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        result = main.build_system_prompt()
        assert "## Memory Instructions" in result

    def test_long_term_memory_dir_not_in_prompt(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", str(tmp_path))
        # The ./memory/ tool memory dir content must NOT appear in the system prompt
        # Only workspace/memory/ daily logs do
        result = main.build_system_prompt()
        # Just verify no section for the tool memory dir leaks in
        assert "user-preferences" not in result


class TestToolReadFile:

    def test_returns_error_string_for_missing_file(self, tmp_path):
        result = main.tool_read_file(str(tmp_path / "nonexistent.txt"))
        assert isinstance(result, str)
        assert "Error reading" in result

    def test_reads_utf8_with_emoji(self, tmp_path):
        path = tmp_path / "test.md"
        path.write_text("Hello 🌍", encoding="utf-8")
        result = main.tool_read_file(str(path))
        assert result == "Hello 🌍"

    def test_reads_normal_file(self, tmp_path):
        path = tmp_path / "test.txt"
        path.write_text("content here", encoding="utf-8")
        result = main.tool_read_file(str(path))
        assert result == "content here"

    def test_returns_error_string_not_exception(self, tmp_path):
        # Must not raise — must return a string
        result = main.tool_read_file("/definitely/does/not/exist/file.md")
        assert isinstance(result, str)


from unittest.mock import patch, MagicMock


class _FakeTextBlock:
    """Minimal text block that behaves like anthropic TextBlock for testing."""
    type = "text"

    def __init__(self, text):
        self.text = text


class TestRunAgentTurn:

    def _make_response(self, stop_reason, text="some text"):
        response = MagicMock()
        response.stop_reason = stop_reason
        response.content = [_FakeTextBlock(text)]
        return response

    def test_end_turn_returns_tuple(self):
        response = self._make_response("end_turn", "hello")
        with patch.object(main.client.messages, "create", return_value=response):
            result = main.run_agent_turn(
                [{"role": "user", "content": "hi"}], "system prompt"
            )
        assert isinstance(result, tuple)
        assert len(result) == 2
        text, messages = result
        assert text == "hello"
        assert isinstance(messages, list)

    def test_max_tokens_returns_tuple_not_none(self):
        """Bug fix: previously returned None on unexpected stop_reason."""
        response = self._make_response("max_tokens", "partial")
        with patch.object(main.client.messages, "create", return_value=response):
            result = main.run_agent_turn(
                [{"role": "user", "content": "hi"}], "system prompt"
            )
        assert result is not None
        text, messages = result
        assert isinstance(text, str)
        assert isinstance(messages, list)

    def test_stop_sequence_returns_tuple_not_none(self):
        response = self._make_response("stop_sequence", "stopped")
        with patch.object(main.client.messages, "create", return_value=response):
            result = main.run_agent_turn(
                [{"role": "user", "content": "hi"}], "system prompt"
            )
        assert result is not None
        assert isinstance(result, tuple)

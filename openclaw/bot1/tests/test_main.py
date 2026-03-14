import os

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

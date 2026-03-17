"""Tests for agents module.

Tests for extract_frontmatter_body, load_agents_index, and AgentsToolkit.
"""

import pytest
import agents
import agents as agents_module  # alias used by TestLoadAgentsIndex* and TestRunAgent*


# Module-level autouse fixture: resets _agents_registry before EVERY test in this file.
# Required because load_agents_index() populates module-level state that persists
# between tests unless explicitly cleared.
@pytest.fixture(autouse=True)
def reset_registry(monkeypatch):
    monkeypatch.setattr(agents_module, "_agents_registry", {})


class TestExtractFrontmatterBody:

    def test_returns_body_when_frontmatter_present(self):
        content = "---\nname: test\n---\n\nThis is the body."
        assert agents.extract_frontmatter_body(content) == "This is the body."

    def test_returns_full_content_when_no_frontmatter(self):
        content = "No frontmatter here."
        assert agents.extract_frontmatter_body(content) == "No frontmatter here."

    def test_horizontal_rule_in_body_not_split(self):
        content = "---\nname: test\n---\n\nBody.\n\n---\n\nMore."
        result = agents.extract_frontmatter_body(content)
        assert result == "Body.\n\n---\n\nMore."

    def test_empty_content_returns_empty_string(self):
        assert agents.extract_frontmatter_body("") == ""

    def test_single_delimiter_returns_full_content_stripped(self):
        content = "---\nname: test\nno closing delimiter"
        assert agents.extract_frontmatter_body(content) == content.strip()


class TestLoadAgentsIndexMissingDir:

    def test_returns_empty_when_agents_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agents_module, "WORKSPACE_DIR", str(tmp_path))
        # tmp_path has no agents/ subdir
        assert agents_module.load_agents_index() == ""

    def test_returns_empty_when_agents_dir_is_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agents_module, "WORKSPACE_DIR", str(tmp_path))
        (tmp_path / "agents").mkdir()
        assert agents_module.load_agents_index() == ""

    def test_non_directory_entries_are_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agents_module, "WORKSPACE_DIR", str(tmp_path))
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        # A file (not a dir) inside agents/ — should be skipped
        (agents_dir / "not_a_dir.md").write_text("content", encoding="utf-8")
        assert agents_module.load_agents_index() == ""

    def test_subdir_with_no_matching_md_file_is_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agents_module, "WORKSPACE_DIR", str(tmp_path))
        agents_dir = tmp_path / "agents"
        agent_dir = agents_dir / "my_agent"
        agent_dir.mkdir(parents=True)
        # No my_agent.md inside the dir
        assert agents_module.load_agents_index() == ""

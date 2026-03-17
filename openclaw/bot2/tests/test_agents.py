"""Tests for agents module.

Tests for extract_frontmatter_body, load_agents_index, and AgentsToolkit.
"""

import shutil

import pytest
from agno.tools import Toolkit
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


def _make_agent_file(agents_dir, dir_name, frontmatter: dict, body: str = "Do the task."):
    """Helper: create workspace/agents/<dir_name>/<dir_name>.md."""
    agent_dir = agents_dir / dir_name
    agent_dir.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    for k, v in frontmatter.items():
        lines.append(f"{k}: {v}")
    lines += ["---", "", body]
    (agent_dir / f"{dir_name}.md").write_text("\n".join(lines), encoding="utf-8")
    return agent_dir


class TestLoadAgentsIndexValid:

    def test_valid_agent_appears_in_xml(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agents_module, "WORKSPACE_DIR", str(tmp_path))
        agents_dir = tmp_path / "agents"
        _make_agent_file(
            agents_dir, "summarizer_agent",
            {"name": "summarizer-agent", "description": "Summarize text."}
        )
        result = agents_module.load_agents_index()
        assert "<name>summarizer-agent</name>" in result
        assert "<description>Summarize text.</description>" in result
        assert "summarizer_agent.md" in result
        assert "<directory>" in result

    def test_instructional_preamble_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agents_module, "WORKSPACE_DIR", str(tmp_path))
        agents_dir = tmp_path / "agents"
        _make_agent_file(
            agents_dir, "summarizer_agent",
            {"name": "summarizer-agent", "description": "Summarize text."}
        )
        result = agents_module.load_agents_index()
        assert "run_agent" in result
        assert result.index("run_agent") < result.index("<available_agents>")

    def test_registry_populated_with_file_path_and_model(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agents_module, "WORKSPACE_DIR", str(tmp_path))
        agents_dir = tmp_path / "agents"
        agent_dir = _make_agent_file(
            agents_dir, "summarizer_agent",
            {"name": "summarizer-agent", "description": "Summarize.", "model": "claude-haiku-4-5-20251001"}
        )
        agents_module.load_agents_index()
        entry = agents_module._agents_registry["summarizer-agent"]
        assert entry["file_path"].endswith("summarizer_agent.md")
        assert entry["model"] == "claude-haiku-4-5-20251001"

    def test_model_absent_stored_as_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agents_module, "WORKSPACE_DIR", str(tmp_path))
        agents_dir = tmp_path / "agents"
        _make_agent_file(
            agents_dir, "summarizer_agent",
            {"name": "summarizer-agent", "description": "Summarize."}
            # no model field
        )
        agents_module.load_agents_index()
        assert agents_module._agents_registry["summarizer-agent"]["model"] is None

    def test_agent_without_name_field_is_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agents_module, "WORKSPACE_DIR", str(tmp_path))
        agents_dir = tmp_path / "agents"
        _make_agent_file(
            agents_dir, "nameless_agent",
            {"description": "Has no name field."}
        )
        result = agents_module.load_agents_index()
        assert result == ""
        assert agents_module._agents_registry == {}


class TestLoadAgentsIndexEdgeCases:

    def test_xml_special_chars_in_description_are_html_escaped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agents_module, "WORKSPACE_DIR", str(tmp_path))
        agents_dir = tmp_path / "agents"
        _make_agent_file(
            agents_dir, "my_agent",
            {"name": "my-agent", "description": "Load <data> & save"}
        )
        result = agents_module.load_agents_index()
        assert "<data>" not in result
        assert "&lt;data&gt;" in result
        assert "&amp;" in result

    def test_multiple_agents_sorted_alphabetically(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agents_module, "WORKSPACE_DIR", str(tmp_path))
        agents_dir = tmp_path / "agents"
        for dir_name, name in [
            ("weather_agent", "weather-agent"),
            ("alpha_agent", "alpha-agent"),
            ("beta_agent", "beta-agent"),
        ]:
            _make_agent_file(agents_dir, dir_name, {"name": name, "description": "desc"})
        result = agents_module.load_agents_index()
        assert result.index("alpha-agent") < result.index("beta-agent") < result.index("weather-agent")

    def test_duplicate_name_last_alphabetical_dir_wins(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agents_module, "WORKSPACE_DIR", str(tmp_path))
        agents_dir = tmp_path / "agents"
        # Both dirs declare name "dup" — "z_agent" comes after "a_agent" alphabetically
        _make_agent_file(agents_dir, "a_agent", {"name": "dup", "description": "first"})
        _make_agent_file(agents_dir, "z_agent", {"name": "dup", "description": "second"})
        agents_module.load_agents_index()
        entry = agents_module._agents_registry["dup"]
        assert "z_agent" in entry["file_path"]

    def test_stale_registry_entry_cleared_on_second_call(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agents_module, "WORKSPACE_DIR", str(tmp_path))
        agents_dir = tmp_path / "agents"
        agent_dir = _make_agent_file(
            agents_dir, "my_agent",
            {"name": "my-agent", "description": "desc"}
        )
        agents_module.load_agents_index()
        assert "my-agent" in agents_module._agents_registry

        # Remove the agent and call again
        shutil.rmtree(str(agent_dir))
        agents_module.load_agents_index()
        assert "my-agent" not in agents_module._agents_registry

    def test_registry_matches_expected_keys_and_structure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agents_module, "WORKSPACE_DIR", str(tmp_path))
        agents_dir = tmp_path / "agents"
        _make_agent_file(
            agents_dir, "my_agent",
            {"name": "my-agent", "description": "desc", "model": "claude-opus-4-6"}
        )
        agents_module.load_agents_index()
        registry = agents_module._agents_registry
        assert set(registry.keys()) == {"my-agent"}
        assert set(registry["my-agent"].keys()) == {"file_path", "model"}
        assert registry["my-agent"]["model"] == "claude-opus-4-6"


class TestAgentsToolkitRegistration:

    def test_is_agno_toolkit_instance(self):
        from agents import AgentsToolkit
        assert isinstance(AgentsToolkit(), Toolkit)

    def test_run_agent_registered_in_functions(self):
        from agents import AgentsToolkit
        toolkit = AgentsToolkit()
        assert "run_agent" in toolkit.functions

    def test_no_extra_tools_registered(self):
        from agents import AgentsToolkit
        toolkit = AgentsToolkit()
        assert list(toolkit.functions.keys()) == ["run_agent"]


from unittest.mock import MagicMock, patch


def _make_fake_ctx(session_state=None):
    """Create a minimal fake RunContext — avoids dependency on RunContext constructor API."""
    ctx = MagicMock()
    ctx.session_state = session_state
    return ctx


class TestRunAgentErrors:

    def test_agent_not_found_returns_error_string(self, monkeypatch):
        monkeypatch.setattr(agents_module, "_agents_registry", {})
        toolkit = agents_module.AgentsToolkit()
        result = toolkit.run_agent(_make_fake_ctx(), "nonexistent-agent", "do something")
        assert "nonexistent-agent" in result
        assert result.startswith("Error")

    def test_agent_not_found_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(agents_module, "_agents_registry", {})
        toolkit = agents_module.AgentsToolkit()
        # Must return a string, never raise
        result = toolkit.run_agent(_make_fake_ctx(), "ghost", "task")
        assert isinstance(result, str)

    def test_unreadable_agent_file_returns_error_string(self, tmp_path, monkeypatch):
        bad_path = str(tmp_path / "nonexistent.md")
        monkeypatch.setattr(
            agents_module,
            "_agents_registry",
            {"my-agent": {"file_path": bad_path, "model": None}},
        )
        toolkit = agents_module.AgentsToolkit()
        result = toolkit.run_agent(_make_fake_ctx(), "my-agent", "task")
        assert "my-agent" in result
        assert result.startswith("Error")

    def test_api_exception_returns_error_string(self, tmp_path, monkeypatch):
        # Create a real (readable) agent file
        agent_file = tmp_path / "agent.md"
        agent_file.write_text("---\nname: my-agent\n---\n\nDo stuff.", encoding="utf-8")
        monkeypatch.setattr(
            agents_module,
            "_agents_registry",
            {"my-agent": {"file_path": str(agent_file), "model": None}},
        )
        toolkit = agents_module.AgentsToolkit()
        with patch("agents.Agent") as MockAgent:
            MockAgent.return_value.run.side_effect = RuntimeError("API down")
            result = toolkit.run_agent(_make_fake_ctx(), "my-agent", "task")
        assert "my-agent" in result
        assert result.startswith("Error")

    def test_none_response_content_returns_empty_string(self, tmp_path, monkeypatch):
        agent_file = tmp_path / "agent.md"
        agent_file.write_text("---\nname: my-agent\n---\n\nDo stuff.", encoding="utf-8")
        monkeypatch.setattr(
            agents_module,
            "_agents_registry",
            {"my-agent": {"file_path": str(agent_file), "model": None}},
        )
        toolkit = agents_module.AgentsToolkit()
        with patch("agents.Agent") as MockAgent:
            MockAgent.return_value.run.return_value = MagicMock(content=None)
            result = toolkit.run_agent(_make_fake_ctx(), "my-agent", "task")
        assert result == ""

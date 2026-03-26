"""Sub-agent support for bot2 (Agno).

Provides:
    extract_frontmatter_body: strip YAML frontmatter, return body text
    load_agents_index: scan workspace/agents/, return XML index for system prompt
    AgentsToolkit: Agno Toolkit with run_agent tool
"""

import html
import os
import re

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.run import RunContext  # verified agno 2.5.9
from agno.tools import Toolkit

from tools import BotToolkit
from constants import APPROVALS_FILE

# Resolved via __file__ so the bot works from any working directory.
WORKSPACE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace")

# Module-level registry populated by load_agents_index().
# key:   frontmatter "name" value (e.g. "summarizer-agent")
# value: {"file_path": str, "model": str | None}
_agents_registry: dict[str, dict] = {}


def extract_frontmatter_body(content: str) -> str:
    """Return body text of a markdown file with YAML frontmatter stripped.

    Uses maxsplit=2 so --- horizontal rules inside the body are never split.
    If no closing --- is found, returns the full content stripped.
    """
    parts = re.split(r"^---\s*$", content, maxsplit=2, flags=re.MULTILINE)
    if len(parts) == 3:
        return parts[2].strip()
    return content.strip()


def _parse_frontmatter(content: str) -> dict:
    """Parse YAML-style frontmatter key-value pairs from markdown content."""
    parts = re.split(r"^---\s*$", content, maxsplit=2, flags=re.MULTILINE)
    if len(parts) < 3:
        return {}
    meta: dict[str, str] = {}
    for line in parts[1].splitlines():
        if not line.strip():
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta


def load_agents_index() -> str:
    """Scan workspace/agents/ and return an XML index for the system prompt.

    Clears and repopulates _agents_registry as a side effect.
    Returns empty string when no agents are found or the directory is missing.
    """
    global _agents_registry
    _agents_registry = {}

    agents_dir = os.path.join(WORKSPACE_DIR, "agents")
    try:
        entries = sorted(os.listdir(agents_dir))
    except OSError:
        return ""

    agents_list = []
    for name in entries:
        dir_path = os.path.join(agents_dir, name)
        if not os.path.isdir(dir_path):
            continue
        agent_file = os.path.join(dir_path, f"{name}.md")
        try:
            with open(agent_file, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        meta = _parse_frontmatter(content)
        agent_name = meta.get("name", "").strip()
        if not agent_name:
            continue
        description = meta.get("description", "")
        model = meta.get("model") or None
        _agents_registry[agent_name] = {"file_path": agent_file, "model": model}
        agents_list.append(
            {
                "name": agent_name,
                "description": description,
                "location": agent_file,
                "directory": dir_path,
            }
        )

    if not agents_list:
        return ""

    xml_entries = "\n".join(
        f"  <agent>\n"
        f"    <name>{html.escape(a['name'])}</name>\n"
        f"    <description>{html.escape(a['description'])}</description>\n"
        f"    <location>{html.escape(a['location'])}</location>\n"
        f"    <directory>{html.escape(a['directory'])}</directory>\n"
        f"  </agent>"
        for a in agents_list
    )
    preamble = (
        "When a task is better handled by a specialist, use the run_agent tool "
        "with the agent's name and a clear task description.\n\n"
    )
    return preamble + f"<available_agents>\n{xml_entries}\n</available_agents>"


class AgentsToolkit(Toolkit):
    """Agno Toolkit providing the run_agent tool for sub-agent dispatch."""

    def __init__(self, skill_registry=None) -> None:
        self._skill_registry = skill_registry
        super().__init__(name="agent_tools", tools=[self.run_agent])

    def run_agent(self, run_context: RunContext, agent_name: str, task: str) -> str:
        """Dispatch a task to a specialized sub-agent and return its response.

        Args:
            agent_name: Name of the agent as listed in the agents index.
            task: The task or question to send to the agent.

        Note:
            run_context is injected automatically by Agno — do not pass it manually.
        """
        try:
            entry = _agents_registry.get(agent_name)
            if entry is None:
                return f"Error: agent '{agent_name}' not found."

            with open(entry["file_path"], "r", encoding="utf-8") as f:
                content = f.read()

            from prompt import build_subagent_system_prompt
            system_prompt = build_subagent_system_prompt(content, self._skill_registry)
            model = entry["model"] or "claude-sonnet-4-6"

            sub_agent = Agent(
                model=Claude(id=model),
                system_message=system_prompt,
                tools=[
                    BotToolkit(approvals_file=APPROVALS_FILE),
                    AgentsToolkit(skill_registry=self._skill_registry),
                ],
                debug_mode=True,
                # no db, no tools, no session_id — ephemeral one-shot agent
            )

            resp = sub_agent.run(task, session_state=run_context.session_state)
            return resp.content or ""

        except Exception as e:
            return f"Error running agent '{agent_name}': {e}"

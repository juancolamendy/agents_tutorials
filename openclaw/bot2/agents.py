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

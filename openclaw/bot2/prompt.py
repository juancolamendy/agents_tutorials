import html
import os
import re
from datetime import datetime, timedelta

from agents import load_agents_index

# Resolve relative to this file so the bot works from any working directory.
# Do NOT use "./workspace" — it breaks when invoked from outside bot2/.
WORKSPACE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace")
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
            "directory": os.path.join(WORKSPACE_DIR, "skills", name),
        })

    if not skills:
        return ""

    xml_entries = "\n".join(
        f"  <skill>\n"
        f"    <name>{html.escape(s['name'])}</name>\n"
        f"    <description>{html.escape(s['description'])}</description>\n"
        f"    <location>{html.escape(s['location'])}</location>\n"
        f"    <directory>{html.escape(s['directory'])}</directory>\n"
        f"  </skill>"
        for s in skills
    )
    return (
        "When a task matches one of the skills below, use the `read_file` tool to "
        "load the SKILL.md at the listed location for detailed instructions.\n\n"
        "All scripts and paths referenced inside a SKILL.md are relative to that "
        "skill's <directory>. For example, if a skill says `uv run ./scripts/foo.py`, "
        "the full path is <directory>/scripts/foo.py. Always prefix script paths with "
        "the skill's <directory> when calling run_command.\n\n"
        f"<available_skills>\n{xml_entries}\n</available_skills>"
    )


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

    agents_index = load_agents_index()
    if agents_index:
        parts.append(f"## Agents\n\n{agents_index}")

    return "\n\n".join(parts)

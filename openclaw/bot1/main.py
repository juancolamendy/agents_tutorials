import asyncio
import json
import os
import re
import subprocess

import anthropic
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic()

def load_soul(path: str = "SOUL.md") -> str:
    try:
        with open(path, "r") as f:
            return f.read()
    except Exception:
        return ""

SOUL = load_soul()

SESSIONS_DIR = "./sessions"
os.makedirs(SESSIONS_DIR, exist_ok=True)

SAFE_COMMANDS = {"ls", "cat", "head", "tail", "wc", "date", "whoami", "echo"}
DANGEROUS_PATTERNS = [r"\brm\b", r"\bsudo\b", r"\bchmod\b", r"\bcurl.*\|.*sh"]
APPROVALS_FILE = "./exec-approvals.json"

def load_approvals():
    if os.path.exists(APPROVALS_FILE):
        with open(APPROVALS_FILE) as f:
            return json.load(f)
    return {"allowed": [], "denied": []}

def save_approval(command, approved):
    approvals = load_approvals()
    key = "allowed" if approved else "denied"
    if command not in approvals[key]:
        approvals[key].append(command)
    with open(APPROVALS_FILE, "w") as f:
        json.dump(approvals, f, indent=2)

def check_command_safety(command):
    """Returns 'safe', 'approved', or 'needs_approval'."""
    base_cmd = command.strip().split()[0] if command.strip() else ""
    if base_cmd in SAFE_COMMANDS:
        return "safe"
    approvals = load_approvals()
    if command in approvals["allowed"]:
        return "approved"
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command):
            return "needs_approval"
    return "needs_approval"

TOOLS = [
    {
        "name": "run_command",
        "description": "Run a shell command on the user's computer",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The command to run"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "read_file",
        "description": "Read a file from the filesystem",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Write content to a file",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file"},
                "content": {"type": "string", "description": "Content to write"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "web_search",
        "description": "Search the web for information",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"}
            },
            "required": ["query"]
        }
    }
]

def execute_tool(name, tool_input):
    if name == "run_command":
        command = tool_input["command"]
        safety = check_command_safety(command)

        if safety == "needs_approval":
            print(f"  [approval needed] {command}")
            answer = input("  Allow this command? (y/n): ").strip().lower()
            approved = answer == "y"
            save_approval(command, approved)
            if not approved:
                return "Command denied by user."

        result = subprocess.run(
            command, shell=True,
            capture_output=True, text=True, timeout=30
        )
        return result.stdout + result.stderr

    elif name == "read_file":
        with open(tool_input["path"], "r") as f:
            return f.read()

    elif name == "write_file":
        with open(tool_input["path"], "w") as f:
            f.write(tool_input["content"])
        return f"Wrote to {tool_input['path']}"

    elif name == "web_search":
        return f"Search results for: {tool_input['query']}"

    return f"Unknown tool: {name}"

def estimate_tokens(messages):
    """Rough token estimate: ~4 chars per token."""
    return sum(len(json.dumps(m)) for m in messages) // 4

def compact_session(user_id, session_id, messages):
    """Summarize old messages when context gets too long."""
    if estimate_tokens(messages) < 100_000:
        return messages

    split = len(messages) // 2
    old, recent = messages[:split], messages[split:]

    print("  [compacting session history...]")

    summary = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": (
                "Summarize this conversation concisely. Preserve:\n"
                "- Key facts about the user (name, preferences)\n"
                "- Important decisions made\n"
                "- Open tasks or TODOs\n\n"
                f"{json.dumps(old, indent=2)}"
            )
        }]
    )

    compacted = [{
        "role": "user",
        "content": f"[Previous conversation summary]\n{summary.content[0].text}"
    }] + recent

    save_session(user_id, session_id, compacted)
    return compacted

def serialize_content(content):
    serialized = []
    for block in content:
        if hasattr(block, "text"):
            serialized.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            serialized.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input
            })
    return serialized

def run_agent_turn(messages):
    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SOUL,
            tools=TOOLS,
            messages=messages
        )

        content = serialize_content(response.content)

        if response.stop_reason == "end_turn":
            text = "".join(block.text for block in response.content if hasattr(block, "text"))
            messages.append({"role": "assistant", "content": content})
            return text, messages

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": content})

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"  [tool] {block.name}({json.dumps(block.input)})")
                    result = execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result)
                    })

            messages.append({"role": "user", "content": tool_results})

def get_session_path(user_id, session_id):
    return os.path.join(SESSIONS_DIR, f"{user_id}_{session_id}.jsonl")

def load_session(user_id, session_id):
    path = get_session_path(user_id, session_id)
    messages = []
    if os.path.exists(path):
        with open(path, "r") as f:
            for line in f:
                if line.strip():
                    messages.append(json.loads(line))
    return messages

def save_session(user_id, session_id, messages):
    path = get_session_path(user_id, session_id)
    with open(path, "w") as f:
        for message in messages:
            f.write(json.dumps(message) + "\n")

async def handle_message(user_id: str, session_id: str, text: str):
    messages = load_session(user_id, session_id)
    messages = compact_session(user_id, session_id, messages)
    messages.append({"role": "user", "content": text})

    response_text, messages = run_agent_turn(messages)

    save_session(user_id, session_id, messages)
    return response_text

async def main():
    user_id = input("Enter your user ID: ").strip() or "default"
    session_id = input("Enter your session ID: ").strip() or "default"
    print(f"Session loaded for user '{user_id}', session '{session_id}'. Type /exit to quit.")

    while True:
        text = input("You: ")
        if text == "/exit":
            break
        resp = await handle_message(user_id, session_id, text)
        print(f"Claude: {resp}")

asyncio.run(main())

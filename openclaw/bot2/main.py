"""CLI entry point for bot2 (Agno-backed agent).

Usage::

    cd bot2
    uv run python main.py

On startup the user is prompted for a ``user_id`` and ``session_id``.
Within the REPL:

- ``/new``  — reset the session (generates a new timestamped session_id)
- ``/quit`` or ``/exit`` — terminate the bot
"""

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

# Resolve paths relative to this file so the bot works from any CWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
SESSIONS_DIR = os.path.join(_HERE, 'sessions')
MEMORY_DIR = os.path.join(_HERE, 'memory')
APPROVALS_FILE = os.path.join(_HERE, 'workspace', 'exec-approvals.json')

os.makedirs(SESSIONS_DIR, exist_ok=True)
os.makedirs(MEMORY_DIR, exist_ok=True)


def build_agent() -> Agent:
    """Construct and return a fully-wired Agno Agent.

    Returns:
        Agent: Ready-to-use agent instance with storage, memory, and tools.
    """
    return Agent(
        model=Claude(id='claude-sonnet-4-6', cache_system_prompt=True),
        tools=[
            BotToolkit(approvals_file=APPROVALS_FILE),
            MemoryTools(db=MarkdownMemoryDb(MEMORY_DIR)),
        ],
        db=JsonlAgentDb(sessions_dir=SESSIONS_DIR),
        system_message=build_system_prompt(),
        add_history_to_context=True,
        num_history_runs=20,
        max_tool_calls_from_history=5,
    )


def main() -> None:
    """Run the interactive CLI REPL."""
    try:
        user_id = input('Enter your user ID: ').strip() or 'default'
        session_id = (
            input('Enter your session ID: ').strip()
            or datetime.now().strftime('%Y%m%d%H%M%S')
        )
    except EOFError:
        print('No TTY detected. Exiting.')
        return

    print(
        f"Session loaded for user '{user_id}', session '{session_id}'. "
        'Type /quit or /exit to quit. Type /new to reset the session.'
    )

    agent = build_agent()

    while True:
        try:
            text = input('You: ')
        except (EOFError, KeyboardInterrupt):
            print('\nGoodbye!')
            break
        if text in ['/quit', '/exit']:
            print('Goodbye!')
            break
        if text == '/new':
            session_id = datetime.now().strftime('%Y%m%d%H%M%S')
            print(f'Session reset. New session ID: {session_id}')
            continue
        try:
            response = agent.run(text, user_id=user_id, session_id=session_id)
            print(f'Claude: {response.content or ""}')
        except KeyboardInterrupt:
            print('\nGoodbye!')
            break
        except Exception as e:  # noqa: BLE001
            print(f'Error: {e}')


if __name__ == '__main__':
    main()

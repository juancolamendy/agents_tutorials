import asyncio
import json
import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic()

SESSIONS_DIR = "./sessions"
os.makedirs(SESSIONS_DIR, exist_ok=True)

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

def append_to_session(user_id, session_id, message):
    path = get_session_path(user_id, session_id)
    with open(path, "a") as f:
        f.write(json.dumps(message) + "\n")

async def handle_message(user_id: str, session_id: str, text: str):
    messages = load_session(user_id, session_id)

    user_msg = {"role": "user", "content": text}
    messages.append(user_msg)
    append_to_session(user_id, session_id, user_msg)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=messages
    )

    assistant_msg = {"role": "assistant", "content": response.content[0].text}
    append_to_session(user_id, session_id, assistant_msg)

    return response.content[0].text

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

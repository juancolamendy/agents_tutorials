# Requirements

## Functional Requirements
Implement the option for sub-agents

Given the a directory `workspace/agents` with agents defined. Similar to the skills approach.
Given a particular agent `/Users/jcolamendy/ai_ml/agents_tutorials/openclaw/bot1/workspace/agents/summarizer_agent/summarizer_agent.md` 
Understand the structure of agent. Frontmatter and prompt. Similar to skills
When the user sends a message or the following rules exists (prompt, skill) such as `use summarizer agent to summarize the output`, the we need to run the that agent as function call and return the result to the conversation

I think:
- we should have a function named `load_agents_index` to provide information about existing agents. See skills as your inspiration
- call the function `load_agents_index` as part of the system prompt.
- add internal function name `tool_run_agent` similar to the `tool_read_file` and `tool_run_command` I think the signature can be `tool_run_agent(agent_name: str, input: str)`
- register the `tool_run_agent` into registry
- `tool_run_agent`
- system_prompt = the agent instructions (after the front-matter)
- messages = (role=user, content=input)
```
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=4096,
    system=system_prompt,
    messages=messages
)
```
"""
Generic Context-Aware Multi-Agent System (Agno + LanceDB)

- Workflow:
    Step 1: PlannerAgent → writes JSON plan into session_state["plan"]
    Step 2: ExecutorAgent → reads plan (passed directly in message), calls subagents

- Execution model:
    * Planner and Executor are *agents* used as workflow steps.
    * Each subagent reads its own dependencies from session_state via its own tools:
      - Librarian writes semantic_blueprint → session_state
      - Researcher writes research_results → session_state
      - Writer calls get_writing_context() to read both from session_state
    * No {{step_id}} placeholder substitution needed.
"""

import os
import json
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv

import lancedb
from openai import OpenAI as OpenAIClient

from agno.agent import Agent
from agno.team import Team
from agno.models.anthropic import Claude
from agno.tools import Toolkit
from agno.run import RunContext
from agno.workflow.workflow import Workflow
from agno.workflow.step import Step
from agno.db.sqlite import SqliteDb

## Load env vars
load_dotenv()

# ============================================================
# 0. EMBEDDINGS + CHUNKING
# ============================================================

openai_client = OpenAIClient(api_key=os.getenv("OPENAI_API_KEY"))

def embed_batch(texts: List[str],
                model: str = "text-embedding-3-small") -> List[List[float]]:
    resp = openai_client.embeddings.create(input=texts, model=model)
    return [d.embedding for d in resp.data]

def chunk_text(text: str,
               chunk_size: int = 500,
               overlap: int = 50) -> List[str]:
    chunks, i = [], 0
    while i < len(text):
        chunks.append(text[i:i + chunk_size])
        i += chunk_size - overlap
    return chunks

# ============================================================
# 1. DATA + LANCEDB
# ============================================================

BLUEPRINTS = [
    {
        "id": "suspenseful_narrative",
        "description": "Creative writing with suspenseful narrative and vivid imagery",
        "blueprint": {
            "tone": "mysterious and tense",
            "style": "narrative",
            "structure": "Hook → rising tension → twist → resolution",
            "techniques": [
                "End paragraphs on questions or hints",
                "Use sensory detail",
                "Reveal information gradually"
            ]
        }
    },
    {
        "id": "technical_explanation",
        "description": "Technical explanation with precise terminology and clear structure",
        "blueprint": {
            "tone": "professional and precise",
            "style": "technical",
            "structure": "Overview → concepts → examples → recap",
            "techniques": [
                "Define key terms",
                "Use numbered steps",
                "Avoid metaphors unless explicitly requested"
            ]
        }
    },
    {
        "id": "casual_summary",
        "description": "Casual friendly summary for non-experts",
        "blueprint": {
            "tone": "friendly and relaxed",
            "style": "conversational",
            "structure": "Main idea → simple breakdown → takeaway",
            "techniques": [
                "Use analogies",
                "Short paragraphs",
                "Minimal jargon"
            ]
        }
    },
]

RAW_KNOWLEDGE = """
Artificial Intelligence (AI) refers to computer systems that perform tasks usually requiring human intelligence.
Machine learning is a subset of AI that learns patterns from data.
Deep learning uses multi-layer neural networks to model complex relationships.
Retrieval-Augmented Generation (RAG) combines retrieval over a knowledge base with a generator model for better factuality.
Vector databases store dense embeddings and support semantic similarity search.
Multi-agent systems split responsibilities across agents like Librarian, Researcher, and Writer coordinated by an orchestrator.
Context engineering designs prompts, blueprints, and workflows to control how agents use tools and knowledge.
"""

db = lancedb.connect("./context_enginer_1.db")

def init_lancedb():
    # Context Library
    try:
        db.drop_table("context_library")
    except Exception:
        pass

    descs = [bp["description"] for bp in BLUEPRINTS]
    desc_emb = embed_batch(descs)
    ctx_rows = []
    for bp, e in zip(BLUEPRINTS, desc_emb):
        ctx_rows.append({
            "id": bp["id"],
            "description": bp["description"],
            "blueprint": json.dumps(bp["blueprint"]),
            "vector": e,
        })
    ctx_table = db.create_table("context_library", data=ctx_rows)

    # Knowledge Base
    try:
        db.drop_table("knowledge_base")
    except Exception:
        pass

    chunks = chunk_text(RAW_KNOWLEDGE, chunk_size=260, overlap=40)
    ch_emb = embed_batch(chunks)
    kb_rows = []
    for i, (txt, e) in enumerate(zip(chunks, ch_emb)):
        kb_rows.append({
            "id": f"chunk_{i}",
            "text": txt,
            "vector": e,
        })
    kb_table = db.create_table("knowledge_base", data=kb_rows)

    print(f"Context library rows: {len(ctx_rows)}")
    print(f"Knowledge base rows: {len(kb_rows)}")
    return ctx_table, kb_table

context_table, knowledge_table = init_lancedb()

# ============================================================
# 2. SUBAGENT TOOLKITS
# ============================================================

class LibrarianTools(Toolkit):
    name = "librarian_tools"

    def __init__(self):
        super().__init__(name=self.name)
        self.register(self.semantic_blueprint_search)

    def semantic_blueprint_search(self,
                                 run_context: RunContext,
                                 intent_query: str) -> str:
        """Procedural RAG over context_library."""
        emb = embed_batch([intent_query])[0]
        df = context_table.search(emb).limit(1).to_pandas()
        if len(df) == 0:
            blueprint = {
                "id": "default_neutral",
                "description": "Neutral fallback blueprint",
                "blueprint": {
                    "tone": "neutral",
                    "style": "plain",
                    "structure": "Intro → body → conclusion",
                    "techniques": ["Explain clearly and concisely"]
                }
            }
            found = False
        else:
            bp = json.loads(df.iloc[0]["blueprint"])
            blueprint = {
                "id": df.iloc[0]["id"],
                "description": df.iloc[0]["description"],
                "blueprint": bp,
            }
            found = True

        if run_context.session_state is not None:
            run_context.session_state["semantic_blueprint"] = blueprint
            run_context.session_state["blueprint_found"] = found
        return json.dumps(blueprint)


class ResearcherTools(Toolkit):
    name = "researcher_tools"

    def __init__(self):
        super().__init__(name=self.name)
        self.register(self.semantic_research)

    def semantic_research(self,
                          run_context: RunContext,
                          query: str,
                          limit: int = 5) -> str:
        """Factual RAG over knowledge_base."""
        emb = embed_batch([query])[0]
        df = knowledge_table.search(emb).limit(limit).to_pandas()
        results = [{"id": r["id"], "text": r["text"]} for _, r in df.iterrows()]

        if run_context.session_state is not None:
            run_context.session_state["research_results"] = results
        return json.dumps(results)


class WriterContextTools(Toolkit):
    name = "writer_context_tools"

    def __init__(self):
        super().__init__(name=self.name)
        self.register(self.get_writing_context)

    def get_writing_context(self, run_context: RunContext) -> str:
        """Read semantic_blueprint and research_results stored by prior agents."""
        blueprint = run_context.session_state.get("semantic_blueprint", {}) if run_context.session_state else {}
        research = run_context.session_state.get("research_results", []) if run_context.session_state else []
        return json.dumps({"semantic_blueprint": blueprint, "research_results": research})

# ============================================================
# 3. SUBAGENTS (Librarian, Researcher, Writer)
# ============================================================

model = Claude(id="claude-sonnet-4-20250514")

librarian_agent = Agent(
    name="Librarian",
    role="Context Librarian",
    model=model,
    tools=[LibrarianTools()],
    instructions=(
        "You fetch semantic style blueprints from the Context Library.\n"
        "Always call semantic_blueprint_search(intent_query=...) first.\n"
        "Keep your own text short; the important data is in the JSON tool output."
    ),
    markdown=True,
)

researcher_agent = Agent(
    name="Researcher",
    role="Knowledge Researcher",
    model=model,
    tools=[ResearcherTools()],
    instructions=(
        "You fetch factual context from the Knowledge Base.\n"
        "Always call semantic_research(query=...) first.\n"
        "Then summarise briefly what you found."
    ),
    markdown=True,
)

writer_agent = Agent(
    name="Writer",
    role="Writer",
    model=model,
    tools=[WriterContextTools()],
    instructions=(
        "You generate final content.\n"
        "Always call get_writing_context() first to load the style blueprint and research facts.\n"
        "Follow blueprint.tone/style/structure/techniques exactly.\n"
        "Do not mention agents, tools, or the internal process."
    ),
    markdown=True,
)

# ============================================================
# 5. EXECUTOR TOOLS – CALL SUBAGENTS (GENERIC)
# ============================================================

class SubagentRouterTools(Toolkit):
    """
    Generic router tool so the Executor can call subagents by name.
    """
    name = "subagent_router_tools"

    def __init__(self):
        super().__init__(name=self.name)
        self.register(self.call_subagent)

    def call_subagent(self,
                      run_context: RunContext,
                      agent_name: str,
                      input_text: str) -> str:
        """
        Dynamically call a subagent by name.
        IMPORTANT: agent_name must be exactly one of: 'Librarian', 'Researcher', 'Writer'.
        Use the agent name exactly as specified in the plan step's 'agent' field.
        """
        name_lower = agent_name.lower().strip()
        if "librarian" in name_lower:
            agent = librarian_agent
        elif "researcher" in name_lower or "research" in name_lower:
            agent = researcher_agent
        elif ("writer" in name_lower or "solution" in name_lower
              or "executor" in name_lower or "summary" in name_lower
              or "analyst" in name_lower or "compose" in name_lower
              or "content" in name_lower or "author" in name_lower):
            agent = writer_agent
        else:
            # last resort: default to Writer for final content generation
            agent = writer_agent

        resp = agent.run(input_text, session_state=run_context.session_state)
        return resp.content

subagent_router_tools = SubagentRouterTools()

# ============================================================
# 6. PLANNER AGENT (OPTIONAL – CAN BE BYPASSED)
# ============================================================

planner_agent = Agent(
    name="Planner",
    role="Planner",
    model=model,
    instructions=(
        "You create a JSON execution plan for the Context Engine.\n"
        "Input: user_goal and optional style_hint.\n"
        "Output schema:\n"
        "{\n"
        "  \"steps\": [\n"
        "    {\"id\": \"step1\", \"agent\": \"Librarian\", \"input_template\": \"...\"},\n"
        "    {\"id\": \"step2\", \"agent\": \"Researcher\", \"input_template\": \"...\"},\n"
        "    {\"id\": \"step3\", \"agent\": \"Writer\", \"input_template\": \"...\"}\n"
        "  ]\n"
        "}\n"
        "The Librarian writes semantic_blueprint to session_state automatically.\n"
        "The Researcher writes research_results to session_state automatically.\n"
        "The Writer reads both via its own tool — do NOT use {{step_id}} placeholders.\n"
        "For the Writer step, input_template should only state the goal to write about.\n"
        "Return ONLY JSON."
    ),
    markdown=False,
)

def planner_step_fn(step_input, run_context: RunContext):
    goal = run_context.session_state.get("user_goal", step_input.input)
    style_hint = run_context.session_state.get("style_hint", "Librarian can infer the style from this hint.")
    prompt = f"""
User goal:
{goal}

Style hint:
{style_hint}

Create the JSON plan now.
"""
    resp = planner_agent.run(prompt)
    try:
        plan = json.loads(resp.content)
    except Exception:
        # simple fallback plan
        plan = {
            "steps": [
                {
                    "id": "step_librarian",
                    "agent": "Librarian",
                    "input_template": f"Find the best writing style blueprint for: {style_hint}",
                },
                {
                    "id": "step_researcher",
                    "agent": "Researcher",
                    "input_template": f"Gather factual context about: {goal}",
                },
                {
                    "id": "step_writer",
                    "agent": "Writer",
                    "input_template": f"Write content for goal: {goal}",
                },
            ]
        }

    if run_context.session_state is not None:
        run_context.session_state["plan"] = plan
    return json.dumps(plan)

# ============================================================
# 7. EXECUTOR AGENT (GENERIC – USES TOOLS & SESSION STATE)
# ============================================================

executor_agent = Agent(
    name="Executor",
    role="Executor",
    model=model,
    tools=[subagent_router_tools],
    instructions=(
        "You are the Executor of a Context Engine.\n"
        "You receive a JSON plan directly in the message with a list of steps.\n"
        "Each step contains: id, agent, input_template.\n\n"
        "Algorithm:\n"
        "1) Initialize step_outputs = {} in session_state.\n"
        "2) For each step in plan.steps (in order):\n"
        "   a) Call subagent_router_tools.call_subagent(agent_name=step.agent,\n"
        "      input_text=step.input_template) to execute the subagent.\n"
        "      Each subagent reads its own dependencies from session_state via its tools.\n"
        "   b) Store the returned text in step_outputs[step.id] and update\n"
        "      session_state['step_outputs'].\n"
        "   c) Append a trace entry to session_state['trace_logs'].\n"
        "3) After all steps, write step_outputs[last_step_id] into\n"
        "   session_state['final_output'] and return it.\n\n"
        "Execute the above algorithm carefully and deterministically."
    ),
    markdown=True,
)

def executor_step_fn(step_input, run_context: RunContext):
    if run_context.session_state is not None:
        run_context.session_state.setdefault("step_outputs", {})
        run_context.session_state.setdefault("trace_logs", [])

    plan = run_context.session_state.get("plan", {"steps": []})
    plan_json = json.dumps(plan, indent=2)

    resp = executor_agent.run(
        f"Execute this plan step by step as described in your system instructions:\n\n{plan_json}\n\nReturn ONLY the final output.",
        session_state=run_context.session_state,
    )
    return run_context.session_state.get("final_output", resp.content)

# ============================================================
# 8. WORKFLOW WITH TWO STEPS
# ============================================================

planner_step = Step(
    name="Planner Step",
    executor=planner_step_fn,   # function that calls Planner agent and writes plan
    description="Planner agent produces JSON plan and stores it in session_state['plan'].",
)

executor_step = Step(
    name="Executor Step",
    executor=executor_step_fn,  # function that calls Executor agent
    description="Executor agent receives plan in prompt and calls subagents; each subagent reads its own context from session_state.",
)

context_engine_workflow = Workflow(
    name="Generic Context Engine",
    description="Two-step workflow: Planner → Executor; Executor uses team of subagents.",
    steps=[planner_step, executor_step],
    session_state={},
    db=SqliteDb(
        session_table="generic_context_engine_sessions",
        db_file="context_engine_2.db",
    ),
)

# ============================================================
# 9. PUBLIC API
# ============================================================

def run_context_engine(
    goal: str,
    style_hint: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    context_engine_workflow.session_state = {
        "user_goal": goal,
        "style_hint": style_hint,
    }
    result = context_engine_workflow.run(input=goal, session_id=session_id)
    state = context_engine_workflow.get_session_state()
    return {
        "final_output": state.get("final_output", result.content),
        "plan": state.get("plan"),
        "trace_logs": state.get("trace_logs", []),
        "session_id": result.session_id,
    }

# ============================================================
# 10. EXAMPLE
# ============================================================

if __name__ == "__main__":
    res = run_context_engine(
        goal="Explain retrieval-augmented generation to a non-technical founder.",
        style_hint="casual summary with friendly tone",
    )
    print("\n=== FINAL OUTPUT ===\n")
    print(res["final_output"])
    print("\n=== PLAN ===\n")
    print(json.dumps(res["plan"], indent=2))
    print("\n=== TRACE LOGS ===\n")
    for log in res["trace_logs"]:
        print(log)


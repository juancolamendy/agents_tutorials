from rich.pretty import pprint

from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.google import Gemini
from agno.db.sqlite import SqliteDb

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Constants
DB_FILE = "context_data.db"

# Tools

# Data structures
class ResponseModel(BaseModel):
    response: str = Field(description="LLM response")
    score: int = Field(description="Confidence of the response provided by LLM based on the reason. 0-1. 0 is lowest confidence on the response. 1 is highest confidence on the response")
    reason: str = Field(description="Reason why LLM provide the response")

# Functions
def create_agent():
    agent = Agent(
        model=Gemini(id="gemini-2.0-flash-exp"),
        # system prompt
        # role / instructions / output
        description="You are a helpful AI assistant",
        instructions=["Provide the best answer to the user questions given your knowledge", "Evaluate your response providing score and reason"],
        output_schema=ResponseModel,
        # system prompt extra
        add_datetime_to_context=True,
        
        # session storage
        db=SqliteDb(db_file=DB_FILE),
        # session history
        add_history_to_context=True,
        num_history_runs=2,
        # session state
        #add_session_state_to_context=True,
       
        # debug
        debug_mode=True,
    )
    return agent


def execute_turn(agent, turn: str):
    response = agent.run(turn)
    pprint(f"Run ID: {response.run_id}\nAgent ID: {response.agent_id}\nSession ID: {response.session_id}\nContent: {response.content}")
    return response

agent = create_agent()

while True:
    user_input = input("\nYou: ")
    if user_input == "/exit":
        break
    execute_turn(agent, user_input)

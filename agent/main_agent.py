from deepagents import create_deep_agent
from langgraph.checkpoint.memory import InMemorySaver

from agent.llm import model
from agent.prompts import main_agent_content
from agent.subagents.network_search_agent import network_search_agent
from tools.markdown_tools import generate_markdown

main_agent = create_deep_agent(
    model=model,
    system_prompt=main_agent_content["system_prompt"],
    tools=[generate_markdown],
    checkpointer=InMemorySaver(),
    subagents=[network_search_agent],
)

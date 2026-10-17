from deepagents import create_deep_agent
from langgraph.checkpoint.memory import InMemorySaver

from agent.llm import model
from agent.prompts import main_agent_content
from agent.subagents.network_search_agent import build_network_search_agent
from tools.markdown_tools import generate_markdown

# 能力按配置注册：缺 TAVILY_API_KEY 时 build_* 返回 None，直接跳过。
# 这样主智能体的工具列表和提示词都不会提到一个不存在的能力。
_subagents = [
    subagent
    for subagent in [build_network_search_agent()]
    if subagent is not None
]

_system_prompt = main_agent_content["system_prompt"]
if not _subagents:
    _system_prompt += (
        "\n\n当前不可用的能力：网络搜索助手（未配置 TAVILY_API_KEY）。"
        "不要尝试委派网络搜索；请基于已有信息回答，并明确告知用户该能力不可用。"
    )

main_agent = create_deep_agent(
    model=model,
    system_prompt=_system_prompt,
    tools=[generate_markdown],
    checkpointer=InMemorySaver(),
    subagents=_subagents,
)

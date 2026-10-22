from deepagents import create_deep_agent
from langgraph.checkpoint.memory import InMemorySaver

from agent.llm import model
from agent.prompts import main_agent_content
from agent.subagents.database_agent import build_database_agent
from agent.subagents.network_search_agent import build_network_search_agent
from tools.file_read_tool import read_file_content
from tools.markdown_tools import generate_markdown
from tools.pdf_tools import convert_md_to_pdf

# 能力按配置注册：缺依赖时工厂返回 None，直接跳过注册。
_candidates = [
    ("网络搜索助手（未配置 TAVILY_API_KEY）", build_network_search_agent()),
    ("数据库查询助手（未配置 MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE）", build_database_agent()),
]
_subagents = [subagent for _, subagent in _candidates if subagent is not None]
_unavailable = [label for label, subagent in _candidates if subagent is None]

_system_prompt = main_agent_content["system_prompt"]
if _unavailable:
    _system_prompt += (
        "\n\n当前不可用的能力：" + "、".join(_unavailable)
        + "。不要尝试委派这些助手；请基于已有信息回答，"
        "并明确告知用户该能力不可用。"
    )

main_agent = create_deep_agent(
    model=model,
    system_prompt=_system_prompt,
    tools=[generate_markdown, convert_md_to_pdf, read_file_content],
    checkpointer=InMemorySaver(),
    subagents=_subagents,
)

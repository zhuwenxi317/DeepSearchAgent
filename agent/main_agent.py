from deepagents import create_deep_agent
from langgraph.checkpoint.memory import InMemorySaver

from agent.llm import model
from agent.subagents.network_search_agent import network_search_agent
from tools.markdown_tools import generate_markdown

main_agent = create_deep_agent(
    model=model,
    system_prompt=(
        "你是团队负责人，负责协调完成用户的请求。你可以：\n"
        "- 委派给网络搜索助手：搜索互联网上的最新信息\n"
        "- 用 generate_markdown 工具：把内容写成 Markdown 报告文件\n"
        "典型流程：当用户要求研究某个主题并生成报告时，先委派网络搜索助手收集信息，"
        "再根据搜索结果用 generate_markdown 生成报告文件。"
    ),
    tools=[generate_markdown],  # 主智能体自己的工具：生成报告
    checkpointer=InMemorySaver(),
    subagents=[network_search_agent],
)

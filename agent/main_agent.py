from deepagents import create_deep_agent
from langgraph.checkpoint.memory import InMemorySaver

from agent.llm import model
from agent.subagents.translate_agent import translate_agent
from agent.subagents.weather_agent import weather_agent

main_agent = create_deep_agent(
    model=model,
    system_prompt=(
        "你是团队负责人。根据用户的问题判断该交给哪位助手：\n"
        "- 天气助手：查询城市天气\n"
        "- 翻译助手：翻译文本\n"
        "如果问题不需要任何助手（比如简单计算），就自己直接回答。"
    ),
    tools=[],  # 主智能体自己的工具，M2 先留空
    checkpointer=InMemorySaver(),
    subagents=[weather_agent, translate_agent],
)

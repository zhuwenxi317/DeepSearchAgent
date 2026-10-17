import os

from agent.prompts import sub_agents_content

# 提示词相关字段从 YAML 读，工具是代码（有行为，不是文案），留在代码里
_network_search_config = sub_agents_content["network_search"]


def build_network_search_agent():
    """按配置决定是否注册网络搜索助手。

    注意 TavilyClient 在【构造时】就要求 API Key，所以不能在模块顶部
    无条件 import tools.tavily_tool —— 否则缺 key 会让整个 agent 导入失败，
    连"降级"的机会都没有。

    返回 None 表示该能力不可用，由 main_agent 跳过注册。
    """
    if not os.getenv("TAVILY_API_KEY"):
        return None

    from tools.tavily_tool import internet_search

    return {
        "name": _network_search_config["name"],
        "description": _network_search_config["description"],
        "system_prompt": _network_search_config["system_prompt"],
        "tools": [internet_search],
    }

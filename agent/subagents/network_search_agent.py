from agent.prompts import sub_agents_content
from tools.tavily_tool import internet_search

# 提示词相关字段从 YAML 读，工具是代码（有行为，不是文案），留在代码里
_network_search_config = sub_agents_content["network_search"]

network_search_agent = {
    "name": _network_search_config["name"],
    "description": _network_search_config["description"],
    "system_prompt": _network_search_config["system_prompt"],
    "tools": [internet_search],
}

from tools.tavily_tool import internet_search

network_search_agent = {
    "name": "网络搜索助手",
    "description": "负责从互联网搜索公开信息。当用户需要了解最新资讯、新闻、趋势等需要联网查询的信息时，使用这个助手。",
    "system_prompt": "你是一个网络搜索专家。根据用户的问题进行搜索，并把搜索结果整理归纳成简洁准确的回答。",
    "tools": [internet_search],
}

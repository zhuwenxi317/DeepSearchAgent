from langchain_core.tools import tool


@tool
def fake_weather(city: str) -> str:
    """查询指定城市的天气。当用户想了解某个城市的天气时使用这个工具。

    Args:
        city: 城市名，例如"北京"或"上海"。
    """
    return f"{city} 今天晴，气温 25 度（模拟数据）"

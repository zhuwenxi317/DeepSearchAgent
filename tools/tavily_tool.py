from typing import Literal

from dotenv import load_dotenv, find_dotenv
from langchain_core.tools import tool
from tavily import TavilyClient

import os

from api.monitor import monitor

# 确保读到 .env 里的 TAVILY_API_KEY
load_dotenv(find_dotenv())

# 延迟构造：TavilyClient 在 __init__ 里就校验 key，
# 放在模块顶部会让"缺 key 时导入工具"直接抛异常，连降级的机会都没有。
_tavily_client = None


def _get_client() -> TavilyClient:
    global _tavily_client
    if _tavily_client is None:
        _tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    return _tavily_client


# on_error="return"：key 失效/网络故障时，把错误当成工具结果交给模型，
# 让它基于已有信息作答，而不是让整个 run 崩掉。
@monitor.traced_tool("网络搜索工具", on_error="return")
@tool
def internet_search(
    query: str,
    topic: Literal["news", "finance", "general"] = "general",
    max_results: int = 5,
    include_raw_content: bool = False,
):
    """根据用户问题进行网络公开信息搜索。

    注意：只用于搜索公开的网络信息；数据库查询或知识库检索请用对应的其他工具。

    Args:
        query: 要搜索的内容。
        topic: 搜索类型，news（新闻）/ finance（财经）/ general（通用）。
        max_results: 返回结果的最大条数。
        include_raw_content: 是否返回网页原文（False 只要摘要，True 要全文）。
    """
    return _get_client().search(
        query=query,
        topic=topic,
        max_results=max_results,
        include_raw_content=include_raw_content,
    )

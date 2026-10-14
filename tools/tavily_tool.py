from typing import Literal

from dotenv import load_dotenv, find_dotenv
from langchain_core.tools import tool
from tavily import TavilyClient

import os

# 确保读到 .env 里的 TAVILY_API_KEY
load_dotenv(find_dotenv())

tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))


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
    return tavily_client.search(
        query=query,
        topic=topic,
        max_results=max_results,
        include_raw_content=include_raw_content,
    )

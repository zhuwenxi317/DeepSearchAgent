from typing import Annotated

from langchain_core.tools import tool

from api.context import get_session_context
from api.monitor import monitor
from utils.path_utils import resolve_path


@monitor.traced_tool("生成Markdown")
@tool
def generate_markdown(
    content: Annotated[str, "要写入文档的文本内容"],
    filename: Annotated[str, "文件名（不含扩展名，或含 .md）"],
    path: Annotated[str, "保存路径（相对子目录，留空则写到会话根目录）"] = "",
) -> str:
    """根据文本内容生成 Markdown 文件，写入当前会话的工作目录。"""
    try:
        session_dir = get_session_context()
        if not session_dir:
            return "生成失败：当前没有设置会话目录（session_dir 未初始化）。"

        if not filename.endswith(".md"):
            filename = filename + ".md"

        safe_path = resolve_path(session_dir, path, filename)
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        safe_path.write_text(content, encoding="utf-8")

        return f"已生成文件：{safe_path}"
    except Exception as e:
        return f"生成失败：{e}"

from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool

from api.context import get_session_context
from api.monitor import monitor
from utils.path_utils import resolve_in_session
from utils.word_converter import convert_md_to_pdf_via_word


@monitor.traced_tool("Markdown转PDF工具")
@tool
def convert_md_to_pdf(
    md_filename: Annotated[
        str,
        "要转换的 Markdown 文件路径，相对当前会话目录，可含子目录，例如 report.md 或 报告/周报.md",
    ],
    pdf_filename: Annotated[
        str,
        "输出的 PDF 路径（相对会话目录，可选）。留空则与源文件同名同目录",
    ] = "",
) -> str:
    """把当前会话目录里已有的 Markdown 文件转换成 PDF（基于本机 Microsoft Word）。

    使用前提：目标 .md 文件已经存在。如果需要新内容，请先用 generate_markdown 生成。
    """
    try:
        session_dir = get_session_context()
        if not session_dir:
            return "转换失败：当前没有设置会话目录（session_dir 未初始化）。"

        md_path = resolve_in_session(session_dir, md_filename, ".md")
        if md_path is None:
            return "转换失败：md_filename 不能为空。"
        if not md_path.is_file():
            return f"转换失败：文件不存在 {md_path.name}"

        if pdf_filename.strip():
            pdf_path = resolve_in_session(session_dir, pdf_filename, ".pdf")
        else:
            pdf_path = md_path.with_suffix(".pdf")
        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        return convert_md_to_pdf_via_word(md_path, pdf_path)
    except Exception as error:
        return f"转换失败：{type(error).__name__}: {error}"

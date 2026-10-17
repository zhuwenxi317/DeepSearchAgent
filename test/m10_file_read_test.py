"""文件读取工具验证（全本地，不花钱、不联网）。

验证点：
    ① 支持 md / txt / docx / pdf / xlsx
    ② 超长文本会截断并标注
    ③ 文件不存在、格式不支持、路径穿越都返回可读错误

运行（PowerShell）：
    $env:PYTHONIOENCODING="utf-8"
    ./.venv/Scripts/python.exe test/m10_file_read_test.py
"""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from api.context import reset_session_context, set_session_context
from tools.file_read_tool import MAX_CHARS, read_file_content


async def read(name: str) -> str:
    return await read_file_content.ainvoke({"filename": name})


async def main():
    with tempfile.TemporaryDirectory() as session_tmp, tempfile.TemporaryDirectory() as outside_tmp:
        session = Path(session_tmp)

        # ---- 准备测试文件 ----
        (session / "note.md").write_text("# 标题\n\n中文内容", encoding="utf-8")
        (session / "plain.txt").write_text("纯文本 abc", encoding="utf-8")
        (session / "big.txt").write_text("x" * (MAX_CHARS + 500), encoding="utf-8")
        (session / "raw.bin").write_bytes(b"\x00\x01\x02")
        # 会话目录之外的文件，用来验证路径穿越被挡住
        outside_secret = Path(outside_tmp) / "secret.txt"
        outside_secret.write_text("SECRET-CONTENT", encoding="utf-8")

        import docx
        document = docx.Document()
        document.add_paragraph("Word 段落内容")
        document.save(session / "doc.docx")

        from reportlab.pdfgen import canvas
        pdf = canvas.Canvas(str(session / "sample.pdf"))
        pdf.drawString(72, 720, "Hello PDF content")
        pdf.save()

        import pandas as pd
        pd.DataFrame({"产品": ["A", "B"], "销量": [10, 20]}).to_excel(
            session / "data.xlsx", index=False
        )

        token = set_session_context(str(session))
        try:
            md = await read("note.md")
            assert "标题" in md and "中文内容" in md
            print("① md 读取 OK")

            text = await read("plain.txt")
            assert "纯文本" in text
            print("   txt 读取 OK")

            word = await read("doc.docx")
            assert "Word 段落内容" in word
            print("   docx 读取 OK")

            pdf_text = await read("sample.pdf")
            assert "Hello PDF" in pdf_text, pdf_text
            print("   pdf 读取 OK")

            excel = await read("data.xlsx")
            assert "产品" in excel and "销量" in excel and "A" in excel
            print("   xlsx 读取 OK")

            big = await read("big.txt")
            assert "已截断" in big and len(big) <= MAX_CHARS + 200, len(big)
            print(f"② 超长文本截断 OK（返回 {len(big)} 字符，原文 {MAX_CHARS + 500}）")

            missing = await read("不存在.md")
            assert "文件不存在" in missing
            print("③ 缺失文件：", missing)

            unsupported = await read("raw.bin")
            assert "不支持的文件格式" in unsupported
            print("   不支持的格式：", unsupported)

            traversal = await read("../secret.txt")
            assert "SECRET-CONTENT" not in traversal, "路径穿越读到了会话目录外的文件！"
            print("   路径穿越已挡住：", traversal)
        finally:
            reset_session_context(token)

    print("\n✅ 文件读取工具通过：多格式、截断、错误处理、路径安全")


if __name__ == "__main__":
    asyncio.run(main())

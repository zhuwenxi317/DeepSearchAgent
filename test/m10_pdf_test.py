"""PDF 导出验证（真实调用本机 Microsoft Word，不花钱、不联网）。

验证点：
    ① 已有的 .md 能转成非空 PDF
    ② 源文件不存在时返回可读错误，而不是抛异常

运行（PowerShell）：
    $env:PYTHONIOENCODING="utf-8"
    ./.venv/Scripts/python.exe test/m10_pdf_test.py
"""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from api.context import reset_session_context, set_session_context
from tools.pdf_tools import convert_md_to_pdf

SAMPLE_MD = """# 测试报告

这是一段中文内容，用来验证字体和排版是否正常。

| 指标 | 数值 |
|---|---|
| 销量 | 1200 |
| 增长 | 15% |

```python
print("hello")
```
"""


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        session = Path(tmp)
        (session / "报告.md").write_text(SAMPLE_MD, encoding="utf-8")

        token = set_session_context(str(session))
        try:
            result = await convert_md_to_pdf.ainvoke({"md_filename": "报告.md"})
            print(f"① 转换结果：{result}")
            pdf = session / "报告.pdf"
            assert pdf.exists(), f"PDF 未生成：{result}"
            assert pdf.stat().st_size > 1000, f"PDF 太小：{pdf.stat().st_size} 字节"
            print(f"   PDF 大小：{pdf.stat().st_size} 字节")

            missing = await convert_md_to_pdf.ainvoke({"md_filename": "不存在.md"})
            print(f"② 缺失文件：{missing}")
            assert "不存在" in missing, missing
        finally:
            reset_session_context(token)

    print("\n✅ PDF 导出通过：中文/表格/代码块可转换，缺失文件返回可读错误")


if __name__ == "__main__":
    asyncio.run(main())

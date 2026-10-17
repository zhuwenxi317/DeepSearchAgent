"""Markdown → PDF 转换（Windows / Microsoft Word COM）。

这一层只做一件事：给定两个绝对路径，完成转换并返回可读结果。
它不读取 ContextVar、不做路径校验——那些属于 tools/pdf_tools.py。

为什么用 Word COM：
    中文字体、表格、代码块的排版效果最好，而且本机已安装 Office。
    Word 不可用的环境（Linux 服务器）只需替换本文件的实现，
    上层工具和 agent 完全不用改。

线程注意：
    工具会在 asyncio 的线程池里执行，所以必须在【当前线程】里
    调用 pythoncom.CoInitialize()，否则会报 "CoInitialize has not been called"。
"""
import logging
from pathlib import Path

_WD_FORMAT_PDF = 17   # Word 常量 wdFormatPDF


def convert_md_to_pdf_via_word(md_abs_path: Path, pdf_abs_path: Path) -> str:
    try:
        import markdown
        import pythoncom
        import win32com.client
    except ImportError as error:
        return (
            f"转换失败：缺少依赖 {error.name}。"
            "请安装：pip install markdown pywin32"
        )

    temp_html_path = md_abs_path.with_suffix(".temp.html")
    word_app = None

    try:
        # 1. Markdown → HTML（tables/fenced_code 覆盖报告里最常见的两种结构）
        md_content = md_abs_path.read_text(encoding="utf-8")
        html_body = markdown.markdown(
            md_content, extensions=["tables", "fenced_code"]
        )
        html_content = f"""<!doctype html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: "Microsoft YaHei", "SimHei", sans-serif; line-height: 1.7; }}
    h1, h2, h3 {{ margin-top: 1.2em; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #333; padding: 8px; }}
    pre {{ background: #f5f5f5; padding: 10px; border-radius: 4px; white-space: pre-wrap; }}
    code {{ font-family: "Consolas", "Monaco", monospace; }}
  </style>
</head>
<body>
{html_body}
</body>
</html>"""
        temp_html_path.write_text(html_content, encoding="utf-8")

        # 2. 调 Word 转 PDF
        pythoncom.CoInitialize()
        # DispatchEx 会新开一个独立 Word 实例：
        # 如果用 Dispatch，Quit() 可能把用户正在编辑的 Word 一起关掉。
        word_app = win32com.client.DispatchEx("Word.Application")
        word_app.Visible = False
        word_app.DisplayAlerts = False

        doc = word_app.Documents.Open(str(temp_html_path.resolve()))
        try:
            doc.SaveAs(str(pdf_abs_path.resolve()), FileFormat=_WD_FORMAT_PDF)
        finally:
            doc.Close(SaveChanges=0)

        if pdf_abs_path.exists() and pdf_abs_path.stat().st_size > 0:
            return f"已生成 PDF：{pdf_abs_path}"
        return f"转换完成但未生成有效文件：{pdf_abs_path}"
    except Exception as error:
        logging.error("Word 转 PDF 失败", exc_info=True)
        return f"转换失败：{type(error).__name__}: {error}"
    finally:
        if word_app is not None:
            try:
                word_app.Quit()
            except Exception:
                pass

        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass

        try:
            temp_html_path.unlink(missing_ok=True)
        except Exception:
            pass

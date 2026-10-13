from langchain_core.tools import tool


@tool
def fake_translate(text: str, target_language: str) -> str:
    """把文本翻译成目标语言。当用户想把某段文字翻译成另一种语言时使用这个工具。

    Args:
        text: 要翻译的原文。
        target_language: 目标语言，例如"英语"、"日语"。
    """
    return f"[模拟翻译] 把「{text}」翻译成 {target_language}"

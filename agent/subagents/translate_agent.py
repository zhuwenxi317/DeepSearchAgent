from tools.fake_translate import fake_translate

translate_agent = {
    "name": "翻译助手",
    "description": "负责文本翻译。当用户想把某段文字翻译成另一种语言时，使用这个助手。",
    "system_prompt": "你是一个翻译助手，用你的工具把用户的文本翻译成目标语言。",
    "tools": [fake_translate],
}

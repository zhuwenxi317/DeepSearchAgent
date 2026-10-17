"""启动配置检查：缺少必需配置时立刻失败，缺少可选能力时降级并告警。

为什么要在启动时检查：
    LLM key 缺失如果等到第一次请求才发现，用户看到的是一个语焉不详的
    500/Traceback；启动时检查能把问题定位到"配置"而不是"代码"。

必需 vs 可选：
    必需（缺失 → 进程直接退出）：LLM 模型名、LLM API Key
    可选（缺失 → 警告 + 禁用对应能力）：Tavily 搜索、自定义 base URL
"""
import os

from dotenv import find_dotenv, load_dotenv

# 只加载一次；后续测试里临时 pop 环境变量不会被重新加载覆盖
load_dotenv(find_dotenv())

REQUIRED_CONFIG = {
    "LLM_QWEN_MAX": "LLM 模型名称（例如 deepseek-chat）",
    "OPENAI_API_KEY": "LLM 的 API Key",
}


def check_startup_config() -> list[str]:
    """检查配置。返回警告列表；必需项缺失时抛 RuntimeError。"""
    missing = [
        f"{key}（{desc}）"
        for key, desc in REQUIRED_CONFIG.items()
        if not os.getenv(key)
    ]
    if missing:
        raise RuntimeError(
            "启动失败：.env 缺少必需配置：\n"
            + "\n".join(f"  - {item}" for item in missing)
            + "\n请补齐后重试（参考 .env 与项目 README）。"
        )

    warnings = []
    if not os.getenv("OPENAI_BASE_URL"):
        warnings.append(
            "未配置 OPENAI_BASE_URL，将使用默认 OpenAI 地址；"
            "如果使用 DeepSeek 等兼容服务，请补上该配置"
        )
    if not os.getenv("TAVILY_API_KEY"):
        warnings.append("未配置 TAVILY_API_KEY，网络搜索助手已禁用")

    for warning in warnings:
        print(f"[配置警告] {warning}", flush=True)
    return warnings


def has_tavily() -> bool:
    return bool(os.getenv("TAVILY_API_KEY"))

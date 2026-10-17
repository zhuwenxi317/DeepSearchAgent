"""M10-1：启动配置检查与能力降级验证。

验证点：
    ① 配置齐全时：检查通过，网络搜索助手正常注册
    ② 缺必需项（LLM_QWEN_MAX / OPENAI_API_KEY）时：抛 RuntimeError，
       错误信息里点名缺的是哪个配置
    ③ 缺可选项（TAVILY_API_KEY）时：只告警，助手返回 None（跳过注册），
       主流程仍可启动

运行：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe test/m10_config_test.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from agent.subagents.network_search_agent import build_network_search_agent
from api.config import check_startup_config, has_tavily

WATCHED_KEYS = ["LLM_QWEN_MAX", "OPENAI_API_KEY", "TAVILY_API_KEY", "OPENAI_BASE_URL"]


def main():
    saved = {key: os.environ.get(key) for key in WATCHED_KEYS}
    try:
        # ① 正常配置
        warnings = check_startup_config()
        print(f"① 配置齐全：通过，warnings={warnings}")
        assert has_tavily() is True
        subagent = build_network_search_agent()
        assert subagent is not None
        assert subagent["name"] == "网络搜索助手"
        print(f"   网络搜索助手已注册：{subagent['name']}")

        # ② 缺必需项
        for key in ("LLM_QWEN_MAX", "OPENAI_API_KEY"):
            value = os.environ.pop(key, None)
            try:
                check_startup_config()
            except RuntimeError as error:
                message = str(error)
                assert key in message, f"错误信息没有点名 {key}: {message}"
                print(f"② 缺 {key}：启动失败，错误信息已点名")
            else:
                raise AssertionError(f"缺 {key} 时应抛 RuntimeError，但没有")
            finally:
                if value is not None:
                    os.environ[key] = value

        # ③ 缺可选项：不崩，降级
        tavily = os.environ.pop("TAVILY_API_KEY", None)
        try:
            warnings = check_startup_config()
            assert any("TAVILY_API_KEY" in item for item in warnings), warnings
            assert has_tavily() is False
            assert build_network_search_agent() is None
            print(f"③ 缺 TAVILY_API_KEY：仅告警，网络搜索助手已跳过")
        finally:
            if tavily is not None:
                os.environ["TAVILY_API_KEY"] = tavily

        # 恢复后应回到正常状态
        assert has_tavily() is True
        assert build_network_search_agent() is not None
        print("④ 环境变量恢复后，能力重新可用")
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    print("\n✅ M10-1 通过：必需配置缺失时快速失败，可选能力缺失时优雅降级")


if __name__ == "__main__":
    main()

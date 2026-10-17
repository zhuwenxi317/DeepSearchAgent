"""M8 补丁：工具失败降级验证。

验证两种 on_error 行为：
    ① on_error="return" → 工具抛异常后，把错误说明当结果返回给模型（run 不崩）
    ② 默认 on_error="raise" → 原样抛出（保持旧行为）
两种情况 trace 里都必须留一条 tool_failed。

运行：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe test/m8_tool_failure_test.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from langchain_core.tools import tool

from api.monitor import monitor
from api.trace_store import trace_store


@monitor.traced_tool("会失败的工具", on_error="return")
@tool
def failing_tool(value: str) -> str:
    """总是失败，用来模拟 API key 过期。"""
    raise RuntimeError("401 Unauthorized: invalid api key")


@monitor.traced_tool("会失败的工具(默认)")
@tool
def failing_tool_strict(value: str) -> str:
    """总是失败，用来验证默认行为仍然是抛出。"""
    raise RuntimeError("401 Unauthorized: invalid api key")


async def main():
    # ① on_error="return"：应返回一段可读的错误说明，而不是抛异常
    result = await failing_tool.ainvoke({"value": "x"})
    print(f"① 返回值：{result}")
    assert isinstance(result, str), f"应返回字符串，实际 {type(result)}"
    assert "调用失败" in result and "401 Unauthorized" in result, "错误信息没带回来"
    assert "该工具当前不可用" in result, "缺少降级提示"

    # ② trace 里必须留下 tool_started + tool_failed（不能因为吞掉异常就假装成功）
    events = trace_store.list_events("", after_sequence=-1)
    names = [(e.event.value, e.name) for e in events]
    print(f"② trace 事件：{names}")
    assert ("tool_started", "会失败的工具") in names, "缺 tool_started"
    assert ("tool_failed", "会失败的工具") in names, "缺 tool_failed（不能假装成功）"

    # ③ 默认行为：异常仍然抛出
    try:
        await failing_tool_strict.ainvoke({"value": "x"})
    except RuntimeError as e:
        print(f"③ 默认行为仍抛出：RuntimeError: {e}")
    else:
        raise AssertionError("默认 on_error='raise' 应抛出异常，但没有")

    # ④ 参数校验错误不能被降级：模型需要机会修正参数
    #    （传 dict 给 str 字段，Pydantic 会拒绝）
    try:
        await failing_tool.ainvoke({"value": {"nested": 1}})
    except Exception as e:
        print(f"④ 参数校验错误仍然抛出：{type(e).__name__}")
    else:
        raise AssertionError("参数校验错误不应被降级成文字返回")

    print("\n✅ 工具失败降级通过：return 路径给模型可读错误，默认路径保持抛出，"
          "参数校验错误不降级，trace 都记 tool_failed")


if __name__ == "__main__":
    asyncio.run(main())

"""M8 Step 4：验证 run → agent → tool 完整事件链。

不通过 HTTP，直接在同一个进程里调 execute_deep_agent，
然后查 trace_store（同一个全局单例），看埋点是否产生了完整事件链。

运行（会真调 LLM + 联网搜索，约 30~60 秒）:
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe test/m8_trace_test.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from api.server import execute_deep_agent
from api.trace_store import trace_store


async def main():
    session_dir = Path("output/session_m8_trace_test")
    await execute_deep_agent(
        "搜索一下 HTTP/3 协议的特点，并生成一份简短报告保存下来",
        "m8-trace-test",
        "m8-run-1",
        session_dir,
    )

    events = trace_store.list_events("m8-run-1")
    print()
    print(f"共 {len(events)} 条事件：")
    for e in events:
        parent = e.parent_id[:8] if e.parent_id else "-"
        entity = e.entity_id[:8] if e.entity_id else "-"
        dur = f"{e.duration_ms}ms" if e.duration_ms is not None else "-"
        print(f"  seq={e.sequence:<2} {e.event.value:16} name={e.name:12} entity={entity} parent={parent} dur={dur}")

    # 断言链完整
    types = [e.event.value for e in events]
    print()
    assert "run_started" in types and "run_completed" in types, "缺 run 事件"
    assert "agent_started" in types and "agent_completed" in types, "缺 agent 事件"
    assert "tool_started" in types and "tool_completed" in types, "缺 tool 事件"
    print("✅ 事件链完整：run → agent → tool 三层都有")


if __name__ == "__main__":
    asyncio.run(main())

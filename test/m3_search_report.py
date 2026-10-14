"""M3 验收测试：搜索 → 生成报告 完整链路。

用法（从项目根目录）:
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe test/m3_search_report.py

观察三个点：
    1. 主 agent 委派给"网络搜索助手"（task 工具）
    2. 主 agent 调用 generate_markdown 写报告
    3. 报告文件出现在会话目录 output/session_m3_demo/
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from api.context import set_session_context
from agent.main_agent import main_agent


def get_messages(state):
    """安全取出 state 里的 messages（处理 None 和 Overwrite）。"""
    if state is None or not isinstance(state, dict):
        return []
    m = state.get("messages", [])
    if type(m).__name__ == "Overwrite":
        m = m.value
    return m if isinstance(m, list) else []


async def run():
    session_dir = "output/session_m3_demo"
    Path(session_dir).mkdir(parents=True, exist_ok=True)
    set_session_context(session_dir)

    question = "帮我搜索一下 AI Agent 领域的最新发展趋势，并生成一份报告保存下来"
    print(f"问题：{question}")
    print(f"会话目录：{session_dir}")
    print()

    config = {"configurable": {"thread_id": "m3-demo"}}
    async for chunk in main_agent.astream({"messages": [("human", question)]}, config=config):
        for node_name, state in chunk.items():
            msgs = get_messages(state)
            if not msgs:
                continue
            last = msgs[-1]
            role = type(last).__name__
            tcs = getattr(last, "tool_calls", [])
            if tcs:
                for tc in tcs:
                    name = tc["name"]
                    args = tc["args"]
                    if name == "task":
                        print(f"  [{node_name}] {role} → 委派给子智能体 '{args.get('subagent_type')}'")
                    else:
                        print(f"  [{node_name}] {role} → 调用 {name}")
            else:
                content = getattr(last, "content", "")
                if content:
                    print(f"  [{node_name}] {role}: {content[:80]!r}")

    print()
    print("会话目录里生成的文件：")
    files = [p for p in Path(session_dir).rglob("*") if p.is_file()]
    for p in files:
        print(f"  {p}")


if __name__ == "__main__":
    asyncio.run(run())

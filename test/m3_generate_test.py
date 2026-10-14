"""M3 测试：generate_markdown 工具是否被调用。

用法（从项目根目录）:
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe test/m3_generate_test.py

重点观察：
    1. 流式输出里出现"调用 generate_markdown" → 工具被调用了
    2. 运行结束后 output/session_test/ 里出现 .md 文件 → 文件写到了会话目录
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
    session_dir = "output/session_test"
    Path(session_dir).mkdir(parents=True, exist_ok=True)
    # ★ 关键：先设置会话目录（ContextVar），generate_markdown 内部靠它知道写到哪
    set_session_context(session_dir)

    question = "帮我写一份关于 AI Agent 的简短学习笔记，保存成 Markdown 文件"
    print(f"问题：{question}")
    print(f"会话目录：{session_dir}")
    print()

    config = {"configurable": {"thread_id": "m3-test"}}
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
                    print(f"  [{node_name}] {role} → 调用 {tc['name']}({tc['args']})")
            else:
                content = getattr(last, "content", "")
                if content:
                    print(f"  [{node_name}] {role}: {content!r}")

    print()
    print("会话目录里生成的文件：")
    files = [p for p in Path(session_dir).rglob("*") if p.is_file()]
    if files:
        for p in files:
            print(f"  {p}")
    else:
        print("  （没有文件）")


if __name__ == "__main__":
    asyncio.run(run())

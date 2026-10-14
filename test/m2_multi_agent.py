"""M2 观察脚本：多智能体委派。

用法（从项目根目录）:
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe test/m2_multi_agent.py

观察主智能体如何通过内置的 task 工具把任务委派给子智能体（天气助手/翻译助手）。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from agent.main_agent import main_agent


def get_messages(state):
    """安全地取出 state 里的 messages 列表。

    deepagents 的中间件节点有的返回 None，有的把 messages 包成 Overwrite 对象，
    这里统一处理成列表（或空列表）。
    """
    if state is None or not isinstance(state, dict):
        return []
    m = state.get("messages", [])
    if type(m).__name__ == "Overwrite":
        m = m.value
    return m if isinstance(m, list) else []


async def run_question(question: str, thread_id: str):
    print("\n" + "=" * 66)
    print(f"问题：{question}")
    print("=" * 66)
    config = {"configurable": {"thread_id": thread_id}}
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
                        # 委派：突出 subagent_type
                        print(f"  [{node_name}] {role} → 委派给子智能体 '{args.get('subagent_type')}'")
                    else:
                        print(f"  [{node_name}] {role} → 调用 {name}({args})")
            else:
                content = getattr(last, "content", "")
                if content:
                    print(f"  [{node_name}] {role}: {content!r}")


async def main():
    await run_question("帮我查一下26年10月12日的一个新闻，简单总结就好", thread_id="weather")



if __name__ == "__main__":
    asyncio.run(main())

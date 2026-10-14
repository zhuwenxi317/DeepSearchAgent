"""M6：reset 到底解决什么问题？

场景：一个 Task 里连着干两件事（M7 的 WebSocket 连接就是这样：
      一条长连接 = 一个 Task，要处理很多条消息）。

    第一件事：生成报告 → 需要设会话目录
    第二件事：纯问答   → 不需要设会话目录，但它如果要读，会读到什么？

注意：两个场景各自跑在自己的 Task 里——create_task 会复制一份上下文副本，
     所以它们互不影响（否则第一个场景 set 的值会漏给第二个场景，
     那这个实验就白做了）。

运行：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe test/m6_reset_demo.py
"""
import asyncio
import sys
from contextvars import ContextVar

sys.stdout.reconfigure(encoding="utf-8")

session_ctx: ContextVar[str | None] = ContextVar("session_dir", default=None)


async def 场景_不reset():
    """一个 Task 里顺序干两件事，第一件设了值，干完不还。"""
    session_ctx.set("output/session_报告任务")            # 第一件事设了
    print(f"    第一件事（生成报告）：写到 {session_ctx.get()!r}")
    # ← 没有 reset，值还挂在上下文里
    print(f"    第二件事（纯问答）  ：读到 {session_ctx.get()!r}   ← ★ 泄漏")


async def 场景_有reset():
    """同样两件事，第一件干完就还。"""
    token = session_ctx.set("output/session_报告任务")
    print(f"    第一件事（生成报告）：写到 {session_ctx.get()!r}")
    session_ctx.reset(token)                              # ← 干完就还
    print(f"    第二件事（纯问答）  ：读到 {session_ctx.get()!r}   ← 干净的'没设置'")


async def main():
    print("=" * 68)
    print("❌ 不 reset：第一件事设的值，泄漏给了第二件事")
    print("=" * 68)
    await asyncio.create_task(场景_不reset())

    print()
    print("=" * 68)
    print("✅ 有 reset：干完就恢复原样，第二件事不会被污染")
    print("=" * 68)
    await asyncio.create_task(场景_有reset())


if __name__ == "__main__":
    asyncio.run(main())

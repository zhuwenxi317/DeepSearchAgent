"""M6 Step 1：复现"全局变量串台"事故，并对比 ContextVar。

运行：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe test/m6_contextvar_demo.py

关键机制：两个协程在同一个线程里交替执行。
任务 A 设完值之后遇到 await（让出执行权）→ 任务 B 进来改掉同一个全局变量
→ A 恢复执行时读到的已经是 B 的值。这就是"串台"。
"""
import asyncio
import sys
from contextvars import ContextVar

sys.stdout.reconfigure(encoding="utf-8")


# ══════════ A. 用全局变量 ══════════
global_session_dir = None


async def task_with_global(name: str, delay: float) -> str:
    global global_session_dir
    global_session_dir = f"session_{name}"   # ① 设值
    await asyncio.sleep(delay)               # ② 让出执行权（等 I/O 的真实场景）
    return f"任务{name} 想写 session_{name}，实际读到 {global_session_dir}"


# ══════════ B. 用 ContextVar ══════════
session_ctx: ContextVar[str] = ContextVar("session_dir")


async def task_with_contextvar(name: str, delay: float) -> str:
    session_ctx.set(f"session_{name}")       # ① 设值（存在本 Task 自己的副本里）
    await asyncio.sleep(delay)               # ② 让出执行权
    return f"任务{name} 想写 session_{name}，实际读到 {session_ctx.get()}"


async def main():
    print("=" * 70)
    print("A. 全局变量版本：A 先设值并 await，B 趁机改掉，A 恢复后读到 B 的值")
    print("=" * 70)
    results = await asyncio.gather(
        task_with_global("A", 0.2),   # 先设值，睡得久
        task_with_global("B", 0.1),   # 后设值，睡得短，先醒
    )
    for r in results:
        print("  " + r)

    print()
    print("=" * 70)
    print("B. ContextVar 版本：每个 Task 一份独立副本，互不影响")
    print("=" * 70)
    results = await asyncio.gather(
        task_with_contextvar("A", 0.2),
        task_with_contextvar("B", 0.1),
    )
    for r in results:
        print("  " + r)


if __name__ == "__main__":
    asyncio.run(main())

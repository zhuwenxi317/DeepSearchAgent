"""并发上下文：按 Task（协程）隔离的变量。

为什么不用全局变量：两个请求在同一个线程里交替执行，A 设完值遇到 await 让出，
B 进来把值改掉，A 恢复后读到的是 B 的值 → 串台（见 test/m6_contextvar_demo.py）。

为什么不用 threading.local：它的隔离粒度是【线程】，而 asyncio 的所有协程
共用同一个线程，所以对协程来说它等于全局变量。

ContextVar 的隔离粒度正好是【Task】——asyncio.create_task 创建新 Task 时
会复制一份当前上下文，此后各改各的副本，物理上就不可能互相覆盖。
"""
from contextvars import ContextVar, Token

# 当前会话 ID。同一个会话的多次提问共享它（checkpointer 靠它存记忆）。
_thread_id_ctx: ContextVar[str | None] = ContextVar("thread_id", default=None)

# 本次运行的 ID。一次任务 = 一个 run，用于区分"同一会话里的不同次执行"。
_run_id_ctx: ContextVar[str | None] = ContextVar("run_id", default=None)

# 当前会话的工作目录（output/session_{thread_id}/）。工具靠它知道文件写到哪。
_session_dir_ctx: ContextVar[str | None] = ContextVar("session_dir", default=None)


def set_thread_context(thread_id: str) -> Token:
    return _thread_id_ctx.set(thread_id)


def get_thread_context() -> str | None:
    return _thread_id_ctx.get()


def reset_thread_context(token: Token) -> None:
    _thread_id_ctx.reset(token)


def set_run_context(run_id: str) -> Token:
    return _run_id_ctx.set(run_id)


def get_run_context() -> str | None:
    return _run_id_ctx.get()


def reset_run_context(token: Token) -> None:
    _run_id_ctx.reset(token)


def set_session_context(path: str) -> Token:
    return _session_dir_ctx.set(path)


def get_session_context() -> str | None:
    return _session_dir_ctx.get()


def reset_session_context(token: Token) -> None:
    _session_dir_ctx.reset(token)

from contextvars import ContextVar

# 当前会话的工作目录（output/session_{thread_id}/）。
# 默认 None 表示"未设置"。工具通过 get_session_context() 读取它，从而知道文件该写到哪。
_session_dir_ctx: ContextVar[str | None] = ContextVar("session_dir", default=None)


def set_session_context(path: str):
    """设置当前会话目录。返回一个 Token（M6 做并发隔离时用 Token 精确恢复）。"""
    return _session_dir_ctx.set(path)


def get_session_context() -> str | None:
    """获取当前会话目录；未设置时返回 None。"""
    return _session_dir_ctx.get()

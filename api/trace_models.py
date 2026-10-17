"""M8 Step 1：轨迹事件建模 —— 全项目共享的「事件语言」。

一个可观测系统，本质上是给每个实体（run / agent / tool）发
started / completed / failed 三态事件，配时间戳和耗时。
这里先把「事件长什么样」用枚举 + Pydantic 定死，后面存储/埋点/前端都吃这一套。
"""
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class TraceEventType(str, Enum):
    """事件词汇表：3 个实体 × 3 种状态 = 9 种事件。

    注意：事件类型本身已经携带了「谁 + 三态」，不需要再配一个 status 字段。
    """

    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"

    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"

    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TOOL_FAILED = "tool_failed"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TraceEvent(BaseModel):
    """一条轨迹事件。

    sequence 是递增游标：客户端记住「看到第几号」，断线后只拉增量（断点续传）。
    它由 trace_store 在 append 时分配，这里默认 0 只是占位。
    """

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    thread_id: str
    run_id: str
    sequence: int = 0

    event: TraceEventType

    # 层级关系：entity_id 是「我是谁」，parent_id 是「我爸是谁」。
    # 靠这两个字段，所有事件能串成一棵 run → agent → tool 的树。
    entity_id: str | None = None
    parent_id: str | None = None

    name: str = ""                       # 实体名字：工具名 / 子智能体名 / "main"
    timestamp: str = Field(default_factory=_now_iso)
    duration_ms: int | None = None       # 只有 completed/failed 时才填

    # run_completed 时携带最终答案，供前端直接渲染。
    # 放在顶层而不是 data 里：data 会经过脱敏/截断（500 字），会把报告截掉。
    output: str | None = None

    data: dict = Field(default_factory=dict)   # 附加信息：工具参数 / 错误 / 结果摘要

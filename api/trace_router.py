"""M8 Step 6a：trace 查询接口。

两个只读接口，让前端/外部能「事后」拉取轨迹：
    GET /api/threads/{thread_id}/runs        → 列出某个会话下有哪些 run
    GET /api/runs/{run_id}/trace             → 按 sequence 拉某个 run 的事件链（支持增量）

因为 Step 5 用的是「方案 A：存储时脱敏」，trace_store 里存的已经是脱敏后的数据，
这里直接返回即可，无需再处理。
"""
from fastapi import APIRouter

from api.trace_store import trace_store

router = APIRouter(prefix="/api")


@router.get("/threads/{thread_id}/runs")
async def list_runs(thread_id: str):
    """列出某个会话下执行过的 run（按首次出现顺序）。"""
    runs = trace_store.list_runs(thread_id)
    return {"thread_id": thread_id, "runs": runs}


@router.get("/runs/{run_id}/trace")
async def get_trace(run_id: str, after_sequence: int = -1, limit: int = 100):
    """拉取某个 run 的事件链。

    after_sequence 语义：只返回 sequence 严格大于它的增量。
    默认 -1 = 从头全量拉。前端断线重连时带上「最后看到的序号」即可断点续传。
    """
    events = trace_store.list_events(run_id, after_sequence=after_sequence, limit=limit)
    return {
        "run_id": run_id,
        "after_sequence": after_sequence,
        "count": len(events),
        "events": [e.model_dump(mode="json") for e in events],
    }

"""M8 Step 2：轨迹存储 —— 内存版 InMemoryTraceStore。

三个核心设计：
    1. append 时自动分配【递增 sequence】—— 断点续传的根基
    2. list_events(run_id, after_sequence, limit) 增量拉取
    3. 容量上限：事件数 / run 数超了就淘汰最旧的（否则内存无限涨）
"""
from api.trace_models import TraceEvent


class InMemoryTraceStore:
    def __init__(self, max_runs: int = 100, max_events_per_run: int = 1000):
        self._events: dict[str, list[TraceEvent]] = {}   # run_id -> 有序事件列表
        self._next_sequence: dict[str, int] = {}          # run_id -> 下一个 sequence
        self._run_order: list[str] = []                   # run 首次出现的顺序（用于淘汰最旧的）
        self._run_thread: dict[str, str] = {}             # run_id -> thread_id（用于按 thread 查 run）
        self.max_runs = max_runs
        self.max_events_per_run = max_events_per_run

    def append(self, event: TraceEvent) -> TraceEvent:
        """存一条事件，自动分配递增 sequence。返回打了 sequence 的事件。"""
        run_id = event.run_id

        # 新 run：登记顺序 + thread 归属，顺便做 run 数量淘汰
        if run_id not in self._events:
            self._events[run_id] = []
            self._next_sequence[run_id] = 0
            self._run_thread[run_id] = event.thread_id
            self._run_order.append(run_id)
            self._evict_runs_if_needed()

        # ★ 递增游标用【计数器】，不用 len(events)：
        #   淘汰旧事件后 len 会变小，若用 len 当 sequence 就会重复编号，
        #   前端断点续传就乱了。计数器只增不减，sequence 永远唯一递增。
        seq = self._next_sequence[run_id]
        self._next_sequence[run_id] = seq + 1
        event.sequence = seq

        events = self._events[run_id]
        events.append(event)
        self._evict_events_if_needed(run_id)
        return event

    def list_events(
        self, run_id: str, after_sequence: int = -1, limit: int = 100
    ) -> list[TraceEvent]:
        """增量拉取：返回 sequence 严格大于 after_sequence 的事件，最多 limit 条。

        after_sequence 默认 -1（一条都还没有）→ 拉全部。
        前端看到第 42 号后断线，重连传 after_sequence=42 → 只拉 43 号及以后。
        """
        events = self._events.get(run_id, [])
        return [e for e in events if e.sequence > after_sequence][:limit]

    def list_runs(self, thread_id: str | None = None) -> list[str]:
        """列出 run_id（按首次出现顺序）；可选按 thread 过滤。"""
        if thread_id is None:
            return list(self._run_order)
        return [rid for rid in self._run_order if self._run_thread.get(rid) == thread_id]

    def list_run_summaries(self, thread_id: str | None = None) -> list[dict]:
        """返回 run 摘要（最新在前），供前端会话列表/恢复使用。

        状态是从事件里"推导"出来的，不额外存：
        - 有 run_completed → completed
        - 有 run_failed     → failed
        - 否则              → running
        时间取首尾事件的 timestamp。
        """
        summaries = []
        for rid in reversed(self._run_order):      # 最新在前：前端默认取 runs[0]
            if thread_id is not None and self._run_thread.get(rid) != thread_id:
                continue
            events = self._events.get(rid, [])
            status = "running"
            ended_at = None
            for event in reversed(events):
                name = event.event.value
                if name in ("run_completed", "run_failed"):
                    status = "completed" if name == "run_completed" else "failed"
                    ended_at = event.timestamp
                    break
            summaries.append({
                "run_id": rid,
                "status": status,
                "started_at": events[0].timestamp if events else None,
                "ended_at": ended_at,
                "event_count": len(events),
            })
        return summaries

    def _evict_runs_if_needed(self) -> None:
        """run 总数超上限：淘汰最早出现的 run。"""
        while len(self._run_order) > self.max_runs:
            oldest = self._run_order.pop(0)
            self._events.pop(oldest, None)
            self._next_sequence.pop(oldest, None)
            self._run_thread.pop(oldest, None)

    def _evict_events_if_needed(self, run_id: str) -> None:
        """单个 run 事件数超上限：删最早的 overflow 条。"""
        events = self._events[run_id]
        overflow = len(events) - self.max_events_per_run
        if overflow > 0:
            del events[:overflow]


# 全局单例：server.py 埋点、router 查询都用同一个实例
trace_store = InMemoryTraceStore()

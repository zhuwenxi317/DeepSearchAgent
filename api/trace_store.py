"""M8 Step 2 / 持久化：轨迹存储 —— 内存索引 + JSONL 磁盘。

读写模型：
    写：每次 append 追加一行 JSONL（只 flush，不 fsync）
    读：进程启动时扫描目录，把所有 *.jsonl 读回内存，重建索引

为什么用 JSONL 而不是数据库：
    1. 追加写 —— 不需要"读整个文件 → 改 → 写回"，进程被杀最多丢最后一行
    2. 一行一个事件 —— 排序、grep、人工排查都直观
    3. 零依赖 —— 不引入 SQLite 的 schema/迁移/并发写问题
代价：没有索引，启动时全量扫描；单机单进程适用。

注意：内存里仍然保留容量上限（max_runs / max_events_per_run），
超限的旧事件只是从内存淘汰，磁盘文件不会删。
"""
import re
from pathlib import Path
from typing import TextIO

from api.trace_models import TraceEvent

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRACE_DIR = PROJECT_ROOT / "data" / "traces"

# run_id 是服务端生成的 UUID；做一次白名单校验，
# 防止任何意外值被拼进文件名（路径穿越）。
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class TraceStore:
    def __init__(
        self,
        directory: Path | None = None,
        max_runs: int = 100,
        max_events_per_run: int = 1000,
    ):
        self.directory = Path(directory) if directory else DEFAULT_TRACE_DIR
        self.directory.mkdir(parents=True, exist_ok=True)

        self._events: dict[str, list[TraceEvent]] = {}   # run_id -> 有序事件列表
        self._next_sequence: dict[str, int] = {}          # run_id -> 下一个 sequence
        self._run_order: list[str] = []                   # run 首次出现的顺序
        self._run_thread: dict[str, str] = {}             # run_id -> thread_id
        self._handles: dict[str, TextIO] = {}             # 追加写的文件句柄缓存

        self.max_runs = max_runs
        self.max_events_per_run = max_events_per_run

        self._load_from_disk()

    # ---------- 启动加载 ----------

    def _load_from_disk(self) -> None:
        """把磁盘上的历史轨迹读回内存。

        文件按修改时间扫描；单个文件按行解析，坏行（例如进程被杀时
        写了一半的最后一行）直接跳过，不影响其它事件。
        """
        files = sorted(self.directory.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        for path in files:
            run_id = path.stem
            if not _RUN_ID_RE.fullmatch(run_id):
                continue

            events: list[TraceEvent] = []
            try:
                with path.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            events.append(TraceEvent.model_validate_json(line))
                        except Exception:
                            continue
            except OSError:
                continue

            if not events:
                continue
            events.sort(key=lambda e: e.sequence)
            self._events[run_id] = events
            self._next_sequence[run_id] = events[-1].sequence + 1
            self._run_thread[run_id] = events[0].thread_id
            self._run_order.append(run_id)
            self._evict_events_if_needed(run_id)

        # 按首条事件时间排序（ISO 时间戳可直接字典序比较）
        self._run_order.sort(key=self._started_at)
        self._evict_runs_if_needed()

    def _started_at(self, run_id: str) -> str:
        events = self._events.get(run_id)
        return events[0].timestamp if events else ""

    # ---------- 写入 ----------

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

        self._events[run_id].append(event)
        self._persist_event(event)
        self._evict_events_if_needed(run_id)
        return event

    def _persist_event(self, event: TraceEvent) -> None:
        """追加一行到 data/traces/<run_id>.jsonl。

        句柄做缓存，避免每条事件都 open/close。
        flush 只保证数据交给操作系统，不保证落盘（fsync）；
        对"进程重启后能读回"已经足够，断电场景会丢最后几条。
        """
        if not _RUN_ID_RE.fullmatch(event.run_id):
            return
        handle = self._handles.get(event.run_id)
        if handle is None:
            path = self.directory / f"{event.run_id}.jsonl"
            handle = path.open("a", encoding="utf-8")
            self._handles[event.run_id] = handle
        handle.write(event.model_dump_json() + "\n")
        handle.flush()

    def close(self) -> None:
        for handle in self._handles.values():
            handle.close()
        self._handles.clear()

    # ---------- 查询 ----------

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

    # ---------- 淘汰（只动内存，不动磁盘） ----------

    def _evict_runs_if_needed(self) -> None:
        """run 总数超上限：淘汰最早出现的 run。"""
        while len(self._run_order) > self.max_runs:
            oldest = self._run_order.pop(0)
            self._events.pop(oldest, None)
            self._next_sequence.pop(oldest, None)
            self._run_thread.pop(oldest, None)
            handle = self._handles.pop(oldest, None)
            if handle:
                handle.close()

    def _evict_events_if_needed(self, run_id: str) -> None:
        """单个 run 事件数超上限：删最早的 overflow 条。"""
        events = self._events[run_id]
        overflow = len(events) - self.max_events_per_run
        if overflow > 0:
            del events[:overflow]


# 全局单例：server.py 埋点、router 查询都用同一个实例
trace_store = TraceStore()

"""M10 前置：trace 磁盘持久化验证（不花钱、不碰网络）。

验证点：
    ① append 后磁盘出现 data/traces/<run_id>.jsonl
    ② 新建一个 TraceStore（模拟进程重启）能读回全部事件
    ③ sequence 从上次的末尾继续递增，不重号
    ④ run 摘要能正确推导（completed / event_count）
    ⑤ 进程被杀导致最后一行写了一半时，坏行被跳过，其余事件不受影响

运行：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe test/m10_persistence_test.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from api.trace_models import TraceEvent, TraceEventType
from api.trace_store import TraceStore


def make_event(run_id, event, name, entity, parent=None, thread_id="t1"):
    return TraceEvent(
        thread_id=thread_id,
        run_id=run_id,
        event=event,
        entity_id=entity,
        parent_id=parent,
        name=name,
    )


def main():
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        store = TraceStore(directory=directory)

        # ① 写一个完整生命周期
        store.append(make_event("run-abc", TraceEventType.RUN_STARTED, "main", "e-run"))
        store.append(make_event("run-abc", TraceEventType.TOOL_STARTED, "网络搜索工具", "e-tool", "e-main"))
        store.append(make_event("run-abc", TraceEventType.TOOL_COMPLETED, "网络搜索工具", "e-tool", "e-main"))
        store.append(make_event("run-abc", TraceEventType.RUN_COMPLETED, "main", "e-run"))
        # 另一个 thread 的 run，用来验证过滤
        store.append(make_event("run-xyz", TraceEventType.RUN_STARTED, "main", "e-run2", thread_id="t2"))
        store.close()

        files = sorted(p.name for p in directory.glob("*.jsonl"))
        print(f"① 磁盘文件：{files}")
        assert files == ["run-abc.jsonl", "run-xyz.jsonl"], files

        # ② 模拟进程重启：新建 store，从磁盘加载
        store2 = TraceStore(directory=directory)
        events = store2.list_events("run-abc")
        seqs = [e.sequence for e in events]
        print(f"② 重启后读回 {len(events)} 条：sequence={seqs}")
        assert seqs == [0, 1, 2, 3], seqs
        assert [e.event.value for e in events] == [
            "run_started", "tool_started", "tool_completed", "run_completed",
        ]

        # ③ 序号继续递增
        store2.append(make_event("run-abc", TraceEventType.AGENT_STARTED, "网络搜索助手", "e-agent", "e-main"))
        seqs = [e.sequence for e in store2.list_events("run-abc")]
        print(f"③ 重启后追加：sequence={seqs}")
        assert seqs[-1] == 4, seqs

        # ④ run 摘要 + thread 过滤
        summaries = store2.list_run_summaries("t1")
        print(f"④ t1 的 run 摘要：{summaries}")
        assert len(summaries) == 1
        assert summaries[0]["run_id"] == "run-abc"
        assert summaries[0]["status"] == "completed"
        assert summaries[0]["event_count"] == 5
        assert store2.list_runs("t1") == ["run-abc"]
        assert store2.list_runs("t2") == ["run-xyz"]

        # ⑤ 坏行容错：手动追加半行 JSON，重新加载
        store2.close()
        path = directory / "run-abc.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write('{"event_id": "broken", "thread_id": "t1"')   # 故意不完整
        store3 = TraceStore(directory=directory)
        recovered = store3.list_events("run-abc")
        print(f"⑤ 含坏行重新加载：{len(recovered)} 条（坏行已跳过）")
        assert len(recovered) == 5, len(recovered)
        assert [e.sequence for e in recovered] == [0, 1, 2, 3, 4]
        store3.close()

    print("\n✅ 持久化验证通过：写入、重启加载、序号续增、摘要推导、坏行容错")


if __name__ == "__main__":
    main()

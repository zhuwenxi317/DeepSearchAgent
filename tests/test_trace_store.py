"""trace_store 的确定性逻辑：序号、增量、淘汰、持久化、摘要。"""
import pytest

from api.trace_models import TraceEvent, TraceEventType
from api.trace_store import TraceStore


def make_event(
    run_id="run-1",
    event=TraceEventType.RUN_STARTED,
    name="main",
    thread_id="t1",
    entity_id="e1",
    parent_id=None,
):
    return TraceEvent(
        thread_id=thread_id,
        run_id=run_id,
        event=event,
        name=name,
        entity_id=entity_id,
        parent_id=parent_id,
    )


@pytest.fixture
def store(tmp_path):
    trace_store = TraceStore(directory=tmp_path / "traces")
    yield trace_store
    trace_store.close()   # Windows 上不关句柄会阻止临时目录清理


def test_sequence_starts_at_zero_and_increments(store):
    sequences = [
        store.append(make_event(event=TraceEventType.RUN_STARTED)).sequence,
        store.append(make_event(event=TraceEventType.AGENT_STARTED)).sequence,
        store.append(make_event(event=TraceEventType.RUN_COMPLETED)).sequence,
    ]
    assert sequences == [0, 1, 2]


def test_after_sequence_is_strict(store):
    for _ in range(4):
        store.append(make_event())

    assert [e.sequence for e in store.list_events("run-1", after_sequence=-1)] == [0, 1, 2, 3]
    assert [e.sequence for e in store.list_events("run-1", after_sequence=1)] == [2, 3]
    assert [e.sequence for e in store.list_events("run-1", after_sequence=3)] == []


def test_limit(store):
    for _ in range(5):
        store.append(make_event())
    assert len(store.list_events("run-1", limit=2)) == 2


def test_event_eviction_does_not_reuse_sequence(tmp_path):
    store = TraceStore(directory=tmp_path / "traces", max_events_per_run=2)
    for _ in range(4):
        store.append(make_event())

    # 内存里只剩最后两条，但序号必须继续往后走，不能从 0 重新开始
    events = store.list_events("run-1")
    assert [e.sequence for e in events] == [2, 3]
    assert store.append(make_event()).sequence == 4
    store.close()


def test_run_eviction_keeps_disk_file(tmp_path):
    directory = tmp_path / "traces"
    store = TraceStore(directory=directory, max_runs=1)
    store.append(make_event(run_id="run-a"))
    store.append(make_event(run_id="run-b"))

    assert store.list_runs() == ["run-b"]
    # 内存淘汰不删磁盘
    assert (directory / "run-a.jsonl").exists()
    assert (directory / "run-b.jsonl").exists()
    store.close()


def test_persistence_reload_and_sequence_continues(tmp_path):
    directory = tmp_path / "traces"
    first = TraceStore(directory=directory)
    for _ in range(3):
        first.append(make_event())
    first.close()

    second = TraceStore(directory=directory)
    assert [e.sequence for e in second.list_events("run-1")] == [0, 1, 2]
    assert second.append(make_event()).sequence == 3
    second.close()


def test_bad_last_line_is_skipped(tmp_path):
    directory = tmp_path / "traces"
    store = TraceStore(directory=directory)
    for _ in range(3):
        store.append(make_event())
    store.close()

    with (directory / "run-1.jsonl").open("a", encoding="utf-8") as handle:
        handle.write('{"event_id": "broken", "run_id": "run-1"')  # 故意写半行

    reloaded = TraceStore(directory=directory)
    assert [e.sequence for e in reloaded.list_events("run-1")] == [0, 1, 2]
    reloaded.close()


def test_run_summaries_latest_first_and_status(store):
    store.append(make_event(run_id="run-old", event=TraceEventType.RUN_STARTED))
    store.append(make_event(run_id="run-old", event=TraceEventType.RUN_COMPLETED))
    store.append(make_event(run_id="run-new", event=TraceEventType.RUN_STARTED))

    summaries = store.list_run_summaries("t1")
    assert [item["run_id"] for item in summaries] == ["run-new", "run-old"]
    assert summaries[0]["status"] == "running"
    assert summaries[1]["status"] == "completed"
    assert summaries[1]["event_count"] == 2
    assert summaries[1]["started_at"] is not None
    assert summaries[1]["ended_at"] is not None


def test_failed_status_and_thread_filter(store):
    store.append(make_event(run_id="run-fail", event=TraceEventType.RUN_STARTED))
    store.append(make_event(run_id="run-fail", event=TraceEventType.RUN_FAILED))
    store.append(make_event(run_id="run-other", thread_id="t2"))

    assert store.list_runs("t1") == ["run-fail"]
    assert store.list_runs("t2") == ["run-other"]
    assert store.list_run_summaries("t1")[0]["status"] == "failed"

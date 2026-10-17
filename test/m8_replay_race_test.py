"""M8 Step 6b-2：replay 竞态 —— pending 缓冲 + 排序 + event_id 去重。

两个部分：
  ① 确定性单测（不需要服务器）：直接驱动 ConnectionManager 和 _flush_pending，
     人为制造「补历史期间又来了新事件」的交错，验证不重不漏、顺序正确。
  ② 集成测试（需要服务器）：任务跑到一半时重连 WebSocket，
     验证最终收到的 sequence 连续、不重不漏，且与 trace 查询接口一致。

先启动 server（另开终端）：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe api/server.py
再运行：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe test/m8_replay_race_test.py
"""
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import httpx
import websockets

BASE = os.getenv("DSP_BASE_URL", "http://127.0.0.1:8000")
WS_BASE = BASE.replace("http://", "ws://").replace("https://", "wss://")


class FakeWebSocket:
    """假连接：只记录发出去的东西，不碰网络。"""

    def __init__(self):
        self.sent: list[dict] = []

    async def accept(self) -> None:
        pass

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


class InterleavingWebSocket(FakeWebSocket):
    """第一次发送时，偷偷塞一个新事件进中转缓冲。

    这精确模拟了竞态：replay/flush 正在 await send_json 的时候，
    agent 那边又产生了一条事件并走了广播路径。
    """

    def __init__(self, manager, state):
        super().__init__()
        self.manager = manager
        self.state = state
        self.injected = False

    async def send_json(self, data: dict) -> None:
        await super().send_json(data)
        if not self.injected and self.state.replaying:
            self.injected = True
            await self.manager.broadcast_event(
                "t1",
                {"event_id": "e4", "run_id": "r1", "sequence": 9, "event": "tool_completed"},
            )


async def unit_test_flush():
    """① 确定性单测：顺序、去重、发送期间新到的事件。"""
    from api.connection_manager import ConnectionManager
    from api.server import _flush_pending

    m = ConnectionManager()
    ws = InterleavingWebSocket(m, None)
    state = await m.connect(ws, "t1", "r1")
    ws.state = state

    state.replaying = True
    # 历史里已经发过 e1（seq 0），先记入已发送集合
    seen_ids = {"e1"}

    # 中转期事件，故意乱序到达；中间夹两条没有 event_id 的进度消息
    await m.broadcast_event("t1", {"event_id": "e3", "run_id": "r1", "sequence": 7, "event": "tool_started"})
    await m.broadcast_event("t1", {"type": "progress", "run_id": "r1", "message": "执行中1"})
    await m.broadcast_event("t1", {"event_id": "e2", "run_id": "r1", "sequence": 5, "event": "agent_started"})
    await m.broadcast_event("t1", {"type": "progress", "run_id": "r1", "message": "执行中2"})
    # 与历史重复的事件（模拟 t1 时刻连接已注册，e1 又被广播了一次）
    await m.broadcast_event("t1", {"event_id": "e1", "run_id": "r1", "sequence": 0, "event": "run_started"})

    assert ws.sent == [], "中转期不该直接发出去"
    assert len(state.pending) == 5, f"中转期应攒下 5 条，实际 {len(state.pending)}"

    flushed = await _flush_pending(ws, state, "r1", seen_ids)

    order = [p.get("event_id") or p.get("message") for p in ws.sent]
    print(f"① 单测发出顺序：{order}")
    assert flushed == 5, f"应发出 5 条（含发送期间新到的 e4），实际 {flushed}"
    assert order == ["执行中1", "执行中2", "e2", "e3", "e4"], f"顺序/去重不对：{order}"
    assert state.pending == [], "flush 结束后缓冲应为空"
    print("✅ ① 单测通过：中转缓冲、按 sequence 排序、event_id 去重、发送期间新事件不丢")


async def integration_test_mid_run():
    """② 集成测试：任务跑到一半重连，收到的事件应连续且不重复。"""
    thread_id = f"m8-race-{uuid.uuid4().hex[:6]}"

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{BASE}/api/task",
            json={
                "query": "搜索 HTTP/3 协议的特点，各搜几个角度，最后生成一份简短报告保存下来",
                "thread_id": thread_id,
            },
        )
        r.raise_for_status()
        run_id = r.json()["run_id"]
        print(f"\n② 已提交任务：thread={thread_id}, run={run_id}")

        # 等任务已经产生了几条事件（保证重连时任务还在跑）
        deadline = time.time() + 60
        while time.time() < deadline:
            tr = await client.get(f"{BASE}/api/runs/{run_id}/trace")
            events = tr.json()["events"]
            if len(events) >= 2:
                break
            await asyncio.sleep(0.2)

        print(f"   任务进行中（已有 {len(events)} 条事件），现在带 after_sequence=-1 重连")

        # after_sequence=-1 = 从头补全部历史（含 seq 0）
        ws_url = f"{WS_BASE}/ws/{thread_id}?run_id={run_id}&after_sequence=-1"
        received: list[dict] = []
        async with websockets.connect(ws_url) as ws:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=180)
                payload = json.loads(raw)
                if "event" not in payload:      # 进度消息 / pong
                    continue
                received.append(payload)
                if payload["event"] in ("run_completed", "run_failed"):
                    break

        # 用查询接口拿权威的完整事件链做对照。
        # ★ 必须显式放大 limit：接口默认只返回 100 条，
        #   长任务会被截断，拿它做对照会误报"多发"。
        tr = await client.get(
            f"{BASE}/api/runs/{run_id}/trace",
            params={"after_sequence": -1, "limit": 2000},
        )
        final = tr.json()["events"]

    seqs = [e["sequence"] for e in received]
    ids = [e["event_id"] for e in received]

    print(f"\n   收到 {len(received)} 条，权威 trace {len(final)} 条")
    print(f"   序号：{seqs}")

    assert len(seqs) == len(set(seqs)), f"有重复 sequence：{seqs}"
    assert len(ids) == len(set(ids)), "有重复 event_id"
    assert seqs == sorted(seqs), f"事件乱序：{seqs}"
    assert seqs == list(range(len(seqs))), f"序号有缺口：{seqs}"
    assert set(ids) == {e["event_id"] for e in final}, "收到的事件与权威 trace 不一致（漏发或多发）"

    print("✅ ② 集成测试通过：中途重连后 sequence 连续、不重不漏，与 trace 接口一致")


async def main():
    await unit_test_flush()
    if "--unit" not in sys.argv:
        await integration_test_mid_run()
    print("\n✅ M8 Step 6b-2 通过：replay 竞态已解决（pending 缓冲 + 排序 + event_id 去重）")


if __name__ == "__main__":
    asyncio.run(main())

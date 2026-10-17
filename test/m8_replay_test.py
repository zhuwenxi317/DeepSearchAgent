"""M8 Step 6b-1：断线重连补历史（replay 骨架）。

场景：任务【已经跑完】，前端模拟"断线重连"——带上 run_id + after_sequence 重连，
验证后端补发了 after_sequence 之后的历史事件。

先启动 server（另开终端）：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe api/server.py
再运行：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe test/m8_replay_test.py

验证点：
    ① 重连带 after_sequence=N 后，能补发 sequence > N 的所有历史
    ② 补发的序列和 trace 查询接口一致（不重不漏）
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


async def main():
    thread_id = f"m8-replay-{uuid.uuid4().hex[:6]}"

    async with httpx.AsyncClient(timeout=30) as client:
        # ① 提交任务，拿到 run_id
        r = await client.post(
            f"{BASE}/api/task",
            json={"query": "搜索 HTTP/3 协议特点并生成简短报告，简短一些就行，不用很多", "thread_id": thread_id},
        )
        run_id = r.json()["run_id"]
        print(f"① 提交任务：run_id={run_id}")

        # ② 等任务跑完
        deadline = time.time() + 180
        events = []
        while time.time() < deadline:
            tr = await client.get(f"{BASE}/api/runs/{run_id}/trace")
            events = tr.json()["events"]
            if any(e["event"] in ("run_completed", "run_failed") for e in events):
                break
            await asyncio.sleep(2)
        print(f"② 任务跑完，共 {len(events)} 条事件")

    # ③ 取一个中间序号，模拟"前端最后看到第 N 条"
    mid_idx = len(events) // 2
    after_seq = events[mid_idx]["sequence"]
    expected = [e for e in events if e["sequence"] > after_seq]
    print(f"③ 模拟断线重连：after_sequence={after_seq}，应补发 {len(expected)} 条")

    # ④ 重连 WS，带 run_id + after_sequence
    ws_url = f"{WS_BASE}/ws/{thread_id}?run_id={run_id}&after_sequence={after_seq}"
    received = []
    async with websockets.connect(ws_url) as ws:
        print(f"④ 已重连 WS：{ws_url}")
        # 收补发的历史，直到收到 run_completed（任务已结束，最后一条补发是它）
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=30)
            event = json.loads(raw)
            received.append(event)
            if event.get("event") in ("run_completed", "run_failed"):
                break

    # ⑤ 断言：补发的和预期一致
    print(f"\n⑤ 补发 {len(received)} 条：")
    for e in received:
        print(f"   seq={e['sequence']:<2} {e['event']}")
    assert len(received) == len(expected), f"补发 {len(received)} 条，预期 {len(expected)} 条"
    assert [e["sequence"] for e in received] == [e["sequence"] for e in expected], "补发序列和预期不一致"

    print(f"\n✅ M8 Step 6b-1 通过：断线重连能补回 after_sequence 之后的历史，不重不漏")


if __name__ == "__main__":
    asyncio.run(main())

"""M7 Step 5：推送隔离验证 —— 该收的收到，不该收的一条都没有。

先启动 server（另开一个终端）：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe api/server.py
再运行：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe test/m7_isolation_test.py

为什么这样设计：
    两个 WS 连接同时挂着，但【只提交 A 的任务】。
    于是 B 的连接应该【完全沉默】——任何一条消息漏进 B，都是串台，一目了然。
    这比"两个都提交"更严格：两个都有推送时，反而不容易看出谁进错了门。

验证点：
    ① A 的连接收到完整推送序列（阳性：该收的收到了）
    ② B 的连接在等待期内一条都收不到（阴性：不该收的没收到）
    ③ A 收到的所有消息 run_id 一致（消息确实属于 A 这一次运行）
"""
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import httpx
import websockets

BASE = os.getenv("DSP_BASE_URL", "http://127.0.0.1:8000")
WS_BASE = BASE.replace("http://", "ws://").replace("https://", "wss://")
QUERY = "搜索一下 WebSocket 协议的特点，并生成一份简短报告保存下来"
ISOLATION_WAIT = 12   # B 在这个时长里必须一条都收不到


async def main():
    thread_a = f"m7-iso-a-{uuid.uuid4().hex[:6]}"
    thread_b = f"m7-iso-b-{uuid.uuid4().hex[:6]}"

    async with websockets.connect(f"{WS_BASE}/ws/{thread_a}") as wsa, \
            websockets.connect(f"{WS_BASE}/ws/{thread_b}") as wsb:
        print(f"① 两个 WS 连接都建立")
        print(f"   wsa → thread_a = {thread_a}")
        print(f"   wsb → thread_b = {thread_b}")
        print()

        # 只提交 A 的任务
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{BASE}/api/task", json={"query": QUERY, "thread_id": thread_a}
            )
            resp.raise_for_status()
            run_a = resp.json()["run_id"]
        print(f"② 只提交了 A 的任务（run_id={run_a}）\n")

        # A 应该收到完整序列
        print("③ A 收到的推送（阳性验证：该收的收到）：")
        msgs_a = []
        while True:
            event = json.loads(await asyncio.wait_for(wsa.recv(), timeout=120))
            if event.get("type") != "progress":
                continue
            msgs_a.append(event)
            print(f"   A ◄── {event['message']}")
            if event["message"].startswith(("任务完成", "任务失败")):
                break

        # B 应该完全沉默（阴性验证：不该收的没收到）
        print(f"\n④ 等 {ISOLATION_WAIT} 秒，看 B 会不会收到东西……")
        try:
            leaked = await asyncio.wait_for(wsb.recv(), timeout=ISOLATION_WAIT)
            print(f"   ✗✗ 串台了！B 收到了：{leaked}")
            raise AssertionError("推送隔离失败：B 收到了 A 的消息")
        except asyncio.TimeoutError:
            print(f"   ✓ B 在这 {ISOLATION_WAIT} 秒里一条都没收到 —— 隔离生效")

        # 断言 A 的序列完整且归属一致
        print("\n⑤ 断言 A 的推送序列")
        assert msgs_a, "A 一条推送都没收到"
        assert msgs_a[0]["message"] == "任务开始", f"第一条是 {msgs_a[0]['message']!r}"
        assert any("委派" in m["message"] for m in msgs_a), "没看到委派子智能体"
        assert msgs_a[-1]["message"] == "任务完成", f"最后一条是 {msgs_a[-1]['message']!r}"
        assert all(m["run_id"] == run_a for m in msgs_a), "A 收到了不属于自己的消息"
        print(f"   ✓ A 收到 {len(msgs_a)} 条，run_id 全部一致，序列完整")

    print()
    print("✅ M7 Step 5 通过：推送隔离正确，该收的收到、不该收的一条没有")


if __name__ == "__main__":
    asyncio.run(main())

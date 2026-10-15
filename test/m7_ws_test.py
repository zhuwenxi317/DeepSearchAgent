"""M7 Step 4：WebSocket 实时推送验证。

先启动 server（另开一个终端，别关）：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe api/server.py
再运行本脚本：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe test/m7_ws_test.py

★ 这里用 httpx 提交任务，【不用 curl】：
  Git Bash 里 curl 传中文会破坏参数编码，后端收到非法 UTF-8 直接 400
  "There was an error parsing the body"——请求压根进不了业务代码，极易误判成后端 bug。

验证点：
    ① WS 握手成功
    ② 提交任务后，实时收到推送序列（不是等跑完才一次性拿到）
    ③ 序列覆盖「任务开始 → 委派子智能体 → … → 任务完成」
    ④ 任务结果文件确实生成了
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
QUERY = "搜索一下 HTTP/3 协议的特点，并生成一份简短报告保存下来"
RECV_TIMEOUT = 120


async def main():
    thread_id = f"m7-ws-{uuid.uuid4().hex[:8]}"
    print(f"WS 地址：{WS_BASE}/ws/{thread_id}")
    print(f"会话 ID：{thread_id}")
    print()

    async with websockets.connect(f"{WS_BASE}/ws/{thread_id}") as ws:
        print("① WS 握手成功")

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{BASE}/api/task", json={"query": QUERY, "thread_id": thread_id}
            )
            resp.raise_for_status()
            print(f"② 任务已提交：{resp.json()}")
        print()

        print("③ 实时收到的推送（边跑边到，不是最后一次性给）：")
        messages = []
        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=RECV_TIMEOUT)
                event = json.loads(raw)
                if event.get("type") != "progress":
                    continue
                messages.append(event["message"])
                print(f"   ◄── 推送：{event['message']}")
                if event["message"].startswith(("任务完成", "任务失败")):
                    break
        except asyncio.TimeoutError:
            print(f"   （{RECV_TIMEOUT} 秒没收到新推送）")

    print()
    print("④ 检查推送序列")
    assert messages, "一条推送都没收到"
    assert messages[0] == "任务开始", f"第一条不是「任务开始」，而是 {messages[0]!r}"
    assert any("委派给子智能体" in m for m in messages), "没有收到「委派子智能体」事件"
    assert messages[-1] == "任务完成", f"最后一条不是「任务完成」，而是 {messages[-1]!r}"
    print(f"   共收到 {len(messages)} 条推送，序列完整")

    print()
    print("⑤ 确认报告已落盘")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{BASE}/api/files", params={"thread_id": thread_id})
        files = resp.json()["files"]
    assert files, "没有生成报告文件"
    for f in files:
        print(f"   {f['path']}  ({f['size']} 字节)")

    print()
    print("✅ M7 Step 4 通过：实时推送序列正确，任务结果也生成")


if __name__ == "__main__":
    asyncio.run(main())

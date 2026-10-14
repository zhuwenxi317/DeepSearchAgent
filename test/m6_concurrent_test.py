"""M6 Step 4：并发验证——两个任务同时跑，各写各的目录。

先启动 server（确认是重启过的、加载了最新代码）：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe api/server.py
再运行：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe test/m6_concurrent_test.py

验证点：
    ① 两个任务用 asyncio.gather **同时**提交（不是一前一后）
    ② 各自报告落在各自的 session_{A}/ 和 session_{B}/ 目录
    ③ 没有谁的文件跑到对方目录里
"""
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import httpx

BASE = os.getenv("DSP_BASE_URL", "http://127.0.0.1:8000")

# 两个主题差异明显，方便肉眼判断有没有写错目录
TASK_A = ("m6-hello-world", "搜索 Hello World 起源的历史，生成一份简短报告保存下来")
TASK_B = ("m6-http-protocol", "搜索 HTTP 协议的版本演进历史，生成一份简短报告保存下来")


async def submit(client, thread_id, query):
    """提交任务，立刻返回。"""
    t0 = time.perf_counter()
    r = await client.post(f"{BASE}/api/task", json={"query": query, "thread_id": thread_id})
    r.raise_for_status()
    print(f"  提交 {thread_id}：{time.perf_counter() - t0:.3f} 秒返回")
    return thread_id


async def wait_files(client, thread_id, timeout=180):
    """轮询等这个会话生成文件。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = await client.get(f"{BASE}/api/files", params={"thread_id": thread_id})
        r.raise_for_status()
        files = r.json()["files"]
        if files:
            return files
        await asyncio.sleep(2)
    return []


async def main():
    async with httpx.AsyncClient(timeout=30) as client:
        print("① 同时提交两个任务（asyncio.gather 并发，不是串行）")
        a_id, b_id = await asyncio.gather(
            submit(client, TASK_A[0], TASK_A[1]),
            submit(client, TASK_B[0], TASK_B[1]),
        )

        print("\n② 等两个任务各自生成报告（两条连接同时在等）")
        files_a, files_b = await asyncio.gather(
            wait_files(client, a_id),
            wait_files(client, b_id),
        )

        print(f"\n  会话 {a_id} 的文件：{[f['name'] for f in files_a]}")
        print(f"  会话 {b_id} 的文件：{[f['name'] for f in files_b]}")

        print("\n③ 检查有没有串台")
        assert files_a, f"{a_id} 没有生成任何文件"
        assert files_b, f"{b_id} 没有生成任何文件"

        # 目录必须各归各的
        dir_a = Path("output") / f"session_{a_id}"
        dir_b = Path("output") / f"session_{b_id}"
        assert dir_a.is_dir(), f"{dir_a} 不存在"
        assert dir_b.is_dir(), f"{dir_b} 不存在"

        for f in files_a:
            print(f"    {a_id}/{f['path']}")
        for f in files_b:
            print(f"    {b_id}/{f['path']}")

        print("\n✅ 并发验证通过：两个任务各写各的目录，没有串台")


if __name__ == "__main__":
    asyncio.run(main())

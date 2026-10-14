"""实验：agent 正在跑时，事件循环还能不能受理新请求？

先启动 server，再运行：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe test/m5_loop_block_test.py

原理：POST 一个耗时任务（要联网搜索，约 20-60s），然后在它跑的过程中
连续 POST 轻量任务并测量响应时间。
    如果耗时任务阻塞了事件循环 → 后续请求会被排队，响应时间飙高。
    如果没阻塞 → 后续请求依旧毫秒级返回。
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import httpx

BASE = "http://127.0.0.1:8000"


async def measure(client, query, label):
    t0 = time.perf_counter()
    r = await client.post(f"{BASE}/api/task", json={"query": query})
    dt = time.perf_counter() - t0
    print(f"   {label}：{dt:.3f} 秒  ({r.status_code})")
    return dt


async def main():
    async with httpx.AsyncClient(timeout=60) as client:
        print("① 先空跑一次，确认服务已热（排除冷启动干扰）")
        await measure(client, "1+1等于几", "预热")

        print("\n② 提交一个耗时任务（联网搜索），不等它完成")
        heavy = await client.post(
            f"{BASE}/api/task",
            json={"query": "搜索 AI Agent 最新进展并生成报告保存下来"},
        )
        print(f"   已提交：{heavy.json()['thread_id']}")

        print("\n③ 在它执行期间，连续提交轻量任务并测量响应时间")
        times = []
        for i in range(8):
            dt = await measure(client, "1+1等于几", f"第 {i+1} 次")
            times.append(dt)
            await asyncio.sleep(1.5)

        print(f"\n④ 最长响应 {max(times):.3f} 秒")
        if max(times) > 1.0:
            print("   ⚠ 事件循环被阻塞了：耗时任务占住了循环，新请求被排队")
        else:
            print("   ✅ 事件循环没有被阻塞：新请求依旧毫秒级返回")


if __name__ == "__main__":
    asyncio.run(main())

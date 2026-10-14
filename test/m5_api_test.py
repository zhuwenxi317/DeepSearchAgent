"""M5 验收：HTTP 服务化完整链路（脚本版）。

先启动 server（另开一个终端）:
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe api/server.py
再运行本脚本:
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe test/m5_api_test.py

四个断言：
    ① POST /api/task 必须"秒回"（不等待 agent 跑完）
    ② 轮询 /api/files 最终能看到生成的报告
    ③ /api/download 能正确下载该报告
    ④ 路径穿越请求被拦截（400）
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
QUERY = "搜索 AI Agent 领域 2026 年的最新发展趋势，并生成一份报告保存下来"


async def main():
    async with httpx.AsyncClient(timeout=30) as client:
        # ① 提交任务，测量响应耗时
        t0 = time.perf_counter()
        r = await client.post(f"{BASE}/api/task", json={"query": QUERY})
        elapsed = time.perf_counter() - t0
        r.raise_for_status()
        data = r.json()
        thread_id = data["thread_id"]
        print(f"① 提交任务：{elapsed:.3f} 秒返回")
        print(f"   {data}")
        assert elapsed < 2, f"接口没有秒回（{elapsed:.1f}s）——后台任务模式没生效"

        # ② 轮询文件列表，等报告生成
        print("\n② 轮询 /api/files ...")
        deadline = time.time() + 180
        files = []
        while time.time() < deadline:
            resp = await client.get(f"{BASE}/api/files", params={"thread_id": thread_id})
            resp.raise_for_status()
            files = resp.json()["files"]
            if files:
                break
            await asyncio.sleep(2)
        print(f"   生成的文件：{files}")
        assert files, "超时 180s：没有生成任何文件"

        # ③ 下载第一个 md 文件
        target = next(f for f in files if f["name"].endswith(".md"))
        dl = await client.get(
            f"{BASE}/api/download",
            params={"thread_id": thread_id, "path": target["path"]},
        )
        dl.raise_for_status()
        print(f"\n③ 下载 {target['path']}：{len(dl.content)} 字节")

        # ④ 路径穿越必须被拦截
        atk = await client.get(
            f"{BASE}/api/download",
            params={"thread_id": thread_id, "path": "../session_2/x.md"},
        )
        print(f"④ 路径穿越请求返回：{atk.status_code} {atk.json()}")
        assert atk.status_code == 400, "路径穿越没有被拦住！"

    print("\n✅ M5 验收通过")


if __name__ == "__main__":
    asyncio.run(main())

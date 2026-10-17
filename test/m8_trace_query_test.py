"""M8 Step 6a：trace 查询接口验证。

先启动 server（另开一个终端）：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe api/server.py
再运行：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe test/m8_trace_query_test.py

验证点：
    ① POST /api/task 后，GET /api/runs/{run_id}/trace 能按 sequence 拉回完整事件链
    ② after_sequence 增量拉取正确（只返回序号更大的）
    ③ GET /api/threads/{thread_id}/runs 能列出该会话的 run
"""
import asyncio
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import httpx

BASE = os.getenv("DSP_BASE_URL", "http://127.0.0.1:8000")


async def main():
    thread_id = f"m8-query-{uuid.uuid4().hex[:6]}"

    async with httpx.AsyncClient(timeout=30) as client:
        # ① 提交任务
        r = await client.post(
            f"{BASE}/api/task",
            json={"query": "搜索 HTTP/3 协议特点并生成简短报告", "thread_id": thread_id},
        )
        r.raise_for_status()
        run_id = r.json()["run_id"]
        print(f"① 已提交任务：thread={thread_id}, run={run_id}")

        # ② 轮询 trace 接口，等任务完成
        print("② 等任务跑完（轮询 trace 接口）...")
        deadline = time.time() + 180
        events = []
        while time.time() < deadline:
            tr = await client.get(f"{BASE}/api/runs/{run_id}/trace")
            tr.raise_for_status()
            events = tr.json()["events"]
            if any(e["event"] in ("run_completed", "run_failed") for e in events):
                break
            await asyncio.sleep(2)

        # ③ 打印完整事件链
        print(f"\n③ 共 {len(events)} 条事件：")
        for e in events:
            parent = (e["parent_id"] or "-")[:8]
            entity = (e["entity_id"] or "-")[:8]
            print(f"   seq={e['sequence']:<2} {e['event']:16} name={e['name']:10} "
                  f"entity={entity} parent={parent}")

        # ④ 断言：run/agent/tool 三层都有
        types = {e["event"] for e in events}
        assert "run_started" in types and "run_completed" in types, "缺 run 事件"
        assert "agent_started" in types, "缺 agent 事件"
        assert "tool_started" in types and "tool_completed" in types, "缺 tool 事件"
        print(f"\n④ 事件链完整（run/agent/tool 三层都有）")

        # ⑤ 增量拉取
        mid = len(events) // 2
        after_seq = events[mid]["sequence"]
        inc = await client.get(
            f"{BASE}/api/runs/{run_id}/trace", params={"after_sequence": after_seq}
        )
        inc_events = inc.json()["events"]
        assert all(e["sequence"] > after_seq for e in inc_events), "增量拉取返回了不该有的旧事件"
        print(f"⑤ after_sequence={after_seq} → 增量返回 {len(inc_events)} 条，全部序号 > {after_seq}")

        # ⑥ 按 thread 查 runs（现在是摘要对象，最新在前）
        runs = await client.get(f"{BASE}/api/threads/{thread_id}/runs")
        runs.raise_for_status()
        run_list = runs.json()["runs"]
        run_ids = [r["run_id"] if isinstance(r, dict) else r for r in run_list]
        assert run_id in run_ids, f"{run_id} 不在 {run_ids} 里"
        print(f"⑥ 该 thread 的 runs：{run_list}")

    print("\n✅ M8 Step 6a 通过：查询接口正确")


if __name__ == "__main__":
    asyncio.run(main())

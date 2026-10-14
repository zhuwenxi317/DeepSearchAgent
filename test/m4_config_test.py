"""M4 验收：改 YAML 场景 → agent 行为变化，代码零改动。

用法（从项目根目录）:
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe test/m4_config_test.py

验收方法：
    1. 先跑一遍，看 agent 的自述身份
    2. 改 prompt/prompts.yml 里 main_agent.system_prompt 的场景（电子产品公司 ↔ 律师事务所）
    3. 重新运行（进程重启 = 重新 import，会重读 YAML），看身份是否跟着变
    全程不动任何 .py 文件。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from agent.main_agent import main_agent


async def run():
    question = "你好，请用一句话介绍一下你自己和你所在的团队。"
    print(f"问题：{question}")
    print()

    config = {"configurable": {"thread_id": "m4-config-demo"}}
    result = await main_agent.ainvoke({"messages": [("human", question)]}, config=config)

    answer = result["messages"][-1].content
    print("agent 的回答：")
    print(f"  {answer}")


if __name__ == "__main__":
    asyncio.run(run())

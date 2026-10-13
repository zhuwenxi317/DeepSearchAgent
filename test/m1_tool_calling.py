"""M1 观察脚本：单智能体工具调用的三个层次。

用法（从项目根目录）:
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe test/m1_tool_calling.py

说明：
    这不是 pytest 单元测试（M10 才写真正的测试），而是手动观察脚本——
    它会真调 LLM API，目的是让你看清 function calling 的完整过程。
    三个层次依次是：
      1. 原始 function calling 协议（最底层，手动完成整个循环）
      2. create_agent 自动跑完循环（dump 全部消息）
      3. 中间件 callback handler（自动打印工具调用）
"""
import sys
from pathlib import Path

# 让脚本能 import 项目根目录下的 agent/ tools/ 包
# （python test/xxx.py 时，sys.path[0] 是 test/ 而非项目根目录）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Windows 控制台默认 GBK，强制 UTF-8 输出，避免中文乱码
sys.stdout.reconfigure(encoding="utf-8")

from langchain.agents import create_agent
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import ToolMessage

from agent.llm import model
from tools.fake_weather import fake_weather

# agent 只创建一次，layer2 / layer3 复用同一个实例
agent = create_agent(model, tools=[fake_weather])


def layer1_raw_function_calling():
    print("=" * 66)
    print("【第一层】原始 function calling 协议（手动跑完整个循环）")
    print("=" * 66)

    # ① 工具被 @tool 转成了什么（这就是发给模型的"说明书"）
    print("\n① 发给模型的工具说明书：")
    print(f"   工具名    : {fake_weather.name}")
    print(f"   工具描述  : {fake_weather.description.splitlines()[0]}")
    print(f"   参数 schema: {fake_weather.args}")

    # ② bind_tools 把工具挂到模型上，然后问一个问题
    llm_with_tools = model.bind_tools([fake_weather])
    first = llm_with_tools.invoke([("human", "北京天气怎么样？")])

    print("\n② 模型第一次返回（注意 content 是空的，重点在 tool_calls）：")
    print(f"   content   : {first.content!r}")
    print(f"   tool_calls: {first.tool_calls}")

    if not first.tool_calls:
        print("   ⚠ 模型没有调用工具，结束")
        return

    # ③ 我们手动执行模型要求调用的工具
    tool_call = first.tool_calls[0]
    tool_output = fake_weather.invoke(tool_call["args"])
    print("\n③ 我们手动执行工具，得到结果：")
    print(f"   {tool_output}")

    # ④ 把结果以 ToolMessage 回填（不是 HumanMessage！），再问一次
    messages = [
        ("human", "北京天气怎么样？"),
        first,
        ToolMessage(content=tool_output, tool_call_id=tool_call["id"]),
    ]
    final = llm_with_tools.invoke(messages)
    print("\n④ 模型看到工具结果后，生成最终回答：")
    print(f"   {final.content}")


def layer2_create_agent():
    print("\n" + "=" * 66)
    print("【第二层】create_agent 自动跑完整个循环（dump 全部消息）")
    print("=" * 66)

    result = agent.invoke({"messages": [("human", "北京天气怎么样？")]})

    print("\n完整消息轨迹（每一条的角色）：")
    for i, msg in enumerate(result["messages"]):
        role = type(msg).__name__
        tool_calls = getattr(msg, "tool_calls", [])
        if tool_calls:
            calls = [(tc["name"], tc["args"]) for tc in tool_calls]
            print(f"  [{i}] {role}: tool_calls={calls}")
        else:
            content = getattr(msg, "content", "")
            print(f"  [{i}] {role}: {content!r}")


class ToolCallLogger(BaseCallbackHandler):
    """中间件：自动打印每一次工具调用（on_tool_start / on_tool_end）。"""

    def on_tool_start(self, serialized, input_str, **kwargs):
        name = serialized.get("name", "?")
        print(f"    ▶ [工具开始] {name}  参数: {input_str}")

    def on_tool_end(self, output, **kwargs):
        print(f"    ◀ [工具结束] 返回: {output}")


def layer3_middleware():
    print("\n" + "=" * 66)
    print("【第三层】中间件（callback handler）自动观察工具调用")
    print("=" * 66)

    result = agent.invoke(
        {"messages": [("human", "北京天气怎么样？")]},
        config={"callbacks": [ToolCallLogger()]},
    )
    print("\n最终答案:", result["messages"][-1].content)


if __name__ == "__main__":
    layer1_raw_function_calling()
    layer2_create_agent()
    layer3_middleware()

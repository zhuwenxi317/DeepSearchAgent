"""M8 Step 3：工具埋点 —— ToolMonitor 的 @traced_tool 装饰器。

包住一个 LangChain 工具：调用前发 TOOL_STARTED，正常返回发 TOOL_COMPLETED，
异常发 TOOL_FAILED。开发者不用在工具里手写埋点，加一行装饰器就自动记录。
"""
import time
from uuid import uuid4

from pydantic import ValidationError

from api.connection_manager import manager
from api.context import get_entity_context, get_run_context, get_thread_context
from api.trace_models import TraceEvent, TraceEventType
from api.trace_serializer import sanitize_for_trace
from api.trace_store import trace_store


class ToolMonitor:
    def traced_tool(self, tool_name: str, on_error: str = "raise"):
        """装饰器工厂：给某个工具包一层埋点。用法：

            @monitor.traced_tool("网络搜索工具")
            @tool
            def internet_search(...): ...

        on_error 决定工具抛异常后的去向：
            "raise"  —— 埋点后原样抛出（默认）。交给 LangGraph 的 ToolNode，
                        但 LangGraph 默认只兜「参数格式错」，其它异常会一路
                        冒到最外层，整个 run 失败。
            "return" —— 埋点后把错误变成一段文字返回给模型。模型会把它当成
                        工具结果，可以决定降级（比如搜索不可用就基于已有信息
                        作答）。trace 里仍然是 tool_failed，不会假装成功。
        """
        if on_error not in ("raise", "return"):
            raise ValueError(f"on_error 只能是 'raise' 或 'return'，收到 {on_error!r}")

        def decorator(tool):
            # 包装异步接口 ainvoke（agent 用 astream 跑，工具走 ainvoke 路径）。
            # ainvoke 本身在事件循环里，所以这里能 await 广播。
            original_ainvoke = tool.ainvoke

            async def traced_ainvoke(*args, **kwargs):
                thread_id = get_thread_context() or ""
                run_id = get_run_context() or ""
                entity_id = str(uuid4())          # 每次调用一个唯一身份（区分同名工具的多次调用）
                parent_id = get_entity_context()  # 当前正在跑的 agent 的 entity_id（谁调用了这个工具）
                started = time.perf_counter()
                input_repr = str(args[0])[:200] if args else ""

                # ① 先存 TOOL_STARTED，再广播（可靠性铁律）
                await self.emit(TraceEvent(
                    thread_id=thread_id, run_id=run_id,
                    event=TraceEventType.TOOL_STARTED,
                    entity_id=entity_id, parent_id=parent_id, name=tool_name,
                    data={"input": input_repr},
                ))

                try:
                    result = await original_ainvoke(*args, **kwargs)
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    await self.emit(TraceEvent(
                        thread_id=thread_id, run_id=run_id,
                        event=TraceEventType.TOOL_COMPLETED,
                        entity_id=entity_id, parent_id=parent_id, name=tool_name,
                        duration_ms=duration_ms,
                        data={"result": str(result)[:200]},
                    ))
                    return result
                except Exception as e:
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    await self.emit(TraceEvent(
                        thread_id=thread_id, run_id=run_id,
                        event=TraceEventType.TOOL_FAILED,
                        entity_id=entity_id, parent_id=parent_id, name=tool_name,
                        duration_ms=duration_ms,
                        data={"error": f"{type(e).__name__}: {e}"},
                    ))
                    if on_error == "return" and not isinstance(e, ValidationError):
                        # 参数校验错误不能走这里：模型应该有机会修正参数重试，
                        # 交给 LangGraph 的默认处理（会回一条 "请修正参数" 的 ToolMessage）。
                        # 其它错误（401、超时、网络故障）才降级成可读说明。
                        # 明确说清「别盲目重试」，否则模型很可能反复调用烧 token。
                        return (
                            f"工具「{tool_name}」调用失败：{type(e).__name__}: {e}。"
                            "如果这是权限/配置类错误，重复调用不会成功；"
                            "请基于你已经掌握的信息继续完成任务，"
                            "并在最终答复中明确告知用户该工具当前不可用、信息可能不完整。"
                        )
                    raise   # 埋点不吞异常，原样抛给上层（agent 才能知道工具失败了）

            # LangChain 的 StructuredTool 是 Pydantic 模型，__setattr__ 被拦截，
            # 直接 tool.ainvoke = ... 会抛 ValueError("object has no field 'ainvoke'")。
            # 用 object.__setattr__ 绕过 Pydantic 的校验，直接设实例属性。
            object.__setattr__(tool, "ainvoke", traced_ainvoke)
            return tool

        return decorator

    async def emit(self, event: TraceEvent) -> None:
        """先脱敏 → 再存 → 再广播。

        脱敏在最前面（方案 A）：敏感信息根本不进 trace_store，也不进广播。
        顺序铁律：能广播出去的事件，一定已经存下来了（断点续传的根基）。
        """
        event.data = sanitize_for_trace(event.data)
        trace_store.append(event)
        await manager.broadcast_event(event.thread_id, event.model_dump(mode="json"))


# 全局单例
monitor = ToolMonitor()

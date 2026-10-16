"""M5 Step 1：最小 FastAPI 服务。

核心范式：POST /api/task 受理任务 → 秒回 id → agent 在后台跑。
（"请求即受理"，而不是"请求即结果"）

启动：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe api/server.py
然后打开 http://127.0.0.1:8000/docs 看自动生成的接口文档。
"""
import asyncio
import re
import sys
import uuid
from pathlib import Path
from typing import Optional

# uvicorn 直接跑本文件时，sys.path[0] 是 api/ 而非项目根，import agent.* 会失败
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from api.connection_manager import manager
from api.monitor import monitor
from api.trace_models import TraceEvent, TraceEventType
from api.trace_router import router as trace_router

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = (PROJECT_ROOT / "output").resolve()

app = FastAPI(title="DeepSearchPro API")
app.include_router(trace_router)

# CORS：允许浏览器从其它源（端口）访问本服务。开发期放开，生产要收紧成白名单。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def safe_join(base: Path, *parts: str) -> Path:
    """把 parts 拼到 base 下，并确保结果仍然在 base 内部（且不等于 base 本身）。

    防路径穿越的通用入口，基准目录由调用方决定。
    """
    target = (base / Path(*parts)).resolve()
    # 注意 1：resolve() 会把 .. 折叠掉，之后判断才有效
    # 注意 2：必须排除"相等"——is_relative_to 对路径自身返回 True，
    #        否则 "x/.." 会解析成 base 本身，越权拿到整个目录
    # 注意 3：Path("a") / "/etc/passwd" = Path("/etc/passwd")，绝对路径会丢掉左边，
    #        所以必须用 resolve() 后的结果做判断，而不是拼接时的字符串
    if target == base or not target.is_relative_to(base):
        raise HTTPException(status_code=400, detail="非法路径：超出允许的目录范围")
    return target


def safe_under_output(*parts: str) -> Path:
    """以 output/ 为边界的 safe_join。"""
    return safe_join(OUTPUT_DIR, *parts)


# thread_id 是"不可猜的扁平标识符"：只允许字母数字下划线连字符，且是单层目录名
_THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def session_dir_of(thread_id: str) -> Path:
    """thread_id → 会话目录。格式非法直接 400。"""
    if not _THREAD_ID_RE.fullmatch(thread_id):
        raise HTTPException(status_code=400, detail="thread_id 格式非法")
    return safe_under_output(f"session_{thread_id}")

# ★ 强引用集合：create_task 返回的 Task 如果没人引用，会被 GC 回收，任务跑一半就没了
_running_tasks: set[asyncio.Task] = set()


class TaskRequest(BaseModel):
    """请求体结构。Pydantic 会自动校验：缺 query 字段直接返回 422。"""

    query: str
    thread_id: Optional[str] = None


def _get_messages(state) -> list:
    """从 astream 的节点更新里安全取出 messages。

    deepagents 的中间件节点（PatchToolCalls、TodoList）产出的是 None 或
    Overwrite 对象，直接 state["messages"] 会炸，所以统一在这里兜住。
    """
    if state is None or not isinstance(state, dict):
        return []
    m = state.get("messages", [])
    if type(m).__name__ == "Overwrite":
        m = m.value
    return m if isinstance(m, list) else []


_main_agent = None


def _load_main_agent():
    """重量级 import 只在第一次真正执行，之后再取就是命中 sys.modules 缓存。

    这个函数【必须在线程里调用】：import deepagents/langchain 要 3+ 秒，
    同步执行会冻住整个事件循环，把正在写的 HTTP 响应也一起卡住。
    """
    global _main_agent
    if _main_agent is None:
        from agent.main_agent import main_agent

        _main_agent = main_agent
    return _main_agent


async def execute_deep_agent(query: str, thread_id: str, run_id: str, session_dir: Path):
    """后台执行 agent 任务。

    「延迟导入」——不在模块顶部 import agent.main_agent。
    否则一启动 server 就要初始化模型（慢、且强制要求 .env 齐全）。
    但延迟导入的代价是"第一个请求付账"，所以必须用 to_thread 挪出事件循环。
    """
    from api.context import (
        reset_agent_context,
        reset_entity_context,
        reset_parent_context,
        reset_run_context,
        reset_session_context,
        reset_thread_context,
        set_agent_context,
        set_entity_context,
        set_parent_context,
        set_run_context,
        set_session_context,
        set_thread_context,
    )

    main_agent = await asyncio.to_thread(_load_main_agent)

    # 不在这里建目录：真正写文件的工具（generate_markdown）内部会按需 mkdir。
    # 提前建会给纯问答任务留下一堆空目录。

    # ★ set 返回 Token，收好——finally 里用它精确恢复，避免污染同一 Task 的后续执行
    token_thread = set_thread_context(thread_id)
    token_run = set_run_context(run_id)
    token_session = set_session_context(str(session_dir))

    # 事件树的两个根节点：run 是根，主 agent 挂在 run 下
    run_entity_id = str(uuid.uuid4())
    main_entity_id = str(uuid.uuid4())

    # 主 agent 执行期间，工具埋点读 entity_id 作为 parent_id，挂到主 agent 下
    token_entity = set_entity_context(main_entity_id)
    token_parent = set_parent_context(run_entity_id)
    token_agent = set_agent_context("main")

    config = {"configurable": {"thread_id": thread_id}}
    print(f"[{thread_id}] 开始执行：{query}")

    async def emit(message: str) -> None:
        """往这个 thread 的所有前端连接推一条进度。没人连着就是空操作。"""
        await manager.broadcast_event(
            thread_id, {"type": "progress", "run_id": run_id, "message": message}
        )

    try:
        await emit("任务开始")

        # 埋 run / 主 agent 的 STARTED（monitor.emit 内部先存后广播）
        await monitor.emit(TraceEvent(
            thread_id=thread_id, run_id=run_id,
            event=TraceEventType.RUN_STARTED,
            entity_id=run_entity_id, name="main",
        ))
        await monitor.emit(TraceEvent(
            thread_id=thread_id, run_id=run_id,
            event=TraceEventType.AGENT_STARTED,
            entity_id=main_entity_id, parent_id=run_entity_id, name="main",
        ))

        # 从 ainvoke 换成 astream：一次只处理一个节点，边跑边播报。
        # 工具调用由 @traced_tool 装饰器自动埋点（tool 事件）。
        # 子智能体的 agent 事件在这里【手工埋】：model 节点看到 task 调用 → STARTED，
        # tools 节点看到 task 返回（ToolMessage）→ COMPLETED。
        # 注意：子智能体内部的工具事件，parent 会挂到主 agent（不是子智能体），
        # 因为子智能体在同一个 Task 里 await 执行，entity ContextVar 不会切换。
        # 这是 LangGraph Context 传播的边界，接受这个瑕疵（不影响回放核心信息）。
        final_text = ""
        subagent_runs: dict[str, tuple[str, str]] = {}  # task 的 tool_call_id -> (entity_id, 名字)

        async for chunk in main_agent.astream(
            {"messages": [("human", query)]}, config=config
        ):
            for _node_name, update in chunk.items():
                for msg in _get_messages(update):
                    tool_calls = getattr(msg, "tool_calls", None) or []
                    if tool_calls:
                        # AIMessage：模型决定调工具
                        for tc in tool_calls:
                            if tc["name"] == "task":
                                sub_name = tc["args"].get("subagent_type", "子智能体")
                                sub_entity = str(uuid.uuid4())
                                subagent_runs[tc["id"]] = (sub_entity, sub_name)
                                await emit(f"委派给子智能体「{sub_name}」")
                                await monitor.emit(TraceEvent(
                                    thread_id=thread_id, run_id=run_id,
                                    event=TraceEventType.AGENT_STARTED,
                                    entity_id=sub_entity, parent_id=main_entity_id, name=sub_name,
                                ))
                            else:
                                await emit(f"调用工具 {tc['name']}")
                    else:
                        # ToolMessage：工具返回。若是 task 返回，埋子智能体 COMPLETED。
                        tool_call_id = getattr(msg, "tool_call_id", None)
                        if tool_call_id in subagent_runs:
                            sub_entity, sub_name = subagent_runs.pop(tool_call_id)
                            await monitor.emit(TraceEvent(
                                thread_id=thread_id, run_id=run_id,
                                event=TraceEventType.AGENT_COMPLETED,
                                entity_id=sub_entity, parent_id=main_entity_id, name=sub_name,
                            ))
                        content = getattr(msg, "content", "")
                        if content:
                            final_text = content

        # 埋 run / 主 agent 的 COMPLETED
        await monitor.emit(TraceEvent(
            thread_id=thread_id, run_id=run_id,
            event=TraceEventType.AGENT_COMPLETED,
            entity_id=main_entity_id, parent_id=run_entity_id, name="main",
        ))
        await monitor.emit(TraceEvent(
            thread_id=thread_id, run_id=run_id,
            event=TraceEventType.RUN_COMPLETED,
            entity_id=run_entity_id, name="main",
        ))

        await emit("任务完成")
        print(f"[{thread_id}] 完成：{final_text[:120]}")
    except Exception as e:
        # 后台任务没人接异常，必须自己吞掉并记录，否则异常会被静默丢弃
        print(f"[{thread_id}] 失败：{type(e).__name__}: {e}")
        await emit(f"任务失败：{type(e).__name__}: {e}")
        await monitor.emit(TraceEvent(
            thread_id=thread_id, run_id=run_id,
            event=TraceEventType.RUN_FAILED,
            entity_id=run_entity_id, name="main",
            data={"error": f"{type(e).__name__}: {e}"},
        ))
    finally:
        # 必须放 finally：中途抛异常也要恢复上下文
        reset_agent_context(token_agent)
        reset_parent_context(token_parent)
        reset_entity_context(token_entity)
        reset_session_context(token_session)
        reset_run_context(token_run)
        reset_thread_context(token_thread)


@app.post("/api/task")
async def run_task(request: TaskRequest):
    """受理任务：立刻返回 id，agent 扔进后台。"""
    thread_id = request.thread_id or str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    # ★ 校验必须在 create_task 之前：进了后台任务就没人能接住异常，
    #   客户端永远等不到结果、也收不到 400
    session_dir = session_dir_of(thread_id)

    task = asyncio.create_task(
        execute_deep_agent(request.query, thread_id, run_id, session_dir)
    )
    _running_tasks.add(task)                    # 先强引用
    task.add_done_callback(_running_tasks.discard)  # 跑完自动摘掉，防止集合无限增长

    return {"status": "started", "thread_id": thread_id, "run_id": run_id}


@app.get("/api/files")
async def list_files(thread_id: str):
    """列出某个会话目录下生成的文件。

    thread_id 是外部传入的，必须过格式校验 + 路径校验。
    """
    session_dir = session_dir_of(thread_id)
    if not session_dir.is_dir():
        return {"thread_id": thread_id, "files": []}

    files = []
    for p in sorted(session_dir.rglob("*")):
        if p.is_file():
            files.append(
                {
                    "name": p.name,
                    # 相对【会话目录】的路径，可以直接喂给 /api/download 的 path 参数
                    # （不暴露服务器绝对路径，也不含 session_xxx/ 前缀）
                    "path": p.relative_to(session_dir).as_posix(),
                    "size": p.stat().st_size,
                }
            )
    return {"thread_id": thread_id, "files": files}


@app.get("/api/download")
async def download_file(thread_id: str, path: str):
    """下载会话目录里的文件。path 是相对会话目录的路径。

    path 完全由客户端控制 → 校验边界是「这个会话目录」，不是整个 output/。
    """
    session_dir = session_dir_of(thread_id)
    target = safe_join(session_dir, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(target, filename=target.name)


@app.post("/api/upload")
async def upload_file(thread_id: str, file: UploadFile = File(...)):
    """上传文件到会话目录。"""
    session_dir = session_dir_of(thread_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    # ★ file.filename 完全由客户端控制，可能是 "../../evil.py"。
    #   只取最后一段，剥掉任何目录成分——这是防上传穿越的标准做法。
    safe_name = Path(file.filename or "").name
    if not safe_name or safe_name in {".", ".."}:
        raise HTTPException(status_code=400, detail="非法文件名")

    dest = safe_join(session_dir, safe_name)
    # 分块写，避免把整个文件读进内存（大文件会打爆内存）
    size = 0
    with dest.open("wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            f.write(chunk)

    return {"status": "uploaded", "filename": safe_name, "size": size}


@app.websocket("/ws/{thread_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    thread_id: str,
    run_id: Optional[str] = None,
    # 断线重连时带上"我最后收到的事件序号"，后端补发之后的历史。
    # M7 先留出这个参数（前端契约），补发逻辑在 M8 有了事件存储之后实现。
    after_sequence: int = 0,
):
    """前端连上这条长连接，就能实时收到这个 thread 的进度。

    这个函数【不会立刻返回】——它一直挂在 receive_text() 上等客户端说话，
    直到客户端断开才结束。这是 WebSocket 端点与 HTTP 端点最大的写法差别。
    """
    await manager.connect(websocket, thread_id, run_id)
    print(f"[WS] {thread_id} 已连接（run_id={run_id}）")

    try:
        while True:
            # 挂在这里等客户端发消息。它同时也是"保持连接活着"的机制：
            # 客户端定时发 ping，我们回 pong，中间的代理/防火墙才不会掐断长连接。
            data = await websocket.receive_text()
            await websocket.send_json({"type": "pong", "echo": data})
    except WebSocketDisconnect:
        # 客户端主动断开（关页面/断网）时，receive_text 抛这个异常
        print(f"[WS] {thread_id} 已断开")
    finally:
        # 不管正常断开还是异常退出，都要从名册上摘掉（disconnect 是幂等的）
        manager.disconnect(thread_id, websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)

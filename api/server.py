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

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = (PROJECT_ROOT / "output").resolve()

app = FastAPI(title="DeepSearchPro API")

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
        reset_run_context,
        reset_session_context,
        reset_thread_context,
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

    config = {"configurable": {"thread_id": thread_id}}
    print(f"[{thread_id}] 开始执行：{query}")

    try:
        result = await main_agent.ainvoke(
            {"messages": [("human", query)]}, config=config
        )
        print(f"[{thread_id}] 完成：{result['messages'][-1].content[:120]}")
    except Exception as e:
        # 后台任务没人接异常，必须自己吞掉并记录，否则异常会被静默丢弃
        print(f"[{thread_id}] 失败：{type(e).__name__}: {e}")
    finally:
        # 必须放 finally：中途抛异常也要恢复上下文
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)

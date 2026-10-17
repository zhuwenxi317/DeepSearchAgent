"""WebSocket 连接管理：一本「谁还连着、属于哪一单任务」的名册。

名册结构（双层字典）：
    {
        "任务A": { 连接1: 状态, 连接2: 状态 },
        "任务B": { 连接3: 状态 },
    }
      ↑ 第一层：按 thread_id 分组 —— 广播时只翻自己那一栏，这就是「推送隔离」
      ↑ 第二层：这个任务下的所有连接（一个任务可能有好几个浏览器/标签页连着）

要回答的两个问题：
    ① "给我找出所有在等 A 号任务消息的连接"  → 翻第一层，O(1) 定位到组
    ② "某条连接断了，从名册上划掉"           → 翻第二层，精确删除
"""
from dataclasses import dataclass, field
from typing import Any, Optional

from fastapi import WebSocket


@dataclass
class ConnectionState:
    """一条 WebSocket 连接的状态。"""

    websocket: WebSocket
    run_id: Optional[str] = None

    # ── replay 竞态的解法 ──────────────────────────────────────────
    # 补历史期间，实时广播【不能直接写出去】，否则会和补发的事件交错/重复。
    # 所以先标记 replaying=True，把新事件临时堆进 pending；
    # 历史发完后，再把 pending 按 sequence 排序、按 event_id 去重补发。
    #
    # 为什么按连接各存一份？每条连接的 replay 进度不同，
    # 全局一份会把 A 连接中转期的事件塞给 B 连接。
    replaying: bool = False
    pending: list[dict[str, Any]] = field(default_factory=list)


class ConnectionManager:
    def __init__(self) -> None:
        # 用 websocket 对象本身当 key：它只按身份比较，天然唯一，
        # 而且拿到 key 就等于拿到那条连接，清理时不用再查一次
        self.active_connections: dict[Optional[str], dict[WebSocket, ConnectionState]] = {}

    async def connect(
        self, websocket: WebSocket, thread_id: str, run_id: Optional[str] = None
    ) -> ConnectionState:
        """握手 + 登记。

        accept() 是握手：客户端发起的是 HTTP Upgrade 请求，
        服务器必须显式 accept 才算把这条长连接建起来。
        """
        await websocket.accept()
        state = ConnectionState(websocket=websocket, run_id=run_id)
        # setdefault：第一次见到这个 thread_id 时先建一个空组，再把连接放进去
        self.active_connections.setdefault(thread_id, {})[websocket] = state
        return state

    async def broadcast_event(self, thread_id: str, event: dict[str, Any]) -> None:
        """把事件推给这个 thread_id 下的所有连接。

        注意它「只推给同 thread」——这是推送隔离，不是体验优化：
        推错了就等于把 A 用户的搜索结果泄露给 B 用户。
        """
        group = self.active_connections.get(thread_id)
        if not group:
            return

        # 拷贝一份(list)再遍历：下面失败时会从字典里删元素，
        # 直接遍历原字典会抛 RuntimeError: dictionary changed size during iteration
        for websocket, state in list(group.items()):
            # ★ 中转期：不直接发，先排队。等这条连接把历史补完再统一发。
            #   这里只是 list.append（同步、无 await），不会和 replay 循环交错出乱序。
            if state.replaying:
                state.pending.append(event)
                continue
            try:
                await websocket.send_json(event)
            except Exception as e:
                # 推不出去说明这条连接已经废了（用户关了页面/网络断了），就地摘掉
                print(f"[WS] 推送失败，摘掉连接：{type(e).__name__}: {e}")
                self.disconnect(thread_id, websocket)

    def disconnect(self, thread_id: str, websocket: WebSocket) -> None:
        """从名册上划掉一条连接。"""
        group = self.active_connections.get(thread_id)
        if not group:
            return
        group.pop(websocket, None)
        # 这一组空了就连分组一起删掉——否则名册里会攒下一堆空壳，越积越多
        if not group:
            self.active_connections.pop(thread_id, None)

    def connection_count(self) -> int:
        """当前总连接数（排查/测试用）。"""
        return sum(len(group) for group in self.active_connections.values())


# 全局单例：server.py 直接 import 这个 manager 用
manager = ConnectionManager()

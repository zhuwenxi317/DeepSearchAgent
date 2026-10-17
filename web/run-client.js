// 一次 run 的生命周期：提交 → 连 WS → 接收事件 → 断线重连。
// 它只操作 store 和 socket，不碰 DOM。
import {
  connectTrace,
  fetchFiles,
  fetchThreadRuns,
  fetchTrace,
  startTask,
  uploadFiles,
} from "./api.js";
import { isTerminalStatus } from "./state.js";

export class RunClient {
  constructor({ store, onNotice = () => {} }) {
    this.store = store;
    this.onNotice = onNotice;
    this.socket = null;
    // 每次重连/关闭都 +1：旧 socket 的回调通过比对 generation 自行失效，
    // 避免"上一代连接"的 onclose 触发新一轮重连。
    this.socketGeneration = 0;
    this.reconnectAttempts = 0;
    this.reconnectTimer = null;
    this.heartbeatTimer = null;
    this.operationGeneration = 0;
  }

  async start({ query, threadId, files = [] }) {
    const generation = ++this.operationGeneration;
    if (files.length) {
      this.store.setTaskStatus("uploading");
      await uploadFiles(threadId, files);
      if (generation !== this.operationGeneration) return null;
    }
    this.store.setTaskStatus("starting");
    const response = await startTask(query, threadId);
    if (generation !== this.operationGeneration) return null;
    if (!response.run_id || !response.thread_id) {
      throw new Error("任务响应缺少 thread_id 或 run_id。");
    }
    this.store.beginRun({
      query,
      threadId: response.thread_id,
      runId: response.run_id,
    });
    this.connect();
    return response;
  }

  // 从历史记录恢复一次 run：先拉 run 摘要，再拉全量事件。
  async restore({ threadId, runId = null }) {
    if (!threadId) return null;
    const generation = ++this.operationGeneration;
    this.store.patch({ threadId, runId });

    const thread = await fetchThreadRuns(threadId);
    if (generation !== this.operationGeneration) return null;
    const summary = runId
      ? thread.runs?.find((item) => item.run_id === runId)
      : thread.runs?.[0];
    if (!summary) {
      if (!runId) {
        this.store.patch({ runId: null, taskStatus: "idle", connection: "idle" });
        return null;
      }
      throw new Error("当前运行记录已不可用。");
    }

    this.store.patch({ runId: summary.run_id });
    this.store.prepareRestore();
    const trace = await fetchTrace(summary.run_id, -1);
    if (generation !== this.operationGeneration) return null;
    for (const event of trace.events) {
      this.store.addEvent(event);
    }
    if (!trace.events.length) {
      this.store.patch({
        taskStatus: summary.status || "idle",
        startedAt: summary.started_at || null,
        endedAt: summary.ended_at || null,
      });
    }
    await this.refreshFiles(threadId, generation);
    if (generation !== this.operationGeneration) return null;
    if (isTerminalStatus(this.store.snapshot.taskStatus)) {
      this.store.setConnection("idle");
    } else {
      this.connect();
    }
    return summary;
  }

  async refreshFiles(threadId = this.store.snapshot.threadId, generation = this.operationGeneration) {
    if (!threadId) return [];
    try {
      const result = await fetchFiles(threadId);
      if (generation !== this.operationGeneration) return [];
      const files = result.files || [];
      this.store.setFiles(files);
      return files;
    } catch (error) {
      if (generation !== this.operationGeneration) return [];
      this.store.addClientError(error.message, "files");
      this.onNotice(`无法加载生成文件：${error.message}`);
      return [];
    }
  }

  clearTimers() {
    globalThis.clearTimeout(this.reconnectTimer);
    globalThis.clearInterval(this.heartbeatTimer);
    this.reconnectTimer = null;
    this.heartbeatTimer = null;
  }

  closeSocket(reason = "client navigation") {
    this.socketGeneration += 1;
    this.clearTimers();
    if (this.socket) {
      this.socket.close(1000, reason);
      this.socket = null;
    }
  }

  close(reason = "client navigation") {
    this.operationGeneration += 1;
    this.closeSocket(reason);
  }

  // 指数退避：1s、2s、4s…最多 15s。断网时不要疯狂重试打爆服务。
  scheduleReconnect(generation) {
    if (
      generation !== this.socketGeneration
      || isTerminalStatus(this.store.snapshot.taskStatus)
    ) {
      return;
    }
    const delay = Math.min(1000 * (2 ** this.reconnectAttempts), 15000);
    this.reconnectAttempts += 1;
    this.reconnectTimer = globalThis.setTimeout(() => this.connect(), delay);
  }

  connect() {
    const { threadId, runId, lastSequence } = this.store.snapshot;
    if (!threadId || !runId) return;

    this.closeSocket();
    const generation = this.socketGeneration;
    this.store.setConnection("connecting");

    const nextSocket = connectTrace({
      threadId,
      runId,
      afterSequence: lastSequence,
      onOpen: () => {
        if (generation !== this.socketGeneration) return;
        this.reconnectAttempts = 0;
        this.store.setConnection("connected");
        // 心跳：25s 一次，让中间的代理/防火墙别把长连接掐掉。
        this.heartbeatTimer = globalThis.setInterval(() => {
          if (nextSocket.readyState === globalThis.WebSocket.OPEN) {
            nextSocket.send("ping");
          }
        }, 25000);
      },
      onMessage: (message) => {
        if (generation !== this.socketGeneration) return;
        this.store.addRawMessage(message);
        // 进度消息（type=progress）没有 event 字段，只进原始消息，
        // 不参与事件树。
        if (message.type !== "monitor_event" && !message.event) return;

        const added = this.store.addEvent(message);
        if (added && ["run_completed", "run_failed"].includes(message.event)) {
          this.refreshFiles(threadId, generation);
          globalThis.clearInterval(this.heartbeatTimer);
        }
      },
      onError: () => {
        if (generation !== this.socketGeneration) return;
        this.store.setConnection("disconnected");
      },
      onClose: (event) => {
        if (generation !== this.socketGeneration) return;
        globalThis.clearInterval(this.heartbeatTimer);
        this.socket = null;
        this.store.setConnection("disconnected");
        if (event.code === 4404) {
          this.store.addClientError("运行记录已过期。", "websocket");
          this.onNotice("当前运行记录已过期，请重新运行任务。", true);
          return;
        }
        this.scheduleReconnect(generation);
      },
    });
    this.socket = nextSocket;
  }
}

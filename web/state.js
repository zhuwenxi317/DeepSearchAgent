const STORAGE_KEY = "deepsearchpro.console.v1";

export const ROLE_DEFINITIONS = {
  main: {
    label: "主智能体",
    purpose: "调度子智能体并给出最终答复。",
  },
  network: {
    label: "网络搜索",
    purpose: "通过 Tavily 检索公开网络信息。",
  },
  database: {
    label: "数据库查询",
    purpose: "查询 MySQL 中的数据（尚未接入）。",
  },
  knowledge: {
    label: "知识库",
    purpose: "查询 RAGFlow 知识库（尚未接入）。",
  },
  files: {
    label: "报告文件",
    purpose: "生成 Markdown / PDF 等产物。",
  },
};

const TERMINAL_EVENTS = new Set(["run_completed", "run_failed"]);
const ACTIVE_EVENTS = new Set(["agent_started", "tool_started"]);
const COMPLETED_EVENTS = new Set(["agent_completed", "tool_completed"]);
const FAILED_EVENTS = new Set(["agent_failed", "tool_failed"]);
const START_EVENT_FOR_TERMINAL_EVENT = {
  run_completed: "run_started",
  run_failed: "run_started",
  agent_completed: "agent_started",
  agent_failed: "agent_started",
  tool_completed: "tool_started",
  tool_failed: "tool_started",
};

function createRoles() {
  return Object.fromEntries(Object.keys(ROLE_DEFINITIONS).map((id) => [
    id,
    {
      id,
      status: "idle",
      lastEvent: null,
      count: 0,
      observed: false,
    },
  ]));
}

function readPersisted() {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY));
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
}

function persistable(snapshot) {
  return {
    threadId: snapshot.threadId,
    runId: snapshot.runId,
    lastSequence: snapshot.lastSequence,
  };
}

function eventKey(event) {
  return event.event_id
    || `${event.run_id || "run"}:${event.sequence || 0}:${event.event || event.type}`;
}

function lifecycleId(event) {
  return event.tool_call_id || event.entity_id || null;
}

// 我们的后端只发「事件名 + data」，没有 node_type / status / input / output / error。
// 这些字段本来就是事件名的推论，与其在后端重复存一份，不如在前端统一推导。
// 这样 trace-record / visualizer 等参考项目模块可以原样复用。
function normalizeEvent(event) {
  const name = event.event || "";
  const data = event.data || {};
  return {
    ...event,
    node_type: event.node_type || (
      name.startsWith("run_")
        ? "run"
        : name.startsWith("agent_")
          ? "agent"
          : name.startsWith("tool_")
            ? "tool"
            : undefined
    ),
    status: event.status || (
      name.endsWith("_started")
        ? "running"
        : name.endsWith("_completed")
          ? "completed"
          : name.endsWith("_failed")
            ? "failed"
            : "unknown"
    ),
    input: event.input
      ?? data.input
      ?? (typeof data.query === "string" ? { query: data.query } : null),
    output: event.output ?? data.result ?? null,
    error: event.error ?? data.error ?? null,
  };
}

// 把 completed/failed 事件合并进对应的 started 事件，避免前端列表出现
// "开始一条、结束一条" 的成对噪音。
function replaceLifecycleStart(events, event) {
  const startEvent = START_EVENT_FOR_TERMINAL_EVENT[event.event];
  const id = lifecycleId(event);
  if (!startEvent || !id) return false;

  for (let index = events.length - 1; index >= 0; index -= 1) {
    const candidate = events[index];
    if (
      candidate.event === startEvent
      && candidate.run_id === event.run_id
      && lifecycleId(candidate) === id
    ) {
      events.splice(index, 1, {
        ...event,
        input: event.input ?? candidate.input ?? null,
        started_at: event.started_at ?? candidate.started_at ?? candidate.timestamp,
      });
      return true;
    }
  }
  return false;
}

function containsAny(value, terms) {
  const text = String(value || "").toLocaleLowerCase();
  return terms.some((term) => text.includes(term));
}

// 我们没有 node_type 字段，用事件名前缀判断实体类型：
//   agent_* → 子智能体；tool_* → 工具。
export function roleForEvent(event) {
  const name = event.name || event.data?.assistant_name || event.data?.tool_name || "";
  const eventName = event.event || "";
  const kind = eventName.startsWith("agent_")
    ? "agent"
    : eventName.startsWith("tool_")
      ? "tool"
      : null;

  if (eventName === "run_started" || TERMINAL_EVENTS.has(eventName)) {
    return "main";
  }
  if (kind === "agent") {
    if (containsAny(name, ["网络", "network", "search", "搜索"])) return "network";
    if (containsAny(name, ["数据库", "database", "mysql", "sql"])) return "database";
    if (containsAny(name, ["ragflow", "知识", "knowledge"])) return "knowledge";
  }
  if (kind === "tool") {
    if (containsAny(name, ["markdown", "生成", "报告", "文档"])) return "files";
    if (containsAny(name, ["网络", "internet", "tavily"])) return "network";
    if (containsAny(name, ["数据库", "mysql", "sql", "table"])) return "database";
    if (containsAny(name, ["ragflow", "知识", "retriev"])) return "knowledge";
  }
  return null;
}

function eventStatus(event) {
  if (FAILED_EVENTS.has(event.event) || event.event === "run_failed") {
    return "failed";
  }
  if (COMPLETED_EVENTS.has(event.event) || event.event === "run_completed") {
    return "completed";
  }
  if (ACTIVE_EVENTS.has(event.event) || event.event === "run_started") {
    return "active";
  }
  return event.status === "running" ? "active" : event.status || "unknown";
}

function initialSnapshot(selection = {}) {
  const persisted = readPersisted();
  const explicitSelection = Boolean(selection.threadId || selection.runId);
  const threadId = selection.threadId || persisted.threadId || crypto.randomUUID();
  const runId = selection.runId || (selection.threadId ? null : persisted.runId) || null;
  return {
    threadId,
    runId,
    // ★ 我们的 sequence 从 0 开始；-1 表示"一条都没收到"。
    lastSequence: !explicitSelection && Number.isInteger(persisted.lastSequence)
      ? persisted.lastSequence
      : -1,
    taskStatus: runId ? "restoring" : "idle",
    connection: "idle",
    query: "",
    events: [],
    rawTraceEvents: [],
    rawMessages: [],
    clientErrors: [],
    roles: createRoles(),
    startedAt: null,
    endedAt: null,
    finalOutput: null,
    files: [],
  };
}

export class ConsoleStore {
  constructor(selection = {}) {
    this.snapshot = initialSnapshot(selection);
    this.listeners = new Set();
    this.eventIds = new Set();
    this.persist();
  }

  subscribe(listener) {
    this.listeners.add(listener);
    listener(this.snapshot);
    return () => this.listeners.delete(listener);
  }

  emit() {
    this.persist();
    for (const listener of this.listeners) {
      listener(this.snapshot);
    }
  }

  persist() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(persistable(this.snapshot)));
  }

  patch(values) {
    Object.assign(this.snapshot, values);
    this.emit();
  }

  setConnection(connection) {
    this.patch({ connection });
  }

  setTaskStatus(taskStatus) {
    this.patch({ taskStatus });
  }

  beginRun({ query, threadId, runId }) {
    this.eventIds.clear();
    this.snapshot = {
      ...this.snapshot,
      threadId,
      runId,
      lastSequence: -1,
      taskStatus: "starting",
      query,
      events: [],
      rawTraceEvents: [],
      rawMessages: [],
      clientErrors: [],
      roles: createRoles(),
      startedAt: null,
      endedAt: null,
      finalOutput: null,
      files: [],
    };
    this.emit();
  }

  newSession() {
    this.eventIds.clear();
    this.snapshot = {
      ...initialSnapshot(),
      threadId: crypto.randomUUID(),
      runId: null,
      lastSequence: -1,
      taskStatus: "idle",
    };
    this.emit();
  }

  prepareRestore() {
    this.eventIds.clear();
    this.snapshot.events = [];
    this.snapshot.rawTraceEvents = [];
    this.snapshot.rawMessages = [];
    this.snapshot.roles = createRoles();
    this.snapshot.startedAt = null;
    this.snapshot.endedAt = null;
    this.snapshot.finalOutput = null;
    this.snapshot.lastSequence = -1;
    this.emit();
  }

  addRawMessage(message) {
    this.snapshot.rawMessages.push({
      receivedAt: new Date().toISOString(),
      payload: message,
    });
    if (this.snapshot.rawMessages.length > 500) {
      this.snapshot.rawMessages.shift();
    }
    this.emit();
  }

  addClientError(message, source = "client") {
    this.snapshot.clientErrors.push({
      source,
      message: String(message),
      timestamp: new Date().toISOString(),
    });
    if (this.snapshot.clientErrors.length > 50) {
      this.snapshot.clientErrors.shift();
    }
    this.emit();
  }

  addEvent(rawEvent) {
    if (!rawEvent || typeof rawEvent !== "object" || !rawEvent.event) {
      return false;
    }
    const event = normalizeEvent(rawEvent);
    const key = eventKey(event);
    if (this.eventIds.has(key)) {
      return false;
    }
    this.eventIds.add(key);
    this.snapshot.rawTraceEvents.push(event);
    this.snapshot.rawTraceEvents.sort(
      (a, b) => (a.sequence || 0) - (b.sequence || 0),
    );
    if (!replaceLifecycleStart(this.snapshot.events, event)) {
      this.snapshot.events.push(event);
    }
    this.snapshot.events.sort((a, b) => (a.sequence || 0) - (b.sequence || 0));
    this.snapshot.lastSequence = Math.max(
      this.snapshot.lastSequence,
      Number(event.sequence) || 0,
    );

    if (event.event === "run_started") {
      this.snapshot.taskStatus = "running";
      this.snapshot.startedAt = event.started_at || event.timestamp || new Date().toISOString();
      // 后端把原始提问放在 data.query 里；恢复会话时靠它还原用户气泡。
      this.snapshot.query = event.input?.query
        || event.data?.query
        || this.snapshot.query;
    }

    const roleId = roleForEvent(event);
    if (roleId) {
      const role = this.snapshot.roles[roleId];
      const firstStart = (
        (roleId === "main" && event.event === "run_started")
        || (event.event.startsWith("agent_") && event.event === "agent_started")
        || (roleId === "files" && event.event === "tool_started")
      );
      role.observed = true;
      role.lastEvent = event;
      role.status = eventStatus(event);
      if (firstStart) {
        role.count += 1;
      }
    }

    if (event.event === "run_completed") {
      this.snapshot.taskStatus = "completed";
      this.snapshot.endedAt = event.ended_at || event.timestamp || new Date().toISOString();
      // 后端把最终答案放在顶层 output 里（data 会被截断到 500 字）
      this.snapshot.finalOutput = event.output ?? event.data?.result ?? null;
      for (const [id, role] of Object.entries(this.snapshot.roles)) {
        if (id !== "main" && role.status === "active") {
          role.status = "waiting";
        }
      }
    }

    if (event.event === "run_failed") {
      this.snapshot.taskStatus = event.status === "cancelled" ? "cancelled" : "failed";
      this.snapshot.endedAt = event.ended_at || event.timestamp || new Date().toISOString();
      for (const [id, role] of Object.entries(this.snapshot.roles)) {
        if (id !== "main" && role.status === "active") {
          role.status = "waiting";
        }
      }
    }

    this.emit();
    return true;
  }

  setFiles(files) {
    this.patch({ files: Array.isArray(files) ? files : [] });
  }
}

export function isTerminalStatus(status) {
  return ["completed", "failed", "cancelled"].includes(status);
}

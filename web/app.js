import { downloadUrl } from "./api.js";
import { renderMarkdown, stringifyValue } from "./markdown.js";
import { RunClient } from "./run-client.js";
import {
  chatUrl,
  createSessionRecord,
  parseTraceSelection,
  restoredQuery,
  SessionRepository,
} from "./session.js";
import {
  ConsoleStore,
  ROLE_DEFINITIONS,
} from "./state.js";
import {
  ExecutionVisualizer,
  statusForNode,
} from "./visualizer.js";
import {
  traceCallRecords,
  traceRecordKind,
  traceRecordListFields,
  traceRecordName,
  traceRecordSearchText,
  traceRecordStatusLabel,
  traceValueSummary,
} from "./trace-record.js";

const repository = new SessionRepository();
const fallback = repository.list()[0] || {};
const viewParams = new URLSearchParams(window.location.search);
const selection = parseTraceSelection(window.location.search, fallback);
const store = new ConsoleStore(selection);
const elements = Object.fromEntries(
  [...document.querySelectorAll("[id]")].map((element) => [element.id, element]),
);

let queuedFiles = [];
let selected = { kind: "node", id: "main" };
let selectedTrigger = null;
let inspectorTab = "overview";
let bottomTab = ["events", "report", "files", "raw"].includes(viewParams.get("tab"))
  ? viewParams.get("tab")
  : "events";
let eventSearch = viewParams.get("event_search") || "";
let eventStatusFilter = ["all", "running", "completed", "failed"].includes(
  viewParams.get("event_status"),
)
  ? viewParams.get("event_status")
  : "all";
let inputRunId = null;
let lastReportedOutput = Symbol("initial");
let noticeTimer = null;
const runClient = new RunClient({ store, onNotice: showNotice });

const visualizer = new ExecutionVisualizer(
  elements["execution-graph"],
  (nodeId) => selectNode(nodeId),
);

function makeElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function formatIdentifier(value) {
  if (!value) return "—";
  return value.length > 18
    ? `${value.slice(0, 9)}…${value.slice(-5)}`
    : value;
}

function formatStatus(status) {
  return {
    idle: "空闲",
    active: "运行中",
    running: "运行中",
    waiting: "等待中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
    unknown: "未知",
  }[status] || status || "未知";
}

function formatEventName(event) {
  return {
    run_started: "任务开始",
    run_completed: "任务完成",
    run_failed: "任务失败",
    agent_started: "子助手开始",
    agent_completed: "子助手完成",
    agent_failed: "子助手失败",
    tool_started: "工具开始",
    tool_completed: "工具完成",
    tool_failed: "工具失败",
  }[event] || String(event || "unknown").replaceAll("_", " ");
}

function formatTime(value, includeDate = false) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(undefined, {
    ...(includeDate ? { year: "numeric", month: "short", day: "2-digit" } : {}),
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function formatDuration(milliseconds) {
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return "—";
  if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`;
  const seconds = Math.floor(milliseconds / 1000);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  if (hours) return `${hours}h ${String(minutes).padStart(2, "0")}m`;
  if (minutes) return `${minutes}m ${String(remainder).padStart(2, "0")}s`;
  return `${remainder}s`;
}

function showNotice(message, sticky = false) {
  clearTimeout(noticeTimer);
  elements["notice-text"].textContent = String(message);
  elements.notice.classList.remove("hidden");
  if (!sticky) {
    noticeTimer = window.setTimeout(() => {
      elements.notice.classList.add("hidden");
    }, 7000);
  }
}

function syncViewUrl() {
  const url = new URL(window.location.href);
  if (store.snapshot.threadId) url.searchParams.set("thread_id", store.snapshot.threadId);
  else url.searchParams.delete("thread_id");
  if (store.snapshot.runId) url.searchParams.set("run_id", store.snapshot.runId);
  else url.searchParams.delete("run_id");
  if (bottomTab === "events") url.searchParams.delete("tab");
  else url.searchParams.set("tab", bottomTab);
  if (eventSearch) url.searchParams.set("event_search", eventSearch);
  else url.searchParams.delete("event_search");
  if (eventStatusFilter === "all") url.searchParams.delete("event_status");
  else url.searchParams.set("event_status", eventStatusFilter);
  history.replaceState(null, "", url);
}

function taskLabel(status) {
  return {
    idle: "空闲",
    uploading: "上传中",
    starting: "启动中",
    restoring: "恢复中",
    running: "运行中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
  }[status] || formatStatus(status);
}

function connectionLabel(status) {
  return {
    idle: store.snapshot.runId ? "已载入轨迹" : "暂无运行",
    connecting: "连接中",
    connected: "实时连接",
    disconnected: "已断开",
  }[status] || formatStatus(status);
}

function updateElapsed(snapshot = store.snapshot) {
  if (!snapshot.startedAt) {
    elements["metric-elapsed"].textContent = "—";
    return;
  }
  const start = new Date(snapshot.startedAt).getTime();
  const end = snapshot.endedAt
    ? new Date(snapshot.endedAt).getTime()
    : Date.now();
  elements["metric-elapsed"].textContent = formatDuration(end - start);
}

function latestActiveRole(snapshot) {
  return Object.values(snapshot.roles)
    .filter((role) => role.status === "active")
    .sort((a, b) => {
      const aSequence = a.lastEvent?.sequence || 0;
      const bSequence = b.lastEvent?.sequence || 0;
      return bSequence - aSequence;
    })[0];
}

function callRecords(snapshot) {
  return traceCallRecords(snapshot.events);
}

function renderHeader(snapshot) {
  elements["thread-id"].textContent = formatIdentifier(snapshot.threadId);
  elements["thread-id"].title = snapshot.threadId;
  elements["run-id"].textContent = formatIdentifier(snapshot.runId);
  elements["run-id"].title = snapshot.runId || "";
  elements["chat-link"].href = chatUrl(snapshot.threadId, snapshot.runId);

  const query = restoredQuery(inputRunId, snapshot);
  if (query !== null) {
    elements["task-input"].value = query;
    inputRunId = snapshot.runId;
  }

  elements["connection-pill"].dataset.status = snapshot.connection;
  elements["connection-label"].textContent = connectionLabel(snapshot.connection);
  elements["task-state"].dataset.status = snapshot.taskStatus;
  elements["task-state"].textContent = taskLabel(snapshot.taskStatus);

  const busy = ["uploading", "starting", "restoring", "running"].includes(
    snapshot.taskStatus,
  );
  elements["run-button"].disabled = busy || !elements["task-input"].value.trim();
  elements["run-button"].textContent = busy ? taskLabel(snapshot.taskStatus) : "运行检索";
}

function renderMetrics(snapshot) {
  const records = callRecords(snapshot);
  elements["metric-events"].textContent = String(records.length);
  elements["metric-tools"].textContent = String(
    records.filter((event) => event.node_type === "tool").length,
  );
  elements["metric-files"].textContent = String(snapshot.files.length);
  elements["metric-connection"].textContent = connectionLabel(snapshot.connection);
  const activeRole = latestActiveRole(snapshot);
  elements["metric-agent"].textContent = activeRole
    ? ROLE_DEFINITIONS[activeRole.id].label
    : "—";
  updateElapsed(snapshot);
}

function renderAgents(snapshot) {
  let activeCount = 0;
  for (const card of document.querySelectorAll("[data-role]")) {
    const role = snapshot.roles[card.dataset.role];
    if (!role) continue;
    if (role.status === "active") activeCount += 1;
    card.dataset.status = role.status;
    card.classList.toggle(
      "selected",
      selected.kind === "node" && selected.id === card.dataset.role,
    );
    const badge = card.querySelector("[data-agent-status]");
    badge.textContent = formatStatus(role.status);
    badge.dataset.status = role.status;
    card.querySelector("[data-agent-event]").textContent = role.lastEvent
      ? role.lastEvent.message || formatEventName(role.lastEvent.event)
      : "未观察到事件";
    card.querySelector("[data-agent-availability]").textContent = role.observed
      ? "已观察到"
      : "状态未报告";
    card.querySelector("[data-agent-count]").textContent =
      `${role.count} 次触发`;
  }
  elements["active-role-count"].textContent = `${activeCount} 个活跃`;
}

function openInspector(nextSelection, trigger = document.activeElement) {
  selected = nextSelection;
  selectedTrigger = trigger instanceof HTMLElement ? trigger : null;
  elements["inspector-drawer"].classList.add("open");
  elements["inspector-backdrop"].classList.add("open");
  elements["inspector-drawer"].removeAttribute("inert");
  elements["inspector-drawer"].setAttribute("aria-hidden", "false");
  render(store.snapshot);
  elements["close-inspector"].focus();
}

function closeInspector() {
  elements["inspector-drawer"].classList.remove("open");
  elements["inspector-backdrop"].classList.remove("open");
  elements["inspector-drawer"].setAttribute("inert", "");
  elements["inspector-drawer"].setAttribute("aria-hidden", "true");
  selectedTrigger?.focus();
}

function selectEvent(event, trigger) {
  openInspector({
    kind: "event",
    id: event.event_id || `${event.run_id}:${event.sequence}`,
    event,
  }, trigger);
}

function selectNode(nodeId, trigger) {
  visualizer.select(nodeId);
  openInspector({ kind: "node", id: nodeId }, trigger);
}

function callRecordMeta(fields) {
  return `${fields.kind} · ${formatTime(fields.executedAt)}`;
}

function renderEvents(snapshot) {
  const list = elements["events-list"];
  const normalizedSearch = eventSearch.toLocaleLowerCase();
  const records = callRecords(snapshot);
  const visibleEvents = records.filter((event) => {
    const matchesStatus = eventStatusFilter === "all"
      || (event.status || "unknown") === eventStatusFilter;
    const haystack = traceRecordSearchText(event).toLocaleLowerCase();
    return matchesStatus && haystack.includes(normalizedSearch);
  });
  if (!visibleEvents.length) {
    const message = records.length
      ? "没有符合筛选条件的调用记录。"
      : "暂无调用记录。";
    list.replaceChildren(makeElement("div", "empty-state", message));
    return;
  }
  const fragment = document.createDocumentFragment();
  for (const event of visibleEvents) {
    const fields = traceRecordListFields(event);
    const row = makeElement("button", "call-record");
    row.type = "button";
    row.dataset.status = event.status || "unknown";
    if (
      selected.kind === "event"
      && selected.id === (event.event_id || `${event.run_id}:${event.sequence}`)
    ) {
      row.classList.add("selected");
    }
    const identity = makeElement("div", "call-record-identity");
    identity.append(
      makeElement("strong", "call-record-name", fields.name),
      makeElement("span", "call-record-meta", callRecordMeta(fields)),
    );
    const header = makeElement("div", "call-record-header");
    header.append(
      identity,
      makeElement(
        "span",
        "call-record-status",
        fields.status,
      ),
    );
    row.append(header);
    row.title = "查看完整调用记录";
    row.addEventListener("click", () => selectEvent(event, row));
    fragment.append(row);
  }
  list.replaceChildren(fragment);
}

function renderReport(snapshot) {
  if (snapshot.finalOutput === lastReportedOutput) return;
  lastReportedOutput = snapshot.finalOutput;
  if (snapshot.finalOutput === null || snapshot.finalOutput === undefined) {
    const empty = makeElement("div", "empty-state");
    empty.append(
      "最终报告会在收到 ",
      makeElement("code", "", "run_completed"),
      " 事件后显示。",
    );
    elements["final-report"].replaceChildren(empty);
    return;
  }
  if (typeof snapshot.finalOutput === "string" && !snapshot.finalOutput.trim()) {
    elements["final-report"].replaceChildren(makeElement(
      "div",
      "empty-state",
      "本次运行没有返回报告内容。",
    ));
    return;
  }
  renderMarkdown(snapshot.finalOutput, elements["final-report"]);
}

function fileKind(name) {
  const extension = String(name).split(".").pop();
  return extension && extension !== name ? extension.toUpperCase() : "文件";
}

function formatBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes)) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

function renderFiles(snapshot) {
  const list = elements["files-list"];
  if (!snapshot.files.length) {
    list.replaceChildren(makeElement("div", "empty-state", "暂无生成文件。"));
    return;
  }

  const fragment = document.createDocumentFragment();
  for (const file of snapshot.files) {
    const row = makeElement("div", "file-row");
    const name = makeElement("strong", "", file.name || "未命名文件");
    name.title = file.path || file.name || "";
    const link = makeElement("a", "", "下载");
    link.href = downloadUrl(snapshot.threadId, file.path);
    link.setAttribute("download", file.name || "");
    const modified = Number(file.mtime) * 1000;
    row.append(
      name,
      makeElement("span", "file-kind", fileKind(file.name || "")),
      makeElement("span", "", formatBytes(file.size)),
      makeElement(
        "span",
        "file-time",
        Number.isFinite(modified) ? formatTime(modified, true) : "—",
      ),
      link,
    );
    fragment.append(row);
  }
  list.replaceChildren(fragment);
}

function renderRaw(snapshot) {
  const traceEvents = snapshot.rawTraceEvents || snapshot.events;
  if (!traceEvents.length && !snapshot.rawMessages.length && !snapshot.clientErrors.length) {
    elements["raw-events"].textContent = "尚未收到 WebSocket 消息。";
    return;
  }
  elements["raw-events"].textContent = JSON.stringify({
    trace_events: traceEvents,
    websocket_messages: snapshot.rawMessages,
    client_errors: snapshot.clientErrors,
  }, null, 2);
}

function eventForNode(snapshot, nodeId) {
  if (nodeId === "input") {
    const traceHistory = snapshot.rawTraceEvents?.length
      ? snapshot.rawTraceEvents
      : snapshot.events;
    return traceHistory.find((event) => event.event === "run_started") || null;
  }
  if (nodeId === "output") {
    return snapshot.events.findLast(
      (event) => event.event === "run_completed" || event.event === "run_failed",
    ) || null;
  }
  if (nodeId === "synthesis") {
    return snapshot.events.findLast(
      (event) => event.node_type === "model" || event.event?.startsWith("report_"),
    ) || null;
  }
  return snapshot.roles[nodeId]?.lastEvent || null;
}

function selectedEvent(snapshot) {
  if (selected.kind === "event") {
    return snapshot.events.find(
      (event) => (event.event_id || `${event.run_id}:${event.sequence}`) === selected.id,
    ) || selected.event || null;
  }
  return eventForNode(snapshot, selected.id);
}

function selectedTitle(snapshot) {
  if (selected.kind === "event") {
    const event = selectedEvent(snapshot);
    return event ? traceRecordName(event) : "调用记录";
  }
  return {
    input: "用户请求",
    synthesis: "主智能体汇总",
    output: "最终结果",
    ...Object.fromEntries(
      Object.entries(ROLE_DEFINITIONS).map(([id, definition]) => [id, definition.label]),
    ),
  }[selected.id] || "详情";
}

function detailList(rows) {
  const list = makeElement("dl", "detail-list");
  for (const [label, value] of rows) {
    const row = makeElement("div", "detail-row");
    row.append(
      makeElement("dt", "", label),
      makeElement("dd", "", value === null || value === undefined ? "—" : String(value)),
    );
    list.append(row);
  }
  return list;
}

function isEmptyInspectorValue(value) {
  if (value === null || value === undefined) return true;
  if (typeof value === "string") return !value.trim();
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === "object") return Object.keys(value).length === 0;
  return false;
}

function jsonPanel(value, emptyMessage, error = false) {
  if (isEmptyInspectorValue(value)) {
    return makeElement("div", "inspector-empty", emptyMessage);
  }
  return makeElement("pre", `json-block${error ? " error-block" : ""}`, stringifyValue(value));
}

function renderInspector(snapshot) {
  const event = selectedEvent(snapshot);
  const title = selectedTitle(snapshot);
  const nodeStatus = selected.kind === "node"
    ? statusForNode(snapshot, selected.id)
    : event?.status || "unknown";
  elements["inspector-title"].textContent = title;
  elements["inspector-status"].textContent = selected.kind === "event"
    ? traceRecordStatusLabel(nodeStatus)
    : formatStatus(nodeStatus);
  elements["inspector-status"].dataset.status = nodeStatus;

  let content;
  if (inspectorTab === "overview") {
    if (event) {
      const overviewRows = [
        ["名称", traceRecordName(event)],
        ["类型", traceRecordKind(event)],
        ["状态", traceRecordStatusLabel(event.status)],
        ["开始时间", formatTime(event.started_at || event.timestamp, true)],
        [
          "结束时间",
          formatTime(
            event.ended_at
              || (["completed", "failed", "cancelled"].includes(event.status)
                ? event.timestamp
                : null),
            true,
          ),
        ],
        ["耗时", event.duration_ms == null ? "未记录" : formatDuration(event.duration_ms)],
        ["入参摘要", traceValueSummary(event.input, "无入参")],
        ["返回摘要", traceValueSummary(event.output, "无返回值")],
      ];
      const errorSummary = traceValueSummary(event.error, "");
      if (errorSummary) overviewRows.push(["错误摘要", errorSummary]);
      content = detailList(overviewRows);
    } else if (selected.kind === "node") {
      const purpose = ROLE_DEFINITIONS[selected.id]?.purpose
        || {
          input: "由 HTTP API 接收的用户任务。",
          synthesis: "当前执行器未单独上报事件的汇总阶段。",
          output: "由任务结束事件提供的最终输出。",
        }[selected.id];
      content = detailList([
        ["名称", title],
        ["状态", formatStatus(nodeStatus)],
        ["说明", purpose || "—"],
        ["追踪证据", "未观察到对应调用"],
      ]);
    } else {
      content = makeElement("div", "inspector-empty", "请选择一条调用记录或流程节点。");
    }
  } else if (inspectorTab === "input") {
    content = jsonPanel(event?.input, "本次调用没有入参。");
  } else if (inspectorTab === "output") {
    content = jsonPanel(event?.output, "本次调用没有返回值。");
  } else if (inspectorTab === "event") {
    content = jsonPanel(event, "暂无完整记录。");
  } else {
    content = jsonPanel(event?.error, "本次调用没有错误。", true);
  }
  elements["inspector-body"].replaceChildren(content);
}

function renderBottomTabs() {
  for (const button of document.querySelectorAll("[data-bottom-tab]")) {
    button.classList.toggle("active", button.dataset.bottomTab === bottomTab);
  }
  for (const panel of document.querySelectorAll("[data-bottom-panel]")) {
    panel.classList.toggle("active", panel.dataset.bottomPanel === bottomTab);
  }
}

function render(snapshot) {
  renderHeader(snapshot);
  renderMetrics(snapshot);
  renderAgents(snapshot);
  renderEvents(snapshot);
  renderReport(snapshot);
  renderFiles(snapshot);
  renderRaw(snapshot);
  renderInspector(snapshot);
  renderBottomTabs();
  visualizer.update(snapshot);
  visualizer.select(selected.kind === "node" ? selected.id : "");
  elements["graph-empty"].classList.toggle("hidden", Boolean(snapshot.runId));
  elements["tab-event-count"].textContent = String(callRecords(snapshot).length);
  elements["tab-file-count"].textContent = String(snapshot.files.length);
}

async function runSearch() {
  const query = elements["task-input"].value.trim();
  if (!query) {
    showNotice("请先输入研究问题。");
    elements["task-input"].focus();
    return;
  }
  if (["uploading", "starting", "restoring", "running"].includes(store.snapshot.taskStatus)) {
    return;
  }

  const threadId = store.snapshot.threadId || crypto.randomUUID();
  try {
    const response = await runClient.start({
      query,
      threadId,
      files: queuedFiles,
    });
    if (!response) return;
    repository.save(createSessionRecord({
      threadId: response.thread_id,
      runId: response.run_id,
      query,
      status: "running",
    }));
    syncViewUrl();
    queuedFiles = [];
    elements["file-input"].value = "";
    updateUploadMeta();
  } catch (error) {
    store.setTaskStatus("failed");
    store.addClientError(error.message, "task");
    showNotice(`无法启动任务：${error.message}。请检查服务配置后重试。`, true);
  }
}

function updateUploadMeta() {
  elements["upload-meta"].textContent = queuedFiles.length
    ? `${queuedFiles.length} 个文件 · ${queuedFiles.map((file) => file.name).join(", ")}`
    : "拖放文件或点击选择";
}

function setQueuedFiles(files) {
  queuedFiles = [...files];
  updateUploadMeta();
}

async function restoreSession() {
  try {
    const summary = await runClient.restore({
      threadId: store.snapshot.threadId,
      runId: store.snapshot.runId,
    });
    if (!summary) {
      store.setTaskStatus("idle");
    }
    syncViewUrl();
  } catch (error) {
    store.addClientError(error.message, "restore");
    store.patch({
      runId: null,
      lastSequence: -1,
      taskStatus: "idle",
      connection: "idle",
    });
    showNotice("上一次运行的内存轨迹已不可用（服务可能重启过），线程 ID 已保留。");
  }
}

elements["run-button"].addEventListener("click", runSearch);
elements["task-input"].addEventListener("input", () => renderHeader(store.snapshot));
elements["task-input"].addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    runSearch();
  }
});

elements["file-input"].addEventListener("change", (event) => {
  setQueuedFiles(event.target.files || []);
});
elements["upload-zone"].addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    elements["file-input"].click();
  }
});
for (const eventName of ["dragenter", "dragover"]) {
  elements["upload-zone"].addEventListener(eventName, (event) => {
    event.preventDefault();
    elements["upload-zone"].classList.add("dragging");
  });
}
for (const eventName of ["dragleave", "drop"]) {
  elements["upload-zone"].addEventListener(eventName, (event) => {
    event.preventDefault();
    elements["upload-zone"].classList.remove("dragging");
  });
}
elements["upload-zone"].addEventListener("drop", (event) => {
  if (event.dataTransfer?.files?.length) {
    setQueuedFiles(event.dataTransfer.files);
  }
});

elements["new-session"].addEventListener("click", () => {
  if (
    store.snapshot.taskStatus === "running"
    && !window.confirm("后台任务仍会继续运行。确定离开当前视图并新建会话吗？")
  ) {
    return;
  }
  runClient.close();
  queuedFiles = [];
  elements["file-input"].value = "";
  elements["task-input"].value = "";
  lastReportedOutput = Symbol("reset");
  selected = { kind: "node", id: "main" };
  updateUploadMeta();
  store.newSession();
  history.replaceState(null, "", "/trace");
});

elements["copy-thread"].addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(store.snapshot.threadId);
    showNotice("线程 ID 已复制");
  } catch {
    showNotice("无法复制线程 ID。");
  }
});

for (const card of document.querySelectorAll("[data-role]")) {
  card.addEventListener("click", () => selectNode(card.dataset.role, card));
}

for (const button of document.querySelectorAll("[data-inspector-tab]")) {
  button.addEventListener("click", () => {
    inspectorTab = button.dataset.inspectorTab;
    for (const tab of document.querySelectorAll("[data-inspector-tab]")) {
      tab.classList.toggle("active", tab === button);
    }
    renderInspector(store.snapshot);
  });
}

for (const button of document.querySelectorAll("[data-bottom-tab]")) {
  button.addEventListener("click", () => {
    bottomTab = button.dataset.bottomTab;
    renderBottomTabs();
    syncViewUrl();
  });
}

elements["records-collapse"].addEventListener("click", () => {
  const collapsed = elements["run-records"].classList.toggle("collapsed");
  elements["records-collapse"].textContent = collapsed
    ? "展开运行记录"
    : "收起运行记录";
  elements["records-collapse"].setAttribute("aria-expanded", String(!collapsed));
});

elements["event-search"].addEventListener("input", (event) => {
  eventSearch = event.target.value;
  renderEvents(store.snapshot);
  syncViewUrl();
});

elements["event-status-filter"].addEventListener("change", (event) => {
  eventStatusFilter = event.target.value;
  renderEvents(store.snapshot);
  syncViewUrl();
});

elements["close-inspector"].addEventListener("click", closeInspector);
elements["inspector-backdrop"].addEventListener("click", closeInspector);
elements["graph-zoom-in"].addEventListener("click", () => visualizer.zoomBy(1));
elements["graph-zoom-out"].addEventListener("click", () => visualizer.zoomBy(-1));
elements["graph-fit"].addEventListener("click", () => visualizer.fit());

window.addEventListener("keydown", (event) => {
  const drawerOpen = elements["inspector-drawer"].classList.contains("open");
  if (event.key === "Escape" && drawerOpen) {
    closeInspector();
    return;
  }
  if (event.key === "Tab" && drawerOpen) {
    const focusable = [...elements["inspector-drawer"].querySelectorAll(
      'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled)',
    )];
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
});

elements["dismiss-notice"].addEventListener("click", () => {
  clearTimeout(noticeTimer);
  elements.notice.classList.add("hidden");
});

window.addEventListener("beforeunload", () => runClient.close());
elements["event-search"].value = eventSearch;
elements["event-status-filter"].value = eventStatusFilter;
store.subscribe(render);
window.setInterval(updateElapsed, 1000);
restoreSession();

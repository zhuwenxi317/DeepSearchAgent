const SYSTEM_EVENT_TYPES = new Set([
  "session_created",
  "message_sent",
]);

const KIND_LABELS = {
  run: "主任务",
  agent: "子助手",
  tool: "工具调用",
  model: "模型调用",
  retriever: "知识检索",
  report: "报告生成",
};

function compactText(value, limit = 160) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text.length > limit ? `${text.slice(0, limit)}...` : text;
}

function isEmptyValue(value) {
  if (value === null || value === undefined) return true;
  if (typeof value === "string") return !value.trim();
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === "object") return Object.keys(value).length === 0;
  return false;
}

function itemLabel(item) {
  if (item === null || item === undefined) return "未命名结果";
  if (typeof item === "string") return compactText(item, 72);
  if (typeof item === "object") {
    return compactText(item.title || item.name || item.url || "未命名结果", 72);
  }
  return compactText(item, 72);
}

function scalarSummary(value) {
  if (value === null || value === undefined) return "空";
  if (typeof value === "string") return compactText(value, 72);
  if (typeof value === "object") {
    if (Array.isArray(value)) return `共 ${value.length} 项`;
    return "对象";
  }
  return compactText(value, 72);
}

export function isSystemTraceEvent(event) {
  return SYSTEM_EVENT_TYPES.has(event?.event);
}

export function traceRecordName(event) {
  if (event?.node_type === "run") return "本次任务";
  return event?.name || "未命名调用";
}

export function traceRecordKind(event) {
  return KIND_LABELS[event?.node_type] || "系统事件";
}

export function traceRecordStatusLabel(status) {
  return {
    pending: "等待中",
    waiting: "等待中",
    running: "执行中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
  }[status] || "未知";
}

export function traceCallRecords(events = []) {
  return events.filter((event) => !isSystemTraceEvent(event));
}

export function traceRecordListFields(event) {
  return {
    name: traceRecordName(event),
    kind: traceRecordKind(event),
    status: traceRecordStatusLabel(event?.status),
    executedAt: event?.started_at || event?.timestamp || null,
  };
}

export function traceValueSummary(value, emptyLabel) {
  if (isEmptyValue(value)) return emptyLabel;
  if (typeof value === "string") return compactText(value);
  if (Array.isArray(value)) return `共 ${value.length} 项`;
  if (typeof value !== "object") return compactText(value);

  if (Array.isArray(value.results)) {
    const labels = value.results.slice(0, 2).map(itemLabel).filter(Boolean);
    const suffix = labels.length ? `：${labels.join("；")}` : "";
    return `找到 ${value.results.length} 条结果${suffix}`;
  }
  if (typeof value.path === "string") return `路径：${compactText(value.path)}`;

  const entries = Object.entries(value).slice(0, 3);
  if (!entries.length) return "空对象";
  return entries.map(([key, item]) => `${key}: ${scalarSummary(item)}`).join(" · ");
}

export function traceRecordSearchText(event) {
  const fields = traceRecordListFields(event);
  return [fields.name, fields.kind, fields.status].filter(Boolean).join(" ");
}

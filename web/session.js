const STORAGE_KEY = "deep-search-pro.sessions.v1";
const MAX_SESSIONS = 50;

export function createSessionRecord({
  threadId,
  runId = null,
  query = "",
  status = "idle",
  updatedAt = new Date().toISOString(),
}) {
  const normalizedQuery = String(query).trim();
  return {
    threadId: String(threadId),
    runId: runId ? String(runId) : null,
    title: normalizedQuery.slice(0, 36) || "新对话",
    query: normalizedQuery,
    status: String(status || "idle"),
    updatedAt: String(updatedAt),
  };
}

export function upsertSession(sessions, record) {
  return [record, ...sessions.filter((item) => item.threadId !== record.threadId)]
    .sort((a, b) => String(b.updatedAt).localeCompare(String(a.updatedAt)))
    .slice(0, MAX_SESSIONS);
}

export function parseTraceSelection(search, fallback = {}) {
  const params = new URLSearchParams(search);
  const hasThreadId = params.has("thread_id");
  const hasRunId = params.has("run_id");
  if (!hasThreadId && !hasRunId) {
    return { threadId: null, runId: null };
  }
  return {
    threadId: params.get("thread_id") || fallback.threadId || null,
    runId: params.get("run_id") || fallback.runId || null,
  };
}

export function parseChatSelection(
  search,
  fallback = {},
  createThreadId = () => globalThis.crypto.randomUUID(),
) {
  const params = new URLSearchParams(search);
  const threadId = params.get("thread_id");
  const runId = params.get("run_id");
  if (threadId) {
    return { threadId, runId: runId || null };
  }
  return {
    threadId: fallback.threadId || createThreadId(),
    runId: runId || fallback.runId || null,
  };
}

export function traceUrl(threadId, runId) {
  const params = new URLSearchParams();
  if (threadId) params.set("thread_id", threadId);
  if (runId) params.set("run_id", runId);
  const query = params.toString();
  return query ? `/trace?${query}` : "/trace";
}

export function chatUrl(threadId, runId) {
  const params = new URLSearchParams();
  if (threadId) params.set("thread_id", threadId);
  if (runId) params.set("run_id", runId);
  const query = params.toString();
  return query ? `/?${query}` : "/";
}

export function restoredQuery(previousRunId, snapshot) {
  const query = String(snapshot.query || "").trim();
  if (!snapshot.runId || snapshot.runId === previousRunId || !query) return null;
  return query;
}

export class SessionRepository {
  constructor(storage = globalThis.localStorage) {
    this.storage = storage;
  }

  list() {
    try {
      const value = JSON.parse(this.storage?.getItem(STORAGE_KEY) || "[]");
      return Array.isArray(value) ? value.filter((item) => item?.threadId) : [];
    } catch {
      return [];
    }
  }

  save(record) {
    const sessions = upsertSession(this.list(), record);
    try {
      this.storage?.setItem(STORAGE_KEY, JSON.stringify(sessions));
    } catch {
      return sessions;
    }
    return sessions;
  }
}

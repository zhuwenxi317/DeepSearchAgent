// 后端接口封装：这一层只管「怎么说话」，不含任何界面逻辑。
// 与参考项目的差异都用注释标出，方便对照学习。
const JSON_HEADERS = {
  "Content-Type": "application/json",
};

async function parseResponse(response) {
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const detail = payload && typeof payload === "object"
      ? payload.detail || payload.error
      : payload;
    throw new Error(detail || `Request failed with HTTP ${response.status}`);
  }

  if (payload && typeof payload === "object" && payload.error) {
    throw new Error(payload.error);
  }
  return payload;
}

// 差异：我们的上传接口一次只收一个文件（字段名 file），
// thread_id 走 query，不是表单字段。所以这里循环上传。
export async function uploadFiles(threadId, files) {
  const uploaded = [];
  for (const file of files) {
    const formData = new FormData();
    formData.append("file", file);
    uploaded.push(await parseResponse(await fetch(
      `/api/upload?thread_id=${encodeURIComponent(threadId)}`,
      { method: "POST", body: formData },
    )));
  }
  return uploaded;
}

export async function startTask(query, threadId) {
  return parseResponse(await fetch("/api/task", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      query,
      thread_id: threadId,
    }),
  }));
}

// 差异：后端返回的是 run_id 字符串数组，这里统一成对象，
// 让上层不用关心后端用的是哪种形状。
export async function fetchThreadRuns(threadId) {
  const payload = await parseResponse(await fetch(
    `/api/threads/${encodeURIComponent(threadId)}/runs`,
  ));
  const runs = (payload.runs || []).map((item) => (
    typeof item === "string" ? { run_id: item } : item
  ));
  return { ...payload, runs };
}

// 差异：我们的接口没有 has_more / last_sequence，靠「本页是否取满 limit」
// 判断还有没有下一页。sequence 从 0 开始，所以默认 afterSequence = -1。
export async function fetchTrace(runId, afterSequence = -1) {
  const events = [];
  const limit = 1000;
  let cursor = afterSequence;

  while (true) {
    const query = new URLSearchParams({
      after_sequence: String(cursor),
      limit: String(limit),
    });
    const page = await parseResponse(await fetch(
      `/api/runs/${encodeURIComponent(runId)}/trace?${query}`,
    ));
    const batch = page.events || [];
    events.push(...batch);
    if (batch.length < limit) {
      break;
    }
    cursor = batch[batch.length - 1].sequence;
  }

  return {
    events,
    lastSequence: events.length ? events[events.length - 1].sequence : cursor,
  };
}

// 差异：后端按 thread_id 列文件（返回的 path 已相对会话目录）。
export async function fetchFiles(threadId) {
  return parseResponse(await fetch(
    `/api/files?thread_id=${encodeURIComponent(threadId)}`,
  ));
}

// 差异：下载需要同时带 thread_id（会话边界）和 path。
export function downloadUrl(threadId, path) {
  const query = new URLSearchParams({ thread_id: threadId, path });
  return `/api/download?${query}`;
}

export function connectTrace({
  threadId,
  runId,
  afterSequence,
  onOpen,
  onMessage,
  onError,
  onClose,
}) {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const query = new URLSearchParams({
    run_id: runId,
    after_sequence: String(afterSequence),
  });
  const socket = new WebSocket(
    `${protocol}//${window.location.host}/ws/${encodeURIComponent(threadId)}?${query}`,
  );

  socket.addEventListener("open", onOpen);
  socket.addEventListener("message", (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch {
      payload = {
        type: "unparseable_message",
        raw: String(event.data),
      };
    }
    onMessage(payload);
  });
  socket.addEventListener("error", onError);
  socket.addEventListener("close", onClose);
  return socket;
}

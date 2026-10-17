import { downloadUrl } from "./api.js";
import {
  createFrameScheduler,
  createRenderBatch,
  initialScrollIntent,
  isExplicitScrollIntent,
  isAtBottom,
  isNearBottom,
  queueRenderBatch,
  reduceScrollIntent,
  resetRenderBatch,
  shouldFollowNewContent,
  shouldRestoreRenderAnchor,
  shouldSubmitOnEnter,
  takeRenderBatch,
} from "./chat-interactions.js";
import { renderMarkdown } from "./markdown.js";
import { RunClient } from "./run-client.js";
import {
  createSessionRecord,
  parseChatSelection,
  SessionRepository,
  traceUrl,
} from "./session.js";
import { ConsoleStore, isTerminalStatus, ROLE_DEFINITIONS } from "./state.js";

const elements = Object.fromEntries(
  [...document.querySelectorAll("[id]")].map((element) => [element.id, element]),
);

const TASK_LABELS = {
  idle: "未开始",
  uploading: "正在上传",
  starting: "正在启动",
  restoring: "正在恢复",
  running: "正在运行",
  completed: "已完成",
  failed: "运行失败",
  cancelled: "已取消",
};

const ROLE_LABELS = Object.fromEntries(
  Object.entries(ROLE_DEFINITIONS).map(([id, value]) => [id, value.label]),
);

const repository = new SessionRepository();
const savedSession = repository.list()[0] || null;
const initialSelection = parseChatSelection(
  window.location.search,
  savedSession || {},
  () => crypto.randomUUID(),
);
const store = new ConsoleStore(initialSelection);
const runClient = new RunClient({ store, onNotice: showNotice });

let queuedFiles = [];
let pendingQuery = "";
let sessionFilter = "";
let noticeTimer = null;
let lastSessionSignature = "";
let lastEventCount = 0;
let conversationBatch = createRenderBatch();
let scrollIntent = initialScrollIntent();

const activeScrollInputs = new Set();
const conversationFrames = createFrameScheduler({
  requestFrame: (callback) => requestAnimationFrame(callback),
  cancelFrame: (frameId) => cancelAnimationFrame(frameId),
});
const wheelFrames = createFrameScheduler({
  requestFrame: (callback) => requestAnimationFrame(callback),
  cancelFrame: (frameId) => cancelAnimationFrame(frameId),
});

function makeElement(tag, className = "", text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function statusLabel(status) {
  return TASK_LABELS[status] || status || "未知";
}

function isBusy(status) {
  return ["uploading", "starting", "restoring", "running"].includes(status);
}

function renderLatestControl() {
  const hidden = scrollIntent.programmatic || scrollIntent.nearBottom;
  elements["scroll-to-latest"].classList.toggle("hidden", hidden);
}

function updateLatestControl() {
  scrollIntent = reduceScrollIntent(scrollIntent, {
    type: "scroll",
    nearBottom: isNearBottom(elements.messages),
    atBottom: isAtBottom(elements.messages),
  });
  renderLatestControl();
}

function discardConversationBatch() {
  conversationFrames.cancel();
  conversationBatch = resetRenderBatch(conversationBatch);
}

function resetScrollIntent() {
  discardConversationBatch();
  wheelFrames.cancel();
  activeScrollInputs.clear();
  scrollIntent = reduceScrollIntent(scrollIntent, { type: "reset" });
  renderLatestControl();
}

function beginUserScroll(source) {
  activeScrollInputs.add(source);
  discardConversationBatch();
  scrollIntent = reduceScrollIntent(scrollIntent, {
    type: "user-start",
    nearBottom: isNearBottom(elements.messages),
  });
  renderLatestControl();
}

function finishUserScroll(source) {
  if (!activeScrollInputs.delete(source) || activeScrollInputs.size) return;
  scrollIntent = reduceScrollIntent(scrollIntent, {
    type: "user-end",
    nearBottom: isNearBottom(elements.messages),
  });
  renderLatestControl();
}

function settleUserScroll() {
  wheelFrames.cancel();
  if (!activeScrollInputs.size && !scrollIntent.userScrolling) return;
  discardConversationBatch();
  activeScrollInputs.clear();
  scrollIntent = reduceScrollIntent(scrollIntent, {
    type: "user-end",
    nearBottom: isNearBottom(elements.messages),
  });
  renderLatestControl();
}

function handleMessageScroll() {
  updateLatestControl();
}

function scrollToLatest({ smooth = false } = {}) {
  discardConversationBatch();
  scrollIntent = reduceScrollIntent(scrollIntent, { type: "programmatic-start" });
  renderLatestControl();
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  elements.messages.scrollTo({
    top: elements.messages.scrollHeight,
    behavior: smooth && !reducedMotion ? "smooth" : "auto",
  });
  updateLatestControl();
}

function shortId(value) {
  const text = String(value || "");
  return text.length > 14 ? `${text.slice(0, 8)}…${text.slice(-4)}` : text;
}

function formatSessionTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

function showNotice(message, sticky = false) {
  globalThis.clearTimeout(noticeTimer);
  elements["notice-text"].textContent = String(message);
  elements.notice.classList.remove("hidden");
  if (!sticky) {
    noticeTimer = globalThis.setTimeout(() => {
      elements.notice.classList.add("hidden");
    }, 4200);
  }
}

function closeSidebar() {
  elements.sidebar.classList.remove("open");
  elements["sidebar-backdrop"].classList.remove("open");
}

function openSidebar() {
  elements.sidebar.classList.add("open");
  elements["sidebar-backdrop"].classList.add("open");
}

function renderHeader(snapshot) {
  const current = repository.list().find((item) => item.threadId === snapshot.threadId);
  const title = snapshot.query || pendingQuery || current?.title || "新对话";
  elements["thread-title"].textContent = title.slice(0, 48);
  elements["thread-id"].textContent = `Thread ${shortId(snapshot.threadId)}`;

  const displayStatus = snapshot.connection === "disconnected" && snapshot.taskStatus === "running"
    ? "disconnected"
    : snapshot.taskStatus;
  const connectionText = displayStatus === "disconnected"
    ? "连接中断"
    : statusLabel(displayStatus);
  elements["connection-label"].dataset.status = displayStatus;
  elements["connection-label"].querySelector("span").textContent = connectionText;
  elements["composer-status"].textContent = connectionText;

  elements["trace-link"].href = traceUrl(snapshot.threadId, snapshot.runId);
  elements["trace-link"].setAttribute("aria-disabled", String(!snapshot.runId));
  const busy = isBusy(snapshot.taskStatus);
  elements["send-button"].disabled = busy || !elements["task-input"].value.trim();
  elements["send-button"].dataset.busy = String(busy);
  elements["send-button"].setAttribute("aria-busy", String(busy));
  elements["attach-button"].disabled = busy;
}

function renderSessions(snapshot) {
  const normalizedFilter = sessionFilter.trim().toLocaleLowerCase();
  const sessions = repository.list().filter((session) => {
    const haystack = `${session.title || ""} ${session.query || ""} ${session.threadId || ""}`
      .toLocaleLowerCase();
    return haystack.includes(normalizedFilter);
  });
  const fragment = document.createDocumentFragment();

  if (!sessions.length) {
    fragment.append(makeElement(
      "div",
      "session-empty",
      normalizedFilter ? "没有匹配的会话" : "暂无历史会话",
    ));
  }

  for (const session of sessions) {
    const button = makeElement("button", "session-item");
    button.type = "button";
    button.classList.toggle("active", session.threadId === snapshot.threadId);
    button.setAttribute("aria-current", session.threadId === snapshot.threadId ? "page" : "false");
    button.append(makeElement("span", "session-title", session.title || "新对话"));

    const meta = makeElement("span", "session-meta");
    meta.append(makeElement("span", "session-status", statusLabel(session.status)));
    meta.append(makeElement("time", "", formatSessionTime(session.updatedAt)));
    button.append(meta);
    button.addEventListener("click", () => activateSession(session));
    fragment.append(button);
  }

  elements["session-list"].replaceChildren(fragment);
}

function makeAssistantHeading() {
  const heading = makeElement("div", "message-heading");
  heading.append(makeElement("span", "assistant-mark", "DS"));
  heading.append(makeElement("span", "", "DeepSearchPro"));
  return heading;
}

function renderProgress(snapshot, article) {
  const panel = makeElement("div", "progress-panel");
  const heading = makeElement("div", "progress-heading");
  const headingText = snapshot.taskStatus === "failed"
    ? "任务执行失败"
    : snapshot.taskStatus === "cancelled"
      ? "任务已取消"
      : "正在检索与分析";
  heading.append(makeElement("span", "", headingText));
  heading.append(makeElement("span", "", `${snapshot.events.length} events`));
  panel.append(heading);

  const list = makeElement("ol", "progress-steps");
  const roles = Object.values(snapshot.roles).filter((role) => role.observed);
  if (!roles.length) {
    const item = makeElement("li", "progress-step");
    item.dataset.status = snapshot.taskStatus;
    item.append(makeElement("span", "", statusLabel(snapshot.taskStatus)));
    item.append(makeElement("code", "", "等待运行事件"));
    list.append(item);
  }
  for (const role of roles) {
    const item = makeElement("li", "progress-step");
    item.dataset.status = role.status;
    item.append(makeElement("span", "", ROLE_LABELS[role.id] || role.id));
    item.append(makeElement(
      "code",
      "",
      role.lastEvent?.event || statusLabel(role.status),
    ));
    list.append(item);
  }
  panel.append(list);
  article.append(panel);
}

function renderAnswerMeta(snapshot, article) {
  const meta = makeElement("div", "answer-meta");
  const observedRoles = Object.values(snapshot.roles).filter((role) => role.observed).length;
  for (const value of [
    `${snapshot.events.length} 条运行事件`,
    `${observedRoles} 个执行角色`,
  ]) {
    const item = makeElement("span");
    item.append(makeElement("i"));
    item.append(document.createTextNode(value));
    meta.append(item);
  }
  article.append(meta);
}

function renderGeneratedFiles(snapshot, article) {
  if (!snapshot.files.length) return;
  const section = makeElement("section", "generated-files");
  section.append(makeElement("h3", "", "生成文件"));
  for (const file of snapshot.files) {
    const row = makeElement("div", "generated-file");
    row.append(makeElement("span", "", file.name || file.path || "未命名文件"));
    const link = makeElement("a", "", "下载");
    link.href = downloadUrl(snapshot.threadId, file.path);
    link.download = file.name || "";
    row.append(link);
    section.append(row);
  }
  article.append(section);
}

function renderConversation(snapshot) {
  const query = pendingQuery || snapshot.query;
  const hasConversation = Boolean(query || snapshot.runId || snapshot.events.length);
  elements["empty-state"].classList.toggle("hidden", hasConversation);
  const fragment = document.createDocumentFragment();

  if (query) {
    const userMessage = makeElement("article", "message user-message");
    userMessage.append(makeElement("div", "user-bubble", query));
    fragment.append(userMessage);
  }

  if (hasConversation) {
    const assistant = makeElement("article", "message assistant-message");
    assistant.append(makeAssistantHeading());
    if (snapshot.finalOutput && !pendingQuery) {
      const body = makeElement("div", "markdown-body");
      renderMarkdown(snapshot.finalOutput, body);
      assistant.append(body);
      renderAnswerMeta(snapshot, assistant);
    } else {
      renderProgress(snapshot, assistant);
    }
    renderGeneratedFiles(snapshot, assistant);
    fragment.append(assistant);
  }

  const contentChanged = snapshot.events.length !== lastEventCount
    || pendingQuery
    || isTerminalStatus(snapshot.taskStatus);
  conversationBatch = queueRenderBatch(conversationBatch, {
    scrollTop: elements.messages.scrollTop,
    contentChanged,
    programmatic: scrollIntent.programmatic,
  });
  elements.conversation.replaceChildren(fragment);
  conversationFrames.schedule(() => {
    const batch = takeRenderBatch(conversationBatch);
    conversationBatch = batch.remaining;
    if (shouldFollowNewContent(scrollIntent, batch.contentChanged)) {
      scrollToLatest();
    } else if (shouldRestoreRenderAnchor(
      scrollIntent,
      batch.anchor,
      batch.contentChanged,
      batch.programmatic,
    )) {
      elements.messages.scrollTop = batch.anchor;
    }
    updateLatestControl();
  });
  lastEventCount = snapshot.events.length;
}

function persistSession(snapshot) {
  if (!snapshot.runId || !snapshot.query) return;
  const signature = [
    snapshot.threadId,
    snapshot.runId,
    snapshot.query,
    snapshot.taskStatus,
  ].join(":");
  if (signature === lastSessionSignature) return;
  repository.save(createSessionRecord({
    threadId: snapshot.threadId,
    runId: snapshot.runId,
    query: snapshot.query,
    status: snapshot.taskStatus,
  }));
  lastSessionSignature = signature;
}

function render(snapshot) {
  persistSession(snapshot);
  renderHeader(snapshot);
  renderSessions(snapshot);
  renderConversation(snapshot);
}

function renderQueuedFiles() {
  const fragment = document.createDocumentFragment();
  queuedFiles.forEach((file, index) => {
    const chip = makeElement("span", "queued-file");
    chip.append(makeElement("span", "", file.name));
    const remove = makeElement("button", "", "×");
    remove.type = "button";
    remove.title = `移除 ${file.name}`;
    remove.setAttribute("aria-label", `移除 ${file.name}`);
    remove.addEventListener("click", () => {
      queuedFiles.splice(index, 1);
      renderQueuedFiles();
    });
    chip.append(remove);
    fragment.append(chip);
  });
  elements["queued-files"].replaceChildren(fragment);
}

function queueSelectedFiles(files) {
  const known = new Set(
    queuedFiles.map((file) => `${file.name}:${file.size}:${file.lastModified}`),
  );
  for (const file of files) {
    const key = `${file.name}:${file.size}:${file.lastModified}`;
    if (!known.has(key)) {
      queuedFiles.push(file);
      known.add(key);
    }
  }
  renderQueuedFiles();
}

async function submitQuestion(event) {
  event.preventDefault();
  const query = elements["task-input"].value.trim();
  if (!query || isBusy(store.snapshot.taskStatus)) return;

  pendingQuery = query;
  resetScrollIntent();
  render(store.snapshot);
  try {
    const response = await runClient.start({
      query,
      threadId: store.snapshot.threadId,
      files: queuedFiles,
    });
    if (!response) return;
    repository.save(createSessionRecord({
      threadId: response.thread_id,
      runId: response.run_id,
      query,
      status: "running",
    }));
    pendingQuery = "";
    queuedFiles = [];
    elements["task-input"].value = "";
    elements["task-input"].style.height = "";
    renderQueuedFiles();
    render(store.snapshot);
  } catch (error) {
    store.patch({ query });
    store.setTaskStatus("failed");
    pendingQuery = "";
    showNotice(`无法启动任务：${error.message}。请检查服务配置后重试。`, true);
  }
}

function newSession() {
  if (
    isBusy(store.snapshot.taskStatus)
    && !window.confirm("当前任务仍在运行。确定离开并新建对话吗？")
  ) {
    return;
  }
  runClient.close();
  pendingQuery = "";
  queuedFiles = [];
  lastSessionSignature = "";
  resetScrollIntent();
  store.newSession();
  history.replaceState(null, "", "/");
  elements["task-input"].value = "";
  renderQueuedFiles();
  closeSidebar();
  elements["task-input"].focus();
}

async function activateSession(session) {
  if (session.threadId === store.snapshot.threadId) {
    closeSidebar();
    return;
  }
  runClient.close();
  pendingQuery = "";
  queuedFiles = [];
  lastSessionSignature = "";
  resetScrollIntent();
  store.newSession();
  store.patch({
    threadId: session.threadId,
    runId: session.runId,
    query: session.query || "",
    taskStatus: session.runId ? "restoring" : "idle",
  });
  const query = new URLSearchParams({ thread_id: session.threadId });
  if (session.runId) query.set("run_id", session.runId);
  history.replaceState(null, "", `/?${query}`);
  closeSidebar();
  try {
    await runClient.restore(session);
  } catch (error) {
    store.patch({ runId: null, taskStatus: "idle", connection: "idle" });
    showNotice(`无法恢复会话：${error.message}`, true);
  }
}

async function restoreInitialSession() {
  if (!initialSelection.runId) return;
  try {
    await runClient.restore(initialSelection);
  } catch (error) {
    store.patch({ runId: null, taskStatus: "idle", connection: "idle" });
    showNotice(`无法恢复会话：${error.message}`, true);
  }
}

store.subscribe(render);
restoreInitialSession();

elements.composer.addEventListener("submit", submitQuestion);
elements["new-session"].addEventListener("click", newSession);
elements["attach-button"].addEventListener("click", () => elements["file-input"].click());
elements["file-input"].addEventListener("change", (event) => {
  queueSelectedFiles(event.target.files || []);
  event.target.value = "";
});
elements["session-search"].addEventListener("input", (event) => {
  sessionFilter = event.target.value;
  renderSessions(store.snapshot);
});
elements["task-input"].addEventListener("input", (event) => {
  event.target.style.height = "auto";
  event.target.style.height = `${Math.min(event.target.scrollHeight, 160)}px`;
  renderHeader(store.snapshot);
});
elements["task-input"].addEventListener("keydown", (event) => {
  if (!shouldSubmitOnEnter(event)) return;
  event.preventDefault();
  elements.composer.requestSubmit();
});
elements.messages.addEventListener("scroll", handleMessageScroll, { passive: true });
elements.messages.addEventListener("wheel", (event) => {
  if (!isExplicitScrollIntent(event)) return;
  beginUserScroll("wheel");
  wheelFrames.schedule(() => finishUserScroll("wheel"));
}, { passive: true });
elements.messages.addEventListener("touchstart", (event) => {
  if (isExplicitScrollIntent(event)) beginUserScroll("touch");
}, { passive: true });
elements.messages.addEventListener("pointerdown", (event) => {
  if (event.pointerType === "touch" || !isExplicitScrollIntent(event)) return;
  beginUserScroll(`pointer:${event.pointerId}`);
}, { passive: true });
elements["scroll-to-latest"].addEventListener("click", () => {
  scrollToLatest({ smooth: true });
});
elements["trace-link"].addEventListener("click", (event) => {
  if (elements["trace-link"].getAttribute("aria-disabled") === "true") {
    event.preventDefault();
  }
});
elements["copy-thread"].addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(store.snapshot.threadId);
    showNotice("线程 ID 已复制");
  } catch {
    showNotice("无法复制线程 ID", true);
  }
});
elements["dismiss-notice"].addEventListener("click", () => {
  globalThis.clearTimeout(noticeTimer);
  elements.notice.classList.add("hidden");
});
elements["open-sidebar"].addEventListener("click", openSidebar);
elements["close-sidebar"].addEventListener("click", closeSidebar);
elements["sidebar-backdrop"].addEventListener("click", closeSidebar);

window.addEventListener("keydown", (event) => {
  if (isExplicitScrollIntent(event)) beginUserScroll(`keyboard:${event.key}`);
  if (event.key === "Escape" && elements.sidebar.classList.contains("open")) {
    closeSidebar();
    elements["open-sidebar"].focus();
  }
});
window.addEventListener("keyup", (event) => {
  finishUserScroll(`keyboard:${event.key}`);
});
window.addEventListener("pointerup", (event) => {
  finishUserScroll(`pointer:${event.pointerId}`);
}, { passive: true });
window.addEventListener("pointercancel", (event) => {
  finishUserScroll(`pointer:${event.pointerId}`);
}, { passive: true });
window.addEventListener("touchend", () => finishUserScroll("touch"), { passive: true });
window.addEventListener("touchcancel", () => finishUserScroll("touch"), { passive: true });
window.addEventListener("blur", settleUserScroll);

for (const eventName of ["dragenter", "dragover"]) {
  elements.composer.addEventListener(eventName, (event) => {
    event.preventDefault();
    if (!isBusy(store.snapshot.taskStatus)) elements.composer.classList.add("dragging");
  });
}
for (const eventName of ["dragleave", "drop"]) {
  elements.composer.addEventListener(eventName, (event) => {
    event.preventDefault();
    elements.composer.classList.remove("dragging");
  });
}
elements.composer.addEventListener("drop", (event) => {
  if (!isBusy(store.snapshot.taskStatus)) queueSelectedFiles(event.dataTransfer?.files || []);
});

window.addEventListener("beforeunload", (event) => {
  runClient.close();
  if (queuedFiles.length || pendingQuery) {
    event.preventDefault();
  }
});

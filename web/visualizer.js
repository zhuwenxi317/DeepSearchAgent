export const EDGE_DEFINITIONS = Object.freeze([
  ["input", "main", false],
  ["main", "network", true],
  ["main", "database", true],
  ["main", "knowledge", true],
  ["network", "synthesis", true],
  ["database", "synthesis", true],
  ["knowledge", "synthesis", true],
  ["main", "synthesis", false],
  ["synthesis", "files", true],
  ["synthesis", "output", false],
  ["files", "output", false],
]);

const ZOOM_LEVELS = [0.75, 1, 1.25];

const STATUS_LABELS = {
  idle: "空闲",
  active: "运行中",
  running: "运行中",
  waiting: "等待中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  unknown: "未知",
};

export function nextZoom(current, direction) {
  const index = ZOOM_LEVELS.indexOf(current);
  const safeIndex = index === -1 ? 1 : index;
  return ZOOM_LEVELS[
    Math.max(0, Math.min(ZOOM_LEVELS.length - 1, safeIndex + direction))
  ];
}

function svgElement(name) {
  return document.createElementNS("http://www.w3.org/2000/svg", name);
}

function centerPoint(element, side) {
  return {
    x: side === "left"
      ? element.offsetLeft
      : element.offsetLeft + element.offsetWidth,
    y: element.offsetTop,
  };
}

export function edgePath(start, end) {
  const horizontalDistance = Math.abs(end.x - start.x);
  const handle = Math.max(56, Math.min(168, horizontalDistance * 0.48));
  const direction = end.x >= start.x ? 1 : -1;
  return `M ${start.x} ${start.y} C ${start.x + (handle * direction)} ${start.y}, ${end.x - (handle * direction)} ${end.y}, ${end.x} ${end.y}`;
}

function nodeStatus(snapshot, nodeId) {
  if (nodeId === "input") {
    if (!snapshot.runId) return "idle";
    if (snapshot.taskStatus === "failed") return "failed";
    if (snapshot.taskStatus === "completed") return "completed";
    return "active";
  }
  if (nodeId === "output") {
    if (snapshot.taskStatus === "failed") return "failed";
    if (snapshot.taskStatus === "completed" && snapshot.finalOutput != null) return "completed";
    if (snapshot.taskStatus === "completed") return "unknown";
    return snapshot.runId ? "waiting" : "idle";
  }
  if (nodeId === "synthesis") {
    const modelEvents = snapshot.events.filter((event) => event.node_type === "model");
    const reportEvents = snapshot.events.filter((event) => event.event?.startsWith("report_"));
    const event = [...modelEvents, ...reportEvents].sort(
      (a, b) => (a.sequence || 0) - (b.sequence || 0),
    ).at(-1);
    if (!event) return "unknown";
    if (event.event?.endsWith("_failed")) return "failed";
    if (event.event?.endsWith("_completed")) return "completed";
    return "active";
  }
  return snapshot.roles[nodeId]?.status || "idle";
}

function nodeDetail(snapshot, nodeId, status) {
  if (nodeId === "input") {
    return snapshot.query || "等待提交";
  }
  if (nodeId === "output") {
    if (status === "completed") return "已收到最终结果";
    if (status === "failed") return "运行失败";
    if (status === "unknown") return "已完成但没有输出";
    return "等待完成";
  }
  if (nodeId === "synthesis") {
    return status === "unknown" ? "无独立事件" : "已观测到模型/报告事件";
  }
  const role = snapshot.roles[nodeId];
  if (!role?.lastEvent) {
    return nodeId === "files" && snapshot.files.length
      ? `${snapshot.files.length} 个文件`
      : "未调用";
  }
  if (role.status === "waiting") {
    return "未收到完成事件";
  }
  return role.lastEvent.message || role.lastEvent.event || "已观察到事件";
}

export class ExecutionVisualizer {
  constructor(container, onSelect) {
    this.container = container;
    this.stage = container.closest(".graph-stage");
    this.viewport = container.closest(".graph-viewport");
    this.svg = container.querySelector("#graph-edges");
    this.nodes = new Map(
      [...container.querySelectorAll("[data-node]")].map((node) => [
        node.dataset.node,
        node,
      ]),
    );
    this.statuses = {};
    this.baseWidth = 1120;
    this.baseHeight = 430;
    this.scale = 1;
    this.fitMode = true;

    for (const [id, node] of this.nodes) {
      node.addEventListener("click", () => onSelect(id));
    }
    this.resizeObserver = new ResizeObserver(() => {
      if (this.fitMode) {
        this.fit();
      } else {
        this.drawEdges();
      }
    });
    this.resizeObserver.observe(this.viewport || container);
    this.fit();
  }

  setZoom(scale, { fitMode = false } = {}) {
    this.scale = scale;
    this.fitMode = fitMode;
    this.container.style.transform = `scale(${scale})`;
    if (this.stage) {
      this.stage.style.width = `${this.baseWidth * scale}px`;
      this.stage.style.height = `${this.baseHeight * scale}px`;
    }
    this.drawEdges();
    return this.scale;
  }

  zoomBy(direction) {
    return this.setZoom(nextZoom(this.scale, direction));
  }

  fit() {
    const available = this.viewport?.clientWidth || this.baseWidth;
    const ratio = available / this.baseWidth;
    const scale = [...ZOOM_LEVELS].reverse().find((level) => level <= ratio)
      || ZOOM_LEVELS[0];
    return this.setZoom(scale, { fitMode: true });
  }

  select(nodeId) {
    for (const [id, node] of this.nodes) {
      node.classList.toggle("selected", id === nodeId);
    }
  }

  update(snapshot) {
    for (const [id, node] of this.nodes) {
      const status = nodeStatus(snapshot, id);
      this.statuses[id] = status;
      node.dataset.status = status;
      node.querySelector(".badge").textContent = STATUS_LABELS[status] || status;
      node.querySelector(".node-detail").textContent = nodeDetail(snapshot, id, status);
    }
    this.drawEdges();
  }

  drawEdges() {
    if (!this.container.offsetWidth || !this.container.offsetHeight) return;
    const fragment = document.createDocumentFragment();

    for (const [sourceId, targetId, conditional] of EDGE_DEFINITIONS) {
      const source = this.nodes.get(sourceId);
      const target = this.nodes.get(targetId);
      if (!source || !target) continue;
      const path = svgElement("path");
      path.setAttribute(
        "d",
        edgePath(
          centerPoint(source, "right"),
          centerPoint(target, "left"),
        ),
      );
      const sourceStatus = this.statuses[sourceId];
      const targetStatus = this.statuses[targetId];
      if (conditional) path.classList.add("conditional");
      if (!["idle", "unknown"].includes(targetStatus)) path.classList.add("observed");
      if (sourceStatus === "active" || targetStatus === "active") path.classList.add("active");
      fragment.append(path);
    }
    this.svg.replaceChildren(fragment);
  }
}

export function statusForNode(snapshot, nodeId) {
  return nodeStatus(snapshot, nodeId);
}

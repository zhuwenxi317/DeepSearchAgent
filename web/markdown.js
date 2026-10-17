export function stringifyValue(value) {
  if (value === undefined) return "Unavailable";
  if (value === null) return "null";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function isSafeLink(
  href,
  base = globalThis.location?.href || "http://localhost/",
) {
  try {
    const url = new URL(href, base);
    return ["http:", "https:", "mailto:"].includes(url.protocol);
  } catch {
    return false;
  }
}

function makeElement(tag, className = "", text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function appendInlineMarkdown(parent, text) {
  const pattern = /(`[^`\n]+`|\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\n]+\*|_([^_\n]+)_|\[[^\]\n]+\]\([^) \n]+\))/g;
  let cursor = 0;

  for (const match of text.matchAll(pattern)) {
    const index = match.index || 0;
    if (index > cursor) {
      parent.append(document.createTextNode(text.slice(cursor, index)));
    }
    const token = match[0];
    if (token.startsWith("`")) {
      parent.append(makeElement("code", "", token.slice(1, -1)));
    } else if (token.startsWith("**") || token.startsWith("__")) {
      parent.append(makeElement("strong", "", token.slice(2, -2)));
    } else if (token.startsWith("*") || token.startsWith("_")) {
      parent.append(makeElement("em", "", token.slice(1, -1)));
    } else if (token.startsWith("[")) {
      const linkMatch = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (linkMatch && isSafeLink(linkMatch[2])) {
        const anchor = makeElement("a", "", linkMatch[1]);
        anchor.href = linkMatch[2];
        anchor.target = "_blank";
        anchor.rel = "noopener noreferrer";
        parent.append(anchor);
      } else {
        parent.append(document.createTextNode(token));
      }
    }
    cursor = index + token.length;
  }

  if (cursor < text.length) {
    parent.append(document.createTextNode(text.slice(cursor)));
  }
}

function isBlockStart(line, nextLine = "") {
  return /^(#{1,6})\s+/.test(line)
    || /^```/.test(line)
    || /^\s*>\s?/.test(line)
    || /^\s*[-*+]\s+/.test(line)
    || /^\s*\d+\.\s+/.test(line)
    || /^\s*(---+|\*\*\*+)\s*$/.test(line)
    || isTableStart(line, nextLine);
}

function tableCells(line) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function isTableStart(line, nextLine) {
  if (!line.includes("|") || !nextLine.includes("|")) return false;
  return tableCells(nextLine).every((cell) => /^:?-{3,}:?$/.test(cell));
}

function appendTable(lines, startIndex, fragment) {
  const headers = tableCells(lines[startIndex]);
  const table = makeElement("table");
  const head = makeElement("thead");
  const headerRow = makeElement("tr");
  for (const value of headers) {
    const cell = makeElement("th");
    appendInlineMarkdown(cell, value);
    headerRow.append(cell);
  }
  head.append(headerRow);
  table.append(head);

  const body = makeElement("tbody");
  let index = startIndex + 2;
  while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
    const row = makeElement("tr");
    for (const value of tableCells(lines[index])) {
      const cell = makeElement("td");
      appendInlineMarkdown(cell, value);
      row.append(cell);
    }
    body.append(row);
    index += 1;
  }
  table.append(body);
  const wrapper = makeElement("div", "table-scroll");
  wrapper.append(table);
  fragment.append(wrapper);
  return index;
}

function renderBlocks(lines, fragment) {
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const fence = line.match(/^```(.*)$/);
    if (fence) {
      index += 1;
      const codeLines = [];
      while (index < lines.length && !/^```/.test(lines[index])) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      const pre = makeElement("pre");
      const code = makeElement("code", "", codeLines.join("\n"));
      if (fence[1].trim()) code.dataset.language = fence[1].trim();
      pre.append(code);
      fragment.append(pre);
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      const element = makeElement(`h${heading[1].length}`);
      appendInlineMarkdown(element, heading[2]);
      fragment.append(element);
      index += 1;
      continue;
    }

    if (/^\s*(---+|\*\*\*+)\s*$/.test(line)) {
      fragment.append(makeElement("hr"));
      index += 1;
      continue;
    }

    if (isTableStart(line, lines[index + 1] || "")) {
      index = appendTable(lines, index, fragment);
      continue;
    }

    if (/^\s*>\s?/.test(line)) {
      const values = [];
      while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
        values.push(lines[index].replace(/^\s*>\s?/, ""));
        index += 1;
      }
      const quote = makeElement("blockquote");
      appendInlineMarkdown(quote, values.join("\n"));
      fragment.append(quote);
      continue;
    }

    const unordered = line.match(/^\s*[-*+]\s+(.+)$/);
    const ordered = line.match(/^\s*\d+\.\s+(.+)$/);
    if (unordered || ordered) {
      const list = makeElement(unordered ? "ul" : "ol");
      const matcher = unordered ? /^\s*[-*+]\s+(.+)$/ : /^\s*\d+\.\s+(.+)$/;
      while (index < lines.length) {
        const itemMatch = lines[index].match(matcher);
        if (!itemMatch) break;
        const item = makeElement("li");
        appendInlineMarkdown(item, itemMatch[1]);
        list.append(item);
        index += 1;
      }
      fragment.append(list);
      continue;
    }

    const paragraphLines = [line];
    index += 1;
    while (
      index < lines.length
      && lines[index].trim()
      && !isBlockStart(lines[index], lines[index + 1] || "")
    ) {
      paragraphLines.push(lines[index]);
      index += 1;
    }
    const paragraph = makeElement("p");
    appendInlineMarkdown(paragraph, paragraphLines.join(" "));
    fragment.append(paragraph);
  }
}

export function renderMarkdown(value, container) {
  const source = stringifyValue(value).replaceAll("\r\n", "\n");
  const fragment = document.createDocumentFragment();
  renderBlocks(source.split("\n"), fragment);
  container.replaceChildren(fragment);
}

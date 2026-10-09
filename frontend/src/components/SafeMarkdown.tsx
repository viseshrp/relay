import { createElement, type ReactNode } from "react";

export function safeMarkdownHref(value: string): string | undefined {
  if (/[\u0000-\u0020\u007f-\u009f]/.test(value)) return undefined;
  if (/^#[\w-]+$/.test(value)) return value;
  try {
    const url = new URL(value);
    return ["https:", "http:", "mailto:"].includes(url.protocol) ? value : undefined;
  } catch { return undefined; }
}

function inline(text: string, depth = 0): ReactNode[] {
  if (depth > 4) return [text];
  const pattern = /\\[\\`*_{}[\]()#+.!>-]|`[^`\n]*`|\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\n]+\*|_[^_\n]+_|\[[^[\]\n]*\]\([^()\n]*\)/g;
  const nodes: ReactNode[] = [];
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    nodes.push(text.slice(cursor, match.index));
    const token = match[0];
    const key = match.index;
    if (token.startsWith("\\")) nodes.push(token.slice(1));
    else if (token.startsWith("`")) nodes.push(<code key={key}>{token.slice(1, -1)}</code>);
    else if (token.startsWith("[")) {
      if (text[match.index - 1] === "!") { nodes.push(token); cursor = match.index + token.length; continue; }
      const end = token.indexOf("](");
      const label = token.slice(1, end);
      const href = safeMarkdownHref(token.slice(end + 2, -1));
      nodes.push(href ? <a key={key} href={href} target="_blank" rel="noopener noreferrer">{inline(label, depth + 1)}</a> : label);
    } else {
      const strong = token.startsWith("**") || token.startsWith("__");
      const size = strong ? 2 : 1;
      nodes.push(createElement(strong ? "strong" : "em", { key }, inline(token.slice(size, -size), depth + 1)));
    }
    cursor = match.index + token.length;
  }
  nodes.push(text.slice(cursor));
  return nodes;
}

function cells(line: string): string[] {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

export function SafeMarkdown({ text }: { text: string }) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  for (let index = 0; index < lines.length;) {
    const line = lines[index];
    if (!line.trim()) { index += 1; continue; }
    const key = index;
    const fence = line.match(/^ {0,3}(`{3,}|~{3,})([\w#+.-]*)\s*$/);
    if (fence) {
      const content: string[] = [];
      const end = new RegExp(`^ {0,3}${fence[1][0]}{${fence[1].length},}\\s*$`);
      index += 1;
      while (index < lines.length && !end.test(lines[index])) content.push(lines[index++]);
      if (index < lines.length) index += 1;
      blocks.push(<pre key={key}><code>{content.join("\n")}</code></pre>);
      continue;
    }
    const heading = line.match(/^ {0,3}(#{1,6})\s+(.+?)\s*#*$/);
    if (heading) { blocks.push(createElement(`h${heading[1].length}`, { key }, inline(heading[2]))); index += 1; continue; }
    if (/^ {0,3}(?:-\s*){3,}$|^ {0,3}(?:\*\s*){3,}$|^ {0,3}(?:_\s*){3,}$/.test(line)) {
      blocks.push(<hr key={key} />); index += 1; continue;
    }
    if (/^ {0,3}>/.test(line)) {
      const quote: string[] = [];
      while (index < lines.length && /^ {0,3}>/.test(lines[index])) quote.push(lines[index++].replace(/^ {0,3}> ?/, ""));
      blocks.push(<blockquote key={key}>{inline(quote.join("\n"))}</blockquote>); continue;
    }
    const item = line.match(/^\s*([-+*]|\d+[.)])\s+(.*)$/);
    if (item) {
      const ordered = /^\d/.test(item[1]);
      const items: ReactNode[] = [];
      for (; index < lines.length; index += 1) {
        const next = lines[index].match(/^\s*([-+*]|\d+[.)])\s+(.*)$/);
        if (!next || /^\d/.test(next[1]) !== ordered) break;
        items.push(<li key={index}>{inline(next[2])}</li>);
      }
      blocks.push(createElement(ordered ? "ol" : "ul", { key }, items)); continue;
    }
    if (line.includes("|") && cells(lines[index + 1] ?? "").every((cell) => /^:?-{3,}:?$/.test(cell))) {
      const headers = cells(line);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) rows.push(cells(lines[index++]));
      blocks.push(<table key={key}><thead><tr>{headers.map((cell, column) => <th key={column}>{inline(cell)}</th>)}</tr></thead>
        <tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, column) => <td key={column}>{inline(cell)}</td>)}</tr>)}</tbody></table>);
      continue;
    }
    const paragraph = [line];
    index += 1;
    while (index < lines.length && lines[index].trim() && !/^ {0,3}(?:[#>`~]|[-+*]\s|\d+[.)]\s)/.test(lines[index])) paragraph.push(lines[index++]);
    blocks.push(<p key={key}>{inline(paragraph.join("\n"))}</p>);
  }
  // React escapes all text. Markdown can only create this fixed set of
  // elements; provider HTML and images never become active browser content.
  return <div className="markdown-text">{blocks}</div>;
}

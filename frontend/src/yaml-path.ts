// Where the cursor sits in a YAML document, read from indentation alone so a
// half-typed line still has a place. Completion and hover use this; the server
// remains the judge of what the document means.

export type YamlSegment = string | number;

export interface YamlCursor {
  /** Mapping path of the line's parent; list items are numeric indexes. */
  path: YamlSegment[];
  /** "value" after `key:` on the cursor's line, otherwise "key". */
  position: "key" | "value";
  /** The key whose value the cursor is in, or null. */
  key: string | null;
  /** The word being typed before the cursor. */
  prefix: string;
  /** Keys already present in the cursor's mapping, other than its own line. */
  siblings: string[];
  /** Set inside an unclosed `${{`; text runs from `${{` to the cursor. */
  expression: { text: string } | null;
  /**
   * Keys and inline values of each enclosing mapping, including the cursor's
   * own complete key: `scopes[i]` describes the node at `path.slice(0, i)`.
   */
  scopes: Record<string, string>[];
}

interface Line {
  /** Column of the first non-space character. */
  indent: number;
  /** Column of a `- ` item marker, or null. */
  dash: number | null;
  /** Column where the content after any marker starts. */
  keyCol: number;
  key: string | null;
  value: string;
  /** Blank or comment-only. */
  blank: boolean;
  /** Index of the line whose `|` or `>` block scalar contains this line. */
  block: number | null;
}

type Container =
  { kind: "map"; indent: number; line: number } | { kind: "seq" };

const MARKER = /^( *)(?:-(?: +|$))?/;
const KEY = /^([^\s:#{[\]][^:#]*?)\s*:(?=\s|$)\s*(.*)$/;
const BLOCK = /^[|>][-+0-9]*$/;
const PREFIX = /[\w./@-]*$/;

function unquote(text: string): string {
  return /^(["']).*\1$/.test(text) ? text.slice(1, -1) : text;
}

/** An inline value without a trailing comment or surrounding quotes. */
export function yamlScalar(text: string): string {
  return unquote(text.replace(/(^|\s+)#.*$/, "").trim());
}

/** The key a line starts with and where it sits, or null for a line without one. */
export function yamlLineKey(
  text: string,
): { key: string; from: number; to: number; value: string } | null {
  const from = MARKER.exec(text)![0].length;
  const match = KEY.exec(text.slice(from));
  if (!match) return null;
  return {
    key: unquote(match[1].trim()),
    from,
    to: from + match[1].trimEnd().length,
    value: match[2],
  };
}

function parseLine(text: string): Omit<Line, "block"> {
  const marker = MARKER.exec(text)![0];
  const leading = /^ */.exec(text)![0].length;
  const dash = marker.length > leading ? leading : null;
  const content = text.slice(marker.length);
  const empty = !content.trim() || content.trimStart().startsWith("#");
  const blank = empty && dash === null;
  const match = empty ? null : KEY.exec(content);
  return {
    indent: blank ? text.length : leading,
    dash,
    // A bare "-" starts an item whose keys will follow two columns later.
    keyCol: blank
      ? text.length
      : dash !== null && empty
        ? dash + 2
        : marker.length,
    key: match ? unquote(match[1].trim()) : null,
    value: match ? match[2] : content,
    blank,
  };
}

/** Block scalar text must be indented further than this column. */
function blockBase(line: Omit<Line, "block">): number {
  return line.key === null ? line.indent : line.keyCol;
}

function outline(lines: string[]): Line[] {
  const result: Line[] = [];
  let owner: number | null = null;
  for (const [index, text] of lines.entries()) {
    const line = parseLine(text);
    if (
      owner !== null &&
      (line.blank || line.indent > blockBase(result[owner]))
    ) {
      result.push({ ...line, block: owner });
      continue;
    }
    owner = null;
    result.push({ ...line, block: null });
    if (!line.blank && BLOCK.test(yamlScalar(line.value))) owner = index;
  }
  return result;
}

function skipped(line: Line): boolean {
  return line.blank || line.block !== null;
}

/** Walk upward from `start`, whose mapping keys sit at `indent`. */
function walk(
  lines: Line[],
  start: number,
  first: Line,
  indent: number,
): { path: YamlSegment[]; containers: Container[] } {
  const path: YamlSegment[] = [];
  const containers: Container[] = [{ kind: "map", indent, line: start }];
  let at = start;
  let current = first;
  for (;;) {
    let item: number | null = null;
    let parent: number | null = null;
    for (let index = at; index >= 0; index--) {
      const line = index === at ? current : lines[index];
      if (index !== at && skipped(line)) continue;
      if (line.dash !== null && line.dash < indent && line.keyCol === indent) {
        item = index;
        break;
      }
      if (!line.blank && line.indent < indent) {
        parent = index;
        break;
      }
    }
    if (item !== null) {
      const column = (item === at ? current : lines[item]).dash!;
      let position = 0;
      parent = null;
      for (let index = item - 1; index >= 0; index--) {
        const line = lines[index];
        if (skipped(line)) continue;
        if (line.dash === column) position++;
        else if (
          line.indent < column ||
          (line.indent === column && line.dash === null)
        ) {
          parent = index;
          break;
        }
      }
      path.push(position);
      containers.push({ kind: "seq" });
      if (parent === null) break;
    }
    if (parent === null) break;
    const line = lines[parent];
    if (line.key === null) break;
    path.push(line.key);
    indent = line.keyCol;
    at = parent;
    current = line;
    containers.push({ kind: "map", indent, line: parent });
  }
  return { path: path.reverse(), containers: containers.reverse() };
}

/** Keys of the mapping whose keys sit at `indent` and which holds `start`. */
function entries(
  lines: Line[],
  start: number,
  indent: number,
): Array<{ key: string; value: string; line: number }> {
  const found: Array<{ key: string; value: string; line: number }> = [];
  const add = (index: number) => {
    const { key, value } = lines[index];
    if (key !== null)
      found.push({ key, value: yamlScalar(value), line: index });
  };
  for (let index = start; index >= 0; index--) {
    const line = lines[index];
    if (skipped(line)) continue;
    if (line.indent < indent) {
      if (line.dash !== null && line.keyCol === indent) add(index);
      break;
    }
    if (line.indent === indent && line.dash === null) add(index);
  }
  for (let index = start + 1; index < lines.length; index++) {
    const line = lines[index];
    if (skipped(line)) continue;
    if (line.indent < indent) break;
    if (line.indent === indent && line.dash === null) add(index);
  }
  return found;
}

export function yamlCursorAt(text: string, offset: number): YamlCursor {
  const rows = text.split(/\r?\n/);
  const lines = outline(rows);
  const row = text.slice(0, offset).split(/\r?\n/).length - 1;
  const before = text.slice(0, offset).split(/\r?\n/)[row];
  const prefix = PREFIX.exec(before)![0];
  const open = before.lastIndexOf("${{");
  const expression =
    open >= 0 && !before.slice(open).includes("}}")
      ? { text: before.slice(open + 3) }
      : null;
  const typed = parseLine(before);
  const owner = lines[row].block;
  const blockText =
    owner !== null &&
    (!lines[row].blank || typed.indent > blockBase(lines[owner]));
  let start = row;
  let first: Line = { ...typed, block: null, key: null };
  let position: YamlCursor["position"] = typed.key === null ? "key" : "value";
  let key = typed.key;
  if (blockText) {
    start = owner;
    first = lines[owner];
    position = "value";
    key = lines[owner].key;
  }
  const { path, containers } = walk(lines, start, first, first.keyCol);
  const scopes = containers.map((container) =>
    container.kind === "seq"
      ? {}
      : Object.fromEntries(
          entries(lines, container.line, container.indent).map((entry) => [
            entry.key,
            entry.value,
          ]),
        ),
  );
  const innermost = containers.at(-1)!;
  const siblings =
    innermost.kind === "map"
      ? entries(lines, innermost.line, innermost.indent)
          .filter((entry) => entry.line !== start)
          .map((entry) => entry.key)
      : [];
  return { path, position, key, prefix, siblings, expression, scopes };
}

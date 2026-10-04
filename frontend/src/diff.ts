/** Read Git's unified patch in linear time; do not compute a second diff. */
export type DiffLine = {
  kind: "context" | "added" | "removed";
  text: string;
  before: number | null;
  after: number | null;
  noNewline?: boolean;
};
export type DiffHunk = { heading: string; lines: DiffLine[] };
export type DiffFile = {
  before: string;
  after: string;
  status: "Modified" | "Added" | "Deleted" | "Renamed" | "Copied";
  binary: boolean;
  metadata: string[];
  hunks: DiffHunk[];
  additions: number;
  removals: number;
};
export type SplitLine = { before: DiffLine | null; after: DiffLine | null };

function gitPath(value: string): string {
  if (!value.startsWith('"') || !value.endsWith('"')) return value;
  // Git's quoted UTF-8 bytes, e.g. "r\303\251sum\303\251.ts", display as résumé.ts.
  // Keep control characters escaped, e.g. "a\n.ts" stays quoted and visible.
  const source = value.slice(1, -1);
  const encoder = new TextEncoder();
  const bytes: number[] = [];
  const escapes: Record<string, number> = { a: 7, b: 8, f: 12, n: 10, r: 13, t: 9, v: 11, '"': 34, "\\": 92 };
  let offset = 0;
  for (const match of source.matchAll(/\\([0-7]{1,3}|.)/g)) {
    for (const byte of encoder.encode(source.slice(offset, match.index))) bytes.push(byte);
    const escaped = match[1];
    const byte = /^[0-7]+$/.test(escaped) ? Number.parseInt(escaped, 8) : escapes[escaped];
    if (byte === undefined || byte > 255) return value;
    bytes.push(byte);
    offset = match.index + match[0].length;
  }
  for (const byte of encoder.encode(source.slice(offset))) bytes.push(byte);
  try {
    const decoded = new TextDecoder("utf-8", { fatal: true }).decode(Uint8Array.from(bytes));
    return /[\u0000-\u001f\u007f]/.test(decoded) ? value : decoded;
  } catch { return value; }
}

function patchPath(value: string): string {
  // "a/src/app.ts" -> "src/app.ts"; a quoted path is decoded before this step.
  return gitPath(value).replace(/^[ab]\//, "");
}

function headerPaths(value: string): [string, string] {
  // "a/my file.ts b/my file.ts" -> two "my file.ts" paths, preserving spaces.
  const quoted = value.match(/^("(?:\\.|[^"\\])*") /);
  if (quoted) return [patchPath(quoted[1]), patchPath(value.slice(quoted[0].length))];
  // "a/dir b/file b/dir b/file" has spaces inside both identical paths.
  // Split its equal halves first; rename/copy metadata supplies distinct names.
  const middle = (value.length - 1) / 2;
  if (Number.isInteger(middle) && value[middle] === " " && value.startsWith("a/") && value.slice(middle + 1).startsWith("b/") && value.slice(2, middle) === value.slice(middle + 3)) {
    return [patchPath(value.slice(0, middle)), patchPath(value.slice(middle + 1))];
  }
  const offset = Math.max(value.lastIndexOf(" b/"), value.lastIndexOf(' "b/'));
  return offset < 0 ? [value, value] : [patchPath(value.slice(0, offset)), patchPath(value.slice(offset + 1))];
}

export function parseGitDiff(text: string): DiffFile[] {
  const files: DiffFile[] = [];
  let file: DiffFile | undefined;
  let hunk: DiffHunk | undefined;
  let before = 0;
  let after = 0;
  // Splitting only at LF preserves tabs, blank lines, and CR bytes in file content.
  // "+\tconst x = 1;\r\n" becomes added text "\tconst x = 1;\r".
  const lines = text.split("\n");
  if (lines.at(-1) === "") lines.pop();
  for (const line of lines) {
    if (line.startsWith("diff --git ")) {
      const [oldPath, newPath] = headerPaths(line.slice("diff --git ".length));
      file = { before: oldPath, after: newPath, status: "Modified", binary: false, metadata: [], hunks: [], additions: 0, removals: 0 };
      files.push(file); hunk = undefined;
      continue;
    }
    if (!file) continue;
    const header = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$/);
    if (header) {
      before = Number(header[1]); after = Number(header[2]);
      hunk = { heading: line, lines: [] }; file.hunks.push(hunk);
      continue;
    }
    if (hunk) {
      // Strip the diff marker only: "+  return x;" -> "  return x;".
      // A source line beginning "++" or "--" is content, not a file header.
      const content = line.slice(1);
      if (line.startsWith("+")) {
        hunk.lines.push({ kind: "added", text: content, before: null, after: after++ }); file.additions++;
      } else if (line.startsWith("-")) {
        hunk.lines.push({ kind: "removed", text: content, before: before++, after: null }); file.removals++;
      } else if (line.startsWith(" ")) {
        hunk.lines.push({ kind: "context", text: content, before: before++, after: after++ });
      } else if (line.startsWith("\\ ") && hunk.lines.length > 0) {
        hunk.lines[hunk.lines.length - 1].noNewline = true;
      } else if (line !== "") file.metadata.push(line);
      continue;
    }
    if (line.startsWith("--- ")) file.before = patchPath(line.slice("--- ".length));
    else if (line.startsWith("+++ ")) file.after = patchPath(line.slice("+++ ".length));
    else {
      file.metadata.push(line);
      if (line.startsWith("new file mode ")) file.status = "Added";
      else if (line.startsWith("deleted file mode ")) file.status = "Deleted";
      else if (line.startsWith("rename from ")) { file.status = "Renamed"; file.before = gitPath(line.slice("rename from ".length)); }
      else if (line.startsWith("rename to ")) file.after = gitPath(line.slice("rename to ".length));
      else if (line.startsWith("copy from ")) { file.status = "Copied"; file.before = gitPath(line.slice("copy from ".length)); }
      else if (line.startsWith("copy to ")) file.after = gitPath(line.slice("copy to ".length));
      else if (line.startsWith("Binary files ") || line === "GIT binary patch") file.binary = true;
    }
  }
  return files;
}

export function splitDiffLines(lines: DiffLine[]): SplitLine[] {
  const rows: SplitLine[] = [];
  let removed: DiffLine[] = [];
  let added: DiffLine[] = [];
  function flush() {
    // Adjacent "-old", "+new" share a row. Extra lines keep an empty opposite cell.
    // This aligns Git's replacement blocks by position without a quadratic re-diff.
    for (let index = 0; index < Math.max(removed.length, added.length); index++) {
      rows.push({ before: removed[index] ?? null, after: added[index] ?? null });
    }
    removed = []; added = [];
  }
  for (const line of lines) {
    if (line.kind === "context") { flush(); rows.push({ before: line, after: line }); }
    else if (line.kind === "removed") { if (added.length > 0) flush(); removed.push(line); }
    else added.push(line);
  }
  flush();
  return rows;
}

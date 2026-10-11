/** Index file metadata in linear time, retaining the patch for the diff renderer. */
export type DiffFile = {
  before: string;
  after: string;
  status: "Modified" | "Added" | "Deleted" | "Renamed" | "Copied";
  binary: boolean;
  metadata: string[];
  patch: string;
  hasHunks: boolean;
  additions: number;
  removals: number;
};

function gitPath(value: string): string {
  if (!value.startsWith('"') || !value.endsWith('"')) return value;
  // Git's quoted UTF-8 bytes, e.g. "r\303\251sum\303\251.ts", display as résumé.ts.
  // Keep control characters escaped, e.g. "a\n.ts" stays quoted and visible.
  const source = value.slice(1, -1);
  const encoder = new TextEncoder();
  const bytes: number[] = [];
  const escapes: Record<string, number> = {
    a: 7,
    b: 8,
    f: 12,
    n: 10,
    r: 13,
    t: 9,
    v: 11,
    '"': 34,
    "\\": 92,
  };
  let offset = 0;
  for (const match of source.matchAll(/\\([0-7]{1,3}|.)/g)) {
    for (const byte of encoder.encode(source.slice(offset, match.index)))
      bytes.push(byte);
    const escaped = match[1];
    const byte = /^[0-7]+$/.test(escaped)
      ? Number.parseInt(escaped, 8)
      : escapes[escaped];
    if (byte === undefined || byte > 255) return value;
    bytes.push(byte);
    offset = match.index + match[0].length;
  }
  for (const byte of encoder.encode(source.slice(offset))) bytes.push(byte);
  try {
    const decoded = new TextDecoder("utf-8", { fatal: true }).decode(
      Uint8Array.from(bytes),
    );
    return /[\u0000-\u001f\u007f]/.test(decoded) ? value : decoded;
  } catch {
    return value;
  }
}

function patchPath(value: string): string {
  // "a/src/app.ts" -> "src/app.ts"; a quoted path is decoded before this step.
  return gitPath(value).replace(/^[ab]\//, "");
}

function headerPaths(value: string): [string, string] {
  // "a/my file.ts b/my file.ts" -> two "my file.ts" paths, preserving spaces.
  const quoted = value.match(/^("(?:\\.|[^"\\])*") /);
  if (quoted)
    return [patchPath(quoted[1]), patchPath(value.slice(quoted[0].length))];
  // "a/dir b/file b/dir b/file" has spaces inside both identical paths.
  // Split its equal halves first; rename/copy metadata supplies distinct names.
  const middle = (value.length - 1) / 2;
  if (
    Number.isInteger(middle) &&
    value[middle] === " " &&
    value.startsWith("a/") &&
    value.slice(middle + 1).startsWith("b/") &&
    value.slice(2, middle) === value.slice(middle + 3)
  ) {
    return [
      patchPath(value.slice(0, middle)),
      patchPath(value.slice(middle + 1)),
    ];
  }
  const offset = Math.max(value.lastIndexOf(" b/"), value.lastIndexOf(' "b/'));
  return offset < 0
    ? [value, value]
    : [patchPath(value.slice(0, offset)), patchPath(value.slice(offset + 1))];
}

export function parseGitDiff(text: string): DiffFile[] {
  const files: DiffFile[] = [];
  // Split only before actual Git headers; "+diff --git ..." remains source text.
  // Each patch retains exact tabs, CR bytes, blank lines, and its final newline.
  for (const patch of text.split(/(?=^diff --git )/m)) {
    if (!patch.startsWith("diff --git ")) continue;
    const lines = patch.split("\n");
    const [before, after] = headerPaths(lines[0].slice("diff --git ".length));
    const file: DiffFile = {
      before,
      after,
      status: "Modified",
      binary: false,
      metadata: [],
      patch,
      hasHunks: false,
      additions: 0,
      removals: 0,
    };
    if (lines.at(-1) === "") lines.pop();
    for (const line of lines.slice(1)) {
      if (line.startsWith("@@ ")) {
        file.hasHunks = true;
        continue;
      }
      // In a hunk, "+++value" is an added source line, not a file header.
      // Count only supplied lines so truncated previews never invent changes.
      if (file.hasHunks) {
        if (line.startsWith("+")) file.additions++;
        else if (line.startsWith("-")) file.removals++;
        continue;
      }
      if (line.startsWith("--- "))
        file.before = patchPath(line.slice("--- ".length));
      else if (line.startsWith("+++ "))
        file.after = patchPath(line.slice("+++ ".length));
      else {
        file.metadata.push(line);
        if (line.startsWith("new file mode ")) file.status = "Added";
        else if (line.startsWith("deleted file mode ")) file.status = "Deleted";
        else if (line.startsWith("rename from ")) {
          file.status = "Renamed";
          file.before = gitPath(line.slice("rename from ".length));
        } else if (line.startsWith("rename to "))
          file.after = gitPath(line.slice("rename to ".length));
        else if (line.startsWith("copy from ")) {
          file.status = "Copied";
          file.before = gitPath(line.slice("copy from ".length));
        } else if (line.startsWith("copy to "))
          file.after = gitPath(line.slice("copy to ".length));
        else if (
          line.startsWith("Binary files ") ||
          line === "GIT binary patch"
        )
          file.binary = true;
      }
    }
    files.push(file);
  }
  return files;
}

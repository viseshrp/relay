// The same line breaks as Python's str.splitlines(), which the server uses.
const LINE_BREAK = /\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]/;

/**
 * Read a list input (`agents`, `argv`, `options`) as the server does: a JSON
 * array of strings, or one non-blank value per line. Returns null for a JSON
 * array that is malformed or holds anything other than strings.
 */
export function parseListInput(raw: unknown): string[] | null {
  const text = String(raw ?? "").trim();
  if (!text) return [];
  if (text.startsWith("[")) {
    let items: unknown;
    try {
      items = JSON.parse(text);
    } catch {
      return null;
    }
    return Array.isArray(items) &&
      items.every((item): item is string => typeof item === "string")
      ? items
      : null;
  }
  return text
    .split(LINE_BREAK)
    .map((line) => line.trim())
    .filter(Boolean);
}

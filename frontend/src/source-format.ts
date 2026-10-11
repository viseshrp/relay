import { isMap, parseDocument, visit } from "yaml";

export function formatWorkflowYaml(source: string): string {
  const document = parseDocument(source, {
    uniqueKeys: true,
    intAsBigInt: true,
    keepSourceTokens: true,
  });
  if (document.errors.length)
    throw new Error(document.errors.map((item) => item.message).join("\n"));
  return document.toString({
    collectionStyle: "block",
    blockQuote: "literal",
    lineWidth: 80,
  });
}

export function sourceDiff(before: string, after: string): string {
  const left = before.split("\n");
  const right = after.split("\n");
  let start = 0;
  while (
    start < left.length &&
    start < right.length &&
    left[start] === right[start]
  )
    start++;
  let end = 0;
  while (
    end < left.length - start &&
    end < right.length - start &&
    left[left.length - end - 1] === right[right.length - end - 1]
  )
    end++;
  const changes = [
    ...left.slice(start, end ? -end : undefined).map((line) => `− ${line}`),
    ...right.slice(start, end ? -end : undefined).map((line) => `+ ${line}`),
  ];
  return changes.length
    ? changes.slice(0, 1000).join("\n") +
        (changes.length > 1000 ? "\n… Preview truncated" : "")
    : "No changes.";
}

export function readableWorkflowYaml(source: string): string {
  // This is a display projection; callers retain the original source and hash.
  if (!source.trimStart().startsWith("{")) return source;
  try {
    JSON.parse(source);
    const document = parseDocument(source, {
      uniqueKeys: true,
      intAsBigInt: true,
    });
    if (document.errors.length || !isMap(document.contents)) return source;
    visit(document, {
      Scalar(_key, scalar) {
        if (typeof scalar.value === "string") scalar.type = undefined;
        if (scalar.source === "-0") scalar.value = -0;
      },
    });
    return document.toString({
      collectionStyle: "block",
      blockQuote: "literal",
      lineWidth: 80,
    });
  } catch {
    return source;
  }
}

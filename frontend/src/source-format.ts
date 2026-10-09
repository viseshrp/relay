import { isMap, parseDocument, visit } from "yaml";

export function readableWorkflowYaml(source: string): string {
  // This is a display projection; callers retain the original source and hash.
  if (!source.trimStart().startsWith("{")) return source;
  try {
    JSON.parse(source);
    const document = parseDocument(source, { uniqueKeys: true, intAsBigInt: true });
    if (document.errors.length || !isMap(document.contents)) return source;
    visit(document, { Scalar(_key, scalar) {
      if (typeof scalar.value === "string") scalar.type = undefined;
      if (scalar.source === "-0") scalar.value = -0;
    } });
    return document.toString({ collectionStyle: "block", blockQuote: "literal", lineWidth: 80 });
  } catch { return source; }
}

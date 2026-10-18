// Completion and hover help for the YAML editor. Both read the cursor's place
// from yaml-path and offer only what the server's language manifest accepts
// there.

import { snippet, type Completion } from "@codemirror/autocomplete";
import { parseActions } from "./actions-workflow";
import { parseBuiltin } from "./builtin-actions";
import {
  availableContexts,
  definitionAt,
  expressionAllowed,
  expressionSuggestions,
  mappingProperties,
  propertyType,
  type LanguageManifest,
} from "./workflow-language";
import {
  yamlCursorAt,
  yamlLineKey,
  yamlScalar,
  type YamlCursor,
} from "./yaml-path";

export interface CompletionExtra {
  /** Agent IDs to offer for an agent step's agent input. */
  agents: string[];
}

const LOCAL_ACTIONS = "./.relay/actions/";
const LOCAL_WORKFLOWS = "./.relay/workflows/";
// An empty snippet field, where the next value is typed.
const FIELD = "${}";

function startsWith(label: string, prefix: string): boolean {
  return label.toLowerCase().startsWith(prefix.toLowerCase());
}

/** The built-in action whose `with` mapping holds the cursor, if any. */
function withAction(
  cursor: YamlCursor,
  manifest: LanguageManifest,
): string | null {
  if (cursor.path.at(-1) !== "with") return null;
  const uses = cursor.scopes[cursor.path.length - 1]?.uses;
  return uses !== undefined && manifest.builtin_inputs[uses] ? uses : null;
}

function describeKey(
  cursor: YamlCursor,
  key: string,
  manifest: LanguageManifest,
): string | null {
  const action = withAction(cursor, manifest);
  if (action)
    return manifest.builtin_inputs[action].descriptions?.[key] ?? null;
  const name = definitionAt(cursor.path, manifest, cursor.scopes);
  const owner = name ? propertyType(name, key, manifest)?.owner : null;
  return owner
    ? (manifest.property_descriptions?.[`${owner}.${key}`] ?? null)
    : null;
}

function keyOptions(
  cursor: YamlCursor,
  manifest: LanguageManifest,
): Completion[] {
  const action = withAction(cursor, manifest);
  const keys = action
    ? manifest.builtin_inputs[action].allowed
    : mappingProperties(
        definitionAt(cursor.path, manifest, cursor.scopes) ?? "",
        manifest,
      ).map((property) => property.key);
  return keys
    .filter((key) => !cursor.siblings.includes(key))
    .map((key) => {
      const info = describeKey(cursor, key, manifest);
      return {
        label: key,
        type: "property",
        apply: `${key}: `,
        ...(info ? { info } : {}),
      };
    });
}

function expressionOptions(
  text: string,
  cursor: YamlCursor,
  manifest: LanguageManifest,
): Completion[] {
  const job =
    cursor.path[0] === "jobs" && typeof cursor.path[1] === "string"
      ? cursor.path[1]
      : undefined;
  const names = [
    ...expressionSuggestions(parseActions(text).value, job).map((item) =>
      item.replace(/^\$\{\{\s*/, "").replace(/\s*\}\}$/, ""),
    ),
    ...Object.entries(manifest.context_properties).flatMap(
      ([context, properties]) =>
        properties.map((property) => `${context}.${property}`),
    ),
  ];
  // Offer only what validation accepts in this field: its contexts and
  // functions, and properties its context has.
  const available = availableContexts(
    cursor.path,
    cursor.key,
    manifest,
    cursor.scopes,
  );
  const valid = (name: string) => expressionAllowed(name, available, manifest);
  const options = new Map<string, Completion>();
  for (const name of names)
    if (valid(name) && startsWith(name, cursor.prefix) && !options.has(name))
      options.set(name, { label: name, type: "variable" });
  // A name written with another platform's root offers Relay's name for it.
  if (cursor.prefix.includes(".")) {
    const aliases = Object.entries(manifest.platform_names ?? {}).flatMap(
      ([root, properties]) =>
        Object.entries(properties).map(([property, replacement]) => [
          `${root}.${property}`,
          replacement,
        ]),
    );
    // Event inputs, written under the root that maps event, are plain inputs.
    for (const [root, properties] of Object.entries(
      manifest.platform_names ?? {},
    ))
      if ("event" in properties)
        for (const name of names.filter((item) => item.startsWith("inputs.")))
          aliases.push([`${root}.event.${name}`, name]);
    for (const [alias, replacement] of aliases)
      if (
        valid(replacement) &&
        startsWith(alias, cursor.prefix) &&
        !options.has(replacement)
      )
        options.set(replacement, {
          label: replacement,
          type: "variable",
          info: `Use ${replacement}.`,
        });
  }
  return [...options.values()];
}

function fixedValues(
  type: string,
  definitions: LanguageManifest["definitions"],
): string[] {
  const definition = definitions[type];
  if (type === "boolean" || definition?.boolean !== undefined)
    return ["true", "false"];
  if (definition?.["allowed-values"]) return definition["allowed-values"];
  return (definition?.["one-of"] ?? []).flatMap((option) => {
    const constant = definitions[option]?.string?.constant;
    return constant
      ? [constant]
      : (definitions[option]?.["allowed-values"] ?? []);
  });
}

function actionOption(
  reference: string,
  cursor: YamlCursor,
  manifest: LanguageManifest,
  line: string,
  lead: string,
): Completion {
  const inputs = manifest.builtin_inputs[reference];
  const option: Completion = {
    label: reference,
    type: "constant",
    ...(inputs?.summary ? { info: inputs.summary } : {}),
  };
  if (cursor.siblings.includes("with") || !inputs?.required.length)
    return option;
  // Snippet lines after the first start at the line's own indentation.
  const base = /^ */.exec(line)![0].length;
  const pad = " ".repeat((yamlLineKey(line)?.from ?? base) - base);
  const template = [
    `${lead}${reference}`,
    `${pad}with:`,
    ...inputs.required.map(
      (name) => `${pad}  ${name}: ${name === "max-iterations" ? "3" : FIELD}`,
    ),
  ].join("\n");
  return { ...option, apply: snippet(template) };
}

/** Values for the key whose value holds the cursor. */
export function valueCompletionsAt(
  cursor: YamlCursor,
  manifest: LanguageManifest,
  extra: CompletionExtra,
  line = "",
  lead = "",
): Completion[] {
  const constants = (values: readonly string[]): Completion[] =>
    values.map((label) => ({ label, type: "constant" }));
  const key = cursor.key ?? "";
  const name = definitionAt(cursor.path, manifest, cursor.scopes);
  if (key === "uses" && name === "regular-step")
    return [
      ...[...manifest.builtins]
        .sort()
        .map((reference) =>
          actionOption(reference, cursor, manifest, line, lead),
        ),
      {
        label: LOCAL_ACTIONS,
        type: "constant",
        info: "Local action directory",
      },
    ];
  if (key === "uses" && name === "workflow-job")
    return constants([LOCAL_WORKFLOWS]);
  if (key === "uses") return [];
  if (key === "shell") return constants(manifest.value_hints?.shell ?? []);
  if (key === "cache-mode") return constants(manifest.cache_modes ?? []);
  const action = withAction(cursor, manifest);
  if (action) {
    const values = manifest.builtin_inputs[action].values?.[key];
    if (values) return constants(values);
    return key === "agent" && parseBuiltin(action)?.name === "agent"
      ? constants(extra.agents)
      : [];
  }
  const property = name ? propertyType(name, key, manifest) : null;
  return property
    ? constants(fixedValues(property.type, manifest.definitions))
    : [];
}

export function completionsAt(
  text: string,
  offset: number,
  manifest: LanguageManifest,
  extra: CompletionExtra,
): { from: number; options: Completion[] } | null {
  const cursor = yamlCursorAt(text, offset);
  const from = offset - cursor.prefix.length;
  const lineStart = text.lastIndexOf("\n", offset - 1) + 1;
  const lineEnd = text.indexOf("\n", offset);
  const line = text.slice(lineStart, lineEnd < 0 ? text.length : lineEnd);
  let options: Completion[];
  if (cursor.expression) options = expressionOptions(text, cursor, manifest);
  else if (cursor.position === "key")
    options = keyOptions(cursor, manifest).filter((option) =>
      startsWith(option.label, cursor.prefix),
    );
  else {
    // A value typed straight after the colon needs a space before it.
    const lead = text[from - 1] === ":" ? " " : "";
    options = valueCompletionsAt(cursor, manifest, extra, line, lead)
      .filter((option) => startsWith(option.label, cursor.prefix))
      .map((option) =>
        lead && option.apply === undefined
          ? { ...option, apply: lead + option.label }
          : option,
      );
  }
  return options.length ? { from, options } : null;
}

/** Help for the key, or the uses value, under the pointer; never a type name. */
export function hoverTextAt(
  text: string,
  offset: number,
  manifest: LanguageManifest,
): string | null {
  const start = text.lastIndexOf("\n", offset - 1) + 1;
  const end = text.indexOf("\n", offset);
  const line = text.slice(start, end < 0 ? text.length : end);
  const column = offset - start;
  const found = yamlLineKey(line);
  if (!found || column < found.from) return null;
  const cursor = yamlCursorAt(text, start + found.from);
  if (cursor.position !== "key") return null;
  if (column <= found.to) return describeKey(cursor, found.key, manifest);
  if (found.key !== "uses" || column <= found.to + 1) return null;
  return manifest.builtin_inputs[yamlScalar(found.value)]?.summary || null;
}

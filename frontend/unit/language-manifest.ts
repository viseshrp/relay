import { readFileSync } from "node:fs";
import type { BuiltinInputs, LanguageManifest } from "../src/workflow-language";

// The server's schema, read as it ships; built-in actions are a small stand-in
// for the registry that the Python tests cover.
const schema = JSON.parse(
  readFileSync(
    new URL("../../relay/workflows/actions/schema.json", import.meta.url),
    "utf8",
  ),
) as Pick<LanguageManifest, "definitions" | "property_descriptions">;

function action(
  allowed: string[],
  required: string[] = [],
  values: Record<string, string[]> = {},
): BuiltinInputs {
  return {
    allowed,
    required,
    summary: `Summary of ${allowed[0] ?? "an action"}.`,
    descriptions: Object.fromEntries(
      allowed.map((input) => [input, `Help for ${input}.`]),
    ),
    values,
  };
}

const inputs: Record<string, BuiltinInputs> = {
  "relay/agent@v1": action(
    ["agent", "agents", "format", "model", "prompt", "prompt-files"],
    [],
    { format: ["exists", "label", "json", "yaml"] },
  ),
  "relay/cache@v1": action(["key", "path"], ["key", "path"]),
  "relay/command@v1": action(["argv", "command"]),
  "relay/download-artifact@v1": action(["name", "path"], ["name"]),
  "relay/human-wait@v1": action(
    ["options", "prompt", "timeout-minutes"],
    ["prompt"],
  ),
  "relay/loop@v1": action(
    ["max-iterations", "workflow"],
    ["max-iterations", "workflow"],
  ),
  "relay/restore-cache@v1": action(["key", "path"], ["key", "path"]),
  "relay/save-cache@v1": action(["key", "path"], ["key", "path"]),
  "relay/upload-artifact@v1": action(["name", "path"], ["path"]),
  "relay/validate-input@v1": action(["type", "value"], ["type", "value"], {
    type: ["string", "integer", "number", "boolean", "enum"],
  }),
  "relay/validate-report@v1": action(["format", "path"]),
};

export const manifest: LanguageManifest = {
  definitions: schema.definitions,
  property_descriptions: schema.property_descriptions,
  // Deliberately unsorted: completion sorts them.
  builtins: Object.keys(inputs).reverse(),
  builtin_inputs: inputs,
  builtin_versions: Object.fromEntries(
    Object.keys(inputs).map((reference) => [
      reference,
      {
        name: reference.slice("relay/".length, reference.indexOf("@")),
        major: 1,
        status: "current" as const,
      },
    ]),
  ),
  cache_modes: ["none", "read", "write", "write-only"],
  value_hints: { shell: ["bash", "sh", "pwsh", "powershell", "cmd", "python"] },
  platform_names: {
    github: {
      event: "relay.event",
      ref_name: "relay.ref_name",
      sha: "relay.sha",
    },
    runner: { os: "host.os" },
  },
  contexts: ["host", "inputs", "relay"],
  context_properties: {
    relay: ["run_id", "run_number", "sha"],
    host: ["arch", "os"],
  },
};

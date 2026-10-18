import { expect, test } from "@playwright/test";
import type { Completion } from "@codemirror/autocomplete";
import { EditorState, type Transaction } from "@codemirror/state";
import { completionsAt, hoverTextAt } from "../src/yaml-completion";
import { manifest } from "./language-manifest";

const extra = { agents: ["claude", "codex"] };

function labels(text: string): string[] | null {
  return (
    completionsAt(text, text.length, manifest, extra)?.options.map(
      (option) => option.label,
    ) ?? null
  );
}

function option(text: string, label: string): Completion {
  const found = completionsAt(text, text.length, manifest, extra)?.options.find(
    (item) => item.label === label,
  );
  if (!found) throw new Error(`No completion ${label}`);
  return found;
}

/** Apply a completion the way the editor does and return the new document. */
function applied(text: string, label: string): string {
  const result = completionsAt(text, text.length, manifest, extra)!;
  const choice = result.options.find((item) => item.label === label)!;
  let state = EditorState.create({ doc: text });
  const editor = {
    get state() {
      return state;
    },
    dispatch(transaction: Transaction) {
      state = transaction.state;
    },
  };
  if (typeof choice.apply === "function")
    choice.apply(editor as never, choice, result.from, text.length);
  else
    state = state.update({
      changes: {
        from: result.from,
        to: text.length,
        insert: choice.apply ?? choice.label,
      },
    }).state;
  return state.doc.toString();
}

const keyCases: Array<[string, string[] | null]> = [
  ["jobs:\n  a:\n    steps:\n      - ru", ["run"]],
  ["jobs:\n  a:\n    ti", ["timeout-minutes"]],
  ["ru", ["run-name"]],
  [
    "jobs:\n  a:\n    steps:\n      - uses: relay/agent@v1\n        with:\n          mo",
    ["model"],
  ],
  ["on:\n  wor", ["workflow_dispatch", "workflow_call", "workflow_run"]],
  ["jobs:\n  a:\n    name: x\n    na", null],
];

for (const [text, expected] of keyCases)
  test(`completion after ${JSON.stringify(text)}`, () => {
    expect(labels(text)).toEqual(expected);
  });

test("key completion describes each field and inserts its colon", () => {
  const run = option("jobs:\n  a:\n    steps:\n      - ru", "run");
  expect(run.info).toBe(manifest.property_descriptions["run-step.run"]);
  expect(run.apply).toBe("run: ");
  expect(
    option(
      "jobs:\n  a:\n    steps:\n      - uses: relay/agent@v1\n        with:\n          mo",
      "model",
    ).info,
  ).toBe(manifest.builtin_inputs["relay/agent@v1"].descriptions.model);
});

test("a script step offers no action fields, and an action step no script fields", () => {
  expect(
    labels("jobs:\n  a:\n    steps:\n      - run: echo\n        wi"),
  ).toBeNull();
  expect(
    labels("jobs:\n  a:\n    steps:\n      - uses: relay/agent@v1\n        sh"),
  ).toBeNull();
  expect(
    labels("jobs:\n  a:\n    steps:\n      - run: echo\n        sh"),
  ).toEqual(["shell"]);
});

test("expression completion offers names valid in the expression", () => {
  const text =
    "on:\n  workflow_dispatch:\n    inputs:\n      task: {type: string}\njobs:\n  a:\n    steps:\n      - run: echo ${{ ";
  expect(labels(`${text}inp`)).toEqual(["inputs.task"]);
  expect(labels(`${text}relay.`)).toEqual([
    "relay.run_id",
    "relay.run_number",
    "relay.sha",
  ]);
  const aliased = option(`${text}github.sh`, "relay.sha");
  expect(aliased.info).toBe("Use relay.sha.");
  expect(labels(`${text}runner.o`)).toEqual(["host.os"]);
  expect(labels(`${text}github.event.inputs.t`)).toEqual(["inputs.task"]);
  expect(labels(`${text}name`)).toBeNull();
});

test("expression completion offers only the contexts and functions of its field", () => {
  const step = "jobs:\n  a:\n    steps:\n      - ";
  expect(labels(`${step}run: echo \${{ succ`)).toBeNull();
  expect(labels(`${step}if: \${{ succ`)).toEqual(["success()"]);
  expect(labels(`${step}run: echo \${{ host.`)).toEqual([
    "host.arch",
    "host.os",
  ]);
  expect(labels("jobs:\n  a:\n    if: ${{ host.")).toBeNull();
  expect(labels("name: ${{ rel")).toBeNull();
  expect(labels("run-name: ${{ rel")).toEqual([
    "relay.run_id",
    "relay.run_number",
    "relay.sha",
  ]);
  expect(labels("jobs:\n  a:\n    concurrency:\n      group: ${{ rel")).toEqual(
    ["relay.run_id", "relay.run_number", "relay.sha"],
  );
});

test("uses on a step offers every built-in action, sorted, then a local action", () => {
  const options = completionsAt(
    "jobs:\n  a:\n    steps:\n      - uses:",
    35,
    manifest,
    extra,
  )!.options;
  expect(options.map((item) => item.label)).toEqual([
    ...[...manifest.builtins].sort(),
    "./.relay/actions/",
  ]);
  expect(options[0].info).toBe(
    manifest.builtin_inputs[[...manifest.builtins].sort()[0]].summary,
  );
  expect(options.at(-1)?.info).toBe("Local action directory");
  expect(labels("jobs:\n  a:\n    uses: ")).toEqual(["./.relay/workflows/"]);
});

test("fixed values are offered in their own order", () => {
  expect(
    labels("jobs:\n  a:\n    steps:\n      - run: echo\n        shell: "),
  ).toEqual(["bash", "sh", "pwsh", "powershell", "cmd", "python"]);
  expect(
    labels(
      "on:\n  workflow_dispatch:\n    inputs:\n      task:\n        type: ",
    ),
  ).toEqual(["string", "boolean", "number", "environment", "choice"]);
  expect(labels("jobs:\n  a:\n    cache-mode: ")).toEqual(manifest.cache_modes);
  expect(labels("jobs:\n  a:\n    continue-on-error: ")).toEqual([
    "true",
    "false",
  ]);
  expect(labels("jobs:\n  a:\n    concurrency:\n      queue: ")).toEqual([
    "single",
    "max",
  ]);
  const agent =
    "jobs:\n  a:\n    steps:\n      - uses: relay/agent@v1\n        with:\n          ";
  expect(labels(`${agent}format: `)).toEqual([
    "exists",
    "label",
    "json",
    "yaml",
  ]);
  expect(labels(`${agent}agent: c`)).toEqual(["claude", "codex"]);
  expect(labels(`${agent}model: `)).toBeNull();
  expect(
    labels(
      "jobs:\n  a:\n    steps:\n      - uses: relay/validate-input@v1\n        with:\n          type: ",
    ),
  ).toEqual(["string", "integer", "number", "boolean", "enum"]);
  expect(
    labels("jobs:\n  a:\n    steps:\n      - run: |\n          echo "),
  ).toBeNull();
});

test("choosing an action for a step without with adds its required inputs", () => {
  const step = "jobs:\n  a:\n    steps:\n      - uses: ";
  expect(applied(step, "relay/human-wait@v1")).toBe(
    `${step}relay/human-wait@v1\n        with:\n          prompt: `,
  );
  expect(applied(step, "relay/loop@v1")).toBe(
    `${step}relay/loop@v1\n        with:\n          max-iterations: 3\n          workflow: `,
  );
  expect(applied(step, "relay/command@v1")).toBe(`${step}relay/command@v1`);
  const later = "jobs:\n  a:\n    steps:\n      - id: wait\n        uses: ";
  expect(applied(later, "relay/human-wait@v1")).toBe(
    `${later}relay/human-wait@v1\n        with:\n          prompt: `,
  );
  const withInputs =
    "jobs:\n  a:\n    steps:\n      - with: {prompt: Go?}\n        uses: ";
  expect(applied(withInputs, "relay/human-wait@v1")).toBe(
    `${withInputs}relay/human-wait@v1`,
  );
  expect(
    applied("jobs:\n  a:\n    steps:\n      - uses:", "relay/command@v1"),
  ).toBe("jobs:\n  a:\n    steps:\n      - uses: relay/command@v1");
});

function hover(text: string, word: string, occurrence = 0): string | null {
  let index = -1;
  for (let count = 0; count <= occurrence; count++)
    index = text.indexOf(word, index + 1);
  return hoverTextAt(text, index + 1, manifest);
}

test("hover describes the field under the pointer by its place", () => {
  const text = [
    "defaults:",
    "  run:",
    "    shell: bash",
    "jobs:",
    "  a:",
    "    needs: [b]",
    "    steps:",
    "      - run: echo",
    "      - uses: relay/agent@v1",
    "        with:",
    "          prompt: Go",
    "          unknown: x",
    "  b:",
    "    steps: [{run: echo}]",
  ].join("\n");
  const descriptions = manifest.property_descriptions;
  expect(hover(text, "run", 1)).toBe(descriptions["run-step.run"]);
  expect(hover(text, "run")).toBe(descriptions["workflow-defaults.run"]);
  expect(hover(text, "needs")).toBe(descriptions["job-factory.needs"]);
  expect(hover(text, "prompt")).toBe(
    manifest.builtin_inputs["relay/agent@v1"].descriptions.prompt,
  );
  expect(hover(text, "relay/agent")).toBe(
    manifest.builtin_inputs["relay/agent@v1"].summary,
  );
  expect(hover(text, "unknown")).toBeNull();
  expect(hover(text, "  a:")).toBeNull();
  expect(hover(text, "echo")).toBeNull();
});

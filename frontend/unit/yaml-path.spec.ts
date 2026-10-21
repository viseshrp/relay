import { expect, test } from "@playwright/test";
import { yamlCursorAt } from "../src/yaml-path";

const cases: Array<
  [
    string,
    Array<string | number>,
    "key" | "value",
    string | null,
    string,
    { text: string } | null,
  ]
> = [
  [
    "jobs:\n  a:\n    steps:\n      - ru",
    ["jobs", "a", "steps", 0],
    "key",
    null,
    "ru",
    null,
  ],
  [
    "jobs:\n  a:\n    steps:\n      - run: echo\n        sh",
    ["jobs", "a", "steps", 0],
    "key",
    null,
    "sh",
    null,
  ],
  ["jobs:\n  a:\n    ne", ["jobs", "a"], "key", null, "ne", null],
  [
    "jobs:\n  a:\n    steps:\n      - uses: relay/agent@v1\n        with:\n          mo",
    ["jobs", "a", "steps", 0, "with"],
    "key",
    null,
    "mo",
    null,
  ],
  ["on:\n  wor", ["on"], "key", null, "wor", null],
  [
    "jobs:\n  a:\n    steps:\n      - uses:",
    ["jobs", "a", "steps", 0],
    "value",
    "uses",
    "",
    null,
  ],
  [
    "jobs:\n  a:\n    steps:\n      - run: |\n          echo ${{ inp",
    ["jobs", "a", "steps", 0],
    "value",
    "run",
    "inp",
    { text: " inp" },
  ],
];

for (const [text, path, position, key, prefix, expression] of cases)
  test(`yamlCursorAt reads ${JSON.stringify(text)}`, () => {
    const cursor = yamlCursorAt(text, text.length);
    expect(cursor.path).toEqual(path);
    expect(cursor.position).toBe(position);
    expect(cursor.key).toBe(key);
    expect(cursor.prefix).toBe(prefix);
    expect(cursor.expression).toEqual(expression);
  });

test("siblings list the other keys of the cursor's mapping, before and after it", () => {
  const text =
    "jobs:\n  a:\n    name: x\n    \n    steps:\n      - run: echo\n";
  const cursor = yamlCursorAt(text, text.indexOf("    \n") + 4);
  expect(cursor.path).toEqual(["jobs", "a"]);
  expect(cursor.siblings).toEqual(["name", "steps"]);
  const step = "jobs:\n  a:\n    steps:\n      - run: echo\n        sh";
  expect(yamlCursorAt(step, step.length).siblings).toEqual(["run"]);
});

test("later list items count earlier items at the same indent", () => {
  const text =
    "jobs:\n  a:\n    steps:\n      - run: one\n        shell: bash\n      - uses: x\n        with:\n          a: |\n            - not an item\n      - na";
  const cursor = yamlCursorAt(text, text.length);
  expect(cursor.path).toEqual(["jobs", "a", "steps", 2]);
  expect(cursor.scopes[3]).toEqual({});
  expect(yamlCursorAt(text, text.indexOf("with:")).scopes[4]).toEqual({
    uses: "x",
    with: "",
  });
});

test("a list written at its key's indent still resolves", () => {
  const text = "jobs:\n  a:\n    steps:\n    - run: echo\n      sh";
  expect(yamlCursorAt(text, text.length).path).toEqual([
    "jobs",
    "a",
    "steps",
    0,
  ]);
});

test("comments and closed expressions are not context", () => {
  const text = "# jobs:\non:\n  # a comment\n  wor";
  expect(yamlCursorAt(text, text.length).path).toEqual(["on"]);
  const closed = "jobs:\n  a:\n    if: ${{ success() }} && ";
  expect(yamlCursorAt(closed, closed.length).expression).toBeNull();
});

import { expect, test } from "@playwright/test";
import {
  builtinLabel,
  currentBuiltin,
  isBuiltin,
  parseBuiltin,
} from "../src/builtin-actions";
import type { LanguageManifest } from "../src/workflow-language";

test("parseBuiltin splits only relay/<name>@v<major> references", () => {
  expect(parseBuiltin("relay/save-cache@v1")).toEqual({
    name: "save-cache",
    major: 1,
  });
  expect(parseBuiltin("relay/agent@v9")).toEqual({ name: "agent", major: 9 });
  for (const value of [
    "relay/agent@v0",
    "relay/agent",
    "./.relay/actions/agent",
    null,
    undefined,
    7,
  ]) {
    expect(parseBuiltin(value)).toBeNull();
  }
});

test("isBuiltin matches any version of one action", () => {
  expect(isBuiltin("relay/agent@v9", "agent")).toBe(true);
  expect(isBuiltin("relay/agent@v1", "agent")).toBe(true);
  expect(isBuiltin("relay/agent@v1", "loop")).toBe(false);
  expect(isBuiltin(null, "agent")).toBe(false);
});

test("builtinLabel names the action and keeps other references", () => {
  expect(builtinLabel("relay/save-cache@v1")).toBe("save-cache");
  expect(builtinLabel("./.relay/actions/lint")).toBe("./.relay/actions/lint");
});

test("currentBuiltin returns the current reference for an action", () => {
  const manifest = {
    builtin_versions: {
      "relay/command@v1": { name: "command", major: 1, status: "deprecated" },
      "relay/command@v2": { name: "command", major: 2, status: "current" },
    },
  } as unknown as LanguageManifest;
  expect(currentBuiltin(manifest, "command")).toBe("relay/command@v2");
  expect(() => currentBuiltin(manifest, "loop")).toThrow(
    "Unknown built-in action loop",
  );
});

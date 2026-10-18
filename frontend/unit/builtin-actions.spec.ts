import { expect, test } from "@playwright/test";
import {
  builtinLabel,
  currentBuiltin,
  isBuiltin,
  isDeprecatedBuiltin,
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

// A stand-in pair: Relay ships one version of each built-in.
const twoVersions = {
  builtin_versions: {
    "relay/command@v1": {
      name: "command",
      major: 1,
      status: "deprecated",
      deprecated_in: "0.0.0",
    },
    "relay/command@v2": {
      name: "command",
      major: 2,
      status: "current",
      deprecated_in: "",
    },
  },
} as unknown as LanguageManifest;

test("currentBuiltin returns the current reference for an action", () => {
  expect(currentBuiltin(twoVersions, "command")).toBe("relay/command@v2");
  expect(() => currentBuiltin(twoVersions, "loop")).toThrow(
    "Unknown built-in action loop",
  );
});

test("isDeprecatedBuiltin marks only registered older versions", () => {
  expect(isDeprecatedBuiltin(twoVersions, "relay/command@v1")).toBe(true);
  for (const uses of [
    "relay/command@v2",
    "relay/command@v9",
    "./.relay/actions/command",
    undefined,
  ]) {
    expect(isDeprecatedBuiltin(twoVersions, uses)).toBe(false);
  }
});

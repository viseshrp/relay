import { expect, test } from "@playwright/test";
import { parseListInput } from "../src/list-input";

test("list inputs accept a JSON array or one value per line", () => {
  expect(parseListInput('["codex", "claude"]')).toEqual(["codex", "claude"]);
  expect(parseListInput("codex\nclaude\n")).toEqual(["codex", "claude"]);
  expect(parseListInput("codex")).toEqual(["codex"]);
  expect(parseListInput("  git\r\n\n  status  \n")).toEqual(["git", "status"]);
  expect(parseListInput("")).toEqual([]);
  expect(parseListInput(undefined)).toEqual([]);
});

test("list inputs reject a malformed JSON array", () => {
  expect(parseListInput('["codex",')).toBeNull();
  expect(parseListInput("[1, 2]")).toBeNull();
});

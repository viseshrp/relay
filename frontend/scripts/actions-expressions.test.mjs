import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { test } from "node:test";
import { data, Evaluator, Lexer, Parser } from "@actions/expressions";
import { reviver } from "@actions/expressions/data/reviver";
import { replacer } from "@actions/expressions/data/replacer";
import { kindStr } from "@actions/expressions/data/expressiondata";

const fixtures = new URL("../../tests/fixtures/actions/expressions/", import.meta.url);
for (const filename of await readdir(fixtures)) {
  const groups = JSON.parse(await readFile(new URL(filename, fixtures), "utf8"), (key, value) => {
    if (key === "contexts") return JSON.parse(JSON.stringify(value), reviver);
    if (key === "result") value.value = reviver("value", value.value);
    return value;
  });
  for (const [group, cases] of Object.entries(groups)) for (const [index, fixture] of cases.entries()) {
    test(`Actions oracle ${filename}:${group}:${index}`, { skip: fixture.options?.skip?.includes("typescript") }, () => {
      const contexts = fixture.contexts || new data.Dictionary();
      let stage = "lexing";
      let result;
      try {
        const tokens = new Lexer(fixture.expr).lex().tokens;
        stage = "parsing";
        const tree = new Parser(tokens, contexts.pairs().map(item => item.key), []).parse();
        stage = "evaluation";
        result = tree === undefined ? new data.Null() : new Evaluator(tree, contexts).evaluate();
      } catch (error) {
        assert.ok(fixture.err, error.message);
        assert.equal(stage, fixture.err.kind);
        if (stage === "lexing") assert.ok(error.message.includes(fixture.err.value));
        return;
      }
      assert.equal(fixture.err, undefined, "Expected an expression error");
      assert.equal(kindStr(result.kind), fixture.result.kind);
      assert.equal(JSON.stringify(result, replacer), JSON.stringify(fixture.result.value, replacer));
    });
  }
}

import js from "@eslint/js";
import babelParser from "@babel/eslint-parser";
import hooks from "eslint-plugin-react-hooks";
import a11y from "eslint-plugin-jsx-a11y";

const components = {
  rules: {
    "bounded-component": {
      meta: {
        schema: [],
        messages: {
          long: "Split {{name}} by responsibility ({{lines}} lines; maximum 300).",
        },
      },
      create(context) {
        return {
          FunctionDeclaration(node) {
            const name = node.id?.name ?? "";
            if (!/^[A-Z]/.test(name)) return;
            const lines = node.loc.end.line - node.loc.start.line + 1;
            if (lines > 300)
              context.report({
                node,
                messageId: "long",
                data: { name, lines },
              });
          },
        };
      },
    },
  },
};

export default [
  { ignores: ["node_modules/**", "test-results/**", "playwright-report/**"] },
  {
    files: ["src/**/*.{ts,tsx}", "e2e/**/*.ts", "*.ts"],
    languageOptions: {
      parser: babelParser,
      parserOptions: {
        requireConfigFile: false,
        babelOptions: {
          parserOpts: { plugins: ["jsx"] },
          plugins: [["@babel/plugin-syntax-typescript", { isTSX: true }]],
        },
      },
    },
    plugins: { "react-hooks": hooks, "jsx-a11y": a11y, components },
    rules: {
      "components/bounded-component": "error",
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",
      ...a11y.configs.recommended.rules,
      "jsx-a11y/no-autofocus": ["error", { ignoreNonDOM: true }],
      "jsx-a11y/no-noninteractive-tabindex": ["error", { roles: ["region"] }],
    },
  },
  {
    files: ["scripts/*.mjs", "*.mjs"],
    rules: { ...js.configs.recommended.rules, "no-undef": "off" },
  },
];

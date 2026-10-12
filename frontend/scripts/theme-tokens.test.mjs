import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const rootDir = fileURLToPath(new URL("..", import.meta.url));

test("theme tokens agree between theme.tsx and styles.css without drift", async () => {
  const themeSrc = await readFile(join(rootDir, "src/theme.tsx"), "utf8");
  const stylesSrc = await readFile(join(rootDir, "src/styles.css"), "utf8");
  const indexSrc = await readFile(join(rootDir, "index.html"), "utf8");

  const extractTokens = (constName) => {
    const match = themeSrc.match(
      new RegExp(`export const ${constName} = \\{([\\s\\S]*?)\\};`),
    );
    assert(match, `Could not find ${constName} in theme.tsx`);
    const tokens = {};
    for (const line of match[1].split("\n")) {
      const lineMatch = line.match(
        /^\s*(["']?[\w-]+["']?):\s*["']([^"']+)["']/,
      );
      if (lineMatch) {
        const key = lineMatch[1].replace(/["']/g, "");
        tokens[key] = lineMatch[2];
      }
    }
    return tokens;
  };

  const lightTokens = extractTokens("lightPaletteTokens");
  const darkTokens = extractTokens("darkPaletteTokens");

  const extractCssVars = (blockSelector) => {
    const regex = new RegExp(`${blockSelector}\\s*\\{([\\s\\S]*?)\\}`, "m");
    const match = stylesSrc.match(regex);
    assert(match, `Could not find CSS block for ${blockSelector}`);
    const vars = {};
    for (const line of match[1].split("\n")) {
      const lineMatch = line.match(/--relay-([\w-]+):\s*([^;]+);/);
      if (lineMatch) {
        vars[lineMatch[1]] = lineMatch[2].trim();
      }
    }
    return vars;
  };

  const rootCss = extractCssVars(":root");
  const darkThemeCss = extractCssVars(':root\\[data-theme="dark"\\]');
  const darkMediaCss = extractCssVars(
    ':root:not\\(\\[data-theme="light"\\]\\)',
  );

  for (const [key, val] of Object.entries(lightTokens)) {
    assert.equal(
      rootCss[key],
      val,
      `Light token drift for ${key}: theme.tsx has "${val}", styles.css :root has "${rootCss[key]}"`,
    );
  }

  for (const [key, val] of Object.entries(darkTokens)) {
    assert.equal(
      darkThemeCss[key],
      val,
      `Dark token drift for ${key}: theme.tsx has "${val}", styles.css [data-theme="dark"] has "${darkThemeCss[key]}"`,
    );
    assert.equal(
      darkMediaCss[key],
      val,
      `Dark media query drift for ${key}: theme.tsx has "${val}", styles.css prefers-color-scheme has "${darkMediaCss[key]}"`,
    );
  }

  assert(
    indexSrc.includes('localStorage.getItem("relay-theme-preference")'),
    "index.html must use the shared relay-theme-preference key",
  );
  assert(
    themeSrc.includes(
      'export const THEME_STORAGE_KEY = "relay-theme-preference";',
    ),
    "theme.tsx must export THEME_STORAGE_KEY as relay-theme-preference",
  );
});

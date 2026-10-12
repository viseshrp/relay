import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = fileURLToPath(new URL("..", import.meta.url));

export async function syncThemeTokens({ check = false } = {}) {
  const tokensPath = join(rootDir, "src/tokens.ts");
  const stylesPath = join(rootDir, "src/styles.css");

  const tokensSrc = await readFile(tokensPath, "utf8");
  let stylesSrc = await readFile(stylesPath, "utf8");

  const extractTokens = (constName) => {
    const match = tokensSrc.match(
      new RegExp(`export const ${constName} = \\{([\\s\\S]*?)\\};`),
    );
    if (!match) throw new Error(`Could not find ${constName} in tokens.ts`);
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

  const formatVars = (tokens, indent = "  ") => {
    return Object.entries(tokens)
      .map(([k, v]) => `${indent}--relay-${k}: ${v};`)
      .join("\n");
  };

  // Replace light variables in :root
  const rootRegex =
    /(:root\s*\{[\s\S]*?--relay-text:[^\n]*\n)([\s\S]*?)(\n\s*--relay-space-1:)/;
  if (rootRegex.test(stylesSrc)) {
    const formattedLight = formatVars(lightTokens, "  ");
    stylesSrc = stylesSrc.replace(
      rootRegex,
      `$1${formattedLight.replace(/^ {2}--relay-text: [^\n]*\n/, "")}$3`,
    );
  }

  // Replace dark variables in :root[data-theme="dark"]
  const darkDataRegex =
    /(:root\[data-theme="dark"\]\s*\{\s*\n\s*color-scheme:\s*dark;\n)([\s\S]*?)(\n\})/;
  if (darkDataRegex.test(stylesSrc)) {
    const formattedDark = formatVars(darkTokens, "  ");
    stylesSrc = stylesSrc.replace(darkDataRegex, `$1${formattedDark}$3`);
  }

  // Replace dark variables in media query
  const darkMediaRegex =
    /(:root:not\(\[data-theme="light"\]\)\s*\{\s*\n\s*color-scheme:\s*dark;\n)([\s\S]*?)(\n\s*\})/;
  if (darkMediaRegex.test(stylesSrc)) {
    const formattedDarkMedia = formatVars(darkTokens, "    ");
    stylesSrc = stylesSrc.replace(darkMediaRegex, `$1${formattedDarkMedia}$3`);
  }

  const currentOnDisk = await readFile(stylesPath, "utf8");
  if (check) {
    if (currentOnDisk !== stylesSrc) {
      throw new Error(
        "styles.css theme variables are out of sync with tokens.ts. Run `npm run sync:tokens` to synchronize.",
      );
    }
    return;
  }

  if (currentOnDisk !== stylesSrc) {
    await writeFile(stylesPath, stylesSrc, "utf8");
    console.log("Updated styles.css theme tokens from tokens.ts");
  } else {
    console.log("styles.css theme tokens are already up to date.");
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const isCheck = process.argv.includes("--check");
  await syncThemeTokens({ check: isCheck });
}

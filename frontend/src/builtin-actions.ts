import type { LanguageManifest } from "./workflow-language";

const BUILTIN = /^relay\/([a-z][a-z-]*)@v([1-9][0-9]*)$/;

export function parseBuiltin(
  uses: unknown,
): { name: string; major: number } | null {
  const match = typeof uses === "string" ? BUILTIN.exec(uses) : null;
  return match ? { name: match[1], major: Number(match[2]) } : null;
}

export function isBuiltin(uses: unknown, name: string): boolean {
  return parseBuiltin(uses)?.name === name;
}

/** True for a version that still runs but has a newer current version. */
export function isDeprecatedBuiltin(
  manifest: LanguageManifest,
  uses: unknown,
): boolean {
  return (
    typeof uses === "string" &&
    manifest.builtin_versions[uses]?.status === "deprecated"
  );
}

export function builtinLabel(reference: string): string {
  return parseBuiltin(reference)?.name ?? reference;
}

export function currentBuiltin(
  manifest: LanguageManifest,
  name: string,
): string {
  const entry = Object.entries(manifest.builtin_versions).find(
    ([, version]) => version.name === name && version.status === "current",
  );
  if (!entry) throw new Error(`Unknown built-in action ${name}`);
  return entry[0];
}

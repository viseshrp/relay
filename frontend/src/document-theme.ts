import {
  darkPaletteTokens,
  lightPaletteTokens,
  THEME_STORAGE_KEY,
  type ResolvedTheme,
  type ThemePreference,
} from "./tokens.ts";

export function getStoredThemePreference(): ThemePreference {
  if (typeof window === "undefined") return "system";
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") {
      return stored;
    }
  } catch {
    // Storage unavailable
  }
  return "system";
}

export function setStoredThemePreference(pref: ThemePreference): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(THEME_STORAGE_KEY, pref);
  } catch {
    // Storage unavailable
  }
}

export function getSystemTheme(): ResolvedTheme {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function resolveTheme(pref: ThemePreference): ResolvedTheme {
  return pref === "system" ? getSystemTheme() : pref;
}

export function applyThemeToDocument(
  resolved: ResolvedTheme,
  preference: ThemePreference = "system",
): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.setAttribute("data-theme", resolved);
  root.style.colorScheme = resolved;
  if (resolved === "dark") {
    root.classList.add("dark");
  } else {
    root.classList.remove("dark");
  }

  const themeColors: Record<ResolvedTheme, string> = {
    light: lightPaletteTokens["surface-muted"],
    dark: darkPaletteTokens["surface-muted"],
  };

  const metaLight = document.querySelector<HTMLMetaElement>(
    'meta[name="theme-color"][media*="light"]',
  );
  const metaDark = document.querySelector<HTMLMetaElement>(
    'meta[name="theme-color"][media*="dark"]',
  );
  const genericMetas = document.querySelectorAll<HTMLMetaElement>(
    'meta[name="theme-color"]:not([media])',
  );

  if (preference === "system") {
    if (metaLight) metaLight.content = themeColors.light;
    if (metaDark) metaDark.content = themeColors.dark;
    for (const meta of genericMetas) {
      meta.content = themeColors[resolved];
    }
  } else {
    const metaTags = document.querySelectorAll<HTMLMetaElement>(
      'meta[name="theme-color"]',
    );
    for (const meta of metaTags) {
      meta.content = themeColors[resolved];
    }
  }
}

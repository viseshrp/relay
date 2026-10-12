import assert from "node:assert/strict";
import { test } from "node:test";

class MockMeta {
  constructor(name, media = null, content = "") {
    this.name = name;
    this.media = media;
    this.content = content;
  }
  getAttribute(attr) {
    if (attr === "media") return this.media;
    if (attr === "name") return this.name;
    if (attr === "content") return this.content;
    return null;
  }
}

class MockElement {
  constructor() {
    this.attributes = new Map();
    this.style = {};
    this.classList = new Set();
  }
  setAttribute(name, val) {
    this.attributes.set(name, String(val));
  }
  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }
}

test("document-theme helper resolves theme preferences and applies attributes and theme-color", async () => {
  const metaLight = new MockMeta(
    "theme-color",
    "(prefers-color-scheme: light)",
    "#ffffff",
  );
  const metaDark = new MockMeta(
    "theme-color",
    "(prefers-color-scheme: dark)",
    "#000000",
  );
  const metaGeneric = new MockMeta("theme-color", null, "");

  const metas = [metaLight, metaDark, metaGeneric];
  const rootElement = new MockElement();

  const store = new Map();
  globalThis.localStorage = {
    getItem: (key) => store.get(key) ?? null,
    setItem: (key, val) => store.set(key, String(val)),
    removeItem: (key) => store.delete(key),
  };

  globalThis.document = {
    documentElement: {
      setAttribute: (k, v) => rootElement.setAttribute(k, v),
      getAttribute: (k) => rootElement.getAttribute(k),
      style: rootElement.style,
      classList: {
        add: (c) => rootElement.classList.add(c),
        remove: (c) => rootElement.classList.delete(c),
        contains: (c) => rootElement.classList.has(c),
      },
    },
    querySelectorAll: (selector) => {
      if (selector === 'meta[name="theme-color"]') return metas;
      if (selector === 'meta[name="theme-color"]:not([media])')
        return metas.filter((m) => !m.media);
      return [];
    },
    querySelector: (selector) => {
      if (selector === 'meta[name="theme-color"][media*="light"]')
        return metaLight;
      if (selector === 'meta[name="theme-color"][media*="dark"]')
        return metaDark;
      return null;
    },
  };

  globalThis.window = {
    matchMedia: (query) => ({
      matches: query.includes("dark"),
    }),
  };

  const {
    applyThemeToDocument,
    getStoredThemePreference,
    getSystemTheme,
    resolveTheme,
    setStoredThemePreference,
  } = await import("../src/document-theme.ts");

  // Storage tests
  assert.equal(getStoredThemePreference(), "system");
  setStoredThemePreference("dark");
  assert.equal(getStoredThemePreference(), "dark");
  setStoredThemePreference("light");
  assert.equal(getStoredThemePreference(), "light");

  // Resolution tests
  assert.equal(getSystemTheme(), "dark");
  assert.equal(resolveTheme("light"), "light");
  assert.equal(resolveTheme("dark"), "dark");
  assert.equal(resolveTheme("system"), "dark");

  // applyThemeToDocument in dark mode
  applyThemeToDocument("dark", "dark");
  assert.equal(rootElement.getAttribute("data-theme"), "dark");
  assert.equal(rootElement.style.colorScheme, "dark");
  assert(rootElement.classList.has("dark"));
  assert.equal(metaLight.content, "#0f172a");
  assert.equal(metaDark.content, "#0f172a");
  assert.equal(metaGeneric.content, "#0f172a");

  // applyThemeToDocument in light mode
  applyThemeToDocument("light", "light");
  assert.equal(rootElement.getAttribute("data-theme"), "light");
  assert.equal(rootElement.style.colorScheme, "light");
  assert(!rootElement.classList.has("dark"));
  assert.equal(metaLight.content, "#f4f6fb");
  assert.equal(metaDark.content, "#f4f6fb");
  assert.equal(metaGeneric.content, "#f4f6fb");

  // applyThemeToDocument in system mode
  applyThemeToDocument("dark", "system");
  assert.equal(metaLight.content, "#f4f6fb");
  assert.equal(metaDark.content, "#0f172a");
  assert.equal(metaGeneric.content, "#0f172a");
});

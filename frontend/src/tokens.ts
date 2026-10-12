export const terminalColors = [
  "#cbd5e1",
  "#f87171",
  "#86efac",
  "#fde047",
  "#93c5fd",
  "#d8b4fe",
  "#67e8f9",
  "#ffffff",
];

export const lightPaletteTokens = {
  text: "#17223b",
  "text-secondary": "#526078",
  "text-on-dark": "#f1f5f9",
  "muted-on-dark": "#94a3b8",
  "danger-on-dark": "#fca5a5",
  primary: "#3156d3",
  "primary-strong": "#233d96",
  "primary-contrast": "#ffffff",
  surface: "#ffffff",
  "surface-muted": "#f4f6fb",
  "surface-hover": "#eef2ff",
  "surface-elevated": "#ffffff",
  border: "#c4cddd",
  "border-subtle": "#dce1ec",
  "border-input": "#7b879c",
  focus: "#3156d3",
  success: "#176b35",
  "success-surface": "#eefbf3",
  danger: "#b42324",
  "danger-surface": "#fff1f1",
  warning: "#9a6700",
  "warning-surface": "#fff8e5",
  disabled: "#67738b",
  terminal: "#0f172a",
  shadow: "#27334b12",
  selection: "#3156d308",
  "focus-glow": "#3156d333",
  overlay: "#ffffffb3",
};

export const darkPaletteTokens = {
  text: "#f1f5f9",
  "text-secondary": "#94a3b8",
  "text-on-dark": "#f1f5f9",
  "muted-on-dark": "#94a3b8",
  "danger-on-dark": "#fca5a5",
  primary: "#93c5fd",
  "primary-strong": "#bfdbfe",
  "primary-contrast": "#0f172a",
  surface: "#1e293b",
  "surface-muted": "#0f172a",
  "surface-hover": "#243147",
  "surface-elevated": "#273449",
  border: "#334155",
  "border-subtle": "#334155",
  "border-input": "#748299",
  focus: "#93c5fd",
  success: "#86efac",
  "success-surface": "rgba(134, 239, 172, 0.14)",
  danger: "#f87171",
  "danger-surface": "rgba(248, 113, 113, 0.14)",
  warning: "#fde047",
  "warning-surface": "rgba(253, 224, 71, 0.14)",
  disabled: "#64748b",
  terminal: "#0f172a",
  shadow: "rgba(0, 0, 0, 0.5)",
  selection: "rgba(147, 197, 253, 0.2)",
  "focus-glow": "rgba(147, 197, 253, 0.35)",
  overlay: "rgba(15, 23, 42, 0.8)",
};

export const paletteTokens = lightPaletteTokens;

export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "relay-theme-preference";

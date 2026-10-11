import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorView } from "@codemirror/view";
import { tags as t } from "@lezer/highlight";
import { createTheme, type Theme } from "@mui/material/styles";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { CssBaseline, ThemeProvider } from "@mui/material";

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
  surface: "#ffffff",
  "surface-muted": "#f4f6fb",
  "surface-hover": "#eef2ff",
  "surface-elevated": "#ffffff",
  border: "#c4cddd",
  "border-subtle": "#dce1ec",
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
  surface: "#1e293b",
  "surface-muted": "#0f172a",
  "surface-hover": "#243147",
  "surface-elevated": "#1e293b",
  border: "#334155",
  "border-subtle": "#1e293b",
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

export function createRelayTheme(mode: "light" | "dark"): Theme {
  const tokens = mode === "dark" ? darkPaletteTokens : lightPaletteTokens;
  return createTheme({
    breakpoints: { values: { xs: 0, sm: 480, md: 768, lg: 1024, xl: 1440 } },
    palette: {
      mode,
      primary: {
        main: tokens.primary,
        ...(mode === "dark" ? { contrastText: "#0f172a" } : {}),
      },
      secondary: { main: mode === "dark" ? "#d8b4fe" : "#6b4eff" },
      text: {
        primary: tokens.text,
        secondary: tokens["text-secondary"],
      },
      success: { main: tokens.success },
      error: { main: tokens.danger },
      warning: { main: tokens.warning },
      divider: tokens["border-subtle"],
      background: {
        default: mode === "dark" ? "#0f172a" : "#f4f6fb",
        paper: tokens.surface,
      },
    },
    spacing: 4,
    shape: { borderRadius: 7 },
    typography: {
      fontFamily:
        'Inter, "Inter Fallback", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif',
      fontSize: 14,
      caption: { fontSize: ".75rem" },
      h5: { fontWeight: 600, fontSize: "1.375rem" },
      h6: { fontWeight: 600, fontSize: "1rem" },
      body1: { fontSize: ".875rem" },
      body2: { fontSize: ".8125rem" },
      button: { fontWeight: 600, textTransform: "none" },
    },
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          ":root": {
            colorScheme: mode,
            ...Object.fromEntries(
              Object.entries(tokens).map(([name, value]) => [
                `--relay-${name}`,
                value,
              ]),
            ),
            ...Object.fromEntries(
              [4, 8, 12, 16, 20, 24, 32, 40].map((size) => [
                `--relay-space-${size / 4}`,
                `${size}px`,
              ]),
            ),
          },
        },
      },
      MuiTypography: {
        defaultProps: {
          variantMapping: {
            h1: "h1",
            h2: "h2",
            h3: "h2",
            h4: "h2",
            h5: "h2",
            h6: "h2",
            subtitle1: "p",
            subtitle2: "p",
            body1: "p",
            body2: "p",
          },
        },
      },
      MuiTooltip: {
        defaultProps: {
          enterDelay: 350,
          enterNextDelay: 0,
          disableTouchListener: true,
        },
      },
      MuiButton: {
        defaultProps: { disableElevation: true, size: "small" },
        styleOverrides: {
          root: {
            minHeight: 32,
            paddingInline: 12,
            "@media (pointer: coarse)": { minHeight: 44 },
          },
        },
      },
      MuiTextField: { defaultProps: { size: "small" } },
      MuiFormControl: { defaultProps: { size: "small" } },
      MuiSelect: { defaultProps: { size: "small" } },
      MuiInputBase: { styleOverrides: { root: { fontSize: ".875rem" } } },
      MuiOutlinedInput: {
        styleOverrides: {
          input: { padding: "8px 12px" },
          multiline: { padding: "8px 12px" },
          root: {
            "& .MuiOutlinedInput-notchedOutline": {
              borderColor: tokens["border-subtle"],
            },
            "&:hover .MuiOutlinedInput-notchedOutline": {
              borderColor: tokens.border,
            },
            "&.Mui-focused .MuiOutlinedInput-notchedOutline": {
              borderColor: tokens.primary,
            },
          },
        },
      },
      MuiFormHelperText: {
        styleOverrides: {
          root: {
            marginLeft: 0,
            marginRight: 0,
            lineHeight: 1.5,
            "&.Mui-disabled": { color: tokens["text-secondary"] },
          },
        },
      },
      MuiSwitch: { defaultProps: { size: "small" } },
      MuiCheckbox: { defaultProps: { size: "small" } },
      MuiIconButton: {
        defaultProps: { size: "small" },
        styleOverrides: {
          root: {
            "&:not(.Mui-disabled)": { color: tokens.primary },
            "@media (pointer: coarse)": { minWidth: 44, minHeight: 44 },
          },
        },
      },
      MuiMenuItem: {
        styleOverrides: {
          root: {
            minHeight: 36,
            whiteSpace: "normal",
            overflowWrap: "anywhere",
            gap: 8,
            "&:hover": {
              backgroundColor: tokens["surface-hover"],
            },
            "&.Mui-selected": {
              backgroundColor: tokens["surface-hover"],
            },
            "@media (pointer: coarse)": { minHeight: 44 },
          },
        },
      },
      MuiMenu: {
        styleOverrides: {
          list: {
            maxHeight: "min(304px, calc(100dvh - 48px))",
            overflowY: "auto",
          },
          paper: {
            maxWidth: "calc(100vw - 32px)",
            maxHeight: "min(320px, calc(100dvh - 32px))",
            border: `1px solid ${tokens["border-subtle"]}`,
            backgroundColor: tokens["surface-elevated"],
          },
        },
      },
      MuiAccordionSummary: {
        styleOverrides: {
          root: { minHeight: 42, "&.Mui-expanded": { minHeight: 42 } },
          content: { marginBlock: 10, "&.Mui-expanded": { marginBlock: 10 } },
        },
      },
      MuiTab: {
        defaultProps: { disableRipple: true },
        styleOverrides: {
          root: {
            minHeight: 40,
            padding: "10px 14px",
            minWidth: 0,
            color: tokens.primary,
            backgroundColor: tokens.surface,
            opacity: 1,
            "&.Mui-selected": {
              color: tokens["primary-strong"],
              fontWeight: 600,
              backgroundColor: tokens["surface-hover"],
            },
            "&.Mui-focusVisible": {
              color: tokens["primary-strong"],
              backgroundColor: tokens["surface-hover"],
            },
            "&.Mui-disabled": {
              color:
                mode === "dark"
                  ? "rgba(255, 255, 255, 0.3)"
                  : "rgba(0, 0, 0, 0.38)",
            },
          },
        },
      },
      MuiListItemButton: {
        styleOverrides: {
          root: {
            "&:not(.Mui-disabled)": { color: tokens.primary },
            "&.Mui-selected": {
              color: tokens["primary-strong"],
              backgroundColor: tokens["surface-hover"],
            },
            "&:hover": {
              backgroundColor: tokens["surface-hover"],
            },
          },
        },
      },
      MuiTabs: { styleOverrides: { root: { minHeight: 40 } } },
      MuiPaper: {
        styleOverrides: {
          root: { backgroundImage: "none" },
          outlined: { borderColor: tokens["border-subtle"] },
        },
      },
    },
  });
}

export const relayTheme = createRelayTheme("light");

export const relayDarkHighlightStyle = HighlightStyle.define([
  { tag: t.keyword, color: "#93c5fd" },
  {
    tag: [t.name, t.deleted, t.character, t.propertyName, t.macroName],
    color: "#e2e8f0",
  },
  { tag: [t.function(t.variableName), t.labelName], color: "#67e8f9" },
  { tag: [t.color, t.constant(t.name), t.standard(t.name)], color: "#fde047" },
  { tag: [t.definition(t.name), t.separator], color: "#cbd5e1" },
  {
    tag: [
      t.typeName,
      t.className,
      t.number,
      t.changed,
      t.annotation,
      t.modifier,
      t.self,
      t.namespace,
    ],
    color: "#fca5a5",
  },
  {
    tag: [
      t.operator,
      t.operatorKeyword,
      t.url,
      t.escape,
      t.regexp,
      t.link,
      t.special(t.string),
    ],
    color: "#d8b4fe",
  },
  { tag: [t.meta, t.comment], color: "#94a3b8", fontStyle: "italic" },
  { tag: t.strong, fontWeight: "bold" },
  { tag: t.emphasis, fontStyle: "italic" },
  { tag: t.strikethrough, textDecoration: "line-through" },
  { tag: t.link, color: "#60a5fa", textDecoration: "underline" },
  { tag: t.heading, fontWeight: "bold", color: "#93c5fd" },
  { tag: [t.atom, t.bool, t.special(t.variableName)], color: "#fde047" },
  { tag: [t.processingInstruction, t.string, t.inserted], color: "#86efac" },
  { tag: t.invalid, color: "#f87171" },
]);

export function createCodeMirrorTheme(isDark: boolean) {
  return [
    EditorView.theme(
      {
        "&": {
          height: "100%",
          backgroundColor: "var(--relay-surface)",
          color: "var(--relay-text)",
        },
        ".cm-scroller": {
          overflow: "auto",
          fontFamily: '"JetBrains Mono", monospace',
        },
        ".cm-gutters": {
          backgroundColor: "var(--relay-surface-muted)",
          color: "var(--relay-text-secondary)",
          borderRight: "1px solid var(--relay-border-subtle)",
        },
        ".cm-activeLineGutter": {
          backgroundColor: "var(--relay-surface-hover)",
          color: "var(--relay-text)",
        },
        ".cm-activeLine": {
          backgroundColor: "var(--relay-surface-hover)",
        },
        ".cm-cursor": {
          borderLeftColor: "var(--relay-text)",
        },
        ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": {
          backgroundColor: "var(--relay-selection) !important",
        },
      },
      { dark: isDark },
    ),
    ...(isDark ? [syntaxHighlighting(relayDarkHighlightStyle)] : []),
  ];
}

export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "relay-theme-preference";

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

export function applyThemeToDocument(resolved: ResolvedTheme): void {
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
    light: "#f4f6fb",
    dark: "#0f172a",
  };

  const metaTags = document.querySelectorAll<HTMLMetaElement>(
    'meta[name="theme-color"]',
  );
  let hasGenericMeta = false;
  for (const meta of metaTags) {
    if (!meta.media) {
      meta.content = themeColors[resolved];
      hasGenericMeta = true;
    }
  }
  if (!hasGenericMeta) {
    const activeMeta = document.createElement("meta");
    activeMeta.name = "theme-color";
    activeMeta.content = themeColors[resolved];
    document.head.appendChild(activeMeta);
  }
}

interface ThemeContextValue {
  preference: ThemePreference;
  resolvedTheme: ResolvedTheme;
  setPreference: (pref: ThemePreference) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  preference: "system",
  resolvedTheme: "light",
  setPreference: () => {},
  toggleTheme: () => {},
});

export function useThemeMode(): ThemeContextValue {
  return useContext(ThemeContext);
}

export function RelayThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPrefState] = useState<ThemePreference>(() =>
    getStoredThemePreference(),
  );
  const [systemTheme, setSystemTheme] = useState<ResolvedTheme>(() =>
    getSystemTheme(),
  );

  const resolvedTheme: ResolvedTheme =
    preference === "system" ? systemTheme : preference;

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = (event: MediaQueryListEvent) => {
      setSystemTheme(event.matches ? "dark" : "light");
    };
    media.addEventListener("change", handleChange);
    return () => media.removeEventListener("change", handleChange);
  }, []);

  useEffect(() => {
    applyThemeToDocument(resolvedTheme);
  }, [resolvedTheme]);

  const setPreference = useCallback((newPref: ThemePreference) => {
    setPrefState(newPref);
    setStoredThemePreference(newPref);
  }, []);

  const toggleTheme = useCallback(() => {
    setPreference(resolvedTheme === "dark" ? "light" : "dark");
  }, [resolvedTheme, setPreference]);

  const theme = useMemo(() => createRelayTheme(resolvedTheme), [resolvedTheme]);

  const contextValue = useMemo<ThemeContextValue>(
    () => ({
      preference,
      resolvedTheme,
      setPreference,
      toggleTheme,
    }),
    [preference, resolvedTheme, setPreference, toggleTheme],
  );

  return (
    <ThemeContext.Provider value={contextValue}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </ThemeProvider>
    </ThemeContext.Provider>
  );
}

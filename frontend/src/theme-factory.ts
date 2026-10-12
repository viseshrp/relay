import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorView } from "@codemirror/view";
import { tags as t } from "@lezer/highlight";
import { createTheme, type Theme } from "@mui/material/styles";
import { darkPaletteTokens, lightPaletteTokens } from "./tokens.ts";

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
        styleOverrides: {
          tooltip: {
            backgroundColor: tokens["surface-elevated"],
            color: tokens.text,
            border: `1px solid ${tokens.border}`,
            boxShadow: `0 4px 12px ${tokens.shadow}`,
            fontSize: ".75rem",
          },
        },
      },
      MuiDialog: {
        styleOverrides: {
          paper: {
            backgroundColor: tokens["surface-elevated"],
            border: `1px solid ${tokens.border}`,
            backgroundImage: "none",
          },
        },
      },
      MuiPopover: {
        styleOverrides: {
          paper: {
            backgroundColor: tokens["surface-elevated"],
            border: `1px solid ${tokens.border}`,
            backgroundImage: "none",
          },
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
              borderColor: tokens["border-input"],
            },
            "&:hover .MuiOutlinedInput-notchedOutline": {
              borderColor: tokens.primary,
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
            border: `1px solid ${tokens.border}`,
            backgroundColor: tokens["surface-elevated"],
            backgroundImage: "none",
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
          outlined: { borderColor: tokens.border },
        },
      },
    },
  });
}

export const relayTheme = createRelayTheme("light");

export const relayLightHighlightStyle = HighlightStyle.define([
  { tag: t.keyword, color: "#1d4ed8" },
  { tag: t.propertyName, color: "#2563eb", fontWeight: "600" },
  {
    tag: [t.name, t.character],
    color: "#1e293b",
  },
  { tag: [t.function(t.variableName), t.labelName], color: "#0284c7" },
  { tag: [t.color, t.constant(t.name), t.standard(t.name)], color: "#92400e" },
  { tag: [t.definition(t.name), t.separator], color: "#475569" },
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
    color: "#7c3aed",
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
      t.macroName,
    ],
    color: "#92400e",
  },
  { tag: [t.meta, t.comment], color: "#64748b", fontStyle: "italic" },
  { tag: t.strong, fontWeight: "bold" },
  { tag: t.emphasis, fontStyle: "italic" },
  { tag: t.strikethrough, textDecoration: "line-through" },
  { tag: t.link, color: "#2563eb", textDecoration: "underline" },
  { tag: t.heading, fontWeight: "bold", color: "#1d4ed8" },
  { tag: [t.atom, t.bool, t.special(t.variableName)], color: "#7c3aed" },
  { tag: [t.processingInstruction, t.string, t.inserted], color: "#0d766e" },
  { tag: t.invalid, color: "#b42324" },
]);

export const relayDarkHighlightStyle = HighlightStyle.define([
  { tag: t.keyword, color: "#93c5fd" },
  { tag: t.propertyName, color: "#93c5fd", fontWeight: "600" },
  {
    tag: [t.name, t.character],
    color: "#f1f5f9",
  },
  { tag: [t.function(t.variableName), t.labelName], color: "#67e8f9" },
  { tag: [t.color, t.constant(t.name), t.standard(t.name)], color: "#fde047" },
  { tag: [t.definition(t.name), t.separator], color: "#94a3b8" },
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
    color: "#fde047",
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
      t.macroName,
    ],
    color: "#f472b6",
  },
  { tag: [t.meta, t.comment], color: "#94a3b8", fontStyle: "italic" },
  { tag: t.strong, fontWeight: "bold" },
  { tag: t.emphasis, fontStyle: "italic" },
  { tag: t.strikethrough, textDecoration: "line-through" },
  { tag: t.link, color: "#93c5fd", textDecoration: "underline" },
  { tag: t.heading, fontWeight: "bold", color: "#93c5fd" },
  { tag: [t.atom, t.bool, t.special(t.variableName)], color: "#fde047" },
  { tag: [t.processingInstruction, t.string, t.inserted], color: "#5eead4" },
  { tag: t.invalid, color: "#f87171" },
]);

export function createCodeMirrorTheme(isDark: boolean) {
  return [
    syntaxHighlighting(
      isDark ? relayDarkHighlightStyle : relayLightHighlightStyle,
    ),
    EditorView.theme(
      {
        "&": {
          color: "var(--relay-text)",
          backgroundColor: "var(--relay-surface)",
          fontSize: "13px",
        },
        ".cm-content": {
          caretColor: "var(--relay-text)",
          padding: "8px 0",
        },
        ".cm-line": {
          lineHeight: "1.6",
          padding: "0 8px",
        },
        "&.cm-focused .cm-cursor": {
          borderLeftColor: "var(--relay-text)",
        },
        "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection":
          {
            backgroundColor: "var(--relay-selection)",
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
  ];
}

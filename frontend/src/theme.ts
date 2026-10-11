import { createTheme } from "@mui/material/styles";

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

export const paletteTokens = {
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

export const relayTheme = createTheme({
  breakpoints: { values: { xs: 0, sm: 480, md: 768, lg: 1024, xl: 1440 } },
  palette: {
    mode: "light",
    primary: { main: "#3156d3" },
    secondary: { main: "#6b4eff" },
    text: {
      primary: paletteTokens.text,
      secondary: paletteTokens["text-secondary"],
    },
    success: { main: paletteTokens.success },
    error: { main: paletteTokens.danger },
    warning: { main: paletteTokens.warning },
    divider: paletteTokens["border-subtle"],
    background: { default: "#f4f6fb", paper: "#ffffff" },
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
          ...Object.fromEntries(
            Object.entries(paletteTokens).map(([name, value]) => [
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
      },
    },
    MuiFormHelperText: {
      styleOverrides: {
        root: {
          marginLeft: 0,
          marginRight: 0,
          lineHeight: 1.5,
          "&.Mui-disabled": { color: paletteTokens["text-secondary"] },
        },
      },
    },
    MuiSwitch: { defaultProps: { size: "small" } },
    MuiCheckbox: { defaultProps: { size: "small" } },
    MuiIconButton: {
      defaultProps: { size: "small" },
      styleOverrides: {
        root: {
          "&:not(.Mui-disabled)": { color: "#3156d3" },
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
          color: "#3156d3",
          backgroundColor: paletteTokens.surface,
          opacity: 1,
          "&.Mui-selected": {
            color: "#233d96",
            fontWeight: 600,
            backgroundColor: "#eef2ff",
          },
          "&.Mui-focusVisible": {
            color: paletteTokens["primary-strong"],
            backgroundColor: "#eef2ff",
          },
          "&.Mui-disabled": { color: "rgba(0, 0, 0, 0.38)" },
        },
      },
    },
    MuiListItemButton: {
      styleOverrides: {
        root: {
          "&:not(.Mui-disabled)": { color: "#3156d3" },
          "&.Mui-selected": { color: "#233d96" },
        },
      },
    },
    MuiTabs: { styleOverrides: { root: { minHeight: 40 } } },
    MuiPaper: { styleOverrides: { root: { backgroundImage: "none" } } },
  },
});

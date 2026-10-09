import { createTheme } from "@mui/material/styles";

export const relayTheme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#3156d3" },
    secondary: { main: "#6b4eff" },
    background: { default: "#f4f6fb", paper: "#ffffff" },
  },
  shape: { borderRadius: 7 },
  typography: {
    fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif',
    fontSize: 14,
    h5: { fontWeight: 720, fontSize: "1.375rem" },
    h6: { fontWeight: 680, fontSize: "1rem" },
    body1: { fontSize: ".875rem" },
    body2: { fontSize: ".8125rem" },
    button: { fontWeight: 650, textTransform: "none" },
  },
  components: {
    MuiButton: { defaultProps: { disableElevation: true, size: "small" }, styleOverrides: { root: { minHeight: 32, paddingInline: 12, "@media (pointer: coarse)": { minHeight: 44 } } } },
    MuiTextField: { defaultProps: { size: "small" } },
    MuiFormControl: { defaultProps: { size: "small" } },
    MuiSelect: { defaultProps: { size: "small" } },
    MuiInputBase: { styleOverrides: { root: { fontSize: ".875rem" } } },
    MuiOutlinedInput: { styleOverrides: { input: { padding: "8px 12px" }, multiline: { padding: "8px 12px" } } },
    MuiFormHelperText: { styleOverrides: { root: { marginLeft: 0, marginRight: 0, lineHeight: 1.5 } } },
    MuiSwitch: { defaultProps: { size: "small" } },
    MuiCheckbox: { defaultProps: { size: "small" } },
    MuiIconButton: { defaultProps: { size: "small" }, styleOverrides: { root: { "&:not(.Mui-disabled)": { color: "#3156d3" }, "@media (pointer: coarse)": { minWidth: 44, minHeight: 44 } } } },
    MuiMenuItem: { styleOverrides: { root: { minHeight: 36, whiteSpace: "normal", overflowWrap: "anywhere", gap: 8, "@media (pointer: coarse)": { minHeight: 44 } } } },
    MuiMenu: { styleOverrides: { list: { maxHeight: "min(304px, calc(100dvh - 48px))", overflowY: "auto" }, paper: { maxWidth: "calc(100vw - 32px)", maxHeight: "min(320px, calc(100dvh - 32px))" } } },
    MuiAccordionSummary: { styleOverrides: { root: { minHeight: 42, "&.Mui-expanded": { minHeight: 42 } }, content: { marginBlock: 10, "&.Mui-expanded": { marginBlock: 10 } } } },
    MuiTab: { styleOverrides: { root: { minHeight: 40, padding: "10px 14px", minWidth: 0, color: "#3156d3", opacity: 1, "&.Mui-selected": { color: "#233d96", fontWeight: 750, backgroundColor: "#eef2ff" }, "&.Mui-disabled": { color: "rgba(0, 0, 0, 0.38)" } } } },
    MuiListItemButton: { styleOverrides: { root: { "&:not(.Mui-disabled)": { color: "#3156d3" }, "&.Mui-selected": { color: "#233d96" } } } },
    MuiTabs: { styleOverrides: { root: { minHeight: 40 } } },
    MuiPaper: { styleOverrides: { root: { backgroundImage: "none" } } },
  },
});

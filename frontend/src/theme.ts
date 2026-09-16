import { createTheme } from "@mui/material/styles";

export const relayTheme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#3156d3" },
    secondary: { main: "#6b4eff" },
    background: { default: "#f4f6fb", paper: "#ffffff" },
  },
  shape: { borderRadius: 10 },
  typography: {
    fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif',
    h5: { fontWeight: 720 },
    h6: { fontWeight: 680 },
    button: { fontWeight: 650, textTransform: "none" },
  },
  components: {
    MuiButton: { defaultProps: { disableElevation: true } },
    MuiPaper: { styleOverrides: { root: { backgroundImage: "none" } } },
  },
});

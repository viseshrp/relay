import "@xyflow/react/dist/style.css";
import "./styles.css";

import { CssBaseline, ThemeProvider } from "@mui/material";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { relayTheme } from "./theme";

const root = document.getElementById("root");
if (root === null) throw new Error("Relay could not find its browser application root.");

createRoot(root).render(
  <StrictMode>
    <ThemeProvider theme={relayTheme}>
      <CssBaseline />
      <App />
    </ThemeProvider>
  </StrictMode>,
);

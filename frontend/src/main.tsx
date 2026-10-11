import "./fonts.css";
import "@xyflow/react/dist/style.css";
import "./styles.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { RelayThemeProvider } from "./theme";

const root = document.getElementById("root");
if (root === null)
  throw new Error("Relay could not find its browser application root.");

createRoot(root).render(
  <StrictMode>
    <RelayThemeProvider>
      <App />
    </RelayThemeProvider>
  </StrictMode>,
);

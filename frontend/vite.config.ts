import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  build: {
    outDir: "../relay/static",
    emptyOutDir: true,
    sourcemap: mode === "development" ? "hidden" : false,
    manifest: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return;
          if (/\/(react|react-dom|scheduler)\//.test(id)) return "react";
          if (id.includes("/@mui/") || id.includes("/@emotion/")) return "mui";
          if (id.includes("/@xyflow/")) return "graph";
          if (id.includes("/@codemirror/") || id.includes("/codemirror/"))
            return "editor";
        },
      },
    },
  },
}));

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../relay/static",
    emptyOutDir: true,
    sourcemap: true,
  },
});

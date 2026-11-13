/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The colour tokens, the font and other files both UIs share live in app/static until the old pages are retired.
const staticDir = fileURLToPath(new URL("../app/static", import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@static": staticDir } },
  server: {
    fs: { allow: [".", staticDir] },
    // Development only: the API runs on `uv run fastapi dev`; in production it is its own address (VITE_API_URL).
    proxy: { "/api": "http://localhost:8000" },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["src/test/setup.ts"],
  },
});

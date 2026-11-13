/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

// The colour tokens, the font and other files both UIs share live in app/static until the old pages are retired.
const staticDir = fileURLToPath(new URL("../app/static", import.meta.url));

export default defineConfig({
  plugins: [
    react(),
    // Installable to the home screen. The service worker caches the app's own files only, never /api: finode works
    // online only and never keeps your books on the device.
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.svg", "apple-touch-icon.png"],
      manifest: {
        name: "finode",
        short_name: "finode",
        start_url: "/",
        scope: "/",
        display: "standalone",
        background_color: "#ecf0ec",
        theme_color: "#ecf0ec",
        icons: [
          { src: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" },
          { src: "/favicon.svg", sizes: "any", type: "image/svg+xml" },
        ],
      },
      workbox: { navigateFallbackDenylist: [/^\/api\//], globPatterns: ["**/*.{js,css,html,svg,png,woff2}"] },
    }),
  ],
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

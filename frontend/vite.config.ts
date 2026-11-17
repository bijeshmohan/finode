/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    // Installable to the home screen. The service worker caches the app's own files only, never /api: finode works
    // online only and never keeps your books on the device.
    VitePWA({
      // A new version waits until the page is left (src/app/update.ts) rather than reloading an open screen.
      registerType: "prompt",
      // Registered in main.tsx, where a failure is caught: the app works online without it.
      injectRegister: false,
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
      workbox: {
        // Every path Traefik sends to the API (compose.yaml; backend/tests/guards/test_compose_routes.py holds the two together).
        navigateFallbackDenylist: [/^\/(api|mcp)(\/|$)/, /^\/\.well-known\//, /^\/(docs|redoc|openapi\.json)$/],
        globPatterns: ["**/*.{js,css,html,svg,png,woff2}"],
      },
    }),
  ],
  server: {
    // Development only: the API runs on `uv run fastapi dev`; in production Traefik sends /api to it on the same address.
    proxy: { "/api": "http://localhost:8000" },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["src/test/setup.ts"],
  },
});

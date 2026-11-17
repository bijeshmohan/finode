// The colour tokens: every colour the app uses (frontend/src/styles/tokens.test.ts and the dark-mode parity guard check them).
import "./styles/tokens.css";
import "./styles/base.css";

import { StrictMode } from "react";
import { registerSW } from "virtual:pwa-register";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { updateWhenHidden } from "./app/update";

const root = document.getElementById("root");
if (!root) throw new Error("index.html has no #root element");

// Installable to the home screen. A registration that fails (the page navigated away meanwhile, an old browser) is
// harmless: the app works online without it. A new version waits for the page to be left (backend/finode/update.ts), then the
// service worker takes over and the page reloads.
const updateSW = registerSW({
  immediate: true,
  onNeedRefresh: () => {
    updateWhenHidden(() => void updateSW(true));
  },
  onRegisterError: () => undefined,
});

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

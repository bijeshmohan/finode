// The colour tokens are shared with the web pages (app/static/tokens.css) until they are retired.
import "@static/tokens.css";
import "./styles/base.css";

import { StrictMode } from "react";
import { registerSW } from "virtual:pwa-register";
import { createRoot } from "react-dom/client";

import { App } from "./App";

const root = document.getElementById("root");
if (!root) throw new Error("index.html has no #root element");

// Installable to the home screen. A registration that fails (the page navigated away meanwhile, an old browser) is
// harmless: the app works online without it.
void registerSW({
  immediate: true,
  onRegisterError: () => undefined,
});

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

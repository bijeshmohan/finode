import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

// Vitest runs from frontend/.
const css = readFileSync("src/styles/base.css", "utf8");

describe("base.css", () => {
  it("uses the shared Anek Latin font", () => {
    expect(css).toContain('font-family: "Anek Latin"');
    expect(css).toContain("@static/fonts/anek-latin.woff2");
  });

  it("turns motion off for people who ask for less", () => {
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
  });

  it("takes its colours from the tokens only", () => {
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
  });
});

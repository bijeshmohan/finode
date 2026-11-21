import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

// Vitest runs from frontend/.
const css = readFileSync("src/styles/base.css", "utf8");

describe("base.css", () => {
  it("uses the app's own IBM Plex faces: Sans for text, Mono for the figures", () => {
    expect(css).toContain('font-family: "IBM Plex Sans"');
    expect(css).toContain('font-family: "IBM Plex Mono"');
    for (const file of ["ibm-plex-sans", "ibm-plex-mono-medium", "ibm-plex-mono-semibold"]) {
      expect(css).toContain(`./fonts/${file}.woff2`);
    }
    expect(css).toContain("var(--font-sans)");
  });

  it("draws the rupee sign from the app's own font, not the phone's", () => {
    expect(css).toContain("U+20B9");
  });

  it("turns motion off for people who ask for less", () => {
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
  });

  it("takes its colours from the tokens only", () => {
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
  });
});

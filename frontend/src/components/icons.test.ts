import { existsSync } from "node:fs";

import { describe, expect, it } from "vitest";

import icons from "./icons.json";

// icons.json is the icons' one source: components/Icon draws them, and TypeScript refuses a name it does not hold. The
// markup is put into the page as it is, so it must be plain SVG drawing only. Vitest runs from frontend/.
const DRAWING = new Set(["path", "circle", "rect", "line", "polyline", "polygon", "ellipse", "g"]);
const entries = Object.entries(icons as Record<string, string>);

describe("icons.json", () => {
  it("holds plain SVG drawing only", () => {
    expect(entries.length).toBeGreaterThan(0);
    for (const [name, markup] of entries) {
      const tags = [...markup.matchAll(/<\s*([a-zA-Z]+)/g)].map((m) => m[1] ?? "");
      expect(tags.length, name).toBeGreaterThan(0);
      expect(
        tags.filter((tag) => !DRAWING.has(tag)),
        name,
      ).toEqual([]);
      expect(markup, name).not.toMatch(/\son[a-z]+\s*=|javascript:|<\s*script/i);
    }
  });

  it("has the icons the layout and the home screen use, and the app's own icons are there", () => {
    for (const name of ["home", "budget", "plus", "bell", "gear", "back", "close", "trash", "robot"]) {
      expect(icons, name).toHaveProperty(name);
    }
    for (const asset of ["favicon.svg", "apple-touch-icon.png"])
      expect(existsSync(`public/${asset}`), asset).toBe(true);
  });
});

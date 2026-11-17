import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// Vitest runs from frontend/. Guards on the look that live in the CSS: colours defined once, in tokens.css, with the
// same tokens in both dark blocks; the quiet greys readable; one bar height; no chart colours; and no rule that blanks
// every checkbox and radio on iOS.
const tokensCss = readFileSync("src/styles/tokens.css", "utf8");

function sheets(dir: string): [string, string][] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry): [string, string][] => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sheets(path);
    return entry.name.endsWith(".css") && entry.name !== "tokens.css" ? [[path, readFileSync(path, "utf8")]] : [];
  });
}
const otherSheets = sheets("src");

/** The body of the first block that opens with `opening` (without nested blocks). */
function block(css: string, opening: string): string {
  const start = css.indexOf(opening);
  if (start < 0) throw new Error(`${opening} not found`);
  const open = css.indexOf("{", start + opening.length - 1);
  return css.slice(open + 1, css.indexOf("}", open));
}

function tokens(body: string): Map<string, string> {
  return new Map([...body.matchAll(/--([a-z0-9-]+):\s*([^;]+);/g)].map((m) => [m[1] ?? "", (m[2] ?? "").trim()]));
}

const light = tokens(block(tokensCss, ":root {"));
const autoDark = tokens(block(tokensCss, ':root:not([data-theme="light"]) {'));
const chosenDark = tokens(block(tokensCss, ':root[data-theme="dark"] {'));

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function ratio(a: string | undefined, b: string | undefined): number {
  if (!a || !b) throw new Error("missing colour");
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (high + 0.05) / (low + 0.05);
}

function rule(sheet: string, selector: string): string {
  const start = sheet.indexOf(`\n${selector} {`);
  if (start < 0) throw new Error(`${selector} not found`);
  return sheet.slice(start, sheet.indexOf("}", start));
}

describe("tokens.css", () => {
  it("holds the light block and both dark blocks", () => {
    expect(tokensCss).toContain("@media (prefers-color-scheme: dark)");
    expect(light.size).toBeGreaterThan(0);
  });

  it("defines the same tokens in both dark blocks", () => {
    expect(chosenDark).toEqual(autoDark);
  });

  it("is the only place the colours are defined", () => {
    for (const [path, sheet] of otherSheets) {
      for (const token of ["--bg:", "--surface:", "--accent:", "--text:", "--muted:"]) {
        expect(sheet, `${token} in ${path}: it belongs in tokens.css`).not.toContain(token);
      }
    }
  });

  it("keeps the quiet grey readable (4.5 : 1) on the page and the tiles in both themes", () => {
    for (const [name, theme] of [
      ["light", light],
      ["dark", chosenDark],
    ] as const) {
      for (const ground of ["bg", "surface"]) {
        expect(ratio(theme.get("muted"), theme.get(ground)), `${name}: muted on ${ground}`).toBeGreaterThanOrEqual(4.5);
      }
    }
    expect(ratio(light.get("muted"), light.get("surface-2")), "also on a grey chip").toBeGreaterThanOrEqual(4.5);
    expect(ratio(light.get("faint"), light.get("bg")), "placeholders and glyphs").toBeGreaterThanOrEqual(3.5);
  });
});

describe("the style sheets", () => {
  it("take every progress bar's thickness from one token", () => {
    expect(light.get("bar-h")).toBe("3px");
    const budget = readFileSync("src/features/budget/Budget.module.css", "utf8");
    const home = readFileSync("src/features/home/Home.module.css", "utf8");
    for (const [sheet, selector] of [
      [budget, ".bar"],
      [budget, ".glanceBar"],
      [home, ".glanceBar"],
    ] as const) {
      expect(rule(sheet, selector), selector).toContain("height: var(--bar-h)");
    }
  });

  it("have no share bars and no chart colours", () => {
    for (const [path, sheet] of otherSheets) {
      for (const banned of ["--chart-", ".sharebar", ".cdot"]) expect(sheet, path).not.toContain(banned);
    }
  });

  it("never blank every checkbox and radio on iOS (appearance: none belongs on a class)", () => {
    for (const [path, sheet] of otherSheets) {
      for (const [, selectors = "", body = ""] of sheet.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
        const bare = selectors.split(",").filter((s) => /^input(\[[^\]]*\])?$/.test(s.trim()));
        expect(bare.length > 0 && body.includes("appearance: none"), `${path}: ${bare.join(", ")}`).toBe(false);
      }
    }
  });
});

describe("the logo", () => {
  it("follows the ink palette in light and dark", () => {
    const svg = readFileSync("public/favicon.svg", "utf8");
    expect(svg).not.toContain("#2563eb");
    expect(svg.replace(/ /g, "")).toContain("prefers-color-scheme:dark");
  });
});

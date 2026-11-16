import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

// Vitest runs from frontend/. What a rule or an assistant added is violet (--auto), wherever a row or the sheet says so.
function rule(file: string, selector: string): string {
  const css = readFileSync(file, "utf8");
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`${selector} not in ${file}`);
  return css.slice(start, css.indexOf("}", start));
}

describe("what was added automatically", () => {
  it("is violet on a row, on the sheet's tags and on who added it", () => {
    expect(rule("src/features/transactions/TransactionList.module.css", ".via")).toContain("color: var(--auto)");
    expect(rule("src/features/transactions/TransactionSheet.module.css", ".tags a")).toContain("color: var(--auto)");
    expect(rule("src/features/transactions/TransactionSheet.module.css", ".by")).toContain("color: var(--auto)");
  });
});

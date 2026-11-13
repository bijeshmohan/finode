import { readFileSync } from "node:fs";

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import type { Grouping } from "../lib/amount";
import { AmountField } from "./AmountField";

function Field({ places = 2, grouping = "indian" as Grouping }) {
  const [value, setValue] = useState("");
  return (
    <AmountField id="amount" label="Amount" value={value} onChange={setValue} places={places} grouping={grouping} />
  );
}

describe("AmountField", () => {
  it("is a decimal keypad field", () => {
    render(<Field />);
    expect(screen.getByLabelText("Amount")).toHaveAttribute("inputmode", "decimal");
  });

  it("ignores what is not an amount", async () => {
    render(<Field />);
    await userEvent.type(screen.getByLabelText("Amount"), "12a.345");
    expect(screen.getByLabelText("Amount")).toHaveValue("12.34");
  });

  it("tidies and groups when you leave it", async () => {
    render(<Field />);
    await userEvent.type(screen.getByLabelText("Amount"), "1234567");
    await userEvent.tab();
    expect(screen.getByLabelText("Amount")).toHaveValue("12,34,567.00");
  });

  it("takes no decimal point for a currency without decimals", async () => {
    render(<Field places={0} grouping="western" />);
    await userEvent.type(screen.getByLabelText("Amount"), "1.5");
    await userEvent.tab();
    expect(screen.getByLabelText("Amount")).toHaveValue("15");
  });

  it("is at least 16px, so iOS does not zoom into it", () => {
    // jsdom does not apply CSS modules, so the rule itself is read (Vitest runs from frontend/).
    const css = readFileSync("src/components/AmountField.module.css", "utf8");
    expect(css).toMatch(/\.input \{[^}]*font-size: max\(16px, 1rem\)/);
  });
});

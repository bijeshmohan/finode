import { readFileSync } from "node:fs";

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import type { Grouping } from "../lib/amount";
import { AmountField } from "./AmountField";

function Field({ places = 2, grouping = "indian" as Grouping, start = "", groupAsTyped = false }) {
  const [value, setValue] = useState(start);
  return (
    <AmountField
      id="amount"
      label="Amount"
      value={value}
      onChange={setValue}
      places={places}
      grouping={grouping}
      groupAsTyped={groupAsTyped}
    />
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

  it("a letter typed in the middle is dropped and the cursor stays where it was", async () => {
    render(<Field start="1,234" />);
    const field = screen.getByLabelText<HTMLInputElement>("Amount");
    await userEvent.type(field, "a", { initialSelectionStart: 2, initialSelectionEnd: 2 });
    expect(field).toHaveValue("1,234");
    expect(field.selectionStart).toBe(2);
  });

  it("can group as it is typed, keeping the cursor after the same digits", async () => {
    render(<Field groupAsTyped />);
    const field = screen.getByLabelText<HTMLInputElement>("Amount");
    await userEvent.type(field, "1234567");
    expect(field).toHaveValue("12,34,567");
    expect(field.selectionStart).toBe("12,34,567".length);
    await userEvent.type(field, "8", { initialSelectionStart: 1, initialSelectionEnd: 1 });
    expect(field).toHaveValue("1,82,34,567");
    expect(field.selectionStart).toBe(3);
  });
});

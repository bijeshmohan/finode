import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { renderInApp } from "../test/render";
import { IconPicker } from "./IconPicker";

function Harness({ start, onChange }: { start: string | null; onChange: (name: string) => void }) {
  const [value, setValue] = useState(start);
  return (
    <IconPicker
      value={value}
      onChange={(name) => {
        setValue(name);
        onChange(name);
      }}
    />
  );
}

describe("IconPicker", () => {
  it("asks for an icon until one is chosen", async () => {
    renderInApp(<Harness start={null} onChange={vi.fn()} />);
    expect(await screen.findByRole("button", { name: /Choose an icon/ })).toBeInTheDocument();
  });

  it("opens the set in its groups and chooses one", async () => {
    const onChange = vi.fn();
    renderInApp(<Harness start={null} onChange={onChange} />);
    await userEvent.click(await screen.findByRole("button", { name: /Choose an icon/ }));
    const sheet = await screen.findByRole("dialog", { name: "Icon" });
    for (const group of ["Food and home", "Getting around", "Health and family", "Fun and shopping", "Money"]) {
      expect(within(sheet).getByRole("heading", { name: group })).toBeInTheDocument();
    }
    await userEvent.click(within(sheet).getByRole("button", { name: "shopping cart" }));
    expect(onChange).toHaveBeenCalledWith("shopping-cart");
    expect(screen.getByRole("button", { name: /shopping cart.*Change/ })).toBeInTheDocument();
  });

  it("marks the chosen icon and is reachable by keyboard", async () => {
    renderInApp(<Harness start="gift" onChange={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: /gift.*Change/ }));
    const sheet = await screen.findByRole("dialog", { name: "Icon" });
    expect(within(sheet).getByRole("button", { name: "gift" })).toHaveAttribute("aria-pressed", "true");
    expect(within(sheet).getByRole("button", { name: "pizza" })).toHaveAttribute("aria-pressed", "false");
    within(sheet).getByRole("button", { name: "pizza" }).focus();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: /pizza.*Change/ })).toBeInTheDocument();
  });
});

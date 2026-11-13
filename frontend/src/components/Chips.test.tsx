import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Chips } from "./Chips";

const OPTIONS = [
  { value: "spend", label: "Spend" },
  { value: "save", label: "Save" },
] as const;

describe("Chips", () => {
  it("marks the chosen one", () => {
    render(<Chips label="Kind" options={OPTIONS} value="save" onChange={vi.fn()} />);
    expect(screen.getByRole("radiogroup", { name: "Kind" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Save" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Spend" })).toHaveAttribute("aria-checked", "false");
  });

  it("a click chooses", async () => {
    const onChange = vi.fn();
    render(<Chips label="Kind" options={OPTIONS} value="spend" onChange={onChange} />);
    await userEvent.click(screen.getByRole("radio", { name: "Save" }));
    expect(onChange).toHaveBeenCalledWith("save");
  });

  it("arrow keys move the choice", async () => {
    const onChange = vi.fn();
    render(<Chips label="Kind" options={OPTIONS} value="spend" onChange={onChange} />);
    screen.getByRole("radio", { name: "Spend" }).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenCalledWith("save");
  });
});

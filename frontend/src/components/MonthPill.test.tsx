import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MonthPill } from "./MonthPill";

describe("MonthPill", () => {
  it("names the month", () => {
    render(<MonthPill month="2026-11" onChange={vi.fn()} />);
    expect(screen.getByText("Nov 2026")).toBeInTheDocument();
  });

  it("goes back a month across a year", () => {
    const onChange = vi.fn();
    render(<MonthPill month="2026-01" onChange={onChange} />);
    screen.getByRole("button", { name: "Previous month" }).click();
    expect(onChange).toHaveBeenCalledWith("2025-12");
  });

  it("goes forward, but not past max", () => {
    const onChange = vi.fn();
    const { rerender } = render(<MonthPill month="2026-12" onChange={onChange} max="2027-01" />);
    screen.getByRole("button", { name: "Next month" }).click();
    expect(onChange).toHaveBeenCalledWith("2027-01");
    rerender(<MonthPill month="2027-01" onChange={onChange} max="2027-01" />);
    expect(screen.getByRole("button", { name: "Next month" })).toBeDisabled();
  });

  it("offers the native month picker", () => {
    render(<MonthPill month="2026-11" onChange={vi.fn()} max="2026-12" />);
    const picker = screen.getByLabelText("Choose a month");
    expect(picker).toHaveAttribute("type", "month");
    expect(picker).toHaveAttribute("max", "2026-12");
  });
});

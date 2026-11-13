import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Sheet } from "./Sheet";

describe("Sheet", () => {
  it("opens with its title and content", () => {
    render(
      <Sheet open onClose={vi.fn()} title="Coffee">
        details
      </Sheet>,
    );
    expect(screen.getByRole("dialog", { name: "Coffee" })).toHaveAttribute("open");
    expect(screen.getByText("details")).toBeInTheDocument();
  });

  it("Escape closes it", () => {
    const onClose = vi.fn();
    render(
      <Sheet open onClose={onClose} title="Coffee">
        details
      </Sheet>,
    );
    fireEvent(screen.getByRole("dialog"), new Event("cancel", { cancelable: true }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("a tap on the dimmed area closes it, a tap inside does not", () => {
    const onClose = vi.fn();
    render(
      <Sheet open onClose={onClose} title="Coffee">
        details
      </Sheet>,
    );
    fireEvent.click(screen.getByText("details"));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("is closed when not open", () => {
    render(
      <Sheet open={false} onClose={vi.fn()} title="Coffee">
        details
      </Sheet>,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

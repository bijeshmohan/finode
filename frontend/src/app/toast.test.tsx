import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider, useToast } from "./toast";

function Saver() {
  const toast = useToast();
  return (
    <button
      type="button"
      onClick={() => {
        toast("Saved");
      }}
    >
      Save
    </button>
  );
}

describe("toasts", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows one and takes it away after three seconds", () => {
    vi.useFakeTimers();
    render(
      <ToastProvider>
        <Saver />
      </ToastProvider>,
    );
    act(() => {
      screen.getByRole("button", { name: "Save" }).click();
    });
    expect(screen.getByRole("status")).toHaveTextContent("Saved");
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });
});

import { act, render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
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
    const router = createMemoryRouter([
      {
        path: "/",
        element: (
          <ToastProvider>
            <Saver />
          </ToastProvider>
        ),
      },
    ]);
    render(<RouterProvider router={router} />);
    act(() => {
      screen.getByRole("button", { name: "Save" }).click();
    });
    expect(screen.getByRole("status")).toHaveTextContent("Saved");
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("a toast handed over in the navigation shows once", async () => {
    const router = createMemoryRouter(
      [
        {
          path: "/",
          element: (
            <ToastProvider>
              <p>home</p>
            </ToastProvider>
          ),
        },
      ],
      { initialEntries: [{ pathname: "/", state: { toast: "Your password was changed. You are signed in." } }] },
    );
    render(<RouterProvider router={router} />);
    expect(await screen.findByRole("status")).toHaveTextContent("Your password was changed. You are signed in.");
    await vi.waitFor(() => {
      expect(router.state.location.state).toBeNull();
    });
  });
});

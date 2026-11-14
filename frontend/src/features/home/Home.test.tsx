import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { components } from "../../api/schema";
import { renderApp, SIGNED_IN } from "../../test/render";
import { row } from "../transactions/fixtures";

type HomeView = components["schemas"]["HomeView"];

function home(overrides: Partial<HomeView> = {}): HomeView {
  return {
    month: "2026-11",
    is_current: true,
    has_recorded: true,
    glance: {
      has_budget: true,
      left: "400.00",
      spent: "600.00",
      assigned: "1000.00",
      carried: "0.00",
      of: "1000.00",
      percent: 60,
      pace: 43,
    },
    spent: "600.00",
    steps: null,
    steps_done: 3,
    steps_total: 3,
    rows: [row()],
    days: [],
    total: 1,
    ...overrides,
  };
}

const INR = { "/api/profile/": [200, { default_currency: "INR" }] as [number, unknown] };

describe("Home", () => {
  it("a new person sees what to do first", async () => {
    renderApp("/", {
      ...SIGNED_IN,
      "/api/views/home": [
        200,
        home({
          has_recorded: false,
          rows: [],
          total: 0,
          steps: [
            { key: "account", title: "Add a bank account, cash or card", done: false, hint: null },
            { key: "spend", title: "Record your first spend", done: false, hint: "Takes about ten seconds" },
            { key: "budget", title: "Give your money a job", done: false, hint: "Set aside rent and food" },
          ],
          steps_done: 0,
        }),
      ],
    });
    expect(await screen.findByText("Nothing recorded yet.")).toBeInTheDocument();
    expect(screen.getByText("Get started · 0 of 3")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Add a bank account/ })).toHaveAttribute("href", "/accounts/new");
    expect(screen.getByRole("link", { name: /Record your first spend/ })).toHaveAttribute("href", "/transactions/new");
    expect(screen.getByRole("link", { name: /Give your money a job/ })).toHaveAttribute("href", "/budget");
    expect(screen.getByRole("link", { name: "Import it" })).toHaveAttribute("href", "/settings/data#import");
  });

  it("overspent: the figure is the real negative, in red", async () => {
    renderApp("/", {
      ...SIGNED_IN,
      ...INR,
      "/api/views/home": [
        200,
        home({
          glance: {
            has_budget: true,
            left: "-50.50",
            spent: "150.50",
            assigned: "100.00",
            carried: "0.00",
            of: "150.50",
            percent: 100,
            pace: 43,
          },
        }),
      ],
    });
    expect(await screen.findByText("Over budget")).toBeInTheDocument();
    const figure = screen.getByTestId("glance-figure");
    await waitFor(() => {
      expect(figure).toHaveTextContent("₹−50.50");
    });
    expect(figure.className).toMatch(/over/);
    expect(
      screen.getByRole("img", { name: /100% of what there was to spend is spent, and 43% of the month/ }),
    ).toBeInTheDocument();
  });

  it("with money left, the figure is plain", async () => {
    renderApp("/", { ...SIGNED_IN, ...INR, "/api/views/home": [200, home()] });
    expect(await screen.findByText("Left to spend")).toBeInTheDocument();
    expect(screen.getByTestId("glance-figure").className).not.toMatch(/over/);
    expect(screen.getByText("Spent so far 600.00 of 1,000.00")).toBeInTheDocument();
  });

  it("the info button shows how left to spend is worked out", async () => {
    renderApp("/", { ...SIGNED_IN, ...INR, "/api/views/home": [200, home()] });
    await userEvent.click(await screen.findByLabelText("How what is left to spend is worked out"));
    const panel = screen.getByRole("region", { name: "How this is worked out" });
    expect(within(panel).getByText("Assigned in November")).toBeInTheDocument();
    expect(within(panel).getByText("Left to spend")).toBeInTheDocument();
    expect(await within(panel).findByText("₹400.00")).toBeInTheDocument();
  });

  it("without a budget, it says what was spent and how to plan", async () => {
    renderApp("/", {
      ...SIGNED_IN,
      "/api/views/home": [200, home({ glance: { ...home().glance, has_budget: false } })],
    });
    expect(await screen.findByText("Spent")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Set up your budget" })).toHaveAttribute("href", "/budget?month=2026-11");
  });

  it("lists the month's first entries and links to all of them", async () => {
    renderApp("/", { ...SIGNED_IN, "/api/views/home": [200, home()] });
    expect(await screen.findByText("Swiggy")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View all ›" })).toHaveAttribute("href", "/transactions?month=2026-11");
  });

  it("a month with nothing says so", async () => {
    renderApp("/?month=2026-10", {
      ...SIGNED_IN,
      "/api/views/home": [200, home({ month: "2026-10", is_current: false, rows: [], total: 0 })],
    });
    expect(await screen.findByText("Nothing was recorded in October.")).toBeInTheDocument();
  });
});

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { calledPaths, renderInApp, SIGNED_IN } from "../../test/render";
import { details, row } from "./fixtures";
import { TransactionSheet } from "./TransactionSheet";

const ID = "00000000-0000-4000-8000-000000000001";
const PATH = `/api/views/transactions/${ID}`;

function sheet(answer: Parameters<typeof renderInApp>[1] = {}, onClose = vi.fn()) {
  const rendered = renderInApp(<TransactionSheet id={ID} onClose={onClose} onOpen={vi.fn()} />, {
    ...SIGNED_IN,
    ...answer,
  });
  return { ...rendered, onClose };
}

describe("TransactionSheet", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows a split's lines with their amounts", async () => {
    sheet({
      [PATH]: [
        200,
        details({
          row: row({ title: "DMart", amount: "100.00" }),
          to_lines: [
            { name: "Food", amount: "70.00", posted_on: null },
            { name: "Rent", amount: "30.00", posted_on: "2026-11-20" },
          ],
          from_lines: [{ name: "Bank", amount: "100.00", posted_on: null }],
        }),
      ],
    });
    expect(await screen.findByRole("heading", { name: "DMart" })).toBeInTheDocument();
    expect(screen.getByText("Spent on")).toBeInTheDocument();
    expect(screen.getByText("70.00")).toBeInTheDocument();
    expect(screen.getByText("posts 20 Nov")).toBeInTheDocument();
    expect(screen.getByText("Today · 13 Nov 2026")).toBeInTheDocument();
  });

  it("asks before deleting, and does nothing when the answer is no", async () => {
    const ask = vi.spyOn(window, "confirm").mockReturnValue(false);
    const { fetch } = sheet({ [PATH]: [200, details()] });
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    expect(ask).toHaveBeenCalledWith("Delete this transaction? Account balances will change. This cannot be undone.");
    expect(calledPaths(fetch)).not.toContain(`/api/transactions/${ID}`);
  });

  it("deletes for good when asked, closes and says so", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { onClose } = sheet({ [PATH]: [200, details()], [`/api/transactions/${ID}`]: [204, null] });
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await vi.waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
    expect(await screen.findByText("Transaction deleted")).toBeInTheDocument();
  });

  it("a refused delete is explained in the sheet", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    sheet({
      [PATH]: [200, details()],
      [`/api/transactions/${ID}`]: [400, { detail: "this entry belongs to a person: change it from their page!" }],
    });
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("this entry belongs to a person");
  });

  it("an entry made through a person only leads to their page", async () => {
    sheet({ [PATH]: [200, details({ person: { id: "p1", name: "Ada" }, loan_like: false })] });
    expect(await screen.findByRole("link", { name: "Open Ada" })).toHaveAttribute("href", "/people/p1");
    expect(screen.queryByRole("link", { name: "Edit" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });

  it("offers Edit, Repeat and Related for an ordinary entry", async () => {
    sheet({ [PATH]: [200, details()] });
    expect(await screen.findByRole("link", { name: "Edit" })).toHaveAttribute("href", `/transactions/${ID}/edit`);
    expect(screen.getByRole("link", { name: "Repeat" })).toHaveAttribute("href", `/transactions/new?repeat=${ID}`);
    expect(screen.getByRole("link", { name: "Related" })).toHaveAttribute("href", `/transactions/new?related=${ID}`);
  });

  it("closes when the entry cannot be loaded", async () => {
    const { onClose } = sheet({ [PATH]: [404, { detail: "transaction not found" }] });
    await vi.waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
  });
});

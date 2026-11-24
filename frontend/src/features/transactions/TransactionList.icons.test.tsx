import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderInApp } from "../../test/render";
import { row } from "./fixtures";
import { TransactionList } from "./TransactionList";

describe("TransactionList", () => {
  it("leads each row with the icon the server chose", async () => {
    renderInApp(<TransactionList rows={[row({ icon: "utensils" })]} onOpen={vi.fn()} />);
    expect((await screen.findByRole("button", { name: /Swiggy/ })).querySelector("svg")).not.toBeNull();
  });
});

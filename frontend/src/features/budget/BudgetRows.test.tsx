import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderInApp } from "../../test/render";
import { BudgetRows } from "./BudgetRows";
import { row } from "./fixtures";

describe("BudgetRows", () => {
  it("leads each line with its category's icon", async () => {
    renderInApp(<BudgetRows rows={[row({ icon: "house" })]} onOpen={vi.fn()} />);
    expect((await screen.findByRole("button", { name: /Rent/ })).querySelector("svg")).not.toBeNull();
  });
});

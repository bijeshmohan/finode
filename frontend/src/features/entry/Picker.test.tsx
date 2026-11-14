import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderInApp } from "../../test/render";
import { groups, ids } from "./fixtures";
import { Picker } from "./Picker";

function picker(props: Partial<Parameters<typeof Picker>[0]> = {}) {
  const onChange = vi.fn();
  renderInApp(
    <Picker
      open
      title="Paid from"
      groups={groups.slice(0, 2)}
      value={null}
      onChange={onChange}
      onClose={vi.fn()}
      {...props}
    />,
  );
  return onChange;
}

describe("Picker", () => {
  it("lists the accounts under their type with their balance", async () => {
    picker();
    const sheet = await screen.findByRole("dialog", { name: "Paid from" });
    expect(within(sheet).getByRole("heading", { name: "Assets" })).toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: /Bank/ })).toHaveTextContent("5,000.00");
  });

  it("search narrows the list and names the group under each", async () => {
    picker();
    await userEvent.type(await screen.findByLabelText("Search"), "vis");
    expect(screen.queryByRole("button", { name: /Bank/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Visa/ })).toHaveTextContent("Liabilities");
  });

  it("chooses and greys the other side's choice", async () => {
    const onChange = picker({ otherSide: ids.card });
    expect(await screen.findByRole("button", { name: /Visa/ })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /Bank/ }));
    expect(onChange).toHaveBeenCalledWith(ids.bank);
  });

  it("marks the chosen one", async () => {
    picker({ value: ids.bank });
    expect(await screen.findByRole("button", { name: /Bank/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("can be cleared when it allows none", async () => {
    const onChange = picker({ clearable: "No category" });
    await userEvent.click(await screen.findByRole("button", { name: "No category" }));
    expect(onChange).toHaveBeenCalledWith(null);
  });
});

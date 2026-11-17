import { describe, expect, it } from "vitest";

import { expenseBody, incomeBody } from "./share";

const bill = {
  categoryId: null,
  accountId: "bank",
  selfPaid: "",
  people: [{ contactId: "ada", value: "1", paid: "10.555" }],
};

describe("what a Split sends", () => {
  it("keeps the decimals of shares and percentages, whatever the currency's places", () => {
    const sent = expenseBody({ ...bill, method: "shares", selfValue: "1.5" });
    expect(sent).toMatchObject({ self_value: "1.5", people: [{ contact_id: "ada", value: "1", paid: "10.555" }] });
    expect(expenseBody({ ...bill, method: "percentage", selfValue: "33.333" })).toMatchObject({
      self_value: "33.333",
    });
  });

  it("sends a typed amount as plain digits, and nothing for an empty box", () => {
    expect(expenseBody({ ...bill, method: "exact", selfValue: "1,500.5", selfPaid: " " })).toMatchObject({
      self_value: "1500.5",
      self_paid: null,
    });
    expect(
      incomeBody({ categoryId: null, accountId: null, people: [{ contactId: "ada", theirs: "−4,000", received: "" }] }),
    ).toMatchObject({ people: [{ contact_id: "ada", theirs: "-4000", received: null }] });
  });
});

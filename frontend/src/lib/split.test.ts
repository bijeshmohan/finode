import { describe, expect, it } from "vitest";

import { allocation, differs, left, less, personNote, positive, sameAmount } from "./split";

describe("what is left to allocate on a side", () => {
  it("is the total less the rows that have an amount", () => {
    expect(left("1,000.00", ["600"], 2)).toBe("400.00");
    expect(left("12,34,567.89", ["34,567.89", ""], 2)).toBe("1200000.00");
  });

  it("can be over", () => {
    expect(allocation("1000", ["600", "600"], 2)).toEqual({ left: "-200.00", over: true, balanced: false });
    expect(allocation("1000", ["600", "400"], 2)).toEqual({ left: "0.00", over: false, balanced: true });
  });

  it("keeps the currency's places: yen have none", () => {
    expect(left("1000", ["333"], 0)).toBe("667");
  });

  it("counts an empty or unreadable amount as nothing", () => {
    expect(left("100", ["", "abc", "−"], 2)).toBe("100.00");
    expect(left("", ["30"], 2)).toBe("-30.00");
  });

  it("a row differs from the total only when the amounts differ", () => {
    expect(differs("1,000.00", "1000")).toBe(false);
    expect(differs("999.99", "1,000")).toBe(true);
    expect(differs("", "1000")).toBe(false);
  });
});

describe("comparing typed amounts", () => {
  it("reads grouping and decimals alike", () => {
    expect(sameAmount("1,000", "1000.00")).toBe(true);
    expect(sameAmount("", "")).toBe(true);
    expect(sameAmount("", "5")).toBe(false);
    expect(positive("0.00")).toBe(false);
    expect(positive("−5")).toBe(false);
    expect(positive("0.5")).toBe(true);
  });
});

describe("less", () => {
  it("compares typed amounts", () => {
    expect(less("200", "500.00")).toBe(true);
    expect(less("500", "500.00")).toBe(false);
    expect(less("", "1")).toBe(true);
  });
});

describe("the note under a person on a transfer", () => {
  const alice = (owes: string) => ({ name: "Alice", owes });
  const note = (owes: string, toThem: boolean, amount: string, total = "") =>
    personNote(alice(owes), toThem, amount, total, "western");

  it("with nothing owed that way, it is a new loan or borrowing", () => {
    expect(note("0", true, "100")).toBe(
      "Alice will owe you this. It is not spending, so your budgets stay as they are.",
    );
    expect(note("0", false, "100")).toBe(
      "You will owe Alice this. It is not income, so your budgets stay as they are.",
    );
    expect(note("500", true, "100")).toBe(
      "Alice will owe you this. It is not spending, so your budgets stay as they are.",
    );
  });

  it("with no amount yet, it says what is owed", () => {
    expect(note("500", false, "")).toBe("Alice owes you 500.00. This pays it back first.");
    expect(note("-300", true, "")).toBe("You owe Alice 300.00. This pays it back first.");
  });

  it("pays back part, all or more than what is owed", () => {
    expect(note("500", false, "200")).toBe("Alice pays back 200.00 of the 500.00 owed to you.");
    expect(note("500", false, "500")).toBe("Alice pays back in full.");
    expect(note("500", false, "1,200")).toBe(
      "Alice pays back 500.00. The other 700.00 is borrowed: you will owe Alice it.",
    );
    expect(note("-300", true, "100")).toBe("You pay back 100.00 of the 300.00 you owe Alice.");
    expect(note("-300", true, "300")).toBe("You pay back Alice in full.");
    expect(note("-300", true, "350")).toBe("You pay back 300.00. The other 50.00 is lent: Alice will owe you it.");
  });

  it("follows the total when the row has no amount", () => {
    expect(note("500", false, "", "200")).toBe("Alice pays back 200.00 of the 500.00 owed to you.");
    expect(note("500", false, "0", "500")).toBe("Alice pays back in full.");
  });

  it("groups as the currency does, and keeps decimals beyond two", () => {
    expect(personNote(alice("100000"), false, "1,00,000", "", "indian")).toBe("Alice pays back in full.");
    expect(personNote(alice("250000"), false, "1,00,000", "", "indian")).toBe(
      "Alice pays back 1,00,000.00 of the 2,50,000.00 owed to you.",
    );
    expect(note("500", false, "200.125")).toBe("Alice pays back 200.125 of the 500.00 owed to you.");
  });
});

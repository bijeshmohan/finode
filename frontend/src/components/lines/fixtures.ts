// The pickers' groups as the form views answer them, for the tests.
import type { PickGroup } from "./queries";

export const ids = {
  bank: "00000000-0000-4000-8000-0000000000b1",
  card: "00000000-0000-4000-8000-0000000000c1",
  loan: "00000000-0000-4000-8000-0000000000l1",
  food: "00000000-0000-4000-8000-0000000000f1",
  salary: "00000000-0000-4000-8000-0000000000s1",
  emi: "00000000-0000-4000-8000-0000000000e1",
  ada: "00000000-0000-4000-8000-0000000000a1",
  bob: "00000000-0000-4000-8000-0000000000a2",
};

export const groups: PickGroup[] = [
  {
    title: "Bank Account",
    options: [{ id: ids.bank, label: "Bank", budget: true, balance: "5000.00" }],
  },
  {
    title: "Credit Card",
    options: [
      { id: ids.card, label: "Visa", budget: true, balance: "-200.00" },
      { id: ids.loan, label: "Amex", budget: true, balance: "-90000.00" },
    ],
  },
  { title: "People", options: [{ id: ids.ada, label: "Ada", budget: false, balance: "0.00" }] },
  { title: "Income", options: [{ id: ids.salary, label: "Salary", budget: false, balance: null, icon: "wallet" }] },
  {
    title: "Expenses",
    options: [
      { id: ids.food, label: "Food", budget: false, balance: null, icon: "utensils" },
      { id: ids.emi, label: "EMI", budget: false, balance: null, icon: "landmark" },
    ],
  },
];

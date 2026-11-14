// The Categories views as the server answers them, for the tests.
import type { CategoriesView, CategoryFormView, CategoryView } from "./queries";

export const ids = {
  food: "00000000-0000-4000-8000-00000000f00d",
  groceries: "00000000-0000-4000-8000-00000000f001",
  rent: "00000000-0000-4000-8000-00000000f0f0",
};

export function categories(over: Partial<CategoriesView> = {}): CategoriesView {
  return {
    month: "2026-11",
    is_current: true,
    tab: "expense",
    grand: "1000.00",
    rows: [
      { id: ids.rent, name: "Rent", total: "600.00", hint: "", share: "60%" },
      { id: ids.food, name: "Food", total: "400.00", hint: "Groceries · Dining", share: "40%" },
      { id: ids.groceries, name: "Travel", total: "0.00", hint: "", share: "0%" },
    ],
    ...over,
  };
}

export function category(over: Partial<CategoryView> = {}): CategoryView {
  return {
    id: ids.food,
    name: "Food",
    details: null,
    kind: "spending",
    built_in: false,
    closed_on: null,
    group: null,
    month: "2026-11",
    is_current: true,
    total: "350.00",
    subs: [{ id: ids.groceries, name: "Groceries", total: "300.00" }],
    own_here: "50.00",
    can_add_child: true,
    can_delete: true,
    entries: [],
    ...over,
  };
}

export function categoryForm(over: Partial<CategoryFormView> = {}): CategoryFormView {
  return {
    editing: false,
    kind: "spending",
    name: "",
    details: null,
    parent_id: null,
    groups: [
      { id: ids.food, name: "Food" },
      { id: ids.rent, name: "Rent" },
    ],
    ...over,
  };
}

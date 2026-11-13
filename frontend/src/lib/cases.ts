// The shared cases (tests/format_cases.json): pytest holds the server's filters to them, Vitest holds these helpers.
import cases from "../../../tests/format_cases.json";

import type { Grouping } from "./amount";

export const moneyCases = cases.money as [string, Grouping, string][];
export const amountCases = cases.amount as [string, string | null, string][];
export const dateCases = {
  friendlyDate: cases.friendly_date as [string, string, string][],
  shortDate: cases.short_date as [string, string, string][],
  dateChip: cases.date_chip as [string, string, string][],
};

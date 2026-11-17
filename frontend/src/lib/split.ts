// The Add screen's only arithmetic on money (the spec's "split preview"): what is left to allocate on a side with
// several rows, whether a row's amount is the whole total, and what a transfer with a person does. big.js keeps every
// digit; everything else about an entry, its shares included, is worked out by the server.
import Big from "big.js";

import type { Grouping } from "./amount";
import { formatMoney } from "./money";

/** An amount as typed ("1,234.50", "−5") as a number, or null when it is empty or not a number. */
function read(text: string): Big | null {
  const plain = text.replace(/[,\s]/g, "").replaceAll("−", "-");
  if (!/^-?(\d+\.?\d*|\.\d+)$/.test(plain)) return null;
  return new Big(plain);
}

function sum(amounts: string[]): Big {
  return amounts.reduce((acc, text) => acc.plus(read(text) ?? 0), new Big(0));
}

/** The total less the rows that have an amount, with the currency's decimal places ("400.00", "-200.00", "667"). */
export function left(total: string, amounts: string[], places: number): string {
  return (read(total) ?? new Big(0)).minus(sum(amounts)).toFixed(places);
}

export interface Allocation {
  left: string;
  over: boolean;
  balanced: boolean;
}

export function allocation(total: string, amounts: string[], places: number): Allocation {
  const rest = (read(total) ?? new Big(0)).minus(sum(amounts));
  return { left: rest.toFixed(places), over: rest.lt(0), balanced: rest.eq(0) };
}

/** Whether a row's amount is something other than the whole total (an empty one never is). */
export function differs(amount: string, total: string): boolean {
  const own = read(amount);
  return own !== null && !own.eq(read(total) ?? 0);
}

/** Whether two typed amounts are the same number (both empty counts as the same). */
export function sameAmount(a: string, b: string): boolean {
  const one = read(a);
  const two = read(b);
  return one === null || two === null ? one === two : one.eq(two);
}

/** Whether a typed amount is more than nothing. */
export function positive(amount: string): boolean {
  return read(amount)?.gt(0) ?? false;
}

/** Whether a typed amount is less than another (an empty one counts as nothing). */
export function less(amount: string, than: string): boolean {
  return (read(amount) ?? new Big(0)).lt(read(than) ?? 0);
}

/** A typed amount that is more than nothing, or null (an empty, unreadable, zero or negative one). */
function more(text: string): Big | null {
  const value = read(text);
  return value?.gt(0) ? value : null;
}

/** What a transfer with a person does. `owes` is what they owe you (a
 * negative one: what you owe them); `toThem` is money going to them. The amount is the row's, else the total's. Money
 * from someone who owes you pays that back first, and money to someone you owe does the same; only the rest is a new
 * loan or borrowing, which is not income or spending. */
export function personNote(
  person: { name: string; owes: string },
  toThem: boolean,
  amount: string,
  total: string,
  grouping: Grouping,
): string {
  const { name } = person;
  const money = (value: Big) => formatMoney(value.toString(), grouping);
  const owes = read(person.owes) ?? new Big(0);
  const owed = toThem ? (owes.lt(0) ? owes.neg() : new Big(0)) : owes.gt(0) ? owes : new Big(0);
  const paid = more(amount) ?? more(total) ?? new Big(0);
  if (owed.eq(0)) {
    return toThem
      ? `${name} will owe you this. It is not spending, so your budgets stay as they are.`
      : `You will owe ${name} this. It is not income, so your budgets stay as they are.`;
  }
  if (paid.eq(0)) {
    return toThem
      ? `You owe ${name} ${money(owed)}. This pays it back first.`
      : `${name} owes you ${money(owed)}. This pays it back first.`;
  }
  if (paid.lt(owed)) {
    return toThem
      ? `You pay back ${money(paid)} of the ${money(owed)} you owe ${name}.`
      : `${name} pays back ${money(paid)} of the ${money(owed)} owed to you.`;
  }
  if (paid.eq(owed)) return toThem ? `You pay back ${name} in full.` : `${name} pays back in full.`;
  const rest = money(paid.minus(owed));
  return toThem
    ? `You pay back ${money(owed)}. The other ${rest} is lent: ${name} will owe you it.`
    : `${name} pays back ${money(owed)}. The other ${rest} is borrowed: you will owe ${name} it.`;
}

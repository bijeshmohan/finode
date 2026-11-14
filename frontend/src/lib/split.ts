// The Add screen's only arithmetic on money (the spec's "split preview"): what is left to allocate on a side with
// several rows, and whether a row's amount is the whole total. big.js keeps every digit; everything else about an
// entry, its shares included, is worked out by the server.
import Big from "big.js";

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

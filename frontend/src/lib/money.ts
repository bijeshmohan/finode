// Amounts as the server writes them (app/templating.py: the `money` and `amount` filters), worked on the string so no
// digit is lost to floating point. tests/format_cases.json holds both to the same answers.
import { type Grouping, groupDigits } from "./amount";

const MINUS = "−"; // a true minus sign lines up with "+" and reads better than a hyphen
const SYMBOLS: Readonly<Record<string, string>> = { INR: "₹" };

/** Grouped digits and at least two decimals; padding zeros beyond two are dropped (100.00000000 is 100.00, 0.01250000
 * is 0.0125). A value that is not a decimal number comes back as it is. */
export function formatMoney(value: string, grouping: Grouping): string {
  const match = /^(-?)(\d*)(?:\.(\d*))?$/.exec(value.trim());
  if (!match) return value;
  const [, sign = "", whole = "", fraction = ""] = match;
  const digits = whole.replace(/^0+(?=\d)/, "") || "0";
  const decimals = fraction.replace(/0+$/, "").padEnd(2, "0");
  return (sign ? MINUS : "") + groupDigits(digits, grouping) + "." + decimals;
}

/** The currency beside an amount: its sign in front where it has one (₹1,200.00, ₹−5.00), else its code after. */
export function withCurrency(text: string, code: string | null): string {
  if (!code) return text;
  const symbol = SYMBOLS[code];
  return symbol === undefined ? `${text} ${code}` : `${symbol}${text}`;
}

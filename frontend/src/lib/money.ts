// Amounts as the server writes them (app/templating.py: the `money` and `amount` filters), worked on the string so no
// digit is lost to floating point. tests/format_cases.json holds both to the same answers.
import { type Grouping, groupDigits } from "./amount";

const MINUS = "−"; // a true minus sign lines up with "+" and reads better than a hyphen
const SYMBOLS: Readonly<Record<string, string>> = { INR: "₹" };

/** Grouped digits and at least two decimals; padding zeros beyond two are dropped (100.00000000 is 100.00, 0.01250000
 * is 0.0125). A value that is not a decimal number comes back as it is. */
export function formatMoney(value: string, grouping: Grouping): string {
  const plain = plainDecimal(value.trim());
  if (plain === null) return value;
  const [, sign = "", whole = "", fraction = ""] = /^(-?)(\d*)\.?(\d*)$/.exec(plain) ?? [];
  const digits = whole.replace(/^0+(?=\d)/, "") || "0";
  const decimals = fraction.replace(/0+$/, "").padEnd(2, "0");
  return (sign ? MINUS : "") + groupDigits(digits, grouping) + "." + decimals;
}

/** A decimal as plain digits: "1E-7" is "0.0000001", "+5" is "5" (the API writes Decimals the way Python's str() does).
 * Null for anything that is not a decimal number. */
function plainDecimal(text: string): string | null {
  const match = /^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(text);
  if (!match || (match[2] === "" && (match[3] ?? "") === "")) return null;
  const [, sign = "", whole = "", fraction = "", exponent = "0"] = match;
  const digits = whole + fraction;
  const point = whole.length + Number(exponent);
  const padded = point < 0 ? "0".repeat(-point) + digits : digits.padEnd(point, "0");
  const at = Math.max(point, 0);
  return `${sign === "-" ? "-" : ""}${padded.slice(0, at) || "0"}.${padded.slice(at)}`;
}

/** The currency beside an amount: its sign in front where it has one (₹1,200.00, ₹−5.00), else its code after. */
export function withCurrency(text: string, code: string | null): string {
  if (!code) return text;
  const symbol = SYMBOLS[code];
  return symbol === undefined ? `${text} ${code}` : `${symbol}${text}`;
}

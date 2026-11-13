// Typing amounts, ported from app/static/app.js (cleanAmount, tidyAmount, groupAmount). The currency's decimal places
// and grouping are arguments here, where app.js read them from <html>. The server checks every amount again.

/** Rupees are written in lakhs and crores (12,34,567); every other currency in thousands (1,234,567). */
export type Grouping = "indian" | "western";

export function groupingFor(currency: string | null): Grouping {
  return currency === "INR" ? "indian" : "western";
}

/** Only what makes an amount: digits, commas, one decimal point (none when `places` is 0, and no more decimals than
 * `places`) and a leading minus; no zeros in front ("01" is 1, "00.5" is 0.5). */
export function cleanAmount(text: string, places: number): string {
  let out = "";
  let dot = false;
  let fraction = 0;
  for (const ch of text) {
    if (ch >= "0" && ch <= "9") {
      if (dot && fraction >= places) continue;
      if (dot) fraction += 1;
      out += ch;
    } else if (ch === ",") out += ch;
    else if (ch === "." && !dot && places > 0) {
      dot = true;
      out += ch;
    } else if (ch === "-" && out === "") out += ch;
  }
  return out.replace(/^(-?)0+(?=\d)/, "$1");
}

/** The amount written out whole when the person leaves the field: no commas or zeros in front and the decimals the
 * currency keeps ("1." becomes 1.00 for rupees). Anything that is not a number stays as typed. */
export function tidyAmount(text: string, places: number): string {
  let t = text.replace(/[,\s]/g, "");
  const sign = t.startsWith("-") ? "-" : "";
  t = t.replace("-", "");
  if (t === "" || t === "." || !/^\d*\.?\d*$/.test(t)) return text;
  const [whole = "", fraction = ""] = t.split(".");
  const digits = whole.replace(/^0+(?=\d)/, "") || "0";
  return sign + digits + (places ? "." + fraction.slice(0, places).padEnd(places, "0") : "");
}

/** Commas in a run of digits. */
export function groupDigits(whole: string, grouping: Grouping): string {
  if (grouping === "indian") return whole.replace(/\B(?=(\d{2})*\d{3}(?!\d))/g, ",");
  return whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** Commas put into whatever number it is given; anything else is left alone. */
export function groupAmount(text: string, grouping: Grouping): string {
  const match = /^(-?)(\d*)(\.\d*)?$/.exec(text.replace(/,/g, ""));
  if (!match) return text;
  const [, sign = "", whole = "", fraction = ""] = match;
  return sign + groupDigits(whole, grouping) + fraction;
}

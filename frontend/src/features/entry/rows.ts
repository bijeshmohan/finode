// The rows of one side of an entry, as the web form keeps them (recomputeTxn in app.js): a row whose amount was typed
// is "touched"; at most one open row waits for the rest while something is left, and suggests it; a side with one row
// is the whole amount. The server checks that the sides add up.
import { type Grouping, groupAmount } from "../../lib/amount";
import { allocation } from "../../lib/split";
import type { EntryFormView } from "./queries";

export interface RowState {
  key: string;
  choice: string | null;
  category: string | null;
  /** What was typed for the row (only a touched row has one). */
  amount: string;
  /** The day the account posts this line, when it is not the entry's own. */
  postedOn: string | null;
  touched: boolean;
}

let made = 0;

export function blankRow(): RowState {
  made += 1;
  return { key: `row-${String(made)}`, choice: null, category: null, amount: "", postedOn: null, touched: false };
}

/** The rows an entry starts with. Several rows keep their own amounts; one row follows the total. */
export function startRows(rows: EntryFormView["from_rows"], grouping: Grouping): RowState[] {
  const several = rows.length > 1;
  const start = rows.map((r) => ({
    ...blankRow(),
    choice: r.choice,
    category: r.category_id,
    postedOn: r.posted_on,
    amount: several && r.amount ? groupAmount(r.amount, grouping) : "",
    touched: several && r.amount !== null,
  }));
  return start.length ? start : [blankRow()];
}

function rest(rows: RowState[], total: string, places: number) {
  return allocation(
    total,
    rows.filter((r) => r.touched).map((r) => r.amount),
    places,
  );
}

function something(left: ReturnType<typeof rest>): boolean {
  return !left.over && !left.balanced;
}

/** The side tidied after a change: an open row added while something is left, spare open rows without an account
 * dropped. */
export function settle(rows: RowState[], total: string, places: number): RowState[] {
  const left = rest(rows, total, places);
  let out = [...rows];
  const open = () => out.filter((r) => !r.touched);
  if (something(left) && open().length === 0) out.push(blankRow());
  const spare = open().slice(1);
  out = out.filter((r) => !(spare.includes(r) && r.choice === null));
  if (!something(left) && out.length > 1) out = out.filter((r) => r.touched || r.choice !== null);
  return out.length ? out : [blankRow()];
}

/** A row's amount as it is shown and sent: what was typed, or for the first open row what is left. */
export function amountOf(rows: RowState[], index: number, total: string, places: number): string {
  const row = rows[index];
  if (!row) return "";
  if (row.touched) return row.amount;
  const first = rows.findIndex((r) => !r.touched);
  const left = rest(rows, total, places);
  return index === first && something(left) ? left.left : "";
}

/** A row taken away. The last one is emptied instead; one row left on a category side is the whole amount again. */
export function removeRow(rows: RowState[], index: number, categorySide: boolean): RowState[] {
  if (rows.length === 1) {
    const only = rows[0] ?? blankRow();
    return [{ ...only, choice: null, category: null, amount: "", postedOn: null, touched: false }];
  }
  const left = rows.filter((_, i) => i !== index);
  if (left.length === 1 && categorySide) return left.map((r) => ({ ...r, amount: "", touched: false }));
  return left;
}

/** A line cannot post before the entry: moving the entry's date past a posting date puts the line back on it. */
export function datesFrom(rows: RowState[], date: string): RowState[] {
  return rows.map((r) => (r.postedOn !== null && r.postedOn < date ? { ...r, postedOn: null } : r));
}

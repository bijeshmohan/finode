// The Add screen's rows, shared with the recurring form: what kind of entry, the amount, and where the
// money came from and went (rows on each side, chosen in our own picker, each with its own amount and, where `dated`,
// its posting day from its settings), with "＋ New" to make an account or a category on the way. The server decides
// what the choices record (services/entry.py, services/recurring_form.py); this part only collects them.
import { type ReactNode, useId, useState } from "react";
import { createPortal } from "react-dom";

import type { components } from "../../api/schema";
import { useCurrency, useGrouping, usePlaces, useSymbol } from "../../app/currency";
import { useToday } from "../../app/session";
import { groupAmount, tidyAmount } from "../../lib/amount";
import { shortDate } from "../../lib/dates";
import { formatMoney } from "../../lib/money";
import { allocation, differs, positive, sameAmount } from "../../lib/split";
import { AmountField } from "../AmountField";
import { Icon } from "../Icon";
import {
  canSwap,
  isAccount,
  isCategorySide,
  KINDS,
  type Kind,
  keepsChoice,
  labelOf,
  offered,
  rowCategoryShown,
  screenOrder,
  type Side,
} from "./kinds";
import styles from "./Lines.module.css";
import { Picker } from "./Picker";
import { QuickAdd, type QuickKind } from "./QuickAdd";
import type { CategoryParent, ParentOption, PickGroup } from "./queries";
import { RowSettings } from "./RowSettings";
import { amountOf, removeRow, type RowState, settle } from "./rows";

export type EntryRow = components["schemas"]["EntryRow"];

/** What the rows need of a screen's state; the screen keeps the rest (payee, note, the Split…) beside it. */
export interface LinesState {
  kind: Kind;
  total: string;
  /** The day the entry is on: a row posted on another day says so. */
  date: string;
  credit: RowState[];
  debit: RowState[];
}

type Update<S> = (next: (now: S) => S) => void;

/** A screen's state with the rows in it: every change leaves both sides tidied (an open row for what is left, no spare
 * empty rows). */
export function useLines<S extends LinesState>(start: () => S): [S, Update<S>] {
  const places = usePlaces();
  const [state, setState] = useState<S>(start);
  const update: Update<S> = (next) => {
    setState((now) => {
      const after = next(now);
      return {
        ...after,
        credit: settle(after.credit, after.total, places),
        debit: settle(after.debit, after.total, places),
      };
    });
  };
  return [state, update];
}

function firstChoice(rows: RowState[]): string | null {
  return rows.find((r) => r.choice !== null)?.choice ?? null;
}

function categoryGroups(groups: PickGroup[]): PickGroup[] {
  return groups.filter((g) => g.title === "Expenses" || g.title === "Income");
}

/** What "＋ New" makes on a side: a category where the side lists categories, else an account under its first root. */
function quickKind(kind: Kind, side: Side): QuickKind {
  const root = KINDS[kind][side].roots?.[0] ?? (side === "debit" ? "Expenses" : "Assets");
  if (root === "Expenses") return { what: "category", kind: "spending" };
  if (root === "Income") return { what: "category", kind: "earning" };
  return { what: "account", root };
}

const other = (side: Side): Side => (side === "credit" ? "debit" : "credit");

/** The rows as the server takes them, or what is missing ("Enter the amount.", "every posting needs an account!",
 * "amount is required!"). */
export function linesBody(
  state: LinesState,
  groups: PickGroup[],
  places: number,
): { rows: EntryRow[]; problem?: undefined } | { rows?: undefined; problem: string } {
  const amount = tidyAmount(state.total, places).replace(/,/g, "");
  if (!amount || !/^-?\d+(\.\d+)?$/.test(amount)) return { problem: "Enter the amount." };
  const rows: EntryRow[] = [];
  for (const s of ["credit", "debit"] as const) {
    const before = rows.length;
    for (const [index, r] of state[s].entries()) {
      const typed = amountOf(state[s], index, state.total, places);
      if (r.choice === null && typed === "") continue; // an untouched blank row
      if (r.choice === null || typed === "") {
        return { problem: r.choice === null ? "every posting needs an account!" : "amount is required!" };
      }
      const shown = rowCategoryShown(r.choice, firstChoice(state[other(s)]), groups);
      rows.push({
        choice: r.choice,
        side: s,
        amount: tidyAmount(typed, places).replace(/,/g, ""),
        category_id: shown ? r.category : null,
        posted_on: r.postedOn,
      });
    }
    if (rows.length === before) return { problem: "every posting needs an account!" };
  }
  return { rows };
}

interface LinesProps<S extends LinesState> {
  state: S;
  update: Update<S>;
  groups: PickGroup[];
  accountParents: ParentOption[];
  categoryParents: CategoryParent[];
  /** Whether a row's settings offer a posting day of its own (an entry: yes; a recurring rule: no). */
  dated: boolean;
  /** Whether the amount takes the focus at once. */
  autoFocus?: boolean;
  /** What else changes when the kind does (the Add screen's Split and named person). */
  onKind?: (after: S, before: S) => S;
  /** The sides are not drawn (the Add screen's Split records the bill instead). */
  hideSides?: boolean;
  /** Drawn between the amount and the sides: the payee, the date, the Split… */
  children?: ReactNode;
}

export function Lines<S extends LinesState>({
  state,
  update,
  groups,
  accountParents,
  categoryParents,
  dated,
  autoFocus = false,
  onKind,
  hideSides = false,
  children,
}: LinesProps<S>) {
  const grouping = useGrouping();
  const places = usePlaces();
  const symbol = useSymbol();
  const code = useCurrency();
  const today = useToday();
  const [picking, setPicking] = useState<{ side: Side; index: number; category: boolean } | null>(null);
  const [tuning, setTuning] = useState<{ side: Side; index: number } | null>(null);
  const [making, setMaking] = useState<{ side: Side; index: number; kind: QuickKind } | null>(null);
  const ids = { credit: useId(), debit: useId() };

  const changeRow = (side: Side, index: number, next: Partial<RowState>) => {
    update((now) => ({ ...now, [side]: now[side].map((r, i) => (i === index ? { ...r, ...next } : r)) }));
  };

  const chooseKind = (tapped: Kind) => {
    update((now) => {
      const kind: Kind = tapped === now.kind ? "other" : tapped;
      const keep = (side: Side): RowState[] =>
        now[side].map((r) => (keepsChoice(kind, side, r.choice, groups) ? r : { ...r, choice: null, category: null }));
      const after = { ...now, kind, credit: keep("credit"), debit: keep("debit") };
      return onKind ? onKind(after, now) : after;
    });
  };

  const swap = () => {
    update((now) => ({
      ...now,
      credit: now.debit,
      debit: now.credit,
      // An expense turned round is no longer an expense (a refund, say): every account is offered again.
      kind: now.kind === "transfer" ? "transfer" : "other",
    }));
  };

  const shownCategory = (side: Side, row: RowState): boolean =>
    rowCategoryShown(row.choice, firstChoice(state[other(side)]), groups);
  const amountAt = (side: Side, index: number) => amountOf(state[side], index, state.total, places);

  const describe = (s: Side, index: number, r: RowState): { when: string; amount: string } => {
    const share = amountAt(s, index);
    const amount =
      positive(share) && differs(share, state.total)
        ? `${formatMoney(share, grouping)}${r.choice === null ? " left" : ""}`
        : "";
    const when = r.postedOn !== null && r.postedOn !== state.date ? `Posts ${shortDate(r.postedOn, today)}` : "";
    return { when, amount };
  };

  const status = (s: Side): string => {
    if (!positive(state.total)) return "";
    const shares = state[s].map((_, index) => amountAt(s, index));
    const sum = allocation(state.total, shares, places);
    if (sum.balanced) return ""; // balanced is the normal state, so nothing is said about it
    const figure = formatMoney(sum.over ? sum.left.replace("-", "") : sum.left, grouping);
    const money = code ? `${figure} ${code}` : figure;
    return sum.over ? `${money} over` : `${money} left to allocate`;
  };

  const side = (s: Side) => {
    const title = KINDS[state.kind][s].title;
    const category = isCategorySide(state.kind, s);
    const said = status(s);
    return (
      <section key={s} className={styles.side}>
        <h2 id={ids[s]} className={styles.sideTitle}>
          {title}
        </h2>
        {state[s].map((r, index) => {
          const label = labelOf(r.choice, groups);
          const { when, amount } = describe(s, index, r);
          const valueId = `${ids[s]}-${r.key}`;
          return (
            <div key={r.key} className={styles.row}>
              <div className={styles.rowLine}>
                <button
                  type="button"
                  className={`${styles.rowPick} ${label === null ? styles.empty : category ? styles.onCategory : styles.onAccount}`}
                  aria-labelledby={`${ids[s]} ${valueId}`}
                  onClick={() => {
                    setPicking({ side: s, index, category: false });
                  }}
                >
                  <span id={valueId} className={styles.rowName}>
                    <span className={label ? undefined : styles.placeholder}>
                      {label ?? (category ? "Category…" : "Account…")}
                    </span>
                    {when && <span className={styles.rowWhen}>{when}</span>}
                    {amount && <span className={styles.rowAmount}>{amount}</span>}
                  </span>
                </button>
                {r.choice !== null && (
                  <button
                    type="button"
                    className={when || amount ? `${styles.rowSettings} ${styles.set}` : styles.rowSettings}
                    aria-haspopup="dialog"
                    aria-label="Amount and date"
                    onClick={() => {
                      setTuning({ side: s, index });
                    }}
                  />
                )}
              </div>
              {shownCategory(s, r) && (
                <button
                  type="button"
                  className={styles.rowCategory}
                  onClick={() => {
                    setPicking({ side: s, index, category: true });
                  }}
                >
                  <span>Category</span>
                  <span className={r.category ? undefined : styles.placeholder}>
                    {labelOf(r.category, groups) ?? "No category"}
                  </span>
                </button>
              )}
            </div>
          );
        })}
        {said && (
          <p className={styles.status} aria-live="polite">
            {said}
          </p>
        )}
      </section>
    );
  };

  const [first, second] = screenOrder(state.kind);
  const pickingGroups = picking
    ? picking.category
      ? categoryGroups(groups)
      : offered(state.kind, picking.side, groups)
    : [];
  const tunedRow = tuning ? state[tuning.side][tuning.index] : undefined;

  return (
    <>
      <div
        className={styles.kinds}
        role="group"
        aria-label="What kind of entry (tap the selected one again to offer every account)"
      >
        {(["expense", "income", "transfer"] as const).map((k) => (
          <button
            key={k}
            type="button"
            aria-pressed={state.kind === k}
            onClick={() => {
              chooseKind(k);
            }}
          >
            {k === "expense" ? "Expense" : k === "income" ? "Income" : "Transfer"}
          </button>
        ))}
      </div>

      <div className={styles.total}>
        {symbol === "₹" && <span className={styles.symbol}>₹</span>}
        <AmountField
          id="total"
          label="Amount"
          big
          groupAsTyped
          // eslint-disable-next-line jsx-a11y-x/no-autofocus -- only on a computer, where it raises no keypad (the screen decides)
          autoFocus={autoFocus}
          value={state.total}
          onChange={(total) => {
            update((now) => ({ ...now, total }));
          }}
          places={places}
          grouping={grouping}
        />
        {symbol !== "₹" && <span className={styles.code}>{symbol}</span>}
      </div>

      {children}

      {!hideSides && side(first ?? "credit")}
      {!hideSides && canSwap(state.kind) && (
        <div className={styles.swapRow}>
          <button
            type="button"
            className={styles.swap}
            aria-label="Swap From and To"
            title="Swap From and To"
            onClick={swap}
          >
            <Icon name="swap" />
          </button>
        </div>
      )}
      {!hideSides && side(second ?? "debit")}

      {/* The sheets sit outside the screen's form, as they did before the rows were shared: a sheet's own form must not
          submit the screen's (React carries a submit up through a portal, so it is stopped here too). */}
      {createPortal(
        <div
          onSubmit={(event) => {
            event.stopPropagation();
          }}
        >
          {picking && (
            <Picker
              open
              title={picking.category ? "Category" : KINDS[state.kind][picking.side].title}
              groups={pickingGroups}
              value={
                picking.category
                  ? (state[picking.side][picking.index]?.category ?? null)
                  : (state[picking.side][picking.index]?.choice ?? null)
              }
              otherSide={picking.category ? null : firstChoice(state[other(picking.side)])}
              {...(picking.category
                ? { clearable: "No category" }
                : {
                    onNew: {
                      noun: quickKind(state.kind, picking.side).what,
                      open: () => {
                        setMaking({ ...picking, kind: quickKind(state.kind, picking.side) });
                      },
                    },
                  })}
              onChange={(id) => {
                changeRow(
                  picking.side,
                  picking.index,
                  picking.category ? { category: id } : { choice: id, category: null },
                );
              }}
              onClose={() => {
                setPicking(null);
              }}
            />
          )}
          {making && (
            <QuickAdd
              making={making.kind}
              accountParents={accountParents}
              categoryParents={categoryParents}
              onMade={(id) => {
                changeRow(making.side, making.index, { choice: id, category: null });
              }}
              onClose={() => {
                setMaking(null);
              }}
            />
          )}
          {tuning && (
            <RowSettings
              key={`${tuning.side}-${String(tuning.index)}`}
              title={labelOf(tunedRow?.choice ?? null, groups) ?? ""}
              amount={groupAmount(amountAt(tuning.side, tuning.index), grouping)}
              date={dated && isAccount(tunedRow?.choice ?? null, groups) ? (tunedRow?.postedOn ?? state.date) : null}
              entryDate={state.date}
              canRemove={state[tuning.side].length > 1}
              onDone={(amount, date) => {
                const { side: s, index } = tuning;
                const shown = amountAt(s, index);
                const postedOn = date !== null && date !== "" && date !== state.date ? date : null;
                changeRow(
                  s,
                  index,
                  sameAmount(amount, shown)
                    ? { postedOn }
                    : {
                        postedOn,
                        amount: groupAmount(tidyAmount(amount, places), grouping),
                        touched: amount.trim() !== "",
                      },
                );
              }}
              onRemove={() => {
                const { side: s, index } = tuning;
                update((now) => ({ ...now, [s]: removeRow(now[s], index, isCategorySide(now.kind, s)) }));
              }}
              onClose={() => {
                setTuning(null);
              }}
            />
          )}
        </div>,
        document.body,
      )}
    </>
  );
}

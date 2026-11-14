// The Add / Edit screen (transaction_form.html, txn_rows.html): what kind of entry, the amount, where the money came from
// and went (rows on each side, chosen in our own picker, each with its own amount and posting day from its settings),
// and for a payment into a loan or fund what it was for. The server decides what the choices record
// (services/entry.py); this screen only sends them.
import { useId, useState } from "react";
import { Link, useNavigate } from "react-router";

import { messageOf } from "../../api/messages";
import { useSubmitOnce } from "../../api/useSubmitOnce";
import { useCurrency, useGrouping, usePlaces, useSymbol } from "../../app/currency";
import { useToday } from "../../app/session";
import { useToast } from "../../app/toast";
import { AmountField } from "../../components/AmountField";
import { Icon } from "../../components/Icon";
import { groupAmount, tidyAmount } from "../../lib/amount";
import { shortDate } from "../../lib/dates";
import { formatMoney } from "../../lib/money";
import { safeNext } from "../../lib/safeNext";
import { allocation, differs, positive, sameAmount } from "../../lib/split";
import { useDeleteTransaction } from "../transactions/queries";
import styles from "./EntryScreen.module.css";
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
import { DateChip } from "./DateChip";
import { NoteAndTags } from "./NoteAndTags";
import { PayeeField } from "./PayeeField";
import { Picker } from "./Picker";
import { Related } from "./RelatedPicker";
import { QuickAdd, type QuickKind } from "./QuickAdd";
import { RowSettings } from "./RowSettings";
import {
  carryExpense,
  carryIncome,
  expenseBody,
  type ExpenseShareState,
  incomeBody,
  type IncomeShareState,
  startExpense,
  startIncome,
} from "./share";
import { ExpenseShareEditor, IncomeShareEditor } from "./ShareEditor";
import styles2 from "./ShareEditor.module.css";
import { SharePreview } from "./SharePreview";
import { amountOf, datesFrom, removeRow, type RowState, settle, startRows } from "./rows";
import { type EntryBody, type EntryFormView, type PickGroup, useSaveEntry } from "./queries";

const ASK = "Delete this transaction? Account balances will change. This cannot be undone.";

export interface EntryState {
  kind: Kind;
  total: string;
  payee: string;
  payeePerson: { id: string; name: string } | null;
  date: string;
  credit: RowState[];
  debit: RowState[];
  comment: string;
  tags: string[];
  related: EntryFormView["related"];
  /** "split": an expense or an income shared with people. */
  mode: "simple" | "split";
  expenseShare: ExpenseShareState;
  incomeShare: IncomeShareState;
}

export function startState(form: EntryFormView, grouping: Parameters<typeof groupAmount>[1]): EntryState {
  return {
    kind: form.kind,
    total: form.total ? groupAmount(form.total, grouping) : "",
    payee: form.payee,
    payeePerson: form.payee_person,
    date: form.date,
    credit: startRows(form.from_rows, grouping),
    debit: startRows(form.to_rows, grouping),
    comment: form.comment,
    tags: form.tags,
    related: form.related,
    mode: form.mode,
    expenseShare: startExpense(form.expense_share, grouping),
    incomeShare: startIncome(form.income_share, grouping),
  };
}

const shareable = (kind: Kind) => kind === "expense" || kind === "income";

/** What "＋ New" makes on a side: a category where the side lists categories, else an account under its first root
 * (app.js suggestedRoot). */
function quickKind(kind: Kind, side: Side): QuickKind {
  const root = KINDS[kind][side].roots?.[0] ?? (side === "debit" ? "Expenses" : "Assets");
  if (root === "Expenses") return { what: "category", kind: "spending" };
  if (root === "Income") return { what: "category", kind: "earning" };
  return { what: "account", root };
}

function categoryGroups(groups: PickGroup[]): PickGroup[] {
  return groups.filter((g) => g.title === "Expenses" || g.title === "Income");
}

/** On a computer the amount takes the focus at once; on a phone that would raise the keypad over the screen. */
function onComputer(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(hover: hover) and (pointer: fine)").matches;
}

interface ScreenProps {
  form: EntryFormView;
  /** The entry being edited. */
  transactionId?: string;
  /** Where to go after saving or deleting (inside the app only). */
  back?: string | null;
}

function firstChoice(rows: RowState[]): string | null {
  return rows.find((r) => r.choice !== null)?.choice ?? null;
}

export function EntryScreen({ form, transactionId, back = null }: ScreenProps) {
  const grouping = useGrouping();
  const places = usePlaces();
  const symbol = useSymbol();
  const code = useCurrency();
  const today = useToday();
  const navigate = useNavigate();
  const toast = useToast();
  const save = useSaveEntry(transactionId);
  const remove = useDeleteTransaction();
  const submit = useSubmitOnce(save);
  const [state, setState] = useState<EntryState>(() => startState(form, grouping));
  const [picking, setPicking] = useState<{ side: Side; index: number; category: boolean } | null>(null);
  const [tuning, setTuning] = useState<{ side: Side; index: number } | null>(null);
  const [making, setMaking] = useState<{ side: Side; index: number; kind: QuickKind } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const ids = { credit: useId(), debit: useId() };
  const groups = form.groups;
  const editing = transactionId !== undefined;
  const leave = () => void navigate(back ? safeNext(back) : "/transactions", { replace: true });

  // Every change leaves both sides tidied: an open row for what is left, no spare empty rows.
  const update = (next: (now: EntryState) => EntryState) => {
    setState((now) => {
      const after = next(now);
      return {
        ...after,
        credit: settle(after.credit, after.total, places),
        debit: settle(after.debit, after.total, places),
      };
    });
  };
  const change = (next: Partial<EntryState>) => {
    update((now) => ({ ...now, ...next }));
  };
  const changeRow = (side: Side, index: number, next: Partial<RowState>) => {
    update((now) => ({ ...now, [side]: now[side].map((r, i) => (i === index ? { ...r, ...next } : r)) }));
  };

  const chooseKind = (tapped: Kind) => {
    update((now) => {
      const kind: Kind = tapped === now.kind ? "other" : tapped;
      const keep = (side: Side): RowState[] =>
        now[side].map((r) => (keepsChoice(kind, side, r.choice, groups) ? r : { ...r, choice: null, category: null }));
      const withPerson = kind === "expense" || kind === "income";
      return {
        ...now,
        kind,
        // A transfer has no Split; coming back to an expense or income starts Simple (the people stay ticked).
        mode: shareable(kind) && shareable(now.kind) ? now.mode : "simple",
        credit: keep("credit"),
        debit: keep("debit"),
        payeePerson: withPerson ? now.payeePerson : null,
      };
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

  const split = state.mode === "split" && shareable(state.kind);

  const chooseMode = (mode: "simple" | "split") => {
    update((now) => {
      if (mode === "simple") return { ...now, mode };
      return {
        ...now,
        mode,
        payeePerson: null,
        expenseShare: carryExpense(now.expenseShare, firstChoice(now.credit), firstChoice(now.debit), groups),
        incomeShare: carryIncome(now.incomeShare, firstChoice(now.credit), firstChoice(now.debit), groups),
      };
    });
  };

  const shareOf = (now: EntryState) =>
    now.kind === "income" ? incomeBody(now.incomeShare, places) : expenseBody(now.expenseShare, places);

  const other = (side: Side): Side => (side === "credit" ? "debit" : "credit");
  const shownCategory = (side: Side, row: RowState): boolean =>
    rowCategoryShown(row.choice, firstChoice(state[other(side)]), groups);
  const amountAt = (side: Side, index: number) => amountOf(state[side], index, state.total, places);

  const send = () => {
    setProblem(null);
    const amount = tidyAmount(state.total, places).replace(/,/g, "");
    if (!amount || !/^-?\d+(\.\d+)?$/.test(amount)) {
      setProblem("Enter the amount.");
      return;
    }
    if (split) {
      const body: EntryBody = {
        kind: state.kind,
        date: state.date,
        payee: state.payee,
        comment: state.comment,
        tags: state.tags,
        related_id: state.related?.id ?? null,
        payee_contact: null,
        rows: [],
        total: amount,
        share: shareOf(state),
      };
      submit(body, {
        onSuccess: () => {
          toast(editing ? "Transaction updated" : state.kind === "income" ? "Income recorded" : "Expense recorded");
          leave();
        },
      });
      return;
    }
    const rows: EntryBody["rows"] = [];
    for (const s of ["credit", "debit"] as const) {
      const before = rows.length;
      for (const [index, r] of state[s].entries()) {
        const typed = amountAt(s, index);
        if (r.choice === null && typed === "") continue; // an untouched blank row
        if (r.choice === null || typed === "") {
          setProblem(r.choice === null ? "every posting needs an account!" : "amount is required!");
          return;
        }
        rows.push({
          choice: r.choice,
          side: s,
          amount: tidyAmount(typed, places).replace(/,/g, ""),
          category_id: shownCategory(s, r) ? r.category : null,
          posted_on: r.postedOn,
        });
      }
      if (rows.length === before) {
        setProblem("every posting needs an account!");
        return;
      }
    }
    const body: EntryBody = {
      kind: state.kind,
      date: state.date,
      payee: state.payee,
      comment: state.comment,
      tags: state.tags,
      related_id: state.related?.id ?? null,
      payee_contact: state.payeePerson?.id ?? null,
      rows,
    };
    submit(body, {
      onSuccess: (saved) => {
        toast(editing ? "Transaction updated" : saved.recorded === "transfer" ? "Recorded" : "Transaction saved");
        leave();
      },
    });
  };

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
                  className={styles.rowPick}
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
                  <Icon name="caret" />
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

  return (
    <>
      <Link className={styles.back} to={back ? safeNext(back) : "/transactions"}>
        <Icon name="back" />
        Back
      </Link>
      <h1 className="sr-only">{editing ? "Edit transaction" : "New transaction"}</h1>
      <form
        className={styles.form}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          send();
        }}
      >
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
            autoFocus={!editing && onComputer()}
            value={state.total}
            onChange={(total) => {
              change({ total });
            }}
            places={places}
            grouping={grouping}
          />
          {symbol !== "₹" && <span className={styles.code}>{symbol}</span>}
        </div>

        <PayeeField
          value={state.payee}
          onChange={(payee) => {
            change({ payee });
          }}
          person={state.payeePerson}
          onPerson={(payeePerson) => {
            change({ payeePerson });
          }}
          editing={editing}
          canName={shareable(state.kind) && !split}
        />
        <div className={styles.metaRow}>
          <DateChip
            value={state.date}
            onChange={(date) => {
              update((now) => ({
                ...now,
                date,
                credit: datesFrom(now.credit, date),
                debit: datesFrom(now.debit, date),
              }));
            }}
          />
          <Related
            value={state.related}
            exclude={transactionId}
            onChange={(related) => {
              change({ related });
            }}
          />
        </div>

        {shareable(state.kind) && (
          <div className={styles2.seg} role="radiogroup" aria-label="How it is recorded">
            {(["simple", "split"] as const).map((m) => (
              <label key={m}>
                <input
                  type="radio"
                  name="mode"
                  checked={state.mode === m}
                  onChange={() => {
                    chooseMode(m);
                  }}
                />
                <span>{m === "simple" ? "Simple" : "Split"}</span>
              </label>
            ))}
          </div>
        )}

        {split && state.kind === "expense" && (
          <ExpenseShareEditor
            share={state.expenseShare}
            people={form.people}
            groups={groups}
            onChange={(expenseShare) => {
              change({ expenseShare });
            }}
          />
        )}
        {split && state.kind === "income" && (
          <IncomeShareEditor
            share={state.incomeShare}
            people={form.people}
            groups={groups}
            onChange={(incomeShare) => {
              change({ incomeShare });
            }}
          />
        )}
        {split && form.people.length > 0 && (
          <SharePreview
            ask={
              positive(state.total)
                ? {
                    total: tidyAmount(state.total, places).replace(/,/g, ""),
                    date: state.date,
                    payee: state.payee,
                    share: shareOf(state),
                  }
                : null
            }
          />
        )}

        {!split && side(first ?? "credit")}
        {!split && canSwap(state.kind) && (
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
        {!split && side(second ?? "debit")}

        <NoteAndTags
          note={state.comment}
          onNote={(comment) => {
            change({ comment });
          }}
          tags={state.tags}
          onTags={(tags) => {
            change({ tags });
          }}
        />

        {(problem ?? (save.isError ? messageOf(save.error) : null)) && (
          <p className={styles.error} role="alert">
            {problem ?? messageOf(save.error)}
          </p>
        )}
        <div className={styles.actions}>
          <button type="submit" className={styles.primary} disabled={save.isPending} aria-busy={save.isPending}>
            {editing ? "Save changes" : "Save"}
          </button>
        </div>
      </form>

      {editing && (
        <section className={styles.danger}>
          {remove.isError && (
            <p className={styles.error} role="alert">
              {messageOf(remove.error)}
            </p>
          )}
          <button
            type="button"
            className={styles.dangerButton}
            disabled={remove.isPending}
            onClick={() => {
              if (!window.confirm(ASK)) return;
              remove.mutate(transactionId, { onSuccess: leave });
            }}
          >
            <Icon name="trash" />
            Delete transaction
          </button>
        </section>
      )}

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
          accountParents={form.account_parents}
          categoryParents={form.category_parents}
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
          title={labelOf(state[tuning.side][tuning.index]?.choice ?? null, groups) ?? ""}
          amount={groupAmount(amountAt(tuning.side, tuning.index), grouping)}
          date={
            isAccount(state[tuning.side][tuning.index]?.choice ?? null, groups)
              ? (state[tuning.side][tuning.index]?.postedOn ?? state.date)
              : null
          }
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
    </>
  );
}

// The Add / Edit screen in its Simple mode (transaction_form.html, txn_rows.html): what kind of entry, the amount, where
// the money came from and went (one row each side, chosen in our own picker), and for a payment into a loan or fund what
// it was for. The server decides what the choices record (services/entry.py); this screen only sends them.
import { useId, useState } from "react";
import { Link, useNavigate } from "react-router";

import { messageOf } from "../../api/messages";
import { useSubmitOnce } from "../../api/useSubmitOnce";
import { useGrouping, usePlaces, useSymbol } from "../../app/currency";
import { useToast } from "../../app/toast";
import { AmountField } from "../../components/AmountField";
import { Icon } from "../../components/Icon";
import { groupAmount, tidyAmount } from "../../lib/amount";
import { safeNext } from "../../lib/safeNext";
import { useDeleteTransaction } from "../transactions/queries";
import styles from "./EntryScreen.module.css";
import {
  canSwap,
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
import { type EntryBody, type EntryFormView, type PickGroup, useSaveEntry } from "./queries";

const ASK = "Delete this transaction? Account balances will change. This cannot be undone.";

interface RowState {
  choice: string | null;
  category: string | null;
}

export interface EntryState {
  kind: Kind;
  total: string;
  payee: string;
  payeePerson: { id: string; name: string } | null;
  date: string;
  credit: RowState;
  debit: RowState;
  comment: string;
  tags: string[];
  related: EntryFormView["related"];
}

export function startState(form: EntryFormView, grouping: Parameters<typeof groupAmount>[1]): EntryState {
  const row = (rows: EntryFormView["from_rows"]): RowState => ({
    choice: rows[0]?.choice ?? null,
    category: rows[0]?.category_id ?? null,
  });
  return {
    kind: form.kind,
    total: form.total ? groupAmount(form.total, grouping) : "",
    payee: form.payee,
    payeePerson: form.payee_person,
    date: form.date,
    credit: row(form.from_rows),
    debit: row(form.to_rows),
    comment: form.comment,
    tags: form.tags,
    related: form.related,
  };
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

export function EntryScreen({ form, transactionId, back = null }: ScreenProps) {
  const grouping = useGrouping();
  const places = usePlaces();
  const symbol = useSymbol();
  const navigate = useNavigate();
  const toast = useToast();
  const save = useSaveEntry(transactionId);
  const remove = useDeleteTransaction();
  const submit = useSubmitOnce(save);
  const [state, setState] = useState<EntryState>(() => startState(form, grouping));
  const [picking, setPicking] = useState<{ side: Side; category: boolean } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const ids = { credit: useId(), debit: useId() };
  const groups = form.groups;
  const editing = transactionId !== undefined;
  const leave = () => void navigate(back ? safeNext(back) : "/transactions", { replace: true });

  const change = (next: Partial<EntryState>) => {
    setState((now) => ({ ...now, ...next }));
  };

  const chooseKind = (tapped: Kind) => {
    setState((now) => {
      const kind: Kind = tapped === now.kind ? "other" : tapped;
      const keep = (side: Side): RowState =>
        keepsChoice(kind, side, now[side].choice, groups) ? now[side] : { choice: null, category: null };
      const withPerson = kind === "expense" || kind === "income";
      return {
        ...now,
        kind,
        credit: keep("credit"),
        debit: keep("debit"),
        payeePerson: withPerson ? now.payeePerson : null,
      };
    });
  };

  const swap = () => {
    setState((now) => ({
      ...now,
      credit: now.debit,
      debit: now.credit,
      // An expense turned round is no longer an expense (a refund, say): every account is offered again.
      kind: now.kind === "transfer" ? "transfer" : "other",
    }));
  };

  const shownCategory = (side: Side): boolean =>
    rowCategoryShown(state[side].choice, state[side === "credit" ? "debit" : "credit"].choice, groups);

  const send = () => {
    setProblem(null);
    const amount = tidyAmount(state.total, places).replace(/,/g, "");
    if (!amount || !/^-?\d+(\.\d+)?$/.test(amount)) {
      setProblem("Enter the amount.");
      return;
    }
    if (!state.credit.choice || !state.debit.choice) {
      setProblem("every posting needs an account!");
      return;
    }
    const row = (side: Side) => ({
      choice: state[side].choice ?? "",
      side,
      amount,
      category_id: shownCategory(side) ? state[side].category : null,
    });
    const body: EntryBody = {
      kind: state.kind,
      date: state.date,
      payee: state.payee,
      comment: state.comment,
      tags: state.tags,
      related_id: state.related?.id ?? null,
      payee_contact: state.payeePerson?.id ?? null,
      rows: [row("credit"), row("debit")],
    };
    submit(body, {
      onSuccess: (saved) => {
        toast(editing ? "Transaction updated" : saved.recorded === "transfer" ? "Recorded" : "Transaction saved");
        leave();
      },
    });
  };

  const side = (s: Side) => {
    const title = KINDS[state.kind][s].title;
    const label = labelOf(state[s].choice, groups);
    const category = isCategorySide(state.kind, s);
    return (
      <section key={s} className={styles.side}>
        <h2 id={ids[s]} className={styles.sideTitle}>
          {title}
        </h2>
        <button
          type="button"
          className={styles.rowPick}
          aria-labelledby={`${ids[s]} ${ids[s]}-value`}
          onClick={() => {
            setPicking({ side: s, category: false });
          }}
        >
          <span id={`${ids[s]}-value`} className={label ? undefined : styles.placeholder}>
            {label ?? (category ? "Category…" : "Account…")}
          </span>
          <Icon name="caret" />
        </button>
        {shownCategory(s) && (
          <button
            type="button"
            className={styles.rowCategory}
            onClick={() => {
              setPicking({ side: s, category: true });
            }}
          >
            <span>Category</span>
            <span className={state[s].category ? undefined : styles.placeholder}>
              {labelOf(state[s].category, groups) ?? "No category"}
            </span>
          </button>
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
          canName={state.kind === "expense" || state.kind === "income"}
        />
        <div className={styles.metaRow}>
          <DateChip
            value={state.date}
            onChange={(date) => {
              change({ date });
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

        {side(first ?? "credit")}
        {canSwap(state.kind) && (
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
        {side(second ?? "debit")}

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
          value={picking.category ? state[picking.side].category : state[picking.side].choice}
          otherSide={picking.category ? null : state[picking.side === "credit" ? "debit" : "credit"].choice}
          {...(picking.category ? { clearable: "No category" } : {})}
          onChange={(id) => {
            const s = picking.side;
            change(picking.category ? { [s]: { ...state[s], category: id } } : { [s]: { choice: id, category: null } });
          }}
          onClose={() => {
            setPicking(null);
          }}
        />
      )}
    </>
  );
}

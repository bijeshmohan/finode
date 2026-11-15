// The Add / Edit screen (transaction_form.html, txn_rows.html): what kind of entry, the amount, where the money came from
// and went (rows on each side, chosen in our own picker, each with its own amount and posting day from its settings),
// and for a payment into a loan or fund what it was for. The server decides what the choices record
// (services/entry.py); this screen only sends them.
import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { messageOf } from "../../api/messages";
import { useSubmitOnce } from "../../api/useSubmitOnce";
import { useGrouping, usePlaces } from "../../app/currency";
import { useToast } from "../../app/toast";
import { Icon } from "../../components/Icon";
import { DateChip } from "../../components/lines/DateChip";
import type { Kind } from "../../components/lines/kinds";
import { Lines, linesBody, type LinesState, useLines } from "../../components/lines/Lines";
import { datesFrom, type RowState, startRows } from "../../components/lines/rows";
import { groupAmount, tidyAmount } from "../../lib/amount";
import { safeNext } from "../../lib/safeNext";
import { positive } from "../../lib/split";
import { useDeleteTransaction } from "../transactions/queries";
import styles from "./EntryScreen.module.css";
import { NoteAndTags } from "./NoteAndTags";
import { PayeeField } from "./PayeeField";
import { Related } from "./RelatedPicker";
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
import { type EntryBody, type EntryFormView, useSaveEntry } from "./queries";

const ASK = "Delete this transaction? Account balances will change. This cannot be undone.";

export interface EntryState extends LinesState {
  payee: string;
  payeePerson: { id: string; name: string } | null;
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
  const navigate = useNavigate();
  const toast = useToast();
  const save = useSaveEntry(transactionId);
  const remove = useDeleteTransaction();
  const submit = useSubmitOnce(save);
  const [state, update] = useLines<EntryState>(() => startState(form, grouping));
  const [problem, setProblem] = useState<string | null>(null);
  const groups = form.groups;
  const editing = transactionId !== undefined;
  const leave = () => void navigate(back ? safeNext(back) : "/transactions", { replace: true });

  const change = (next: Partial<EntryState>) => {
    update((now) => ({ ...now, ...next }));
  };

  // A transfer has no Split; coming back to an expense or income starts Simple (the people stay ticked). A person is
  // named only on an expense or an income.
  const kindChanged = (after: EntryState, before: EntryState): EntryState => {
    const withPerson = after.kind === "expense" || after.kind === "income";
    return {
      ...after,
      mode: shareable(after.kind) && shareable(before.kind) ? before.mode : "simple",
      payeePerson: withPerson ? before.payeePerson : null,
    };
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
    now.kind === "income" ? incomeBody(now.incomeShare) : expenseBody(now.expenseShare);

  const send = () => {
    setProblem(null);
    if (split) {
      const amount = tidyAmount(state.total, places).replace(/,/g, "");
      if (!amount || !/^-?\d+(\.\d+)?$/.test(amount)) {
        setProblem("Enter the amount.");
        return;
      }
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
    const lines = linesBody(state, groups, places);
    if (lines.problem !== undefined) {
      setProblem(lines.problem);
      return;
    }
    const body: EntryBody = {
      kind: state.kind,
      date: state.date,
      payee: state.payee,
      comment: state.comment,
      tags: state.tags,
      related_id: state.related?.id ?? null,
      payee_contact: state.payeePerson?.id ?? null,
      rows: lines.rows,
    };
    submit(body, {
      onSuccess: (saved) => {
        toast(editing ? "Transaction updated" : saved.recorded === "transfer" ? "Recorded" : "Transaction saved");
        leave();
      },
    });
  };

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
        <Lines
          state={state}
          update={update}
          groups={groups}
          accountParents={form.account_parents}
          categoryParents={form.category_parents}
          dated
          autoFocus={!editing && onComputer()}
          onKind={kindChanged}
          hideSides={split}
        >
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
        </Lines>

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
    </>
  );
}

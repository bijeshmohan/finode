// Adding or editing an account. A new one picks its type first (Bank Account, Cash, Credit Card or Prepaid Wallet, in
// the person's order); an account keeps its type. A Credit Card takes its bill days. Every account is part of the
// budget. An edit sends only what changed: a new balance records an adjustment against Opening Balances, so it is never
// sent unchanged.
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { messageOf } from "../../api/messages";
import { useGrouping, usePlaces, useSymbol } from "../../app/currency";
import { useToast } from "../../app/toast";
import { AmountField } from "../../components/AmountField";
import { Chips } from "../../components/Chips";
import { Icon } from "../../components/Icon";
import { LoadError } from "../../components/LoadError";
import { groupAmount, tidyAmount } from "../../lib/amount";
import { sameAmount } from "../../lib/split";
import look from "../../components/Page.module.css";
import form from "../../components/Forms.module.css";
import {
  type AccountFormView,
  type AccountType,
  type AccountUpdate,
  useAccountForm,
  useAddAccountFromForm,
  useDeleteAccount,
  useUpdateAccount,
} from "./queries";

type Rounding = AccountFormView["bill_rounding"];

/** A day of the month as typed, or null when empty; undefined when it is not a number. */
function day(text: string): number | null | undefined {
  const t = text.trim();
  if (!t) return null;
  return /^\d{1,2}$/.test(t) ? Number(t) : undefined;
}

function FormBody({ view, accountId }: { view: AccountFormView; accountId: string | undefined }) {
  const grouping = useGrouping();
  const places = usePlaces();
  const sign = useSymbol();
  const toast = useToast();
  const navigate = useNavigate();
  const add = useAddAccountFromForm();
  const update = useUpdateAccount(accountId ?? "");
  const remove = useDeleteAccount(accountId ?? "");
  const editing = view.editing;
  const [name, setName] = useState(view.name);
  const [type, setType] = useState<AccountType | null>(view.type);
  const [balance, setBalance] = useState(view.balance ? groupAmount(view.balance, grouping) : "");
  const [statement, setStatement] = useState(view.statement_day?.toString() ?? "");
  const [due, setDue] = useState(view.due_day?.toString() ?? "");
  const [rounding, setRounding] = useState<Rounding>(view.bill_rounding);
  const [note, setNote] = useState(view.details ?? "");
  const [problem, setProblem] = useState<string | null>(null);
  const canBill = type === "liabilities.cards";
  const balanceLabel = canBill ? "Amount you owe now" : editing ? "Balance" : "Current balance";
  const pending = add.isPending || update.isPending;
  const back = editing && accountId ? `/accounts/${accountId}` : "/accounts";

  const submit = () => {
    setProblem(null);
    const statementDay = day(statement);
    const dueDay = day(due);
    if (canBill && (statementDay === undefined || dueDay === undefined)) {
      setProblem("the statement day and the due day are numbers from 1 to 31!");
      return;
    }
    const plainBalance = balance.trim() ? tidyAmount(balance, places).replace(/,/g, "") : "";
    const details = note.trim() || null;
    if (!editing) {
      if (!type) {
        setProblem("choose what kind of account it is!");
        return;
      }
      add.mutate(
        {
          name: name.trim(),
          type,
          details,
          balance: plainBalance || "0",
          ...(canBill ? { statement_day: statementDay ?? null, due_day: dueDay ?? null } : {}),
          bill_rounding: canBill ? rounding : "none",
        },
        {
          onSuccess: (made) => {
            toast("Account added");
            void navigate(`/accounts/${made.id}`, { replace: true });
          },
          onError: (e) => {
            setProblem(messageOf(e));
          },
        },
      );
      return;
    }
    const changes: AccountUpdate = {};
    if (name.trim() !== view.name) changes.name = name.trim();
    if (details !== view.details) changes.details = details;
    if (plainBalance && view.balance !== null && !sameAmount(plainBalance, view.balance))
      changes.balance = plainBalance;
    if (
      canBill &&
      (statementDay !== view.statement_day || dueDay !== view.due_day || rounding !== view.bill_rounding)
    ) {
      changes.statement_day = statementDay ?? null;
      changes.due_day = dueDay ?? null;
      changes.bill_rounding = rounding;
    }
    if (Object.keys(changes).length === 0) {
      void navigate(back);
      return;
    }
    update.mutate(changes, {
      onSuccess: () => {
        toast("Account updated");
        void navigate(back);
      },
      onError: (e) => {
        setProblem(messageOf(e));
      },
    });
  };

  return (
    <>
      <Link className={look.back} to={back}>
        <Icon name="back" />
        {editing ? view.name : "Accounts"}
      </Link>
      <h1 className={form.title}>{editing ? "Edit account" : "Add account"}</h1>
      <form
        className={form.form}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <label>
          Name
          <input
            type="text"
            maxLength={40}
            required
            placeholder="e.g. HDFC Savings"
            autoFocus={!editing}
            value={name}
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
        </label>
        {!editing && (
          <div className={form.field}>
            <span>Kind</span>
            <Chips
              label="Kind of account"
              options={view.types.map((t) => ({ value: t.key, label: t.name }))}
              value={type ?? ""}
              onChange={(value) => {
                setType(value as AccountType);
              }}
            />
          </div>
        )}
        <div className={form.field}>
          <AmountField
            id="account-balance"
            label={balanceLabel}
            value={balance}
            onChange={setBalance}
            places={places}
            grouping={grouping}
          />
          {editing && <span className={form.hint}>Changing this records an adjustment against Opening Balances.</span>}
        </div>
        {canBill && (
          <div className={form.billDays}>
            <label>
              Statement day
              <input
                type="text"
                inputMode="numeric"
                maxLength={2}
                autoComplete="off"
                placeholder="22"
                value={statement}
                onChange={(event) => {
                  setStatement(event.target.value);
                }}
              />
              <span className={form.hint}>The day of the month your bank closes the bill</span>
            </label>
            <label>
              Payment due day
              <input
                type="text"
                inputMode="numeric"
                maxLength={2}
                autoComplete="off"
                placeholder="15"
                value={due}
                onChange={(event) => {
                  setDue(event.target.value);
                }}
              />
              <span className={form.hint}>The day it must be paid by. 31 means the last day of the month</span>
            </label>
            <label>
              Round the bill
              <select
                value={rounding}
                onChange={(event) => {
                  setRounding(event.target.value as Rounding);
                }}
              >
                <option value="none">Exactly, to the paisa</option>
                <option value="nearest">To the nearest {sign}1</option>
                <option value="up">Up to the next {sign}1</option>
              </select>
              <span className={form.hint}>How your bank rounds what you owe</span>
            </label>
          </div>
        )}
        <details className={form.note} open={view.details ? true : undefined}>
          <summary>{view.details ? "Note" : "+ Add a note"}</summary>
          <label>
            <input
              type="text"
              maxLength={200}
              aria-label="Notes"
              value={note}
              onChange={(event) => {
                setNote(event.target.value);
              }}
            />
          </label>
        </details>
        {problem && (
          <p className={form.error} role="alert">
            {problem}
          </p>
        )}
        <div>
          <button type="submit" className={form.primary} disabled={pending} aria-busy={pending}>
            {editing ? "Save changes" : "Add account"}
          </button>
        </div>
      </form>

      {editing && accountId && (
        <section className={form.danger}>
          {remove.isError && (
            <p className={form.error} role="alert">
              {messageOf(remove.error)}
            </p>
          )}
          <button
            type="button"
            className={form.dangerButton}
            disabled={remove.isPending}
            onClick={() => {
              if (!window.confirm(`Delete account '${view.name}'?`)) return;
              remove.mutate(undefined, {
                onSuccess: () => {
                  toast("Account deleted");
                  void navigate("/accounts", { replace: true });
                },
              });
            }}
          >
            <Icon name="trash" />
            Delete account
          </button>
          <p className={form.dangerHint}>Only an account without transactions can be deleted.</p>
        </section>
      )}
    </>
  );
}

/** /accounts/new (?type=) and /accounts/:accountId/edit. */
export function AccountForm() {
  const { accountId } = useParams();
  const [params] = useSearchParams();
  const query: { account_id?: string; type?: string } = accountId ? { account_id: accountId } : {};
  const type = params.get("type");
  if (!accountId && type) query.type = type;
  const view = useAccountForm(query);
  if (view.isError) return <LoadError error={view.error} onRetry={() => void view.refetch()} />;
  if (!view.data) return <h1 className="sr-only">{accountId ? "Edit account" : "Add account"}</h1>;
  return <FormBody key={JSON.stringify(query)} view={view.data} accountId={accountId} />;
}

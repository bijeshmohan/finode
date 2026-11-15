// Adding or editing what a person already owed before finode (person_opening.html). Once part of it was paid back, who
// owes whom stays as it is and the amount can't go below what was paid (the server says so).
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { messageOf } from "../../api/messages";
import { useGrouping, usePlaces } from "../../app/currency";
import { useToast } from "../../app/toast";
import form from "../../components/Forms.module.css";
import { Icon } from "../../components/Icon";
import { LoadError } from "../../components/LoadError";
import look from "../../components/Page.module.css";
import { groupAmount, tidyAmount } from "../../lib/amount";
import { formatMoney } from "../../lib/money";
import { sameAmount } from "../../lib/split";
import { type Direction, OpeningFields } from "./OpeningFields";
import styles from "./People.module.css";
import { type OpeningFormView, type OpeningUpdate, useAddOpening, useOpeningForm, useUpdateOpening } from "./queries";

function FormBody({
  view,
  contactId,
  transactionId,
}: {
  view: OpeningFormView;
  contactId: string;
  transactionId: string | undefined;
}) {
  const grouping = useGrouping();
  const places = usePlaces();
  const toast = useToast();
  const navigate = useNavigate();
  const add = useAddOpening(contactId);
  const update = useUpdateOpening(transactionId ?? "");
  const [direction, setDirection] = useState<Direction>(view.direction);
  const [amount, setAmount] = useState(view.amount ? groupAmount(view.amount, grouping) : "");
  const [since, setSince] = useState(view.date);
  const [note, setNote] = useState(view.description);
  const [problem, setProblem] = useState<string | null>(null);
  const back = `/people/${contactId}`;
  const name = view.person_name;
  const pending = add.isPending || update.isPending;

  const done = (said: string) => () => {
    toast(said);
    void navigate(back, { replace: true });
  };
  const failed = (e: unknown) => {
    setProblem(messageOf(e));
  };

  const submit = () => {
    setProblem(null);
    const typed = tidyAmount(amount, places).replace(/,/g, "");
    if (!typed) {
      setProblem("enter the amount!");
      return;
    }
    const description = note.trim() ? note.trim() : null;
    if (!view.editing) {
      add.mutate(
        { direction, amount: typed, date: since, description },
        { onSuccess: done("Opening balance added"), onError: failed },
      );
      return;
    }
    const changes: OpeningUpdate = {};
    if (direction !== view.direction) changes.direction = direction;
    if (!view.amount || !sameAmount(typed, view.amount)) changes.amount = typed;
    if (since !== view.date) changes.date = since;
    if (description !== (view.description || null)) changes.description = description;
    if (Object.keys(changes).length === 0) {
      void navigate(back);
      return;
    }
    update.mutate(changes, { onSuccess: done("Opening balance saved"), onError: failed });
  };

  return (
    <>
      <Link className={look.back} to={back}>
        <Icon name="back" />
        {name}
      </Link>
      <h1 className={form.title}>{view.editing ? "Edit opening balance" : "Opening balance"}</h1>
      {view.editing ? (
        view.paid && (
          <p className={styles.warn}>
            {formatMoney(view.paid, grouping)} of this has been paid back. The amount can&apos;t go below that, and who
            owes whom can&apos;t change.
          </p>
        )
      ) : (
        <p className={styles.lead}>
          What {name} already owed before you started with finode. It touches none of your accounts or budgets.
        </p>
      )}
      <form
        className={form.form}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <OpeningFields
          choices={view.paid ? null : [`${name} owes you`, `You owe ${name}`]}
          direction={direction}
          onDirection={setDirection}
          amount={amount}
          onAmount={setAmount}
          since={since}
          onSince={setSince}
        />
        <label>
          Note (optional)
          <input
            type="text"
            maxLength={200}
            value={note}
            onChange={(event) => {
              setNote(event.target.value);
            }}
          />
        </label>
        {problem && (
          <p className={form.error} role="alert">
            {problem}
          </p>
        )}
        <div>
          <button type="submit" className={form.primary} disabled={pending} aria-busy={pending}>
            {view.editing ? "Save changes" : "Add opening balance"}
          </button>
        </div>
      </form>
    </>
  );
}

export function OpeningForm() {
  const { contactId = "", transactionId } = useParams();
  const query = useOpeningForm(contactId, transactionId);
  if (query.isError) return <LoadError error={query.error} onRetry={() => void query.refetch()} />;
  if (!query.data) return <h1 className="sr-only">Opening balance</h1>;
  return (
    <FormBody key={transactionId ?? "new"} view={query.data} contactId={contactId} transactionId={transactionId} />
  );
}

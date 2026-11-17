// Adding or editing a person: the name and details; when adding, what they already owed (an opening
// balance), saved with them or not at all (services/people_view.add_person).
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { messageOf } from "../../api/messages";
import { usePlaces } from "../../app/currency";
import { useToday } from "../../app/session";
import { useToast } from "../../app/toast";
import form from "../../components/Forms.module.css";
import { Icon } from "../../components/Icon";
import { LoadError } from "../../components/LoadError";
import look from "../../components/Page.module.css";
import { tidyAmount } from "../../lib/amount";
import { type Direction, OpeningFields } from "./OpeningFields";
import styles from "./People.module.css";
import { useAddPerson, usePersonDetails, useUpdatePerson } from "./queries";

interface Details {
  name: string;
  phone?: string | null;
  email?: string | null;
  notes?: string | null;
}

const orNull = (text: string) => (text.trim() ? text.trim() : null);

function FormBody({ start, contactId }: { start: Details | null; contactId: string | undefined }) {
  const places = usePlaces();
  const today = useToday();
  const toast = useToast();
  const navigate = useNavigate();
  const add = useAddPerson();
  const update = useUpdatePerson(contactId ?? "");
  const editing = contactId !== undefined;
  const [name, setName] = useState(start?.name ?? "");
  const [phone, setPhone] = useState(start?.phone ?? "");
  const [email, setEmail] = useState(start?.email ?? "");
  const [notes, setNotes] = useState(start?.notes ?? "");
  const [owing, setOwing] = useState(false);
  const [direction, setDirection] = useState<Direction>("receivable");
  const [amount, setAmount] = useState("");
  const [since, setSince] = useState(today);
  const [problem, setProblem] = useState<string | null>(null);
  const back = editing ? `/people/${contactId}` : "/people";
  const pending = add.isPending || update.isPending;

  const submit = () => {
    setProblem(null);
    const details = { name: name.trim(), phone: orNull(phone), email: orNull(email), notes: orNull(notes) };
    const failed = (e: unknown) => {
      setProblem(messageOf(e));
    };
    if (editing) {
      update.mutate(details, {
        onSuccess: () => {
          toast("Person saved");
          void navigate(back, { replace: true });
        },
        onError: failed,
      });
      return;
    }
    const typed = tidyAmount(amount, places).replace(/,/g, "");
    add.mutate(
      typed ? { ...details, opening: { direction, amount: typed, date: since, description: null } } : details,
      {
        onSuccess: (made) => {
          toast("Person added");
          void navigate(`/people/${made.id}`, { replace: true });
        },
        onError: failed,
      },
    );
  };

  return (
    <>
      <Link className={look.back} to={back}>
        <Icon name="back" />
        {editing ? (start?.name ?? "") : "People"}
      </Link>
      <h1 className={form.title}>{editing ? "Edit person" : "Add person"}</h1>
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
            maxLength={30}
            required
            placeholder="e.g. Alice"
            autoFocus={!editing}
            value={name}
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
        </label>
        <label>
          Phone (optional)
          <input
            type="tel"
            maxLength={30}
            autoComplete="off"
            value={phone}
            onChange={(event) => {
              setPhone(event.target.value);
            }}
          />
        </label>
        <label>
          Email (optional)
          <input
            type="email"
            maxLength={254}
            autoComplete="off"
            value={email}
            onChange={(event) => {
              setEmail(event.target.value);
            }}
          />
        </label>
        <label>
          Note (optional)
          <input
            type="text"
            maxLength={500}
            value={notes}
            onChange={(event) => {
              setNotes(event.target.value);
            }}
          />
        </label>
        {!editing && (
          <>
            <button
              type="button"
              className={styles.extra}
              aria-expanded={owing}
              onClick={() => {
                setOwing((now) => !now);
              }}
            >
              <span>Already owes you, or is owed?</span>
              <Icon name="chevron-right" />
            </button>
            {owing && (
              <div className={styles.owing}>
                <OpeningFields
                  choices={["They owe you", "You owe them"]}
                  direction={direction}
                  onDirection={setDirection}
                  amount={amount}
                  onAmount={setAmount}
                  since={since}
                  onSince={setSince}
                />
                <p className={form.hint}>
                  Added to your opening balances. Your accounts and budgets don&apos;t change. It can be paid back with
                  Settle up.
                </p>
              </div>
            )}
          </>
        )}
        {problem && (
          <p className={form.error} role="alert">
            {problem}
          </p>
        )}
        <div>
          <button type="submit" className={form.primary} disabled={pending} aria-busy={pending}>
            {editing ? "Save changes" : "Add person"}
          </button>
        </div>
      </form>
    </>
  );
}

export function PersonForm() {
  const { contactId } = useParams();
  const query = usePersonDetails(contactId);
  if (contactId === undefined) return <FormBody start={null} contactId={undefined} />;
  if (query.isError) return <LoadError error={query.error} onRetry={() => void query.refetch()} />;
  if (!query.data) return <h1 className="sr-only">Edit person</h1>;
  return <FormBody key={contactId} start={query.data} contactId={contactId} />;
}

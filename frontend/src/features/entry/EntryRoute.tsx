// The Add and Edit addresses: /transactions/new (blank, or ?account=, ?category=, ?repeat=, ?related=, ?pay=&amount=,
// ?move=&with=) and /transactions/:id/edit, each with an optional ?back=. Loads where the form starts and opens it.
import { Navigate, useParams, useSearchParams } from "react-router";

import { LoadError } from "../../components/LoadError";
import { EntryScreen } from "./EntryScreen";
import styles from "./EntryScreen.module.css";
import { type FormQuery, useEntryForm } from "./queries";

const STARTS = ["account", "category", "repeat", "related", "pay", "amount", "move", "with"] as const;

export function EntryRoute() {
  const { transactionId } = useParams();
  const [params] = useSearchParams();
  const query: FormQuery = transactionId ? { transaction_id: transactionId } : {};
  if (!transactionId) {
    for (const key of STARTS) {
      const value = params.get(key);
      if (value) Object.assign(query, { [key]: value });
    }
  }
  const form = useEntryForm(query);
  const back = params.get("back");

  if (form.isError) return <LoadError error={form.error} onRetry={() => void form.refetch()} />;
  if (!form.data) return <h1 className="sr-only">{transactionId ? "Edit transaction" : "New transaction"}</h1>;
  if (form.data.person_page) return <Navigate to={`/people/${form.data.person_page}`} replace />;
  if (!form.data.simple) {
    return (
      <>
        <h1>Edit transaction</h1>
        <p className={styles.muted}>
          This entry has several lines or is shared with people: edit it on the web page for now.
        </p>
      </>
    );
  }
  return (
    <EntryScreen
      // A different entry (or a different way of starting one) is a fresh form.
      key={JSON.stringify(query)}
      form={form.data}
      {...(transactionId ? { transactionId } : {})}
      back={back}
    />
  );
}

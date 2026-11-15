// One entry done with a person in its sheet (partials/person_entry_sheet.html): what it was, its notes, Edit for an
// opening balance, and Reverse, which the server does the way the entry's kind is undone.
import { Link } from "react-router";

import { messageOf } from "../../api/messages";
import { useGrouping } from "../../app/currency";
import { useToday } from "../../app/session";
import { useToast } from "../../app/toast";
import { Icon } from "../../components/Icon";
import { Sheet } from "../../components/Sheet";
import { friendlyDate } from "../../lib/dates";
import { formatMoney } from "../../lib/money";
import styles from "./People.module.css";
import { usePersonEntry, useReverseEntry } from "./queries";

interface SheetProps {
  contactId: string;
  name: string;
  transactionId: string;
  /** The row's own title, for the sheet's name while its view loads. */
  title: string;
  onClose: () => void;
}

export function EntrySheet({ contactId, name, transactionId, title, onClose }: SheetProps) {
  const today = useToday();
  const grouping = useGrouping();
  const toast = useToast();
  const query = usePersonEntry(contactId, transactionId);
  const reverse = useReverseEntry(contactId);
  const sheet = query.data;
  return (
    <Sheet open onClose={onClose} title={sheet?.title ?? title} showTitle={false}>
      {query.isError && (
        <p className={styles.error} role="alert">
          {messageOf(query.error)}
        </p>
      )}
      {sheet && (
        <>
          <div className={styles.sheetHead}>
            <div>
              <h2>{sheet.title}</h2>
              <p>
                {friendlyDate(sheet.date, today)} · {name}
              </p>
            </div>
            <p className={styles.sheetAmount}>{formatMoney(sheet.amount, grouping)}</p>
          </div>
          {sheet.notes.map((note) => (
            <p key={note} className={styles.note}>
              {note}
            </p>
          ))}
          {reverse.isError && (
            <p className={styles.error} role="alert">
              {messageOf(reverse.error)}
            </p>
          )}
          {sheet.can_edit && (
            <div className={styles.actions}>
              <Link className={styles.secondary} to={`/people/${contactId}/opening/${transactionId}/edit`}>
                Edit
              </Link>
            </div>
          )}
          {sheet.can_reverse && (
            <>
              <p className={styles.hint}>
                Reversing removes it for good, as if it had never happened. It can&apos;t be reversed while something
                has been paid back against it.
              </p>
              <button
                type="button"
                className={styles.danger}
                disabled={reverse.isPending}
                onClick={() => {
                  if (!window.confirm("Reverse this? It is removed for good.")) return;
                  reverse.mutate(transactionId, {
                    onSuccess: () => {
                      toast("Reversed. It is as if it never happened.");
                      onClose();
                    },
                  });
                }}
              >
                <Icon name="trash" />
                Reverse
              </button>
            </>
          )}
        </>
      )}
    </Sheet>
  );
}

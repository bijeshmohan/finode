// One tag in its sheet (partials/tag_sheet.html): how often and when it was last used, its entries, and Rename, Merge
// into… (renaming onto another tag) and Delete. A change toasts, refreshes the views and closes the sheet; a refusal
// stays in it.
import { useId, useState } from "react";
import { Link } from "react-router";

import { messageOf } from "../../api/messages";
import { useToday } from "../../app/session";
import { useToast } from "../../app/toast";
import { Icon } from "../../components/Icon";
import { Sheet } from "../../components/Sheet";
import { friendlyDate } from "../../lib/dates";
import { type Tag, useDeleteTag, useRenameTag } from "./queries";
import styles from "./Tags.module.css";

const entries = (n: number) => `${String(n)} entr${n === 1 ? "y" : "ies"}`;

export function TagSheet({ tag, others, onClose }: { tag: Tag; others: string[]; onClose: () => void }) {
  const today = useToday();
  const toast = useToast();
  const rename = useRenameTag();
  const remove = useDeleteTag();
  const id = useId();
  const [showing, setShowing] = useState<"rename" | "merge" | null>(null);
  const [to, setTo] = useState(tag.tag);
  const [into, setInto] = useState(others[0] ?? "");
  const failed = rename.error ?? remove.error;
  const toggle = (which: "rename" | "merge") => {
    setShowing((now) => (now === which ? null : which));
  };
  const send = (name: string, done: string) => {
    remove.reset();
    rename.mutate(
      { name: tag.tag, to: name },
      {
        onSuccess: () => {
          toast(done);
          onClose();
        },
      },
    );
  };
  return (
    <Sheet open onClose={onClose} title={`#${tag.tag}`} showTitle={false}>
      <div className={styles.head}>
        <h2>#{tag.tag}</h2>
        <p>
          {entries(tag.uses)} · last used {friendlyDate(tag.last_used, today)}
        </p>
      </div>
      <Link
        className={styles.extra}
        to={`/transactions?month=${tag.last_used.slice(0, 7)}&tag=${encodeURIComponent(tag.tag)}`}
      >
        <span>View entries</span>
        <Icon name="chevron-right" />
      </Link>
      <button
        type="button"
        className={styles.extra}
        aria-expanded={showing === "rename"}
        onClick={() => {
          toggle("rename");
        }}
      >
        <span>Rename</span>
        <Icon name="chevron-right" />
      </button>
      {showing === "rename" && (
        <form
          className={styles.form}
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            send(to, "Tag renamed");
          }}
        >
          <input
            id={`${id}-to`}
            type="text"
            value={to}
            maxLength={30}
            autoComplete="off"
            autoCapitalize="none"
            aria-label="New name"
            onChange={(event) => {
              setTo(event.target.value);
            }}
          />
          <p className={styles.hint}>If the new name is another of your tags, the two become one.</p>
          <button type="submit" className={styles.secondary} disabled={rename.isPending}>
            Rename
          </button>
        </form>
      )}
      {others.length > 0 && (
        <>
          <button
            type="button"
            className={styles.extra}
            aria-expanded={showing === "merge"}
            onClick={() => {
              toggle("merge");
            }}
          >
            <span>Merge into…</span>
            <Icon name="chevron-right" />
          </button>
          {showing === "merge" && (
            <form
              className={styles.form}
              noValidate
              onSubmit={(event) => {
                event.preventDefault();
                send(into, "Tags merged");
              }}
            >
              <select
                aria-label="Merge into"
                value={into}
                onChange={(event) => {
                  setInto(event.target.value);
                }}
              >
                {others.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
              <button type="submit" className={styles.secondary} disabled={rename.isPending}>
                Merge
              </button>
            </form>
          )}
        </>
      )}
      {failed && (
        <p className={styles.error} role="alert">
          {messageOf(failed)}
        </p>
      )}
      <button
        type="button"
        className={styles.danger}
        disabled={remove.isPending}
        onClick={() => {
          const ask = `Delete the tag ${tag.tag}? It comes off ${entries(tag.uses)}; they are not deleted.`;
          if (!window.confirm(ask)) return;
          rename.reset();
          remove.mutate(tag.tag, {
            onSuccess: () => {
              toast("Tag deleted");
              onClose();
            },
          });
        }}
      >
        <Icon name="trash" />
        Delete tag
      </button>
    </Sheet>
  );
}

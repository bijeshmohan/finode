// The Tags page: every tag with how many entries carry it, most used first; a tag opens its sheet.
import { useState } from "react";
import { Link } from "react-router";

import { Icon } from "../../components/Icon";
import { LoadError } from "../../components/LoadError";
import look from "../../components/Page.module.css";
import { type Tag, useTags } from "./queries";
import { TagSheet } from "./TagSheet";
import styles from "./Tags.module.css";

export function TagsPage() {
  const query = useTags();
  const [open, setOpen] = useState<Tag | null>(null);
  const tags = query.data;
  if (query.isError) return <LoadError error={query.error} onRetry={() => void query.refetch()} />;
  return (
    <>
      <Link className={look.back} to="/settings">
        <Icon name="back" />
        Settings
      </Link>
      <div className={look.pageHead}>
        <h1>Tags</h1>
      </div>
      {tags &&
        (tags.length > 0 ? (
          <div className={styles.tile}>
            {tags.map((t) => (
              <button
                key={t.tag}
                type="button"
                className={styles.row}
                onClick={() => {
                  setOpen(t);
                }}
              >
                <span className={styles.name}>#{t.tag}</span>
                <span className={styles.count}>{t.uses}</span>
              </button>
            ))}
          </div>
        ) : (
          <div className={look.empty}>
            <p>No tags yet. Add one with the # button when you record or edit an entry.</p>
            <Link className={look.button} to="/transactions/new">
              Record a transaction
            </Link>
          </div>
        ))}
      {open && tags && (
        <TagSheet
          tag={open}
          others={tags.filter((t) => t.tag !== open.tag).map((t) => t.tag)}
          onClose={() => {
            setOpen(null);
          }}
        />
      )}
    </>
  );
}

// The note, with its # button, and the line of chosen tags under it (partials/tags_box.html). Tags are their own
// thing, not words in the note: a # typed in the note stays text. The sheet lists the tags in use, searches them, and
// offers to create a new one; an entry can have at most 10.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { data } from "../../api/client";
import { useApi } from "../../api/context";
import { Sheet } from "../../components/Sheet";
import styles from "./EntryScreen.module.css";

/** As the server keeps it (app/tags.py): "Goa trip" is the tag goa-trip. The server checks every tag again. */
const NAME = /^[a-z0-9](?:[a-z0-9_-]{0,28}[a-z0-9])?$/;
export const MAX_TAGS = 10;

export function cleanTag(text: string): string {
  return text.trim().replace(/^#+/, "").trim().toLowerCase().replace(/\s+/g, "-");
}

interface NoteProps {
  note: string;
  onNote: (note: string) => void;
  tags: string[];
  onTags: (tags: string[]) => void;
}

export function NoteAndTags({ note, onNote, tags, onTags }: NoteProps) {
  const [open, setOpen] = useState(false);
  return (
    <div className={styles.tagsBox}>
      <div className={styles.noteField}>
        <input
          type="text"
          maxLength={200}
          placeholder="Note (optional)"
          aria-label="Note"
          value={note}
          onChange={(event) => {
            onNote(event.target.value);
          }}
        />
        <button
          type="button"
          className={styles.hash}
          aria-label="Tags"
          title="Tags"
          onClick={() => {
            setOpen(true);
          }}
        >
          #
        </button>
      </div>
      {tags.length > 0 && (
        <button
          type="button"
          className={styles.tagsLine}
          aria-label="Change the tags"
          onClick={() => {
            setOpen(true);
          }}
        >
          {tags.map((tag) => (
            <span key={tag}>#{tag}</span>
          ))}
        </button>
      )}
      {open && (
        <TagsSheet
          chosen={tags}
          onChange={onTags}
          onClose={() => {
            setOpen(false);
          }}
        />
      )}
    </div>
  );
}

function TagsSheet({
  chosen,
  onChange,
  onClose,
}: {
  chosen: string[];
  onChange: (tags: string[]) => void;
  onClose: () => void;
}) {
  const api = useApi();
  const [search, setSearch] = useState("");
  const inUse = useQuery({ queryKey: ["tags"], queryFn: () => data(api.GET("/api/tags/")) });
  const wanted = cleanTag(search);
  const names = [...new Set([...chosen, ...(inUse.data ?? []).map((t) => t.tag)])];
  const shown = wanted ? names.filter((n) => n.includes(wanted)) : names;
  const full = chosen.length >= MAX_TAGS;
  const toggle = (name: string) => {
    if (chosen.includes(name)) onChange(chosen.filter((n) => n !== name));
    else if (!full) onChange([...chosen, name]);
  };
  const creatable = wanted !== "" && NAME.test(wanted) && !names.includes(wanted);

  return (
    <Sheet open onClose={onClose} title="Tags">
      <input
        type="search"
        className={styles.search}
        placeholder="Search or create a #tag"
        aria-label="Search or create a tag"
        autoComplete="off"
        autoCapitalize="none"
        value={search}
        onChange={(event) => {
          setSearch(event.target.value);
        }}
      />
      <ul className={styles.options}>
        {creatable && (
          <li>
            <button
              type="button"
              disabled={full}
              onClick={() => {
                toggle(wanted);
                setSearch("");
              }}
            >
              ＋ Create “#{wanted}”
            </button>
          </li>
        )}
        {shown.map((name) => (
          <li key={name}>
            <button
              type="button"
              aria-pressed={chosen.includes(name)}
              disabled={full && !chosen.includes(name)}
              onClick={() => {
                toggle(name);
              }}
            >
              <span>#{name}</span>
              <span className={styles.tick} aria-hidden="true">
                {chosen.includes(name) ? "✓" : ""}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {full && <p className={styles.muted}>An entry can have at most 10 tags.</p>}
      <div className={styles.actions}>
        <button type="button" className={styles.primary} onClick={onClose}>
          Done
        </button>
      </div>
    </Sheet>
  );
}

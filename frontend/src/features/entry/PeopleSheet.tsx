// The sheet that adds people to a Split (people_sheet.html): tick the ones who are in it; a search narrows the list.
import { useState } from "react";

import { Sheet } from "../../components/Sheet";
import pickerStyles from "./Picker.module.css";
import styles from "./ShareEditor.module.css";
import type { EntryFormView } from "./queries";

interface PeopleSheetProps {
  people: EntryFormView["people"];
  chosen: string[];
  onToggle: (id: string) => void;
  onClose: () => void;
}

export function PeopleSheet({ people, chosen, onToggle, onClose }: PeopleSheetProps) {
  const [search, setSearch] = useState("");
  const wanted = search.trim().toLowerCase();
  const count = chosen.length;
  return (
    <Sheet open onClose={onClose} title="Split with">
      <input
        type="search"
        className={pickerStyles.search}
        placeholder="Search people"
        aria-label="Search people"
        autoComplete="off"
        value={search}
        onChange={(event) => {
          setSearch(event.target.value);
        }}
      />
      <div className={pickerStyles.list}>
        {people
          .filter((p) => p.name.toLowerCase().includes(wanted))
          .map((p) => (
            <button
              key={p.id}
              type="button"
              className={pickerStyles.option}
              aria-pressed={chosen.includes(p.id)}
              onClick={() => {
                onToggle(p.id);
              }}
            >
              <span>{p.name}</span>
            </button>
          ))}
      </div>
      <button type="button" className={styles.done} onClick={onClose}>
        {count ? `Done · ${String(count)} ${count === 1 ? "person" : "people"}` : "Done"}
      </button>
    </Sheet>
  );
}

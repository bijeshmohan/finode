// A category's icon field: the chosen icon and its name (or "Choose an icon"), opening a sheet with the set in its
// groups. Choosing closes the sheet. The set is category-icons.json; the server checks the name again.
import { useId, useState } from "react";

import { CategoryIcon, categoryIconGroups, iconLabel } from "./CategoryIcon";
import styles from "./IconPicker.module.css";
import { Sheet } from "./Sheet";

export function IconPicker({ value, onChange }: { value: string | null; onChange: (name: string) => void }) {
  const [open, setOpen] = useState(false);
  const labelId = useId();
  return (
    <div className={styles.field}>
      <span id={labelId} className={styles.fieldLabel}>
        Icon
      </span>
      <button
        type="button"
        className={styles.pick}
        aria-haspopup="dialog"
        aria-describedby={labelId}
        onClick={() => {
          setOpen(true);
        }}
      >
        {value ? (
          <>
            <span className={styles.chosen}>
              <CategoryIcon name={value} />
            </span>
            <span className={styles.name}>{iconLabel(value)}</span>
            <span className={styles.change}>Change</span>
          </>
        ) : (
          <span className={styles.empty}>Choose an icon</span>
        )}
      </button>
      <Sheet
        open={open}
        title="Icon"
        onClose={() => {
          setOpen(false);
        }}
      >
        {categoryIconGroups.map((group) => (
          <section key={group.name} className={styles.group}>
            <h3 className={styles.groupTitle}>{group.name}</h3>
            <div className={styles.grid}>
              {group.icons.map((name) => (
                <button
                  key={name}
                  type="button"
                  className={styles.cell}
                  aria-label={iconLabel(name)}
                  aria-pressed={name === value}
                  title={iconLabel(name)}
                  onClick={() => {
                    onChange(name);
                    setOpen(false);
                  }}
                >
                  <CategoryIcon name={name} />
                </button>
              ))}
            </div>
          </section>
        ))}
      </Sheet>
    </div>
  );
}

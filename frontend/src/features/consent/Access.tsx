// What each access level lets an assistant do, in plain words (partials/access.html): the consent screen's cards.
import styles from "./Access.module.css";

export type AccessLevel = "read" | "write" | "manage";

const LEVELS: Record<AccessLevel, { title: string; example: string; yes: string[]; no: string; hint: string }> = {
  read: {
    title: "Read only",
    example: "Ask: “What did I spend on food in September?”",
    yes: ["See accounts, balances and transactions", "Reports"],
    no: "Cannot change anything",
    hint: "The safe choice. You can allow changes later.",
  },
  write: {
    title: "Read & write",
    example: "Say: “I paid 450 for lunch from HDFC.”",
    yes: ["Everything in read only", "Record, edit and delete transactions", "Add accounts"],
    no: "Cannot rename, merge or delete accounts",
    hint: "Everything it records is marked with its name, so you can review it.",
  },
  manage: {
    title: "Read, write & manage accounts",
    example: "Say: “Rename Banks to Bank Accounts and merge the two Swiggy categories.”",
    yes: ["Everything in read & write", "Rename, move, close and reopen accounts, and merge two into one"],
    no: "Never deletes accounts",
    hint: "Changes how your whole history is organised, so allow it only for assistants you trust. Every change is recorded with its name.",
  },
};

export function Access({ level }: { level: AccessLevel }) {
  const l = LEVELS[level];
  return (
    <span className={styles.level}>
      <strong>{l.title}</strong>
      <span className={styles.example}>{l.example}</span>
      <ul className={styles.list}>
        {l.yes.map((y) => (
          <li key={y} className={styles.yes}>
            {y}
          </li>
        ))}
        <li className={styles.no}>{l.no}</li>
      </ul>
      <span className={styles.hint}>{l.hint}</span>
    </span>
  );
}

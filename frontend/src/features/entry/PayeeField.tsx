// The payee, with the chips of people you pay (partials/txn_payee.html): names only, while you type; a chip fills the
// payee and moves on to the amount, never an account. After an "@", your people: choosing one names them on an expense
// or an income (a gift, nothing owed), shown in a chip with ✕ to take them off.
import { useQuery } from "@tanstack/react-query";

import { data } from "../../api/client";
import { useApi } from "../../api/context";
import styles from "./EntryScreen.module.css";

interface PayeeProps {
  value: string;
  onChange: (value: string) => void;
  person: { id: string; name: string } | null;
  onPerson: (person: { id: string; name: string } | null) => void;
  /** An edit offers people only: the payee it has is not second-guessed. */
  editing: boolean;
  /** People can be named on an expense or an income only. */
  canName: boolean;
}

export function PayeeField({ value, onChange, person, onPerson, editing, canName }: PayeeProps) {
  const api = useApi();
  const typed = value.trim();
  const suggestions = useQuery({
    queryKey: ["payee-suggestions", typed, editing],
    queryFn: () =>
      data(
        api.GET("/api/transactions/payee-suggestions", {
          params: { query: { payee: typed, ...(editing ? { only: "people" } : {}) } },
        }),
      ),
    enabled: typed !== "" && !person,
    staleTime: 30_000,
  });
  const names = suggestions.data?.names ?? [];
  const people = canName ? (suggestions.data?.people ?? []) : [];

  return (
    <div className={styles.payee}>
      <label className={styles.payeeLabel}>
        <span className="sr-only">Payee</span>
        <input
          id="payee"
          type="text"
          maxLength={40}
          placeholder="Payee or Merchant?"
          autoComplete="off"
          autoCapitalize="words"
          value={value}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
      </label>
      {person && (
        <div className={styles.chipNote}>
          <span>
            <small>
              Saved in <b>{person.name}</b>&apos;s activity. Nothing is owed.
            </small>
          </span>
          <button
            type="button"
            className={styles.linkButton}
            aria-label="Take the person off"
            onClick={() => {
              onPerson(null);
            }}
          >
            ✕
          </button>
        </div>
      )}
      {(names.length > 0 || people.length > 0) && (
        <div className={styles.chips} role="group" aria-label="People you pay">
          {names.map((name) => (
            <button
              key={name}
              type="button"
              className={styles.chip}
              onClick={() => {
                onChange(name);
                document.getElementById("total")?.focus();
              }}
            >
              {name}
            </button>
          ))}
          {people.map((p) => (
            <button
              key={p.id}
              type="button"
              className={`${styles.chip} ${styles.personChip}`}
              onClick={() => {
                onChange(p.name);
                onPerson({ id: p.id, name: p.name });
              }}
            >
              {p.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

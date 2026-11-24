// A new account or category made from the Add screen's picker: an account is one of the four types (those of the side
// the picker was opened for come first), a category goes under a group or none. The server checks the name; once made,
// it is chosen on the row the picker was opened from.
import { useState } from "react";

import { messageOf } from "../../api/messages";
import { usePlaces } from "../../app/currency";
import { Chips } from "../../components/Chips";
import { Icon } from "../../components/Icon";
import { IconPicker } from "../../components/IconPicker";
import { Sheet } from "../../components/Sheet";
import { tidyAmount } from "../../lib/amount";
import styles from "./QuickAdd.module.css";
import { type AccountTypeOption, useAddAccount, useAddCategory } from "./queries";

export type QuickKind = { what: "account"; root: string } | { what: "category"; kind: "spending" | "earning" };

interface QuickAddProps {
  making: QuickKind;
  accountTypes: AccountTypeOption[];
  onMade: (id: string) => void;
  onClose: () => void;
}

export function QuickAdd({ making, accountTypes, onMade, onClose }: QuickAddProps) {
  const places = usePlaces();
  const addAccount = useAddAccount();
  const addCategory = useAddCategory();
  const account = making.what === "account";
  const title = account ? "New account" : "New category";
  const [name, setName] = useState("");
  // All four types, starting on the one the side was opened for (its first heading: "Bank Account" for Paid from).
  const offered = accountTypes;
  const [type, setType] = useState<AccountTypeOption["key"] | "">(
    account ? (offered.find((t) => t.name === making.root)?.key ?? offered[0]?.key ?? "") : "",
  );
  const [balance, setBalance] = useState("");
  const [icon, setIcon] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const pending = addAccount.isPending || addCategory.isPending;
  const error = addAccount.error ?? addCategory.error;
  const made = (created: { id: string }) => {
    onMade(created.id);
    onClose();
  };

  const submit = () => {
    if (making.what === "account") {
      if (!type) return;
      const opening = balance.trim() ? tidyAmount(balance, places).replace(/,/g, "") : "0";
      addAccount.mutate({ name: name.trim(), type, balance: opening, bill_rounding: "none" }, { onSuccess: made });
    } else {
      if (!icon) {
        setProblem("Choose an icon");
        return;
      }
      setProblem(null);
      addCategory.mutate({ name: name.trim(), kind: making.kind, icon }, { onSuccess: made });
    }
  };

  return (
    <Sheet open onClose={onClose} title={title} showTitle={false}>
      <div className={styles.head}>
        <h2>{title}</h2>
        <button type="button" className={styles.close} aria-label="Close" onClick={onClose}>
          <Icon name="close" />
        </button>
      </div>
      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <label>
          Name
          <input
            type="text"
            maxLength={40}
            required
            // eslint-disable-next-line jsx-a11y-x/no-autofocus -- the sheet is opened to type this name
            autoFocus
            autoComplete="off"
            placeholder={!account && making.kind === "earning" ? "e.g. Freelance" : "e.g. Pharmacy"}
            value={name}
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
        </label>
        {account && (
          <div className={styles.field}>
            <span>Kind</span>
            <Chips
              label="Kind of account"
              options={offered.map((t) => ({ value: t.key, label: t.name, icon: t.icon }))}
              value={type}
              onChange={setType}
            />
          </div>
        )}
        {account && (
          <label>
            Current balance
            <input
              type="text"
              inputMode="decimal"
              placeholder="0.00"
              autoComplete="off"
              value={balance}
              onChange={(event) => {
                setBalance(event.target.value);
              }}
            />
            <span className={styles.hint}>Optional. Recorded as an opening balance dated today.</span>
          </label>
        )}
        {!account && (
          <IconPicker
            value={icon}
            onChange={(chosen) => {
              setIcon(chosen);
              setProblem(null);
            }}
          />
        )}
        {(problem ?? error) && (
          <p className={styles.error} role="alert">
            {problem ?? messageOf(error)}
          </p>
        )}
        <div className={styles.actions}>
          <button type="submit" className={styles.primary} disabled={pending} aria-busy={pending}>
            {account ? "Add account" : "Add category"}
          </button>
          <button type="button" className={styles.secondary} onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Sheet>
  );
}

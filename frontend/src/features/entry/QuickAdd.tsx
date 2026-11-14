// A new account or category made from the Add screen's picker (quick_account.html, quick_category.html): the server
// checks the name and where it goes; once made, it is chosen on the row the picker was opened from.
import { useState } from "react";

import { messageOf } from "../../api/messages";
import { usePlaces } from "../../app/currency";
import { Icon } from "../../components/Icon";
import { Sheet } from "../../components/Sheet";
import { tidyAmount } from "../../lib/amount";
import styles from "./QuickAdd.module.css";
import { type CategoryParent, type ParentOption, useAddAccount, useAddCategory } from "./queries";

export type QuickKind = { what: "account"; root: string } | { what: "category"; kind: "spending" | "earning" };

interface QuickAddProps {
  making: QuickKind;
  accountParents: ParentOption[];
  categoryParents: CategoryParent[];
  onMade: (id: string) => void;
  onClose: () => void;
}

export function QuickAdd({ making, accountParents, categoryParents, onMade, onClose }: QuickAddProps) {
  const places = usePlaces();
  const addAccount = useAddAccount();
  const addCategory = useAddCategory();
  const account = making.what === "account";
  const title = account ? "New account" : "New category";
  const [name, setName] = useState("");
  const [parent, setParent] = useState<string>(
    account ? (accountParents.find((p) => p.depth === 0 && p.root === making.root)?.id ?? "") : "",
  );
  const [balance, setBalance] = useState("");
  const chosen = accountParents.find((p) => p.id === parent);
  const pending = addAccount.isPending || addCategory.isPending;
  const error = addAccount.error ?? addCategory.error;
  const made = (created: { id: string }) => {
    onMade(created.id);
    onClose();
  };

  const submit = () => {
    if (making.what === "account") {
      const opening = chosen?.opening_balance && balance.trim() ? tidyAmount(balance, places).replace(/,/g, "") : "0";
      addAccount.mutate(
        { name: name.trim(), parent_id: parent || null, balance: opening, bill_rounding: "none" },
        { onSuccess: made },
      );
    } else {
      addCategory.mutate({ name: name.trim(), kind: making.kind, parent_id: parent || null }, { onSuccess: made });
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
        {account ? (
          <label>
            Belongs under
            <select
              required
              value={parent}
              onChange={(event) => {
                setParent(event.target.value);
              }}
            >
              {parent === "" && <option value="">Choose…</option>}
              {accountParents.map((p) => (
                <option key={p.id} value={p.id}>
                  {"   ".repeat(p.depth)}
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <label>
            Under
            <select
              value={parent}
              onChange={(event) => {
                setParent(event.target.value);
              }}
            >
              <option value="">None (top level)</option>
              {categoryParents
                .filter((c) => c.kind === making.kind)
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
            </select>
          </label>
        )}
        {account && chosen?.opening_balance && (
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
        {error && (
          <p className={styles.error} role="alert">
            {messageOf(error)}
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

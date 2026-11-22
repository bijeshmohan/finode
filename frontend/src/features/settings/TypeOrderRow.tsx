// The order of the four account types: the Accounts page's rows, the pickers' headings and the assistants' list follow
// it. Each move saves at once; a refusal shows the server's words and the order stays as it was.
import { messageOf } from "../../api/messages";
import { useProfile } from "../../app/currency";
import { Icon } from "../../components/Icon";
import { useUpdateProfile } from "./queries";
import { SettingRow } from "./SettingRow";
import styles from "./Settings.module.css";

type TypeKey = "assets.bank" | "assets.cash" | "liabilities.cards" | "assets.wallet";

const NAMES: Record<TypeKey, string> = {
  "assets.bank": "Bank Account",
  "assets.cash": "Cash",
  "liabilities.cards": "Credit Card",
  "assets.wallet": "Prepaid Wallet",
};

/** The order with the type at `index` moved one place up (`step` -1) or down (`step` 1). */
function moved(order: TypeKey[], index: number, step: -1 | 1): TypeKey[] {
  const next = [...order];
  const other = index + step;
  const here = next[index];
  const there = next[other];
  if (here === undefined || there === undefined) return order;
  next[index] = there;
  next[other] = here;
  return next;
}

export function TypeOrderRow() {
  const profile = useProfile();
  const update = useUpdateProfile();
  const order = profile.data?.account_type_order ?? [];
  const move = (index: number, step: -1 | 1) => {
    update.mutate({ account_type_order: moved(order, index, step) });
  };
  return (
    <SettingRow id="account-types" title="Order of account types" value={order.map((k) => NAMES[k]).join(", ")}>
      <p className={styles.muted}>Accounts, the pickers and your assistants list the types in this order.</p>
      <ol className={styles.order} aria-label="Order of account types">
        {order.map((key, index) => (
          <li key={key}>
            <span>{NAMES[key]}</span>
            <span className={styles.orderButtons}>
              {index > 0 && (
                <button
                  type="button"
                  className={`${styles.small} ${styles.up}`}
                  aria-label={`Move ${NAMES[key]} up`}
                  disabled={update.isPending}
                  onClick={() => {
                    move(index, -1);
                  }}
                >
                  <Icon name="caret" />
                </button>
              )}
              {index < order.length - 1 && (
                <button
                  type="button"
                  className={styles.small}
                  aria-label={`Move ${NAMES[key]} down`}
                  disabled={update.isPending}
                  onClick={() => {
                    move(index, 1);
                  }}
                >
                  <Icon name="caret" />
                </button>
              )}
            </span>
          </li>
        ))}
      </ol>
      {update.isError && (
        <p className={styles.error} role="alert">
          {messageOf(update.error)}
        </p>
      )}
    </SettingRow>
  );
}

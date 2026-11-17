// A large amount with its currency: the rupee sign in front for INR, set apart (smaller,
// lighter, raised; a negative has its minus after the sign: ₹−5.00), the code after it, small, for anything else.
import { useCurrency, useGrouping } from "../app/currency";
import { formatMoney } from "../lib/money";
import styles from "./Figure.module.css";

export function Figure({ value }: { value: string }) {
  const code = useCurrency();
  const text = formatMoney(value, useGrouping());
  if (code === "INR")
    return (
      <>
        <span className={styles.cur}>₹</span>
        {text}
      </>
    );
  return (
    <>
      {text}
      {code && <small> {code}</small>}
    </>
  );
}

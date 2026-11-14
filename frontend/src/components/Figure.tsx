// A large amount with its currency (partials/money.html `figure`): the rupee sign in front for INR (a negative has its
// minus after the sign: ₹−5.00), the code after it, small, for anything else.
import { useCurrency, useGrouping } from "../app/currency";
import { formatMoney } from "../lib/money";

export function Figure({ value }: { value: string }) {
  const code = useCurrency();
  const text = formatMoney(value, useGrouping());
  if (code === "INR") return <>₹{text}</>;
  return (
    <>
      {text}
      {code && <small> {code}</small>}
    </>
  );
}

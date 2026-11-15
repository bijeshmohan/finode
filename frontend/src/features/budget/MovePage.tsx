// Moving money between categories (budget_move.html): from one category's available money to another; Ready to assign
// stays the same. The pickers say what each category has left.
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { messageOf } from "../../api/messages";
import { useGrouping, usePlaces } from "../../app/currency";
import { useToast } from "../../app/toast";
import { AmountField } from "../../components/AmountField";
import { Icon } from "../../components/Icon";
import { LoadError } from "../../components/LoadError";
import look from "../../components/Page.module.css";
import { tidyAmount } from "../../lib/amount";
import { monthName } from "../../lib/dates";
import form from "../../components/Forms.module.css";
import { Picker } from "../../components/lines/Picker";
import { type BudgetMoveView, useBudgetMove, useMoveMoney } from "./queries";

function Body({ view }: { view: BudgetMoveView }) {
  const grouping = useGrouping();
  const places = usePlaces();
  const toast = useToast();
  const navigate = useNavigate();
  const move = useMoveMoney();
  const [amount, setAmount] = useState("");
  const [from, setFrom] = useState<string | null>(view.source ?? null);
  const [to, setTo] = useState<string | null>(null);
  const [picking, setPicking] = useState<"From" | "To" | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const groups = [
    {
      title: "Categories",
      options: view.lines.map((l) => ({ id: l.category_id, label: l.path, budget: false, balance: l.available })),
    },
  ];
  const nameOf = (id: string | null) => view.lines.find((l) => l.category_id === id)?.path ?? "Choose…";
  const field = (label: "From" | "To", value: string | null) => (
    <div className={form.field}>
      <span aria-hidden="true">{label}</span>
      <button
        type="button"
        className={form.pick}
        aria-haspopup="dialog"
        aria-label={`${label}: ${nameOf(value)}`}
        onClick={() => {
          setPicking(label);
        }}
      >
        <span>{nameOf(value)}</span>
      </button>
    </div>
  );

  return (
    <>
      <Link className={look.back} to={`/budget?month=${view.month}`}>
        <Icon name="back" />
        Budgets
      </Link>
      <h1 className={form.title}>Move money</h1>
      <p className={look.muted}>
        {monthName(view.month)} {view.month.slice(0, 4)} · from one category&apos;s available money to another. Ready to
        assign stays the same.
      </p>
      <form
        className={form.form}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          setProblem(null);
          if (!from || !to) {
            setProblem("Choose the category to move from and the one to move to.");
            return;
          }
          move.mutate(
            {
              month: view.month,
              from_category: from,
              to_category: to,
              amount: tidyAmount(amount, places).replace(/,/g, "") || "0",
            },
            {
              onSuccess: () => {
                toast("Money moved");
                void navigate(`/budget?month=${view.month}`);
              },
              onError: (e) => {
                setProblem(messageOf(e));
              },
            },
          );
        }}
      >
        <AmountField
          id="move-amount"
          label="Amount"
          value={amount}
          onChange={setAmount}
          places={places}
          grouping={grouping}
          // eslint-disable-next-line jsx-a11y-x/no-autofocus -- the page is opened to type the amount, as on the web page
          autoFocus
        />
        {field("From", from)}
        {field("To", to)}
        {problem && (
          <p className={form.error} role="alert">
            {problem}
          </p>
        )}
        <div>
          <button type="submit" className={form.primary} disabled={move.isPending} aria-busy={move.isPending}>
            Move money
          </button>
        </div>
      </form>
      {picking && (
        <Picker
          open
          title={picking}
          groups={groups}
          value={picking === "From" ? from : to}
          suffix="left"
          onChange={(id) => {
            if (picking === "From") setFrom(id);
            else setTo(id);
          }}
          onClose={() => {
            setPicking(null);
          }}
        />
      )}
    </>
  );
}

/** /budget/move (?month=, ?source=). */
export function MovePage() {
  const [params] = useSearchParams();
  const query = useBudgetMove(params.get("month"), params.get("source"));
  if (query.isError) return <LoadError error={query.error} onRetry={() => void query.refetch()} />;
  if (!query.data) return <h1 className="sr-only">Move money</h1>;
  return <Body view={query.data} />;
}

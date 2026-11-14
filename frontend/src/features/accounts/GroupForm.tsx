// A new group (group_form.html): a shelf on the Accounts page for accounts, holding money the person owns or owes, and
// what the accounts made in it start as. Nothing is chosen for the person.
import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { messageOf } from "../../api/messages";
import { useToast } from "../../app/toast";
import { Icon } from "../../components/Icon";
import styles from "./Accounts.module.css";
import form from "./Forms.module.css";
import { useAddGroup } from "./queries";

const HOLDS = [
  ["own", "Money I own", "Assets"],
  ["owe", "Money I owe", "Liabilities"],
] as const;

export function GroupForm() {
  const toast = useToast();
  const navigate = useNavigate();
  const add = useAddGroup();
  const [name, setName] = useState("");
  const [holds, setHolds] = useState<"Assets" | "Liabilities" | null>(null);
  const [inBudget, setInBudget] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const submit = () => {
    setProblem(null);
    if (holds === null) {
      setProblem("choose whether it holds money you own or money you owe!");
      return;
    }
    add.mutate(
      { name: name.trim(), root: holds, new_accounts_in_budget: inBudget },
      {
        onSuccess: () => {
          toast("Group added");
          void navigate("/accounts", { replace: true });
        },
        onError: (e) => {
          setProblem(messageOf(e));
        },
      },
    );
  };

  return (
    <>
      <Link className={styles.back} to="/accounts">
        <Icon name="back" />
        Accounts
      </Link>
      <h1 className={form.title}>New group</h1>
      <form
        className={form.form}
        noValidate
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
            placeholder="e.g. Family"
            // eslint-disable-next-line jsx-a11y-x/no-autofocus -- the form starts with the name, as the web form does
            autoFocus
            value={name}
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
        </label>
        <div className={form.field}>
          <span>What it holds</span>
          <div className={form.seg} role="radiogroup" aria-label="What the group holds">
            {HOLDS.map(([key, label, root]) => (
              <label key={key}>
                <input
                  type="radio"
                  name="holds"
                  checked={holds === root}
                  onChange={() => {
                    setHolds(root);
                  }}
                />
                <span>{label}</span>
              </label>
            ))}
          </div>
        </div>
        <label className={form.check}>
          <span>
            Part of the budget{" "}
            <span className={form.hint}>
              Accounts you add here start with this choice. You can change it for any account
            </span>
          </span>
          <input
            type="checkbox"
            checked={inBudget}
            onChange={(event) => {
              setInBudget(event.target.checked);
            }}
          />
        </label>
        {problem && (
          <p className={form.error} role="alert">
            {problem}
          </p>
        )}
        <div>
          <button type="submit" className={form.primary} disabled={add.isPending} aria-busy={add.isPending}>
            Create group
          </button>
        </div>
      </form>
    </>
  );
}

// A new person's first steps (partials/get_started.html): a step still to do is a link (the next one is filled in), a
// finished one is ticked.
import { Link } from "react-router";

import { Icon } from "../../components/Icon";
import styles from "./Home.module.css";
import type { HomeView } from "./queries";

/** Where each step leads in the app. */
const STEP_ADDRESS: Record<NonNullable<HomeView["steps"]>[number]["key"], string> = {
  account: "/accounts/new",
  spend: "/transactions/new",
  budget: "/budget",
};

export function GetStarted({ steps }: { steps: NonNullable<HomeView["steps"]> }) {
  const next = steps.find((s) => !s.done);
  return (
    <ol className={styles.steps}>
      {steps.map((step, i) =>
        step.done ? (
          <li key={step.key} className={styles.done}>
            <span className={styles.stepMark} aria-hidden="true">
              ✓
            </span>
            <span className={styles.stepText}>{step.title}</span>
          </li>
        ) : (
          <li key={step.key}>
            <Link className={styles.stepLink} to={STEP_ADDRESS[step.key]}>
              <span className={`${styles.stepMark} ${step === next ? styles.now : ""}`.trim()} aria-hidden="true">
                {i + 1}
              </span>
              <span className={styles.stepText}>
                {step.title}
                {step.hint && <small className={styles.stepHint}>{step.hint}</small>}
              </span>
              <Icon name="chevron-right" />
            </Link>
          </li>
        ),
      )}
    </ol>
  );
}

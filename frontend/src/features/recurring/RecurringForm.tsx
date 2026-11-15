// The recurring form (recurring_form.html): the Add screen's rows (no posting day of their own, no people), the payee,
// how often it repeats, when it starts and ends, the note and tags; for a rule being edited where it stands, and
// Pause, Skip, Resume and Delete. The server turns the rows into a plain rule or a split (services/recurring_form.py).
import { useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router";

import { messageOf } from "../../api/messages";
import { useSubmitOnce } from "../../api/useSubmitOnce";
import { useGrouping, usePlaces } from "../../app/currency";
import { useToday } from "../../app/session";
import { useToast } from "../../app/toast";
import { Icon } from "../../components/Icon";
import { DateChip } from "../../components/lines/DateChip";
import form from "../../components/lines/Form.module.css";
import { Lines, linesBody, type LinesState, useLines } from "../../components/lines/Lines";
import { NoteAndTags } from "../../components/lines/NoteAndTags";
import { PayeeField } from "../../components/lines/PayeeField";
import { startRows } from "../../components/lines/rows";
import { LoadError } from "../../components/LoadError";
import { groupAmount } from "../../lib/amount";
import { friendlyDate } from "../../lib/dates";
import {
  type RecurringFormView,
  type RuleAction,
  type RuleBody,
  useRecurringForm,
  useRuleAction,
  useSaveRule,
} from "./queries";
import styles from "./Recurring.module.css";

const SAID: Record<RuleAction | "saved", string> = {
  saved: "Recurring transaction saved. Anything already due has been recorded.",
  pause: "Paused. Nothing will be recorded until you resume it.",
  skip: "Skipped. Nothing was recorded for that one; the next one is on its way as usual.",
  resume: "Resumed. Occurrences missed while it was paused are skipped.",
  delete: "Recurring transaction deleted. What it recorded is kept.",
};

const SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "01 Dec 2026", as the web page's confirmation writes a day (strftime %d %b %Y). */
function fullDay(iso: string): string {
  const [year = "", month = "1", day = ""] = iso.split("-");
  return `${day} ${SHORT[Number(month) - 1] ?? ""} ${year}`;
}

type Frequency = RuleBody["frequency"];
const FREQUENCIES: readonly string[] = ["daily", "weekly", "monthly", "yearly"] satisfies Frequency[];
const isFrequency = (value: string): value is Frequency => FREQUENCIES.includes(value);

interface RuleState extends LinesState {
  payee: string;
  comment: string;
  tags: string[];
  frequency: Frequency;
  every: string;
  end: string | null;
}

function startState(view: RecurringFormView, grouping: Parameters<typeof groupAmount>[1]): RuleState {
  return {
    kind: view.kind,
    total: view.total ? groupAmount(view.total, grouping) : "",
    date: view.start_date,
    credit: startRows(view.from_rows, grouping),
    debit: startRows(view.to_rows, grouping),
    payee: view.payee,
    comment: view.comment,
    tags: view.tags,
    frequency: isFrequency(view.frequency) ? view.frequency : "monthly",
    every: String(view.every),
    end: view.end_date,
  };
}

/** Where a rule being edited stands: "Every month · next on Tue, 1 Dec · last recorded Sun, 1 Nov". */
function origin(view: RecurringFormView, today: string): string {
  const parts = [view.schedule ?? ""];
  if (view.active && view.next_date) parts.push(`next on ${friendlyDate(view.next_date, today)}`);
  else parts.push(view.status === "ended" ? "ended" : "paused");
  if (view.last_date) parts.push(`last recorded ${friendlyDate(view.last_date, today)}`);
  if (view.skipped_date && (!view.last_date || view.skipped_date > view.last_date)) {
    parts.push(`skipped ${friendlyDate(view.skipped_date, today)}`);
  }
  return parts.join(" · ");
}

function Standing({ view, recurringId }: { view: RecurringFormView; recurringId: string }) {
  const today = useToday();
  const toast = useToast();
  const navigate = useNavigate();
  const act = useRuleAction(recurringId);
  const run = (action: RuleAction) => {
    act.mutate(action, {
      onSuccess: () => {
        toast(SAID[action]);
        void navigate("/recurring", { replace: true });
      },
    });
  };
  const next = view.next_date ?? "";
  return (
    <section className={styles.card}>
      <h2>{view.active ? "Active" : "Paused"}</h2>
      {act.isError && (
        <p className={form.error} role="alert">
          {messageOf(act.error)}
        </p>
      )}
      {view.active ? (
        <>
          <p>Pause it to stop recording without losing the rule.</p>
          <button
            type="button"
            className={styles.secondary}
            disabled={act.isPending}
            onClick={() => {
              run("pause");
            }}
          >
            Pause
          </button>
          <p>Just this once? Skip the next one ({friendlyDate(next, today)}) and carry on after it.</p>
          <button
            type="button"
            className={styles.secondary}
            disabled={act.isPending}
            onClick={() => {
              if (!window.confirm(`Skip ${fullDay(next)}? Nothing will be recorded for it.`)) return;
              run("skip");
            }}
          >
            Skip {friendlyDate(next, today)}
          </button>
        </>
      ) : view.status !== "ended" ? (
        <>
          <p>Occurrences missed while paused are skipped.</p>
          <button
            type="button"
            className={styles.primary}
            disabled={act.isPending}
            onClick={() => {
              run("resume");
            }}
          >
            Resume
          </button>
        </>
      ) : (
        <p>It has ended. Move the end date to carry on.</p>
      )}
      <div>
        <button
          type="button"
          className={form.dangerButton}
          disabled={act.isPending}
          onClick={() => {
            if (!window.confirm("Delete this recurring transaction? Transactions it already recorded are kept."))
              return;
            run("delete");
          }}
        >
          <Icon name="trash" />
          Delete
        </button>
      </div>
    </section>
  );
}

function RuleScreen({ view, recurringId }: { view: RecurringFormView; recurringId: string | undefined }) {
  const grouping = useGrouping();
  const places = usePlaces();
  const today = useToday();
  const toast = useToast();
  const navigate = useNavigate();
  const save = useSaveRule(recurringId);
  const submit = useSubmitOnce(save);
  const [state, update] = useLines<RuleState>(() => startState(view, grouping));
  const [problem, setProblem] = useState<string | null>(null);
  const editing = recurringId !== undefined;
  const change = (next: Partial<RuleState>) => {
    update((now) => ({ ...now, ...next }));
  };
  const count = Number(state.every);

  const send = () => {
    setProblem(null);
    const lines = linesBody(state, view.groups, places);
    if (lines.problem !== undefined) {
      setProblem(lines.problem);
      return;
    }
    const every = Number.parseInt(state.every, 10);
    if (!Number.isInteger(every) || String(every) !== state.every.trim()) {
      setProblem("'every' must be a whole number!");
      return;
    }
    submit(
      {
        payee: state.payee,
        comment: state.comment,
        tags: state.tags,
        rows: lines.rows,
        frequency: state.frequency,
        every,
        start_date: state.date,
        end_date: state.end,
      },
      {
        onSuccess: () => {
          toast(SAID.saved);
          void navigate("/recurring", { replace: true });
        },
      },
    );
  };

  return (
    <>
      <Link className={form.back} to="/recurring">
        <Icon name="back" />
        Recurring
      </Link>
      <h1>{editing ? "Edit recurring transaction" : "New recurring transaction"}</h1>
      {editing && <p className={styles.origin}>{origin(view, today)}</p>}
      {editing && view.last_error && (
        <p className={form.error} role="alert">
          Couldn&apos;t record {view.last_error}. It will try again on the next run; fix the accounts or this rule.
        </p>
      )}
      <form
        className={form.form}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          send();
        }}
      >
        <Lines
          state={state}
          update={update}
          groups={view.groups}
          accountParents={view.account_parents}
          categoryParents={view.category_parents}
          dated={false}
        >
          <PayeeField
            value={state.payee}
            onChange={(payee) => {
              change({ payee });
            }}
            person={null}
            onPerson={() => undefined}
            editing={editing}
            canName={false}
          />
        </Lines>

        <div className={styles.repeat}>
          <Icon name="repeat" />
          <span className={styles.repeatLabel}>Every</span>
          <input
            type="number"
            min={1}
            max={366}
            inputMode="numeric"
            aria-label="Every how many"
            value={state.every}
            onChange={(event) => {
              change({ every: event.target.value });
            }}
          />
          <select
            aria-label="Unit"
            value={state.frequency}
            onChange={(event) => {
              if (isFrequency(event.target.value)) change({ frequency: event.target.value });
            }}
          >
            {view.frequencies.map((f) => (
              <option key={f.value} value={f.value}>
                {f.name}
                {count === 1 ? "" : "s"}
              </option>
            ))}
          </select>
        </div>
        <div className={form.metaRow}>
          <DateChip
            label="Starts"
            prefix="Starts"
            value={state.date}
            onChange={(date) => {
              change({ date });
            }}
          />
          <span className={styles.endChip}>
            <DateChip
              label="Ends (optional)"
              prefix="Ends"
              emptyLabel="never"
              value={state.end}
              onChange={(end) => {
                change({ end });
              }}
            />
            {state.end && (
              <button
                type="button"
                className={styles.endClear}
                aria-label="No end date"
                onClick={() => {
                  change({ end: null });
                }}
              >
                ✕
              </button>
            )}
          </span>
        </div>
        {state.date < today && (
          <p className={styles.hint}>A start date in the past is recorded right away for every missed date.</p>
        )}

        <NoteAndTags
          note={state.comment}
          onNote={(comment) => {
            change({ comment });
          }}
          tags={state.tags}
          onTags={(tags) => {
            change({ tags });
          }}
        />

        {(problem ?? (save.isError ? messageOf(save.error) : null)) && (
          <p className={form.error} role="alert">
            {problem ?? messageOf(save.error)}
          </p>
        )}
        <div className={form.actions}>
          <button type="submit" className={form.primary} disabled={save.isPending} aria-busy={save.isPending}>
            {editing ? "Save changes" : "Save"}
          </button>
        </div>
      </form>
      {editing && <Standing view={view} recurringId={recurringId} />}
    </>
  );
}

export function RecurringForm() {
  const { recurringId } = useParams();
  const query = useRecurringForm(recurringId);
  if (query.isError) return <LoadError error={query.error} onRetry={() => void query.refetch()} />;
  if (!query.data) return <h1 className="sr-only">Recurring transaction</h1>;
  return <RuleScreen key={recurringId ?? "new"} view={query.data} recurringId={recurringId} />;
}

/** A rule's own address (the bell's "Open rule" on the web page) opens its form. */
export function RuleAddress() {
  const { recurringId = "" } = useParams();
  return <Navigate to={`/recurring/${recurringId}/edit`} replace />;
}

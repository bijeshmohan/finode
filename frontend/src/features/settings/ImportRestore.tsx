// The preview, then confirm, of an import or a restore (partials/import_preview.html, restore_preview.html): a file
// is sent with dry_run first; what it would do is listed, and only a preview without errors offers to go ahead.
import { type ReactNode, useState } from "react";
import { useNavigate } from "react-router";

import { ApiError } from "../../api/client";
import { messageOf } from "../../api/messages";
import { useGrouping } from "../../app/currency";
import { useToast } from "../../app/toast";
import { fullDate } from "../../lib/dates";
import { formatMoney } from "../../lib/money";
import { type ImportSummary, type RestoreSummary, useImport, useRestore } from "./dataQueries";
import styles from "./Settings.module.css";

const many = (n: number, one: string, more: string) => `${String(n)} ${n === 1 ? one : more}`;

/** What a refusal says: the summary's own errors when the API sent one, else its words. */
function refusal(error: unknown): string[] {
  if (error instanceof ApiError && error.detail && typeof error.detail === "object" && "errors" in error.detail) {
    const { errors } = error.detail;
    if (Array.isArray(errors)) return errors.map(String);
  }
  return [messageOf(error)];
}

function Problems({ title, errors }: { title: string; errors: string[] }) {
  return (
    <div className={styles.error} role="alert">
      <strong>{title}</strong>
      <ul className={styles.plainList}>
        {errors.map((e) => (
          <li key={e}>{e}</li>
        ))}
      </ul>
    </div>
  );
}

function ImportReady({ summary }: { summary: ImportSummary }) {
  const grouping = useGrouping();
  const newAccounts = summary.new_accounts ?? [];
  const newCategories = summary.new_categories ?? [];
  const news = newAccounts.length;
  const cats = newCategories.length;
  return (
    <div className={styles.body}>
      <p>
        <strong>Ready to import</strong>
      </p>
      <ul className={styles.plainList}>
        <li>
          {many(summary.transactions, "transaction", "transactions")}
          {summary.date_from && summary.date_to && `, ${fullDate(summary.date_from)} to ${fullDate(summary.date_to)}`}
        </li>
        <li>
          {many(news, "new account", "new accounts")}
          {summary.accounts_reused > 0 && `, ${String(summary.accounts_reused)} existing reused`}
          {cats > 0 && `, ${many(cats, "new category", "new categories")}`}
        </li>
        <li>
          Assets {formatMoney(summary.assets, grouping)} · Liabilities {formatMoney(summary.liabilities, grouping)}
        </li>
        {summary.skipped_empty > 0 && (
          <li className={styles.muted}>
            {many(summary.skipped_empty, "zero-amount transaction", "zero-amount transactions")} skipped
          </li>
        )}
        {(summary.warnings ?? []).map((w) => (
          <li key={w} className={styles.muted}>
            {w}
          </li>
        ))}
      </ul>
      {(news > 0 || cats > 0) && (
        <details>
          <summary>New accounts and categories</summary>
          <ul className={styles.plainList}>
            {[...newAccounts, ...newCategories].map((path) => (
              <li key={path}>{path.replaceAll(":", " › ")}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function RestoreReady({ summary }: { summary: RestoreSummary }) {
  return (
    <div className={styles.body}>
      <p>
        <strong>Ready to restore</strong>
      </p>
      <ul className={styles.plainList}>
        <li>
          {many(summary.accounts, "account", "accounts")}, {many(summary.categories, "category", "categories")},{" "}
          {many(summary.transactions, "transaction", "transactions")}
          {summary.date_from &&
            summary.date_to &&
            ` from ${fullDate(summary.date_from)} to ${fullDate(summary.date_to)}`}
        </li>
        {summary.recurring > 0 && <li>{many(summary.recurring, "recurring transaction", "recurring transactions")}</li>}
        {summary.tags > 0 && <li>{many(summary.tags, "tag", "tags")}</li>}
        {summary.allocations > 0 && <li>Budget: {many(summary.allocations, "assigned amount", "assigned amounts")}</li>}
      </ul>
    </div>
  );
}

interface FlowProps<T extends { errors?: string[] }> {
  kind: "import" | "restore";
  send: {
    mutate: (
      vars: { file: File; dryRun: boolean },
      callbacks: { onSuccess: (answer: T) => void; onError: (error: unknown) => void },
    ) => void;
    isPending: boolean;
  };
  ready: (summary: T) => ReactNode;
  confirm: (summary: T) => string;
}

function Flow<T extends { errors?: string[] }>({ kind, send, ready, confirm }: FlowProps<T>) {
  const toast = useToast();
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [summary, setSummary] = useState<T | null>(null);
  const [problems, setProblems] = useState<string[] | null>(null);
  const isImport = kind === "import";

  const show = (next: T | null, wrong: string[] | null) => {
    setSummary(next);
    setProblems(wrong);
  };

  const run = (dryRun: boolean) => {
    if (!file) {
      show(null, ["Choose a file first."]); // the API's words for no file
      return;
    }
    send.mutate(
      { file, dryRun },
      {
        onSuccess: (answer) => {
          const errors = answer.errors ?? [];
          if (errors.length > 0) {
            show(null, errors);
            return;
          }
          if (dryRun) {
            show(answer, null);
            return;
          }
          toast(isImport ? "Import complete" : "Backup restored");
          void navigate("/", { replace: true });
        },
        onError: (error) => {
          show(null, refusal(error));
        },
      },
    );
  };

  return (
    <>
      <form
        className={styles.body}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          run(true);
        }}
      >
        <input
          type="file"
          aria-label={isImport ? "Ledger file" : "Backup file"}
          accept={isImport ? ".ledger,.journal,.hledger,.dat,.txt,text/plain" : ".json,application/json"}
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null);
            show(null, null);
          }}
        />
        <div className={styles.actions}>
          <button type="submit" className={styles.secondary} disabled={send.isPending}>
            {isImport ? "Preview import" : "Preview restore"}
          </button>
        </div>
      </form>
      <div aria-live="polite">
        {problems && (
          <Problems title={isImport ? "Nothing was imported." : "Nothing was restored."} errors={problems} />
        )}
        {summary && (
          <>
            {ready(summary)}
            <div className={styles.actions}>
              <button
                type="button"
                className={styles.primary}
                disabled={send.isPending}
                onClick={() => {
                  run(false);
                }}
              >
                {confirm(summary)}
              </button>
            </div>
          </>
        )}
      </div>
    </>
  );
}

export function ImportFlow() {
  const send = useImport();
  return (
    <Flow<ImportSummary>
      kind="import"
      send={send}
      ready={(summary) => <ImportReady summary={summary} />}
      confirm={(summary) => `Import ${many(summary.transactions, "transaction", "transactions")}`}
    />
  );
}

export function RestoreFlow() {
  const send = useRestore();
  return (
    <Flow<RestoreSummary>
      kind="restore"
      send={send}
      ready={(summary) => <RestoreReady summary={summary} />}
      confirm={() => "Restore everything"}
    />
  );
}

// Your data: Export and Backup as downloads from the API, Restore and Import (a preview first),
// and under "Erase or leave" Erase my books and Delete my account, each asking first and wanting the confirm word.
import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { messageOf } from "../../api/messages";
import { useToast } from "../../app/toast";
import { Icon } from "../../components/Icon";
import { LoadError } from "../../components/LoadError";
import look from "../../components/Page.module.css";
import { useDataOptions, useDeleteAccount, useErase } from "./dataQueries";
import { ImportFlow, RestoreFlow } from "./ImportRestore";
import { useLeaveSignedIn } from "./queries";
import { SettingRow } from "./SettingRow";
import styles from "./Settings.module.css";

function Confirmed({
  word,
  button,
  ask,
  pending,
  error,
  onConfirm,
}: {
  word: string;
  button: string;
  ask: string;
  pending: boolean;
  error: unknown;
  onConfirm: (typed: string) => void;
}) {
  const [typed, setTyped] = useState("");
  return (
    <form
      className={styles.body}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (!window.confirm(ask)) return;
        onConfirm(typed);
      }}
    >
      <label>
        <span>
          Type <strong>{word}</strong> to confirm
        </span>
        <input
          type="text"
          autoComplete="off"
          autoCapitalize="off"
          value={typed}
          onChange={(event) => {
            setTyped(event.target.value);
          }}
        />
      </label>
      {error !== null && (
        <p className={styles.error} role="alert">
          {messageOf(error)}
        </p>
      )}
      <button type="submit" className={styles.dangerButton} disabled={pending}>
        {button}
      </button>
    </form>
  );
}

export function DataPage() {
  const query = useDataOptions();
  const erase = useErase();
  const remove = useDeleteAccount();
  const toast = useToast();
  const navigate = useNavigate();
  const leave = useLeaveSignedIn();
  const options = query.data;
  if (query.isError) return <LoadError error={query.error} onRetry={() => void query.refetch()} />;
  return (
    <>
      <Link className={look.back} to="/settings">
        <Icon name="back" />
        Settings
      </Link>
      <div className={look.pageHead}>
        <h1>Your data</h1>
      </div>
      {options && (
        <>
          <div className={styles.tile}>
            <SettingRow id="export" title="Export" value="Ledger, CSV">
              <p className={styles.muted}>
                Ledger format opens in hledger and similar tools; CSV opens in a spreadsheet.
              </p>
              <div className={styles.actions}>
                <a className={styles.secondary} href="/api/export?format=ledger" download>
                  Export ledger file
                </a>
                <a className={styles.secondary} href="/api/export?format=csv" download>
                  Export CSV
                </a>
              </div>
            </SettingRow>
            <SettingRow id="backup" title="Backup" value="Everything, one file">
              <p className={styles.muted}>
                Everything you recorded in one file. Keep it somewhere safe. Access tokens and connected apps are not
                included.
              </p>
              <div className={styles.actions}>
                <a className={styles.secondary} href="/api/backup" download>
                  Download backup
                </a>
              </div>
              {options.can_restore ? (
                <>
                  <h3 className={styles.subhead}>Restore a backup</h3>
                  <p className={styles.muted}>Rebuilds your books from a backup file. You see a preview first.</p>
                  <RestoreFlow />
                </>
              ) : (
                <p className={styles.muted}>Restoring only works on an empty ledger.</p>
              )}
            </SettingRow>
            <SettingRow id="import" title="Import" value="From a ledger file">
              {options.can_import ? (
                <>
                  <p className={styles.muted}>
                    Start from a ledger or hledger file. You see a preview first. Accounts can be two levels deep at
                    most.
                  </p>
                  <ImportFlow />
                </>
              ) : (
                <p className={styles.muted}>
                  Importing is only available before you record transactions. Export your data first if you want to
                  start over.
                </p>
              )}
            </SettingRow>
          </div>

          <h2 className={styles.label}>Erase or leave</h2>
          <div className={styles.tile}>
            <SettingRow id="erase" title="Erase my books" danger>
              <p className={styles.muted}>
                Deletes your accounts, transactions, budget and history. You keep your login, settings and
                assistants&apos; access. This can&apos;t be undone: download a backup first.
              </p>
              <Confirmed
                word={options.confirm_word}
                button="Erase my books"
                ask="Erase all your accounts, transactions and budget? This cannot be undone."
                pending={erase.isPending}
                error={erase.error}
                onConfirm={(typed) => {
                  erase.mutate(typed, {
                    onSuccess: () => {
                      toast("Your books were erased");
                      void navigate("/", { replace: true });
                    },
                  });
                }}
              />
            </SettingRow>
            <SettingRow id="delete-account" title="Delete my account" danger>
              {options.can_delete_login ? (
                <>
                  <p className={styles.muted}>
                    Erases everything above and removes your login, settings and assistant access. You would have to
                    sign up again.
                  </p>
                  <Confirmed
                    word={options.confirm_word}
                    button="Delete my account"
                    ask="Delete your account and everything in it? This cannot be undone."
                    pending={remove.isPending}
                    error={remove.error}
                    onConfirm={(typed) => {
                      remove.mutate(typed, {
                        onSuccess: () => {
                          toast("Your account was deleted. Goodbye!");
                          leave();
                        },
                      });
                    }}
                  />
                </>
              ) : (
                <p className={styles.muted}>
                  Deleting your login isn&apos;t set up here. Erase your books above and ask the person who runs finode
                  to remove your login.
                </p>
              )}
            </SettingRow>
          </div>
        </>
      )}
    </>
  );
}

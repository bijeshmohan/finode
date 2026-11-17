// AI assistants: what is connected with its access,
// the address to sign in with Claude, a token made here (its secret shown once, kept in this page only) and the setup
// instructions.
import { useState } from "react";
import { Link } from "react-router";

import { messageOf } from "../../api/messages";
import { useToday } from "../../app/session";
import { useToast } from "../../app/toast";
import { CopyButton } from "./CopyButton";
import { Icon } from "../../components/Icon";
import { LoadError } from "../../components/LoadError";
import look from "../../components/Page.module.css";
import { friendlyDate } from "../../lib/dates";
import {
  type App,
  type Change,
  type Scope,
  type Token,
  useAssistantChange,
  useAssistants,
  useCreateToken,
} from "./assistantQueries";
import { McpSetup } from "./McpSetup";
import { SettingRow } from "./SettingRow";
import styles from "./Settings.module.css";

const LABEL: Record<string, string> = {
  read: "read only",
  write: "read & write",
  manage: "read, write & manage accounts",
};

const SCOPE_WORDS: Record<Scope, [string, string]> = {
  read: [
    "Read only.",
    "Answers questions about your accounts, balances, transactions and reports. Cannot change anything. The safe choice; you can allow changes later.",
  ],
  write: [
    "Read & write.",
    "Can also record, edit and delete transactions and add accounts. Cannot rename, merge or delete accounts. Everything it records carries its name, so you can review it.",
  ],
  manage: [
    "Read, write & manage accounts.",
    "Can also rename, move, close and reopen accounts, and merge two into one. Never deletes accounts. It changes how your whole history is organised, so allow it only for assistants you trust.",
  ],
};

const SAID = {
  access: "Access updated. It applies to the very next request.",
  revoke: "Token revoked. Assistants using it can no longer connect.",
  disconnect: "App disconnected. It can no longer reach your books.",
};

function AccessButtons({ scope, who, onScope }: { scope: string; who: string; onScope: (scope: Scope) => void }) {
  return (
    <>
      {scope !== "read" && (
        <button
          type="button"
          className={styles.small}
          onClick={() => {
            onScope("read");
          }}
        >
          Make read only
        </button>
      )}
      {scope === "manage" && (
        <button
          type="button"
          className={styles.small}
          onClick={() => {
            onScope("write");
          }}
        >
          Stop account changes
        </button>
      )}
      {scope === "read" && (
        <button
          type="button"
          className={styles.small}
          onClick={() => {
            if (window.confirm(`Let ${who} record, edit and delete transactions?`)) onScope("write");
          }}
        >
          Allow changes
        </button>
      )}
      {scope !== "manage" && (
        <button
          type="button"
          className={styles.small}
          onClick={() => {
            if (window.confirm(`Let ${who} also rename, move, close and merge your accounts?`)) onScope("manage");
          }}
        >
          Allow account changes
        </button>
      )}
    </>
  );
}

function Connected({ apps, tokens }: { apps: App[]; tokens: Token[] }) {
  const today = useToday();
  const toast = useToast();
  const change = useAssistantChange();
  const day = (iso: string) => friendlyDate(iso.slice(0, 10), today);
  const used = (iso: string | null | undefined) => (iso ? `last used ${day(iso)}` : "never used");
  const run = (next: Change, said: string) => {
    change.mutate(next, {
      onSuccess: () => {
        toast(said);
      },
    });
  };
  const badge = (scope: string) => (
    <span className={scope === "read" ? styles.badge : `${styles.badge} ${styles.badgeWrite}`}>
      {LABEL[scope] ?? scope}
    </span>
  );
  if (apps.length === 0 && tokens.length === 0) return <p className={styles.muted}>Nothing connected yet.</p>;
  return (
    <>
      {change.isError && (
        <p className={styles.error} role="alert">
          {messageOf(change.error)}
        </p>
      )}
      <ul className={styles.tokens}>
        {apps.map((g) => (
          <li key={g.id}>
            <span>
              <strong>{g.client_name}</strong>
              {badge(g.scope)}
              <span className={styles.tokenLine}>
                Signed in · connected {day(g.created)} · {used(g.last_used)}
              </span>
            </span>
            <span className={styles.rowActions}>
              <AccessButtons
                scope={g.scope}
                who={g.client_name}
                onScope={(scope) => {
                  run({ what: "app", id: g.id, scope }, SAID.access);
                }}
              />
              <button
                type="button"
                className={styles.small}
                onClick={() => {
                  if (window.confirm(`Disconnect ${g.client_name}? It stops working at once.`)) {
                    run({ what: "disconnect", id: g.id }, SAID.disconnect);
                  }
                }}
              >
                Disconnect
              </button>
            </span>
          </li>
        ))}
        {tokens.map((t) => (
          <li key={t.id}>
            <span>
              <strong>{t.name}</strong>
              {badge(t.scope)}
              <span className={styles.tokenLine}>
                Token {t.prefix}… · created {day(t.created)} · {used(t.last_used)}
              </span>
            </span>
            <span className={styles.rowActions}>
              <AccessButtons
                scope={t.scope}
                who={`assistants using '${t.name}'`}
                onScope={(scope) => {
                  run({ what: "token", id: t.id, scope }, SAID.access);
                }}
              />
              <button
                type="button"
                className={styles.small}
                onClick={() => {
                  if (window.confirm(`Revoke '${t.name}'? Assistants using it stop working at once.`)) {
                    run({ what: "revoke", id: t.id }, SAID.revoke);
                  }
                }}
              >
                Revoke
              </button>
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}

function NewToken({ url }: { url: string }) {
  const create = useCreateToken();
  const [name, setName] = useState("");
  const [scope, setScope] = useState<Scope>("read");
  // The secret lives in this page only: leaving drops it, and it is never cached.
  const [made, setMade] = useState<{ name: string; secret: string } | null>(null);
  const [title, words] = SCOPE_WORDS[scope];
  return (
    <>
      <form
        className={styles.body}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate(
            { name: name.trim(), scope },
            {
              onSuccess: (answer) => {
                setMade({ name: answer.name, secret: answer.secret });
                setName("");
                create.reset();
              },
            },
          );
        }}
      >
        <label>
          Name
          <input
            type="text"
            maxLength={40}
            autoComplete="off"
            placeholder="e.g. Claude Desktop"
            aria-describedby="token-name-hint"
            value={name}
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
        </label>
        <span id="token-name-hint" className={styles.hintLine}>
          Where you&apos;ll use it. It shows up next to everything the assistant records.
        </span>
        <fieldset className={styles.fieldset}>
          <legend>Access</legend>
          <div className={styles.scopes}>
            {(["read", "write", "manage"] as const).map((s) => (
              <label key={s}>
                <input
                  type="radio"
                  name="scope"
                  checked={scope === s}
                  onChange={() => {
                    setScope(s);
                  }}
                />
                <span>{s === "read" ? "Read" : s === "write" ? "Write" : "Manage"}</span>
              </label>
            ))}
          </div>
          <p className={styles.muted}>
            <strong>{title}</strong> {words}
          </p>
        </fieldset>
        {create.isError && (
          <p className={styles.error} role="alert">
            {messageOf(create.error)}
          </p>
        )}
        <button type="submit" className={styles.primary} disabled={create.isPending}>
          <Icon name="key" />
          Create token
        </button>
      </form>
      {made && (
        <section className={styles.card}>
          <h2>{made.name} is ready</h2>
          <p className={styles.notice}>
            Copy this token now. finode keeps only a fingerprint of it, so it can&apos;t be shown again.
          </p>
          <div className={styles.copyRow}>
            <code className={styles.secret} id="token-secret">
              {made.secret}
            </code>
            <CopyButton text={made.secret} label="Copy token" target="token-secret" />
          </div>
          <McpSetup url={url} secret={made.secret} />
        </section>
      )}
    </>
  );
}

export function AssistantsPage() {
  const query = useAssistants();
  const view = query.data;
  if (query.isError) return <LoadError error={query.error} onRetry={() => void query.refetch()} />;
  return (
    <>
      <Link className={look.back} to="/settings">
        <Icon name="back" />
        Settings
      </Link>
      <div className={look.pageHead}>
        <h1>AI assistants</h1>
      </div>
      {view && (
        <>
          <h2 className={styles.label}>Connected</h2>
          <div className={styles.tile}>
            <Connected apps={view.apps} tokens={view.tokens} />
          </div>

          <h2 className={styles.label}>Connect a new one</h2>
          <div className={styles.tile}>
            <SettingRow id="signin" title="Sign in with Claude">
              <p className={styles.muted}>
                Add this address as a custom connector in Claude or another app, then choose the access level.
              </p>
              <div className={styles.copyRow}>
                <code className={styles.secret} id="mcp-address">
                  {view.mcp_url}
                </code>
                <CopyButton text={view.mcp_url} label="Copy" target="mcp-address" />
              </div>
            </SettingRow>
            <SettingRow id="token" title="Use a token" value="Claude Code, Cursor">
              <NewToken url={view.mcp_url} />
            </SettingRow>
            <SettingRow id="setup" title="Setup instructions for tokens">
              <McpSetup url={view.mcp_url} secret={null} />
            </SettingRow>
          </div>
        </>
      )}
    </>
  );
}

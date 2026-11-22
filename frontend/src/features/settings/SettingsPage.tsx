// Settings: your name, the currency, the look and the order of the account types, the links to Your data, Tags, People, Recurring and AI
// assistants, About (feedback, the test notice) and Sign out.
import { useState } from "react";

import { messageOf } from "../../api/messages";
import { useCurrencies, useProfile } from "../../app/currency";
import { useAuthOptions } from "../../app/options";
import { useSession } from "../../app/session";
import { useToast } from "../../app/toast";
import look from "../../components/Page.module.css";
import { TestNotice } from "../../components/TestNotice";
import { chooseTheme, readTheme, type Theme } from "../../lib/theme";
import { useLeaveSignedIn, useSignOut, useUpdateProfile } from "./queries";
import { SettingLink, SettingRow } from "./SettingRow";
import styles from "./Settings.module.css";
import { TypeOrderRow } from "./TypeOrderRow";

const THEMES: [Theme, string][] = [
  ["auto", "Match device"],
  ["light", "Light"],
  ["dark", "Dark"],
];

function NameRow({ first, last, email }: { first: string; last: string; email: string | null }) {
  const update = useUpdateProfile();
  const toast = useToast();
  const [firstName, setFirstName] = useState(first);
  const [lastName, setLastName] = useState(last);
  const shown = [first, last].filter(Boolean).join(" ");
  return (
    <SettingRow id="name" title={shown || "Your profile"} value={email ?? ""}>
      <form
        className={styles.body}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          update.mutate(
            { first_name: firstName.trim(), last_name: lastName.trim() },
            {
              onSuccess: () => {
                toast("Profile saved");
              },
            },
          );
        }}
      >
        <div className={styles.names}>
          <label>
            First name
            <input
              type="text"
              maxLength={40}
              autoComplete="given-name"
              value={firstName}
              onChange={(event) => {
                setFirstName(event.target.value);
              }}
            />
          </label>
          <label>
            Last name
            <input
              type="text"
              maxLength={40}
              autoComplete="family-name"
              value={lastName}
              onChange={(event) => {
                setLastName(event.target.value);
              }}
            />
          </label>
        </div>
        {email && (
          <p className={styles.muted}>Your email ({email}) is used to sign in and can&apos;t be changed here.</p>
        )}
        {update.isError && (
          <p className={styles.error} role="alert">
            {messageOf(update.error)}
          </p>
        )}
        <button type="submit" className={styles.primary} disabled={update.isPending}>
          Save name
        </button>
      </form>
    </SettingRow>
  );
}

function CurrencyRow({ code }: { code: string }) {
  const update = useUpdateProfile();
  const currencies = useCurrencies();
  const toast = useToast();
  const [chosen, setChosen] = useState(code);
  return (
    <SettingRow id="currency" title="Currency" value={code}>
      <form
        className={styles.body}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          update.mutate(
            { default_currency: chosen },
            {
              onSuccess: () => {
                toast("Currency saved");
              },
            },
          );
        }}
      >
        <p className={styles.muted}>Changing it only changes the label: nothing is converted.</p>
        <label>
          Currency
          <select
            value={chosen}
            onChange={(event) => {
              setChosen(event.target.value);
            }}
          >
            {(currencies.data ?? []).map((c) => (
              <option key={c.code} value={c.code}>
                {c.code} · {c.name}
              </option>
            ))}
          </select>
        </label>
        {update.isError && (
          <p className={styles.error} role="alert">
            {messageOf(update.error)}
          </p>
        )}
        <button type="submit" className={styles.primary} disabled={update.isPending}>
          Save currency
        </button>
      </form>
    </SettingRow>
  );
}

function AppearanceRow() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  return (
    <SettingRow id="appearance" title="Appearance" value={THEMES.find(([t]) => t === theme)?.[1] ?? "Match device"}>
      <p className={styles.muted}>Applies to this browser only.</p>
      <div className={styles.themes} role="group" aria-label="Theme">
        {THEMES.map(([value, name]) => (
          <button
            key={value}
            type="button"
            aria-pressed={theme === value}
            onClick={() => {
              chooseTheme(value);
              setTheme(value);
            }}
          >
            {name}
          </button>
        ))}
      </div>
    </SettingRow>
  );
}

export function SettingsPage() {
  const session = useSession();
  const profile = useProfile();
  const options = useAuthOptions();
  const signOut = useSignOut();
  const leave = useLeaveSignedIn();
  const p = profile.data;
  const notice = options.data?.test_notice ?? false;
  return (
    <>
      <div className={look.pageHead}>
        <h1>Settings</h1>
      </div>
      {p && (
        <div className={styles.tile}>
          <NameRow first={p.first_name ?? ""} last={p.last_name ?? ""} email={session.email ?? null} />
        </div>
      )}

      <h2 className={styles.label}>Preferences</h2>
      <div className={styles.tile}>
        {p && <CurrencyRow code={p.default_currency ?? ""} />}
        <AppearanceRow />
        {p && <TypeOrderRow />}
      </div>

      <h2 className={styles.label}>Your data</h2>
      <div className={styles.tile}>
        <SettingLink id="data" title="Backup, export and import" to="/profile/data" />
        <SettingLink id="tags" title="Tags" to="/tags" />
        <SettingLink id="people" title="People" to="/people" />
        <SettingLink id="recurring" title="Recurring transactions" to="/recurring" />
        <SettingLink id="assistants" title="AI assistants" to="/profile/assistants" />
      </div>

      {session.feedback_url || notice ? (
        <h2 className={styles.label}>About</h2>
      ) : (
        <h2 className={styles.label} aria-hidden="true">
          &nbsp;
        </h2>
      )}
      <div className={styles.tile}>
        {session.feedback_url && <SettingLink id="feedback" title="Send feedback" to={session.feedback_url} />}
        {notice && (
          <SettingRow id="about" title="About this test" value="Please read">
            <TestNotice />
          </SettingRow>
        )}
        <div className={styles.setting}>
          <button
            type="button"
            className={styles.signout}
            disabled={signOut.isPending}
            onClick={() => {
              signOut.mutate(undefined, { onSuccess: leave });
            }}
          >
            Sign out
          </button>
          {signOut.isError && (
            <p className={styles.error} role="alert">
              {messageOf(signOut.error)}
            </p>
          )}
        </div>
      </div>
    </>
  );
}

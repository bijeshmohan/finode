// The consent screen of "Sign in with finode" for assistants: Supabase sends the person here with
// an authorization id; they choose what the app may do, or deny, and are sent back to the app at the address the API
// checked. An app already decided is sent back at once.
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useSearchParams } from "react-router";

import { data } from "../../api/client";
import { useApi } from "../../api/context";
import { messageOf } from "../../api/messages";
import { leaveTo } from "../../app/leave";
import { Icon } from "../../components/Icon";
import look from "../../components/Page.module.css";
import { Access, type AccessLevel } from "./Access";
import styles from "./Consent.module.css";

const NO_ID = "This page is opened by an app that wants to connect. Start from the app's connector settings.";

function CantConnect({ message }: { message: string }) {
  return (
    <>
      <Link className={look.back} to="/profile/assistants">
        <Icon name="back" />
        AI assistants
      </Link>
      <h1>Can&apos;t connect</h1>
      <p className={styles.error} role="alert">
        {message}
      </p>
    </>
  );
}

const ALLOW: [AccessLevel, string][] = [
  ["read", "Allow read only"],
  ["write", "Allow read & write"],
  ["manage", "Allow read, write & manage accounts"],
];

function Consent({ id }: { id: string }) {
  const api = useApi();
  const details = useQuery({
    queryKey: ["consent", id],
    queryFn: () =>
      data(api.GET("/api/oauth/consent/{authorization_id}", { params: { path: { authorization_id: id } } })),
    retry: false,
    staleTime: Infinity,
  });
  const decide = useMutation({
    mutationFn: (body: { decision: "allow" | "deny"; access: AccessLevel }) =>
      data(api.POST("/api/oauth/consent/{authorization_id}", { params: { path: { authorization_id: id } }, body })),
    onSuccess: (answer) => {
      leaveTo(answer.redirect_url);
    },
  });
  const back = details.data?.redirect_url;
  useEffect(() => {
    if (back) leaveTo(back);
  }, [back]);

  if (details.isError) return <CantConnect message={messageOf(details.error)} />;
  if (decide.isError) return <CantConnect message={messageOf(decide.error)} />;
  const app = details.data;
  if (!app || back) return <h1 className="sr-only">Connect an app</h1>;
  return (
    <>
      <h1>Connect {app.client_name}?</h1>
      <div className={styles.card}>
        <p>
          <strong>{app.client_name}</strong> wants to work with your finode books on your behalf.
          {app.client_uri && <span className={styles.muted}> ({app.client_uri})</span>}
        </p>
        {app.redirect_uri && (
          <p className={styles.muted}>
            After you decide, you&apos;ll be sent back to <code>{app.redirect_uri}</code>.
          </p>
        )}
        <h2 className={styles.choose}>What should it be allowed to do?</h2>
        <div className={styles.choices}>
          {ALLOW.map(([level, label]) => (
            <div key={level} className={styles.choice}>
              <Access level={level} />
              <button
                type="button"
                className={styles.allow}
                disabled={decide.isPending}
                onClick={() => {
                  decide.mutate({ decision: "allow", access: level });
                }}
              >
                {label}
              </button>
            </div>
          ))}
        </div>
        <p className={styles.muted}>
          You can change this or disconnect the app any time under Profile › AI assistants. Only connect apps you trust.
        </p>
        <div>
          <button
            type="button"
            className={styles.deny}
            disabled={decide.isPending}
            onClick={() => {
              decide.mutate({ decision: "deny", access: "read" });
            }}
          >
            Deny
          </button>
        </div>
      </div>
    </>
  );
}

export function ConsentPage() {
  const [params] = useSearchParams();
  const id = (params.get("authorization_id") ?? "").trim();
  if (!id) return <CantConnect message={NO_ID} />;
  return <Consent id={id} />;
}

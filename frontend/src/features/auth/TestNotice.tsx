// The notice shown at sign-up while finode is a test with invited people (partials/test_notice.html, word for word).
import styles from "./fields.module.css";

export function TestNotice() {
  return (
    <div className={styles.testNotice} role="note">
      <strong>This is a test.</strong> This is a test version run by a person, not a company. Your data is stored on a
      server I can technically access, but I won&apos;t look at it unless you ask me to help with a problem. Data may be
      reset. Nothing here is financial advice.
    </div>
  );
}

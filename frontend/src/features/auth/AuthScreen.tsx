// The bare page every sign-in screen sits on (login.html): no tab bar, no card, the brand and a centred column.
import type { ReactNode } from "react";

import styles from "./AuthScreen.module.css";

export function AuthScreen({ intro, children }: { intro?: ReactNode; children: ReactNode }) {
  return (
    <main className={styles.page}>
      <section className={styles.column}>
        <h1 className={styles.brand}>
          <img src="/favicon.svg" alt="" width="44" height="44" />
          finode
        </h1>
        {intro !== undefined && <p className={styles.intro}>{intro}</p>}
        {children}
      </section>
    </main>
  );
}

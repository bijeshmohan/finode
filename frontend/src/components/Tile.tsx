// A bento tile: the slip rows sit on (the tile rule at the end of app/static/style.css).
import { type ReactNode, useId } from "react";

import styles from "./Tile.module.css";

export function Tile({ title, children }: { title?: string; children: ReactNode }) {
  const id = useId();
  return (
    <section className={styles.tile} aria-labelledby={title ? id : undefined}>
      {title && (
        <h2 id={id} className={styles.title}>
          {title}
        </h2>
      )}
      {children}
    </section>
  );
}

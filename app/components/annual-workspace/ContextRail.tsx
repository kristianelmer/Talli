import type { AnnualWorkspaceViewModel } from "../../lib/annual-workspace";
import styles from "./annual-workspace.module.css";

export function ContextRail({ model }: { model: AnnualWorkspaceViewModel }) {
  const deadlines = model.obligations
    .map((item) => item.deadline)
    .filter((item) => item !== null)
    .sort((left, right) => left.deadline.localeCompare(right.deadline))
    .slice(0, 3);
  return (
    <aside className={styles.contextRail} aria-label="Kontekst">
      <section className={styles.contextGroup}>
        <h2>Frister</h2>
        <ul className={styles.contextList}>{deadlines.map((item) => <li key={item.filing}><strong>{item.filing}</strong>{item.deadline}</li>)}</ul>
      </section>
      <section className={styles.contextGroup}>
        <h2>Dokumenter</h2>
        {model.documents.length ? <ul className={styles.contextList}>{model.documents.slice(0, 5).map((item) => <li key={item.id}><strong>{item.name}</strong>{item.status}</li>)}</ul> : <p className={styles.muted}>Ingen dokumenter for året ennå.</p>}
      </section>
      <section className={styles.contextGroup}>
        <h2>Kontroll</h2>
        {model.comments.length ? <ul className={styles.contextList}>{model.comments.slice(0, 5).map((item) => <li key={item.id}><strong>{item.severity === "hard_block" ? "Må løses" : "Kommentar"}</strong>{item.body}</li>)}</ul> : <p className={styles.muted}>Ingen kontrollkommentarer.</p>}
      </section>
    </aside>
  );
}

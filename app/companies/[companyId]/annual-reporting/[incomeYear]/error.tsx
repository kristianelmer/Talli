"use client";

import styles from "../../../../components/annual-workspace/annual-workspace.module.css";

export default function AnnualReportingError({ reset }: { reset: () => void }) {
  return (
    <section>
      <h1>Årsrapporteringen kunne ikke lastes</h1>
      <p>Prøv på nytt. Hvis problemet fortsetter, kan du gå tilbake til selskapsoversikten.</p>
      <button className={styles.primaryButton} onClick={reset} type="button">Prøv igjen</button>
    </section>
  );
}

import type { Metadata } from "next";

import { EligibilityChecker } from "./EligibilityChecker";
import styles from "./eligibility.module.css";

export const metadata: Metadata = {
  title: "Sjekk selskapet gratis – Talli",
  description: "Finn ut om Talli passer for selskapsåret før du oppretter konto.",
};

export default function CompanyEligibilityPage() {
  return (
    <main className={styles.page}>
      <section className={styles.shell}>
        <p className={styles.eyebrow}>Gratis · ingen konto · ingen betaling</p>
        <h1>Sjekk selskapet gratis</h1>
        <p className={styles.intro}>
          Først sjekker vi offentlige fakta. Deretter får du ett spørsmål om gangen.
        </p>
        <p className={styles.provisional}>Foreløpig svar er alltid merket tydelig.</p>
        <EligibilityChecker />
      </section>
    </main>
  );
}

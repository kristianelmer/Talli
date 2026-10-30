import type { AnnualWorkspaceContext } from "../../lib/annual-workspace";
import styles from "./annual-workspace.module.css";

export function AnnualWorkspaceRecovery({ context }: { context: AnnualWorkspaceContext }) {
  const overview = `/companies/${context.companyId}/annual-reporting/${context.incomeYear}`;
  const scope = new URLSearchParams({ companyId: context.companyId, incomeYear: String(context.incomeYear) });
  return (
    <main className={`${styles.workspace} ${styles.main}`}>
      <section className={styles.section} aria-labelledby="annual-recovery-title">
        <header className={styles.pageHeader}>
          <div>
            <h1 id="annual-recovery-title">Årsrapporteringen er midlertidig utilgjengelig</h1>
            <p>Inntektsår {context.incomeYear}</p>
          </div>
        </header>
        <p>Vi kunne ikke hente årets grunnlag nå. Leveringsstatus og innsendingsklarhet er ukjent. Ingen data er endret.</p>
        <p><a className={styles.primaryButton} href={overview}>Prøv årsoversikten igjen</a></p>
        <h2>Åpne lagrede dokumenter</h2>
        <p>Du kan prøve dokumentvisningene mens årsoversikten er utilgjengelig.</p>
        <ul className={styles.contextList}>
          <li><a href={`/filing/aksjonaerregisteroppgaven?${scope}`}>Aksjonærregisteroppgaven</a></li>
          <li><a href={`/filing/skattemelding?${scope}`}>Skattemelding for AS</a></li>
          <li><a href={`/filing/aarsregnskap?${scope}`}>Årsregnskap</a></li>
        </ul>
        <p><a href="/dashboard">Til selskapsoversikten</a></p>
      </section>
    </main>
  );
}

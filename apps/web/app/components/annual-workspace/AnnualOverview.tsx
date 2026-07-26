import Link from "next/link";

import type { AnnualWorkspaceViewModel } from "../../lib/annual-workspace";
import { ContextRail } from "./ContextRail";
import { ObligationRow } from "./ObligationRow";
import styles from "./annual-workspace.module.css";

export function AnnualOverview({ model }: { model: AnnualWorkspaceViewModel }) {
  return (
    <div className={styles.overviewLayout}>
      <section aria-labelledby="annual-title">
        <header className={styles.pageHeader}>
          <div><h1 id="annual-title">Årsrapportering</h1><p>{model.company.name} · {model.context.incomeYear}</p></div>
        </header>
        <section aria-labelledby="next-action-title" className={styles.nextAction}>
          <div><h2 id="next-action-title">Neste steg</h2><p>Vi har funnet det viktigste åpne punktet.</p></div>
          <Link className={styles.primaryButton} href={model.nextAction.href}>{model.nextAction.label}</Link>
        </section>
        <div className={styles.obligationList}>
          {model.obligations.map((obligation) => <ObligationRow key={obligation.obligation} obligation={obligation} />)}
        </div>
        <p className={styles.flowHint}>Du kan åpne pliktene i valgfri rekkefølge. Talli viser hva som må løses før innsending.</p>
      </section>
      <ContextRail model={model} />
    </div>
  );
}

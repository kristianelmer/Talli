import Link from "next/link";

import type { AnnualObligationViewModel } from "../../lib/annual-workspace";
import styles from "./annual-workspace.module.css";

const description = {
  aksjonaerregisteroppgaven: "Kontroller eiere og aksjebevegelser for året.",
  aarsregnskap: "Gjør regnskap, noter og årsopplysninger klare.",
  skattemelding: "Kontroller skattegrunnlaget for holdingselskapet.",
} as const;

export function ObligationRow({ obligation }: { obligation: AnnualObligationViewModel }) {
  const openCount = obligation.hardBlocks.length + obligation.warnings.length;
  return (
    <article className={styles.obligationRow} data-obligation={obligation.obligation} data-status={obligation.status}>
      <div>
        <h2><Link href={obligation.href}>{obligation.label}</Link></h2>
        <p className={styles.muted}>{description[obligation.obligation]}</p>
        <div className={styles.rowMeta}>
          <span className={styles.status} aria-label={`Status: ${obligation.statusLabel}`}><span className={styles.statusDot} aria-hidden="true" />{obligation.statusLabel}</span>
          {obligation.deadline ? <span>Frist {obligation.deadline.deadline}</span> : null}
          {openCount ? <span>{openCount} åpne {openCount === 1 ? "punkt" : "punkter"}</span> : null}
        </div>
      </div>
      <Link className={styles.secondaryButton} href={obligation.nextAction.href}>{obligation.nextAction.label}</Link>
    </article>
  );
}

import Link from "next/link";
import type { ReactNode } from "react";

import { annualReviewHref, type AnnualWorkspaceViewModel } from "../../lib/annual-workspace";
import styles from "./annual-workspace.module.css";

const roleLabel = { owner: "Eier", reviewer: "Kontrollør", read_only: "Lesetilgang" } as const;

export function AnnualWorkspaceShell({ model, children }: { model: AnnualWorkspaceViewModel; children: ReactNode }) {
  return (
    <div className={styles.workspace}>
      <header className={styles.topbar}>
        <Link className={styles.brand} href="/">Talli</Link>
        <div className={styles.companyContext}>
          <span>{model.company.name} · {model.context.incomeYear}</span>
          <span className={styles.role}>{roleLabel[model.role]}</span>
        </div>
      </header>
      <div className={styles.frame}>
        <nav className={styles.nav} aria-label="Årsrapportering">
          <p className={styles.navLabel}>Årsrapportering</p>
          <Link href={model.obligations[0].href.replace(/\/[^/]+$/, "")}>Oversikt</Link>
          {model.obligations.map((item) => <Link key={item.obligation} href={item.href}>{item.label}</Link>)}
          <Link href={annualReviewHref(model.context)}>Gjennomgang</Link>
          <hr className={styles.navRule} />
          <Link href="/#everyday-actions">Løpende handlinger</Link>
        </nav>
        <main className={styles.main}>{children}</main>
      </div>
    </div>
  );
}

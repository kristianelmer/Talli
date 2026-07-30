import Link from "next/link";
import type { ReactNode } from "react";

import type { AnnualWorkspaceViewModel } from "../../lib/annual-workspace";
import styles from "./annual-workspace.module.css";

const roleLabel = { owner: "Eier", reviewer: "Kontrollør", read_only: "Lesetilgang" } as const;

export function AnnualWorkspaceShell({ model, children }: { model: AnnualWorkspaceViewModel; children: ReactNode }) {
  const annualOverviewHref = model.obligations[0].href.replace(/\/[^/]+$/, "");

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
        <nav className={styles.nav} aria-label="Arbeidsflate">
          <p className={styles.navLabel}>Arbeidsflate</p>
          <Link className={styles.navActive} href={annualOverviewHref} aria-current="page">Årsrapportering</Link>
          <hr className={styles.navRule} />
          <Link href="/actions">Handlinger</Link>
          <Link href="/transactions">Transaksjoner</Link>
          <Link href="/documents">Dokumenter</Link>
          <Link href="/connections">Selskap</Link>
          <Link href="/billing">Innstillinger</Link>
        </nav>
        <main className={styles.main}>{children}</main>
      </div>
    </div>
  );
}

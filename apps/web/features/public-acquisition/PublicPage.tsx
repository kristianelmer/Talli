import Link from "next/link";
import type { ReactNode } from "react";

import styles from "./PublicPage.module.css";

type PublicPageProps = {
  eyebrow: string;
  title: string;
  lede: string;
  children: ReactNode;
};

const footerLinks = [
  ["Passer Talli?", "/passer-talli"],
  ["Pris", "/pris"],
  ["Hjelp", "/hjelp"],
  ["Sikkerhet", "/sikkerhet"],
  ["Status", "/status"],
  ["Vilkår", "/vilkar"],
  ["Personvern", "/personvern"],
  ["Databehandleravtale", "/databehandleravtale"],
] as const;

export function PublicPage({ eyebrow, title, lede, children }: PublicPageProps) {
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <Link className={styles.brand} href="/" aria-label="Talli forside">
          <span className={styles.brandMark} aria-hidden="true" />
          Talli
        </Link>
        <Link className={styles.back} href="/">Til forsiden</Link>
      </header>
      <main className={styles.main}>
        <p className={styles.eyebrow}>{eyebrow}</p>
        <h1 className={styles.title}>{title}</h1>
        <p className={styles.lede}>{lede}</p>
        {children}
      </main>
      <footer className={styles.footer}>
        <div className={styles.footerInner}>
          <nav className={styles.footerNav} aria-label="Offentlig informasjon">
            {footerLinks.map(([label, href]) => <Link href={href} key={href}>{label}</Link>)}
          </nav>
          <span>ELMER WELFIS · org.nr. 930 835 978 · post@talli.no</span>
        </div>
      </footer>
    </div>
  );
}

export { styles as publicPageStyles };

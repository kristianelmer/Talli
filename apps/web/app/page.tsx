import type { Metadata } from "next";
import Link from "next/link";

import { publicRecruitmentOffer as c } from "../features/public-acquisition";
import { LinkButton } from "./components/ui";
import styles from "./page.module.css";

export const metadata: Metadata = {
  title: c.metadata.title,
  description: c.metadata.description,
  alternates: { canonical: "/" },
};

const structuredData = [
  {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: "Talli",
    legalName: "ELMER WELFIS",
    url: "https://talli.no",
    email: "post@talli.no",
    identifier: "930835978",
  },
  {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name: "Talli",
    applicationCategory: "BusinessApplication",
    operatingSystem: "Web",
    description: c.metadata.description,
    offers: {
      "@type": "Offer",
      price: "1490",
      priceCurrency: "NOK",
      availability: "https://schema.org/OutOfStock",
      description: "Betaling er ikke åpnet; gratis rekrutteringsmodus.",
    },
  },
] as const;

export default function Home() {
  return (
    <div className={styles.page}>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData) }}
      />
      <header className={styles.header}>
        <Link className={styles.brand} href="/" aria-label="Talli forside">
          <span className={styles.brandMark} aria-hidden="true" />
          {c.brand}
        </Link>
        <Link className={styles.signIn} href="/login">Logg inn</Link>
      </header>

      <main className={styles.main}>
        <section className={styles.hero} aria-labelledby="home-title">
          <p className={styles.mode}>{c.recruitmentNotice}</p>
          <p className={styles.eyebrow}>{c.eyebrow}</p>
          <h1 className={styles.title} id="home-title">{c.title}</h1>
          <p className={styles.lede}>{c.supportingLine}</p>
          <div className={styles.primaryAction}>
            <LinkButton href={c.primaryAction.href} variant="primary" size="lg">
              {c.primaryAction.label}
            </LinkButton>
          </div>
        </section>

        <section className={styles.section} aria-labelledby="included-title">
          <h2 className={styles.sectionTitle} id="included-title">{c.includedTitle}</h2>
          <div className={styles.cards}>
            {c.filings.map((filing) => (
              <article className={styles.card} key={filing}>
                <h3>{filing}</h3>
              </article>
            ))}
          </div>
          <p className={styles.lede}>{c.reconstruction}</p>
          <details className={styles.promiseDetails}>
            <summary>Se hele det versjonerte selskapsårsløftet</summary>
            <ul>
              {c.includedCapabilityClaims.map((claim) => (
                <li key={claim}>{claim}</li>
              ))}
            </ul>
          </details>
        </section>

        <section className={styles.scopeCard} aria-labelledby="scope-title">
          <h2 id="scope-title">{c.scope.title}</h2>
          <p>{c.scope.supported}</p>
          <p>{c.scope.blocked}</p>
          <p>{c.scope.nextStep}</p>
        </section>

        <section className={styles.section} aria-labelledby="steps-title">
          <h2 className={styles.sectionTitle} id="steps-title">Slik fungerer gratissjekken</h2>
          <ol className={styles.steps}>
            {c.steps.map((step, index) => (
              <li className={styles.step} key={step.title}>
                <span className={styles.stepNumber} aria-hidden="true">{index + 1}</span>
                <h3>{step.title}</h3>
                <p>{step.body}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className={styles.priceGrid} aria-labelledby="price-title">
          <article className={styles.priceCard}>
            <h2 id="price-title">{c.priceTitle}</h2>
            <p className={styles.priceLine}>{c.priceLine}</p>
            <p className={styles.restriction}>{c.priceRestriction}</p>
          </article>
          <article className={styles.priceCard}>
            <h2>{c.refundTitle}</h2>
            <p>{c.refundPromise}</p>
          </article>
        </section>

        <section className={styles.trust} aria-labelledby="proof-title">
          <h2 className={styles.sectionTitle} id="proof-title">{c.proofTitle}</h2>
          <p>{c.proofBody}</p>
          <nav className={styles.trustLinks} aria-label="Dokumentasjon og vilkår">
            {c.proofLinks.map((link) => (
              <Link href={link.href} key={link.href}>{link.label}</Link>
            ))}
          </nav>
          <p>{c.operator}</p>
          <p>{c.nonAffiliation}</p>
        </section>

        <section className={styles.section} aria-labelledby="faq-title">
          <h2 className={styles.sectionTitle} id="faq-title">{c.faqTitle}</h2>
          <div className={styles.faqList}>
            {c.faq.map((item) => (
              <details className={styles.faqItem} key={item.question}>
                <summary>{item.question}</summary>
                <p>{item.answer}</p>
              </details>
            ))}
          </div>
        </section>

        <section className={styles.finalAction} aria-labelledby="final-action-title">
          <h2 id="final-action-title">{c.finalTitle}</h2>
          <p>{c.finalBody}</p>
          <LinkButton href={c.primaryAction.href} variant="secondary" size="lg">
            {c.primaryAction.label}
          </LinkButton>
        </section>
      </main>

      <footer className={styles.footer}>
        <div className={styles.footerInner}>
          <nav className={styles.footerLinks} aria-label="Juridisk og kontakt">
            <Link href="/passer-talli">Passer Talli?</Link>
            <Link href="/pris">Pris</Link>
            <Link href="/hjelp">Hjelp</Link>
            <Link href="/sikkerhet">Sikkerhet</Link>
            <Link href="/status">Status</Link>
            <Link href="/vilkar">Vilkår</Link>
            <Link href="/personvern">Personvern</Link>
            <Link href="/databehandleravtale">Databehandleravtale</Link>
          </nav>
          <p className={styles.footerNote}>{c.nonAffiliation}</p>
          <span>© 2026 Talli</span>
        </div>
      </footer>
    </div>
  );
}

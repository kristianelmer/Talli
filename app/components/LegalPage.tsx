import Link from "next/link";

import { ownerCopy } from "../lib/copy";

type LegalSection = {
  heading: string;
  body: readonly string[];
  bullets: readonly string[];
};

type LegalDoc = {
  title: string;
  intro: string;
  sections: readonly LegalSection[];
};

export function LegalPage({ doc }: { doc: LegalDoc }) {
  const c = ownerCopy.legal;
  return (
    <div className="legalShell">
      <article className="legalDoc">
        <div className="appBrand">
          <span className="appBrandMark" aria-hidden="true" />
          <span>{ownerCopy.brand}</span>
        </div>
        <p className="legalMeta">
          {c.lastUpdatedLabel}: {c.lastUpdated}
        </p>
        <h1 className="legalTitle">{doc.title}</h1>
        <p className="legalIntro">{doc.intro}</p>
        {doc.sections.map((section) => (
          <section key={section.heading} className="legalSection">
            <h2>{section.heading}</h2>
            {section.body.map((paragraph, i) => (
              <p key={i}>{paragraph}</p>
            ))}
            {section.bullets.length > 0 ? (
              <ul>
                {section.bullets.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            ) : null}
          </section>
        ))}
        <p className="legalBack">
          <Link href={c.backHref}>{c.backCta}</Link>
        </p>
      </article>
    </div>
  );
}

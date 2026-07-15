import type { Metadata } from "next";
import Link from "next/link";

import { LinkButton } from "./components/ui";
import { ownerCopy } from "./lib/copy";
import { getCurrentUser } from "./lib/supabase/server";

const c = ownerCopy.home;
const betaInterestHref = "mailto:post@talli.no?subject=Betatilgang%20til%20Talli";

export const metadata: Metadata = {
  title: c.metaTitle,
  description: c.metaDescription,
};

export default async function Home() {
  const user = await getCurrentUser();
  const primaryHref = user ? "/dashboard" : betaInterestHref;
  const primaryLabel = user ? c.nav.toApp : c.hero.primaryCta;

  return (
    <div className="lpPage">
      <header className="lpHeader">
        <div className="lpHeaderInner">
          <div className="appBrand">
            <span className="appBrandMark" aria-hidden="true" />
            <span>{ownerCopy.brand}</span>
          </div>
          <div className="lpHeaderActions">
            {user ? (
              <LinkButton href="/dashboard" variant="primary">
                {c.nav.toApp}
              </LinkButton>
            ) : (
              <>
                <LinkButton href="/login" variant="ghost">
                  {c.nav.signIn}
                </LinkButton>
                <LinkButton href={betaInterestHref} variant="primary">
                  {c.nav.signUp}
                </LinkButton>
              </>
            )}
          </div>
        </div>
      </header>

      <main className="lpMain">
        <section className="lpHero">
          <p className="lpEyebrow">{c.hero.eyebrow}</p>
          <h1 className="lpTitle">{c.hero.title}</h1>
          <p className="lpLede">{c.hero.lede}</p>
          <div className="lpCtaRow">
            <LinkButton href={primaryHref} variant="primary" size="lg">
              {primaryLabel}
            </LinkButton>
            {!user ? (
              <LinkButton href="/login" variant="secondary" size="lg">
                {c.hero.secondaryCta}
              </LinkButton>
            ) : null}
          </div>
          <p className="lpReassure">{c.hero.reassurance}</p>
        </section>

        <section className="lpSection" aria-labelledby="lp-features">
          <h2 className="lpSectionTitle" id="lp-features">
            {c.features.title}
          </h2>
          <div className="lpFeatures">
            {c.features.items.map((item) => (
              <article key={item.title} className="lpCard">
                <h3 className="lpCardTitle">{item.title}</h3>
                <p className="lpCardBody">{item.body}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="lpSection" aria-labelledby="lp-steps">
          <h2 className="lpSectionTitle" id="lp-steps">
            {c.steps.title}
          </h2>
          <ol className="lpSteps">
            {c.steps.items.map((item, i) => (
              <li key={item.title} className="lpStep">
                <span className="lpStepNum" aria-hidden="true">
                  {i + 1}
                </span>
                <h3 className="lpStepTitle">{item.title}</h3>
                <p className="lpStepBody">{item.body}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className="lpScope">
          <h2 className="lpScopeTitle">{c.scope.title}</h2>
          <p className="lpScopeBody">{c.scope.body}</p>
          <div className="lpDisclosures">
            {c.disclosures.map((disclosure) => (
              <p key={disclosure} className="lpScopeBody">
                {disclosure}
              </p>
            ))}
          </div>
        </section>

        <section className="lpClosing">
          <h2 className="lpClosingTitle">{c.closing.title}</h2>
          <p className="lpClosingBody">{c.closing.body}</p>
          <LinkButton href={primaryHref} variant="secondary" size="lg">
            {user ? c.nav.toApp : c.closing.cta}
          </LinkButton>
        </section>
      </main>

      <footer className="lpFooter">
        <div className="lpFooterInner">
          <div className="appBrand">
            <span className="appBrandMark" aria-hidden="true" />
            <span>{ownerCopy.brand}</span>
          </div>
          <nav className="lpFooterLinks" aria-label="Footer">
            <Link href="/vilkar">{ownerCopy.auth.termsLink}</Link>
            <Link href="/personvern">{ownerCopy.auth.privacyLink}</Link>
            {user ? (
              <Link href="/dashboard">{c.nav.toApp}</Link>
            ) : (
              <Link href="/login">{c.nav.signIn}</Link>
            )}
          </nav>
          <span>{c.footer.rights}</span>
        </div>
      </footer>
    </div>
  );
}

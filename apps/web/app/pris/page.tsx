import type { Metadata } from "next";

import releaseState from "../../../../architecture/release-state.json";
import {
  PublicPage,
  publicPageStyles as styles,
} from "../../features/public-acquisition/PublicPage";
import {
  deniedAcquisitionGates,
  derivePublicAcquisitionRuntime,
  publicRecruitmentOffer,
} from "../../features/public-acquisition";
import { LinkButton } from "../components/ui";

export const metadata: Metadata = {
  title: "Pris og refusjon",
  description: "Én tydelig pris for et støttet holdingselskapsår, med trygg refusjon og ingen betaling i rekrutteringsmodus.",
  alternates: { canonical: "/pris" },
};

export default function PricingPage() {
  const runtime = derivePublicAcquisitionRuntime({
    requestedMode: process.env.TALLI_PUBLIC_ACQUISITION_MODE,
    requestedCheckout: process.env.TALLI_CHECKOUT_ENABLED,
    stableRelease: releaseState.latestStableCustomerReadyRelease,
    capabilityManifestVersion: publicRecruitmentOffer.capabilityManifestVersion,
    expectedCapabilityManifestVersion: "2026.1",
    definitiveEligibilityContinuation: false,
    gates: deniedAcquisitionGates,
  });
  return (
    <PublicPage
      eyebrow="Én pris · ett selskapsår"
      title="NOK 1,490 inkl. mva."
      lede="Når betaling åpner, dekker én årlig pris ett støttet holdingselskap, banktilkobling, hele kalenderåret og alle tre innsendingene."
    >
      <aside className={styles.notice} aria-label="Betalingsstatus">
        <p>
          Gratis rekrutteringsmodus. Betaling og produksjonsbruk er ikke åpnet, og kan ikke
          aktiveres før alle produkt-, leverandør- og lanseringsporter er grønne.
        </p>
      </aside>
      <section className={styles.section}>
        <h2>Dette inngår</h2>
        <ul>
          <li>Gjenoppbygging og bokføring av det komplette kalenderåret.</li>
          <li>Banktilkobling med CSV/CAMT.053 som robust reserve.</li>
          <li>RF-1086, skattemeldingen for selskapet og årsregnskapet.</li>
          <li>Selskapsdokumenter, kvitteringer, sporbarhet, SAF-T 1.40 og arkiv.</li>
        </ul>
      </section>
      <section className={styles.section}>
        <h2>Før et kjøp kan starte</h2>
        <ol>
          <li>Den gratis sjekken gir først et tydelig foreløpig svar.</li>
          <li>Alle manglende fakta avklares og endelig selskapsårs-støtte bekreftes.</li>
          <li>Konto, organisasjonsmyndighet, vilkår, personvern/DPA og datakildesamtykke bekreftes.</li>
          <li>Pris, fornyelsesdato, oppsigelse, refusjon og eget samtykke til gjentakende betaling vises.</li>
        </ol>
        <div className={styles.actions}>
          {runtime.checkoutEnabled ? (
            <LinkButton href="/signup?next=/checkout" variant="primary">Fortsett til betaling</LinkButton>
          ) : (
            <span className={styles.disabledAction} aria-disabled="true">Betaling er stengt</span>
          )}
          <LinkButton href="/sjekk-selskapet" variant="secondary">Sjekk selskapet gratis</LinkButton>
        </div>
      </section>
      <section className={styles.section}>
        <h2>Fornyelse, oppsigelse og refusjon</h2>
        <ul>
          <li>Automatisk årsfornyelse krever eget samtykke; prisendring varsles minst 60 dager før.</li>
          <li>Oppsigelse stopper neste fornyelse, men fjerner ikke allerede betalt tilgang.</li>
          <li>Full refusjon innen 30 dager etter første kjøp hvis ingen produksjonsinnsending er sendt.</li>
          <li>Full automatisk refusjon hvis Talli feilaktig godtar saken eller Talli/en leverandør ikke kan fullføre det lovede året.</li>
          <li>En ny, genuint ustøttet kundesituasjon gir trygg stopp, eksport og forholdsmessig refusjon etter de godkjente vilkårene.</li>
        </ul>
      </section>
    </PublicPage>
  );
}

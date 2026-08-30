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
      title="NOK 1 490 per selskapsår"
      lede="Når betaling åpner, dekker én årlig pris ett støttet holdingselskap, banktilkobling, hele kalenderåret og alle tre innsendingene."
    >
      <aside className={styles.notice} aria-label="Betalingsstatus">
        <p>
          Gratis rekrutteringsmodus. Betaling og produksjonsbruk er ikke åpnet, og kan ikke
          aktiveres før alle produkt-, leverandør- og lanseringsporter er grønne.
        </p>
      </aside>
      <p>Merverdiavgift er inkludert når den gjelder etter loven.</p>
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
          <li>Pris, refusjon og eventuelle regler for fornyelse, oppsigelse eller belastning vises tydelig og må godtas før betaling.</li>
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
        <h2>Refusjon og betaling</h2>
        <ul>
          <li>Betaling, automatisk fornyelse og belastning er ikke åpnet nå.</li>
          <li>Hvis Talli bekrefter at året støttes, men ikke kan fullføre det på grunn av feil i Tallis egen logikk eller tilkobling, får kunden hele beløpet tilbake.</li>
          <li>Feil i kundeopplysninger, manglende dokumentasjon eller fullmakt, frister kunden ikke følger, og avbrudd hos myndigheter utenfor Tallis kontroll gir ikke automatisk refusjon.</li>
        </ul>
      </section>
    </PublicPage>
  );
}

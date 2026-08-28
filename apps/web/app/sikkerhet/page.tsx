import type { Metadata } from "next";

import {
  PublicPage,
  publicPageStyles as styles,
} from "../../features/public-acquisition/PublicPage";

export const metadata: Metadata = {
  title: "Sikkerhet",
  description: "Slik avgrenser Talli tilgang, data, bank, innsending og feil før produksjonsåpning.",
  alternates: { canonical: "/sikkerhet" },
};

export default function SecurityPage() {
  return (
    <PublicPage
      eyebrow="Sikkerhet og kontroll"
      title="Stopp først når bevis mangler"
      lede="Talli er bygget for å avvise uklare eller uautoriserte handlinger. Denne siden er et sammendrag, ikke en sertifisering eller påstand om at produksjon er åpnet."
    >
      <section className={styles.section}>
        <h2>Tilgang og selskapsdata</h2>
        <p>
          Innlogging, medlemskap, selskapsgrense og sterk godkjenning kontrolleres før berørte
          handlinger. Lokale tester angriper tilgang på tvers av selskaper; produksjonsbevis må
          fortsatt være ferskt før åpning.
        </p>
      </section>
      <section className={styles.section}>
        <h2>Bank og innsending</h2>
        <p>
          Banktilgangen er bare lesetilgang, og Talli samler ikke bankpassord. Bokføring og
          innsending krever eksplisitt eierhandling, stabil identitet og avstemming av ukjente
          utfall før et forsøk kan gjentas.
        </p>
      </section>
      <section className={styles.section}>
        <h2>Dataminimering</h2>
        <p>
          Markedsmåling er adskilt fra produkt- og revisjonsdata. Ingen person-, selskaps-, bank-,
          dokument-, regnskaps- eller fritekstdata skal inngå. Ikke-nødvendig måling krever samtykke.
        </p>
      </section>
      <section className={styles.section}>
        <h2>Hendelser og ansvarlig varsling</h2>
        <p>
          Ved mistanke om en sikkerhetshendelse: ikke send sensitiv informasjon på e-post. Beskriv
          tidspunkt og berørt funksjon til post@talli.no, så avtales en trygg kanal ved behov.
        </p>
      </section>
    </PublicPage>
  );
}

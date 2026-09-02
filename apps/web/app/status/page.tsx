import type { Metadata } from "next";

import {
  PublicPage,
  publicPageStyles as styles,
} from "../../features/public-acquisition/PublicPage";

export const metadata: Metadata = {
  title: "Status",
  description: "Gjeldende offentlig tilgjengelighet for Talli i gratis rekrutterings- og valideringsmodus.",
  alternates: { canonical: "/status" },
};

export const dynamic = "force-static";

export default function StatusPage() {
  return (
    <PublicPage
      eyebrow="Gjeldende modus"
      title="Gratis rekruttering · produksjon stengt"
      lede="Gratissjekken kan brukes lokalt og i godkjent rekrutteringsmodus. Betaling, live banktilkobling og produksjonsinnsending er ikke åpnet."
    >
      <section className={styles.section}>
        <h2>Tilgjengelig</h2>
        <ul>
          <li>Gratis, foreløpig organisasjonsnummersjekk.</li>
          <li>Offentlig selskapsgrense, pris, vilkår, personvern, DPA og hjelp.</li>
          <li>Lokal og syntetisk produktvalidering uten kundedata eller leverandøraktivering.</li>
        </ul>
      </section>
      <section className={styles.section}>
        <h2>Ikke åpnet</h2>
        <ul>
          <li>Kjøp, betaling og automatisk fornyelse.</li>
          <li>Live banktilkobling eller behandling av kundens bankdata.</li>
          <li>Direkte produksjonsinnsending av RF-1086, skattemelding eller årsregnskap.</li>
        </ul>
      </section>
      <section className={styles.section}>
        <h2>Driftsmeldinger</h2>
        <p>
          Det finnes ingen offentlig produksjonstjeneste å rapportere oppetid for ennå. En hendelse
          eller endring i rekrutteringsflaten kan meldes til post@talli.no. Denne siden lover ikke
          tilgjengelighet for funksjoner som fortsatt er stengt.
        </p>
      </section>
    </PublicPage>
  );
}

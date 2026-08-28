import type { Metadata } from "next";
import Link from "next/link";

import {
  PublicPage,
  publicPageStyles as styles,
} from "../../features/public-acquisition/PublicPage";

export const metadata: Metadata = {
  title: "Hjelp",
  description: "Kort hjelp om gratissjekk, selskapsgrense, pris, bank, innsending, refusjon og trygg utgang fra Talli.",
  alternates: { canonical: "/hjelp" },
};

export default function HelpPage() {
  return (
    <PublicPage
      eyebrow="Hjelp uten regnskapsspråk"
      title="Finn neste trygge steg"
      lede="Talli forklarer hvordan produktet virker. Support tar ikke regnskapsavgjørelser for selskapet og kan ikke overstyre en ustøttet eller uklar sak."
    >
      <section className={styles.section}>
        <h2>Før konto og betaling</h2>
        <p>
          Start med <Link href="/sjekk-selskapet">gratissjekken</Link>. Offentlige fakta gir et
          foreløpig svar; viktige mangler må avklares før en endelig vurdering. Se også
          <Link href="/passer-talli"> selskapsgrensen</Link> og <Link href="/pris"> pris/refusjon</Link>.
        </p>
      </section>
      <section className={styles.section}>
        <h2>Bank, bokføring og innsending</h2>
        <p>
          Ved full åpning hentes bankbevegelser via lesetilgang, med bankfil som reserve.
          Manglende perioder må avstemmes. Eieren kontrollerer og godkjenner alltid før bokføring
          eller innsending; uklare fakta stopper berørt steg.
        </p>
      </section>
      <section className={styles.section}>
        <h2>Personvern, sikkerhet og status</h2>
        <p>
          Les <Link href="/personvern">personvern</Link>, <Link href="/databehandleravtale">DPA</Link>,
          <Link href="/sikkerhet"> sikkerhetssammendraget</Link> og <Link href="/status">tjenestestatus</Link>.
          Markedsmåling skal aldri inneholde organisasjonsnummer, navn, e-post, bank-, dokument- eller regnskapsdata.
        </p>
      </section>
      <section className={styles.section}>
        <h2>Kontakt</h2>
        <p>
          Skriv til post@talli.no. Henvendelser håndteres manuelt. Ved en ustøttet sak får du
          forklaring, lesing/eksport og trygg utgang; support kan ikke gjøre saken støttet ved å ta
          regnskapsmessige skjønn på dine vegne.
        </p>
      </section>
    </PublicPage>
  );
}

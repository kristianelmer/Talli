import type { Metadata } from "next";
import Link from "next/link";

import {
  PublicPage,
  publicPageStyles as styles,
} from "../../features/public-acquisition/PublicPage";
import { LinkButton } from "../components/ui";

export const metadata: Metadata = {
  title: "Hvem passer Talli for?",
  description: "Se den tydelige selskapsgrensen før du sjekker holdingselskapet gratis.",
  alternates: { canonical: "/passer-talli" },
};

export default function ScopePage() {
  return (
    <PublicPage
      eyebrow="Selskapsgrense · versjon 2026.1"
      title="For vanlige, eierstyrte holding-AS"
      lede="Gratissjekken skiller mellom passer, må avklares og passer ikke. Ukjente viktige fakta blir aldri behandlet som null."
    >
      <section className={styles.section}>
        <h2>Dette kan passe</h2>
        <ul>
          <li>Norsk AS med kalenderår, én ordinær aksjeklasse og regnskap i NOK.</li>
          <li>Én eller flere norske eiere og datterselskap uten krav om konsernregnskap.</li>
          <li>Vanlige norske aksjer/fond, utbytte, lån, renter, skatt og administrasjonskostnader.</li>
          <li>Oppstart etter 1. januar når hele året kan gjenoppbygges og avstemmes fra årets start.</li>
        </ul>
      </section>
      <section className={styles.section}>
        <h2>Dette passer ikke</h2>
        <ul>
          <li>Revisjon, konsernregnskap, flere aksjeklasser, utenlandske eiere eller valuta.</li>
          <li>Lønn, MVA, kundefakturering, varelager, eiendom eller løpende salg av varer/tjenester.</li>
          <li>Krypto, derivater, aktiv handel, utenlandsk skatt eller uklar investeringstype.</li>
          <li>Fusjon, fisjon, omdanning, komplisert omorganisering eller uvanlige eier-/lånevilkår.</li>
        </ul>
      </section>
      <section className={styles.section}>
        <h2>Når noe må avklares</h2>
        <p>
          Et foreløpig svar er ikke en kjøpsgodkjenning. Manglende opplysninger om blant annet
          revisjon, konsern, eierskap, aktivitet eller hele årets dokumentasjon må avklares før
          Talli kan gi et endelig svar. Et senere funn stopper berørt arbeid og bevarer lesing og eksport.
        </p>
        <div className={styles.actions}>
          <LinkButton href="/sjekk-selskapet" variant="primary">Sjekk selskapet gratis</LinkButton>
          <Link href="/hjelp">Slik fungerer sjekken</Link>
        </div>
      </section>
    </PublicPage>
  );
}

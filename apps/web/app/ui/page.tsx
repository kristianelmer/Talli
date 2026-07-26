import type { Metadata } from "next";

import {
  Banner,
  Button,
  Card,
  EmptyState,
  FormField,
  Inbox,
  LinkButton,
  LoadingState,
  Panel,
  Plus,
  Select,
  Skeleton,
  SkeletonText,
  Spinner,
  StatCard,
  StatusBadge,
  Stepper,
  WizardShell,
  type DomainStatus,
} from "../components/ui";
import { ClientDemos } from "./ClientDemos";

export const metadata: Metadata = {
  title: "Komponenter · Talli",
  robots: { index: false, follow: false },
};

const DOMAIN_STATUSES: DomainStatus[] = [
  "utkast",
  "trenger_gjennomgang",
  "blokkert",
  "klar",
  "levert",
  "til_regnskapsforer",
];

const SWATCHES: Array<{ name: string; token: string }> = [
  { name: "Brand", token: "--color-brand" },
  { name: "Brand strong", token: "--color-brand-strong" },
  { name: "Brand soft", token: "--color-brand-soft" },
  { name: "Success", token: "--color-success" },
  { name: "Warning", token: "--color-warning" },
  { name: "Danger", token: "--color-danger" },
  { name: "Info", token: "--color-info" },
  { name: "Gold", token: "--color-gold" },
  { name: "Canvas", token: "--color-bg" },
  { name: "Surface", token: "--color-surface" },
  { name: "Sunken", token: "--color-surface-sunken" },
  { name: "Border", token: "--color-border" },
  { name: "Ink", token: "--color-text" },
  { name: "Muted ink", token: "--color-text-muted" },
];

export default function UiPreviewPage() {
  return (
    <div className="uiPage">
      <div className="uiContainer">
        <header className="uiHead">
          <h1 className="pageTitle">Komponentbibliotek</h1>
          <p className="pageLede">
            Calm Nordic – levende referanse for #92. Alle komponenter bruker
            design-tokens fra <code>app/tokens.css</code>. Ikke en
            produksjonsside.
          </p>
        </header>

        <section className="uiSection">
          <h2 className="uiSectionTitle">Knapper</h2>
          <div className="uiRow">
            <Button variant="primary">Primær</Button>
            <Button variant="secondary">Sekundær</Button>
            <Button variant="ghost">Ghost</Button>
            <Button variant="destructive">Slett</Button>
            <LinkButton href="#" variant="secondary">
              Lenkeknapp
            </LinkButton>
          </div>
          <div className="uiRow">
            <Button size="sm">Liten</Button>
            <Button>Standard</Button>
            <Button size="lg">Stor</Button>
            <Button disabled>Deaktivert</Button>
            <Button variant="primary">
              <Plus size={16} aria-hidden="true" />
              Med ikon
            </Button>
          </div>
        </section>

        <section className="uiSection">
          <h2 className="uiSectionTitle">Statusmerker (domene)</h2>
          <div className="uiRow">
            {DOMAIN_STATUSES.map((status) => (
              <StatusBadge key={status} status={status} />
            ))}
          </div>
        </section>

        <section className="uiSection">
          <h2 className="uiSectionTitle">Varselbanner</h2>
          <div className="uiStack">
            <Banner variant="info" title="Forhåndsvisning">
              Dette er en simulert innsending – ingenting sendes til
              myndighetene ennå.
            </Banner>
            <Banner variant="success" title="Klar til innsending">
              Alle krav er oppfylt for inntektsåret.
            </Banner>
            <Banner variant="warning" title="Trenger gjennomgang">
              Vi fant noe som bør sjekkes før du fortsetter.
            </Banner>
            <Banner variant="danger" title="Blokkert">
              Aksjonærregisteret mangler. Legg det til for å fortsette.
            </Banner>
          </div>
        </section>

        <section className="uiSection">
          <h2 className="uiSectionTitle">Skjemafelt</h2>
          <div className="uiStack">
            <FormField
              label="E-post"
              name="demo-email"
              type="email"
              required
              helper="Vi bruker denne til pålogging."
            />
            <FormField
              label="Notat"
              name="demo-note"
              optionalHint
              placeholder="Valgfritt notat …"
            />
            <FormField
              label="Passord"
              name="demo-password"
              type="password"
              required
              error="Passordet må være minst 6 tegn."
            />
            <Select
              label="Selskapstype"
              name="demo-type"
              placeholder="Velg type"
              options={[
                { value: "as", label: "Aksjeselskap (AS)" },
                { value: "holding", label: "Holdingselskap" },
              ]}
              helper="Talli er laget for enkle holding-AS."
            />
          </div>
        </section>

        <section className="uiSection">
          <h2 className="uiSectionTitle">Interaktivt (klient)</h2>
          <p className="uiNote">
            Toast-varsler, inline-validering og pending-tilstand på innsending.
          </p>
          <ClientDemos />
        </section>

        <section className="uiSection">
          <h2 className="uiSectionTitle">Stegindikator</h2>
          <Stepper
            steps={["Selskap", "Eiere", "Åpningsbalanse", "Gjennomgang"]}
            current={2}
          />
        </section>

        <section className="uiSection">
          <h2 className="uiSectionTitle">Veiviser-skall</h2>
          <WizardShell
            title="Hvem eier selskapet?"
            intro="Legg til aksjonærene. Dette brukes til aksjonærregisteret (RF-1086)."
            steps={["Selskap", "Eiere", "Åpningsbalanse", "Gjennomgang"]}
            current={1}
            back={<Button variant="ghost">Tilbake</Button>}
            next={<Button variant="primary">Lagre og fortsett</Button>}
          >
            <p className="uiNote">Ett spørsmål per steg holder flyten rolig.</p>
          </WizardShell>
        </section>

        <section className="uiSection">
          <h2 className="uiSectionTitle">Kort &amp; paneler</h2>
          <div className="cardGrid">
            <StatCard label="Inntektsår" value="2025" note="Gjeldende periode" />
            <StatCard label="Frister" value="3" note="neste 90 dager" />
            <StatCard label="Status" value="Klar" />
          </div>
          <Panel
            title="Årsoppgjør 2025"
            actions={<StatusBadge status="klar" />}
            footer={<Button variant="primary">Start innsending</Button>}
          >
            <Card>
              <span className="cardLabel">Neste steg</span>
              <p className="cardNote">
                Forhåndsvis filingpakken før du bekrefter.
              </p>
            </Card>
          </Panel>
        </section>

        <section className="uiSection">
          <h2 className="uiSectionTitle">Tomtilstand &amp; lasting</h2>
          <EmptyState
            icon={<Inbox size={22} aria-hidden="true" />}
            title="Ingen transaksjoner ennå"
            action={
              <Button variant="primary">
                <Plus size={16} aria-hidden="true" />
                Legg til første transaksjon
              </Button>
            }
          >
            Når du registrerer en transaksjon dukker den opp her.
          </EmptyState>
          <div className="uiRow">
            <Spinner size="lg" label="Laster" />
            <LoadingState />
          </div>
          <Card>
            <Skeleton width="40%" height="1.2em" />
            <SkeletonText lines={3} />
          </Card>
        </section>

        <section className="uiSection">
          <h2 className="uiSectionTitle">Fargetokens</h2>
          <div className="uiSwatchGrid">
            {SWATCHES.map((swatch) => (
              <div key={swatch.token} className="uiSwatch">
                <div
                  className="uiSwatchFill"
                  style={{ background: `var(${swatch.token})` }}
                />
                <div className="uiSwatchMeta">
                  <strong>{swatch.name}</strong>
                  <code>{swatch.token}</code>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

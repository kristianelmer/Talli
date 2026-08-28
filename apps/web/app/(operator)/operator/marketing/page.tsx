import type { MarketingFunnelReportResponse } from "@talli/talli-api-client";

import { marketingMeasurementTransportFromEnvironment } from "../../../../features/public-acquisition/server.ts";
import { createSupabaseServerClient } from "../../../lib/supabase/server";

export const dynamic = "force-dynamic";

const stageLabels: Record<string, string> = {
  home_view: "Forsidevisninger",
  eligibility_start: "Startet selskapsjekk",
  provisional_supported: "Foreløpig støttet",
  provisional_clarify: "Trenger avklaring",
  provisional_blocked: "Foreløpig stoppet",
  definitive_eligible: "Endelig kvalifisert",
  definitive_blocked: "Endelig stoppet",
  signup_start: "Startet registrering",
  terms_accept: "Godtatt vilkår",
  checkout_start: "Startet betaling",
  purchase_complete: "Kjøp fullført",
  purchase_failed: "Kjøp feilet",
  company_year_started: "Selskapsår startet",
  bank_connected: "Bank tilkoblet",
  year_ready: "År klart",
  filing_accepted: "Innsending akseptert",
  company_year_complete: "Selskapsår fullført",
  support_contact: "Kontaktet support",
  unsupported_exit: "Avsluttet utenfor omfang",
  refund_started: "Refusjon startet",
  refund_completed: "Refusjon fullført",
};

const surfaceLabels: Record<string, string> = {
  homepage: "Forside",
  eligibility: "Selskapsjekk",
  signup: "Registrering",
  checkout: "Betaling",
  workspace: "Arbeidsflate",
  banking: "Bank",
  year_close: "Årsavslutning",
  filing: "Innsending",
  support: "Support",
  refund: "Refusjon",
};

function percent(value: number | null | undefined): string {
  return value === null || value === undefined
    ? "Ikke tilgjengelig"
    : new Intl.NumberFormat("nb-NO", {
        style: "percent",
        maximumFractionDigits: 1,
      }).format(value);
}

function duration(value: number | null | undefined): string {
  if (value === null || value === undefined) return "Ikke tilgjengelig";
  if (value < 3_600) return `${Math.round(value / 60)} min`;
  if (value < 86_400) return `${Math.round(value / 3_600)} t`;
  return `${Math.round(value / 86_400)} d`;
}

async function loadReport(): Promise<MarketingFunnelReportResponse | null> {
  const supabase = await createSupabaseServerClient();
  const { data } = await supabase.auth.getSession();
  const accessToken = data.session?.access_token;
  if (!accessToken) return null;
  try {
    return await marketingMeasurementTransportFromEnvironment().report(accessToken, 30);
  } catch {
    return null;
  }
}

export default async function OperatorMarketingPage() {
  const report = await loadReport();

  return (
    <>
      <div className="pageHead">
        <h1 className="pageTitle">Anonym traktmåling</h1>
        <p className="pageLede">
          Aggregerte hendelser fra frivillig samtykke de siste 30 dagene. Ingen
          rå økter, personer, selskaper eller fritekst vises her.
        </p>
      </div>

      {!report ? (
        <section className="dataPanel blocked" aria-labelledby="measurement-unavailable">
          <h2 id="measurement-unavailable">Måling er ikke tilgjengelig</h2>
          <p>
            Backend, database eller operatørkontroll er ikke konfigurert. Visningen
            feiler lukket og viser ingen antatte tall.
          </p>
        </section>
      ) : (
        <>
          <section className="band" aria-labelledby="funnel-counts">
            <div className="sectionHeader">
              <p className="eyebrow">Volum</p>
              <h2 id="funnel-counts">Faste traktsteg</h2>
            </div>
            <div className="readinessGrid">
              {Object.entries(report.counts).map(([event, count]) => (
                <article className="readinessItem" key={event}>
                  <span>{stageLabels[event] ?? event}</span>
                  <strong>{count.toLocaleString("nb-NO")}</strong>
                </article>
              ))}
            </div>
          </section>

          <section className="band" aria-labelledby="funnel-rates">
            <div className="sectionHeader">
              <p className="eyebrow">Konvertering og tid</p>
              <h2 id="funnel-rates">Resultater uten kampanjekostnad</h2>
            </div>
            <div className="readinessGrid">
              <article className="readinessItem">
                <span>Forside til kjøp</span>
                <strong>{percent(report.rates.home_to_purchase)}</strong>
                <p>Median: {duration(report.medianSeconds.home_to_purchase)}</p>
              </article>
              <article className="readinessItem">
                <span>Selskapsjekk til kjøp</span>
                <strong>{percent(report.rates.eligibility_to_purchase)}</strong>
              </article>
              <article className="readinessItem">
                <span>Stoppet utenfor omfang</span>
                <strong>{percent(report.rates.unsupported)}</strong>
              </article>
              <article className="readinessItem">
                <span>Selskapsår fullført</span>
                <strong>{percent(report.rates.company_year_completion)}</strong>
                <p>Median: {duration(report.medianSeconds.company_year_completion)}</p>
                <p>Krever en separat aggregert livsløpsmåling uten stabil markeds-ID.</p>
              </article>
              <article className="readinessItem">
                <span>Refusjonsrate</span>
                <strong>{percent(report.rates.refund)}</strong>
                <p>Krever en separat aggregert kjøpskohort uten stabil markeds-ID.</p>
              </article>
              <article className="readinessItem">
                <span>Anskaffelseskostnad</span>
                <strong>Ikke tilgjengelig</strong>
                <p>Ingen godkjent annonsekostnad er koblet til målingen.</p>
              </article>
            </div>
          </section>

          <section className="band" aria-labelledby="funnel-signals">
            <div className="sectionHeader">
              <p className="eyebrow">Hjelp og stopp</p>
              <h2 id="funnel-signals">Gjentatte, aggregerte signaler</h2>
            </div>
            {Object.keys(report.supportBySurface).length ? (
              <div className="readinessGrid">
                {Object.entries(report.supportBySurface).map(([surface, count]) => (
                  <article className="readinessItem" key={surface}>
                    <span>Hjelpekontakter · {surfaceLabels[surface] ?? surface}</span>
                    <strong>{count.toLocaleString("nb-NO")}</strong>
                  </article>
                ))}
              </div>
            ) : (
              <p>Ingen hjelpekontakter i perioden.</p>
            )}
            {report.repeatedSignals.length ? (
              <div className="readinessGrid">
                {report.repeatedSignals.map((signal) => (
                  <article
                    className="readinessItem"
                    key={`${signal.event}:${signal.surface}:${signal.reason}`}
                  >
                    <span>{stageLabels[signal.event] ?? signal.event}</span>
                    <strong>{signal.count.toLocaleString("nb-NO")}</strong>
                    <p>{signal.surface} · {signal.reason}</p>
                  </article>
                ))}
              </div>
            ) : (
              <p>Ingen gjentatte årsakssignaler i perioden.</p>
            )}
          </section>
        </>
      )}
    </>
  );
}

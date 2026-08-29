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
  unsupported_exit: "Avsluttet utenfor omfang",
};

const surfaceLabels: Record<string, string> = {
  homepage: "Forside",
  eligibility: "Selskapsjekk",
  signup: "Registrering",
};

function percent(value: number | null | undefined): string {
  return value === null || value === undefined
    ? "Ikke tilgjengelig"
    : new Intl.NumberFormat("nb-NO", {
        style: "percent",
        maximumFractionDigits: 1,
      }).format(value);
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
              <p className="eyebrow">Offentlig sjekk</p>
              <h2 id="funnel-rates">Kort økt uten livsløpskobling</h2>
            </div>
            <div className="readinessGrid">
              <article className="readinessItem">
                <span>Stoppet utenfor omfang</span>
                <strong>{percent(report.rates.unsupported)}</strong>
              </article>
              <article className="readinessItem">
                <span>Ingen konto- eller kjøpskohort</span>
                <strong>Ikke samlet inn</strong>
                <p>Kjøp, selskapsår, support, refusjon og regnskapsutfall kobles ikke til markedsøkten.</p>
              </article>
            </div>
          </section>

          <section className="band" aria-labelledby="funnel-signals">
            <div className="sectionHeader">
              <p className="eyebrow">Hjelp og stopp</p>
              <h2 id="funnel-signals">Gjentatte, aggregerte signaler</h2>
            </div>
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

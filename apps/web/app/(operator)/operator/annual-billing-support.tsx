import type { AnnualSupportPageWire } from "../../../features/billing";

const money = (minor: number) => new Intl.NumberFormat("nb-NO", {
  style: "currency", currency: "NOK",
}).format(minor / 100);

const date = (value: string) => new Intl.DateTimeFormat("nb-NO", {
  timeZone: "Europe/Oslo", day: "numeric", month: "long", year: "numeric",
}).format(new Date(value));

const operationLabels = {
  created: "registrert", pending: "venter", unknown: "ukjent utfall",
  confirmed: "bekreftet", failed: "mislyktes",
};
const purchaseLabels = { pending: "Venter på betaling", paid: "Betalt", failed: "Betaling mislyktes", refunded: "Refundert" };

export function AnnualBillingSupport({ page, error, supportCaseId }: {
  page: AnnualSupportPageWire | null;
  error: "sign-in" | "step-up" | "unavailable" | null;
  supportCaseId: string;
}) {
  if (!page && !error) return null;
  const firstPage = `/operator?${new URLSearchParams({ supportCase: supportCaseId })}#annual-billing`;
  return <section id="annual-billing" aria-labelledby="annual-billing-heading" className="formPanel">
    <h2 id="annual-billing-heading">Årskjøp og refusjoner</h2>
    {error ? <div role="alert">
      <p>{error === "step-up"
        ? "Bekreft MFA på nytt for å lese årskjøp i saken."
        : error === "sign-in" ? "Logg inn på nytt for å lese årskjøp i saken."
        : "Årskjøp kunne ikke leses. Kontroller at saken er åpnet og at du har gyldig administratortilgang til fakturering."}</p>
      <a href={firstPage}>Prøv første side på nytt</a>
    </div> : page ? <>
      <p>Registrerte kjøp for selskap {page.companyId}, på tvers av inntektsår. Beløpene viser registrerte betalinger og refusjoner. Bruk kjøpsreferansen ved oppfølging i saken.</p>
      {page.purchases.length === 0 ? <p>Ingen årskjøp registrert på denne siden.</p> : null}
      <div className="readinessGrid">
        {page.purchases.map((purchase) => <article className="readinessItem" key={purchase.purchaseId}>
          <h3>Inntektsår {purchase.incomeYear} · {purchaseLabels[purchase.status]}</h3>
          <p>Kjøpsreferanse: <code style={{ overflowWrap: "anywhere" }}>{purchase.purchaseId}</code></p>
          <p>Avtalt pris: {money(purchase.grossMinor)}. Betalt: {money(purchase.capturedMinor)}. Refundert: {money(purchase.refundedMinor)}.</p>
          {purchase.refundCaseCount ? <>
            <p>Registrert refusjon totalt: {money(purchase.recordedRefundMinor)}. Gjenstår: <strong>{money(purchase.remainingRefundMinor)}</strong>.</p>
            {purchase.refundInitiateBy ? <p>Frist for å starte gjenstående refusjon: <strong>{date(purchase.refundInitiateBy)}</strong>.</p> : null}
            <p>{purchase.refundRequestCount} registrerte refusjonsforespørsler{purchase.latestRefundRequestedAt ? `, sist ${date(purchase.latestRefundRequestedAt)}` : ""}.</p>
          </> : <p>Ingen refusjon registrert.</p>}
          <p>Refusjonsforsøk: {Object.entries(purchase.refundOperations)
            .filter(([, count]) => count > 0)
            .map(([status, count]) => `${count} ${operationLabels[status as keyof typeof operationLabels]}`)
            .join(", ") || "Ingen registrert"}.</p>
          <p>Fornyelse i Talli: {purchase.renewalCanceledAt ? `stoppet ${date(purchase.renewalCanceledAt)}` : purchase.recurringConsent ? "ikke stoppet" : "ikke valgt"}.</p>
          <p>Stopp hos betalingsleverandør: <strong>{purchase.cleanupStatus ? operationLabels[purchase.cleanupStatus] : "Ingen operasjon registrert"}</strong>.</p>
          <p>Avtalte datoer: tilgang til {date(purchase.paidThrough)}, eksport til {date(purchase.exportThrough)}.</p>
          <small>Betalingsstatus oppdatert {date(purchase.updatedAt)}.</small>
        </article>)}
      </div>
      <nav aria-label="Sider med årskjøp">
        <a href={firstPage}>Nyeste kjøp</a>
        {page.nextPurchaseId ? <> · <a href={`/operator?${new URLSearchParams({ supportCase: page.supportCaseId, annualBefore: page.nextPurchaseId })}#annual-billing`}>Eldre kjøp</a></> : null}
      </nav>
    </> : null}
  </section>;
}

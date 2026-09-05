import type { AnnualBillingSnapshotWire, AnnualPurchaseSummaryWire } from "../../../features/billing";
import { Banner, Button, EmptyState, LinkButton, StatusBadge } from "../ui";

const money = new Intl.NumberFormat("nb-NO", { style: "currency", currency: "NOK" });
const date = new Intl.DateTimeFormat("nb-NO", { day: "numeric", month: "long", year: "numeric", timeZone: "Europe/Oslo" });
const calendarDate = (value: string) => date.format(new Date(`${value}T12:00:00Z`));
const statusLabels = { pending: "Betalingen er ikke bekreftet", paid: "Betalt", failed: "Betalingen ble ikke fullført", refunded: "Refundert" };

type Props = {
  companyName: string;
  snapshot: AnnualBillingSnapshotWire;
  beforePurchaseId?: string;
  operationIds: Record<string, string>;
  unconfirmedPurchaseId?: string;
  cancelAction: (formData: FormData) => Promise<void>;
};

function Purchase({ purchase, operationId, beforePurchaseId, unconfirmed, cancelAction }: {
  purchase: AnnualPurchaseSummaryWire;
  operationId: string;
  beforePurchaseId?: string;
  unconfirmed: boolean;
  cancelAction: Props["cancelAction"];
}) {
  return <article className="billingStatusCard" aria-label={`Kjøp ${date.format(new Date(purchase.acceptedAt))}`}>
    <div className="billingStatusHead">
      <h3 className="billingStatusTitle">{date.format(new Date(purchase.acceptedAt))}</h3>
      <StatusBadge variant={purchase.status === "paid" ? "success" : purchase.status === "failed" ? "warning" : "info"}
        label={statusLabels[purchase.status]} />
    </div>
    <p>{money.format(purchase.grossMinor / 100)} inkl. mva. for selskapsåret {purchase.incomeYear}</p>
    <p className="fieldHelp">{money.format(purchase.netMinor / 100)} ekskl. mva. + {money.format(purchase.vatMinor / 100)} mva. ({purchase.vatBasisPoints / 100} %).</p>
    {purchase.status === "paid" ? <p>Betalt tilgang til og med {calendarDate(purchase.paidThrough)}.
      Lese- og eksporttilgang til og med {calendarDate(purchase.exportThrough)}.</p> : null}
    {purchase.refundedMinor > 0 ? <p>Refundert beløp: {money.format(purchase.refundedMinor / 100)}.</p> : null}
    {purchase.renewalCanceledAt ? <Banner variant="success">
      Fornyelsen ble stoppet {date.format(new Date(purchase.renewalCanceledAt))}.
      Oppsigelsen endrer ikke tilgangen du allerede har betalt for.
    </Banner> : !purchase.recurringConsent ? <p>Automatisk fornyelse er ikke valgt.</p> : <>
      <p>Planlagt fornyelse {calendarDate(purchase.renewalDate)}. Neste selskapsår må være godkjent før betaling.</p>
      {unconfirmed ? <Banner variant="warning">
        Vi fikk ikke bekreftet oppsigelsen. Prøv igjen med knappen nedenfor. Samme forespørsel blir brukt på nytt.
      </Banner> : null}
      <form action={cancelAction}>
        <input type="hidden" name="companyId" value={purchase.companyId} />
        <input type="hidden" name="purchaseId" value={purchase.purchaseId} />
        <input type="hidden" name="operationId" value={operationId} />
        {beforePurchaseId ? <input type="hidden" name="beforePurchaseId" value={beforePurchaseId} /> : null}
        <Button type="submit" variant="secondary">Stopp fornyelse</Button>
        <p className="fieldHelp">Fornyelsen stoppes med en gang. Oppsigelsen endrer ikke tilgangen du allerede har betalt for.</p>
      </form>
    </>}
    <details><summary>Vilkårene for dette kjøpet</summary>
      <p style={{ whiteSpace: "pre-wrap" }}>{purchase.termsText}</p>
    </details>
  </article>;
}

export function AnnualBillingView({ companyName, snapshot, beforePurchaseId, operationIds, unconfirmedPurchaseId, cancelAction }: Props) {
  const { offer, purchases, nextPurchaseId } = snapshot;
  const base = `/billing?companyId=${encodeURIComponent(offer.companyId)}`;
  return <>
    <section className="billingSection" aria-labelledby="annual-offer-title">
      <h2 id="annual-offer-title" className="sectionTitle">{companyName} · selskapsåret {offer.incomeYear}</h2>
      <div className="planCard">
        <p className="planName">Ett abonnement for hele selskapsåret</p>
        <p className="planPrice">{money.format(offer.grossMinor / 100)} inkl. mva.</p>
        <p className="fieldHelp">{money.format(offer.netMinor / 100)} ekskl. mva. + {money.format(offer.vatMinor / 100)} mva. ({offer.vatBasisPoints / 100} %).</p>
        <p>Regnskap, selskapsdokumenter, alle tre innsendinger, kvitteringer og arkiv for et støttet selskapsår.</p>
        <p>Betaling er ikke åpnet.</p>
        <details><summary>Se hele årstilbudet og vilkårene</summary>
          <p style={{ whiteSpace: "pre-wrap" }}>{offer.termsText}</p>
        </details>
      </div>
    </section>
    <section className="billingSection" aria-labelledby="annual-history-title">
      <h2 id="annual-history-title" className="sectionTitle">Kjøpshistorikk og fornyelse</h2>
      {purchases.length === 0 ? <EmptyState title="Ingen kjøp for dette selskapsåret">
        Det er ikke registrert et årskjøp for {offer.incomeYear}.
      </EmptyState> : <div className="annualPurchaseList">
        {purchases.map((purchase) => <Purchase key={purchase.purchaseId} purchase={purchase}
          operationId={operationIds[purchase.purchaseId]} beforePurchaseId={beforePurchaseId}
          unconfirmed={purchase.purchaseId === unconfirmedPurchaseId} cancelAction={cancelAction} />)}
      </div>}
      <nav className="actionRow" aria-label="Kjøpshistorikk">
        {beforePurchaseId ? <LinkButton href={base}>Nyeste kjøp</LinkButton> : null}
        {nextPurchaseId ? <LinkButton href={`${base}&beforePurchaseId=${encodeURIComponent(nextPurchaseId)}`}>
          Eldre kjøp
        </LinkButton> : null}
      </nav>
      <LinkButton variant="secondary" href={`/archive/${offer.companyId}/${offer.incomeYear}/download`}>Last ned årsarkivet</LinkButton>
    </section>
  </>;
}

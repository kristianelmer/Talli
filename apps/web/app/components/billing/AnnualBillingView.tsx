import type { AnnualBillingSnapshotWire, AnnualBillingRefundSnapshotWire, AnnualPurchaseSummaryWire, AnnualPurchaseRefundSummaryWire, AnnualBillingOfferWire, AnnualPurchaseHistoryWire } from "../../../features/billing";
import { Banner, Button, EmptyState, LinkButton, StatusBadge } from "../ui";
import { AnnualAgreementCleanupControl } from "./AnnualAgreementCleanupControl";
import type { AnnualAgreementCleanupAction } from "../../lib/annual-billing-cleanup";

const money = new Intl.NumberFormat("nb-NO", { style: "currency", currency: "NOK" });
const date = new Intl.DateTimeFormat("nb-NO", { day: "numeric", month: "long", year: "numeric", timeZone: "Europe/Oslo" });
const calendarDate = (value: string) => date.format(new Date(`${value}T12:00:00Z`));
const statusLabels = { pending: "Betalingen er ikke bekreftet", paid: "Betalt", failed: "Betalingen ble ikke fullført", refunded: "Refundert" };

type Props = {
  companyId: string;
  companyName: string;
  snapshot: AnnualBillingSnapshotWire | AnnualBillingRefundSnapshotWire | AnnualPurchaseHistoryWire;
  offer?: AnnualBillingOfferWire;
  offerUnavailable?: boolean;
  limitedHistory?: boolean;
  beforePurchaseId?: string;
  operationIds: Record<string, string>;
  unconfirmedPurchaseId?: string;
  cancelAction: (formData: FormData) => Promise<void>;
  cleanupAction: AnnualAgreementCleanupAction;
};

function RefundEvidence({ purchase }: { purchase: AnnualPurchaseSummaryWire | AnnualPurchaseRefundSummaryWire }) {
  if (!("refundOperations" in purchase)) return <p>Refusjonsdetaljer er ikke tilgjengelige nå.
    {purchase.refundedMinor > 0 ? <> Registrert refundert beløp: {money.format(purchase.refundedMinor / 100)}.</> : null}
  </p>;
  const operations = purchase.refundOperations;
  const hasEvidence = purchase.recordedRefundMinor > 0 || purchase.refundedMinor > 0 || purchase.refundRequestCount > 0
    || Object.values(operations).some((count) => count > 0);
  if (!hasEvidence) return null;

  return <section aria-label="Registrert refusjon">
    <h4>Refusjon</h4>
    {purchase.recordedRefundMinor > 0 ? <>
      <p>Registrert refusjonsbeløp: {money.format(purchase.recordedRefundMinor / 100)}.</p>
      <p>Gjenstående registrert beløp: {money.format(purchase.remainingRefundMinor / 100)}.</p>
    </> : null}
    <p>Registrert refundert beløp: {money.format(purchase.refundedMinor / 100)}.</p>
    {purchase.refundInitiateBy ? <p>Registrert frist for å starte refusjonen: {calendarDate(purchase.refundInitiateBy)}.</p> : null}
    {purchase.latestRefundRequestedAt ? <p>Refusjonsforespørsel registrert {date.format(new Date(purchase.latestRefundRequestedAt))}.
      En registrert forespørsel er ikke en bekreftelse på utbetaling.</p> : null}
    {operations.created > 0 ? <p>Et refusjonsforsøk er klargjort, men ikke bekreftet.</p> : null}
    {operations.pending > 0 ? <p>En refusjon venter på bekreftelse fra betalingsleverandøren.</p> : null}
    {operations.unknown > 0 ? <Banner variant="warning">Utfallet av et refusjonsforsøk er ikke kjent.</Banner> : null}
    {operations.failed > 0 ? <Banner variant="warning">Et refusjonsforsøk ble ikke fullført.</Banner> : null}
    {Object.values(operations).every((count) => count === 0) ? <p>Ingen refusjonsforsøk er registrert.</p> : null}
    <p className="fieldHelp">Fristen gjelder når Talli skal starte refusjonen. Tiden til pengene er på konto avhenger av betalingsleverandøren og banken.</p>
  </section>;
}

function Purchase({ purchase, operationId, beforePurchaseId, unconfirmed, cancelAction, cleanupAction }: {
  purchase: AnnualPurchaseSummaryWire | AnnualPurchaseRefundSummaryWire;
  operationId: string;
  beforePurchaseId?: string;
  unconfirmed: boolean;
  cancelAction: Props["cancelAction"];
  cleanupAction: Props["cleanupAction"];
}) {
  return <article id={`annual-purchase-${purchase.purchaseId}`} className="billingStatusCard" aria-label={`Kjøp ${date.format(new Date(purchase.acceptedAt))}`}>
    <div className="billingStatusHead">
      <h3 className="billingStatusTitle">{date.format(new Date(purchase.acceptedAt))}</h3>
      <StatusBadge variant={purchase.status === "paid" ? "success" : purchase.status === "failed" ? "warning" : "info"}
        label={statusLabels[purchase.status]} />
    </div>
    <p>{money.format(purchase.grossMinor / 100)} inkl. mva. for selskapsåret {purchase.incomeYear}</p>
    <p className="fieldHelp">{money.format(purchase.netMinor / 100)} ekskl. mva. + {money.format(purchase.vatMinor / 100)} mva. ({purchase.vatBasisPoints / 100} %).</p>
    {purchase.status === "paid" ? <p>Betalt tilgang til og med {calendarDate(purchase.paidThrough)}.
      Lese- og eksporttilgang til og med {calendarDate(purchase.exportThrough)}.</p> : null}
    <RefundEvidence purchase={purchase} />
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
    {purchase.renewalCanceledAt ? <AnnualAgreementCleanupControl key={`${purchase.companyId}:${purchase.purchaseId}`}
      companyId={purchase.companyId} purchaseId={purchase.purchaseId} beforePurchaseId={beforePurchaseId}
      cleanupAction={cleanupAction} /> : null}
    <details><summary>Vilkårene for dette kjøpet</summary>
      <p style={{ whiteSpace: "pre-wrap" }}>{purchase.termsText}</p>
    </details>
    <LinkButton variant="secondary" href={`/archive/${purchase.companyId}/${purchase.incomeYear}/download`}>
      Last ned årsarkivet for {purchase.incomeYear}
    </LinkButton>
  </article>;
}

export function AnnualBillingView({ companyId, companyName, snapshot, offer: currentOffer, offerUnavailable, limitedHistory,
  beforePurchaseId, operationIds, unconfirmedPurchaseId, cancelAction, cleanupAction }: Props) {
  const { purchases, nextPurchaseId } = snapshot;
  const offer = "offer" in snapshot ? snapshot.offer : currentOffer;
  const base = `/billing?companyId=${encodeURIComponent(companyId)}`;
  return <>
    {offer ? <section className="billingSection" aria-labelledby="annual-offer-title">
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
    </section> : <section className="billingSection">
      <h2 className="sectionTitle">{companyName}</h2>
      {offerUnavailable ? <p>Årstilbudet kan ikke vises nå. Kjøpshistorikken er tilgjengelig nedenfor.</p>
        : <EmptyState title="Nytt selskapsår er ikke klart">
          <p>Fullfør oppsettet for å se et nytt årstilbud. Du kan fortsatt se og administrere tidligere kjøp nedenfor.</p>
          <LinkButton href="/onboarding">Fortsett oppsettet</LinkButton>
        </EmptyState>}
    </section>}
    <section className="billingSection" aria-labelledby="annual-history-title">
      <h2 id="annual-history-title" className="sectionTitle">Kjøpshistorikk og fornyelse</h2>
      {limitedHistory ? <Banner variant="info">Bare de nyeste kjøpene for selskapsåret {offer?.incomeYear} vises nå.
        Hele kjøpshistorikken er midlertidig utilgjengelig.</Banner> : null}
      {purchases.length === 0 ? <EmptyState title={beforePurchaseId ? "Ingen eldre kjøp" : limitedHistory ? "Ingen kjøp i denne delen av historikken" : "Ingen årskjøp registrert"}>
        {beforePurchaseId ? "Du har kommet til slutten av kjøpshistorikken." : limitedHistory ? "Tidligere selskapsår kan ikke vises nå." : "Det er ikke registrert årskjøp for selskapet."}
      </EmptyState> : <div className="annualPurchaseList">
        {purchases.map((purchase) => <Purchase key={purchase.purchaseId} purchase={purchase}
          operationId={operationIds[purchase.purchaseId]} beforePurchaseId={beforePurchaseId}
          unconfirmed={purchase.purchaseId === unconfirmedPurchaseId} cancelAction={cancelAction} cleanupAction={cleanupAction} />)}
      </div>}
      <nav className="actionRow" aria-label="Kjøpshistorikk">
        {beforePurchaseId ? <LinkButton href={base}>Nyeste kjøp</LinkButton> : null}
        {nextPurchaseId && !limitedHistory ? <LinkButton href={`${base}&beforePurchaseId=${encodeURIComponent(nextPurchaseId)}`}>
          Eldre kjøp
        </LinkButton> : null}
      </nav>
      {offer && !purchases.some((purchase) => purchase.incomeYear === offer.incomeYear) ?
        <LinkButton variant="secondary" href={`/archive/${companyId}/${offer.incomeYear}/download`}>Last ned årsarkivet for {offer.incomeYear}</LinkButton> : null}
    </section>
  </>;
}

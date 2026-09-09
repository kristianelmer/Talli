import type { AnnualBillingSnapshotWire, AnnualBillingRefundSnapshotWire, AnnualPurchaseSummaryWire, AnnualPurchaseRefundSummaryWire, AnnualBillingOfferWire, AnnualPurchaseHistoryWire } from "../../../features/billing";
import { Banner, Button, EmptyState, LinkButton, StatusBadge, buttonClass } from "../ui";
import { AnnualCheckoutObservationControl } from "./AnnualCheckoutObservationControl";
import type { AnnualCheckoutObservationAction } from "../../lib/annual-checkout-observation";
import { AnnualAgreementCleanupControl } from "./AnnualAgreementCleanupControl";
import type { AnnualAgreementCleanupAction } from "../../lib/annual-billing-cleanup";
import { AnnualRefundRecoveryControl } from "./AnnualRefundRecoveryControl";
import type { AnnualRefundRecoveryAction, AnnualRefundTargetsView } from "../../lib/annual-refund-recovery";
import type { ReactNode } from "react";

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
  observeAction: AnnualCheckoutObservationAction;
  recoverRefundAction: AnnualRefundRecoveryAction;
  refundTargets?: AnnualRefundTargetsView;
  refundSelectionUnavailable?: boolean;
  checkoutControl?: ReactNode;
  selectedCheckoutPurchaseId?: string;
  checkoutBeforePurchaseId?: string;
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

function RefundTargets({ purchase, beforePurchaseId, selected, recoverAction }: {
  purchase: AnnualPurchaseSummaryWire | AnnualPurchaseRefundSummaryWire;
  beforePurchaseId?: string;
  selected?: AnnualRefundTargetsView;
  recoverAction: AnnualRefundRecoveryAction;
}) {
  const query = new URLSearchParams({ companyId: purchase.companyId, refundPurchaseId: purchase.purchaseId });
  if (beforePurchaseId) query.set("beforePurchaseId", beforePurchaseId);
  const href = `/billing?${query}#annual-purchase-${purchase.purchaseId}`;
  if (!selected) return "refundOperations" in purchase && purchase.refundRequestCount > 0
    ? <LinkButton href={href}>Vis dine registrerte refusjonsforespørsler</LinkButton> : null;
  const retryQuery = new URLSearchParams(query);
  if (selected.beforeRefundRequestId) retryQuery.set("beforeRefundRequestId", selected.beforeRefundRequestId);
  if (selected.selectedRefundRequestId) retryQuery.set("refundRequestId", selected.selectedRefundRequestId);
  const retryHref = `/billing?${retryQuery}#annual-purchase-${purchase.purchaseId}`;
  const page = selected.page;
  const labels = { created: "Klargjort", pending: "Venter på bekreftelse", unknown: "Ukjent utfall", confirmed: "Forsøket er bekreftet", failed: "Forsøket ble ikke fullført" };
  if (page?.nextRefundRequestId) query.set("beforeRefundRequestId", page.nextRefundRequestId);
  return <section aria-label="Dine registrerte refusjonsforespørsler">
    <h4>Dine registrerte refusjonsforespørsler</h4>
    {page === null ? <Banner variant="warning">Forespørslene kan ikke vises nå. <LinkButton href={retryHref}>Last inn på nytt</LinkButton>
      {selected.beforeRefundRequestId ? <LinkButton href={href}>Nyeste forespørsler</LinkButton> : null}</Banner>
      : <>
        {selected.selectedRefundRequestId && !page.targets.some(value => value.refundRequestId === selected.selectedRefundRequestId)
          ? <Banner variant="info">Den valgte forespørselen vises ikke på denne siden. Velg en registrert forespørsel for å sjekke status.</Banner> : null}
        {page.targets.length === 0 ? <p>{selected.beforeRefundRequestId ? "Ingen eldre forespørsler på denne siden."
          : "Ingen registrerte forespørsler kan kontrolleres av deg nå."} Dette endrer ikke et eventuelt gjenstående refusjonsbeløp.</p>
          : <>
            <p>Du kan sjekke status for tidligere registrerte refusjonsforsøk. Beløpene for kjøpet vises ovenfor.</p>
            {page.targets.map(value => <div key={`${purchase.companyId}:${purchase.purchaseId}:${value.refundRequestId}`} className="formPanel">
              <p>Registrert {date.format(new Date(value.requestedAt))} · {labels[value.status]}</p>
              <AnnualRefundRecoveryControl companyId={purchase.companyId} purchaseId={purchase.purchaseId}
                refundRequestId={value.refundRequestId} beforePurchaseId={beforePurchaseId}
                beforeRefundRequestId={selected.beforeRefundRequestId} recoverAction={recoverAction} />
            </div>)}
          </>}
        <nav className="actionRow" aria-label="Refusjonsforespørsler">
          {selected.beforeRefundRequestId ? <LinkButton href={href}>Nyeste forespørsler</LinkButton> : null}
          {page.nextRefundRequestId ? <LinkButton href={`/billing?${query}#annual-purchase-${purchase.purchaseId}`}>Eldre forespørsler</LinkButton> : null}
        </nav>
      </>}
  </section>;
}

function Purchase({ purchase, operationId, beforePurchaseId, unconfirmed, cancelAction, cleanupAction, observeAction,
  recoverRefundAction, refundTargets }: {
  purchase: AnnualPurchaseSummaryWire | AnnualPurchaseRefundSummaryWire;
  operationId: string;
  beforePurchaseId?: string;
  unconfirmed: boolean;
  cancelAction: Props["cancelAction"];
  cleanupAction: Props["cleanupAction"];
  observeAction: Props["observeAction"];
  recoverRefundAction: Props["recoverRefundAction"];
  refundTargets?: AnnualRefundTargetsView;
}) {
  return <article id={`annual-purchase-${purchase.purchaseId}`} className="billingStatusCard" aria-label={`Kjøp ${date.format(new Date(purchase.acceptedAt))}`}>
    <div className="billingStatusHead">
      <h3 className="billingStatusTitle">{date.format(new Date(purchase.acceptedAt))}</h3>
      <StatusBadge variant={purchase.status === "paid" ? "success" : purchase.status === "failed" ? "warning" : "info"}
        label={statusLabels[purchase.status]} />
    </div>
    <p>{money.format(purchase.grossMinor / 100)} inkl. mva. for selskapsåret {purchase.incomeYear}</p>
    <p className="fieldHelp">{money.format(purchase.netMinor / 100)} ekskl. mva. + {money.format(purchase.vatMinor / 100)} mva. ({purchase.vatBasisPoints / 100} %).</p>
    <p>Registrert belastet beløp: {money.format(purchase.capturedMinor / 100)}.</p>
    {purchase.status === "paid" ? <p>Betalt tilgang til og med {calendarDate(purchase.paidThrough)}.
      Lese- og eksporttilgang til og med {calendarDate(purchase.exportThrough)}.</p> : null}
    <RefundEvidence purchase={purchase} />
    <RefundTargets purchase={purchase} beforePurchaseId={beforePurchaseId} selected={refundTargets}
      recoverAction={recoverRefundAction} />
    {purchase.status === "pending" ? <AnnualCheckoutObservationControl key={`checkout-observation:${purchase.companyId}:${purchase.purchaseId}`}
      companyId={purchase.companyId} purchaseId={purchase.purchaseId} beforePurchaseId={beforePurchaseId}
      observeAction={observeAction} /> : null}
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
    {purchase.renewalCanceledAt ? <AnnualAgreementCleanupControl key={`agreement-cleanup:${purchase.companyId}:${purchase.purchaseId}`}
      companyId={purchase.companyId} purchaseId={purchase.purchaseId} beforePurchaseId={beforePurchaseId}
      cleanupAction={cleanupAction} /> : null}
    <details><summary>Vilkårene for dette kjøpet</summary>
      <p style={{ whiteSpace: "pre-wrap" }}>{purchase.termsText}</p>
    </details>
    {/* Download requests can record an export attempt; never prefetch them. */}
    <a className={buttonClass("secondary")} href={`/archive/${purchase.companyId}/${purchase.incomeYear}/download`}>
      Last ned årsarkivet for {purchase.incomeYear}
    </a>
  </article>;
}

export function AnnualBillingView({ companyId, companyName, snapshot, offer: currentOffer, offerUnavailable, limitedHistory,
  beforePurchaseId, operationIds, unconfirmedPurchaseId, cancelAction, cleanupAction, observeAction,
  recoverRefundAction, refundTargets, refundSelectionUnavailable, checkoutControl, selectedCheckoutPurchaseId, checkoutBeforePurchaseId }: Props) {
  const { purchases, nextPurchaseId } = snapshot;
  const offer = "offer" in snapshot ? snapshot.offer : currentOffer;
  const base = `/billing?companyId=${encodeURIComponent(companyId)}`;
  const historyQuery = new URLSearchParams({ companyId });
  if (selectedCheckoutPurchaseId) historyQuery.set("checkoutPurchaseId", selectedCheckoutPurchaseId);
  if (checkoutBeforePurchaseId) historyQuery.set("checkoutBeforePurchaseId", checkoutBeforePurchaseId);
  const historyBase = `/billing?${historyQuery}`;
  return <>
    {offer ? <section className="billingSection" aria-labelledby="annual-offer-title">
      <h2 id="annual-offer-title" className="sectionTitle">{companyName} · selskapsåret {offer.incomeYear}</h2>
      <div className="planCard">
        <p className="planName">Ett abonnement for hele selskapsåret</p>
        <p className="planPrice">{money.format(offer.grossMinor / 100)} inkl. mva.</p>
        <p className="fieldHelp">{money.format(offer.netMinor / 100)} ekskl. mva. + {money.format(offer.vatMinor / 100)} mva. ({offer.vatBasisPoints / 100} %).</p>
        <p>Regnskap, selskapsdokumenter, alle tre innsendinger, kvitteringer og arkiv for et støttet selskapsår.</p>
        {!checkoutControl ? <p>Betaling er ikke åpnet.</p> : null}
        <details><summary>Se hele årstilbudet og vilkårene</summary>
          <p style={{ whiteSpace: "pre-wrap" }}>{offer.termsText}</p>
        </details>
      </div>
    </section> : <section className="billingSection">
      <h2 className="sectionTitle">{companyName}</h2>
      {offerUnavailable ? <p>Årstilbudet kan ikke vises nå. Kjøpshistorikken er tilgjengelig nedenfor.</p>
        : <EmptyState title="Nytt selskapsår er ikke klart" action={<LinkButton href="/onboarding">Fortsett oppsettet</LinkButton>}>
          Fullfør oppsettet for å se et nytt årstilbud. Du kan fortsatt se og administrere tidligere kjøp nedenfor.
        </EmptyState>}
    </section>}
    {checkoutControl}
    <section className="billingSection" aria-labelledby="annual-history-title">
      <h2 id="annual-history-title" className="sectionTitle">Kjøpshistorikk og fornyelse</h2>
      {selectedCheckoutPurchaseId && !purchases.some(purchase => purchase.purchaseId === selectedCheckoutPurchaseId)
        ? <Banner variant="info">Kjøpet fra forespørselen vises ikke på denne siden. Se eldre kjøp for å finne det.</Banner> : null}
      {checkoutBeforePurchaseId ? <LinkButton href={`${base}&beforePurchaseId=${encodeURIComponent(checkoutBeforePurchaseId)}`}>Tilbake til historikksiden du kom fra</LinkButton> : null}
      {refundSelectionUnavailable ? <Banner variant="warning">Den valgte refusjonsoversikten er ikke tilgjengelig på denne historikksiden.
        Velg et kjøp nedenfor for å se registrerte forespørsler.</Banner> : null}
      {limitedHistory ? <Banner variant="info">Bare de nyeste kjøpene for selskapsåret {offer?.incomeYear} vises nå.
        Hele kjøpshistorikken er midlertidig utilgjengelig.</Banner> : null}
      {purchases.length === 0 ? <EmptyState title={beforePurchaseId ? "Ingen eldre kjøp" : limitedHistory ? "Ingen kjøp i denne delen av historikken" : "Ingen årskjøp registrert"}>
        {beforePurchaseId ? "Du har kommet til slutten av kjøpshistorikken." : limitedHistory ? "Tidligere selskapsår kan ikke vises nå." : "Det er ikke registrert årskjøp for selskapet."}
      </EmptyState> : <div className="annualPurchaseList">
        {purchases.map((purchase) => <Purchase key={purchase.purchaseId} purchase={purchase}
          operationId={operationIds[purchase.purchaseId]} beforePurchaseId={beforePurchaseId}
          unconfirmed={purchase.purchaseId === unconfirmedPurchaseId} cancelAction={cancelAction} cleanupAction={cleanupAction} observeAction={observeAction}
          recoverRefundAction={recoverRefundAction} refundTargets={refundTargets?.purchaseId === purchase.purchaseId ? refundTargets : undefined} />)}
      </div>}
      <nav className="actionRow" aria-label="Kjøpshistorikk">
        {beforePurchaseId ? <LinkButton href={historyBase}>Nyeste kjøp</LinkButton> : null}
        {nextPurchaseId && !limitedHistory ? <LinkButton href={`${historyBase}&beforePurchaseId=${encodeURIComponent(nextPurchaseId)}`}>
          Eldre kjøp
        </LinkButton> : null}
      </nav>
      {offer && !purchases.some((purchase) => purchase.incomeYear === offer.incomeYear) ?
        <a className={buttonClass("secondary")} href={`/archive/${companyId}/${offer.incomeYear}/download`}>Last ned årsarkivet for {offer.incomeYear}</a> : null}
    </section>
  </>;
}

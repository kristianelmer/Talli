import { randomUUID } from "node:crypto";
import { redirect } from "next/navigation";
import { annualBillingAccessRejected, annualBillingRecovery, loadAnnualBillingSnapshot, loadAnnualPurchaseHistory, loadAnnualRefundRecoveryTargets } from "../../../features/billing";
import { cancelAnnualRenewal, cleanupAnnualAgreement, observeAnnualCheckout, recoverAnnualRefund } from "../../actions";
import { AnnualBillingView } from "../../components/billing/AnnualBillingView";
import { EmptyState, LinkButton } from "../../components/ui";
import { ownerCopy } from "../../lib/copy";
import { listCompanyAccessContexts } from "../../lib/company-access-context";
import { getCurrentSessionAccessToken } from "../../lib/supabase/auth-session";
import type { AnnualRefundTargetsView } from "../../lib/annual-refund-recovery";

export const dynamic = "force-dynamic";
const t = ownerCopy.billing;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
type Params = Record<string, string | string[] | undefined>;
function parameter(params: Params, name: string) {
  const value = params[name];
  return typeof value === "string" ? value : undefined;
}

export default async function BillingPage({ searchParams }: { searchParams: Promise<Params> }) {
  const params = await searchParams;
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) {
    const returnQuery = new URLSearchParams();
    for (const key of ["companyId", "beforePurchaseId", "cancellationOperationId", "cancellationPurchaseId", "cleanupPurchaseId", "checkoutPurchaseId", "refundPurchaseId", "refundRequestId", "beforeRefundRequestId"]) {
      const value = parameter(params, key);
      if (value && uuid.test(value)) returnQuery.set(key, value);
    }
    redirect(`/login?next=${encodeURIComponent(`/billing?${returnQuery}`)}`);
  }
  const context = await listCompanyAccessContexts();
  const selectedId = parameter(params, "companyId");
  const company = selectedId
    ? context.companies.find((item) => item.id === selectedId)
    : context.companies[0];
  const beforePurchaseId = parameter(params, "beforePurchaseId");
  const query = new URLSearchParams();
  if (company) query.set("companyId", company.id);
  else if (selectedId && uuid.test(selectedId)) query.set("companyId", selectedId);
  if (beforePurchaseId && uuid.test(beforePurchaseId)) query.set("beforePurchaseId", beforePurchaseId);
  for (const key of ["cancellationOperationId", "cancellationPurchaseId", "cleanupPurchaseId", "checkoutPurchaseId", "refundPurchaseId", "refundRequestId", "beforeRefundRequestId"]) {
    const value = parameter(params, key);
    if (value && uuid.test(value)) query.set(key, value);
  }
  const returnTo = `/billing?${query}`;
  const mfaHref = `/mfa?next=${encodeURIComponent(returnTo)}`;
  let content;
  if (context.error) {
    content = <EmptyState title="Abonnementet kan ikke vises nå" action={
      <LinkButton href={context.requiresAal2 ? mfaHref : context.requiresSignIn
        ? `/login?next=${encodeURIComponent(returnTo)}` : returnTo}>
        {context.requiresAal2 ? "Bekreft identiteten din" : context.requiresSignIn ? "Logg inn igjen" : "Prøv igjen"}
      </LinkButton>
    }>Vi må kunne bekrefte tilgangen din til selskapet før vi viser abonnementet.</EmptyState>;
  } else if (!company) {
    content = <EmptyState title={selectedId ? "Selskapet er ikke tilgjengelig" : t.needsCompanyTitle}
      action={<LinkButton href={selectedId ? "/billing" : "/onboarding"}>
        {selectedId ? "Tilbake til abonnement" : t.needsCompanyCta}
      </LinkButton>}>
      {selectedId ? "Velg et selskap du har tilgang til." : t.needsCompanyBody}
    </EmptyState>;
  } else if (beforePurchaseId && !uuid.test(beforePurchaseId)) {
    content = <EmptyState title="Historikksiden er ikke tilgjengelig" action={
      <LinkButton href={`/billing?companyId=${company.id}`}>Vis nyeste kjøp</LinkButton>
    }>Åpne kjøpshistorikken på nytt.</EmptyState>;
  } else {
    let snapshot;
    let published;
    let offerUnavailable = false;
    let limitedHistory = false;
    let recovery;
    let refundTargets: AnnualRefundTargetsView | undefined;
    let refundSelectionUnavailable = false;
    try {
      const history = await loadAnnualPurchaseHistory(accessToken, {
        companyId: company.id, beforePurchaseId,
      });
      if (history === null && beforePurchaseId) throw new Error("Annual history unavailable");
      if (company.admittedAccountingYear) {
        try {
          published = await loadAnnualBillingSnapshot(accessToken, {
            companyId: company.id, incomeYear: company.admittedAccountingYear,
          });
        } catch (error) {
          if (annualBillingAccessRejected(error)) throw error;
          offerUnavailable = true;
        }
      }
      const candidate = history ?? published;
      limitedHistory = history === null && published !== undefined;
      const refundPurchaseId = parameter(params, "refundPurchaseId");
      const refundRequestId = parameter(params, "refundRequestId");
      const beforeRefundRequestId = parameter(params, "beforeRefundRequestId");
      if (refundPurchaseId || refundRequestId || beforeRefundRequestId) {
        const selected = candidate?.purchases.find(value => value.purchaseId === refundPurchaseId);
        if (!selected || !refundPurchaseId || !uuid.test(refundPurchaseId)
          || (refundRequestId && !uuid.test(refundRequestId)) || (beforeRefundRequestId && !uuid.test(beforeRefundRequestId))) {
          refundSelectionUnavailable = true;
        } else {
          let page = null;
          try {
            page = await loadAnnualRefundRecoveryTargets(accessToken, { companyId: company.id,
              purchaseId: refundPurchaseId, beforeRefundRequestId });
            if (page && (page.companyId !== company.id || page.purchaseId !== selected.purchaseId || page.incomeYear !== selected.incomeYear)) {
              throw new Error("Refund target scope unavailable");
            }
          } catch (error) {
            if (annualBillingAccessRejected(error)) throw error;
            page = null;
          }
          refundTargets = { purchaseId: refundPurchaseId, beforeRefundRequestId, selectedRefundRequestId: refundRequestId, page };
        }
      }
      // Assign only after all protected reads: a later auth failure must not
      // leave previously loaded history or controls visible.
      snapshot = candidate;
    } catch (error) {
      recovery = annualBillingRecovery(error);
    }
    if (snapshot) {
      const retryId = parameter(params, "cancellationOperationId");
      const retryPurchaseId = parameter(params, "cancellationPurchaseId");
      content = <AnnualBillingView companyId={company.id} companyName={company.name} snapshot={snapshot}
        offer={published?.offer} offerUnavailable={offerUnavailable} limitedHistory={limitedHistory}
        beforePurchaseId={beforePurchaseId} cancelAction={cancelAnnualRenewal} cleanupAction={cleanupAnnualAgreement} observeAction={observeAnnualCheckout}
        recoverRefundAction={recoverAnnualRefund} refundTargets={refundTargets} refundSelectionUnavailable={refundSelectionUnavailable}
        unconfirmedPurchaseId={parameter(params, "cancellationError") === "unconfirmed" ? retryPurchaseId : undefined}
        operationIds={Object.fromEntries(snapshot.purchases.map((purchase) => [
          purchase.purchaseId, retryId && uuid.test(retryId) && purchase.purchaseId === retryPurchaseId
            ? retryId : randomUUID(),
        ]))} />;
    } else {
      content = <EmptyState title="Abonnementet kan ikke vises nå" action={
        <LinkButton href={recovery === "step-up" ? mfaHref : recovery === "sign-in"
          ? `/login?next=${encodeURIComponent(returnTo)}` : returnTo}>
          {recovery === "step-up" ? "Bekreft identiteten din" : recovery === "sign-in" ? "Logg inn igjen" : "Prøv igjen"}
        </LinkButton>
      }>Vi fikk ikke bekreftet betalings- og fornyelsesstatusen. Prøv igjen for å se oppdatert status.
        {beforePurchaseId ? <LinkButton href={`/billing?companyId=${company.id}`}>Vis nyeste kjøp</LinkButton> : null}
      </EmptyState>;
    }
  }
  return <div>
    <div className="pageHead"><h1 className="pageTitle">{t.hubTitle}</h1>
      <p className="pageLede">Se årstilbud, kjøpshistorikk og fornyelse for selskapet.</p></div>
    {context.companies.length > 1 ? <nav aria-label="Velg selskap" className="actionRow">
      {context.companies.map((item) => <LinkButton key={item.id}
        href={`/billing?companyId=${item.id}`} aria-current={company?.id === item.id ? "page" : undefined}>
        {item.name}
      </LinkButton>)}
    </nav> : null}
    {content}
  </div>;
}

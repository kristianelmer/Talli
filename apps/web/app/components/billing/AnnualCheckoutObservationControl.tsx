"use client";

import { useActionState } from "react";
import type { AnnualCheckoutObservationAction, AnnualCheckoutObservationActionState } from "../../lib/annual-checkout-observation";
import { Banner, Button, LinkButton, buttonClass } from "../ui";

export function AnnualCheckoutObservationControl({ companyId, purchaseId, beforePurchaseId, observeAction }: {
  companyId: string;
  purchaseId: string;
  beforePurchaseId?: string;
  observeAction: AnnualCheckoutObservationAction;
}) {
  const [state, formAction, pending] = useActionState<AnnualCheckoutObservationActionState, FormData>(async (previous, formData) => {
    try {
      return await observeAction(previous, formData);
    } catch {
      // A response can be lost after the backend stores an observation. Retry
      // the original purchase without inventing a result or a new charge.
      return { kind: "recovery", companyId, purchaseId, reason: "unavailable", href: null };
    }
  }, { kind: "idle" });
  const observed = state.kind === "observed" && state.companyId === companyId && state.purchaseId === purchaseId ? state : null;
  const recovery = state.kind === "recovery" && state.companyId === companyId && state.purchaseId === purchaseId ? state : null;
  const query = new URLSearchParams({ companyId });
  if (beforePurchaseId) query.set("beforePurchaseId", beforePurchaseId);
  const historyHref = `/billing?${query}#annual-purchase-${purchaseId}`;
  return <div className="formPanel" aria-label="Kontroll av betalingsstatus">
    <p>Sjekk statusen for dette kjøpet hos betalingsleverandøren.</p>
    <div aria-live="polite" aria-atomic="true">
      {pending ? <p>Sjekker betalingsstatus …</p> : observed ? <Banner variant="info">
        {observed.status === "pending" ? "Betalingen er fortsatt ikke bekreftet. Du kan sjekke det samme kjøpet igjen senere."
          : <>Statusen er kontrollert. <LinkButton href={historyHref}>Vis oppdatert kjøpshistorikk</LinkButton></>}
        {observed.status === "pending" && observed.checkoutUrl ? <a className={buttonClass("primary")}
          href={observed.checkoutUrl} rel="noreferrer">Fortsett til betaling</a> : null}
      </Banner> : recovery || state.kind === "invalid" ? <Banner variant="warning">
        Vi fikk ikke bekreftet betalingsstatusen.
        {recovery?.href ? <> <LinkButton href={recovery.href}>
          {recovery.reason === "step-up" ? "Bekreft identiteten din" : "Logg inn igjen"}
        </LinkButton></> : " Prøv igjen senere for det samme kjøpet."}
      </Banner> : null}
    </div>
    <form action={formAction}>
      <input type="hidden" name="companyId" value={companyId} />
      <input type="hidden" name="purchaseId" value={purchaseId} />
      {beforePurchaseId ? <input type="hidden" name="beforePurchaseId" value={beforePurchaseId} /> : null}
      <Button type="submit" variant="secondary" disabled={pending}>
        {pending ? "Sjekker …" : "Sjekk betalingsstatus"}
      </Button>
    </form>
    {recovery || state.kind === "invalid" ? <LinkButton href={historyHref}>Last inn kjøpshistorikken</LinkButton> : null}
  </div>;
}

"use client";

import { useActionState } from "react";
import type { AnnualRefundRecoveryAction, AnnualRefundRecoveryActionState } from "../../lib/annual-refund-recovery";
import { Banner, Button, LinkButton } from "../ui";

export function AnnualRefundRecoveryControl({ companyId, purchaseId, refundRequestId, beforePurchaseId,
  beforeRefundRequestId, recoverAction }: {
  companyId: string;
  purchaseId: string;
  refundRequestId: string;
  beforePurchaseId?: string;
  beforeRefundRequestId?: string;
  recoverAction: AnnualRefundRecoveryAction;
}) {
  const [state, formAction, pending] = useActionState<AnnualRefundRecoveryActionState, FormData>(async (previous, formData) => {
    try {
      return await recoverAction(previous, formData);
    } catch {
      return { kind: "recovery", companyId, purchaseId, refundRequestId, reason: "unavailable", href: null };
    }
  }, { kind: "idle" });
  const scoped = (state.kind === "observed" || state.kind === "recovery") && state.companyId === companyId
    && state.purchaseId === purchaseId && state.refundRequestId === refundRequestId ? state : null;
  const query = new URLSearchParams({ companyId, refundPurchaseId: purchaseId });
  if (beforePurchaseId) query.set("beforePurchaseId", beforePurchaseId);
  if (beforeRefundRequestId) query.set("beforeRefundRequestId", beforeRefundRequestId);
  const historyHref = `/billing?${query}#annual-purchase-${purchaseId}`;
  return <div className="formPanel" aria-label="Kontroll av refusjonsstatus">
    <div aria-live="polite" aria-atomic="true">
      {pending ? <p>Sjekker refusjonsstatus …</p> : scoped?.kind === "observed" ? <Banner variant="info">
        {scoped.status === "pending" ? "Refusjonsforsøket venter fortsatt på bekreftelse."
          : scoped.status === "unknown" ? "Utfallet av refusjonsforsøket er fortsatt ukjent. Du kan sjekke igjen senere."
          : scoped.status === "failed" ? "Dette refusjonsforsøket ble ikke fullført."
          : "Dette refusjonsforsøket er bekreftet. Det kan fortsatt gjenstå et beløp for kjøpet."}
        {" "}<LinkButton href={historyHref}>Vis oppdatert kjøpshistorikk</LinkButton>
      </Banner> : scoped?.kind === "recovery" || state.kind === "invalid" ? <Banner variant="warning">
        Vi fikk ikke bekreftet refusjonsstatusen.
        {scoped?.kind === "recovery" && scoped.href ? <> <LinkButton href={scoped.href}>
          {scoped.reason === "step-up" ? "Bekreft identiteten din" : "Logg inn igjen"}
        </LinkButton></> : " Prøv igjen senere for den samme forespørselen."}
      </Banner> : null}
    </div>
    <form action={formAction}>
      <input type="hidden" name="companyId" value={companyId} />
      <input type="hidden" name="purchaseId" value={purchaseId} />
      <input type="hidden" name="refundRequestId" value={refundRequestId} />
      {beforePurchaseId ? <input type="hidden" name="beforePurchaseId" value={beforePurchaseId} /> : null}
      {beforeRefundRequestId ? <input type="hidden" name="beforeRefundRequestId" value={beforeRefundRequestId} /> : null}
      <Button type="submit" variant="secondary" disabled={pending}>
        {pending ? "Sjekker …" : "Sjekk refusjonsstatus"}
      </Button>
    </form>
    {scoped?.kind === "recovery" || state.kind === "invalid" ? <LinkButton href={historyHref}>Last inn refusjonsoversikten</LinkButton> : null}
  </div>;
}

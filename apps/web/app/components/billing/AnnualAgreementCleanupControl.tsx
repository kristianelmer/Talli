"use client";

import { useActionState } from "react";
import type { AnnualAgreementCleanupAction, AnnualAgreementCleanupActionState } from "../../lib/annual-billing-cleanup";
import { Banner, Button, LinkButton } from "../ui";

const messages = {
  confirmed: "Betalingsleverandøren har bekreftet at betalingsavtalen er avsluttet.",
  pending: "Avslutningen venter på bekreftelse. Du kan prøve igjen for å kontrollere den samme avtalen.",
  unknown: "Vi fikk ikke bekreftet utfallet. Prøv igjen for å kontrollere den samme betalingsavtalen.",
  deferred: "Betalingsavtalen kan ikke avsluttes ennå. Fornyelsen er fortsatt stoppet i Talli. Prøv igjen senere.",
};

export function AnnualAgreementCleanupControl({ companyId, purchaseId, beforePurchaseId, cleanupAction }: {
  companyId: string;
  purchaseId: string;
  beforePurchaseId?: string;
  cleanupAction: AnnualAgreementCleanupAction;
}) {
  const [state, formAction, pending] = useActionState<AnnualAgreementCleanupActionState, FormData>(async (previous, formData) => {
    try {
      return await cleanupAction(previous, formData);
    } catch {
      // A lost browser-to-server response can follow a committed effect. Keep
      // the same purchase retryable without treating that uncertainty as success.
      return { kind: "recovery", companyId, purchaseId, reason: "unavailable", href: null };
    }
  }, { kind: "idle" });
  const result = state.kind === "result" && state.value.companyId === companyId && state.value.purchaseId === purchaseId
    ? state.value : null;
  const recovery = state.kind === "recovery" && state.companyId === companyId && state.purchaseId === purchaseId
    ? state : null;
  const confirmed = result?.status === "confirmed";
  return <div className="formPanel" aria-label="Avslutning av betalingsavtale">
    <p>Fornyelsen er stoppet i Talli. Her kan du kontrollere og fullføre avslutningen hos betalingsleverandøren.</p>
    <div aria-live="polite" aria-atomic="true">
      {pending ? <p>Kontrollerer betalingsavtalen …</p> : result ? <Banner variant={confirmed ? "success" : "warning"}>
        {messages[result.status]}
      </Banner> : recovery || state.kind === "invalid" ? <Banner variant="warning">
        Vi fikk ikke bekreftet at betalingsavtalen er avsluttet.
        {recovery?.href ? <> <LinkButton href={recovery.href}>
          {recovery.reason === "step-up" ? "Bekreft identiteten din" : "Logg inn igjen"}
        </LinkButton></> : " Prøv igjen senere."}
      </Banner> : null}
    </div>
    {!confirmed ? <form action={formAction}>
      <input type="hidden" name="companyId" value={companyId} />
      <input type="hidden" name="purchaseId" value={purchaseId} />
      {beforePurchaseId ? <input type="hidden" name="beforePurchaseId" value={beforePurchaseId} /> : null}
      <Button type="submit" variant="secondary" disabled={pending}>
        {pending ? "Kontrollerer …" : "Fullfør avslutning av betalingsavtalen"}
      </Button>
    </form> : null}
  </div>;
}

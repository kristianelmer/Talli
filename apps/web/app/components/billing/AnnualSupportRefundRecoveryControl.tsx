"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import type { AnnualSupportRefundIdentity, AnnualSupportRefundRecoveryAction, AnnualSupportRefundRecoveryActionState } from "../../lib/annual-support-refund-recovery";
import { operatorSupportLocation } from "../../lib/operator-support";
import { Banner, Button } from "../ui";

export function AnnualSupportRefundRecoveryControl({ initiatingUserId, supportCaseId, companyId, purchaseId,
  refundRequestId, beforePurchaseId, beforeRefundRequestId, recoverAction }: AnnualSupportRefundIdentity & {
  beforePurchaseId?: string;
  beforeRefundRequestId?: string;
  recoverAction: AnnualSupportRefundRecoveryAction;
}) {
  const identity = { initiatingUserId, supportCaseId, companyId, purchaseId, refundRequestId };
  const scopeKey = [initiatingUserId, supportCaseId, companyId, purchaseId, refundRequestId].join(":");
  const currentScope = useRef(scopeKey);
  currentScope.current = scopeKey;
  const mounted = useRef(true);
  const busy = useRef(false);
  const [pending, setPending] = useState(false);
  const [state, setState] = useState<AnnualSupportRefundRecoveryActionState>({ kind: "idle" });
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const { returnTo } = operatorSupportLocation({ supportCase: supportCaseId, companyId, refundPurchaseId: purchaseId,
    refundRequestId, annualBefore: beforePurchaseId, beforeRefundRequestId });
  const reloadHref = returnTo.split("#")[0];
  const unavailable = (): AnnualSupportRefundRecoveryActionState => ({
    kind: "recovery", ...identity, reason: "unavailable", href: returnTo,
  });
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy.current) return;
    const submitted = new FormData(event.currentTarget);
    busy.current = true;
    setPending(true);
    let result: AnnualSupportRefundRecoveryActionState;
    try { result = await recoverAction({ kind: "idle" }, submitted); }
    catch { result = unavailable(); }
    finally { busy.current = false; }
    if (mounted.current && currentScope.current === scopeKey) {
      setState(result);
      setPending(false);
    }
  }
  const scoped = state.kind !== "idle" && state.kind !== "invalid"
    && (Object.keys(identity) as (keyof AnnualSupportRefundIdentity)[]).every(name => state[name] === identity[name]) ? state : null;
  return <div className="formPanel" aria-label="Kontroll av registrert refusjonsforsøk">
    <p>Sjekker det registrerte forsøket. Oppretter ingen ny refusjon.</p>
    <div aria-live="polite" aria-atomic="true">
      {pending ? <p>Sjekker refusjonsstatus …</p> : scoped?.kind === "observed" ? <Banner variant="info">
        {scoped.status === "pending" ? "Refusjonsforsøket venter fortsatt på bekreftelse."
          : scoped.status === "unknown" ? "Utfallet av refusjonsforsøket er fortsatt ukjent. Du kan sjekke igjen senere."
          : scoped.status === "failed" ? "Dette refusjonsforsøket ble ikke fullført."
          : "Dette refusjonsforsøket er bekreftet. Det kan fortsatt gjenstå et beløp for kjøpet."}
        {" "}<a className="btn btn--secondary" href={reloadHref}>Vis oppdatert kjøpshistorikk</a>
      </Banner> : scoped?.kind === "different-user" ? <Banner variant="warning">
        Brukeren er endret. Last inn saken og velg forespørselen på nytt.
        {" "}<a className="btn btn--secondary" href={reloadHref}>Last inn saken</a>
      </Banner> : scoped?.kind === "recovery" || state.kind === "invalid" ? <Banner variant="warning">
        Vi fikk ikke bekreftet refusjonsstatusen. Kontroller tilgangen til saken før du prøver igjen.
        {scoped?.kind === "recovery" ? <> <a className="btn btn--secondary" href={scoped.reason === "unavailable" || scoped.reason === "forbidden" ? reloadHref : scoped.href}>
          {scoped.reason === "sign-in" ? "Logg inn igjen" : scoped.reason === "step-up" ? "Bekreft identiteten din" : "Last inn saken på nytt"}
        </a></> : null}
      </Banner> : null}
    </div>
    <form onSubmit={submit}>
      {Object.entries(identity).map(([name, value]) => <input key={name} type="hidden" name={name} value={value} />)}
      {beforePurchaseId ? <input type="hidden" name="beforePurchaseId" value={beforePurchaseId} /> : null}
      {beforeRefundRequestId ? <input type="hidden" name="beforeRefundRequestId" value={beforeRefundRequestId} /> : null}
      <Button type="submit" variant="secondary" disabled={pending || scoped?.kind === "different-user"}>
        {pending ? "Sjekker …" : "Sjekk refusjonsstatus"}
      </Button>
    </form>
  </div>;
}

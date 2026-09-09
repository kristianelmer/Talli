"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import type { AnnualSupportCleanupIdentity, AnnualSupportCleanupRecoveryAction, AnnualSupportCleanupRecoveryActionState } from "../../lib/annual-support-cleanup-recovery";
import { operatorSupportLocation } from "../../lib/operator-support";
import { Banner, Button } from "../ui";

export function AnnualSupportCleanupRecoveryControl({ initiatingUserId, supportCaseId, companyId, purchaseId,
  beforePurchaseId, recoverAction }: AnnualSupportCleanupIdentity & {
  beforePurchaseId?: string;
  recoverAction: AnnualSupportCleanupRecoveryAction;
}) {
  const identity = { initiatingUserId, supportCaseId, companyId, purchaseId };
  const scopeKey = [initiatingUserId, supportCaseId, companyId, purchaseId].join(":");
  const currentScope = useRef(scopeKey);
  currentScope.current = scopeKey;
  const mounted = useRef(true);
  const busy = useRef(false);
  const [pending, setPending] = useState(false);
  const [state, setState] = useState<AnnualSupportCleanupRecoveryActionState>({ kind: "idle" });
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const { returnTo } = operatorSupportLocation({ supportCase: supportCaseId, companyId, annualBefore: beforePurchaseId });
  const reloadHref = returnTo.split("#")[0];
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy.current) return;
    const submitted = new FormData(event.currentTarget);
    busy.current = true;
    setPending(true);
    let result: AnnualSupportCleanupRecoveryActionState;
    try { result = await recoverAction({ kind: "idle" }, submitted); }
    catch { result = { kind: "recovery", ...identity, reason: "unavailable", href: reloadHref }; }
    finally { busy.current = false; }
    if (mounted.current && currentScope.current === scopeKey) {
      setState(result);
      setPending(false);
    }
  }
  const scoped = state.kind !== "idle" && state.kind !== "invalid"
    && (Object.keys(identity) as (keyof AnnualSupportCleanupIdentity)[]).every(name => state[name] === identity[name]) ? state : null;
  return <div className="formPanel" aria-label="Kontroll av registrert avtalestopp">
    <p>Sjekk om betalingsleverandøren har bekreftet det registrerte avtalestoppet.</p>
    <div aria-live="polite" aria-atomic="true">
      {pending ? <p>Sjekker avtalestopp …</p> : scoped?.kind === "observed" ? <Banner variant="info">
        {scoped.status === "confirmed" ? "Betalingsleverandøren har bekreftet avtalestoppet."
          : scoped.status === "pending" ? "Avtalestoppet er ikke bekreftet. Følg opp det registrerte forsøket i saken."
          : "Utfallet av avtalestoppet er fortsatt ukjent. Du kan sjekke igjen senere."}
        {" "}<a className="btn btn--secondary" href={reloadHref}>Vis oppdatert kjøpshistorikk</a>
      </Banner> : scoped?.kind === "different-user" ? <Banner variant="warning">
        Brukeren er endret. Last inn saken og velg kjøpet på nytt.
        {" "}<a className="btn btn--secondary" href={reloadHref}>Last inn saken</a>
      </Banner> : scoped?.kind === "recovery" || state.kind === "invalid" ? <Banner variant="warning">
        Vi fikk ikke bekreftet avtalestoppet. Kontroller tilgangen til saken før du prøver igjen.
        {scoped?.kind === "recovery" ? <> <a className="btn btn--secondary" href={scoped.reason === "unavailable" || scoped.reason === "forbidden" ? reloadHref : scoped.href}>
          {scoped.reason === "sign-in" ? "Logg inn igjen" : scoped.reason === "step-up" ? "Bekreft identiteten din" : "Last inn saken på nytt"}
        </a></> : null}
      </Banner> : null}
    </div>
    <form onSubmit={submit}>
      {Object.entries(identity).map(([name, value]) => <input key={name} type="hidden" name={name} value={value} />)}
      {beforePurchaseId ? <input type="hidden" name="beforePurchaseId" value={beforePurchaseId} /> : null}
      <Button type="submit" variant="secondary" disabled={pending || scoped?.kind === "different-user"}>
        {pending ? "Sjekker …" : "Sjekk avtalestopp"}
      </Button>
    </form>
  </div>;
}

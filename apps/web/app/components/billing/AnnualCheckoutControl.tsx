"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import type { AnnualCheckoutPreparationWire } from "../../../features/billing";
import {
  annualCheckoutHistoryHref, parseAnnualCheckoutDraft, readAnnualCheckoutDraft, removeAnnualCheckoutDraft,
  sameAnnualCheckoutDraft, saveAnnualCheckoutDraft, type AnnualCheckoutDraft, type AnnualCheckoutDraftRead,
  type AnnualCheckoutRequestAction, type AnnualCheckoutRequestActionState,
} from "../../lib/annual-checkout-request";
import { Banner, Button, LinkButton, buttonClass } from "../ui";

const money = new Intl.NumberFormat("nb-NO", { style: "currency", currency: "NOK" });
const calendarDate = (value: string) => new Intl.DateTimeFormat("nb-NO", {
  dateStyle: "long", timeZone: "Europe/Oslo",
}).format(new Date(`${value}T12:00:00Z`));

export function AnnualCheckoutControl({ companyId, initiatingUserId, beforePurchaseId, preparation, pendingPurchaseIds, startAction, withdrawAction }: {
  companyId: string;
  initiatingUserId: string;
  beforePurchaseId?: string;
  preparation: AnnualCheckoutPreparationWire | null;
  pendingPurchaseIds: string[];
  startAction: AnnualCheckoutRequestAction;
  withdrawAction: AnnualCheckoutRequestAction;
}) {
  const [saved, setSaved] = useState<AnnualCheckoutDraftRead | { kind: "restoring" }>({ kind: "restoring" });
  const [feedback, setFeedback] = useState<AnnualCheckoutRequestActionState>({ kind: "idle" });
  const [pending, setPending] = useState(false);
  const [storageFailed, setStorageFailed] = useState(false);
  const busy = useRef(false);
  const currentUser = useRef<string | null>(initiatingUserId);
  const base = `/billing?${new URLSearchParams({ companyId })}`;
  const returnTo = beforePurchaseId ? `${base}&beforePurchaseId=${encodeURIComponent(beforePurchaseId)}` : base;

  useEffect(() => {
    currentUser.current = initiatingUserId;
    try { setSaved(readAnnualCheckoutDraft(window.sessionStorage, companyId)); }
    catch { setSaved({ kind: "unavailable" }); }
    setFeedback({ kind: "idle" });
    return () => { currentUser.current = null; };
  }, [companyId, initiatingUserId]);

  async function send(next: AnnualCheckoutDraft, expected: AnnualCheckoutDraft | null) {
    // A ref blocks duplicate events before React has rendered disabled buttons.
    if (busy.current || next.initiatingUserId !== initiatingUserId || next.body.companyId !== companyId) return;
    busy.current = true;
    setStorageFailed(false);
    setFeedback({ kind: "idle" });
    let persisted = false;
    try {
      // Persist the withdrawal choice too, before the first await. A refresh
      // after a lost response must not resurrect the purchase-start action.
      if (!saveAnnualCheckoutDraft(window.sessionStorage, next, expected)) {
        setSaved(readAnnualCheckoutDraft(window.sessionStorage, companyId));
        setStorageFailed(true);
        return;
      }
      setSaved({ kind: "retained", draft: next });
      persisted = true;
      setPending(true);
      const form = new FormData();
      form.set("draft", JSON.stringify(next));
      const result = await (next.phase === "withdrawal-requested" ? withdrawAction : startAction)({ kind: "idle" }, form);
      if (currentUser.current !== next.initiatingUserId) return;
      if (!("draft" in result) || !sameAnnualCheckoutDraft(result.draft, next)) {
        setFeedback({ kind: "recovery", draft: next, reason: "unavailable", href: null, withdrawalRecommended: false });
        return;
      }
      if (result.kind === "started" || result.kind === "resolved") {
        if (!removeAnnualCheckoutDraft(window.sessionStorage, next)) {
          setSaved(readAnnualCheckoutDraft(window.sessionStorage, companyId));
          setStorageFailed(true);
          return;
        }
        setSaved({ kind: "empty" });
      }
      setFeedback(result);
    } catch {
      if (currentUser.current === next.initiatingUserId) {
        if (!persisted) { setSaved({ kind: "unavailable" }); setStorageFailed(true); }
        setFeedback({ kind: "recovery", draft: next, reason: "unavailable", href: null, withdrawalRecommended: false });
      }
    } finally {
      busy.current = false;
      if (currentUser.current === next.initiatingUserId) setPending(false);
    }
  }

  function purchase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy.current || saved.kind !== "empty" || preparation?.state !== "available" || !preparation.offer || !preparation.consentVersion) return;
    const data = new FormData(event.currentTarget);
    const offer = preparation.offer;
    const draft = parseAnnualCheckoutDraft(JSON.stringify({
      version: 1, initiatingUserId, idempotencyKey: crypto.randomUUID(), beforePurchaseId: beforePurchaseId ?? null,
      phase: "checkout-requested", body: { companyId, incomeYear: offer.incomeYear,
        offerVersion: offer.offerVersion, termsDigest: offer.termsDigest, consentVersion: preparation.consentVersion,
        purchaseAccepted: data.get("purchaseAccepted") === "on", recurringConsent: data.get("recurringConsent") === "on" },
    }));
    if (draft) void send(draft, null);
  }

  const draft = saved.kind === "retained" ? saved.draft : null;
  const ownFeedback = "draft" in feedback && feedback.draft.initiatingUserId === initiatingUserId
    && feedback.draft.body.companyId === companyId ? feedback : null;
  const mismatch = (draft && draft.initiatingUserId !== initiatingUserId) || ownFeedback?.kind === "different-user";
  const recovery = ownFeedback?.kind === "recovery" ? ownFeedback : null;
  const completed = saved.kind === "empty" && (ownFeedback?.kind === "started" || ownFeedback?.kind === "resolved") ? ownFeedback : null;
  const purchaseId = completed?.kind === "started" ? completed.purchaseId : completed?.resolution.purchaseId;
  const withdrawn = completed?.kind === "resolved" && completed.resolution.state === "withdrawn";
  const offer = preparation?.state === "available" ? preparation.offer : null;

  return <section id="annual-checkout-review" className="billingSection" aria-labelledby="annual-checkout-title">
    <h2 id="annual-checkout-title" className="sectionTitle">Kjøp eller gjenopprett et årskjøp</h2>
    <div aria-live="polite" aria-atomic="true">
      {pending ? <p>{draft?.phase === "withdrawal-requested" ? "Trekker tilbake kjøpsforespørselen …" : "Registrerer kjøpsforespørselen …"}</p> : null}
      {storageFailed || saved.kind === "unavailable" ? <Banner variant="warning">
        Kjøpsforespørselen kan ikke gjenopprettes trygt nå. Last inn siden på nytt før du fortsetter.
        <a className={buttonClass("secondary")} href={returnTo}>Last inn siden på nytt</a>
      </Banner> : null}
      {mismatch ? <Banner variant="warning">Denne forespørselen ble startet av en annen bruker.
        Logg inn med brukeren som startet den. <LinkButton href={`/login?reauth=1&next=${encodeURIComponent(returnTo)}`}>Logg inn igjen</LinkButton>
      </Banner> : recovery && !pending ? <Banner variant="warning">
        {draft?.phase === "withdrawal-requested" ? "Vi fikk ikke bekreftet tilbaketrekkingen. Prøv igjen med den samme forespørselen."
          : recovery.withdrawalRecommended ? "Den tidligere forespørselen kan ikke fullføres med disse vilkårene. Trekk den tilbake før du gjennomgår et nytt kjøp."
          : "Vi fikk ikke bekreftet kjøpet. Den opprinnelige forespørselen er beholdt."}
        {recovery.href ? <LinkButton href={recovery.href}>{recovery.reason === "step-up" ? "Bekreft identiteten din" : "Logg inn igjen"}</LinkButton> : null}
      </Banner> : null}
      {completed && !pending ? <Banner variant="info">
        {withdrawn ? "Kjøpsforespørselen er trukket tilbake. Den kan ikke opprette et kjøp."
          : "Forespørselen er registrert som et kjøp. Se status og tilgjengelige handlinger i kjøpshistorikken."}
        {completed.kind === "started" && completed.checkoutUrl && pendingPurchaseIds.includes(completed.purchaseId)
          ? <a className={buttonClass("primary")} href={completed.checkoutUrl} rel="noreferrer">Fortsett til betaling</a> : null}
        {purchaseId ? <LinkButton href={annualCheckoutHistoryHref(companyId, purchaseId, completed.draft.beforePurchaseId)}>Se kjøpshistorikken</LinkButton> : null}
        {withdrawn ? <a className={buttonClass("secondary")} href={base}>Se gjeldende årstilbud</a> : null}
      </Banner> : null}
    </div>
    {saved.kind === "restoring" ? <p>Henter eventuell tidligere kjøpsforespørsel …</p> : null}
    {draft && !mismatch && !storageFailed ? <div className="formPanel">
      <p>Den beholdte forespørselen gjelder selskapsåret {draft.body.incomeYear}.
        Ditt valg om automatisk fornyelse: {draft.body.recurringConsent ? "Ja" : "Nei"}.</p>
      <p>Hvis kjøpet allerede er registrert, viser vi det i kjøpshistorikken.</p>
      <div className="actionRow">
        {draft.phase === "checkout-requested" && !recovery?.withdrawalRecommended ? <Button type="button" disabled={pending}
          onClick={() => void send(draft, draft)}>Prøv samme kjøpsforespørsel igjen</Button> : null}
        <Button type="button" variant="secondary" disabled={pending}
          onClick={() => void send({ ...draft, phase: "withdrawal-requested" }, draft)}>
          {draft.phase === "withdrawal-requested" ? "Prøv tilbaketrekkingen igjen" : "Trekk tilbake kjøpsforespørselen"}
        </Button>
      </div>
      <LinkButton href={returnTo}>Se kjøpshistorikken</LinkButton>
    </div> : null}
    {saved.kind === "empty" && !completed && !storageFailed ? offer && preparation?.consentVersion ? <form
      key={`${offer.incomeYear}:${offer.offerVersion}:${offer.termsDigest}:${preparation.consentVersion}`} className="formPanel" onSubmit={purchase}>
      <p><strong>{money.format(offer.grossMinor / 100)} inkl. mva.</strong> for selskapsåret {offer.incomeYear}.</p>
      <p className="fieldHelp">{money.format(offer.netMinor / 100)} ekskl. mva. + {money.format(offer.vatMinor / 100)} mva. ({offer.vatBasisPoints / 100} %).</p>
      <p>Tilgang til og med {calendarDate(offer.paidThrough)}. Lese- og eksporttilgang til og med {calendarDate(offer.exportThrough)}.</p>
      <details><summary>Les vilkårene for dette kjøpet</summary><p style={{ whiteSpace: "pre-wrap" }}>{offer.termsText}</p></details>
      <label className="checkboxRow"><input type="checkbox" name="purchaseAccepted" required disabled={pending} />
        Jeg har lest vilkårene og vil kjøpe selskapsåret for {money.format(offer.grossMinor / 100)} inkl. mva.</label>
      <label className="checkboxRow"><input type="checkbox" name="recurringConsent" disabled={pending} />
        Jeg ønsker automatisk fornyelse (valgfritt).</label>
      <p className="fieldHelp">Planlagt fornyelse {calendarDate(offer.renewalDate)}. Neste selskapsår må være godkjent før betaling.
        Du kan stoppe fornyelsen i kjøpshistorikken.</p>
      <Button type="submit" disabled={pending}>Kjøp selskapsåret – {money.format(offer.grossMinor / 100)}</Button>
    </form> : preparation?.state === "existing" && preparation.purchaseId ? <p>Det finnes allerede et kjøp for dette selskapsåret.
      <LinkButton href={annualCheckoutHistoryHref(companyId, preparation.purchaseId, beforePurchaseId ?? null)}>Se kjøpet</LinkButton></p>
      : <p>Betaling er ikke åpnet nå. Du kan fortsatt se og administrere tidligere kjøp.</p> : null}
  </section>;
}

"use client";

import { useState, useTransition } from "react";
import type { RfSourcePreviewWire, RfSourceProductionReviewWire, RfSourceProductionApprovalCommandWire } from "../../../../../features/shareholder-register-filing";
import { Banner } from "../../../../components/ui";
import { approveSourceProductionAction, reviewSourceProductionAction, type PriorFiling } from "./approval-actions";

const blockers: Record<string, string> = {
  preview_not_ready: "Forhåndsvisningen har forhold som må avklares.",
  filing_permission_required: "Innsendingsrett må bekreftes for selskapet.",
  hard_review_comment: "En blokkerende kommentar må avklares.",
  blocking_override: "En blokkerende overstyring må avklares.",
  stored_release_inputs_not_ready: "Årskontrollen er ikke klar. Kontroller bank, åpningsbalanse og årsopplysninger.",
  technical_release_not_ready: "Talli har ikke åpnet for produksjonsgodkjenning ennå.",
};

export function SourceApproval({ preview, onLockChange, busy }: { preview: RfSourcePreviewWire; onLockChange(locked: boolean): boolean; busy: boolean }) {
  const [review, setReview] = useState<RfSourceProductionReviewWire | null>(null);
  const [priorFilings, setPriorFilings] = useState<PriorFiling[]>([]);
  const [priorId, setPriorId] = useState("");
  const [reason, setReason] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [confirmed, setConfirmed] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [approved, setApproved] = useState(false);
  const [attempt, setAttempt] = useState<RfSourceProductionApprovalCommandWire | null>(null);
  const [pending, startTransition] = useTransition();
  function prepare() {
    startTransition(async () => {
      setMessage(null); setReview(null); setWarnings([]); setConfirmed(false); setPriorId(""); setReason("");
      try {
        const result = await reviewSourceProductionAction({ companyId: preview.companyId, incomeYear: preview.incomeYear,
          previewId: preview.previewId, sourceId: preview.sourceId, sourceSha256: preview.sourceSha256 });
        if (result.ok) { setReview(result.value.review); setPriorFilings(result.value.priorFilings); }
        else setMessage(result.message);
      } catch { setMessage("Kontrollen kunne ikke hentes. Prøv igjen."); }
    });
  }
  function approve() {
    if (!review || busy) return;
    const prior = priorFilings.find(row => row.submissionId === priorId);
    const command = attempt ?? { companyId: review.companyId, incomeYear: review.incomeYear,
      previewId: review.previewId, entitlementId: review.entitlementId, reviewSha256: review.reviewSha256,
      acknowledgedWarningCodes: warnings, realFilingConfirmed: confirmed,
      predecessor: prior ? { submissionId: prior.submissionId, manifestSha256: prior.manifestSha256, reason } : null };
    if (!onLockChange(true)) return;
    setAttempt(command);
    startTransition(async () => {
      setMessage(null);
      try {
        const result = await approveSourceProductionAction(command);
        if (result.ok) { setApproved(true); setAttempt(null); onLockChange(false); }
        else setMessage(result.message);
      } catch { setMessage("Svaret ble borte. Godkjenningen kan være lagret. Prøv samme godkjenning igjen."); }
    });
  }
  if (approved) return <Banner variant="info">Godkjenningen er lagret. Oppgaven er ikke sendt. Innsending av hele årsgrunnlaget er foreløpig ikke tilgjengelig.</Banner>;
  return <section className="wizardSection" aria-label="Godkjenning av årsgrunnlag">
    <h3>Godkjenn oppgaven</h3>
    <p>Kontroller forhåndsvisningen før du godkjenner. Innsending av hele årsgrunnlaget er foreløpig ikke tilgjengelig.</p>
    <button type="button" className="btn btn--secondary" disabled={busy || pending || attempt !== null}
      onClick={prepare}>{pending ? "Kontrollerer …" : "Kontroller vilkår for godkjenning"}</button>
    {message ? <div role="alert"><Banner variant="danger">{message}</Banner></div> : null}
    {review?.blockers.length ? <ul>{review.blockers.map(code => <li key={code}>{blockers[code] ?? "Et vilkår for godkjenning må avklares. Kontroller lagret status."}</li>)}</ul> : null}
    {review?.canApprove ? <fieldset disabled={busy || pending || attempt !== null} className="wizardForm"><legend>Din gjennomgang</legend>
      {review.warningCodes.map(code => <label className="checkRow" key={code}>
        <input type="checkbox" checked={warnings.includes(code)} onChange={e => { setConfirmed(false); setWarnings(values => e.target.checked ? [...values, code] : values.filter(value => value !== code)); }} />
        {preview.readinessIssues.find(issue => issue.code === code)?.message ?? "Kontroller advarselen i forhåndsvisningen før godkjenning."}
      </label>)}
      {priorFilings.length ? <><label className="field"><span className="fieldLabel">Oppgaven som skal erstattes</span>
        <select value={priorId} onChange={e => { setPriorId(e.target.value); setConfirmed(false); }}><option value="">Velg tidligere innsending</option>
          {priorFilings.map(row => <option key={row.submissionId} value={row.submissionId} disabled={!["accepted", "rejected"].includes(row.status)}>
            {row.createdAt} · {row.status === "accepted" ? "Godkjent" : row.status === "rejected" ? "Avvist" : "Må avklares før korrigering"}
          </option>)}</select></label>
        <label className="field"><span className="fieldLabel">Hvorfor skal oppgaven korrigeres?</span>
          <textarea value={reason} onChange={e => { setReason(e.target.value); setConfirmed(false); }} /></label></> : null}
      <label className="checkRow"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />
        Jeg har kontrollert hele oppgaven og godkjenner dette grunnlaget for en reell innsending.</label>
    </fieldset> : null}
    {review?.canApprove ? <button type="button" className="btn btn--primary" onClick={approve}
      disabled={busy || pending || (!attempt && (!confirmed || warnings.length !== review.warningCodes.length || (priorFilings.length > 0 && (!priorId || !reason.trim()))))}>
      {attempt ? "Prøv samme godkjenning igjen" : "Lagre godkjenning"}</button> : null}
    {attempt ? <p role="status">Resultatet er ikke bekreftet. Behold samme godkjenning ved nytt forsøk. Feltene og forhåndsvisningen er låst til resultatet er bekreftet.</p> : null}
  </section>;
}

"use client";

import { useState, useTransition } from "react";
import type { RfSourceProductionPositionWire } from "../../../../../features/shareholder-register-filing";
import { Banner } from "../../../../components/ui";
import { readSourceProductionPositionAction, sendSourceProductionAction, reconcileSourceProductionAction } from "./dispatch-actions";

const descriptions: Record<RfSourceProductionPositionWire["disposition"], string> = {
  unclaimed: "Godkjenningen er lagret. Oppgaven er ikke sendt fra denne godkjenningen.",
  current_admission_required: "Et innsendingsforsøk er lagret. Talli kontrollerer vilkårene før oppgaven fortsetter.",
  retry_admission_required: "Den siste operasjonen kan prøves igjen med samme godkjente oppgave. Vilkårene kontrolleres på nytt.",
  recovery_required: "En operasjon har ukjent utfall. Utfallet må avklares før innsendingen kan fortsette.",
  blocked: "Innsendingen er stanset. Den lagrede operasjonen tillater ikke et nytt forsøk.",
  current_approval_required: "Grunnlaget krever en ny gjennomgang og godkjenning før innsending.",
  confirmed: "Innsendingen er bekreftet mottatt. Se tilbakemeldingen for Skatteetatens behandling.",
};
const feedback: Record<string, string> = { sent: "Sendt", processing: "Under behandling", accepted: "Godkjent",
  rejected: "Avvist", action_required: "Krever oppfølging", unknown: "Utfallet er ukjent" };

export function SourceProduction({ companyId, incomeYear, approvals, artifacts }: { companyId: string; incomeYear: number;
  approvals: { id: string; approvedAt: string }[];
  artifacts: { id: string; submissionId: string; documentId: string; classification: string }[] }) {
  const [approvalId, setApprovalId] = useState(approvals[0]?.id ?? "");
  const [position, setPosition] = useState<RfSourceProductionPositionWire | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const scope = { companyId, incomeYear, approvalId };
  const canAttempt = position && ["unclaimed", "current_admission_required", "retry_admission_required"].includes(position.disposition);
  function read() {
    setPosition(null); setConfirmed(false); setMessage(null);
    startTransition(async () => {
      try {
        const result = await readSourceProductionPositionAction(scope);
        if (result.ok) setPosition(result.value); else setMessage(result.message);
      } catch { setMessage("Status kunne ikke hentes. Hent lagret status før du gjør noe mer."); }
    });
  }
  function send() {
    if (!position || !confirmed || pending || !canAttempt) return;
    const command = { ...scope, manifestSha256: position.manifestSha256, expectedHead: position.expectedHead, confirmed: true };
    setPosition(null); setConfirmed(false); setMessage(null);
    startTransition(async () => {
      try {
        const result = await sendSourceProductionAction(command);
        setMessage(result.ok ? "Innsendingen er bekreftet. Hent lagret status og tilbakemelding." : result.message);
      } catch { setMessage("Svaret ble borte. Oppgaven kan være sendt. Hent lagret status; ikke start en ny oppgave."); }
    });
  }
  function reconcile() {
    if (!position || position.disposition !== "confirmed" || pending) return;
    setMessage(null);
    startTransition(async () => {
      try {
        const result = await reconcileSourceProductionAction(scope);
        if (!result.ok) setMessage(result.message);
        else setMessage(result.value.errorCode ? "Tilbakemeldingen kunne ikke oppdateres. Kontroller lagret status."
          : `Tilbakemelding: ${feedback[result.value.state ?? "unknown"]}.`);
        const current = await readSourceProductionPositionAction(scope);
        if (current.ok) setPosition(current.value); else { setPosition(null); setMessage(current.message); }
      } catch { setPosition(null); setMessage("Tilbakemeldingen kunne ikke bekreftes. Hent lagret status."); }
    });
  }
  return <section id="innsending" className="wizardSection" aria-label="Innsending og status">
    <h2>Innsending og status</h2>
    {!approvals.length ? <p>Lag og kontroller en forhåndsvisning, og lagre en godkjenning før innsending.</p> : <>
      <label className="field"><span className="fieldLabel">Lagret godkjenning</span>
        <select value={approvalId} disabled={pending} onChange={e => { setApprovalId(e.target.value); setPosition(null); setConfirmed(false); setMessage(null); }}>
          {approvals.map(row => <option key={row.id} value={row.id}>{new Date(row.approvedAt).toLocaleString("nb-NO", { timeZone: "Europe/Oslo" })}</option>)}
        </select></label>
      <button type="button" className="btn btn--secondary" disabled={pending} onClick={read}>Hent lagret status</button>
      {position ? <p role="status">{descriptions[position.disposition]}{position.disposition === "confirmed" && position.feedbackState ? ` Status: ${feedback[position.feedbackState]}.` : ""}</p> : null}
      {position ? <details><summary>Se den godkjente forhåndsvisningen</summary>
        <p>Godkjent {new Date(position.approvedAt).toLocaleString("nb-NO", { timeZone: "Europe/Oslo" })}</p>
        <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{position.previewText}</pre></details> : null}
      {canAttempt ? <><label className="checkRow"><input type="checkbox" disabled={pending} checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />
        Jeg vil sende den lagrede, godkjente oppgaven til Skatteetaten.</label>
        <button type="button" className="btn btn--primary" disabled={pending || !confirmed} onClick={send}>
          {position?.disposition === "unclaimed" ? "Send godkjent oppgave" : "Fortsett samme innsending"}</button></> : null}
      {position?.disposition === "confirmed" ? <button type="button" className="btn btn--secondary" disabled={pending} onClick={reconcile}>Hent tilbakemelding</button> : null}
      {position?.disposition === "confirmed" ? <ul aria-label="Tilbakemeldingsdokumenter">
        {artifacts.filter(row => row.submissionId === position.submissionId).map(row => <li key={row.id}>
          <a href={`/documents/${encodeURIComponent(row.documentId)}/download`}>Tilbakemelding: {feedback[row.classification] ?? "Dokument"}</a>
        </li>)}</ul> : null}
    </>}
    {pending ? <p role="status">Behandler forespørselen …</p> : null}
    {message ? <div role="alert"><Banner variant="info">{message}</Banner></div> : null}
  </section>;
}

"use client";

import { useEffect, useRef, useState, useTransition, type ReactNode } from "react";
import type {
  RfCurrentYearSourceRecordWire, RfSourceIntakeBasisWire, RfSourcePreviewWire, RfSourceDocumentWire,
  RfYearSourceReceiptWire,
} from "../../../../../features/shareholder-register-filing/index.ts";
import { SourceApproval } from "./SourceApproval";
import { Banner } from "../../../../components/ui";
import { captureSourceAction, previewSourceAction, readSourceDocumentAction } from "./actions";
import {
  afterCaptureFailure, allocationFields, editSource, eventFields, eventLabels, newEvent, resetReview,
  shareFields, sourceCommand, type EventDraft, type EventKind, type SourceDraft, type SourceSaveAttempt,
} from "./model";

type Props = { basis: RfSourceIntakeBasisWire; current: RfCurrentYearSourceRecordWire | null;
  documentOptions: { id: string; name: string; incomeYear: number }[]; caseId: string };
function Field({ label, value, onChange, type = "text", count = false, required = true }: {
  label: string; value: string; onChange(value: string): void; type?: string; count?: boolean; required?: boolean;
}) {
  return <label className="field"><span className="fieldLabel">{label}</span>
    <input type={type} value={value} onChange={e => onChange(e.target.value)} required={required}
      step={type === "datetime-local" ? "1" : undefined} inputMode={count ? "numeric" : undefined} />
  </label>;
}
function Check({ children, checked, onChange }: { children: ReactNode; checked: boolean; onChange(value: boolean): void }) {
  return <label className="checkRow"><input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} />{children}</label>;
}
function toggle(ids: string[], id: string, selected: boolean) {
  return selected ? [...new Set([...ids, id])] : ids.filter(value => value !== id);
}
const statusLabels: Record<string, string> = {
  pending: "Venter på ferdigbehandling", finalized: "Ferdigbehandlet", rejected: "Avvist", superseded: "Erstattet",
  recorded: "Registrert", reversed: "Tilbakeført", corrected: "Korrigert", incomplete: "Ufullstendig", conflicting: "Må avklares",
};
function statusLabel(value: string) { return statusLabels[value] ?? "Må kontrolleres"; }
function eventLabel(value: string) { return eventLabels[value as EventKind] ?? "Kapitalhendelse"; }
function blockerLabel(code: string) {
  const labels: Record<string, string> = {
    rf1086_source_governance_receipt_invalid: "Beslutningen mangler entydig dokumentasjon på ferdigbehandling.",
    rf1086_source_governance_economics_invalid: "Beløp eller aksjefordeling i beslutningen må avklares.",
    rf1086_source_governance_unresolved: "En beslutning er ikke ferdigbehandlet.",
    rf1086_source_nominal_increase_unavailable: "Kapitalforhøyelse ved økt pålydende er foreløpig ikke klar for rapportering.",
  };
  return labels[code] ?? "En registrert beslutning eller rettelse må avklares i selskapsgrunnlaget.";
}
function governanceReceipts(basis: RfSourceIntakeBasisWire) {
  return [
    ...basis.dividends.flatMap(row => row.finalizations.map(final => ({ id: final.receiptId,
      label: `Utbytte ${row.reportingDate} · ${statusLabel(row.status)}`, documentIds: final.originalDocumentIds }))),
    ...basis.capitalEvents.map(row => {
      const representative = row.events.find(event => event.receiptId === row.representativeReceiptId);
      return { id: row.representativeReceiptId,
        label: `${eventLabel(representative?.eventKind ?? "")} ${representative?.reportingDate ?? ""} · ${statusLabel(row.status)}`,
        documentIds: [...new Set(row.events.flatMap(event => event.documents.map(doc => doc.documentId)))] };
    }),
  ];
}

export function SourceEditor({ basis, current, documentOptions, caseId }: Props) {
  const [draft, setDraft] = useState(() => editSource(basis, current?.draft ?? null, caseId));
  const [kind, setKind] = useState<EventKind>("formation");
  const [documentId, setDocumentId] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const [attempt, setAttempt] = useState<SourceSaveAttempt | null>(null);
  const [saved, setSaved] = useState<RfYearSourceReceiptWire | null>(null);
  const savedHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { if (saved) savedHeading.current?.focus(); }, [saved]);
  const [preview, setPreview] = useState<RfSourcePreviewWire | null>(null);
  const [approvalLocked, setApprovalLocked] = useState(false);
  const approvalLock = useRef(false);
  const sourceWork = useRef(false);
  function lockApproval(locked: boolean) {
    if (locked && sourceWork.current) return false;
    approvalLock.current = locked;
    setApprovalLocked(locked);
    return true;
  }
  function work(operation: () => Promise<void>) {
    if (approvalLock.current || sourceWork.current) return;
    sourceWork.current = true;
    startTransition(async () => { try { await operation(); } finally { sourceWork.current = false; } });
  }
  const [previewError, setPreviewError] = useState<string | null>(null);
  const receipt = saved ?? current?.receipt;
  const frozen = pending || attempt !== null || saved !== null || approvalLocked;
  const receipts = governanceReceipts(basis);
  function change(update: (value: SourceDraft) => SourceDraft) {
    if (approvalLock.current) return;
    setDraft(value => resetReview(update(value))); setMessage(null); setPreview(null);
  }
  function updateEvent(index: number, update: (event: EventDraft) => EventDraft) {
    change(value => ({ ...value, events: value.events.map((event, row) => row === index ? update(event) : event) }));
  }
  function documentName(id: string) { return documentOptions.find(doc => doc.id === id)?.name ?? `Dokument ${id}`; }
  function selectDocuments(ids: string[], onChange: (value: string[]) => void) {
    return <div className="wizardForm">{draft.documents.length ? draft.documents.map(doc =>
      <Check key={doc.documentId} checked={ids.includes(doc.documentId)} onChange={value => onChange(toggle(ids, doc.documentId, value))}>
        {documentName(doc.documentId)} · {doc.sourceIncomeYear}
      </Check>) : <p>Legg til dokumenter under «Dokumentasjon» først.</p>}</div>;
  }
  function addDocuments(ids: string[]) {
    work(async () => {
      const loaded: RfSourceDocumentWire[] = [];
      try {
      for (const id of [...new Set(ids)]) {
        const result = await readSourceDocumentAction(basis.companyId, id);
        if (!result.ok) { setMessage(result.message); return; }
        loaded.push(result.value);
      }
      change(value => ({ ...value, documents: [...value.documents.filter(doc => !ids.includes(doc.documentId)), ...loaded] }));
      } catch { setMessage("Dokumentopplysningene kunne ikke hentes. Prøv igjen."); }
    });
  }
  function capture() {
    if (approvalLock.current) return;
    let next = attempt;
    if (!next) {
      try { next = { command: sourceCommand(draft), key: crypto.randomUUID(), uncertain: false }; }
      catch (error) { setMessage(error instanceof Error ? error.message : "Kontroller feltene."); return; }
      setAttempt(next);
    }
    const submitted = next;
    work(async () => {
      setMessage(null);
      try {
      const result = await captureSourceAction(submitted.command, submitted.key);
      if (!result.ok) {
        setMessage(result.message);
        setAttempt(afterCaptureFailure(submitted, result.rejected));
        return;
      }
      setSaved(result.value); setAttempt(null); setPreview(null);
      } catch { setAttempt(afterCaptureFailure(submitted, false)); setMessage("Forbindelsen ble brutt. Lagringen kan ha blitt gjennomført. Prøv samme lagring igjen eller kontroller sist lagrede grunnlag."); }
    });
  }
  function generatePreview() {
    if (!receipt || approvalLock.current) return;
    work(async () => {
      setPreviewError(null); setPreview(null);
      try {
        const result = await previewSourceAction({ companyId: receipt.companyId, incomeYear: receipt.incomeYear, sourceId: receipt.sourceId });
        if (result.ok) setPreview(result.value); else setPreviewError(result.message);
      } catch { setPreviewError("Forhåndsvisningen kunne ikke hentes. Prøv igjen."); }
    });
  }
  const reloadHref = `/filing/aksjonaerregisteroppgaven/source?${new URLSearchParams({ companyId: basis.companyId, incomeYear: String(basis.incomeYear) })}`;
  return <div className="wizardForm">
    <Banner variant="info">Kontroller hele året, også aksjonærer som har solgt alle aksjene. Beløp oppgis i kroner, uten tusenskilletegn.
      Lagring oppretter et årsgrunnlag. Innsending krever en egen gjennomgang og godkjenning.</Banner>
    {receipt ? <section className="dataPanel" aria-label="Lagret årsgrunnlag">
      <h2 ref={savedHeading} tabIndex={-1}>{saved ? "Årsgrunnlaget er lagret" : "Gjeldende årsgrunnlag"}</h2>
      <p>Versjon {receipt.version} · lagret {receipt.confirmedAt}</p>
      <button type="button" className="btn btn--secondary" disabled={pending || approvalLocked} onClick={generatePreview}>Lag forhåndsvisning av lagret grunnlag</button>
      {saved ? <p><a href={reloadHref}>Åpne lagret grunnlag for en ny korrigering</a></p> : <p>Endringer nedenfor lagres som en ny versjon. Tidligere grunnlag beholdes.</p>}
    </section> : null}
    {previewError ? <Banner variant="danger">{previewError}</Banner> : null}
    {preview ? <section className="dataPanel" aria-label="Forhåndsvisning av årsgrunnlag">
      <h2>Forhåndsvisning · {preview.readinessStatus === "ready" ? "grunnlaget er kontrollert" : "må avklares"}</h2>
      <p>Dette gjelder det lagrede grunnlaget. Oppgaven er ikke sendt.</p>
      {preview.readinessIssues.length ? <ul>{preview.readinessIssues.map((issue, index) => <li key={index}>{issue.message}</li>)}</ul> : null}
      <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{preview.previewText}</pre>
      <details><summary>Innsendingsdokumenter</summary>
        <h3>Hovedskjema</h3><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{preview.hovedskjemaXml ?? "Ikke tilgjengelig"}</pre>
        {Object.entries(preview.underskjemaXml ?? {}).map(([id, xml]) => <details key={id}><summary>Aksjonær {draft.holders.find(h => h.id === id)?.name ?? id}</summary>
          <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{xml}</pre></details>)}
      </details>
      <SourceApproval key={preview.previewId} preview={preview} onLockChange={lockApproval} busy={pending} />
    </section> : null}
    <section className="dataPanel" aria-label="Registrerte selskapsbeslutninger">
      <h2>Registrerte beslutninger og rettelser</h2>
      <p><a className="btn btn--secondary" href={`/filing/aksjonaerregisteroppgaven/register?${new URLSearchParams({ companyId: basis.companyId, incomeYear: String(basis.incomeYear) })}`}>Åpne aksjeeierbok ved kapitalendring</a></p>
      <p>Kontroller disse mot hendelsene nedenfor. Datoen for rapportering kan høre til et annet år enn beslutningens årsgrunnlag.</p>
      {basis.blockers.length ? <Banner variant="danger">Registrerte forhold må avklares før årsgrunnlaget kan lagres.
        <ul>{basis.blockers.map(code => <li key={code}>{blockerLabel(code)}</li>)}</ul><a href="/actions">Se selskapsbeslutninger</a></Banner> : null}
      {!basis.dividends.length && !basis.capitalEvents.length && !basis.ledgerAmendments.length ? <p>Ingen slike beslutninger eller rettelser er registrert for rapporteringsåret. Kontroller også dine egne originaldokumenter.</p> : null}
      {basis.dividends.map(row => <details key={row.decisionId}><summary>Utbytte · {row.reportingDate} · {statusLabel(row.status)}</summary>
        <p>Beslutningsgrunnlag: {row.sourceIncomeYear}. Utbytte: {row.economics?.amount ?? "Mangler"} kr.</p>
        <ul>{row.economics?.allocations.map(a => <li key={a.shareholderId}>{draft.holders.find(h => h.id === a.shareholderId)?.name || a.shareholderId}: {a.amount} kr / {a.shareCountBasis} aksjer</li>)}</ul>
        {row.blockers.map(code => <p key={code}>{blockerLabel(code)}</p>)}
        <p><a href={`/corporate-decisions/${encodeURIComponent(row.decisionId)}`}>Åpne beslutningen og signerte dokumenter</a></p>
      </details>)}
      {basis.capitalEvents.map(row => <details key={row.representativeReceiptId}><summary>Kapitalhendelse · {statusLabel(row.status)}</summary>
        {row.events.map(event => <div key={event.receiptId}><p>{eventLabel(event.eventKind)} · {event.reportingDate} · årsgrunnlag {event.sourceIncomeYear}</p>
          <p>Registergrunnlag: {event.registerObservation ? `versjon ${event.registerObservation.revision}` : "mangler"}</p>
          {event.economics ? <dl>{Object.entries(event.economics).map(([key, value]) => <div key={key}><dt>{({ issuedShareCount: "Nye aksjer", newShareCapital: "Aksjekapital etter", oldShareCapital: "Aksjekapital før", nominalIncrease: "Kapitaløkning", nominalReduction: "Kapitalreduksjon", sharePremium: "Overkurs" } as Record<string, string>)[key] ?? key}</dt><dd>{value ?? "Mangler"}</dd></div>)}</dl> : null}
          {event.blockers.map(code => <p key={code}>{blockerLabel(code)}</p>)}</div>)}{row.blockers.map(code => <p key={code}>{blockerLabel(code)}</p>)}
      </details>)}
      {basis.ledgerAmendments.map(row => <p key={row.reversalEntryId}>Bokføringsrettelse for {row.sourceIncomeYear}: {row.reason}</p>)}
    </section>
    <form className="wizardForm" onSubmit={e => { e.preventDefault(); capture(); }}>
      <fieldset disabled={frozen} className="wizardSection"><legend>Selskap og aksjekapital</legend>
        <p>{draft.company.name} · {draft.company.orgNumber}<br />{draft.company.address}, {draft.company.postalCode} {draft.company.city}</p>
        <button type="button" className="btn btn--secondary" onClick={() => change(value => ({ ...value,
          company: { ...value.company, orgNumber: basis.company.orgNumber, name: basis.company.name, address: basis.company.address,
            postalCode: basis.company.postalCode, city: basis.company.city } }))}>Bruk gjeldende selskapsopplysninger</button>
        <label className="field"><span className="fieldLabel">Aksjeklasse</span><select required value={draft.company.shareType ?? ""}
          onChange={e => change(value => ({ ...value, company: { ...value.company, shareType: e.target.value } }))}>
          <option value="">Velg aksjeklasse</option><option value="01">Ordinære aksjer</option>
          {draft.company.shareType && draft.company.shareType !== "01" ? <option value={draft.company.shareType}>Tidligere verdi: {draft.company.shareType}</option> : null}
        </select></label>
        <Field label="E-post for kontakt (valgfritt)" type="email" required={false} value={draft.company.contactEmail ?? ""}
          onChange={contactEmail => change(value => ({ ...value, company: { ...value.company, contactEmail: contactEmail || null } }))} />
        <div className="fieldRow">{shareFields.map(field => <Field key={field.key} label={`${field.label}${field.count ? "" : " (kr)"}`}
          count={field.count} value={draft.shares[field.key] ?? ""} onChange={text => change(value => ({ ...value, shares: { ...value.shares, [field.key]: text } }))} />)}</div>
      </fieldset>
      <fieldset disabled={frozen} className="wizardSection"><legend>Aksjonærer gjennom året</legend>
        <p>Bruk samme aksjonærreferanse som i tidligere grunnlag og selskapsbeslutninger. Referansen skiller aksjonærene; fødselsnummer og organisasjonsnummer fylles ut separat.</p>
        {draft.holders.map((holder, index) => <fieldset className="wizardSection" key={index}><legend>Aksjonær {index + 1}</legend>
          <div className="fieldRow">
            <Field label="Aksjonærreferanse" value={holder.id} onChange={id => change(value => ({ ...value, holders: value.holders.map((h, row) => row === index ? { ...h, id } : h) }))} />
            <Field label="Navn" value={holder.name} onChange={name => change(value => ({ ...value, holders: value.holders.map((h, row) => row === index ? { ...h, name } : h) }))} />
            <label className="field"><span className="fieldLabel">Type aksjonær</span><select value={holder.kind} onChange={e => {
              const kind = e.target.value === "norwegian_company" ? "norwegian_company" : "norwegian_person";
              change(value => ({ ...value, holders: value.holders.map((h, row) => row === index ? { ...h, kind, identifier: "" } : h) }));
            }}><option value="norwegian_person">Norsk person</option><option value="norwegian_company">Norsk selskap</option></select></label>
            <Field label={holder.kind === "norwegian_person" ? "Fødselsnummer (11 siffer)" : "Organisasjonsnummer (9 siffer)"} count value={holder.identifier}
              onChange={identifier => change(value => ({ ...value, holders: value.holders.map((h, row) => row === index ? { ...h, identifier } : h) }))} />
            {(["previousShareCount", "currentShareCount"] as const).map(key => <Field key={key} label={key === "previousShareCount" ? "Aksjer ved årets start" : "Aksjer ved årets slutt"}
              count value={holder[key]} onChange={text => change(value => ({ ...value, holders: value.holders.map((h, row) => row === index ? { ...h, [key]: text } : h) }))} />)}
          </div><button type="button" className="btn btn--ghost" onClick={() => change(value => ({ ...value, holders: value.holders.filter((_, row) => row !== index) }))}>Fjern aksjonær {index + 1}</button>
        </fieldset>)}
        <button type="button" className="btn btn--secondary" onClick={() => change(value => ({ ...value, holders: [...value.holders,
          { id: crypto.randomUUID(), name: "", kind: "norwegian_person", identifier: "", previousShareCount: "", currentShareCount: "" }] }))}>Legg til aksjonær</button>
      </fieldset>
      <fieldset disabled={frozen} className="wizardSection"><legend>Dokumentasjon</legend>
        <p>Last opp originaler i <a href="/documents" target="_blank" rel="noreferrer">Dokumenter</a>, og last denne siden på nytt før du starter utfyllingen. Dokumenter fra tidligere år kan brukes som inngående grunnlag.</p>
        <label className="field"><span className="fieldLabel">Velg originaldokument</span><select value={documentId} onChange={e => setDocumentId(e.target.value)}>
          <option value="">Velg dokument</option>{documentOptions.map(doc => <option key={doc.id} value={doc.id}>{doc.name} · {doc.incomeYear}</option>)}
        </select></label>
        <button type="button" className="btn btn--secondary" disabled={!documentId} onClick={() => addDocuments([documentId])}>Hent dokumentopplysninger</button>
        {draft.documents.map(doc => <div key={doc.documentId}><p>{documentName(doc.documentId)} · {doc.sourceIncomeYear} · {doc.byteLength} byte</p>
          <button type="button" className="btn btn--ghost" onClick={() => addDocuments([doc.documentId])}>Oppdater dokumentopplysninger</button>
          <button type="button" className="btn btn--ghost" onClick={() => change(value => ({ ...value,
            documents: value.documents.filter(d => d.documentId !== doc.documentId), openingDocumentIds: value.openingDocumentIds.filter(id => id !== doc.documentId),
            closingDocumentIds: value.closingDocumentIds.filter(id => id !== doc.documentId), paidInDocumentIds: value.paidInDocumentIds.filter(id => id !== doc.documentId),
            events: value.events.map(e => ({ ...e, documentIds: e.documentIds.filter(id => id !== doc.documentId) })) }))}>Fjern dokument fra grunnlaget</button>
        </div>)}
        {([['openingDocumentIds', 'Grunnlag ved årets start'], ['closingDocumentIds', 'Grunnlag ved årets slutt'], ['paidInDocumentIds', 'Innbetalt kapital og overkurs']] as const).map(([key, label]) =>
          <fieldset className="wizardSection" key={key}><legend>{label}</legend>{selectDocuments(draft[key], ids => change(value => ({ ...value, [key]: ids })))}</fieldset>)}
      </fieldset>
      <fieldset disabled={frozen} className="wizardSection"><legend>Hendelser i tidsrekkefølge</legend>
        <p>Bruk dato og lokalt klokkeslett fra originalgrunnlaget. Hendelsene skal stå i stigende rekkefølge. Ta også med overdragelser uten endring i samlet aksjekapital.</p>
        {draft.events.map((event, index) => <fieldset className="wizardSection" key={event.key}><legend>{index + 1}. {eventLabels[event.type]}</legend>
          {event.type === "cash_nominal_increase" ? <Banner variant="info">Økt pålydende kan gjennomgås her, men kan foreløpig ikke lagres som et ferdig årsgrunnlag.</Banner> : null}
          <Field label="Dato og lokalt klokkeslett" type="datetime-local" value={event.timestamp} onChange={timestamp => updateEvent(index, e => ({ ...e, timestamp }))} />
          <div className="fieldRow">{eventFields[event.type].map(field => <Field key={field.key} label={`${field.label}${field.count ? "" : " (kr)"}`} count={field.count}
            value={event.values[field.key] ?? ""} onChange={text => updateEvent(index, e => ({ ...e, values: { ...e.values, [field.key]: text } }))} />)}</div>
          {event.type === "share_sale" ? ([['sellerShareholderId', 'Selger'], ['buyerShareholderId', 'Kjøper']] as const).map(([key, label]) => <label className="field" key={key}><span className="fieldLabel">{label}</span>
            <select required value={event.values[key] ?? ""} onChange={e => updateEvent(index, v => ({ ...v, values: { ...v.values, [key]: e.target.value } }))}>
              <option value="">Velg aksjonær</option>{draft.holders.map((h, row) => <option value={h.id} key={row}>{h.name || h.id}</option>)}
              {event.values[key] && !draft.holders.some(h => h.id === event.values[key]) ? <option value={event.values[key]}>Tidligere aksjonærreferanse – må kontrolleres</option> : null}
            </select></label>) : null}
          {allocationFields[event.type] ? <div className="wizardForm"><h3>Fordeling på aksjonærer</h3>
            {event.allocations.map((allocation, allocationIndex) => <fieldset className="wizardSection" key={allocationIndex}><legend>Fordeling {allocationIndex + 1}</legend>
              <label className="field"><span className="fieldLabel">Aksjonær</span><select required value={allocation.shareholderId} onChange={e => updateEvent(index, v => ({ ...v,
                allocations: v.allocations.map((a, i) => i === allocationIndex ? { ...a, shareholderId: e.target.value } : a) }))}>
                <option value="">Velg aksjonær</option>{draft.holders.map((h, row) => <option key={row} value={h.id}>{h.name || h.id}</option>)}
                {allocation.shareholderId && !draft.holders.some(h => h.id === allocation.shareholderId) ? <option value={allocation.shareholderId}>Tidligere aksjonærreferanse – må kontrolleres</option> : null}
              </select></label>
              {allocationFields[event.type]?.map(field => <Field key={field.key} label={`${field.label}${field.count ? "" : " (kr)"}`} count={field.count}
                value={allocation.values[field.key] ?? ""} onChange={text => updateEvent(index, v => ({ ...v, allocations: v.allocations.map((a, i) => i === allocationIndex ? { ...a, values: { ...a.values, [field.key]: text } } : a) }))} />)}
              <button type="button" className="btn btn--ghost" onClick={() => updateEvent(index, e => ({ ...e, allocations: e.allocations.filter((_, i) => i !== allocationIndex) }))}>Fjern fordeling {allocationIndex + 1}</button>
            </fieldset>)}
            <button type="button" className="btn btn--secondary" onClick={() => updateEvent(index, e => ({ ...e, allocations: [...e.allocations, { shareholderId: "", values: {} }] }))}>Legg til fordeling</button>
          </div> : null}
          {["cash_issue", "cash_nominal_increase", "loss_covering_reduction"].includes(event.type) ? <Check checked={event.registrationConfirmed}
            onChange={registrationConfirmed => updateEvent(index, e => ({ ...e, registrationConfirmed }))}>Registreringen i Foretaksregisteret er kontrollert mot originalen.</Check> : null}
          {!["formation", "share_sale"].includes(event.type) ? <>
            <label className="field"><span className="fieldLabel">Registrert beslutning</span><select required value={event.governanceReceiptId} onChange={e => updateEvent(index, v => ({ ...v, governanceReceiptId: e.target.value }))}>
              <option value="">Velg tilhørende beslutning</option>{receipts.map(row => <option key={row.id} value={row.id}>{row.label}</option>)}
              {event.governanceReceiptId && !receipts.some(r => r.id === event.governanceReceiptId) ? <option value={event.governanceReceiptId}>Tidligere beslutning – må kontrolleres</option> : null}
            </select></label>
            <button type="button" className="btn btn--secondary" disabled={!receipts.find(r => r.id === event.governanceReceiptId)?.documentIds.length}
              onClick={() => addDocuments(receipts.find(r => r.id === event.governanceReceiptId)?.documentIds ?? [])}>Hent beslutningens originaldokumenter</button>
          </> : null}
          <fieldset className="wizardSection"><legend>Dokumenter for denne hendelsen</legend>{selectDocuments(event.documentIds, documentIds => updateEvent(index, e => ({ ...e, documentIds })))}</fieldset>
          <div className="fieldRow"><button type="button" className="btn btn--ghost" disabled={index === 0} onClick={() => change(value => {
            const events = [...value.events]; [events[index - 1], events[index]] = [events[index], events[index - 1]]; return { ...value, events };
          })}>Flytt hendelse {index + 1} opp</button>
          <button type="button" className="btn btn--ghost" onClick={() => change(value => ({ ...value, events: value.events.filter((_, row) => row !== index) }))}>Fjern hendelse {index + 1}</button></div>
        </fieldset>)}
        <label className="field"><span className="fieldLabel">Ny hendelse</span><select value={kind} onChange={e => setKind(e.target.value as EventKind)}>
          {Object.entries(eventLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select></label>
        <button type="button" className="btn btn--secondary" onClick={() => change(value => ({ ...value, events: [...value.events, newEvent(kind, crypto.randomUUID())] }))}>Legg til hendelse</button>
      </fieldset>
      <fieldset disabled={frozen} className="wizardSection"><legend>Gjennomgang av hele året</legend>
        {draft.supersedesSourceId ? <Field label="Hvorfor korrigeres det tidligere årsgrunnlaget?" value={draft.correctionReason}
          onChange={correctionReason => change(value => ({ ...value, correctionReason }))} /> : null}
        <p>Endrer du opplysninger eller dokumenter, må gjennomgangen bekreftes på nytt.</p>
        <Check checked={draft.identitiesReviewed} onChange={identitiesReviewed => setDraft(value => ({ ...value, identitiesReviewed }))}>Jeg har kontrollert alle aksjonærnavn og identifikasjonsnumre.</Check>
        <Check checked={draft.completeYearConfirmed} onChange={completeYearConfirmed => setDraft(value => ({ ...value, completeYearConfirmed }))}>Jeg har kontrollert at hele året og alle hendelser er med.</Check>
        <Check checked={draft.paidInReviewed} onChange={paidInReviewed => setDraft(value => ({ ...value, paidInReviewed }))}>Jeg har kontrollert innbetalt aksjekapital og overkurs mot dokumentasjonen.</Check>
        {!draft.events.length ? <Check checked={draft.noActivityConfirmed} onChange={noActivityConfirmed => setDraft(value => ({ ...value, noActivityConfirmed }))}>Jeg bekrefter at det ikke var rapporteringspliktige hendelser i året.</Check> : null}
      </fieldset>
      {message ? <div role="alert"><Banner variant="danger">{message}</Banner></div> : null}
      {attempt && !pending ? <Banner variant="info">Lagringen er ikke bekreftet. Feltene beholdes uendret. Prøv samme lagring igjen, eller <a href={reloadHref}>åpne sist lagrede grunnlag</a> for å kontrollere resultatet.</Banner> : null}
      <button type="submit" className="btn btn--primary" disabled={approvalLocked || pending || saved !== null || !draft.identitiesReviewed || !draft.completeYearConfirmed || !draft.paidInReviewed || (!draft.events.length && !draft.noActivityConfirmed)}>
        {pending ? "Kontrollerer …" : attempt ? "Prøv samme lagring igjen" : draft.supersedesSourceId ? "Lagre korrigert årsgrunnlag" : "Lagre årsgrunnlag"}
      </button>
    </form>
  </div>;
}

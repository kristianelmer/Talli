"use client";
import { useEffect, useRef, useState, useTransition, type ReactNode } from "react";
import { Banner } from "../../../../components/ui";
import type { RfRegisterObservationRecordWire, RfRegisterObservationCaptureWire, RfRegisterObservationReceiptWire, RfSourceDocumentWire } from "../../../../../features/shareholder-register-filing";
import { readSourceDocumentAction } from "../source/actions";
import { afterCaptureFailure, type SaveAttempt } from "../source/model";
import { captureRegisterAction } from "./actions";
import { documentRoles, editRegister, registerCommand, registerKinds, resetRegisterReview,
  type DocumentRole, type RegisterDraft, type RegisterKind, type StateDraft } from "./model";
type Props = { companyId: string; incomeYear: number; current: RfRegisterObservationRecordWire | null;
  documentOptions: { id: string; name: string; incomeYear: number }[] };
function Field({ label, value, change, type = "text", count = false }: {
  label: string; value: string; change(value: string): void; type?: string; count?: boolean;
}) { return <label className="field"><span className="fieldLabel">{label}</span><input required type={type} value={value}
  step={type === "datetime-local" ? "1" : undefined} inputMode={count ? "numeric" : undefined} onChange={e => change(e.target.value)} /></label>; }
function Check({ children, checked, change }: { children: ReactNode; checked: boolean; change(value: boolean): void }) {
  return <label className="checkboxField"><input type="checkbox" checked={checked} onChange={e => change(e.target.checked)} /><span>{children}</span></label>;
}
export function RegisterEditor({ companyId, incomeYear, current, documentOptions }: Props) {
  const [draft, setDraft] = useState(() => editRegister(companyId, incomeYear, current?.draft ?? null));
  const [documentId, setDocumentId] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const [attempt, setAttempt] = useState<SaveAttempt<RfRegisterObservationCaptureWire> | null>(null);
  const [saved, setSaved] = useState<RfRegisterObservationReceiptWire | null>(null);
  const savedHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { if (saved) savedHeading.current?.focus(); }, [saved]);
  const historical = current !== null && !current.isCurrent;
  const frozen = pending || attempt !== null || saved !== null || historical;
  const base = `/filing/aksjonaerregisteroppgaven/register?${new URLSearchParams({ companyId, incomeYear: String(incomeYear) })}`;
  function change(update: (value: RegisterDraft) => RegisterDraft) { setDraft(value => resetRegisterReview(update(value))); setMessage(null); }
  function changeState(key: "before" | "after", update: (value: StateDraft) => StateDraft) { change(value => ({ ...value, [key]: update(value[key]) })); }
  const name = (id: string) => documentOptions.find(d => d.id === id)?.name ?? `Dokument ${id}`;
  function loadDocument(id: string) {
    startTransition(async () => {
      try {
        const result = await readSourceDocumentAction(companyId, id);
        if (!result.ok) { setMessage(result.message); return; }
        const doc: RfSourceDocumentWire = result.value;
        change(value => ({ ...value, documents: [...value.documents.filter(d => d.documentId !== id), doc] }));
      } catch { setMessage("Dokumentopplysningene kunne ikke hentes. Prøv igjen."); }
    });
  }
  function capture() {
    let next = attempt;
    if (!next) {
      try { next = { command: registerCommand(draft), key: crypto.randomUUID(), uncertain: false }; }
      catch (error) { setMessage(error instanceof Error ? error.message : "Kontroller feltene."); return; }
      setAttempt(next);
    }
    const submitted = next;
    startTransition(async () => {
      try {
        setMessage(null);
        const result = await captureRegisterAction(submitted.command, submitted.key);
        if (!result.ok) { setMessage(result.message); setAttempt(afterCaptureFailure(submitted, result.rejected)); return; }
        setSaved(result.value); setAttempt(null);
      } catch { setAttempt(afterCaptureFailure(submitted, false)); setMessage("Forbindelsen ble brutt. Kontroller lagret status, eller prøv samme lagring igjen."); }
    });
  }
  return <div className="wizardForm">
    <Banner variant="info">Dette grunnlaget dokumenterer én kapitalendring. Bruk originale aksjeeierbøker og registreringsdokumenter.
      Lagre grunnlaget før du bokfører kapitalhendelsen. Det erstatter ikke en selskapsbeslutning og sender ingen oppgave.</Banner>
    {historical ? <Banner variant="warning">Dette er en erstattet versjon. Velg gjeldende versjon i listen for å korrigere opplysningene.</Banner> : null}
    {saved ? <section className="dataPanel"><h2 ref={savedHeading} tabIndex={-1}>Registergrunnlaget er lagret</h2><p>Versjon {saved.version}. Velg dette grunnlaget når du registrerer kapitalhendelsen.</p>
      <a className="btn btn--primary" href="/actions/corporate-event">Åpne selskapshendelser</a>
      <p><a href={`${base}&observationId=${saved.observationId}`}>Åpne lagret grunnlag for kontroll eller korrigering</a></p>
      <details><summary>Referanse til det lagrede grunnlaget</summary><p style={{ overflowWrap: "anywhere" }}>{saved.observationId} · versjon {saved.version}<br />{saved.factSha256}</p></details>
    </section> : null}
    <form className="wizardForm" onSubmit={e => { e.preventDefault(); capture(); }}>
      <fieldset className="wizardSection" disabled={frozen}><legend>Kapitalendringen</legend>
        {current ? <p>{registerKinds[draft.eventKind]} · {draft.effectiveAt.replace("T", " ")}<br />Ved korrigering beholdes hendelsen og tidspunktet.</p> : <>
          <label className="field"><span className="fieldLabel">Type endring</span><select value={draft.eventKind} onChange={e => change(value => ({ ...value, eventKind: e.target.value as RegisterKind }))}>
            {Object.entries(registerKinds).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select></label>
          <Field label="Dato og lokalt klokkeslett for endringen" type="datetime-local" value={draft.effectiveAt} change={effectiveAt => change(value => ({ ...value, effectiveAt }))} />
        </>}
        {draft.eventKind === "cash_nominal_increase" ? <Banner variant="info">Du kan lagre registerdokumentasjonen. Videre behandling av økt pålydende i selskapsbeslutningen og årsgrunnlaget er foreløpig ikke tilgjengelig.</Banner> : null}
      </fieldset>
      {(["before", "after"] as const).map(key => <fieldset key={key} className="wizardSection" disabled={frozen}><legend>{key === "before" ? "Før kapitalendringen" : "Etter kapitalendringen"}</legend>
        {key === "after" ? <button type="button" className="btn btn--secondary" onClick={() => change(value => ({ ...value, after: structuredClone(value.before) }))}>Kopier inngående opplysninger til utgående utkast</button> : null}
        <div className="fieldRow">
          <Field label="Registrert aksjekapital (kr)" value={draft[key].shareCapital} change={shareCapital => changeState(key, value => ({ ...value, shareCapital }))} />
          <Field label="Pålydende per aksje (kr)" value={draft[key].nominalValue} change={nominalValue => changeState(key, value => ({ ...value, nominalValue }))} />
          <Field label="Samlet antall aksjer" count value={draft[key].shareCount} change={shareCount => changeState(key, value => ({ ...value, shareCount }))} />
        </div>
        <p>Ta med alle aksjonærer med aksjer på dette tidspunktet. Bruk samme aksjonærreferanse før og etter, og i årsgrunnlaget.</p>
        {draft[key].holdings.map((holder, index) => <fieldset className="wizardSection" key={index}><legend>Aksjonær {index + 1}</legend>
          <div className="fieldRow">
            <Field label="Aksjonærreferanse" value={holder.shareholderId} change={shareholderId => changeState(key, value => ({ ...value, holdings: value.holdings.map((h, i) => i === index ? { ...h, shareholderId } : h) }))} />
            <Field label="Navn" value={holder.name} change={name => changeState(key, value => ({ ...value, holdings: value.holdings.map((h, i) => i === index ? { ...h, name } : h) }))} />
            <label className="field"><span className="fieldLabel">Type aksjonær</span><select value={holder.kind} onChange={e => {
              const kind = e.target.value === "norwegian_company" ? "norwegian_company" : "norwegian_person";
              changeState(key, value => ({ ...value, holdings: value.holdings.map((h, i) => i === index ? { ...h, kind, identifier: "" } : h) }));
            }}><option value="norwegian_person">Norsk person</option><option value="norwegian_company">Norsk selskap</option></select></label>
            <Field label={holder.kind === "norwegian_person" ? "Fødselsnummer (11 siffer)" : "Organisasjonsnummer (9 siffer)"} count value={holder.identifier}
              change={identifier => changeState(key, value => ({ ...value, holdings: value.holdings.map((h, i) => i === index ? { ...h, identifier } : h) }))} />
            <Field label="Antall aksjer" count value={holder.shareCount} change={shareCount => changeState(key, value => ({ ...value, holdings: value.holdings.map((h, i) => i === index ? { ...h, shareCount } : h) }))} />
          </div><button type="button" className="btn btn--ghost" onClick={() => changeState(key, value => ({ ...value, holdings: value.holdings.filter((_, i) => i !== index) }))}>Fjern aksjonær {index + 1}</button>
        </fieldset>)}
        <button type="button" className="btn btn--secondary" onClick={() => changeState(key, value => ({ ...value, holdings: [...value.holdings,
          { shareholderId: crypto.randomUUID(), name: "", kind: "norwegian_person", identifier: "", shareCount: "" }] }))}>Legg til aksjonær</button>
      </fieldset>)}
      <fieldset className="wizardSection" disabled={frozen}><legend>Originaldokumenter</legend>
        <p>Bruk opplastede regnskaps- eller selskapsdokumenter knyttet til arbeidsområdet. Dokumenter generert fra denne rapporteringen er ikke uavhengige originaler.</p>
        <p><a href="/documents" target="_blank" rel="noreferrer">Last opp originaler i Dokumenter</a> før du starter utfyllingen, og last deretter denne siden på nytt.</p>
        <label className="field"><span className="fieldLabel">Velg dokument</span><select value={documentId} onChange={e => setDocumentId(e.target.value)}>
          <option value="">Velg original</option>{documentOptions.map(d => <option key={d.id} value={d.id}>{d.name} · {d.incomeYear}</option>)}
        </select></label>
        <button type="button" className="btn btn--secondary" disabled={!documentId} onClick={() => loadDocument(documentId)}>Hent dokumentopplysninger</button>
        {draft.documents.map(doc => <div key={doc.documentId}><p>{name(doc.documentId)} · {doc.sourceIncomeYear}</p>
          <button type="button" className="btn btn--ghost" onClick={() => loadDocument(doc.documentId)}>Oppdater dokumentopplysninger</button>
          <button type="button" className="btn btn--ghost" onClick={() => change(value => ({ ...value, documents: value.documents.filter(d => d.documentId !== doc.documentId),
            roles: { register_before: value.roles.register_before.filter(id => id !== doc.documentId), register_after: value.roles.register_after.filter(id => id !== doc.documentId), registration: value.roles.registration.filter(id => id !== doc.documentId) } }))}>Fjern dokument fra grunnlaget</button>
        </div>)}
        {(Object.keys(documentRoles) as DocumentRole[]).map(role => <fieldset className="wizardSection" key={role}><legend>{documentRoles[role]}</legend>
          {draft.documents.length ? draft.documents.map(doc => <Check key={doc.documentId} checked={draft.roles[role].includes(doc.documentId)} change={checked => change(value => ({ ...value,
            roles: { ...value.roles, [role]: checked ? [...new Set([...value.roles[role], doc.documentId])] : value.roles[role].filter(id => id !== doc.documentId) } }))}>{name(doc.documentId)} · {doc.sourceIncomeYear}</Check>) : <p>Hent dokumentopplysninger først.</p>}
        </fieldset>)}
      </fieldset>
      <fieldset className="wizardSection" disabled={frozen}><legend>Gjennomgang</legend>
        {current ? <Field label="Hvorfor korrigeres registergrunnlaget?" value={draft.correctionReason} change={correctionReason => change(value => ({ ...value, correctionReason }))} /> : null}
        <Check checked={draft.completeRegisterConfirmed} change={completeRegisterConfirmed => setDraft(value => ({ ...value, completeRegisterConfirmed }))}>Jeg har kontrollert alle aksjonærer, identifikasjonsnumre og aksjer før og etter endringen.</Check>
        <Check checked={draft.registrationConfirmed} change={registrationConfirmed => setDraft(value => ({ ...value, registrationConfirmed }))}>Jeg har kontrollert registreringen mot originaldokumentasjonen.</Check>
        <Check checked={draft.singleShareClassConfirmed} change={singleShareClassConfirmed => setDraft(value => ({ ...value, singleShareClassConfirmed }))}>Jeg bekrefter at det bare er én aksjeklasse.</Check>
      </fieldset>
      {message ? <Banner variant="danger">{message}</Banner> : null}
      {attempt && !pending ? <Banner variant="info">Lagringen er ikke bekreftet. Prøv samme lagring igjen, eller <a href={base}>kontroller alle lagrede registergrunnlag</a>.</Banner> : null}
      <button type="submit" className="btn btn--primary" disabled={pending || historical || saved !== null || !draft.completeRegisterConfirmed || !draft.registrationConfirmed || !draft.singleShareClassConfirmed}>
        {pending ? "Kontrollerer …" : attempt ? "Prøv samme lagring igjen" : current ? "Lagre korrigert registergrunnlag" : "Lagre registergrunnlag"}
      </button>
    </form>
  </div>;
}

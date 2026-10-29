import {randomUUID} from "node:crypto";
import {Banner,SubmitButton,LinkButton} from "../../components/ui";
import {getCurrentSessionAccessToken} from "../../lib/supabase/auth-session";
import {loadTaxDeliveryWorkspace,loadTaxDeliveryOwnerReview,companyTaxActionErrorMessage,taxDeliveryMfaRequired,
  type CompanyTaxDeliveryWorkspaceWire,type CompanyTaxDeliveryWorkspaceRowWire,type CompanyTaxOwnerReviewArtifactWire,
  type TaxDeliveryAction,type TaxDeliveryWorkspaceState} from "../../../features/company-tax-filing";
import {taxDeliveryOwnerAction} from "./_tax-delivery-actions";
import {TaxDeliveryFields} from "./_tax-delivery-fields";
import styles from "./_tax-delivery.module.css";

const states: Record<TaxDeliveryWorkspaceState,string>={prepared:"Utkast klart",legacy_prepared:"Tidligere utkast",reviewed:"Utkast bekreftet",
  creation_uncertain:"Oppretting er uavklart",created:"Levering opprettet",upload_uncertain:"Dokumentoverføring er uavklart",uploaded:"Dokumenter overført",
  validation_start_uncertain:"Valideringsstart er uavklart",validation_pending:"Venter på validering",validation_blocked:"Validering krever kontroll",
  validated:"Validering klar",confirmation_uncertain:"Kontrollsteget er uavklart",owner_review:"Klar for eierkontroll",
  submission_uncertain:"Innsendingsstatus er uavklart",submitted_receipt_pending:"Sendt – venter på kvittering",submitted_receipt_recorded:"Kvittering mottatt – venter på arkivering",submitted_receipted:"Sendt og kvittert"};
const actions: Record<TaxDeliveryAction,string>={approve:"Bekreft utkastet",create:"Opprett levering",upload:"Overfør dokumentene",
  reconcile_upload:"Kontroller dokumentoverføringen",validate:"Valider dokumentene",reconcile_validation:"Hent valideringen",
  prepare_confirmation:"Gjør klar eierkontroll",reconcile_confirmation:"Kontroller bekreftelsessteget",submit:"Bekreft og send",
  reconcile_submission:"Avklar innsendingsstatus",reconcile_feedback:"Hent kvittering",prepare_correction:"Kontroller og forbered korrigering"};
const originals: Record<string,string>={current:"Gjeldende skattemelding",draft_tax:"Skattemelding i utkastet",draft_business:"Næringsspesifikasjon i utkastet",
  draft_envelope:"Komplett dokumentpakke",finite_admission:"Testløpets avgrensning",instance:"Status og filkontroll",envelope:"Overført dokumentpakke",
  validation_job:"Valideringsstatus",validation_result:"Valideringsresultat med beregnede dokumenter",process_response:"Svar på prosessteg",
  feedback:"Kvittering",mutation_response:"Opprinnelig operasjonssvar",parent_instance:"Forgjengerens terminalstatus",parent_envelope:"Forgjengerens dokumentpakke",
  parent_feedback:"Forgjengerens kvittering",calculated_tax:"Beregnet skattemelding",calculated_business:"Beregnet næringsspesifikasjon",
  calculated_tax_computation:"Beregnet skatt",calculated_summary:"Oppsummering av skattegrunnlaget"};
const documentNames: Record<string,string>={skattemeldingUpersonligEtterBeregning:"Beregnet skattemelding",naeringsspesifikasjonEtterBeregning:"Beregnet næringsspesifikasjon",
  beregnetSkattUpersonlig:"Beregnet skatt",summertSkattegrunnlagForVisningUpersonlig:"Oppsummering av skattegrunnlaget"};
const noteNames: Record<string,string>={additional_info:"Tilleggsinformasjon",calculated_text:"Beregnet tekst",calculated_value:"Beregnet verdi",difference_value:"Differanse",
  occurrence_id:"Forekomst",path:"Felt",received_text:"Mottatt tekst",received_value:"Mottatt verdi",type_code:"Type",message:"Veiledning",servicing_strategy:"Oppfølging"};

function HiddenScope({workspace,row,action}: {workspace: CompanyTaxDeliveryWorkspaceWire;row?: CompanyTaxDeliveryWorkspaceRowWire;action: string}) {
  return <><input type="hidden" name="companyId" value={workspace.companyId}/><input type="hidden" name="incomeYear" value={workspace.incomeYear}/>
    <input type="hidden" name="deliveryAction" value={action}/>{row ? <input type="hidden" name="filingId" value={row.filingId}/> : null}</>;
}

function originalHref(workspace: CompanyTaxDeliveryWorkspaceWire,row: CompanyTaxDeliveryWorkspaceRowWire,key: string) {
  return "/api/company-tax/delivery-original?"+new URLSearchParams({companyId:workspace.companyId,incomeYear:String(workspace.incomeYear),filingId:row.filingId,key});
}

type ReviewResponse=Pick<CompanyTaxOwnerReviewArtifactWire["review"]["response"],"calculation_deviations"|"validation_deviations"|"guidance"|"failure_reasons"|"subject_flags">;
function ValidationDetails({response,responseOriginalSha256,documents,workspace,row}: {response: ReviewResponse;responseOriginalSha256: string;documents: CompanyTaxOwnerReviewArtifactWire["review"]["documents"];
    workspace: CompanyTaxDeliveryWorkspaceWire;row: CompanyTaxDeliveryWorkspaceRowWire}) {
  const responseOriginal=row.originals.find(value=>value.purpose==="validation_result" && value.sha256===responseOriginalSha256);
  const notes=[...response.calculation_deviations,...response.validation_deviations,...response.guidance];
  return <section aria-label="Valideringsresultat">
    <h3>Kontroller beregningen og merknadene</h3>
    <p className="cardNote">Les de beregnede dokumentene og alle merknadene før du bekrefter.</p>
    <p>{response.calculation_deviations.length} beregningsavvik · {response.validation_deviations.length} valideringsavvik · {response.guidance.length} veiledninger · {response.failure_reasons.length} feilårsaker</p>
    {notes.map((item,index)=><dl key={index} aria-label={"Merknad "+(index+1)}>{Object.entries(item).filter(([,value])=>value!==null).map(([name,value])=>
      <div key={name}><dt>{noteNames[name] ?? name}</dt><dd>{String(value ?? "") || "Tom verdi"}</dd></div>)}</dl>)}
    {response.failure_reasons.map((reason,index)=><p key={index}>{reason}</p>)}
    {response.subject_flags.length ? <details><summary>Selskapsopplysninger fra beregningen ({response.subject_flags.length})</summary>
      <TaxDeliveryFields label="Selskapsopplysninger fra beregningen" fields={response.subject_flags.map(flag=>({path:flag.name,value:flag.value?"True":"False"}))}/>
    </details> : null}
    {documents.map(document=>{
      const original=row.originals.find(original=>original.sha256===document.original_sha256 && original.purpose.startsWith("calculated_"));
      return <details key={row.filingId+":"+document.document_type+":"+document.original_sha256}>
        <summary>{documentNames[document.document_type] ?? document.document_type} ({document.fields.length} felt)</summary>
        {original ? <a href={originalHref(workspace,row,original.key)}>Last ned dokumentets original</a> : responseOriginal ?
          <a href={originalHref(workspace,row,responseOriginal.key)}>Last ned valideringsoriginalen</a> : null}
        <TaxDeliveryFields label={documentNames[document.document_type] ?? document.document_type} fields={document.fields}/>
      </details>;
    })}
  </section>;
}

function OwnerReview({artifact,workspace,row}: {artifact: CompanyTaxOwnerReviewArtifactWire;workspace: CompanyTaxDeliveryWorkspaceWire;row: CompanyTaxDeliveryWorkspaceRowWire}) {
  return <section aria-label="Eierkontroll av beregnede dokumenter">
    <ValidationDetails responseOriginalSha256={artifact.review.response.inspection.original_sha256} response={artifact.review.response} documents={artifact.review.documents} workspace={workspace} row={row}/>
    {row.actions.includes("submit") ? <form action={taxDeliveryOwnerAction} key={artifact.artifactSha256}>
      <HiddenScope workspace={workspace} row={row} action="submit"/>
      <input type="hidden" name="ownerReviewSha256" value={artifact.artifactSha256}/>
      <label><input type="checkbox" name="documentsConfirmed" required/>Jeg har kontrollert de beregnede dokumentene.</label>
      <label><input type="checkbox" name="warningsAcknowledged" required/>Jeg har lest og tatt stilling til alle merknadene.</label>
      <SubmitButton pendingLabel="Bekrefter…">Bekreft og send</SubmitButton>
    </form> : null}
  </section>;
}

export async function TaxDeliveryPanel({companyId,incomeYear}: {companyId: string;incomeYear: number}) {
  if (incomeYear!==2025) return null;
  const token=await getCurrentSessionAccessToken();
  if (!token) return null;
  let workspace: CompanyTaxDeliveryWorkspaceWire;
  try {workspace=await loadTaxDeliveryWorkspace(token,companyId,incomeYear);}
  catch (error) {return <section className="filingStep"><div className="filingStepHead"><h2 className="filingStepTitle">Levering av skattemeldingen</h2></div>
    <div className="filingStepBody"><Banner variant="warning">Leveringsstatus er ikke tilgjengelig. {companyTaxActionErrorMessage(error)}</Banner>
      {taxDeliveryMfaRequired(error) ? <LinkButton href="/mfa?fresh=1&next=%2Ffiling%2Fskattemelding" variant="secondary">Bekreft identiteten</LinkButton> : <LinkButton href="/filing/skattemelding" variant="secondary">Oppdater status</LinkButton>}</div></section>;}
  const reviews=new Map<string,CompanyTaxOwnerReviewArtifactWire>();
  await Promise.all(workspace.rows.filter(row=>row.state==="owner_review" && row.approvalSha256).map(async row=>{
    try {reviews.set(row.filingId,await loadTaxDeliveryOwnerReview(token,companyId,incomeYear,row.filingId,row.approvalSha256!));} catch { /* The absent artifact disables its confirmation form. */ }
  }));
  return <div className={styles.panel} data-tax-delivery="workspace">
    <section className="filingStep"><div className="filingStepHead"><h2 className="filingStepTitle">Levering av skattemeldingen</h2></div>
      <div className="filingStepBody">
        {workspace.technicalMode==="finite_loopback" ? <Banner variant="info">Prøveløp. Leveringen behandles i et avgrenset testmiljø.</Banner> :
          <p className="cardNote">Videre levering er ikke tilgjengelig nå. Lagrede dokumenter kan fortsatt leses.</p>}
        {workspace.preparationAvailable ? <form action={taxDeliveryOwnerAction}>
          <HiddenScope workspace={workspace} action="prepare"/><input type="hidden" name="candidateId" value={randomUUID()}/>
          <SubmitButton pendingLabel="Henter og forbereder…">Forbered skattemeldingen</SubmitButton>
        </form> : null}
        {!workspace.rows.length ? <p className="cardNote">Ingen utkast er lagret i dette leveringsløpet.</p> : null}
      </div>
    </section>
    {workspace.rows.toReversed().map(row=><section className="filingStep" key={row.filingId} data-tax-filing={row.filingId}>
      <div className="filingStepHead"><h2 className="filingStepTitle">{states[row.state]}</h2></div>
      <div className="filingStepBody">
        <p className={styles.reference}>Levering <code>{row.filingId}</code>{row.parentFilingId ? <> · Korrigerer <code>{row.parentFilingId}</code></> : null}</p>
        {!row.sourceCurrent ? <Banner variant="warning">Tallgrunnlaget har endret seg siden dette utkastet ble lagret.</Banner> : null}
        {row.state==="creation_uncertain" || row.state==="validation_start_uncertain" ? <Banner variant="warning">Status må avklares før en ny levering kan starte.</Banner> : null}
        {row.state==="submitted_receipted" ? <p className="cardNote">Kvitteringen gjelder den tekniske leveringen.</p> : null}
        <details open={row.state==="prepared"}><summary>Felt i utkastet ({row.fields.length})</summary>
          <TaxDeliveryFields label="Felt i utkastet" fields={row.fields.map(field=>({path:field.document+" · "+field.path,value:field.value}))}/>
        </details>
        {row.state==="validation_blocked" && !row.validation ? <Banner variant="warning">Det lagrede valideringssvaret kunne ikke tolkes fullstendig. Last ned originalen for kontroll. Innsending er ikke tilgjengelig.</Banner> : null}
        {row.state!=="owner_review" && row.validation ? <>
          {!row.validation.documentsAvailable ? <Banner variant="warning">De beregnede dokumentene kunne ikke tolkes fullstendig. Last ned valideringsoriginalen for kontroll. Innsending er ikke tilgjengelig.</Banner> : null}
          <ValidationDetails responseOriginalSha256={row.validation.originalSha256} response={{calculation_deviations:row.validation.calculationDeviations,validation_deviations:row.validation.validationDeviations,
            guidance:row.validation.guidance,failure_reasons:row.validation.failureReasons,subject_flags:row.validation.subjectFlags}}
            documents={row.validation.documents} workspace={workspace} row={row}/>
        </> : null}
        {row.state==="owner_review" ? reviews.has(row.filingId) ? <OwnerReview artifact={reviews.get(row.filingId)!} workspace={workspace} row={row}/> :
          <Banner variant="warning">Den komplette eierkontrollen kunne ikke leses. Bekreftelse er ikke tilgjengelig.</Banner> : null}
        <div className={styles.actions}>{row.actions.filter(action=>action!=="submit").map(action=><form action={taxDeliveryOwnerAction} key={action}>
          <HiddenScope workspace={workspace} row={row} action={action}/>
          {action==="prepare_correction" ? <input type="hidden" name="candidateId" value={randomUUID()}/> : null}
          <SubmitButton variant={action==="prepare_correction"?"secondary":"primary"} pendingLabel="Kontrollerer…">{row.state==="submitted_receipt_recorded" && action==="reconcile_feedback" ? "Kontroller arkivering" : actions[action]}</SubmitButton>
        </form>)}</div>
        <details><summary>Originale dokumenter og svar ({row.originals.length})</summary><ul className={styles.originals}>
          {row.originals.map(original=><li key={original.key}><a href={originalHref(workspace,row,original.key)}>
            {originals[original.purpose] ?? original.purpose} · {original.sha256.slice(0,8)}</a></li>)}
        </ul></details>
      </div>
    </section>)}
  </div>;
}

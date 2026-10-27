import {randomUUID} from "node:crypto";
import {Banner,SubmitButton,LinkButton} from "../../components/ui";
import {getCurrentSessionAccessToken} from "../../lib/supabase/auth-session";
import {loadAccountsDeliveryWorkspace,annualAccountsActionErrorMessage,accountsDeliveryMfaRequired,
  type AccountsDeliveryWorkspaceWire,type AccountsDeliveryWorkspaceRowWire} from "../../../features/annual-accounts-filing";
import {accountsDeliveryOwnerAction} from "./_accounts-delivery-actions";
import {TaxDeliveryFields} from "./_tax-delivery-fields";
import styles from "./_tax-delivery.module.css";
import accountsStyles from "./_accounts-delivery.module.css";

const states: Record<AccountsDeliveryWorkspaceRowWire["state"],string>={draft:"Utkast klart",reviewed:"Utkast kontrollert",
  creation_unknown:"Oppretting er uavklart",created:"Levering opprettet",main_upload_unknown:"Hovedskjemaets overføring er uavklart",
  main_uploaded:"Hovedskjema kontrollert",accounts_upload_unknown:"Regnskapsdokumentets overføring er uavklart",validation_blocked:"Validering krever kontroll",
  confirmation_review:"Klar for dokumentkontroll",confirmation_unknown:"Bekreftelsessteget er uavklart",person_review:"Klar for personens signeringskontroll",
  signing_unknown:"Signeringssteget er uavklart",technical_archive:"Teknisk arkivering bekreftet",inspection_unavailable:"Dokumentkontrollen er utilgjengelig"};
const actions: Record<AccountsDeliveryWorkspaceRowWire["actions"][number],string>={review_prepare:"Bekreft utkastet",review_confirm:"Bekreft dokumentkontrollen",
  review_sign:"Bekreft signeringskontrollen",create_instance:"Opprett levering",upload_main_form:"Overfør hovedskjema",upload_company_accounts:"Overfør regnskapsdokumentet",
  confirm:"Gå videre til signering",sign:"Utfør personens signeringssteg",reconcile:"Hent og kontroller status"};
const names: Record<string,string>={prepared_draft:"Lagret utkast",prepared_source:"Tallgrunnlag og beslutninger",prepared_main:"Hovedskjema i utkastet",
  prepared_accounts:"Regnskapsdokument i utkastet",operation_record:"Operasjonsoriginal",instance:"Status og filreferanser",main_form:"Hovedskjema fra leveringen",
  company_accounts:"Regnskapsdokument fra leveringen",validation:"Valideringsoriginal",pdf:"Generert PDF",signature:"Signaturoriginal"};

function Scope({workspace,row,action}: {workspace: AccountsDeliveryWorkspaceWire;row?: AccountsDeliveryWorkspaceRowWire;action: string}) {
  return <><input type="hidden" name="companyId" value={workspace.companyId}/><input type="hidden" name="incomeYear" value={workspace.incomeYear}/>
    <input type="hidden" name="deliveryAction" value={action}/>{row ? <input type="hidden" name="filingId" value={row.filingId}/> : null}</>;
}

function href(workspace: AccountsDeliveryWorkspaceWire,row: AccountsDeliveryWorkspaceRowWire,key: string) {
  return "/api/annual-accounts/delivery-original?"+new URLSearchParams({companyId:workspace.companyId,incomeYear:String(workspace.incomeYear),filingId:row.filingId,key});
}

export async function AccountsDeliveryPanel({companyId,incomeYear}: {companyId: string;incomeYear: number}) {
  if (incomeYear!==2025) return null;
  const token=await getCurrentSessionAccessToken();if (!token) return null;
  let workspace: AccountsDeliveryWorkspaceWire;
  try {workspace=await loadAccountsDeliveryWorkspace(token,companyId,incomeYear);}
  catch (error) {return <section className="filingStep"><div className="filingStepHead"><h2 className="filingStepTitle">Levering av årsregnskapet</h2></div>
    <div className="filingStepBody"><Banner variant="warning">Leveringsstatus er ikke tilgjengelig. {annualAccountsActionErrorMessage(error)}</Banner>
      {accountsDeliveryMfaRequired(error) ? <LinkButton href="/mfa?next=%2Ffiling%2Faarsregnskap" variant="secondary">Bekreft identiteten</LinkButton> :
        <LinkButton href="/filing/aarsregnskap" variant="secondary">Oppdater status</LinkButton>}</div></section>;}
  return <div className={styles.panel} data-accounts-delivery="workspace">
    <section className="filingStep"><div className="filingStepHead"><h2 className="filingStepTitle">Levering av årsregnskapet</h2></div>
      <div className="filingStepBody">
        {workspace.preparationAvailable || workspace.rows.some(row=>row.actions.length) ? <Banner variant="info">Prøveløp. Leveringen behandles i et avgrenset testmiljø.</Banner> :
          <p className="cardNote">Videre levering er ikke tilgjengelig nå. Lagrede dokumenter kan fortsatt leses.</p>}
        {workspace.preparationAvailable ? <form action={accountsDeliveryOwnerAction}>
          <Scope workspace={workspace} action="prepare"/><input type="hidden" name="candidateId" value={randomUUID()}/>
          <label className={accountsStyles.inputLabel}>Kontaktadresse<input className={accountsStyles.input} type="email" name="contactEmail" autoComplete="email" required maxLength={1000}/></label>
          <label className={accountsStyles.inputLabel}>Bekreftende representant<input className={accountsStyles.input} name="confirmingRepresentative" autoComplete="name" required maxLength={1000}/></label>
          <SubmitButton pendingLabel="Henter og forbereder…">Forbered årsregnskapet</SubmitButton>
        </form> : null}
        {!workspace.rows.length ? <p className="cardNote">Ingen utkast er lagret i dette leveringsløpet.</p> : null}
      </div>
    </section>
    {workspace.rows.toReversed().map(row=><section className="filingStep" key={row.filingId} data-accounts-filing={row.filingId}>
      <div className="filingStepHead"><h2 className="filingStepTitle">{states[row.state]}</h2></div>
      <div className="filingStepBody">
        <p className={styles.reference}>Levering <code>{row.filingId}</code></p>
        {!row.sourceCurrent ? <Banner variant="warning">Tallgrunnlaget har endret seg eller kan ikke leses nå. Nye leveringssteg er stengt.</Banner> : null}
        {row.state==="creation_unknown" ? <Banner variant="warning">Opprettingen må avklares før en ny levering kan starte.</Banner> : null}
        {row.state==="technical_archive" ? <p className="cardNote">Statusen viser teknisk arkivering i prøveløpet.</p> : null}
        {row.state==="inspection_unavailable" ? <Banner variant="warning">Dokumentkontrollen kan ikke verifiseres nå. Originalene er fortsatt tilgjengelige.</Banner> : null}
        <details open={row.state==="draft"}><summary>Alle felt i dokumentene ({row.fields.length})</summary>
          <TaxDeliveryFields key={row.draftSha256} label="Felt i årsregnskapet" fields={row.fields.map(field=>({path:field.document+" · "+field.path,value:field.value}))}/>
        </details>
        {row.validationIssues.length ? <section aria-label="Alle valideringsmerknader"><h3>Valideringsmerknader</h3><ul className={accountsStyles.issues}>
          {row.validationIssues.map((issue,index)=><li key={index}><dl>{Object.entries(issue).map(([name,value])=><div key={name}><dt>{name}</dt><dd>{typeof value==="object"?JSON.stringify(value):String(value ?? "")}</dd></div>)}</dl></li>)}
        </ul></section> : null}
        {row.originals.some(original=>original.purpose==="pdf") ? <section aria-label="Genererte PDF-dokumenter"><h3>Kontroller PDF-dokumentene</h3>
          <ul className={styles.originals}>{row.originals.filter(original=>original.purpose==="pdf").map(original=><li key={original.key}>
            <a href={href(workspace,row,original.key)}>Last ned PDF · {original.sha256.slice(0,8)}</a></li>)}</ul></section> : null}
        <div className={styles.actions}>{row.actions.map(action=><form action={accountsDeliveryOwnerAction} key={row.reviewSha256+":"+action}>
          <Scope workspace={workspace} row={row} action={action}/>
          {action==="review_prepare" || action==="review_confirm" || action==="review_sign" ? <>
            <input type="hidden" name="reviewSha256" value={row.reviewSha256}/>
            <label><input type="checkbox" name="documentsChecked" required/>Jeg har kontrollert dokumentene og alle merknadene.</label>
            <label><input type="checkbox" name="actionConfirmed" required/>{action==="review_sign"?"Jeg vil utføre personens signeringssteg for denne leveringen.":
              action==="review_confirm"?"Jeg vil gå videre til signering av disse dokumentene.":"Jeg vil opprette leveringen med dette utkastet."}</label>
          </> : null}
          <SubmitButton variant={action==="reconcile"?"secondary":"primary"} pendingLabel="Kontrollerer…">{actions[action]}</SubmitButton>
        </form>)}</div>
        <details><summary>Originale dokumenter og svar ({row.originals.length})</summary><ul className={styles.originals}>
          {row.originals.map(original=><li key={original.key}><a href={href(workspace,row,original.key)}>{names[original.purpose] ?? original.purpose} · {original.sha256.slice(0,8)}</a></li>)}
        </ul></details>
      </div>
    </section>)}
  </div>;
}

import { randomUUID } from "node:crypto";

import {
  recordLaunchSignoff,
  reviewCompanyDeletion,
  runProductionAuthorityOperation,
  runProductionSystembrukerCallbackOperation,
  upsertProductionPilotEntitlement,
} from "../../actions";
import { operatorAuthorityCopy } from "../../lib/copy";
import {
  buildLaunchSignoffGate,
  launchSignoffKeys,
  launchSignoffLabel,
} from "../../lib/launch-signoff";
import {
  getCurrentUser,
  listAuthorityOperations,
  listLaunchSignoffs,
  searchOperatorSupportDashboard,
} from "../../lib/supabase/server";
import { OperatorMfa } from "./operator-mfa";

type OperatorProps = {
  searchParams?: Promise<{
    operatorOrg?: string;
    error?: string;
    pilot?: string;
    authority?: string;
  }>;
};

const authorityResultMessages: Record<string, string> = {
  created_and_verified: "Systemet ble opprettet og verifisert i produksjon.",
  already_verified: "Systemet finnes allerede og samsvarer med den faste definisjonen.",
  callback_already_verified: "Den faste Systembruker-callbacken er allerede verifisert.",
  callback_updated_and_verified: "Den faste Systembruker-callbacken ble lagt til og verifisert.",
  definition_conflict: "Eksisterende system avviker. Ingen overskriving ble utført.",
  authority_ops_disabled: "Produksjonsoperasjoner er deaktivert.",
  authority_step_up_required: "Fersk AAL2/MFA kreves før operasjonen kan kjøres.",
  authority_step_up_failed: "AAL2/MFA-kontrollen kunne ikke fullføres.",
  authority_operation_invalid: "Operasjonen eller bekreftelsesfrasen var ugyldig.",
  admin_operator_required: "Aktiv admin-operatør kreves.",
  authority_environment_invalid: "Produksjonsmiljøet er ugyldig konfigurert.",
  authority_client_id_invalid: "Maskinporten-klient-ID-en er ugyldig.",
  authority_key_id_invalid: "Maskinporten-nøkkel-ID-en er ugyldig.",
  authority_private_key_invalid: "Maskinporten-privatnøkkelen er ugyldig.",
  authority_audit_unavailable: "Revisjonsloggen er ikke tilgjengelig.",
  authority_audit_start_failed: "Operasjonen ble ikke startet fordi revisjonsloggen feilet.",
  authority_audit_completion_failed: "Resultatet kunne ikke ferdigstilles i revisjonsloggen.",
  authority_token_error: "Maskinporten-token kunne ikke hentes.",
  authority_network_error: "Nettverkskallet til Altinn feilet.",
  authority_http_error: "Altinn avviste operasjonen.",
  authority_response_invalid: "Altinn returnerte et ugyldig svar.",
  authority_verification_error: "Systemregister-resultatet kunne ikke verifiseres med en ny avlesning.",
  authority_operation_failed: "Produksjonsoperasjonen feilet.",
  authority_mfa_ready: "AAL2 er aktiv for denne operatørøkten.",
};

export default async function OperatorPage({ searchParams }: OperatorProps) {
  const params = await searchParams;
  const user = await getCurrentUser();
  const operatorSearch = params?.operatorOrg ?? "";
  const operatorDashboard = operatorSearch
    ? await searchOperatorSupportDashboard(operatorSearch, user?.id)
    : { summaries: [], isOperator: false, error: null };
  const launchSignoffState = user
    ? await listLaunchSignoffs(user.id)
    : { launchSignoffs: [], isOperator: false, isAdminOperator: false, error: null };
  const authorityState = user
    ? await listAuthorityOperations(user.id)
    : { operations: [], isAdminOperator: false, error: null };
  const authorityOpsEnabled = process.env.TALLI_AUTHORITY_OPS_ENABLED === "true";
  const launchSignoffGate = buildLaunchSignoffGate({
    signoffs: launchSignoffState.launchSignoffs.map((signoff) => ({
      key: signoff.key,
      status: signoff.status,
      reviewer: signoff.reviewer,
      reviewedAt: signoff.reviewed_at,
      evidenceLink: signoff.evidence_link,
      decision: signoff.decision,
    })),
  });
  return (
    <>
      <div className="pageHead">
        <h1 className="pageTitle">Operatør</h1>
        <p className="pageLede">
          Supportstatus og launch sign-off. Kun for aktive operatører.
        </p>
      </div>
      <section className="band">
        <div className="sectionHeader">
          <p className="eyebrow">Operator</p>
          <h2>Supportstatus uten muterende snarveier.</h2>
        </div>
        {params?.error ? <p className="errorText">{params.error}</p> : null}
        {params?.pilot === "updated" ? <p className="successText">Produksjonspiloten er oppdatert.</p> : null}
        {params?.authority ? (
          <p className={[
            "created_and_verified",
            "already_verified",
            "callback_already_verified",
            "callback_updated_and_verified",
          ].includes(params.authority) ? "successText" : "errorText"}>
            {authorityResultMessages[params.authority] ?? "Ukjent resultat fra produksjonsoperasjonen."}
          </p>
        ) : null}
        <form className="dataPanel formPanel widePanel" method="get">
          <label>
            Org.nr eller navn
            <input name="operatorOrg" defaultValue={operatorSearch} placeholder="314259521" />
          </label>
          <button className="secondaryButton" type="submit">
            Søk
          </button>
        </form>
        {operatorDashboard.error ? <p className="errorText">{operatorDashboard.error}</p> : null}
        {launchSignoffState.error ? <p className="errorText">{launchSignoffState.error}</p> : null}
        {launchSignoffState.isOperator ? (
          <>
            <div className="readinessGrid">
              <div className="readinessItem">
                <span>Launch signoff</span>
                <strong data-status={launchSignoffGate.ready ? "ready" : "warning"}>{launchSignoffGate.status}</strong>
                <p>{launchSignoffGate.messages[0] ?? "Alle launch signoffs er godkjent."}</p>
                <p>Mangler: {launchSignoffGate.missing.length}</p>
                <p>Avvist: {launchSignoffGate.rejected.length}</p>
                <p>Utdatert: {launchSignoffGate.stale.length}</p>
              </div>
              {launchSignoffKeys.map((key) => {
                const signoff = launchSignoffState.launchSignoffs.find((item) => item.key === key);
                return (
                  <div className="readinessItem" key={key}>
                    <span>{launchSignoffLabel(key)}</span>
                    <strong data-status={signoff?.status === "approved" ? "ready" : signoff ? "warning" : "draft"}>
                      {signoff?.status ?? "pending"}
                    </strong>
                    <p>Reviewer: {signoff?.reviewer || "Mangler"}</p>
                    <p>Dato: {signoff?.reviewed_at ? new Date(signoff.reviewed_at).toLocaleString("nb-NO") : "Mangler"}</p>
                    <p>{signoff?.decision || "Ingen beslutning registrert."}</p>
                    {signoff?.evidence_link ? <a href={signoff.evidence_link}>Evidens</a> : null}
                  </div>
                );
              })}
            </div>
            {launchSignoffState.isAdminOperator ? (
              <>
              {process.env.SUPABASE_URL && process.env.SUPABASE_ANON_KEY ? (
                <OperatorMfa
                  supabaseUrl={process.env.SUPABASE_URL}
                  supabaseAnonKey={process.env.SUPABASE_ANON_KEY}
                />
              ) : null}
              <form className="dataPanel formPanel widePanel" action={recordLaunchSignoff}>
                <label>
                  Signoff
                  <select name="key" defaultValue="launch_legal_name_public_copy">
                    {launchSignoffKeys.map((key) => (
                      <option key={key} value={key}>
                        {launchSignoffLabel(key)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Status
                  <select name="status" defaultValue="pending">
                    <option value="pending">Pending</option>
                    <option value="approved">Approved</option>
                    <option value="rejected">Rejected</option>
                  </select>
                </label>
                <label>
                  Reviewer
                  <input name="reviewer" placeholder="Navn/rolle" />
                </label>
                <label>
                  Reviewed at
                  <input name="reviewedAt" type="datetime-local" required />
                </label>
                <label>
                  Evidence link
                  <input name="evidenceLink" placeholder="https://..." />
                </label>
                <label>
                  Decision
                  <textarea name="decision" placeholder="Beslutning, begrensninger, neste steg" />
                </label>
                <button className="secondaryButton" type="submit">
                  Lagre launch signoff
                </button>
              </form>
              <form className="dataPanel formPanel widePanel" action={upsertProductionPilotEntitlement}>
                <h3>Eksakt RF-1086-produksjonspilot</h3>
                <p>Én navngitt eier, ett selskap, ett inntektsår og kun profilen uten aktivitet.</p>
                <label>Selskap-ID<input name="companyId" required placeholder="UUID fra operatørsøket" /></label>
                <label>Eierens bruker-ID<input name="ownerUserId" required placeholder="Supabase user UUID" /></label>
                <label>Inntektsår<input name="incomeYear" type="number" min="2000" max="2100" defaultValue="2025" required /></label>
                <label>Status
                  <select name="status" defaultValue="pending">
                    <option value="pending">Pending</option><option value="active">Active</option>
                    <option value="suspended">Suspended</option><option value="completed">Completed</option>
                    <option value="revoked">Revoked</option>
                  </select>
                </label>
                <label>Systembrukerforespørsel-ID<input name="systemUserRequestId" required placeholder="Verifisert request UUID" /></label>
                <label>Aktiv fra<input name="startsAt" type="datetime-local" required /></label>
                <label>Utløper<input name="expiresAt" type="datetime-local" required /></label>
                <label>Evidensreferanse<input name="evidenceReference" required placeholder="Sak/avtale/runbook-referanse" /></label>
                <label><input name="billingExempt" type="checkbox" defaultChecked /> Gratis, invitert beta</label>
                <button className="secondaryButton" type="submit">Lagre eksakt entitlement</button>
              </form>
              <form className="dataPanel formPanel widePanel" action={runProductionAuthorityOperation}>
                <h3>Produksjon · Systemregister</h3>
                <p>
                  Status: <strong>{authorityOpsEnabled ? "Midlertidig aktivert" : "Deaktivert"}</strong>
                </p>
                <p>System: <code>930835978_talli</code></p>
                <p>Rettighet: <code>ske-innrapportering-aksjonaerregisteroppgave</code></p>
                <p>Operasjonen verifiserer eksisterende definisjon og overskriver aldri en konflikt.</p>
                <input type="hidden" name="operation" value="register_rf1086_system" />
                <label>
                  Skriv REGISTER TALLI RF1086 SYSTEM
                  <input name="confirmation" autoComplete="off" required />
                </label>
                <button className="secondaryButton" type="submit" disabled={!authorityOpsEnabled}>
                  Registrer eller verifiser system
                </button>
              </form>
              <form
                className="dataPanel formPanel widePanel"
                action={runProductionSystembrukerCallbackOperation}
              >
                <h3>{operatorAuthorityCopy.systembrukerCallback.title}</h3>
                <p>
                  {operatorAuthorityCopy.systembrukerCallback.gateLabel}:{" "}
                  <strong>
                    {authorityOpsEnabled
                      ? operatorAuthorityCopy.systembrukerCallback.enabled
                      : operatorAuthorityCopy.systembrukerCallback.disabled}
                  </strong>
                </p>
                <p>{operatorAuthorityCopy.systembrukerCallback.body}</p>
                <p>
                  {operatorAuthorityCopy.systembrukerCallback.callbackLabel}:{" "}
                  <code>{operatorAuthorityCopy.systembrukerCallback.callback}</code>
                </p>
                <input
                  type="hidden"
                  name="operation"
                  value="set_rf1086_systembruker_callback"
                />
                <label>
                  {operatorAuthorityCopy.systembrukerCallback.confirmationLabel}
                  <input name="confirmation" autoComplete="off" required />
                </label>
                <button className="secondaryButton" type="submit" disabled={!authorityOpsEnabled}>
                  {operatorAuthorityCopy.systembrukerCallback.cta}
                </button>
              </form>
              {authorityState.error ? (
                <p className="errorText">Kunne ikke lese revisjonsloggen for produksjonsoperasjoner.</p>
              ) : null}
              <div className="readinessGrid">
                {authorityState.operations.map((operation) => (
                  <div className="readinessItem" key={operation.id}>
                    <span>{operation.operation}</span>
                    <strong data-status={operation.status === "succeeded" ? "ready" : "warning"}>
                      {operation.status} · {operation.result_code}
                    </strong>
                    <p>HTTP: {operation.authority_http_status ?? "–"}</p>
                    <p>System: {operation.metadata.systemId ?? "–"}</p>
                    <p>Klient: {operation.metadata.clientId ?? "–"}</p>
                    <p>Rettighet: {operation.metadata.right ?? "–"}</p>
                    <p>Callback: {operation.metadata.callbackPath ?? "–"}</p>
                    <p>Startet: {new Date(operation.created_at).toLocaleString("nb-NO")}</p>
                    <p>Fullført: {operation.completed_at ? new Date(operation.completed_at).toLocaleString("nb-NO") : "Pågår"}</p>
                  </div>
                ))}
              </div>
              </>
            ) : null}
          </>
        ) : null}
        <div className="readinessGrid">
          {operatorDashboard.summaries.map((summary) => (
            <div className="readinessItem" key={summary.companyId}>
              <span>{summary.orgNumber}</span>
              <strong data-status={summary.refundStatus !== "none" || summary.restoreStatus !== "ok" ? "warning" : "ready"}>
                {summary.companyName}
              </strong>
              <p>Filing: {summary.filingStatus}</p>
              <p>Readiness blockers: {summary.readinessBlockCount}</p>
              <p>Authority prod gates: {summary.authorityProductionEnabled}</p>
              <p>Billing: {summary.billingStatus}</p>
              <p>Refund: {summary.refundStatus}</p>
              <p>Restore/archive: {summary.restoreStatus}</p>
              <p>Audit: {summary.recentAuditActions.join(", ") || "Ingen"}</p>
              {launchSignoffState.isAdminOperator
                && summary.cancellationId
                && summary.cancellationStatus === "retention_hold"
                && summary.cancellationUpdatedAt ? (
                <form className="formPanel" action={reviewCompanyDeletion}>
                  <input name="operationId" type="hidden" value={randomUUID()} />
                  <input name="companyId" type="hidden" value={summary.companyId} />
                  <input name="cancellationId" type="hidden" value={summary.cancellationId} />
                  <input name="expectedUpdatedAt" type="hidden" value={summary.cancellationUpdatedAt} />
                  <label>
                    Beslutning
                    <select name="decision" defaultValue="approved">
                      <option value="approved">Godkjenn</option>
                      <option value="rejected">Avvis</option>
                    </select>
                  </label>
                  <label>
                    Evidensreferanse
                    <input name="evidenceReference" required placeholder="Saks-/dokumentreferanse" />
                  </label>
                  <button className="secondaryButton" type="submit">Registrer uavhengig deletion review</button>
                </form>
              ) : null}
            </div>
          ))}
          {operatorSearch && operatorDashboard.isOperator && operatorDashboard.summaries.length === 0 ? (
            <div className="readinessItem">
              <span>Operator</span>
              <strong data-status="draft">Ingen treff</strong>
              <p>Ingen selskap matchet søket.</p>
            </div>
          ) : null}
        </div>
      </section>
    </>
  );
}

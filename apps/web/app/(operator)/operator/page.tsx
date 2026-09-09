import { AnnualBillingSupport, OperatorReadRecoveryView } from "./annual-billing-support";
import { randomUUID } from "node:crypto";
import { redirect } from "next/navigation";
import { operatorRecoveryHref, operatorSupportLocation } from "../../lib/operator-support";

import {
  grantSupportAccess,
  recoverAnnualSupportRefund,
  recoverAnnualSupportCleanup,
  openSupportCase,
  recordLaunchSignoff,
  reviewCompanyDeletion,
  revokeSupportAccess,
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
  getOperatorPageAccess,
  listAuthorityOperations,
  listLaunchSignoffs,
  readOperatorSupportDashboard,
} from "../../lib/supabase/server";
import { OperatorMfa } from "./operator-mfa";
import { loadPendingCancellationOperation } from "../../lib/cancellation-operation-state";

type OperatorProps = {
  searchParams?: Promise<{
    supportCase?: string | string[];
    annualBefore?: string | string[];
    companyId?: string | string[];
    refundPurchaseId?: string | string[];
    refundRequestId?: string | string[];
    beforeRefundRequestId?: string | string[];
    grant?: string;
    error?: string;
    pilot?: string;
    authority?: string;
  }>;
};

const authorityResultMessages: Record<string, string> = {
  created_and_verified: "Systemet ble opprettet og verifisert i produksjon.",
  already_verified:
    "Systemet finnes allerede og samsvarer med den faste definisjonen.",
  callback_already_verified:
    "Den faste Systembruker-callbacken er allerede verifisert.",
  callback_updated_and_verified:
    "Den faste Systembruker-callbacken ble lagt til og verifisert.",
  definition_conflict:
    "Eksisterende system avviker. Ingen overskriving ble utført.",
  authority_ops_disabled: "Produksjonsoperasjoner er deaktivert.",
  authority_step_up_required:
    "Fersk AAL2/MFA kreves før operasjonen kan kjøres.",
  authority_step_up_failed: "AAL2/MFA-kontrollen kunne ikke fullføres.",
  authority_operation_invalid:
    "Operasjonen eller bekreftelsesfrasen var ugyldig.",
  admin_operator_required: "Aktiv admin-operatør kreves.",
  authority_environment_invalid: "Produksjonsmiljøet er ugyldig konfigurert.",
  authority_client_id_invalid: "Maskinporten-klient-ID-en er ugyldig.",
  authority_key_id_invalid: "Maskinporten-nøkkel-ID-en er ugyldig.",
  authority_private_key_invalid: "Maskinporten-privatnøkkelen er ugyldig.",
  authority_audit_unavailable: "Revisjonsloggen er ikke tilgjengelig.",
  authority_audit_start_failed:
    "Operasjonen ble ikke startet fordi revisjonsloggen feilet.",
  authority_audit_completion_failed:
    "Resultatet kunne ikke ferdigstilles i revisjonsloggen.",
  authority_token_error: "Maskinporten-token kunne ikke hentes.",
  authority_network_error: "Nettverkskallet til Altinn feilet.",
  authority_http_error: "Altinn avviste operasjonen.",
  authority_response_invalid: "Altinn returnerte et ugyldig svar.",
  authority_verification_error:
    "Systemregister-resultatet kunne ikke verifiseres med en ny avlesning.",
  authority_operation_failed: "Produksjonsoperasjonen feilet.",
  authority_mfa_ready: "AAL2 er aktiv for denne operatørøkten.",
};

export default async function OperatorPage({ searchParams }: OperatorProps) {
  const params = await searchParams;
  const location = operatorSupportLocation(params);
  const access = await getOperatorPageAccess();
  if (access.recovery === "forbidden") redirect("/dashboard");
  if (access.recovery === "sign-in" || access.recovery === "step-up") {
    redirect(operatorRecoveryHref(access.recovery, location.returnTo));
  }
  if (access.recovery) return <OperatorReadRecoveryView recovery={access.recovery} returnTo={location.returnTo} />;
  if (location.invalid) return <OperatorReadRecoveryView recovery="unavailable" returnTo={location.returnTo} />;
  const user = access.user;
  const { supportCaseId, beforePurchaseId } = location;
  const operatorDashboard = supportCaseId
    ? await readOperatorSupportDashboard(supportCaseId, user.id, beforePurchaseId, location)
    : { summaries: [], isOperator: false, error: null, annualBilling: null, annualBillingError: null, annualRefundTargets: null, recovery: null };
  if (operatorDashboard.recovery) {
    return <OperatorReadRecoveryView recovery={operatorDashboard.recovery} returnTo={location.returnTo} />;
  }
  const pendingCancellationOperation = await loadPendingCancellationOperation();
  const launchSignoffState = user
    ? await listLaunchSignoffs(user.id)
    : {
        launchSignoffs: [],
        isOperator: false,
        isAdminOperator: false,
        error: null,
      };
  const authorityState = user
    ? await listAuthorityOperations(user.id)
    : { operations: [], isAdminOperator: false, error: null };
  const authorityOpsEnabled =
    process.env.TALLI_AUTHORITY_OPS_ENABLED === "true";
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
        {params?.pilot === "updated" ? (
          <p className="successText">Produksjonspiloten er oppdatert.</p>
        ) : null}
        {params?.grant === "created" ? (
          <p className="successText">Saksbundet supporttilgang er opprettet.</p>
        ) : null}
        {params?.grant === "revoked" ? (
          <p className="successText">Supporttilgangen er tilbakekalt.</p>
        ) : null}
        {params?.authority ? (
          <p
            className={
              [
                "created_and_verified",
                "already_verified",
                "callback_already_verified",
                "callback_updated_and_verified",
              ].includes(params.authority)
                ? "successText"
                : "errorText"
            }
          >
            {authorityResultMessages[params.authority] ??
              "Ukjent resultat fra produksjonsoperasjonen."}
          </p>
        ) : null}
        <form
          className="dataPanel formPanel widePanel"
          action={openSupportCase}
        >
          <input name="operationId" type="hidden" value={randomUUID()} />
          <label>
            Beskyttet saks-ID
            <input
              name="supportCaseId"
              defaultValue={supportCaseId}
              placeholder="00000000-0000-0000-0000-000000000000"
              required
            />
          </label>
          <button className="secondaryButton" type="submit">
            Åpne sak
          </button>
        </form>
        {launchSignoffState.error ? (
          <p className="errorText">{launchSignoffState.error}</p>
        ) : null}
        {launchSignoffState.isOperator ? (
          <>
            <div className="readinessGrid">
              <div className="readinessItem">
                <span>Launch signoff</span>
                <strong
                  data-status={launchSignoffGate.ready ? "ready" : "warning"}
                >
                  {launchSignoffGate.status}
                </strong>
                <p>
                  {launchSignoffGate.messages[0] ??
                    "Alle launch signoffs er godkjent."}
                </p>
                <p>Mangler: {launchSignoffGate.missing.length}</p>
                <p>Avvist: {launchSignoffGate.rejected.length}</p>
                <p>Utdatert: {launchSignoffGate.stale.length}</p>
              </div>
              {launchSignoffKeys.map((key) => {
                const signoff = launchSignoffState.launchSignoffs.find(
                  (item) => item.key === key,
                );
                return (
                  <div className="readinessItem" key={key}>
                    <span>{launchSignoffLabel(key)}</span>
                    <strong
                      data-status={
                        signoff?.status === "approved"
                          ? "ready"
                          : signoff
                            ? "warning"
                            : "draft"
                      }
                    >
                      {signoff?.status ?? "pending"}
                    </strong>
                    <p>Reviewer: {signoff?.reviewer || "Mangler"}</p>
                    <p>
                      Dato:{" "}
                      {signoff?.reviewed_at
                        ? new Date(signoff.reviewed_at).toLocaleString("nb-NO")
                        : "Mangler"}
                    </p>
                    <p>{signoff?.decision || "Ingen beslutning registrert."}</p>
                    {signoff?.evidence_link ? (
                      <a href={signoff.evidence_link}>Evidens</a>
                    ) : null}
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
                <form
                  className="dataPanel formPanel widePanel"
                  action={recordLaunchSignoff}
                >
                  <label>
                    Signoff
                    <select
                      name="key"
                      defaultValue="launch_legal_name_public_copy"
                    >
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
                    <textarea
                      name="decision"
                      placeholder="Beslutning, begrensninger, neste steg"
                    />
                  </label>
                  <button className="secondaryButton" type="submit">
                    Lagre launch signoff
                  </button>
                </form>
                <form
                  className="dataPanel formPanel widePanel"
                  action={upsertProductionPilotEntitlement}
                >
                  <h3>Eksakt RF-1086-produksjonspilot</h3>
                  <input name="operationId" type="hidden" value={randomUUID()} />
                  <p>
                    Én navngitt eier, ett selskap, ett inntektsår og kun
                    profilen uten aktivitet.
                  </p>
                  <label>
                    Selskap-ID
                    <input
                      name="companyId"
                      required
                      placeholder="UUID fra operatørsøket"
                    />
                  </label>
                  <label>
                    Eierens bruker-ID
                    <input
                      name="ownerUserId"
                      required
                      placeholder="Supabase user UUID"
                    />
                  </label>
                  <label>
                    Inntektsår
                    <input
                      name="incomeYear"
                      type="number"
                      min="2000"
                      max="2100"
                      defaultValue="2025"
                      required
                    />
                  </label>
                  <label>
                    Status
                    <select name="status" defaultValue="pending">
                      <option value="pending">Pending</option>
                      <option value="active">Active</option>
                      <option value="suspended">Suspended</option>
                      <option value="completed">Completed</option>
                      <option value="revoked">Revoked</option>
                    </select>
                  </label>
                  <label>
                    Systembrukerforespørsel-ID
                    <input
                      name="systemUserRequestId"
                      required
                      placeholder="Verifisert request UUID"
                    />
                  </label>
                  <label>
                    Aktiv fra
                    <input name="startsAt" type="datetime-local" required />
                  </label>
                  <label>
                    Utløper
                    <input name="expiresAt" type="datetime-local" required />
                  </label>
                  <label>
                    Evidensreferanse
                    <input
                      name="evidenceReference"
                      required
                      placeholder="Sak/avtale/runbook-referanse"
                    />
                  </label>
                  <label>
                    <input
                      name="billingExempt"
                      type="checkbox"
                      defaultChecked
                    />{" "}
                    Gratis, invitert beta
                  </label>
                  <button className="secondaryButton" type="submit">
                    Lagre eksakt entitlement
                  </button>
                </form>
                <form
                  className="dataPanel formPanel widePanel"
                  action={runProductionAuthorityOperation}
                >
                  <h3>Produksjon · Systemregister</h3>
                  <p>
                    Status:{" "}
                    <strong>
                      {authorityOpsEnabled
                        ? "Midlertidig aktivert"
                        : "Deaktivert"}
                    </strong>
                  </p>
                  <p>
                    System: <code>930835978_talli</code>
                  </p>
                  <p>
                    Rettighet:{" "}
                    <code>ske-innrapportering-aksjonaerregisteroppgave</code>
                  </p>
                  <p>
                    Operasjonen verifiserer eksisterende definisjon og
                    overskriver aldri en konflikt.
                  </p>
                  <input
                    type="hidden"
                    name="operation"
                    value="register_rf1086_system"
                  />
                  <label>
                    Skriv REGISTER TALLI RF1086 SYSTEM
                    <input name="confirmation" autoComplete="off" required />
                  </label>
                  <button
                    className="secondaryButton"
                    type="submit"
                    disabled={!authorityOpsEnabled}
                  >
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
                    <code>
                      {operatorAuthorityCopy.systembrukerCallback.callback}
                    </code>
                  </p>
                  <input
                    type="hidden"
                    name="operation"
                    value="set_rf1086_systembruker_callback"
                  />
                  <label>
                    {
                      operatorAuthorityCopy.systembrukerCallback
                        .confirmationLabel
                    }
                    <input name="confirmation" autoComplete="off" required />
                  </label>
                  <button
                    className="secondaryButton"
                    type="submit"
                    disabled={!authorityOpsEnabled}
                  >
                    {operatorAuthorityCopy.systembrukerCallback.cta}
                  </button>
                </form>
                {authorityState.error ? (
                  <p className="errorText">
                    Kunne ikke lese revisjonsloggen for produksjonsoperasjoner.
                  </p>
                ) : null}
                <div className="readinessGrid">
                  {authorityState.operations.map((operation) => (
                    <div className="readinessItem" key={operation.id}>
                      <span>{operation.operation}</span>
                      <strong
                        data-status={
                          operation.status === "succeeded" ? "ready" : "warning"
                        }
                      >
                        {operation.status} · {operation.result_code}
                      </strong>
                      <p>HTTP: {operation.authority_http_status ?? "–"}</p>
                      <p>System: {operation.metadata.systemId ?? "–"}</p>
                      <p>Klient: {operation.metadata.clientId ?? "–"}</p>
                      <p>Rettighet: {operation.metadata.right ?? "–"}</p>
                      <p>Callback: {operation.metadata.callbackPath ?? "–"}</p>
                      <p>
                        Startet:{" "}
                        {new Date(operation.created_at).toLocaleString("nb-NO")}
                      </p>
                      <p>
                        Fullført:{" "}
                        {operation.completed_at
                          ? new Date(operation.completed_at).toLocaleString(
                              "nb-NO",
                            )
                          : "Pågår"}
                      </p>
                    </div>
                  ))}
                </div>
              </>
            ) : null}
          </>
        ) : null}
        {launchSignoffState.isAdminOperator && user ? (
          <form
            className="dataPanel formPanel widePanel"
            action={grantSupportAccess}
          >
            <input name="operationId" type="hidden" value={randomUUID()} />
            <label>
              Selskap-ID
              <input name="companyId" required />
            </label>
            <label>
              Operatør-ID
              <input name="operatorUserId" required defaultValue={user.id} />
            </label>
            <label>
              Begrunnelse
              <select name="reason" defaultValue="customer_request">
                <option value="customer_request">Kundeforespørsel</option>
                <option value="security_incident">Sikkerhetshendelse</option>
                <option value="service_recovery">Tjenestegjenoppretting</option>
                <option value="legal_obligation">Rettslig plikt</option>
              </select>
            </label>
            <label>
              Starter (ISO 8601)
              <input
                name="startsAt"
                required
                placeholder="2026-08-30T10:00:00Z"
              />
            </label>
            <label>
              Utløper, maks 8 timer (ISO 8601)
              <input
                name="expiresAt"
                required
                placeholder="2026-08-30T18:00:00Z"
              />
            </label>
            <fieldset>
              <legend>Tilgangsomfang</legend>
              {[
                "profile",
                "filing",
                "billing",
                "audit",
                "cancellation",
                "authority",
                "documents",
                "production",
              ].map((scope) => (
                <label key={scope}>
                  <input type="checkbox" name="scopes" value={scope} />
                  {scope}
                </label>
              ))}
            </fieldset>
            <button className="secondaryButton" type="submit">
              Opprett generert support-sak
            </button>
          </form>
        ) : null}
        {launchSignoffState.isAdminOperator && supportCaseId ? (
          <form
            className="dataPanel formPanel widePanel"
            action={revokeSupportAccess}
          >
            <input name="operationId" type="hidden" value={randomUUID()} />
            <input name="supportCaseId" type="hidden" value={supportCaseId} />
            <label>
              Tilbakekallingsgrunn
              <select name="reason" defaultValue="case_closed">
                <option value="case_closed">Sak lukket</option>
                <option value="access_no_longer_needed">
                  Tilgang ikke lenger nødvendig
                </option>
                <option value="operator_removed">Operatør fjernet</option>
                <option value="security_response">Sikkerhetstiltak</option>
                <option value="grant_replaced">Erstattet tilgang</option>
              </select>
            </label>
            <button className="secondaryButton" type="submit">
              Tilbakekall tilgang
            </button>
          </form>
        ) : null}
        <AnnualBillingSupport
          page={operatorDashboard.annualBilling}
          error={operatorDashboard.annualBillingError}
          supportCaseId={supportCaseId}
          beforePurchaseId={beforePurchaseId}
          initiatingUserId={user.id}
          refundTargets={operatorDashboard.annualRefundTargets}
          recoverAction={recoverAnnualSupportRefund}
          recoverCleanupAction={recoverAnnualSupportCleanup}
        />
        <div className="readinessGrid">
          {operatorDashboard.summaries.map((summary) => (
            <div className="readinessItem" key={summary.companyId}>
              <span>{summary.orgNumber}</span>
              <strong
                data-status={
                  summary.refundStatus !== "none" ||
                  summary.restoreStatus !== "ok"
                    ? "warning"
                    : "ready"
                }
              >
                {summary.companyName}
              </strong>
              <p>Filing: {summary.filingStatus}</p>
              <p>Readiness blockers: {summary.readinessBlockCount}</p>
              <p>Authority prod gates: {summary.authorityProductionEnabled}</p>
              <p>Billing: {summary.billingStatus}</p>
              <p>Refund: {summary.refundStatus}</p>
              <p>Restore/archive: {summary.restoreStatus}</p>
              <p>Audit: {summary.recentAuditActions.join(", ") || "Ingen"}</p>
              {!operatorDashboard.error &&
              launchSignoffState.isAdminOperator &&
              summary.cancellationId &&
              summary.cancellationStatus === "retention_hold" &&
              summary.cancellationUpdatedAt ? (
                <form className="formPanel" action={reviewCompanyDeletion}>
                  <input
                    name="operationId"
                    type="hidden"
                    value={
                      pendingCancellationOperation?.command === "review" &&
                      pendingCancellationOperation.supportCaseId ===
                        supportCaseId &&
                      pendingCancellationOperation.cancellationId ===
                        summary.cancellationId
                        ? pendingCancellationOperation.operationId
                        : randomUUID()
                    }
                  />
                  <input
                    name="companyId"
                    type="hidden"
                    value={summary.companyId}
                  />
                  <input
                    name="supportCaseId"
                    type="hidden"
                    value={supportCaseId}
                  />
                  <input
                    name="cancellationId"
                    type="hidden"
                    value={summary.cancellationId}
                  />
                  <input
                    name="expectedUpdatedAt"
                    type="hidden"
                    value={
                      pendingCancellationOperation?.command === "review" &&
                      pendingCancellationOperation.supportCaseId ===
                        supportCaseId &&
                      pendingCancellationOperation.cancellationId ===
                        summary.cancellationId
                        ? pendingCancellationOperation.expectedUpdatedAt
                        : summary.cancellationUpdatedAt
                    }
                  />
                  <label>
                    Beslutning
                    <select
                      name="decision"
                      defaultValue={
                        pendingCancellationOperation?.command === "review" &&
                        pendingCancellationOperation.supportCaseId ===
                          supportCaseId &&
                        pendingCancellationOperation.cancellationId ===
                          summary.cancellationId
                          ? pendingCancellationOperation.decision
                          : "approved"
                      }
                    >
                      <option value="approved">Godkjenn</option>
                      <option value="rejected">Avvis</option>
                    </select>
                  </label>
                  <label>
                    Evidensreferanse
                    <input
                      name="evidenceReference"
                      required
                      placeholder="Saks-/dokumentreferanse"
                      defaultValue={
                        pendingCancellationOperation?.command === "review" &&
                        pendingCancellationOperation.supportCaseId ===
                          supportCaseId &&
                        pendingCancellationOperation.cancellationId ===
                          summary.cancellationId
                          ? pendingCancellationOperation.evidenceReference
                          : undefined
                      }
                    />
                  </label>
                  <button className="secondaryButton" type="submit">
                    Registrer uavhengig slettevurdering
                  </button>
                </form>
              ) : null}
            </div>
          ))}
          {supportCaseId &&
          operatorDashboard.isOperator &&
          operatorDashboard.summaries.length === 0 &&
          !operatorDashboard.annualBilling && !operatorDashboard.annualBillingError ? (
            <div className="readinessItem">
              <span>Operator</span>
              <strong data-status="draft">Ingen treff</strong>
              <p>Saken ga ingen autoriserte supportdata.</p>
            </div>
          ) : null}
        </div>
      </section>
    </>
  );
}

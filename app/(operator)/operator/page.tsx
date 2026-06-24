import { recordLaunchSignoff } from "../../actions";
import {
  buildLaunchSignoffGate,
  launchSignoffKeys,
  launchSignoffLabel,
} from "../../lib/launch-signoff";
import {
  getCurrentUser,
  listLaunchSignoffs,
  searchOperatorSupportDashboard,
} from "../../lib/supabase/server";

type OperatorProps = {
  searchParams?: Promise<{ operatorOrg?: string }>;
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

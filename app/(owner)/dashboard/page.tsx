import {
  authorityObligationLabel,
  authorityObligations,
} from "../../lib/authority-permission";
import { deadlineStatusLabel } from "../../lib/deadlines";
import { loadWorkspaceData } from "../../lib/workspace-data";
import { ownerCopy } from "../../lib/copy";
import {
  Banner,
  EmptyState,
  FileText,
  LinkButton,
  Panel,
  StatCard,
  StatusBadge,
} from "../../components/ui";
import type { DomainStatus } from "../../components/ui";

type DashboardProps = {
  searchParams?: Promise<{ error?: string }>;
};

type ReadinessStatus = "ready" | "warning" | "blocked";

const READINESS_BADGE: Record<ReadinessStatus, DomainStatus> = {
  ready: "klar",
  warning: "trenger_gjennomgang",
  blocked: "blokkert",
};

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export default async function DashboardPage({ searchParams }: DashboardProps) {
  const params = await searchParams;
  const data = await loadWorkspaceData();
  const {
    companies,
    primaryCompanyId,
    primaryIncomeYear,
    primaryReadinessSnapshots,
    deadlines,
    documents,
    transactions,
    unmatchedTransactions,
    actions,
  } = data;

  const primaryCompany =
    companies.find((company) => company.id === primaryCompanyId) ?? companies[0];

  const pendingObligations = primaryCompany
    ? authorityObligations.filter(
        (obligation) =>
          !primaryReadinessSnapshots.find((item) => item.obligation === obligation)
            ?.ready,
      )
    : authorityObligations;

  const dash = ownerCopy.dashboard;
  const nba = dash.nextAction;

  let nextAction: {
    eyebrow: string;
    title: string;
    body: string;
    href: string;
    cta: string;
  };
  if (!primaryCompany) {
    nextAction = {
      eyebrow: nba.setupEyebrow,
      title: nba.setupTitle,
      body: nba.setupBody,
      href: "/workspace#opprett",
      cta: nba.setupCta,
    };
  } else if (pendingObligations.length > 0) {
    nextAction = {
      eyebrow: nba.pendingEyebrow(primaryIncomeYear),
      title: nba.pendingTitle,
      body: nba.pendingBody(pendingObligations.length, authorityObligations.length),
      href: "/workspace#arbeidsflate",
      cta: nba.pendingCta,
    };
  } else if (unmatchedTransactions.length > 0) {
    nextAction = {
      eyebrow: nba.reconcileEyebrow,
      title: nba.reconcileTitle,
      body: nba.reconcileBody(unmatchedTransactions.length),
      href: "/workspace#arbeidsflate",
      cta: nba.reconcileCta,
    };
  } else {
    nextAction = {
      eyebrow: nba.readyEyebrow,
      title: nba.readyTitle,
      body: nba.readyBody,
      href: "/workspace#arbeidsflate",
      cta: nba.readyCta,
    };
  }

  const upcomingDeadlines = deadlines.slice(0, 4);

  return (
    <div>
      <div className="pageHead">
        <h1 className="pageTitle">
          {primaryCompany ? primaryCompany.name : dash.welcomeTitle}
        </h1>
        <p className="pageLede">
          {primaryCompany
            ? dash.orgLine(primaryCompany.org_number, primaryIncomeYear)
            : ownerCopy.tagline}
        </p>
      </div>

      {params?.error ? <Banner variant="danger">{params.error}</Banner> : null}

      {primaryCompany ? (
        <section className="nbaCard" aria-label={dash.nextStepEyebrow}>
          <span className="nbaKicker">{nextAction.eyebrow}</span>
          <h2 className="nbaTitle">{nextAction.title}</h2>
          <p className="cardNote">{nextAction.body}</p>
          <div>
            <LinkButton variant="primary" href={nextAction.href}>
              {nextAction.cta}
            </LinkButton>
          </div>
        </section>
      ) : (
        <EmptyState
          icon={<FileText size={22} aria-hidden="true" />}
          title={dash.empty.title}
          action={
            <LinkButton variant="primary" href="/workspace#opprett">
              {dash.empty.cta}
            </LinkButton>
          }
        >
          {dash.empty.body}
        </EmptyState>
      )}

      {primaryCompany ? (
        <>
          <Panel
            title={dash.complianceTitle(primaryIncomeYear)}
            className="dashboardSection"
          >
            <div className="statusList">
              {authorityObligations.map((obligation) => {
                const snapshot = primaryReadinessSnapshots.find(
                  (item) => item.obligation === obligation,
                );
                const blockers = snapshot?.hard_blocks ?? [];
                return (
                  <div className="statusRow statusRow--stacked" key={obligation}>
                    <div className="statusRowHead">
                      <span>{authorityObligationLabel(obligation)}</span>
                      {snapshot ? (
                        <StatusBadge status={READINESS_BADGE[snapshot.status]} />
                      ) : (
                        <StatusBadge
                          variant="draft"
                          label={ownerCopy.status.notAssessed}
                        />
                      )}
                    </div>
                    {blockers.length > 0 ? (
                      <div className="statusRowDetail">
                        <span className="cardLabel">{dash.blockersLabel}</span>
                        <ul className="blockerList">
                          {blockers.map((issue) => (
                            <li key={issue.code}>{issue.message}</li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </Panel>

          <Panel title={dash.overviewTitle} className="dashboardSection">
            <div className="cardGrid">
              <StatCard label={dash.metrics.documents} value={documents.length} />
              <StatCard
                label={dash.metrics.transactions}
                value={transactions.length}
              />
              <StatCard
                label={dash.metrics.unmatched}
                value={unmatchedTransactions.length}
              />
              <StatCard label={dash.metrics.actions} value={actions.length} />
            </div>
          </Panel>

          {upcomingDeadlines.length > 0 ? (
            <Panel title={dash.deadlinesTitle} className="dashboardSection">
              <div className="statusList">
                {upcomingDeadlines.map((deadline) => (
                  <div
                    className="statusRow"
                    key={`${deadline.incomeYear}-${deadline.filing}`}
                  >
                    <span>
                      {capitalize(deadline.filing)} {deadline.incomeYear} ·{" "}
                      {deadline.deadline}
                    </span>
                    <StatusBadge
                      variant={
                        deadline.status === "overdue" ||
                        deadline.status === "late_simulated"
                          ? "danger"
                          : deadline.status === "due"
                            ? "warning"
                            : "info"
                      }
                      label={deadlineStatusLabel(deadline.status)}
                    />
                  </div>
                ))}
              </div>
            </Panel>
          ) : null}
        </>
      ) : null}

      <Panel title={ownerCopy.filing.title} className="dashboardSection">
        <p className="cardNote">{ownerCopy.filing.preProductionGate}</p>
        <p className="cardNote">{ownerCopy.filing.notAffiliated}</p>
      </Panel>
    </div>
  );
}

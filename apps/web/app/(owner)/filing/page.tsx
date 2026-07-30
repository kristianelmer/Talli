import Link from "next/link";

import { Banner, EmptyState, LinkButton, StatusBadge } from "../../components/ui";
import { evaluateObligationReadiness } from "../../lib/annual-readiness";
import { ownerCopy } from "../../lib/copy";
import { loadWorkspaceData } from "../../lib/workspace-data";
import {
  FILING_OBLIGATIONS,
  buildReadinessInput,
} from "./_readiness";
import { buildOwnerFilingPresentation } from "./_presentation";

export const dynamic = "force-dynamic";

type FilingHubProps = {
  searchParams?: Promise<{ error?: string; posted?: string }>;
};

export default async function FilingHubPage({ searchParams }: FilingHubProps) {
  const params = await searchParams;
  const data = await loadWorkspaceData();
  const f = ownerCopy.filing;

  const input = buildReadinessInput(data);

  if (!input) {
    return (
      <div>
        <div className="pageHead">
          <h1 className="pageTitle">{f.hubTitle}</h1>
          <p className="pageLede">{f.hubLede}</p>
        </div>
        <EmptyState
          title={f.needsCompanyTitle}
          action={
            <LinkButton variant="primary" href="/onboarding">
              {f.needsCompanyCta}
            </LinkButton>
          }
        >
          {f.needsCompanyBody}
        </EmptyState>
      </div>
    );
  }

  return (
    <div>
      <div className="pageHead">
        <h1 className="pageTitle">{f.hubTitle}</h1>
        <p className="pageLede">{f.hubLede}</p>
      </div>

      {params?.posted ? <Banner variant="success">{f.posted}</Banner> : null}
      {params?.error ? <Banner variant="danger">{params.error}</Banner> : null}

      <p className="cardNote">{f.yearLabel(input.incomeYear)}</p>

      <div className="actionGrid">
        {FILING_OBLIGATIONS.map((obligation) => {
          const meta = f.obligations[obligation];
          const snapshot = evaluateObligationReadiness(input, obligation);
          const presentation = buildOwnerFilingPresentation({
            obligation,
            incomeYear: input.incomeYear,
            submissions: input.filingSubmissions,
          });

          const badge = presentation.pendingFeedback ? (
            <StatusBadge
              variant="warning"
              label={presentation.pendingFeedback.badgeLabel}
              icon="alert"
            />
          ) : presentation.submitted ? (
            <StatusBadge variant="success" label={f.status.submitted} icon="check" />
          ) : snapshot.ready ? (
            <StatusBadge status="klar" />
          ) : snapshot.status === "warning" ? (
            <StatusBadge variant="warning" label={f.status.warning} icon="alert" />
          ) : (
            <StatusBadge variant="danger" label={f.status.blocked} icon="alert" />
          );

          return (
            <Link
              key={obligation}
              className="actionCard filingCard"
              href={`/filing/${obligation}`}
            >
              <span className="filingCardHead">
                <span className="actionCardTitle">{meta.label}</span>
                {badge}
              </span>
              <span className="actionCardBody">
                {presentation.pendingFeedback?.body ?? meta.summary}
              </span>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

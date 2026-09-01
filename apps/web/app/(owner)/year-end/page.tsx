import { randomUUID } from "node:crypto";

import { hasPositiveInvestmentUnits } from "../../../features/investments";

import { EmptyState, LinkButton } from "../../components/ui";
import { buildAnnualAccountsPayload } from "../../lib/annual-accounts";
import {
  buildAnnualCloseBasis,
  buildAnnualCloseReviewedFacts,
} from "../../lib/annual-corporate-documents";
import { corporateAnnualSourceHash } from "../../lib/corporate-decision-facts";
import { evaluateCorporateDocumentReadiness } from "../../lib/corporate-document-readiness";
import { ownerCopy } from "../../lib/copy";
import { loadWorkspaceData } from "../../lib/workspace-data";
import { CorporateAnnualDecisionForm } from "./CorporateAnnualDecisionForm";
import { YearEndInterview } from "./YearEndInterview";

export const dynamic = "force-dynamic";

export default async function YearEndPage() {
  const data = await loadWorkspaceData();
  const {
    companies,
    primaryCompanyId,
    primaryIncomeYear,
    primaryAnnualData,
    actions,
    positions,
    entries,
    setups,
    shareholders,
    corporateDecisions,
    corporateDocumentSets,
    corporateDocumentArtifacts,
    corporateDocumentEvents,
    corporateDecisionFinalizations,
  } = data;

  const c = ownerCopy.yearEnd;
  const primaryCompany =
    companies.find((company) => company.id === primaryCompanyId) ?? companies[0];

  if (!primaryCompany) {
    return (
      <div>
        <div className="pageHead">
          <h1 className="pageTitle">{c.title(primaryIncomeYear)}</h1>
          <p className="pageLede">{c.intro}</p>
        </div>
        <EmptyState
          title={c.needsCompanyTitle}
          action={
            <LinkButton variant="primary" href="/onboarding">
              {c.needsCompanyCta}
            </LinkButton>
          }
        >
          {c.needsCompanyBody}
        </EmptyState>
      </div>
    );
  }

  const companyId = primaryCompany.id;
  const year = primaryIncomeYear;
  const yearActions = actions.filter(
    (action) => action.company_id === companyId && action.income_year === year,
  );
  const hasActionType = (...types: string[]) =>
    yearActions.some((action) => types.includes(action.action_type));

  const registered = {
    shares_owned_at_year_end: positions.some(
      (position) => position.company_id === companyId
        && hasPositiveInvestmentUnits(position.share_count),
    ),
    bought_or_sold_shares: hasActionType("share_purchase", "share_sale"),
    received_dividends: hasActionType("dividend_received", "fund_distribution_received"),
    declared_owner_dividends: entries.some(
      (entry) => entry.company_id === companyId
        && entry.income_year === year
        && entry.entry_type === "owner_dividend_declared",
    ),
    shareholder_loans: entries.some(
      (entry) => entry.company_id === companyId
        && entry.income_year === year
        && entry.entry_type === "shareholder_loan",
    ),
    paid_costs: entries.some(
      (entry) =>
        entry.company_id === companyId &&
        entry.income_year === year &&
        entry.entry_type === "admin_cost",
    ),
  };
  const featureEnabled = process.env.TALLI_CORPORATE_DOCUMENTS_ENABLED === "true";
  const setup = setups.find(
    (candidate) => candidate.company_id === companyId && candidate.income_year === year,
  );
  const annualShareholders = setup
    ? shareholders
        .filter((shareholder) => shareholder.setup_id === setup.id)
        .sort((left, right) => left.id.localeCompare(right.id, "en"))
    : [];
  let annualBasis = null;
  let reviewedFacts = null;
  let sourceHash: string | null = null;
  let annualDecisionBlocker: string | null = null;
  if (!primaryAnnualData) {
    annualDecisionBlocker = "Fullfør årsavslutningen før årsprotokollene opprettes.";
  } else if (!setup || annualShareholders.length === 0) {
    annualDecisionBlocker = "Låst aksjonærgrunnlag mangler for regnskapsåret.";
  } else {
    try {
      annualBasis = buildAnnualCloseBasis({
        annualData: primaryAnnualData,
        annualAccountsPayload: buildAnnualAccountsPayload({
          incomeYear: year,
          annualData: primaryAnnualData,
          ledgerEntries: entries.filter(
            (entry) => entry.company_id === companyId && entry.income_year === year,
          ),
        }),
      });
      reviewedFacts = buildAnnualCloseReviewedFacts({
        company: {
          id: primaryCompany.id,
          organizationNumber: primaryCompany.org_number,
          legalName: primaryCompany.name,
        },
        shareholders: annualShareholders.map((shareholder, order) => ({
          id: shareholder.id,
          name: shareholder.name,
          shareCount: Number(shareholder.share_count),
          order,
        })),
        annualBasis,
      });
      sourceHash = corporateAnnualSourceHash(annualBasis);
    } catch (error) {
      annualDecisionBlocker = error instanceof Error
        ? error.message
        : "Årsregnskapsgrunnlaget er ikke klart for protokoller.";
    }
  }
  const currentDecision = corporateDecisions.find(
    (decision) => decision.company_id === companyId
      && decision.income_year === year
      && decision.decision_kind === "annual_close",
  ) ?? null;
  const currentSet = currentDecision
    ? corporateDocumentSets.find((set) => set.decision_id === currentDecision.id) ?? null
    : null;
  const lifecycle = evaluateCorporateDocumentReadiness({
    currentDecisionHash: currentDecision?.decision_hash ?? "",
    currentSourceHash: sourceHash ?? "",
    decision: currentDecision ? {
      id: currentDecision.id,
      decision_kind: currentDecision.decision_kind,
      decision_hash: currentDecision.decision_hash,
      source_hash: currentDecision.source_hash,
    } : null,
    documentSet: currentSet ? {
      id: currentSet.id,
      decision_id: currentSet.decision_id,
      decision_hash: currentSet.decision_hash,
    } : null,
    artifacts: currentSet
      ? corporateDocumentArtifacts.filter((artifact) => artifact.set_id === currentSet.id)
      : [],
    events: currentDecision
      ? corporateDocumentEvents.filter((event) => event.decision_id === currentDecision.id)
      : [],
    finalizations: currentDecision
      ? corporateDecisionFinalizations.filter(
          (finalization) => finalization.decision_id === currentDecision.id,
        )
      : [],
  });

  return (
    <section className="wizard">
      <YearEndInterview
        companyId={companyId}
        incomeYear={year}
        initialAnswers={primaryAnnualData?.answers ?? null}
        initialFte={primaryAnnualData?.annual_full_time_equivalents ?? null}
        registered={registered}
      />
      <CorporateAnnualDecisionForm
        companyId={companyId}
        incomeYear={year}
        shareholders={annualShareholders.map((shareholder) => ({
          id: shareholder.id,
          name: shareholder.name,
          shareCount: Number(shareholder.share_count),
        }))}
        annualBasis={annualBasis}
        reviewedFacts={reviewedFacts}
        sourceHash={sourceHash}
        featureEnabled={featureEnabled}
        blocker={annualDecisionBlocker}
        lifecycle={currentDecision && currentSet ? {
          decisionId: currentDecision.id,
          state: lifecycle.state,
          decisionHash: currentDecision.decision_hash,
          sourceHash: currentDecision.source_hash,
          templateVersion: currentSet.template_version,
          stale: !lifecycle.currentHashMatches,
        } : null}
        draftIds={{
          decisionId: randomUUID(),
          documentSetId: randomUUID(),
          annualBoardArtifactId: randomUUID(),
          annualBoardDocumentId: randomUUID(),
          annualGeneralMeetingArtifactId: randomUUID(),
          annualGeneralMeetingDocumentId: randomUUID(),
        }}
      />
    </section>
  );
}

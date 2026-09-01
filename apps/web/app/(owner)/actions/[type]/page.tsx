import { randomUUID } from "node:crypto";
import { notFound } from "next/navigation";

import { Banner, EmptyState, LinkButton, WizardShell } from "../../../components/ui";
import { buildAnnualAccountsPayload } from "../../../lib/annual-accounts";
import { ownerCopy } from "../../../lib/copy";
import {
  buildOwnerDividendAnnualBasis,
  buildOwnerDividendReviewedFacts,
} from "../../../lib/owner-dividend";
import { loadWorkspaceData } from "../../../lib/workspace-data";
import { DividendReceivedWizard } from "../_components/DividendReceivedWizard";
import { FundDistributionWizard } from "../_components/FundDistributionWizard";
import { InvestmentCorrectionWizard } from "../_components/InvestmentCorrectionWizard";
import { OwnerDividendWizard } from "../_components/OwnerDividendWizard";
import { SharePurchaseWizard } from "../_components/SharePurchaseWizard";
import { ShareSaleWizard } from "../_components/ShareSaleWizard";
import { ShareholderLoanWizard } from "../_components/ShareholderLoanWizard";
import { TaxSettlementWizard } from "../_components/TaxSettlementWizard";

type ActionSlug =
  | "share-purchase"
  | "share-sale"
  | "dividend-received"
  | "fund-distribution"
  | "investment-correction"
  | "owner-dividend"
  | "shareholder-loan"
  | "tax-settlement";

const COPY_KEY: Record<ActionSlug, keyof typeof ownerCopy.actions> = {
  "share-purchase": "sharePurchase",
  "share-sale": "shareSale",
  "dividend-received": "dividendReceived",
  "fund-distribution": "fundDistribution",
  "investment-correction": "investmentCorrection",
  "owner-dividend": "ownerDividend",
  "shareholder-loan": "shareholderLoan",
  "tax-settlement": "taxSettlement",
};

function isActionSlug(value: string): value is ActionSlug {
  return value in COPY_KEY;
}

type ActionPageProps = {
  params: Promise<{ type: string }>;
  searchParams?: Promise<{
    error?: string;
    dividendReceivedOperationId?: string;
    sharePurchaseOperationId?: string;
    shareSaleOperationId?: string;
    fundDistributionOperationId?: string;
    investmentCorrectionOperationId?: string;
    investmentCorrectionReplacementActionId?: string;
    shareholderLoanOperationId?: string;
    taxSettlementOperationId?: string;
  }>;
};

export default async function ActionPage({
  params,
  searchParams,
}: ActionPageProps) {
  const { type } = await params;
  if (!isActionSlug(type)) {
    notFound();
  }
  const query = await searchParams;
  const data = await loadWorkspaceData();
  const {
    companies,
    primaryCompanyId,
    primaryIncomeYear,
    positions,
    actions,
    investmentCorrections,
    annualData,
    setups,
    shareholders,
    entries,
  } = data;

  const a = ownerCopy.actions;
  const primaryCompany =
    companies.find((company) => company.id === primaryCompanyId) ?? companies[0];

  if (!primaryCompany) {
    return (
      <EmptyState
        title={a.needsCompanyTitle}
        action={
          <LinkButton variant="primary" href="/onboarding">
            {a.needsCompanyCta}
          </LinkButton>
        }
      >
        {a.needsCompanyBody}
      </EmptyState>
    );
  }

  const companyId = primaryCompany.id;
  const incomeYear = primaryIncomeYear;
  const companyPositions = positions.filter(
    (position) => position.company_id === companyId,
  );
  const head = a[COPY_KEY[type]] as { title: string; intro: string };
  const corporateDocumentsEnabled = process.env.TALLI_CORPORATE_DOCUMENTS_ENABLED === "true";

  let body: React.ReactNode;
  switch (type) {
    case "share-purchase":
      body = (
        <SharePurchaseWizard
          companyId={companyId}
          incomeYear={incomeYear}
          operationId={query?.sharePurchaseOperationId}
        />
      );
      break;
    case "share-sale":
      body = (
        <ShareSaleWizard
          companyId={companyId}
          incomeYear={incomeYear}
          operationId={query?.shareSaleOperationId}
          positions={companyPositions.map((position) => ({
            id: position.id,
            name: position.name,
            kind: position.kind,
            share_count: position.share_count,
            lot_history_status: position.lot_history_status,
          }))}
        />
      );
      break;
    case "dividend-received":
      body = (
        <DividendReceivedWizard
          companyId={companyId}
          incomeYear={incomeYear}
          operationId={query?.dividendReceivedOperationId}
          investments={companyPositions
            .filter((position) => position.kind !== "norwegian_equity_fund")
            .map((position) => ({
              id: position.id,
              name: position.name,
              kind: position.kind,
            }))}
        />
      );
      break;
    case "fund-distribution":
      body = (
        <FundDistributionWizard
          companyId={companyId}
          incomeYear={incomeYear}
          operationId={query?.fundDistributionOperationId}
          investments={companyPositions
            .filter((position) => position.kind === "norwegian_equity_fund")
            .map((position) => ({ id: position.id, name: position.name }))}
        />
      );
      break;
    case "investment-correction": {
      const corrected = new Set(
        investmentCorrections.map((correction) => correction.original_action_id),
      );
      const correctable = actions
        .filter((action) => action.company_id === companyId
          && action.income_year === incomeYear
          && !corrected.has(action.id))
        .map((action) => {
          const payload = action.payload;
          const numberFact = (key: string, fallback = 0) => {
            const value = Number(payload[key] ?? fallback);
            return Number.isFinite(value) ? value : fallback;
          };
          const stringFact = (key: string, fallback = "") => (
            typeof payload[key] === "string" ? payload[key] : fallback
          );
          const nullableNumberFact = (key: string) => (
            payload[key] === null || payload[key] === undefined
              ? null
              : numberFact(key)
          );
          const investmentKind = stringFact("investment_kind") as
            | "norwegian_private_company"
            | "norwegian_listed_share"
            | "norwegian_equity_fund";
          const grossAmount = action.action_type === "share_purchase"
            ? numberFact("purchase_amount")
            : action.action_type === "share_sale"
              ? numberFact("proceeds")
              : numberFact("gross_amount");
          return {
            id: action.id,
            kind: action.action_type,
            label: `${action.action_date} · ${stringFact("investment_name", stringFact("fund_name", "Investering"))}`,
            actionDate: action.action_date,
            positionId: stringFact("position_id"),
            investmentName: stringFact(
              action.action_type === "fund_distribution_received"
                ? "fund_name"
                : action.action_type === "dividend_received"
                  ? "paying_company_name"
                  : "investment_name",
            ),
            investmentKey: stringFact("investment_key"),
            investmentKind,
            accountingClassification: stringFact("accounting_classification") as
              | "subsidiary" | "associate" | "other_long_term"
              | "current_listed_share" | "current_fund",
            orgNumber: stringFact("org_number") || null,
            shareCount: action.action_type === "share_purchase"
              ? nullableNumberFact("share_count")
              : action.action_type === "share_sale"
                ? nullableNumberFact("sold_share_count")
                : null,
            grossAmount,
            transactionCosts: numberFact("transaction_costs"),
            declaredDate: stringFact(
              action.action_type === "fund_distribution_received"
                ? "entitlement_date" : "declared_date",
            ) || null,
            fundEquityRatioBasisPoints: nullableNumberFact(
              action.action_type === "fund_distribution_received"
                ? "opening_fund_equity_ratio_basis_points"
                : "fund_equity_ratio_basis_points",
            ),
            fundTaxStatementReference:
              stringFact("fund_tax_statement_reference") || null,
            groupExceptionClaimed: payload.group_exception_claimed === true,
            yearEndOwnershipBasisPoints: nullableNumberFact(
              "year_end_ownership_basis_points",
            ),
            yearEndVotingBasisPoints: nullableNumberFact(
              "year_end_voting_basis_points",
            ),
            groupEvidenceReference:
              stringFact("group_evidence_reference") || null,
          };
        });
      body = (
        <InvestmentCorrectionWizard
          companyId={companyId}
          incomeYear={incomeYear}
          activities={correctable}
          operationId={query?.investmentCorrectionOperationId}
          replacementActionId={query?.investmentCorrectionReplacementActionId}
        />
      );
      break;
    }
    case "owner-dividend":
      const currentSetup = setups.find(
        (setup) => setup.company_id === companyId && setup.income_year === incomeYear,
      );
      const decisionShareholders = currentSetup
        ? shareholders
            .filter((shareholder) => shareholder.setup_id === currentSetup.id)
            .sort((left, right) => left.id.localeCompare(right.id, "en"))
        : [];
      const approvedAnnualData = [...annualData]
        .filter((candidate) => candidate.company_id === companyId
          && candidate.income_year <= incomeYear
          && candidate.answers.general_meeting_approved)
        .sort((left, right) => right.income_year - left.income_year)[0];
      let annualBasis = null;
      let reviewedFacts = null;
      let basisBlocker: string | null = null;
      if (!currentSetup) {
        basisBlocker = "Låst aksjonærgrunnlag mangler for beslutningsåret.";
      } else if (!approvedAnnualData) {
        basisBlocker = "Siste godkjente årsregnskap mangler.";
      } else {
        try {
          const annualAccountsPayload = buildAnnualAccountsPayload({
            incomeYear: approvedAnnualData.income_year,
            annualData: approvedAnnualData,
            ledgerEntries: entries.filter((entry) => entry.company_id === companyId
              && entry.income_year === approvedAnnualData.income_year),
          });
          annualBasis = buildOwnerDividendAnnualBasis({
            annualData: approvedAnnualData,
            annualAccountsPayload,
          });
          reviewedFacts = buildOwnerDividendReviewedFacts({
            company: {
              id: primaryCompany.id,
              organizationNumber: primaryCompany.org_number,
              legalName: primaryCompany.name,
            },
            shareholders: decisionShareholders.map((shareholder, order) => ({
              id: shareholder.id,
              name: shareholder.name,
              shareCount: Number(shareholder.share_count),
              order,
            })),
            annualBasis,
          });
        } catch (error) {
          basisBlocker = error instanceof Error ? error.message : "Årsgrunnlaget er utenfor støttet løype.";
        }
      }
      body = (
        <OwnerDividendWizard
          companyId={companyId}
          incomeYear={incomeYear}
          shareholders={decisionShareholders.map((shareholder) => ({
            id: shareholder.id,
            name: shareholder.name,
            share_count: shareholder.share_count,
          }))}
          annualBasis={annualBasis}
          reviewedFacts={reviewedFacts}
          featureEnabled={corporateDocumentsEnabled}
          basisBlocker={basisBlocker}
          draftIds={{
            decisionId: randomUUID(),
            documentSetId: randomUUID(),
            dividendBoardArtifactId: randomUUID(),
            dividendBoardDocumentId: randomUUID(),
            dividendGeneralMeetingArtifactId: randomUUID(),
            dividendGeneralMeetingDocumentId: randomUUID(),
          }}
        />
      );
      break;
    case "shareholder-loan":
      body = (
        <ShareholderLoanWizard
          companyId={companyId}
          incomeYear={incomeYear}
          operationId={query?.shareholderLoanOperationId}
        />
      );
      break;
    case "tax-settlement":
      body = (
        <TaxSettlementWizard
          companyId={companyId}
          incomeYear={incomeYear}
          operationId={query?.taxSettlementOperationId}
        />
      );
      break;
  }

  return (
    <WizardShell
      title={head.title}
      intro={head.intro}
      back={
        <LinkButton variant="ghost" href="/actions">
          {a.backToHub}
        </LinkButton>
      }
    >
      {query?.error ? <Banner variant="danger">{query.error}</Banner> : null}
      {body}
    </WizardShell>
  );
}

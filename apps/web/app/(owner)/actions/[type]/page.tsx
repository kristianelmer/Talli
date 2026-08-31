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
import { OwnerDividendWizard } from "../_components/OwnerDividendWizard";
import { SharePurchaseWizard } from "../_components/SharePurchaseWizard";
import { ShareSaleWizard } from "../_components/ShareSaleWizard";
import { ShareholderLoanWizard } from "../_components/ShareholderLoanWizard";
import { TaxSettlementWizard } from "../_components/TaxSettlementWizard";

type ActionSlug =
  | "share-purchase"
  | "share-sale"
  | "dividend-received"
  | "owner-dividend"
  | "shareholder-loan"
  | "tax-settlement";

const COPY_KEY: Record<ActionSlug, keyof typeof ownerCopy.actions> = {
  "share-purchase": "sharePurchase",
  "share-sale": "shareSale",
  "dividend-received": "dividendReceived",
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
          investments={companyPositions.map((position) => ({
            id: position.id,
            name: position.name,
          }))}
        />
      );
      break;
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

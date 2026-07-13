import { notFound } from "next/navigation";

import { Banner, EmptyState, LinkButton, WizardShell } from "../../../components/ui";
import { ownerCopy } from "../../../lib/copy";
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
  searchParams?: Promise<{ error?: string }>;
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
    investmentLots,
    primaryShareholders,
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

  let body: React.ReactNode;
  switch (type) {
    case "share-purchase":
      body = <SharePurchaseWizard companyId={companyId} incomeYear={incomeYear} />;
      break;
    case "share-sale":
      body = (
        <ShareSaleWizard
          companyId={companyId}
          incomeYear={incomeYear}
          positions={companyPositions.map((position) => ({
            id: position.id,
            investment_key: position.investment_key,
            name: position.name,
            share_count: position.share_count,
            cost_basis: position.cost_basis,
            lot_history_status: position.lot_history_status,
            acquisition_lots: investmentLots
              .filter((lot) => lot.position_id === position.id && lot.remaining_share_count > 0)
              .map((lot) => ({
                id: lot.id,
                acquisitionDate: lot.acquisition_date,
                remainingShareCount: lot.remaining_share_count,
                remainingCostBasis: lot.remaining_cost_basis,
              })),
          }))}
        />
      );
      break;
    case "dividend-received":
      body = (
        <DividendReceivedWizard
          companyId={companyId}
          incomeYear={incomeYear}
          investments={companyPositions.map((position) => ({
            investment_key: position.investment_key,
            name: position.name,
          }))}
        />
      );
      break;
    case "owner-dividend":
      body = (
        <OwnerDividendWizard
          companyId={companyId}
          incomeYear={incomeYear}
          shareholders={primaryShareholders.map((shareholder) => ({
            id: shareholder.id,
            name: shareholder.name,
            share_count: shareholder.share_count,
          }))}
        />
      );
      break;
    case "shareholder-loan":
      body = (
        <ShareholderLoanWizard companyId={companyId} incomeYear={incomeYear} />
      );
      break;
    case "tax-settlement":
      body = <TaxSettlementWizard companyId={companyId} incomeYear={incomeYear} />;
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

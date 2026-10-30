import { loadPresentedAnnualAccountsSource } from "./annual-accounts-workspace-source.ts";
import { loadPresentedCompanyTaxSource } from "./company-tax-workspace-source.ts";
import { loadPresentedRf1086Source, newestFirst, composeFilingSources } from "./rf1086-workspace-source";
import { cache } from "react";
import { notFound, redirect } from "next/navigation.js";
import { TalliApiError } from "@talli/talli-api-client";
import { BackendFetchError, BackendTransportError } from "../../lib/protected-backend-fetch.ts";

import { buildAnnualWorkspaceViewModel, type AnnualWorkspaceContext } from "./annual-workspace.ts";
import { scopeAnnualWorkspaceRecords } from "./annual-workspace-scope.ts";
import { buildDeadlineDashboard } from "./deadlines.ts";
import {
  listAnnualData,
  listBankTransactions,
  listDocumentsForCompanies,
  listFilingReadinessSnapshots,
  listLedgerEntries,
  listOpeningSetups,
  listPeriodLocks,
} from "./supabase/server.ts";
import { listCompanyAccessContexts } from "./company-access-context.ts";
import {
  effectiveInvestmentActivity,
  listPresentedInvestmentActivity,
  listPresentedInvestmentCorrections,
  listPresentedInvestmentPositions,
} from "../../features/investments";
import { getCurrentSessionAccessToken } from "./supabase/auth-session.ts";
import { loadBillingEntitlement } from "../../features/billing";
import { loadTaxDeliveryWorkspace } from "../../features/company-tax-filing";
import { loadAccountsDeliveryWorkspace } from "../../features/annual-accounts-filing";
import { readAnnualDeliverySummary } from "./annual-delivery-summary.ts";

class AnnualWorkspaceUnavailable extends Error {}

const annualWorkspaceDeadlineMs = 12_000;

function recoverAccess(error: unknown, context: AnnualWorkspaceContext) {
  if (!(error instanceof TalliApiError)) return;
  const next = encodeURIComponent(`/companies/${context.companyId}/annual-reporting/${context.incomeYear}`);
  if (error.status === 401) redirect(`/login?reauth=1&next=${next}`);
  if (error.status === 403 && /(?:AAL2_REQUIRED|STEP_UP_REQUIRED)$/u.test(error.problem?.code ?? "")) {
    redirect(`/mfa?fresh=1&next=${next}`);
  }
  if (error.status === 403 || error.status === 404) notFound();
}

export const loadAnnualWorkspace = cache(async (context: AnnualWorkspaceContext) => {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu.test(context.companyId)
      || !Number.isInteger(context.incomeYear) || context.incomeYear < 2000 || context.incomeYear > 2100) notFound();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new AbortController();
  try {
    // One display deadline, no automatic retries. Underlying reads retain their
    // transport deadlines; late results are discarded, never published as facts.
    return await Promise.race([
      readAnnualWorkspace(context, deadline.signal),
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => {
          deadline.abort();
          reject(new AnnualWorkspaceUnavailable("deadline"));
        }, annualWorkspaceDeadlineMs);
      }),
    ]);
  } catch (error) {
    recoverAccess(error, context);
    if (error instanceof AnnualWorkspaceUnavailable
        || error instanceof TalliApiError && (error.status >= 500 || [408, 429].includes(error.status))
        || error instanceof BackendFetchError
        || error instanceof BackendTransportError && ["BACKEND_REQUEST_ABORTED", "BACKEND_OIDC_TOKEN_UNAVAILABLE"].includes(error.code)
        || error instanceof Error && ["TimeoutError", "AbortError", "AuthRetryableFetchError"].includes(error.name)
        || error instanceof TypeError && error.message === "fetch failed") {
      return { status: "unavailable" as const, context };
    }
    throw error;
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
});

async function readAnnualWorkspace(context: AnnualWorkspaceContext, deadline: AbortSignal) {
  const next = encodeURIComponent(`/companies/${context.companyId}/annual-reporting/${context.incomeYear}`);
  // A cookie token is not authorization. The scoped backend context below
  // independently verifies Auth, membership and the requested company-year.
  const accessToken = await getCurrentSessionAccessToken();
  if (deadline.aborted) throw new AnnualWorkspaceUnavailable("deadline");
  if (!accessToken) redirect(`/login?reauth=1&next=${next}`);

  const access = await listCompanyAccessContexts({ companyId: context.companyId, accountingYear: context.incomeYear });
  if (deadline.aborted) throw new AnnualWorkspaceUnavailable("deadline");
  if (access.requiresSignIn) redirect(`/login?reauth=1&next=${next}`);
  if (access.requiresAal2) redirect(`/mfa?fresh=1&next=${next}`);
  if (access.accessDenied) notFound();
  const { companies, error: companyError } = access;
  if (companyError) throw new AnnualWorkspaceUnavailable("company_access");
  const company = companies.find((item) => item.id === context.companyId);
  if (!company) notFound();

  if (!company.currentAgreementAccepted) {
    redirect(company.role === "owner" ? "/dashboard" : "/dashboard?agreement=required");
  }

  const companyIds = [company.id];
  const [
    documentsResult,
    openingResult,
    locksResult,
    annualDataResult,
    transactionsResult,
    actionsResult,
    correctionsResult,
    positionsResult,
    entriesResult,
    snapshotsResult,
    billingEntitlement,
    rfSource,
    taxSource,
    accountsSource,
    taxDelivery,
    accountsDelivery,
  ] = await Promise.all([
    listDocumentsForCompanies(companyIds),
    listOpeningSetups(companyIds),
    listPeriodLocks(companyIds),
    listAnnualData(companyIds),
    listBankTransactions(companyIds),
    listPresentedInvestmentActivity(accessToken, companyIds),
    listPresentedInvestmentCorrections(accessToken, companyIds),
    listPresentedInvestmentPositions(accessToken, companyIds),
    listLedgerEntries(companyIds),
    listFilingReadinessSnapshots(companyIds),
    loadBillingEntitlement(accessToken, {
      companyId: context.companyId,
      incomeYear: context.incomeYear,
      obligation: "aksjonaerregisteroppgaven",
      caseProfile: "rf1086_no_activity_v1",
    }),
    loadPresentedRf1086Source(accessToken, companyIds, context.incomeYear),
    loadPresentedCompanyTaxSource(accessToken, companyIds, context.incomeYear),
    loadPresentedAnnualAccountsSource(accessToken, companyIds, context.incomeYear),
    readAnnualDeliverySummary(context.incomeYear, () => loadTaxDeliveryWorkspace(accessToken, company.id, context.incomeYear)),
    readAnnualDeliverySummary(context.incomeYear, () => loadAccountsDeliveryWorkspace(accessToken, company.id, context.incomeYear)),
  ]);
  if (deadline.aborted) throw new AnnualWorkspaceUnavailable("deadline");

  const failedSources = [
    ["rf1086", rfSource.error],
    ["company-tax", taxSource.error],
    ["annual-accounts", accountsSource.error],
    ["documents", documentsResult.error],
    ["opening", openingResult.error],
    ["locks", locksResult.error],
    ["annual_data", annualDataResult.error],
    ["transactions", transactionsResult.error],
    ["actions", actionsResult.error],
    ["corrections", correctionsResult.error],
    ["positions", positionsResult.error],
    ["entries", entriesResult.error],
    ["snapshots", snapshotsResult.error],
  ].filter((entry) => entry[1]);
  if (failedSources.length) {
    console.error("annual_workspace_load_failed", { sources: failedSources.map(([source]) => source) });
    throw new AnnualWorkspaceUnavailable("sources");
  }

  const records = scopeAnnualWorkspaceRecords(context, {
    documents: documentsResult.documents,
    setups: openingResult.setups,
    shareholders: openingResult.shareholders,
    locks: locksResult.locks,
    annualData: annualDataResult.annualData,
    previews: newestFirst(composeFilingSources(composeFilingSources(accountsSource.previews, rfSource.previews), taxSource.previews), (row) => row.created_at),
    submissions: newestFirst(composeFilingSources(composeFilingSources(accountsSource.submissions, rfSource.submissions), taxSource.submissions), (row) => row.updated_at),
    overrides: newestFirst(composeFilingSources(composeFilingSources(accountsSource.overrides, rfSource.overrides), taxSource.overrides), (row) => row.created_at),
    transactions: transactionsResult.transactions,
    actions: effectiveInvestmentActivity(
      actionsResult.actions,
      correctionsResult.corrections,
    ),
    positions: positionsResult.positions,
    entries: entriesResult.entries,
    snapshots: snapshotsResult.readinessSnapshots,
    comments: newestFirst(composeFilingSources(composeFilingSources(accountsSource.comments, rfSource.comments), taxSource.comments), (row) => row.created_at),
    authorityPermissions: newestFirst(composeFilingSources(composeFilingSources(accountsSource.authorityPermissions, rfSource.authorityPermissions), taxSource.authorityPermissions), (row) => row.updated_at),
  });
  const deadlines = buildDeadlineDashboard({ incomeYear: context.incomeYear, submissions: records.submissions });
  const model = buildAnnualWorkspaceViewModel({
    context,
    company,
    role: company.role ?? "read_only",
    snapshots: records.snapshots,
    deadlines,
    documents: records.documents,
    comments: records.comments,
    submissions: records.submissions,
    deliverySummaries: { skattemelding: taxDelivery, aarsregnskap: accountsDelivery },
    previews: records.previews,
  });

  return { status: "ready" as const, model, records, deadlines, billingEntitlement };
}

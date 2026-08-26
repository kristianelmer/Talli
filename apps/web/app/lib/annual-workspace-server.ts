import { cache } from "react";
import { notFound, redirect } from "next/navigation.js";

import { buildAnnualWorkspaceViewModel, type AnnualWorkspaceContext } from "./annual-workspace.ts";
import { scopeAnnualWorkspaceRecords } from "./annual-workspace-scope.ts";
import { buildDeadlineDashboard } from "./deadlines.ts";
import {
  getCurrentUser,
  listAnnualData,
  listAuthorityPermissions,
  listBankTransactions,
  listBillingAccounts,
  listDocumentsForCompanies,
  listFilingOverrides,
  listFilingPreviews,
  listFilingReadinessSnapshots,
  listFilingReviewComments,
  listFilingSubmissions,
  listHoldingActions,
  listInvestmentPositions,
  listLedgerEntries,
  listOpeningSetups,
  listPeriodLocks,
} from "./supabase/server.ts";
import { listCompanyAccessContexts } from "./company-access-context.ts";

export const loadAnnualWorkspace = cache(async (context: AnnualWorkspaceContext) => {
  if (!Number.isInteger(context.incomeYear) || context.incomeYear < 2000 || context.incomeYear > 2100) notFound();

  const user = await getCurrentUser();
  if (!user) redirect("/?error=Innlogging%20kreves");

  const { companies, error: companyError } = await listCompanyAccessContexts({ companyId: context.companyId });
  if (companyError) throw new Error("Kunne ikke laste selskapsarbeidsflaten.");
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
    previewsResult,
    submissionsResult,
    overridesResult,
    transactionsResult,
    actionsResult,
    positionsResult,
    entriesResult,
    snapshotsResult,
    commentsResult,
    billingResult,
    authorityResult,
  ] = await Promise.all([
    listDocumentsForCompanies(companyIds),
    listOpeningSetups(companyIds),
    listPeriodLocks(companyIds),
    listAnnualData(companyIds),
    listFilingPreviews(companyIds),
    listFilingSubmissions(companyIds),
    listFilingOverrides(companyIds),
    listBankTransactions(companyIds),
    listHoldingActions(companyIds),
    listInvestmentPositions(companyIds),
    listLedgerEntries(companyIds),
    listFilingReadinessSnapshots(companyIds),
    listFilingReviewComments(companyIds),
    listBillingAccounts(companyIds),
    listAuthorityPermissions(companyIds),
  ]);

  const failedSources = [
    ["documents", documentsResult.error],
    ["opening", openingResult.error],
    ["locks", locksResult.error],
    ["annual_data", annualDataResult.error],
    ["previews", previewsResult.error],
    ["submissions", submissionsResult.error],
    ["overrides", overridesResult.error],
    ["transactions", transactionsResult.error],
    ["actions", actionsResult.error],
    ["positions", positionsResult.error],
    ["entries", entriesResult.error],
    ["snapshots", snapshotsResult.error],
    ["comments", commentsResult.error],
    ["billing", billingResult.error],
    ["authority", authorityResult.error],
  ].filter((entry) => entry[1]);
  if (failedSources.length) {
    console.error("annual_workspace_load_failed", { sources: failedSources.map(([source]) => source) });
    throw new Error("Kunne ikke laste årsrapporteringen. Prøv igjen.");
  }

  const records = scopeAnnualWorkspaceRecords(context, {
    documents: documentsResult.documents,
    setups: openingResult.setups,
    shareholders: openingResult.shareholders,
    locks: locksResult.locks,
    annualData: annualDataResult.annualData,
    previews: previewsResult.previews,
    submissions: submissionsResult.submissions,
    overrides: overridesResult.overrides,
    transactions: transactionsResult.transactions,
    actions: actionsResult.actions,
    positions: positionsResult.positions,
    entries: entriesResult.entries,
    snapshots: snapshotsResult.readinessSnapshots,
    comments: commentsResult.comments,
    billingAccounts: billingResult.billingAccounts,
    authorityPermissions: authorityResult.authorityPermissions,
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
  });

  return { model, records, deadlines };
});

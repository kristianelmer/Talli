import { loadPresentedRf1086Source, newestFirst, composeFilingSources } from "./rf1086-workspace-source";
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
  listDocumentsForCompanies,
  listFilingOverrides,
  listFilingPreviews,
  listFilingReadinessSnapshots,
  listFilingReviewComments,
  listFilingSubmissions,
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

export const loadAnnualWorkspace = cache(async (context: AnnualWorkspaceContext) => {
  if (!Number.isInteger(context.incomeYear) || context.incomeYear < 2000 || context.incomeYear > 2100) notFound();

  const user = await getCurrentUser();
  if (!user) redirect("/?error=Innlogging%20kreves");
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) redirect("/?error=Innlogging%20kreves");

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
    correctionsResult,
    positionsResult,
    entriesResult,
    snapshotsResult,
    commentsResult,
    billingEntitlement,
    authorityResult,
    rfSource,
  ] = await Promise.all([
    listDocumentsForCompanies(companyIds),
    listOpeningSetups(companyIds),
    listPeriodLocks(companyIds),
    listAnnualData(companyIds),
    listFilingPreviews(companyIds),
    listFilingSubmissions(companyIds),
    listFilingOverrides(companyIds),
    listBankTransactions(companyIds),
    listPresentedInvestmentActivity(accessToken, companyIds),
    listPresentedInvestmentCorrections(accessToken, companyIds),
    listPresentedInvestmentPositions(accessToken, companyIds),
    listLedgerEntries(companyIds),
    listFilingReadinessSnapshots(companyIds),
    listFilingReviewComments(companyIds),
    loadBillingEntitlement(accessToken, {
      companyId: context.companyId,
      incomeYear: context.incomeYear,
      obligation: "aksjonaerregisteroppgaven",
      caseProfile: "rf1086_no_activity_v1",
    }),
    listAuthorityPermissions(companyIds),
    loadPresentedRf1086Source(accessToken, companyIds, context.incomeYear),
  ]);

  const failedSources = [
    ["rf1086", rfSource.error],
    ["documents", documentsResult.error],
    ["opening", openingResult.error],
    ["locks", locksResult.error],
    ["annual_data", annualDataResult.error],
    ["previews", previewsResult.error],
    ["submissions", submissionsResult.error],
    ["overrides", overridesResult.error],
    ["transactions", transactionsResult.error],
    ["actions", actionsResult.error],
    ["corrections", correctionsResult.error],
    ["positions", positionsResult.error],
    ["entries", entriesResult.error],
    ["snapshots", snapshotsResult.error],
    ["comments", commentsResult.error],
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
    previews: newestFirst(composeFilingSources(previewsResult.previews, rfSource.previews), (row) => row.created_at),
    submissions: newestFirst(composeFilingSources(submissionsResult.submissions, rfSource.submissions), (row) => row.updated_at),
    overrides: newestFirst(composeFilingSources(overridesResult.overrides, rfSource.overrides), (row) => row.created_at),
    transactions: transactionsResult.transactions,
    actions: effectiveInvestmentActivity(
      actionsResult.actions,
      correctionsResult.corrections,
    ),
    positions: positionsResult.positions,
    entries: entriesResult.entries,
    snapshots: snapshotsResult.readinessSnapshots,
    comments: newestFirst(composeFilingSources(commentsResult.comments, rfSource.comments), (row) => row.created_at),
    authorityPermissions: newestFirst(composeFilingSources(authorityResult.authorityPermissions, rfSource.authorityPermissions), (row) => row.updated_at),
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

  return { model, records, deadlines, billingEntitlement };
});
